"""Permission and playback regressions, using synthetic responses only."""

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from curl_cffi import requests
from typer.testing import CliRunner

from djhx_bilix import auth, cli
from djhx_bilix.bilibili import client as client_module
from djhx_bilix.bilibili.client import BilibiliClient, cookie_header
from djhx_bilix.bilibili.parser import apply_playback, embedded_json, parse_video
from djhx_bilix.credentials import normalize_cookie
from djhx_bilix.errors import APIError, BilixError, InputError
from djhx_bilix.models import Page, Stream
from djhx_bilix.planner import build_plan

SECRET = "SYNTHETIC_SESSION"
EP_URL = "https://www.bilibili.com/bangumi/play/ep123"
PLAY = {
    "timelength": 4000,
    "accept_quality": [125, 80],
    "dash": {
        "video": [{"id": 125, "codecid": 12, "baseUrl": "https://cdn.test/hdr"}],
        "audio": [{"id": 30280, "baseUrl": "https://cdn.test/aac", "bandwidth": 192000}],
        "dolby": {"audio": [{"id": 30250, "baseUrl": "https://cdn.test/dolby"}]},
        "flac": {"audio": {"id": 30251, "baseUrl": "https://cdn.test/flac"}},
    },
}


def season_document(result):
    metadata = {"season_id": 456, "title": "电影标题", "evaluate": "介绍"}
    next_data = {
        "props": {
            "pageProps": {
                "dehydratedState": {
                    "queries": [{"state": {"data": metadata}}],
                }
            }
        },
    }
    ssr = {"status": 200, "data": {"result": result}}
    return (
        f"<script>const playurlSSRData={json.dumps(ssr)};"
        "window.__playinfo__ = playurlSSRData.data\n</script>"
        f'<script type="application/json" id="__NEXT_DATA__">{json.dumps(next_data)}</script>'
    )


@pytest.mark.parametrize("ending", [";", "\n", "\r\n", "</script>"])
def test_pgc_javascript_alias_does_not_require_json(ending):
    assert embedded_json("window.__playinfo__=playurlSSRData.data" + ending, "__playinfo__") == {}


def test_new_pgc_wrapper_metadata_and_audio():
    document = season_document(
        {
            "video_info": PLAY,
            "arc": {"bvid": "BV1j4411W7F7", "cid": 987},
            "supplement": {"ogv_episode_info": {"episode_id": 123, "long_title": "第一集"}},
        }
    )
    info = parse_video(document, EP_URL)
    assert info.title == "电影标题 · 第一集"
    assert (info.bvid, info.cid, info.episode_id, info.season_id) == (
        "BV1j4411W7F7",
        "987",
        "123",
        "456",
    )
    assert info.duration == 4
    assert {s.audio_kind for s in info.audios} == {"aac", "flac", "dolby"}
    public = json.dumps(info.public_dict())
    assert "cdn.test" not in public
    assert len(info.public_dict()["available_audio"]) == 3


def session_factory(monkeypatch, response):
    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, *args, **kwargs):
            return response

    monkeypatch.setattr(requests, "Session", Session)


def test_missing_ssr_playback_uses_episode_api(monkeypatch, settings):
    session_factory(
        monkeypatch,
        SimpleNamespace(
            text=season_document({}),
            raise_for_status=lambda: None,
        ),
    )
    calls = []

    def api(self, path, params):
        calls.append((path, params))
        return {"video_info": PLAY, "arc": {"bvid": "BV1j4411W7F7", "cid": 987}}

    monkeypatch.setattr(BilibiliClient, "api", api)
    info = BilibiliClient(settings).fetch(EP_URL)
    assert info.videos[0].quality == 125 and info.duration == 4
    assert info.cid == "987" and info.bvid == "BV1j4411W7F7"
    assert calls == [
        (
            "pgc/player/web/v2/playurl",
            {
                "ep_id": "123",
                "qn": 127,
                "fnval": 143312,
                "fourk": 1,
            },
        )
    ]


def test_existing_ssr_streams_do_not_trigger_extra_request(monkeypatch, settings):
    session_factory(
        monkeypatch,
        SimpleNamespace(
            text=season_document({"video_info": PLAY}),
            raise_for_status=lambda: None,
        ),
    )
    monkeypatch.setattr(BilibiliClient, "api", lambda *a: pytest.fail("unneeded request"))
    assert BilibiliClient(settings).fetch(EP_URL).videos


@pytest.mark.parametrize("identifier", ["ss456", "md789"])
@pytest.mark.parametrize("trailer", [False, True])
def test_season_root_reports_primary_episode_permissions(
    monkeypatch, settings, identifier, trailer
):
    root_url = (
        "https://www.bilibili.com/bangumi/"
        + ("play/" if identifier.startswith("ss") else "media/")
        + identifier
    )
    pages = (
        Page(1, "正片第一集", EP_URL, 4, "111"),
        Page(2, "正片第二集", EP_URL + "4", 4, "222"),
    )
    documents = {
        root_url: season_document({"video_info": PLAY, "arc": {"cid": 987}} if trailer else {}),
        EP_URL: season_document(
            {
                "video_info": {**PLAY, "is_preview": 1},
                "arc": {"bvid": "BV1j4411W7F7", "cid": 111},
                "supplement": {"ogv_episode_info": {"episode_id": 123, "long_title": "正片"}},
            }
        ),
    }
    calls = []

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, url, **kwargs):
            calls.append(url)
            return SimpleNamespace(text=documents[url], raise_for_status=lambda: None)

    monkeypatch.setattr(requests, "Session", Session)
    monkeypatch.setattr(BilibiliClient, "episodes", lambda self, url: pages)
    monkeypatch.setattr(BilibiliClient, "api", lambda *a: pytest.fail("SSR already has streams"))
    info = BilibiliClient(settings).fetch(root_url)
    assert calls == [root_url, EP_URL]
    assert info.url == root_url and info.pages == pages
    assert info.cid == "111" and info.episode_id == "123" and info.is_preview
    assert info.title.endswith(" · 正片")
    with pytest.raises(InputError, match="试看"):
        build_plan(info, settings.download_dir)


def test_season_root_reuses_matching_primary_streams(monkeypatch, settings):
    root_url = "https://www.bilibili.com/bangumi/play/ss456"
    pages = (Page(1, "正片", EP_URL, 4, "987"),)
    session_factory(
        monkeypatch,
        SimpleNamespace(
            text=season_document({"video_info": PLAY, "arc": {"cid": 987}}),
            raise_for_status=lambda: None,
        ),
    )
    monkeypatch.setattr(BilibiliClient, "episodes", lambda self, url: pages)
    monkeypatch.setattr(BilibiliClient, "api", lambda *a: pytest.fail("unneeded request"))
    info = BilibiliClient(settings).fetch(root_url)
    assert info.cid == "987" and info.pages == pages and info.videos


def test_matching_season_metadata_without_playback_fetches_primary_episode(
    monkeypatch, settings, video_info
):
    root_url = "https://www.bilibili.com/bangumi/play/ss456"
    pages = (Page(1, "正片", EP_URL, 4, video_info.cid),)
    calls = []

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, url, **kwargs):
            calls.append(url)
            return SimpleNamespace(text=url, raise_for_status=lambda: None)

    def parse(document, url):
        if url == root_url:
            return replace(video_info, url=url, pages=(), videos=(), audios=())
        return replace(video_info, url=url, is_preview=True)

    monkeypatch.setattr(requests, "Session", Session)
    monkeypatch.setattr(client_module, "parse_video", parse)
    monkeypatch.setattr(BilibiliClient, "episodes", lambda self, url: pages)
    monkeypatch.setattr(BilibiliClient, "api", lambda *a: pytest.fail("unneeded request"))
    info = BilibiliClient(settings).fetch(root_url)
    assert calls == [root_url, EP_URL]
    assert info.cid == video_info.cid and info.pages == pages and info.is_preview


def test_legacy_set_cookie_normalization_and_readonly_migration(settings):
    legacy = (
        f"SESSDATA={SECRET}; Path=/; Domain=.bilibili.com; "
        "Expires=Wed, 01 Jan 2030 00:00:00 GMT; HttpOnly; Secure, "
        "bili_jct=FAKE_CSRF; Path=/; SameSite=None, DedeUserID=1; Path=/"
    )
    expected = f"SESSDATA={SECRET}; bili_jct=FAKE_CSRF; DedeUserID=1"
    assert normalize_cookie(legacy, require_session=True) == expected
    settings.config_dir.mkdir()
    settings.token_file.write_text(legacy, encoding="utf-8")
    assert cookie_header(settings) == expected
    assert settings.token_file.read_text(encoding="utf-8") == legacy


@pytest.mark.parametrize("cookie", ["", "other=value", f"SESSDATA={SECRET}\r\nInjected: secret"])
def test_invalid_cookie_never_replaces_existing_token(cookie, settings):
    auth.save_token(settings, f"SESSDATA={SECRET}")
    with pytest.raises(BilixError) as error:
        auth.save_token(settings, cookie)
    assert SECRET not in str(error.value)
    assert settings.token_file.read_text(encoding="utf-8") == f"SESSDATA={SECRET}"


@pytest.mark.parametrize("code", [-101, -10403, -412, 12345])
def test_api_error_never_contains_upstream_message(monkeypatch, settings, code):
    session_factory(
        monkeypatch,
        SimpleNamespace(
            json=lambda: {"code": code, "message": SECRET, "data": {"refresh_token": SECRET}},
            raise_for_status=lambda: None,
        ),
    )
    with pytest.raises(APIError) as error:
        BilibiliClient(settings).api("test")
    assert error.value.code == code and SECRET not in str(error.value)


@pytest.mark.parametrize("body", [{"code": SECRET}, [], {"code": True}])
def test_api_rejects_non_numeric_status_without_leaking(monkeypatch, settings, body):
    session_factory(monkeypatch, SimpleNamespace(json=lambda: body, raise_for_status=lambda: None))
    with pytest.raises(BilixError) as error:
        BilibiliClient(settings).api("test")
    assert SECRET not in str(error.value)


@pytest.mark.parametrize("key", ["data", "result"])
@pytest.mark.parametrize("payload", [[], SECRET, 1, True])
def test_api_rejects_non_object_payload_without_leaking(monkeypatch, settings, key, payload):
    session_factory(
        monkeypatch,
        SimpleNamespace(json=lambda: {"code": 0, key: payload}, raise_for_status=lambda: None),
    )
    with pytest.raises(BilixError, match="响应格式") as error:
        BilibiliClient(settings).api("test")
    assert SECRET not in str(error.value)


@pytest.mark.parametrize(
    "video",
    [None, [SECRET], [{"baseUrl": "https://cdn.test/video", "id": SECRET}]],
)
def test_malformed_episode_playback_is_safe_per_item_json_failure(monkeypatch, video_info, video):
    session_factory(monkeypatch, SimpleNamespace(text="ignored", raise_for_status=lambda: None))
    monkeypatch.setattr(
        client_module,
        "parse_video",
        lambda document, url: (
            replace(video_info, url=url, episode_id="123", videos=(), audios=())
            if url == EP_URL
            else video_info
        ),
    )
    monkeypatch.setattr(
        BilibiliClient,
        "api",
        lambda *a: {"video_info": {"dash": {"video": video}}},
    )
    result = CliRunner().invoke(cli.app, ["info", EP_URL, "BV1j4411W7F7", "--json"])
    records = json.loads(result.stdout)
    assert result.exit_code == 1 and len(records) == 2
    assert not records[0]["ok"] and records[1]["ok"]
    assert "数据不完整" in records[0]["error"]
    assert SECRET not in result.output


@pytest.mark.parametrize(
    "vip_status,vip_type,expected", [(1, 1, True), (1, 2, True), (0, 2, False), (0, 0, False)]
)
def test_ordinary_expired_vip_and_active_vip_accounts(settings, vip_status, vip_type, expected):
    auth.save_token(settings, f"SESSDATA={SECRET}")
    client = SimpleNamespace(
        settings=settings,
        api=lambda _: {
            "isLogin": True,
            "uname": "测试用户",
            "vip": {"status": vip_status, "type": vip_type},
            "refresh_token": SECRET,
            "wbi_img": {"img_url": SECRET},
        },
    )
    result = auth.status(client)
    assert result["logged_in"] and result["vip"] == expected
    assert SECRET not in json.dumps(result)


def test_expired_session_status_and_cli_message(settings, monkeypatch):
    auth.save_token(settings, f"SESSDATA={SECRET}")

    def expired(*args, **kwargs):
        raise APIError(-101)

    monkeypatch.setattr(BilibiliClient, "api", expired)
    assert auth.status(BilibiliClient(settings)) == {"logged_in": False, "expired": True}
    runner = CliRunner()
    result = runner.invoke(cli.app, ["auth", "status"])
    assert result.exit_code == 0 and "已失效" in result.output
    assert SECRET not in result.output
    result = runner.invoke(cli.app, ["auth", "status", "--json"])
    assert json.loads(result.stdout) == {"logged_in": False, "expired": True}


@pytest.mark.parametrize("flag", ["is_preview", "is_drm"])
def test_preview_and_drm_are_rejected_before_transfer(video_info, tmp_path, flag):
    info = apply_playback(video_info, {**PLAY, flag: 1})
    assert info.public_dict()[flag]
    with pytest.raises(InputError):
        build_plan(info, tmp_path)


def test_auto_codec_preserves_highest_member_quality(video_info, tmp_path):
    hdr = Stream(125, 12, 5000000, ("https://cdn.test/hdr",))
    info = replace(video_info, videos=(*video_info.videos, hdr))
    for quality in (None, 125):
        plan = build_plan(info, tmp_path, quality=quality, strict=True)
        assert plan.video == hdr and not plan.warnings
    with pytest.raises(InputError):
        build_plan(info, tmp_path, quality=125, codec="AVC", strict=True)


def test_audio_selection_and_distinct_outputs(video_info, tmp_path):
    flac = Stream(30251, 0, 1000000, ("https://cdn.test/flac",), audio_kind="flac")
    dolby = Stream(30250, 0, 448000, ("https://cdn.test/dolby",), audio_kind="dolby")
    info = replace(video_info, audios=(*video_info.audios, flac, dolby))
    aac_plan = build_plan(info, tmp_path)
    flac_plan = build_plan(info, tmp_path, audio="flac")
    dolby_plan = build_plan(info, tmp_path, audio="dolby")
    assert aac_plan.audio.audio_kind == "aac" and aac_plan.audio.bandwidth == 192000
    assert flac_plan.audio == flac and dolby_plan.audio == dolby
    assert len({p.output for p in (aac_plan, flac_plan, dolby_plan)}) == 3
    assert build_plan(info, tmp_path, audio="best").audio == flac
    with pytest.raises(InputError):
        build_plan(video_info, tmp_path, audio="flac")


def test_cli_hdr_auto_and_audio_option(monkeypatch, video_info):
    info = apply_playback(video_info, PLAY)
    monkeypatch.setattr(BilibiliClient, "fetch", lambda *a: info)
    monkeypatch.setattr(cli, "execute", lambda *a: pytest.fail("must not transfer"))
    result = CliRunner().invoke(
        cli.app,
        [
            "download",
            "BV1j4411W7F7",
            "-q",
            "HDR",
            "--audio",
            "FLAC",
            "--strict",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "HDR / HEVC / FLAC" in result.output
