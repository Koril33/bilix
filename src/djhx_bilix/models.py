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


@dataclass(frozen=True)
class DownloadPlan:
    info: VideoInfo
    video: Stream
    audio: Stream
    output: Path
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class DownloadResult:
    output: Path
    skipped: bool = False
