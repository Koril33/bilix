"""One CLI for console scripts, python -m and the Windows executable."""

import json
import os
import signal
import sys
import threading
from datetime import datetime
from difflib import get_close_matches
from enum import StrEnum
from functools import wraps
from pathlib import Path
from typing import Annotated

import typer

from . import __version__, auth
from .bilibili.client import BilibiliClient
from .completion import (
    COMPLETE_VAR,
    Shell,
    complete_directory,
    complete_file,
    complete_page,
    complete_quality,
    prepare_powershell_input,
    shell_script,
)
from .config import load_settings
from .errors import BilixError, InputError, OperationCancelled
from .media import FFmpeg, find_ffmpeg
from .operations import CancellationToken
from .planner import parse_quality
from .presentation import console, download_progress, error_console, show_info
from .tasks import DownloadOptions, JobSpec, Session, run_batch, run_preview, summary_text
from .urls import load_urls, normalize_url, parse_pages

app = typer.Typer(
    no_args_is_help=True,
    pretty_exceptions_enable=False,
    help="BiliX · Bilibili 视频下载器",
    rich_markup_mode="rich",
    suggest_commands=True,
    epilog="快速开始：blx info BV1j4411W7F7；blx download BV1j4411W7F7 --dry-run；"
    "blx auth login。\n"
    "Tab 补全：blx completion SHELL，支持 bash/zsh/fish/powershell/pwsh。",
    context_settings={"help_option_names": ["--help", "-h"]},
)
auth_app = typer.Typer(
    no_args_is_help=True,
    pretty_exceptions_enable=False,
    help="管理扫码登录与本地凭据",
    suggest_commands=True,
    context_settings={"help_option_names": ["--help", "-h"]},
)
app.add_typer(auth_app, name="auth")


class Codec(StrEnum):
    auto = "auto"
    avc = "AVC"
    hevc = "HEVC"
    av1 = "AV1"


class Audio(StrEnum):
    aac = "aac"
    flac = "flac"
    dolby = "dolby"
    best = "best"


class OutputMode(StrEnum):
    merged = "merged"
    audio = "audio"
    video = "video"
    separate = "separate"
    cover = "cover"


def guarded(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except OperationCancelled:
            error_console.print("已取消", markup=False)
            raise typer.Exit(130) from None
        except BilixError as error:
            error_console.print(f"错误：{error}", markup=False)
            raise typer.Exit(1) from None
        except OSError:
            error_console.print("错误：文件或目录无法访问，请检查路径和权限", markup=False)
            raise typer.Exit(1) from None
        except (typer.Exit, typer.BadParameter):
            raise
        except KeyboardInterrupt:
            error_console.print("已取消", markup=False)
            raise typer.Exit(130) from None
        except Exception:
            error_console.print(
                "错误：操作失败，请检查网络及参数；可用 blx doctor 检查环境", markup=False
            )
            raise typer.Exit(1) from None

    return wrapper


def version_callback(value: bool):
    if value:
        typer.echo(f"BiliX {__version__}")
        raise typer.Exit()


@app.callback()
def root(
    version: Annotated[
        bool,
        typer.Option("--version", "-v", callback=version_callback, is_eager=True, help="显示版本"),
    ] = False,
):
    pass


@app.command("completion", help="生成 Tab 补全脚本；按终端类型选择 SHELL")
def completion_command(ctx: typer.Context, shell: Shell):
    name = ctx.find_root().info_name or "blx"
    # A shell registers executables, rather than the multi-word module invocation.
    if " -m " in name:
        name = "blx"
    if shell in (Shell.powershell, Shell.pwsh) and os.name == "nt":
        launcher = Path(sys.argv[0])
        # Python console-script launchers strip the .exe suffix from argv[0].
        if launcher.suffix.lower() != ".exe":
            launcher = Path(str(launcher) + ".exe")
        if launcher.is_file():
            name = str(launcher.resolve())
    typer.echo(shell_script(name, shell))


def sources(urls: list[str] | None, file: Path | None) -> list[str]:
    result = list(urls or []) + (load_urls(file) if file else [])
    if not result:
        raise InputError("请提供至少一个视频 URL/BV 号，或使用 --file 指定文本文件")
    return result


def run_info(urls: list[str] | None, file: Path | None, json_output: bool):
    client = BilibiliClient(load_settings())
    records = []
    failures = 0
    for index, url in enumerate(sources(urls, file), 1):
        try:
            info = client.fetch(normalize_url(url))
            if json_output:
                records.append({"ok": True, **info.public_dict()})
            else:
                show_info(info)
        except BilixError as error:
            failures += 1
            if json_output:
                records.append({"ok": False, "input_index": index, "error": str(error)})
            else:
                error_console.print(f"第 {index} 个地址失败：{error}", markup=False)
    if json_output:
        typer.echo(json.dumps(records, ensure_ascii=False, indent=2))
    if failures:
        raise typer.Exit(1)


@app.command("info", help="查看视频信息、可获取的编码及选集")
@guarded
def info_command(
    urls: Annotated[list[str] | None, typer.Argument(help="视频 URL 或 BV 号")] = None,
    file: Annotated[
        Path | None,
        typer.Option(
            "--file",
            "-o",
            rich_help_panel="输入与保存",
            help="UTF-8 URL 列表",
            autocompletion=complete_file,
        ),
    ] = None,
    json_output: Annotated[bool, typer.Option("--json", help="输出 JSON，便于脚本处理")] = False,
):
    run_info(urls, file, json_output)


@app.command(
    "download",
    help="下载视频；默认遵循链接 ?p=，无 ?p= 时选全部 P，已有文件跳过",
    epilog="示例：blx download BV1j4411W7F7 --dry-run\n"
    "blx download BV1j4411W7F7 -p 1,3-5 -q 1080p --save ./下载\n"
    "blx download --file urls.txt --quiet\n覆盖使用 --overwrite；-o 仍表示输入文件。",
)
@app.command("video", hidden=True)
@guarded
def download_command(
    urls: Annotated[list[str] | None, typer.Argument(help="一个或多个 URL/BV 号")] = None,
    quality: Annotated[
        str,
        typer.Option(
            "--quality",
            "-q",
            rich_help_panel="媒体与选集",
            help="auto / 1080p+ / 1080p60 / 4k / HDR / 8k / id",
            autocompletion=complete_quality,
        ),
    ] = "auto",
    codec: Annotated[
        Codec,
        typer.Option(
            "--codec",
            rich_help_panel="媒体与选集",
            case_sensitive=False,
            help="视频编码；auto 按清晰度选择",
        ),
    ] = Codec.auto,
    audio: Annotated[
        Audio,
        typer.Option(
            "--audio",
            rich_help_panel="媒体与选集",
            case_sensitive=False,
            help="AAC / FLAC 无损 / Dolby / best",
        ),
    ] = Audio.aac,
    save: Annotated[
        Path | None,
        typer.Option(
            "--save",
            "-s",
            rich_help_panel="输入与保存",
            help="保存目录",
            autocompletion=complete_directory,
        ),
    ] = None,
    page: Annotated[
        str | None,
        typer.Option(
            "--page",
            "-p",
            rich_help_panel="媒体与选集",
            help="all / 1 / 1,3,5-7",
            autocompletion=complete_page,
        ),
    ] = None,
    file: Annotated[
        Path | None,
        typer.Option(
            "--file", "--origin", "-o", help="UTF-8 URL 列表", autocompletion=complete_file
        ),
    ] = None,
    overwrite: Annotated[
        bool,
        typer.Option("--overwrite", rich_help_panel="执行与安全", help="验证成功后替换已有文件"),
    ] = False,
    strict: Annotated[
        bool,
        typer.Option(
            "--strict", rich_help_panel="执行与安全", help="指定清晰度/编码不可用时直接失败"
        ),
    ] = False,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", rich_help_panel="执行与安全", help="显示计划，不下载媒体")
    ] = False,
    ffmpeg: Annotated[
        str | None,
        typer.Option(
            "--ffmpeg",
            rich_help_panel="执行与安全",
            help="FFmpeg 路径",
            autocompletion=complete_file,
        ),
    ] = None,
    quiet: Annotated[
        bool,
        typer.Option("--quiet", rich_help_panel="执行与安全", help="隐藏进度和计划，仅显示结果"),
    ] = False,
    info: Annotated[bool, typer.Option("--info", "-i", help="兼容旧版：仅查看视频信息")] = False,
    mode: Annotated[
        OutputMode,
        typer.Option(
            "--mode",
            rich_help_panel="媒体与选集",
            help="merged 完整视频 / audio 音频 / video 无声视频 / separate 分别保存 / cover 封面",
        ),
    ] = OutputMode.merged,
    cover: Annotated[
        bool,
        typer.Option(
            "--cover", rich_help_panel="媒体与选集", help="同时保存封面，普通多 P 每来源一张"
        ),
    ] = False,
):
    if info:
        run_info(urls, file, False)
        return
    quality_id = parse_quality(quality)
    parse_pages(page)
    settings = load_settings()
    specs = tuple(JobSpec(url, page) for url in sources(urls, file))
    options = DownloadOptions(
        quality_id,
        None if codec == Codec.auto else codec.value,
        audio.value,
        save or settings.download_dir,
        strict,
        overwrite,
        ffmpeg or settings.ffmpeg,
        dry_run,
        naming_template=settings.naming_template,
        proxy=settings.proxy,
        concurrency=settings.concurrency,
        mode=mode.value,
        cover=cover,
    )
    cancel = CancellationToken()
    previous_handlers = {}
    if threading.current_thread() is threading.main_thread():
        interrupts = [signal.SIGINT]
        if os.name == "nt":
            interrupts.append(signal.SIGBREAK)
        for interrupt in interrupts:
            previous_handlers[interrupt] = signal.signal(interrupt, lambda *_: cancel.cancel())
    labels = {"new": "新建", "skip": "跳过（已存在，未校验）", "replace": "替换", "blocked": "阻塞"}
    try:
        with download_progress(quiet or dry_run) as progress:

            def emit(event):
                kind = event["type"]
                if kind == "progress":
                    if progress and event.get("samples"):
                        progress.feedback(event["samples"], event["attempt"].attempt_id)
                    elif progress:
                        for stream, (done, total) in event["streams"].items():
                            progress(stream, done, total)
                elif kind in {"plan", "preview"}:
                    for warning in event.get("warnings", ()):
                        error_console.print(f"提示：{warning}", markup=False)
                    if event.get("duplicate"):
                        error_console.print(
                            "提示：本批次存在重复输出路径，将逐项重新检查", markup=False
                        )
                    if not quiet and event.get("output"):
                        console.print(
                            f"{event.get('title', '')} · {event['selection']}", markup=False
                        )
                        console.print(
                            f"→ {event['output']} · {labels[event['conflict']]}",
                            markup=False,
                            soft_wrap=True,
                        )
                    if event.get("detail"):
                        error_console.print(
                            f"失败：{event['detail']}；{event.get('action', '')}", markup=False
                        )
                elif kind == "source" and event["request"].state == "failed":
                    source = event["request"]
                    error_console.print(
                        f"来源读取失败：{source.spec.source}：{source.detail}；{source.action}",
                        markup=False,
                    )
                elif kind == "task":
                    attempt = event["attempt"]
                    if attempt.state == "failed":
                        error_console.print(
                            f"失败：{event['task'].label}（{event['task'].target_url}）："
                            f"{attempt.detail}；{attempt.action}",
                            markup=False,
                            soft_wrap=True,
                        )
                    elif attempt.state in {"completed", "skipped"}:
                        if attempt.state == "skipped":
                            console.print("已有文件未校验", markup=False)
                        prefix = "跳过已有文件" if attempt.state == "skipped" else "完成"
                        console.print(
                            f"{prefix}：{attempt.output}",
                            markup=False,
                            soft_wrap=True,
                        )

            if dry_run:
                counts = run_preview(specs, options, emit, cancel)
            else:
                session = Session()
                counts = run_batch(session, session.begin(specs, options), emit, cancel)
    finally:
        for interrupt, handler in previous_handlers.items():
            signal.signal(interrupt, handler)
    console.print(summary_text(counts), markup=False, soft_wrap=True)
    if cancel.cancelled():
        raise typer.Exit(130)
    if counts["failed"] or counts["source_failed"]:
        raise typer.Exit(1)


@auth_app.command("login", help="生成二维码并等待手机确认登录")
@guarded
def login_command():
    auth.login(load_settings(), lambda message: console.print(message, markup=False))


@auth_app.command("status", help="查看登录状态")
@guarded
def status_command(
    json_output: Annotated[
        bool, typer.Option("--json", help="输出登录状态 JSON，不含凭据")
    ] = False,
):
    result = auth.status(BilibiliClient(load_settings()))
    if json_output:
        typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if not result["logged_in"]:
        console.print(
            "登录已失效，请使用 blx auth login 重新扫码"
            if result.get("expired")
            else "未登录，可使用 blx auth login 扫码登录"
        )
        return
    membership = "年度大会员" if result.get("vip_type") == 2 else "大会员"
    membership = membership if result["vip"] else "普通账号"
    if result["vip"] and result.get("vip_expires_at"):
        membership += (
            "（到期 "
            + datetime.fromtimestamp(result["vip_expires_at"] / 1000).strftime("%Y-%m-%d")
            + "）"
        )
    console.print(
        f"已登录：{result['name']} · UID {result['uid']} · 等级 {result['level']} · {membership}",
        markup=False,
    )


@auth_app.command("logout", help="删除本地登录凭据")
@guarded
def logout_command():
    auth.logout(load_settings())
    console.print("本地登录凭据已删除")


@app.command("config", help="查看配置位置与当前设置")
@guarded
def config_command():
    settings = load_settings()
    console.print(
        f"配置：{settings.config_file}\n文件下载目录：{settings.file_download_dir or '未设置'}\n"
        f"生效下载目录：{settings.download_dir}（{settings.download_source}）\n"
        f"文件 FFmpeg：{settings.file_ffmpeg or '未设置'}\n"
        f"生效 FFmpeg：{settings.ffmpeg or '自动查找'}（{settings.ffmpeg_source}；"
        "请用 doctor 验证可运行性）",
        markup=False,
    )


@app.command("doctor", help="检查版本、配置和 FFmpeg；不会访问网络")
@guarded
def doctor_command():
    settings = load_settings()
    path = find_ffmpeg(settings.ffmpeg)
    console.print(
        f"BiliX {__version__}\nPython {sys.version.split()[0]}\nFFmpeg：{path}\n"
        f"{FFmpeg(path).version()}\n配置目录：{settings.config_dir}",
        markup=False,
    )


@app.command("user", hidden=True)
@guarded
def legacy_user(
    login: Annotated[bool, typer.Option("--login", "-l")] = False,
    logout: Annotated[bool, typer.Option("--logout")] = False,
    info: Annotated[bool, typer.Option("--info", "-i")] = False,
):
    if login and logout:
        raise InputError("--login 和 --logout 不能同时使用")
    if login:
        login_command()
    elif logout:
        logout_command()
    else:
        status_command(False)


def main():
    # Isolated Windows executables may start with a legacy ANSI output encoding.
    # Configure the actual streams before Typer/Rich render Chinese help or paths.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, TypeError, ValueError):
                # Capture streams and embedded callers may not support reconfiguration.
                pass
    arguments = sys.argv[1:]
    if os.environ.get(COMPLETE_VAR):
        if prepare_powershell_input():
            app(args=[], complete_var=COMPLETE_VAR)
        return
    root_options = ("--help", "-h", "--version", "-v", "--install-completion", "--show-completion")
    if arguments and arguments[0] not in root_options:
        account_flags = {
            "--login": "login",
            "-l": "login",
            "--logout": "logout",
            "--user": "status",
            "-u": "status",
        }
        if arguments[0] in account_flags:
            arguments = ["auth", account_flags[arguments[0]], *arguments[1:]]
        elif arguments[0].strip().lower().startswith(("http://", "https://", "bv")) or (
            arguments[0].startswith("-")
            and not get_close_matches(arguments[0], root_options, cutoff=0.75)
        ):
            arguments = ["download", *arguments]
    app(args=arguments)
