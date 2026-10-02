"""One CLI for console scripts, python -m and the Windows executable."""

import json
import sys
from datetime import datetime
from enum import StrEnum
from functools import wraps
from pathlib import Path
from typing import Annotated

import typer

from . import __version__, auth
from .bilibili.client import BilibiliClient
from .config import load_settings
from .errors import BilixError, InputError
from .media import FFmpeg, find_ffmpeg
from .models import CODECS, QUALITY_NAMES
from .planner import build_plan, parse_quality
from .presentation import console, download_progress, error_console, show_info
from .service import discover, execute
from .urls import load_urls, normalize_url, parse_pages

app = typer.Typer(
    no_args_is_help=True,
    pretty_exceptions_enable=False,
    help="BiliX · Bilibili 视频下载器",
    rich_markup_mode="rich",
    context_settings={"help_option_names": ["--help", "-h"]},
)
auth_app = typer.Typer(
    no_args_is_help=True,
    pretty_exceptions_enable=False,
    help="管理扫码登录与本地凭据",
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


def guarded(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        try:
            return function(*args, **kwargs)
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
    file: Annotated[Path | None, typer.Option("--file", "-o", help="UTF-8 URL 列表")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="输出 JSON，便于脚本处理")] = False,
):
    run_info(urls, file, json_output)


@app.command("download", help="下载视频；默认选全部 P，已有文件默认跳过")
@app.command("video", hidden=True)
@guarded
def download_command(
    urls: Annotated[list[str] | None, typer.Argument(help="一个或多个 URL/BV 号")] = None,
    quality: Annotated[
        str, typer.Option("--quality", "-q", help="auto / 1080p+ / 1080p60 / 4k / HDR / 8k / id")
    ] = "auto",
    codec: Annotated[
        Codec, typer.Option("--codec", case_sensitive=False, help="视频编码；auto 按清晰度选择")
    ] = Codec.auto,
    audio: Annotated[
        Audio, typer.Option("--audio", case_sensitive=False, help="AAC / FLAC 无损 / Dolby / best")
    ] = Audio.aac,
    save: Annotated[Path | None, typer.Option("--save", "-s", help="保存目录")] = None,
    page: Annotated[str | None, typer.Option("--page", "-p", help="all / 1 / 1,3,5-7")] = None,
    file: Annotated[
        Path | None, typer.Option("--file", "--origin", "-o", help="UTF-8 URL 列表")
    ] = None,
    overwrite: Annotated[bool, typer.Option("--overwrite", help="验证成功后替换已有文件")] = False,
    strict: Annotated[
        bool, typer.Option("--strict", help="指定清晰度/编码不可用时直接失败")
    ] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="显示计划，不下载媒体")] = False,
    ffmpeg: Annotated[str | None, typer.Option("--ffmpeg", help="FFmpeg 路径")] = None,
    quiet: Annotated[bool, typer.Option("--quiet", help="隐藏进度和计划，仅显示结果")] = False,
    info: Annotated[bool, typer.Option("--info", "-i", help="兼容旧版：仅查看视频信息")] = False,
):
    if info:
        run_info(urls, file, False)
        return
    quality_id = parse_quality(quality)
    parse_pages(page)
    settings = load_settings()
    client = BilibiliClient(settings)
    completed = skipped = failed = planned = 0
    for index, url in enumerate(sources(urls, file), 1):
        try:
            targets = discover(client, normalize_url(url), page)
        except BilixError as error:
            failed += 1
            error_console.print(f"第 {index} 个地址失败：{error}", markup=False)
            continue
        for target in targets:
            try:
                video = target.cached_info or client.fetch(target.url)
                plan = build_plan(
                    video,
                    save or settings.download_dir,
                    quality_id,
                    None if codec == Codec.auto else codec.value,
                    strict,
                    audio.value,
                )
                for warning in plan.warnings:
                    error_console.print(f"提示：{warning}", markup=False)
                if not quiet:
                    console.print(
                        f"{video.title} · "
                        f"{QUALITY_NAMES.get(plan.video.quality, plan.video.quality)} / "
                        f"{CODECS.get(plan.video.codec, plan.video.codec)} / "
                        f"{plan.audio.audio_kind.upper()}",
                        markup=False,
                    )
                    console.print(f"→ {plan.output}", markup=False, soft_wrap=True)
                if dry_run:
                    planned += 1
                    continue
                with download_progress(quiet) as progress:
                    result = execute(plan, ffmpeg or settings.ffmpeg, overwrite, progress)
                if result.skipped:
                    skipped += 1
                    console.print(f"跳过已有文件：{result.output}", markup=False, soft_wrap=True)
                else:
                    completed += 1
                    console.print(f"完成：{result.output}", markup=False, soft_wrap=True)
            except BilixError as error:
                failed += 1
                error_console.print(f"失败：{error}", markup=False, soft_wrap=True)
    console.print(
        f"{'计划 ' + str(planned) + ' 项；' if dry_run else ''}"
        f"完成 {completed} · 跳过 {skipped} · 失败 {failed}",
        markup=False,
    )
    if failed:
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
        f"配置：{settings.config_file}\n下载目录：{settings.download_dir}\n"
        f"FFmpeg：{settings.ffmpeg or '自动查找'}",
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
    arguments = sys.argv[1:]
    commands = {"download", "video", "info", "auth", "user", "config", "doctor"}
    if (
        arguments
        and arguments[0] not in commands
        and arguments[0]
        not in (
            "--help",
            "-h",
            "--version",
            "-v",
            "--install-completion",
            "--show-completion",
        )
    ):
        account_flags = {
            "--login": "login",
            "-l": "login",
            "--logout": "logout",
            "--user": "status",
            "-u": "status",
        }
        if arguments[0] in account_flags:
            arguments = ["auth", account_flags[arguments[0]], *arguments[1:]]
        else:
            arguments = ["download", *arguments]
    app(args=arguments)
