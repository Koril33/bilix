"""Real FFmpeg regression checks with synthetic media, requiring a full FFmpeg install."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from djhx_bilix.errors import MediaError
from djhx_bilix.media import FFmpeg, find_ffmpeg


@pytest.fixture(scope="module")
def encoder():
    path = os.environ.get("BILIX_TEST_FFMPEG") or shutil.which("ffmpeg")
    if not path:
        pytest.skip("Full FFmpeg not installed")
    result = subprocess.run([path, "-hide_banner", "-encoders"], capture_output=True, text=True)
    if "libx264" not in result.stdout:
        pytest.skip("Full FFmpeg with libx264 required to generate synthetic media")
    return path


@pytest.fixture
def media_files(encoder, tmp_path):
    video, audio = tmp_path / "video.mp4", tmp_path / "audio.mp4"
    subprocess.run(
        [
            encoder,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=s=64x64:r=25",
            "-t",
            "4",
            "-c:v",
            "libx264",
            "-movflags",
            "+faststart",
            str(video),
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            encoder,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440",
            "-t",
            "4",
            "-c:a",
            "aac",
            str(audio),
        ],
        check=True,
        capture_output=True,
    )
    return video, audio


def test_packet_scan_and_mux_with_bundled_ffmpeg(media_files, tmp_path):
    media = FFmpeg(find_ffmpeg())
    video, audio = media_files
    checked_video, checked_audio = tmp_path / "v.checked.mp4", tmp_path / "a.checked.mp4"
    v_duration = media.check_stream(video, checked_video, "v", 4)
    a_duration = media.check_stream(audio, checked_audio, "a", 4)
    assert abs(v_duration - a_duration) < 1
    media.mux(checked_video, checked_audio, tmp_path / "result.mp4")
    assert (tmp_path / "result.mp4").stat().st_size > 0


def test_truncated_packet_data_is_rejected(media_files, tmp_path):
    video, _ = media_files
    truncated = tmp_path / "truncated.mp4"
    data = video.read_bytes()
    truncated.write_bytes(data[: int(len(data) * 0.8)])
    with pytest.raises(MediaError):
        FFmpeg(find_ffmpeg()).check_stream(truncated, tmp_path / "bad.checked.mp4", "v", 4)


def test_short_timeline_is_rejected(media_files, tmp_path):
    video, _ = media_files
    with pytest.raises(MediaError, match="时长不完整"):
        FFmpeg(find_ffmpeg()).check_stream(video, tmp_path / "short.checked.mp4", "v", 20)


def test_explicit_missing_ffmpeg():
    with pytest.raises(MediaError):
        find_ffmpeg(str(Path("does-not-exist-ffmpeg.exe")))


@pytest.mark.parametrize("codec", ["flac", "eac3"])
def test_member_audio_survives_scan_and_mux(codec, encoder, media_files, tmp_path):
    video, _ = media_files
    audio = tmp_path / "member-audio.mp4"
    subprocess.run(
        [
            encoder,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440",
            "-t",
            "4",
            "-c:a",
            codec,
            "-strict",
            "-2",
            str(audio),
        ],
        check=True,
        capture_output=True,
    )
    media = FFmpeg(find_ffmpeg())
    checked = tmp_path / "checked.mp4"
    media.check_stream(audio, checked, "a", 4)
    output = tmp_path / "result.mp4"
    media.mux(video, checked, output)
    # Decode the result, verifying both that the selected codec remains and its packets are valid.
    subprocess.run(
        [encoder, "-v", "error", "-xerror", "-i", str(output), "-map", "0:a:0", "-f", "null", "-"],
        check=True,
        capture_output=True,
    )
    probe = Path(encoder).with_name("ffprobe" + Path(encoder).suffix)
    data = json.loads(
        subprocess.check_output(
            [str(probe), "-v", "error", "-show_streams", "-of", "json", str(output)],
        )
    )
    assert next(s for s in data["streams"] if s["codec_type"] == "audio")["codec_name"] == codec


def add_dolby_configuration(data, path):
    """Add synthetic profile-8 metadata to a generated MP4 whose moov is after mdat.

    This tests container metadata preservation, without storing a copyrighted fixture.
    A visual sample entry has a 78-byte header; stsd has an 8-byte header.
    """
    if not path:
        record = bytes([1, 0, 8 << 1, (9 << 3) | 5, 4 << 4]) + bytes(19)
        return data + (32).to_bytes(4, "big") + b"dvvC" + record
    offset = 0
    while offset < len(data):
        size = int.from_bytes(data[offset : offset + 4], "big")
        kind = data[offset + 4 : offset + 8]
        assert size >= 8
        if kind == path[0]:
            header_size = {b"stsd": 8, b"hvc1": 78, b"hev1": 78}.get(kind, 0)
            header = data[offset + 8 : offset + 8 + header_size]
            payload = add_dolby_configuration(
                data[offset + 8 + header_size : offset + size], path[1:]
            )
            box = (8 + len(header) + len(payload)).to_bytes(4, "big") + kind + header + payload
            return data[:offset] + box + data[offset + size :]
        offset += size
    raise AssertionError("Synthetic MP4 is missing a required box")


def test_dolby_vision_configuration_survives_both_remuxes(encoder, media_files, tmp_path):
    _, audio = media_files
    video = tmp_path / "dolby.mp4"
    subprocess.run(
        [
            encoder,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=s=64x64:r=25",
            "-t",
            "4",
            "-c:v",
            "libx265",
            "-x265-params",
            "pools=1:frame-threads=1",
            "-tag:v",
            "hvc1",
            str(video),
        ],
        check=True,
        capture_output=True,
    )
    video.write_bytes(
        add_dolby_configuration(
            video.read_bytes(),
            [b"moov", b"trak", b"mdia", b"minf", b"stbl", b"stsd", b"hvc1"],
        )
    )
    probe = Path(encoder).with_name("ffprobe" + Path(encoder).suffix)

    def configuration(path):
        data = json.loads(
            subprocess.check_output(
                [str(probe), "-v", "error", "-show_streams", "-of", "json", str(path)],
            )
        )
        return next(
            s
            for s in data["streams"][0].get("side_data_list", [])
            if s["side_data_type"] == "DOVI configuration record"
        )

    original = configuration(video)
    media = FFmpeg(find_ffmpeg())
    checked = tmp_path / "checked.mp4"
    media.check_stream(video, checked, "v", 4)
    assert configuration(checked) == original
    output = tmp_path / "result.mp4"
    media.mux(checked, audio, output)
    assert configuration(output) == original
