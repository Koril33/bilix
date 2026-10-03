"""Download orchestration and atomic publication of validated results."""

import os
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .bilibili.client import USER_AGENT, BilibiliClient
from .downloader import ProgressCallback, transfer
from .errors import BilixError, DownloadError, MediaError
from .media import FFmpeg, find_ffmpeg
from .models import DownloadPlan, DownloadResult, VideoTarget
from .planner import select_pages


def discover(client: BilibiliClient, url: str, page: str | None) -> tuple[VideoTarget, ...]:
    info = client.fetch(url)
    pages = select_pages(info, page)
    result = []
    for part in pages:
        label = f"P{part.number} {part.title}" if len(info.pages) > 1 else ""
        if part.cid and part.cid == info.cid and info.videos:
            result.append(VideoTarget(info.url, info, label))
        elif part.url == info.url:
            result.append(VideoTarget(info.url, info, label))
        else:
            result.append(VideoTarget(part.url, label=label))
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
) -> DownloadResult:
    if plan.output.exists():
        if not plan.output.is_file():
            raise DownloadError("输出路径已存在但不是普通文件，请调整保存目录")
        if not overwrite:
            return DownloadResult(plan.output, skipped=True)
    media = FFmpeg(find_ffmpeg(ffmpeg_path))
    plan.output.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=".bilix-", dir=plan.output.parent))
    video, audio = work / "video.m4s", work / "audio.m4s"
    checked_video, checked_audio = work / "video.checked.mp4", work / "audio.checked.mp4"
    output = work / "result.mp4"
    headers = {"User-Agent": USER_AGENT, "Referer": plan.info.url}
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(transfer, stream, target, headers, progress)
                for stream, target in ((plan.video, video), (plan.audio, audio))
            ]
            # Every result is consumed. Wait for both workers before leaving their work directory.
            errors = []
            for future in futures:
                try:
                    future.result()
                except Exception as error:
                    errors.append(error)
            if errors:
                error = errors[0]
                if isinstance(error, BilixError):
                    raise error
                raise DownloadError("媒体流写入失败")
        video_duration = media.check_stream(video, checked_video, "v", plan.info.duration)
        audio_duration = media.check_stream(audio, checked_audio, "a", plan.info.duration)
        if abs(video_duration - audio_duration) > 2:
            raise MediaError("音视频时长不一致，未提交 MP4")
        media.mux(checked_video, checked_audio, output)
        # Ensure buffers reach the filesystem before committing the new directory entry.
        with output.open("rb+") as handle:
            os.fsync(handle.fileno())
        committed = commit_file(output, plan.output, overwrite)
    except (BilixError, OSError) as error:
        message = str(error) if isinstance(error, BilixError) else "文件写入或提交失败"
        raise DownloadError(f"{message}；临时目录：{work}") from None
    except KeyboardInterrupt:
        raise DownloadError(f"下载已中断；临时目录：{work}") from None
    shutil.rmtree(work, ignore_errors=True)
    return DownloadResult(plan.output, skipped=not committed)
