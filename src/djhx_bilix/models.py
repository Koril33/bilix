"""Data passed between discovery, planning, transfer and presentation layers."""

from dataclasses import dataclass, field
from pathlib import Path

CODECS = {7: "AVC", 12: "HEVC", 13: "AV1"}
QUALITY_NAMES = {
    6: "240P",
    16: "360P",
    32: "480P",
    64: "720P",
    74: "720P60",
    80: "1080P",
    100: "智能修复",
    112: "1080P+",
    116: "1080P60",
    120: "4K",
    125: "HDR",
    126: "杜比视界",
    127: "8K",
}

OUTPUT_MODES = {
    "merged": "完整视频（含声音）",
    "audio": "仅音频",
    "video": "仅视频（无声音）",
    "separate": "音频与视频分别保存",
    "cover": "仅封面",
}
OUTPUT_KINDS = {"media": "完整视频", "video": "无声视频", "audio": "音频", "cover": "封面"}


@dataclass(frozen=True)
class Stream:
    quality: int
    codec: int
    bandwidth: int
    urls: tuple[str, ...] = field(repr=False)
    size: int | None = None
    audio_kind: str = "aac"


@dataclass(frozen=True)
class Page:
    number: int
    title: str
    url: str
    duration: float = 0
    cid: str = ""
    bvid: str = ""
    episode_id: str = ""


@dataclass(frozen=True)
class VideoInfo:
    url: str
    title: str
    bvid: str
    cid: str
    duration: float
    pages: tuple[Page, ...]
    videos: tuple[Stream, ...] = ()
    audios: tuple[Stream, ...] = ()
    advertised_qualities: tuple[int, ...] = ()
    description: str = ""
    owner: str = ""
    episode_id: str = ""
    season_id: str = ""
    is_preview: bool = False
    is_drm: bool = False
    cover: str = ""

    def public_dict(self) -> dict:
        """Metadata export deliberately excludes signed CDN URLs and credentials."""
        return {
            "url": self.url,
            "title": self.title,
            "bvid": self.bvid,
            "cid": self.cid,
            "duration": self.duration,
            "description": self.description,
            "owner": self.owner,
            "cover": self.cover,
            "episode_id": self.episode_id,
            "season_id": self.season_id,
            "is_preview": self.is_preview,
            "is_drm": self.is_drm,
            "pages": [
                {
                    "number": p.number,
                    "title": p.title,
                    "url": p.url,
                    "duration": p.duration,
                    "cid": p.cid,
                }
                for p in self.pages
            ],
            "advertised_qualities": list(self.advertised_qualities),
            "available_streams": [
                {
                    "quality": s.quality,
                    "name": QUALITY_NAMES.get(s.quality, str(s.quality)),
                    "codec": CODECS.get(s.codec, str(s.codec)),
                    "bandwidth": s.bandwidth,
                }
                for s in self.videos
            ],
            "available_audio": [
                {"id": s.quality, "kind": s.audio_kind, "bandwidth": s.bandwidth}
                for s in self.audios
            ],
        }


@dataclass(frozen=True)
class VideoTarget:
    url: str
    cached_info: VideoInfo | None = None
    label: str = ""
    page_number: int = 1
    cid: str = ""
    bvid: str = ""
    episode_id: str = ""


@dataclass(frozen=True)
class OutputFile:
    kind: str
    output: Path


@dataclass(frozen=True)
class OutputResult:
    kind: str
    output: Path
    state: str
    detail: str = ""


@dataclass(frozen=True)
class DownloadPlan:
    info: VideoInfo
    video: Stream | None
    audio: Stream | None
    output: Path
    warnings: tuple[str, ...] = ()
    mode: str = "merged"
    files: tuple[OutputFile, ...] = ()

    @property
    def outputs(self) -> tuple[OutputFile, ...]:
        return self.files or (OutputFile("media", self.output),)


@dataclass(frozen=True)
class DownloadResult:
    output: Path
    skipped: bool = False
    files: tuple[OutputResult, ...] = ()
