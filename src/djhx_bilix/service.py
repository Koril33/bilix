"""Download orchestration and atomic publication of validated results."""

import os
import shutil
import tempfile
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

from .bilibili.client import USER_AGENT, BilibiliClient
from .config import load_settings
from .downloader import ProgressCallback, transfer
from .errors import BilixError, DownloadError, MediaError, OperationCancelled
from .media import FFmpeg, find_ffmpeg
from .models import DownloadPlan, DownloadResult, VideoTarget
from .operations import CancellationToken, StageEvent
from .planner import select_pages


def discover(
    client: BilibiliClient,
    url: str,
    page: str | None,
    *,
    cancel: CancellationToken | None = None,
) -> tuple[VideoTarget, ...]:
    if cancel:
        cancel.raise_if_cancelled()
    info = client.fetch(url)
    if cancel:
        cancel.raise_if_cancelled()
    pages = select_pages(info, page)
    result = []
    for part in pages:
        if cancel:
            cancel.raise_if_cancelled()
        label = f"P{part.number} {part.title}" if len(info.pages) > 1 else ""
        identity = dict(
            page_number=part.number,
            cid=part.cid,
            bvid=part.bvid or (info.bvid if not info.episode_id else ""),
        )
        if part.cid and part.cid == info.cid and info.videos:
            result.append(
                VideoTarget(info.url, info, label, **identity, episode_id=info.episode_id)
            )
        elif part.url == info.url:
            result.append(
                VideoTarget(info.url, info, label, **identity, episode_id=info.episode_id)
            )
        else:
            result.append(
                VideoTarget(part.url, label=label, **identity, episode_id=part.episode_id)
            )
    return tuple(result)


def commit_file(source: Path, destination: Path, overwrite: bool) -> bool:
    """Publish on the same filesystem. Return False if a competing output already exists."""
    if overwrite:
        os.replace(source, destination)
        return True
    try:
        if os.name == "nt":
            # Windows rename fails if the destination exists, including on FAT/exFAT.
            os.rename(source, destination)
        else:
            # POSIX rename replaces existing files; an atomic hard link never does.
            os.link(source, destination)
    except FileExistsError:
        if not destination.is_file():
            raise DownloadError("输出路径已存在但不是普通文件，请调整保存目录") from None
        return False
    source.unlink(missing_ok=True)
    return True


def execute(
    plan: DownloadPlan,
    ffmpeg_path: str | None = None,
    overwrite: bool = False,
    progress: ProgressCallback | None = None,
    *,
    cancel: CancellationToken | None = None,
    stage: Callable[[StageEvent], None] | None = None,
    proxy: str | None = None,
) -> DownloadResult:
    if cancel:
        cancel.raise_if_cancelled()
    if plan.output.exists():
        if not plan.output.is_file():
            raise DownloadError("输出路径已存在但不是普通文件，请调整保存目录")
        if not overwrite:
            if stage:
                stage(StageEvent("skipped"))
            return DownloadResult(plan.output, skipped=True)
    executable = find_ffmpeg(ffmpeg_path)
    media = FFmpeg(executable)
    if cancel:
        cancel.raise_if_cancelled()
    try:
        plan.output.parent.mkdir(parents=True, exist_ok=True)
        work = Path(tempfile.mkdtemp(prefix=".bilix-", dir=plan.output.parent))
    except OSError:
        raise DownloadError("无法创建下载临时目录，请检查保存路径、权限和剩余空间") from None
    video, audio = work / "video.m4s", work / "audio.m4s"
    checked_video, checked_audio = work / "video.checked.mp4", work / "audio.checked.mp4"
    output = work / "result.mp4"
    headers = {"User-Agent": USER_AGENT, "Referer": plan.info.url}
    refresh_guard = threading.Lock()

    def refresh_stream(original):
        with refresh_guard:
            client = BilibiliClient(replace(load_settings(), proxy=proxy), cancel=cancel)
            info = client.fetch(plan.info.url)
            if (info.bvid, info.cid, info.episode_id) != (
                plan.info.bvid,
                plan.info.cid,
                plan.info.episode_id,
            ):
                raise DownloadError("来源身份已变化，无法恢复媒体流")
            if info.is_preview or info.is_drm:
                raise DownloadError("当前权限无法恢复原媒体流")
            candidates = info.videos if original.codec else info.audios
            stream = next(
                (
                    s
                    for s in candidates
                    if (s.quality, s.codec, s.audio_kind)
                    == (original.quality, original.codec, original.audio_kind)
                ),
                None,
            )
            if stream is None:
                raise DownloadError("原媒体格式已不可获取，请调整参数后重新下载")
            return stream

    try:
        if stage:
            stage(StageEvent("downloading", ffmpeg=str(executable)))
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(
                    transfer,
                    stream,
                    target,
                    headers,
                    progress,
                    **({"cancel": cancel} if cancel else {}),
                    **({"proxy": proxy} if proxy is not None else {}),
                    **(
                        {"refresh": lambda s=stream: refresh_stream(s)}
                        if hasattr(cancel, "paused")
                        else {}
                    ),
                    **({"feedback": progress.feedback} if hasattr(progress, "feedback") else {}),
                )
                for stream, target in ((plan.video, video), (plan.audio, audio))
            ]
            # Every result is consumed. Wait for both workers before leaving their work directory.
            errors = []
            for future in futures:
                try:
                    future.result()
                except Exception as error:
                    errors.append(error)
            if cancel:
                cancel.raise_if_cancelled()
            if errors:
                error = errors[0]
                if isinstance(error, BilixError):
                    raise error
                raise DownloadError("媒体流写入失败")
        if stage:
            stage(StageEvent("checking_video"))
        if cancel:
            cancel.checkpoint()
        video_duration = media.check_stream(
            video, checked_video, "v", plan.info.duration, **({"cancel": cancel} if cancel else {})
        )
        if cancel:
            cancel.raise_if_cancelled()
        if stage:
            stage(StageEvent("checking_audio"))
        if cancel:
            cancel.checkpoint()
        audio_duration = media.check_stream(
            audio, checked_audio, "a", plan.info.duration, **({"cancel": cancel} if cancel else {})
        )
        if abs(video_duration - audio_duration) > 2:
            raise MediaError("音视频时长不一致，未提交 MP4")
        if stage:
            stage(StageEvent("muxing"))
        if cancel:
            cancel.checkpoint()
        try:
            media.mux(
                checked_video, checked_audio, output, **({"cancel": cancel} if cancel else {})
            )
        except MediaError as error:
            raise MediaError(
                str(error),
                error_code="mux" if error.error_code == "validation" else error.error_code,
                action=error.action,
            ) from None
        # Ensure buffers reach the filesystem before committing the new directory entry.
        with output.open("rb+") as handle:
            os.fsync(handle.fileno())
        if cancel:
            cancel.raise_if_cancelled()
        if stage:
            stage(StageEvent("committing"))
        if cancel:
            cancel.checkpoint()
        committed = commit_file(output, plan.output, overwrite)
    except OperationCancelled:
        shutil.rmtree(work, ignore_errors=True)
        raise
    except (BilixError, OSError) as error:
        if cancel and cancel.cancelled():
            shutil.rmtree(work, ignore_errors=True)
            raise OperationCancelled("操作已取消") from None
        message = str(error) if isinstance(error, BilixError) else "文件写入或提交失败"
        raise DownloadError(f"{message}；临时目录：{work}", cause=error) from None
    except KeyboardInterrupt:
        if cancel:
            cancel.cancel()
        shutil.rmtree(work, ignore_errors=True)
        raise OperationCancelled("操作已取消") from None
    shutil.rmtree(work, ignore_errors=True)
    if stage:
        stage(StageEvent("completed" if committed else "skipped"))
    return DownloadResult(plan.output, skipped=not committed)
