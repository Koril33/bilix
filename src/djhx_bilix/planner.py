"""Pure download planning: page, quality, codec, audio and output selection."""

from pathlib import Path
from urllib.parse import urlsplit

from .errors import InputError
from .filenames import safe_filename
from .models import CODECS, QUALITY_NAMES, DownloadPlan, Page, VideoInfo
from .urls import parse_pages, url_page


def parse_quality(value: str | None) -> int | None:
    if value is None or value.lower() in ("auto", "best"):
        return None
    names = {name.lower(): q for q, name in QUALITY_NAMES.items()}
    result = int(value) if value.isdigit() else names.get(value.lower())
    if result not in QUALITY_NAMES:
        raise InputError("未知清晰度，请使用 auto、360p、480p、720p、1080p、4k 或对应 id")
    return result


def select_pages(info: VideoInfo, page: str | None) -> tuple[Page, ...]:
    selected = parse_pages(page)
    # Explicit --page overrides the page in a URL; otherwise ?p= selects just that part.
    if page is None and url_page(info.url) is not None:
        selected = (url_page(info.url),)
    pages = info.pages or (Page(1, info.title, info.url, info.duration, info.cid),)
    if selected is None:
        return pages
    mapping = {p.number: p for p in pages}
    missing = [number for number in selected if number not in mapping]
    if missing:
        raise InputError(f"选集超出范围：{','.join(map(str, missing))}；该视频共 {len(pages)} 集")
    return tuple(mapping[n] for n in selected)


def build_plan(
    info: VideoInfo,
    save: Path,
    quality: int | None = None,
    codec: str | None = None,
    strict: bool = False,
    audio: str = "aac",
) -> DownloadPlan:
    if info.is_drm:
        raise InputError("该媒体使用 DRM 保护，当前下载器不支持")
    if info.is_preview:
        raise InputError("当前会话仅能获取试看内容，未下载正片；请检查账号或影片购买权限")
    if not info.videos or not info.audios:
        raise InputError("没有可下载的音视频流，可能需要登录或相应会员权限")
    if quality is not None and quality not in QUALITY_NAMES:
        raise InputError("未知清晰度 id")
    if codec is None:
        # Auto chooses the best permitted quality before preferring its codec.
        # An unavailable requested quality must not force AVC and skip a better
        # HEVC/AV1 fallback that the current account can actually retrieve.
        eligible = [s for s in info.videos if quality is None or s.quality <= quality]
        target_quality = max((s.quality for s in eligible), default=quality)
        matching = [s for s in info.videos if s.quality == target_quality]
        codec = next((CODECS[k] for k in (7, 12, 13) if any(s.codec == k for s in matching)), "AVC")
    codec = codec.upper()
    if codec not in CODECS.values():
        raise InputError("--codec 必须是 AVC、HEVC 或 AV1")
    codecid = next(k for k, v in CODECS.items() if v == codec)
    warnings = []
    candidates = [v for v in info.videos if v.codec == codecid]
    if not candidates:
        if strict:
            raise InputError(f"当前账号无法获取 {codec} 视频流")
        candidates = list(info.videos)
        warnings.append(f"{codec} 不可用，将使用当前可获取的编码")
    exact = [v for v in candidates if v.quality == quality] if quality else []
    if quality and not exact:
        if strict:
            raise InputError(f"当前账号无法获取指定清晰度 {QUALITY_NAMES[quality]}")
        # Fallback never upgrades a user's explicit size/quality limit.
        lower = [v for v in candidates if v.quality <= quality]
        if not lower:
            raise InputError("没有不高于指定清晰度的可用流，请调整 --quality")
        candidates = lower
        warnings.append(f"{QUALITY_NAMES[quality]} 不可用，将使用可获取的较低清晰度")
    video = max(exact or candidates, key=lambda v: (v.quality, v.bandwidth))
    if audio not in ("aac", "flac", "dolby", "best"):
        raise InputError("--audio 必须是 aac、flac、dolby 或 best")
    audio_candidates = [s for s in info.audios if audio == "best" or s.audio_kind == audio]
    if not audio_candidates:
        raise InputError(f"该视频或当前账号没有可获取的 {audio.upper()} 音频")
    selected_audio = max(
        audio_candidates,
        key=lambda s: (
            ({"aac": 0, "dolby": 1, "flac": 2}.get(s.audio_kind, 0) if audio == "best" else 0),
            s.bandwidth,
        ),
    )
    title = info.title
    current = next((p for p in info.pages if p.cid == info.cid), None)
    if len(info.pages) > 1 and current:
        title += f"_P{current.number}_{current.title}"
    identity = info.bvid or urlsplit(info.url).path.split("/")[-1]
    identity = safe_filename(identity, 24)
    suffix = f"_{identity}_{info.cid}_{QUALITY_NAMES.get(video.quality, video.quality)}"
    suffix += f"_{CODECS.get(video.codec, video.codec)}"
    if selected_audio.audio_kind != "aac":
        suffix += f"_{selected_audio.audio_kind.upper()}"
    suffix += ".mp4"
    output = save / (safe_filename(title) + suffix)
    return DownloadPlan(info, video, selected_audio, output, tuple(warnings))
