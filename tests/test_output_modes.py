"""End-to-end decisions for independent file outputs and cover-only access."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from djhx_bilix import artwork, service
from djhx_bilix.errors import NetworkError
from djhx_bilix.operations import CancellationToken
from djhx_bilix.planner import build_plan
from djhx_bilix.tasks import DownloadOptions, JobSpec, Session, run_batch, run_preview


class CopyingMedia:
    def __init__(self, executable):
        pass

    def check_stream(self, source, target, kind, expected, *, cancel=None):
        target.write_bytes(source.read_bytes())
        return expected


def test_modes_select_only_needed_streams_and_disambiguate_paths(video_info, tmp_path):
    no_video = replace(video_info, videos=())
    no_audio = replace(video_info, audios=())
    audio = build_plan(no_video, tmp_path, mode="audio")
    video = build_plan(no_audio, tmp_path, mode="video")
    assert audio.video is None and audio.audio is not None
    assert audio.output.suffix == ".m4a"
    assert video.audio is None and video.video is not None
    assert video.output.name.endswith(".video.mp4")
    assert build_plan(video_info, tmp_path).output.name.endswith(".mp4")
    assert len({audio.output, video.output, build_plan(video_info, tmp_path).output}) == 3
    cover = build_plan(
        replace(no_video, audios=(), cover="https://i1.hdslb.com/c.jpg"), tmp_path, mode="cover"
    )
    assert [f.kind for f in cover.outputs] == ["cover"]


def test_separate_partial_failure_keeps_video_and_retry_only_fetches_audio(
    monkeypatch, video_info, tmp_path
):
    monkeypatch.setattr(service, "find_ffmpeg", lambda _value: "fake")
    monkeypatch.setattr(service, "FFmpeg", CopyingMedia)
    calls = {"video": 0, "audio": 0}

    def transfer(stream, target, headers, progress, **kwargs):
        kind = target.stem
        calls[kind] += 1
        if kind == "audio" and calls[kind] == 1:
            raise NetworkError("audio unavailable")
        target.write_bytes(kind.encode())

    monkeypatch.setattr(service, "transfer", transfer)
    options = DownloadOptions(None, None, "aac", tmp_path, False, False, None, mode="separate")
    session = Session()
    batch = session.begin((JobSpec(video_info.url),), options)
    client = SimpleNamespace(fetch=lambda _url: video_info)
    first = run_batch(session, batch, lambda _event: None, CancellationToken(), client=client)
    task = next(iter(session.tasks.values()))
    assert first["failed"] == 1
    assert task.latest.error_code == "partial"
    assert [(f.kind, f.state) for f in task.latest.files] == [
        ("video", "completed"),
        ("audio", "failed"),
    ]
    assert task.latest.files[0].output.read_bytes() == b"video"
    retry = session.retry((task.task_id,))
    second = run_batch(session, retry, lambda _event: None, CancellationToken(), client=client)
    assert second["completed"] == 1
    assert calls == {"video": 1, "audio": 2}
    assert task.latest.files[0].output.read_bytes() == b"video"
    assert len([f for f in session.tasks[task.task_id].latest.files if f.state == "completed"]) == 2


def test_cover_only_works_without_streams_or_ffmpeg_and_uses_response_format(
    monkeypatch, video_info, tmp_path
):
    info = replace(video_info, videos=(), audios=(), cover="https://i1.hdslb.com/cover.jpg")
    monkeypatch.setattr(service, "find_ffmpeg", lambda _value: pytest.fail("FFmpeg should not run"))
    monkeypatch.setattr("djhx_bilix.exports.download_cover", lambda *_a, **_k: (b"image", ".png"))
    options = DownloadOptions(None, None, "aac", tmp_path, False, False, None, mode="cover")
    session = Session()
    batch = session.begin((JobSpec(info.url),), options)
    client = SimpleNamespace(fetch=lambda _url: info)
    counts = run_batch(session, batch, lambda _event: None, CancellationToken(), client=client)
    result = next(iter(session.tasks.values())).latest
    assert counts["completed"] == 1
    assert len(result.files) == 1 and result.files[0].output.suffix == ".png"
    assert result.files[0].output.read_bytes() == b"image"


def test_preview_lists_each_file_and_cover_failure_does_not_discard_media(
    monkeypatch, video_info, tmp_path
):
    info = replace(video_info, cover="https://i1.hdslb.com/cover.jpg")
    options = DownloadOptions(
        None, None, "aac", tmp_path, False, False, None, mode="video", cover=True
    )
    client = SimpleNamespace(fetch=lambda _url: info)
    events = []
    preview = run_preview(
        (JobSpec(info.url),), options, events.append, CancellationToken(), client=client
    )
    assert preview["planned"] == 2
    assert sorted(e["output"] for e in events if e["type"] == "preview") == sorted(
        str(f.output) for f in build_plan(info, tmp_path, mode="video", cover=True).outputs
    )
    monkeypatch.setattr(service, "find_ffmpeg", lambda _value: "fake")
    monkeypatch.setattr(service, "FFmpeg", CopyingMedia)
    monkeypatch.setattr(
        service, "transfer", lambda _s, target, _h, _p, **_k: target.write_bytes(b"video")
    )
    monkeypatch.setattr(
        "djhx_bilix.exports.download_cover",
        lambda *_a, **_k: (_ for _ in ()).throw(NetworkError("cover unavailable")),
    )
    session = Session()
    batch = session.begin((JobSpec(info.url),), options)
    counts = run_batch(session, batch, lambda _event: None, CancellationToken(), client=client)
    result = next(iter(session.tasks.values())).latest
    assert counts["failed"] == 1 and result.error_code == "partial"
    assert result.files[0].output.is_file()
    assert result.files[1].state == "failed"


@pytest.mark.parametrize(
    "url",
    [
        "https://hdslb.com.attacker.example/cover.jpg",
        "https://user:secret@i1.hdslb.com/cover.jpg",
        "https://i1.hdslb.com:8080/cover.jpg",
        "file:///etc/passwd",
    ],
)
def test_cover_rejects_untrusted_sources(url):
    with pytest.raises(NetworkError):
        artwork.cover_url(url)


def test_cover_rejects_non_image_content():
    with pytest.raises(NetworkError):
        artwork.image_extension(b"<html>not an image</html>")
