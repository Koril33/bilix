from dataclasses import replace

import pytest

from djhx_bilix.errors import InputError
from djhx_bilix.filenames import safe_filename
from djhx_bilix.models import Page, Stream
from djhx_bilix.planner import build_plan, parse_quality, select_pages
from djhx_bilix.urls import normalize_url, parse_pages


def test_normalization_keeps_page_and_discards_tracking():
    assert normalize_url("http://bilibili.com/video/BV1j4411W7F7/?p=2&share=abc#x") == (
        "https://www.bilibili.com/video/BV1j4411W7F7?p=2"
    )
    assert normalize_url("BV1j4411W7F7").endswith("/video/BV1j4411W7F7")


@pytest.mark.parametrize(
    "url",
    [
        "https://bilibili.com.evil/video/BV1j4411W7F7",
        "https://www.bilibili.com/",
        "https://secret@www.bilibili.com/video/BV1j4411W7F7",
        "file:///video",
        "https://www.bilibili.com/video/BV1j4411W7F7?p=0",
        "https://www.bilibili.com/video/BV1j4411W7F7?p=1&p=2",
    ],
)
def test_invalid_urls(url):
    with pytest.raises(InputError):
        normalize_url(url)


def test_combined_page_selection():
    assert parse_pages("1,3,5-7") == (1, 3, 5, 6, 7)
    assert parse_pages("all") is None


@pytest.mark.parametrize("value", ["", "0", "3-1", "1,1", "1-3,2", "10001", "1,,2", "a"])
def test_invalid_pages(value):
    with pytest.raises(InputError):
        parse_pages(value)


def test_single_page_explicit_and_bounds(video_info):
    assert len(select_pages(video_info, "1")) == 1
    assert len(select_pages(video_info, "all")) == 1
    with pytest.raises(InputError):
        select_pages(video_info, "2")


def test_multi_page_defaults_and_url_precedence(video_info):
    pages = video_info.pages + (Page(2, "part 2", video_info.url + "?p=2", 5, "200"),)
    video_info = replace(video_info, pages=pages)
    assert [p.number for p in select_pages(video_info, None)] == [1, 2]
    video_info = replace(video_info, url=video_info.url + "?p=2")
    assert [p.number for p in select_pages(video_info, None)] == [2]
    assert [p.number for p in select_pages(video_info, "1")] == [1]
    assert len(select_pages(video_info, "all")) == 2


def test_best_audio_and_explicit_fallback(video_info, tmp_path):
    plan = build_plan(video_info, tmp_path, quality=80)
    assert plan.video.quality == 32
    assert plan.audio.bandwidth == 192000
    assert plan.warnings
    with pytest.raises(InputError):
        build_plan(video_info, tmp_path, quality=80, strict=True)


def test_actual_codec_in_name(video_info, tmp_path):
    info = replace(video_info, videos=tuple(s for s in video_info.videos if s.codec == 12))
    plan = build_plan(info, tmp_path, codec="AVC")
    assert "HEVC" in plan.output.name
    assert plan.warnings
    with pytest.raises(InputError):
        build_plan(info, tmp_path, codec="AVC", strict=True)


@pytest.mark.parametrize("codecid,codec", [(12, "HEVC"), (13, "AV1")])
def test_auto_codec_quality_fallback_keeps_best_eligible_stream(
    video_info, tmp_path, codecid, codec
):
    best = Stream(80, codecid, 1000000, ("https://cdn.test/1080",))
    unavailable_higher = Stream(125, 12, 2000000, ("https://cdn.test/hdr",))
    info = replace(video_info, videos=(*video_info.videos, best, unavailable_higher))
    plan = build_plan(info, tmp_path, quality=120)
    assert plan.video == best
    assert codec in plan.output.name and plan.warnings
    assert plan.video.quality <= 120
    with pytest.raises(InputError, match="指定清晰度"):
        build_plan(info, tmp_path, quality=120, strict=True)


def test_explicit_codec_fallback_keeps_codec_preference(video_info, tmp_path):
    hevc = Stream(80, 12, 1000000, ("https://cdn.test/1080",))
    info = replace(video_info, videos=(*video_info.videos, hevc))
    plan = build_plan(info, tmp_path, quality=120, codec="AVC")
    assert plan.video.quality == 32 and plan.video.codec == 7
    assert plan.warnings


def test_auto_codec_fallback_prefers_avc_at_same_quality(video_info, tmp_path):
    avc = Stream(80, 7, 1000000, ("https://cdn.test/avc",))
    hevc = Stream(80, 12, 2000000, ("https://cdn.test/hevc",))
    info = replace(video_info, videos=(*video_info.videos, avc, hevc))
    assert build_plan(info, tmp_path, quality=120).video == avc


def test_auto_codec_quality_fallback_never_upgrades(video_info, tmp_path):
    info = replace(video_info, videos=tuple(s for s in video_info.videos if s.quality == 32))
    with pytest.raises(InputError, match="不高于"):
        build_plan(info, tmp_path, quality=16)


def test_quality_aliases():
    assert parse_quality("1080p") == parse_quality("80") == 80
    assert parse_quality("4K") == 120
    with pytest.raises(InputError):
        parse_quality("999")


@pytest.mark.parametrize("name", ["CON", "NUL.txt", "COM1", "...", "a" * 300, "正片"])
def test_portable_filenames(name):
    result = safe_filename(name)
    assert result and len(result.encode()) <= 180
    assert result not in ("CON", "COM1", "NUL.txt")


def test_filename_entities_and_part_identity(video_info, tmp_path):
    assert safe_filename("A &amp; B") == "A & B"
    pages = video_info.pages + (Page(2, "part 2", video_info.url + "?p=2", 5, "200"),)
    p1 = build_plan(replace(video_info, pages=pages), tmp_path)
    p2 = build_plan(replace(video_info, pages=pages, cid="200"), tmp_path)
    assert p1.output != p2.output
    assert "P2" in p2.output.name
