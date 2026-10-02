import pytest

from djhx_bilix.config import Settings
from djhx_bilix.models import Page, Stream, VideoInfo


@pytest.fixture(autouse=True)
def isolated_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("BILIX_CONFIG_DIR", str(tmp_path / "profile"))
    monkeypatch.setenv("BILIX_DOWNLOAD_DIR", str(tmp_path / "downloads"))
    monkeypatch.delenv("BILIX_FFMPEG", raising=False)


@pytest.fixture
def settings(tmp_path):
    return Settings(tmp_path / "profile", tmp_path / "downloads")


@pytest.fixture
def video_info():
    url = "https://www.bilibili.com/video/BV1j4411W7F7"
    return VideoInfo(
        url,
        "test video",
        "BV1j4411W7F7",
        "100",
        4,
        (Page(1, "part 1", url + "?p=1", 4, "100"),),
        (
            Stream(32, 7, 200, ("https://cdn.example/video",)),
            Stream(16, 7, 100, ("https://cdn.example/video-low",)),
            Stream(32, 12, 150, ("https://cdn.example/video-hevc",)),
        ),
        (
            Stream(30216, 0, 64000, ("https://cdn.example/audio-low",)),
            Stream(30280, 0, 192000, ("https://cdn.example/audio",)),
        ),
        (80, 32, 16),
    )
