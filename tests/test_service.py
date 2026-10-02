import threading
from dataclasses import replace

import pytest

from djhx_bilix import service
from djhx_bilix.errors import DownloadError, MediaError, NetworkError
from djhx_bilix.models import Page
from djhx_bilix.planner import build_plan


class FakeMedia:
    def __init__(self, *args):
        pass

    def check_stream(self, source, target, kind, expected):
        target.write_bytes(source.read_bytes())
        return expected

    def mux(self, video, audio, output):
        output.write_bytes(video.read_bytes() + audio.read_bytes())


@pytest.fixture
def prepared(monkeypatch):
    monkeypatch.setattr(service, "find_ffmpeg", lambda _: "fake")
    monkeypatch.setattr(service, "FFmpeg", FakeMedia)

    def transfer(stream, target, headers, progress):
        assert "Cookie" not in headers
        target.write_bytes(target.stem.encode())

    monkeypatch.setattr(service, "transfer", transfer)


@pytest.mark.parametrize("stage", ["download", "check", "mux", "commit"])
def test_failure_preserves_old_file_and_work_directory(
    prepared, monkeypatch, video_info, tmp_path, stage
):
    plan = build_plan(video_info, tmp_path)
    plan.output.write_bytes(b"valuable existing MP4")

    def fail(*args, **kwargs):
        raise MediaError("injected failure")

    if stage == "download":
        monkeypatch.setattr(service, "transfer", fail)
    elif stage == "check":
        monkeypatch.setattr(FakeMedia, "check_stream", fail)
    elif stage == "mux":
        monkeypatch.setattr(FakeMedia, "mux", fail)
    else:
        monkeypatch.setattr(service, "commit_file", fail)
    with pytest.raises(DownloadError, match="临时目录"):
        service.execute(plan, overwrite=True)
    assert plan.output.read_bytes() == b"valuable existing MP4"
    work = list(tmp_path.glob(".bilix-*"))
    assert len(work) == 1
    if stage != "download":
        assert (work[0] / "video.m4s").exists()
        assert (work[0] / "audio.m4s").exists()


def test_all_worker_results_consumed(prepared, monkeypatch, video_info, tmp_path):
    barrier = threading.Barrier(2)
    finished = []

    def failure(stream, target, headers, progress):
        barrier.wait(timeout=5)
        finished.append(target.stem)
        raise NetworkError("worker failed")

    monkeypatch.setattr(service, "transfer", failure)
    with pytest.raises(DownloadError):
        service.execute(build_plan(video_info, tmp_path))
    assert sorted(finished) == ["audio", "video"]
    assert not list(tmp_path.glob("*.mp4"))


def test_skip_does_not_touch_file_or_transfer(monkeypatch, video_info, tmp_path):
    plan = build_plan(video_info, tmp_path)
    plan.output.write_bytes(b"old")
    monkeypatch.setattr(service, "find_ffmpeg", lambda _: pytest.fail("should skip before FFmpeg"))
    assert service.execute(plan).skipped
    assert plan.output.read_bytes() == b"old"


@pytest.mark.parametrize("overwrite", [False, True])
def test_existing_output_directory_is_an_error_before_transfer(
    monkeypatch, video_info, tmp_path, overwrite
):
    plan = build_plan(video_info, tmp_path)
    plan.output.mkdir()
    protected = plan.output / "keep.txt"
    protected.write_bytes(b"valuable content")
    monkeypatch.setattr(service, "find_ffmpeg", lambda _: pytest.fail("must fail before FFmpeg"))
    with pytest.raises(DownloadError, match="不是普通文件"):
        service.execute(plan, overwrite=overwrite)
    assert protected.read_bytes() == b"valuable content"
    assert not list(tmp_path.glob(".bilix-*"))


@pytest.mark.parametrize("overwrite", [False, True])
def test_validated_atomic_commit(prepared, video_info, tmp_path, overwrite):
    plan = build_plan(video_info, tmp_path)
    if overwrite:
        plan.output.write_bytes(b"old")
    result = service.execute(plan, overwrite=overwrite)
    assert not result.skipped
    assert plan.output.read_bytes() == b"videoaudio"
    assert not list(tmp_path.glob(".bilix-*"))


def test_competing_writer_is_not_overwritten(tmp_path):
    source, destination = tmp_path / "new", tmp_path / "existing"
    source.write_bytes(b"new")
    destination.write_bytes(b"old")
    assert service.commit_file(source, destination, overwrite=False) is False
    assert destination.read_bytes() == b"old"


def test_competing_output_directory_is_not_reported_as_skipped(tmp_path):
    source, destination = tmp_path / "new", tmp_path / "existing"
    source.write_bytes(b"new")
    destination.mkdir()
    with pytest.raises(DownloadError, match="不是普通文件"):
        service.commit_file(source, destination, overwrite=False)
    assert source.read_bytes() == b"new" and destination.is_dir()


def test_discovery_reuses_current_page(video_info):
    class Client:
        def __init__(self):
            self.calls = []

        def fetch(self, url):
            self.calls.append(url)
            return replace(video_info, url=url)

    client = Client()
    targets = service.discover(client, video_info.url, "1")
    assert len(targets) == 1 and targets[0].cached_info == video_info
    assert client.calls == [video_info.url]


def test_discovery_does_not_prefetch_all_pages(video_info):
    pages = video_info.pages + (Page(2, "second", video_info.url + "?p=2", 4, "200"),)
    info = replace(video_info, pages=pages)

    class Client:
        def fetch(self, url):
            assert url == video_info.url, "Only the initial page should be requested"
            return info

    targets = service.discover(Client(), video_info.url, None)
    assert len(targets) == 2
    assert targets[0].cached_info is info
    assert targets[1].cached_info is None
