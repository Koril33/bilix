"""Independent validated outputs; one failed file never discards successful files."""

import os
import shutil
import tempfile
from dataclasses import replace
from pathlib import Path

from . import service
from .artwork import download_cover
from .bilibili.client import USER_AGENT, BilibiliClient
from .config import load_settings
from .errors import DownloadError, OperationCancelled, safe_error
from .models import DownloadResult, OutputResult
from .operations import StageEvent


def execute_files(
    plan, ffmpeg_path, overwrite, progress, *, cancel, stage, proxy, artifact, retained
):
    results = []
    media = None
    if stage:
        stage(StageEvent("exporting"))

    def record(result):
        results.append(result)
        if artifact:
            artifact(result)

    def refresh(original, kind):
        info = BilibiliClient(replace(load_settings(), proxy=proxy), cancel=cancel).fetch(
            plan.info.url
        )
        if (info.bvid, info.cid, info.episode_id) != (
            plan.info.bvid,
            plan.info.cid,
            plan.info.episode_id,
        ):
            raise DownloadError("来源身份已变化，无法恢复媒体流")
        if info.is_preview or info.is_drm:
            raise DownloadError("当前权限无法恢复原媒体流")
        candidates = info.videos if kind == "video" else info.audios
        value = next(
            (
                s
                for s in candidates
                if (s.quality, s.codec, s.audio_kind)
                == (original.quality, original.codec, original.audio_kind)
            ),
            None,
        )
        if value is None:
            raise DownloadError("原媒体格式已不可获取，请调整参数后重新下载")
        return value

    for item in plan.outputs:
        if cancel:
            cancel.checkpoint()
        destination, work = item.output, None
        try:
            old = next(
                (
                    r
                    for r in retained
                    if r.kind == item.kind
                    and r.output == destination
                    and r.state in {"completed", "skipped"}
                    and r.output.is_file()
                ),
                None,
            )
            if old:
                record(replace(old, detail="保留上次成功文件"))
                continue
            # Cover format is determined from the response, before its conflict decision.
            data = None
            if item.kind == "cover":
                data, extension = download_cover(plan.info.cover, cancel=cancel, proxy=proxy)
                destination = destination.with_suffix(extension)
                old = next(
                    (
                        r
                        for r in retained
                        if r.kind == "cover"
                        and r.output == destination
                        and r.state in {"completed", "skipped"}
                        and r.output.is_file()
                    ),
                    None,
                )
                if old:
                    record(replace(old, detail="保留上次成功文件"))
                    continue
            if destination.exists():
                if not destination.is_file():
                    raise DownloadError("输出路径已存在但不是普通文件，请调整保存目录")
                if not overwrite:
                    record(OutputResult(item.kind, destination, "skipped", "已存在，未校验"))
                    continue
            if item.kind == "media":
                value = service._execute_merged(
                    replace(plan, files=(), output=destination),
                    ffmpeg_path,
                    overwrite,
                    progress,
                    cancel=cancel,
                    proxy=proxy,
                )
                record(
                    OutputResult(
                        item.kind,
                        value.output,
                        "skipped" if value.skipped else "completed",
                        "已校验并合并",
                    )
                )
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            work = Path(tempfile.mkdtemp(prefix=".bilix-", dir=destination.parent))
            if item.kind == "cover":
                output = work / ("cover" + destination.suffix)
                output.write_bytes(data)
            else:
                if media is None:
                    executable = service.find_ffmpeg(ffmpeg_path)
                    media = service.FFmpeg(executable)
                    if stage:
                        stage(StageEvent("exporting", ffmpeg=str(executable)))
                stream = plan.video if item.kind == "video" else plan.audio
                source = work / (item.kind + ".m4s")
                output = work / (item.kind + ".checked" + destination.suffix)
                extra = {}
                if cancel:
                    extra["cancel"] = cancel
                if proxy is not None:
                    extra["proxy"] = proxy
                if hasattr(cancel, "paused"):
                    extra["refresh"] = lambda s=stream, k=item.kind: refresh(s, k)
                if hasattr(progress, "feedback"):
                    extra["feedback"] = progress.feedback
                service.transfer(
                    stream,
                    source,
                    {"User-Agent": USER_AGENT, "Referer": plan.info.url},
                    progress,
                    **extra,
                )
                if cancel:
                    cancel.checkpoint()
                media.check_stream(
                    source,
                    output,
                    "v" if item.kind == "video" else "a",
                    plan.info.duration,
                    **({"cancel": cancel} if cancel else {}),
                )
            with output.open("rb+") as handle:
                os.fsync(handle.fileno())
            if cancel:
                cancel.checkpoint()
            committed = service.commit_file(output, destination, overwrite)
            record(
                OutputResult(
                    item.kind,
                    destination,
                    "completed" if committed else "skipped",
                    "已检查并保存" if committed else "已存在，未校验",
                )
            )
            shutil.rmtree(work, ignore_errors=True)
            work = None
        except OperationCancelled:
            if work:
                shutil.rmtree(work, ignore_errors=True)
            raise
        except Exception as error:
            if cancel:
                cancel.raise_if_cancelled()
            detail, _, _ = safe_error(error)
            if work:
                detail += f"；临时目录：{work}"
            record(OutputResult(item.kind, destination, "failed", detail))
    successful = [r for r in results if r.state in {"completed", "skipped"}]
    return DownloadResult(
        successful[0].output if successful else plan.output,
        bool(results) and all(r.state == "skipped" for r in results),
        tuple(results),
    )
