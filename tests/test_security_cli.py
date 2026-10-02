import json
import os
import subprocess
import sys
from dataclasses import replace
from types import SimpleNamespace

import pytest
from curl_cffi import requests
from curl_cffi.requests.exceptions import RequestException
from typer.testing import CliRunner

from djhx_bilix import auth, cli
from djhx_bilix.bilibili.client import BilibiliClient
from djhx_bilix.config import load_settings
from djhx_bilix.errors import BilixError, InputError, NetworkError
from djhx_bilix.models import DownloadResult, Page

runner = CliRunner()
SECRET = "AUDIT_DUMMY_SECRET"


def test_cookie_attributes_are_not_stored():
    response = SimpleNamespace(
        cookies=SimpleNamespace(get_dict=lambda: {}),
        headers=SimpleNamespace(
            get_list=lambda _: [
                f"SESSDATA={SECRET}; Path=/; HttpOnly; Secure",
                "bili_jct=FAKE_CSRF; Path=/",
            ]
        ),
    )
    cookie = auth.response_cookie(response)
    assert cookie == f"SESSDATA={SECRET}; bili_jct=FAKE_CSRF"
    assert "Path" not in cookie and "HttpOnly" not in cookie


def test_missing_session_cookie_is_failure():
    with pytest.raises(BilixError):
        auth.response_cookie(
            SimpleNamespace(
                cookies=SimpleNamespace(get_dict=lambda: {"other": "value"}),
                headers=SimpleNamespace(get_list=lambda _: []),
            )
        )


def test_atomic_token_write_and_logout(settings):
    auth.save_token(settings, f"SESSDATA={SECRET}")
    assert settings.token_file.read_text() == f"SESSDATA={SECRET}"
    assert not list(settings.config_dir.glob(".token-*"))
    auth.logout(settings)
    assert not settings.token_file.exists()


def test_no_directories_created_by_import(tmp_path):
    config = tmp_path / "fresh-config"
    downloads = tmp_path / "fresh-downloads"
    env = {**os.environ, "BILIX_CONFIG_DIR": str(config), "BILIX_DOWNLOAD_DIR": str(downloads)}
    result = subprocess.run(
        [sys.executable, "-c", "import djhx_bilix.cli"], env=env, capture_output=True
    )
    assert result.returncode == 0
    assert not config.exists() and not downloads.exists()


def test_bad_configuration_is_actionable(settings):
    settings.config_dir.mkdir()
    settings.config_file.write_text("download_dir = 123", encoding="utf-8")
    with pytest.raises(InputError):
        load_settings()


@pytest.mark.parametrize("exception", [NetworkError("网络故障"), RuntimeError(SECRET)])
def test_cli_never_renders_exception_locals_or_secrets(monkeypatch, settings, exception):
    auth.save_token(settings, f"SESSDATA={SECRET}")

    def failure(self, url):
        headers = self.headers()
        assert SECRET in headers["Cookie"]
        raise exception

    monkeypatch.setattr(BilibiliClient, "fetch", failure)
    result = runner.invoke(cli.app, ["info", "BV1j4411W7F7"])
    assert result.exit_code == 1
    assert SECRET not in result.output
    assert "Cookie" not in result.output and "Traceback" not in result.output


def test_client_replaces_raw_request_exception(monkeypatch, settings):
    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, *args, **kwargs):
            raise RequestException(f"Cookie: SESSDATA={SECRET}")

    monkeypatch.setattr(requests, "Session", Session)
    with pytest.raises(NetworkError) as error:
        BilibiliClient(settings).fetch("BV1j4411W7F7")
    assert SECRET not in str(error.value)
    assert error.value.__suppress_context__


def test_login_success_response_is_never_printed(monkeypatch, settings):
    outputs = []
    generation = SimpleNamespace(
        raise_for_status=lambda: None,
        json=lambda: {"data": {"url": "https://example.test/qr", "qrcode_key": SECRET}},
    )
    polling = SimpleNamespace(
        raise_for_status=lambda: None,
        json=lambda: {"data": {"code": 0, "url": f"https://example.test?refresh={SECRET}"}},
        cookies=SimpleNamespace(get_dict=lambda: {"SESSDATA": SECRET}),
    )

    class Session:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, url, **kwargs):
            return generation if "generate" in url else polling

    monkeypatch.setattr(requests, "Session", Session)
    auth.login(settings, outputs.append)
    assert SECRET not in "\n".join(outputs)
    assert settings.token_file.read_text() == f"SESSDATA={SECRET}"
    assert not list(settings.config_dir.glob("login-*.png"))


def test_batch_failure_continues_and_returns_failure(monkeypatch, video_info):
    calls = []

    def fetch(self, url):
        calls.append(url)
        if "BV0000000000" in url:
            raise BilixError("无效视频")
        return video_info

    monkeypatch.setattr(BilibiliClient, "fetch", fetch)
    result = runner.invoke(cli.app, ["info", "BV0000000000", "BV1j4411W7F7", "--json"])
    records = json.loads(result.stdout)
    assert result.exit_code == 1
    assert len(calls) == 2 and len(records) == 2
    assert records[0]["ok"] is False and records[1]["ok"] is True


@pytest.mark.parametrize(
    "arguments",
    [
        ["download", "BV1j4411W7F7", "--codec", "garbage"],
        ["download", "BV1j4411W7F7", "-q", "999"],
        ["download", "BV1j4411W7F7", "--page", "3-1"],
    ],
)
def test_invalid_parameters_fail_before_network(monkeypatch, arguments):
    monkeypatch.setattr(BilibiliClient, "fetch", lambda *a: pytest.fail("unexpected network"))
    assert runner.invoke(cli.app, arguments).exit_code != 0


def test_dry_run_single_page_and_compatibility_alias(monkeypatch, video_info):
    monkeypatch.setattr(BilibiliClient, "fetch", lambda *a: video_info)
    monkeypatch.setattr(cli, "execute", lambda *a: pytest.fail("must not transfer"))
    for command in ("download", "video"):
        result = runner.invoke(cli.app, [command, "BV1j4411W7F7", "--page", "1", "--dry-run"])
        assert result.exit_code == 0, result.output
        assert "计划 1 项" in result.output


def test_file_info_without_positional_urls(monkeypatch, video_info, tmp_path):
    path = tmp_path / "urls.txt"
    path.write_text("# comment\nBV1j4411W7F7\n", encoding="utf-8-sig")
    monkeypatch.setattr(BilibiliClient, "fetch", lambda *a: video_info)
    result = runner.invoke(cli.app, ["video", "-i", "-o", str(path)])
    assert result.exit_code == 0, result.output


def test_middle_page_failure_does_not_skip_later_pages(monkeypatch, video_info):
    pages = video_info.pages + (
        Page(2, "second", video_info.url + "?p=2", 4, "200"),
        Page(3, "third", video_info.url + "?p=3", 4, "300"),
    )
    calls = []

    def fetch(self, url):
        calls.append(url)
        if "p=2" in url:
            raise NetworkError("second page failed")
        return replace(video_info, url=url, pages=pages, cid="300" if "p=3" in url else "100")

    monkeypatch.setattr(BilibiliClient, "fetch", fetch)
    result = runner.invoke(cli.app, ["download", "BV1j4411W7F7", "--dry-run"])
    assert result.exit_code == 1
    assert "计划 2 项" in result.output
    assert "失败 1" in result.output
    assert calls[-1].endswith("?p=3")


def test_root_legacy_arguments_use_same_entry(monkeypatch):
    invocations = []
    monkeypatch.setattr(cli, "app", lambda **kwargs: invocations.append(kwargs["args"]))
    monkeypatch.setattr(sys, "argv", ["bilix.exe", "-i", "BV1j4411W7F7"])
    cli.main()
    assert invocations == [["download", "-i", "BV1j4411W7F7"]]


@pytest.mark.parametrize("arguments", [["-h"], ["download", "-h"], ["auth", "status", "-h"]])
def test_short_help_never_requires_account_or_network(monkeypatch, arguments):
    monkeypatch.setattr(BilibiliClient, "fetch", lambda *a: pytest.fail("unexpected network"))
    result = runner.invoke(cli.app, arguments)
    assert result.exit_code == 0, result.output
    assert "Usage:" in result.output


def test_completion_options_reach_root_entry(monkeypatch):
    invocations = []
    monkeypatch.setattr(cli, "app", lambda **kwargs: invocations.append(kwargs["args"]))
    monkeypatch.setattr(sys, "argv", ["blx", "--show-completion", "bash"])
    cli.main()
    assert invocations == [["--show-completion", "bash"]]


def test_reported_output_path_remains_a_single_copyable_line(monkeypatch, video_info, tmp_path):
    monkeypatch.setattr(BilibiliClient, "fetch", lambda *a: video_info)
    output = tmp_path / ("长文件名" * 25 + ".mp4")
    monkeypatch.setattr(cli, "execute", lambda *a: DownloadResult(output, skipped=True))
    result = runner.invoke(cli.app, ["download", "BV1j4411W7F7", "--quiet"])
    assert result.exit_code == 0
    assert f"跳过已有文件：{output}\n" in result.stdout
