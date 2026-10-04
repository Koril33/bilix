import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from curl_cffi.requests.exceptions import RequestException

from djhx_bilix import auth, config, media
from djhx_bilix.bilibili.client import BilibiliClient
from djhx_bilix.config import load_settings, save_settings
from djhx_bilix.errors import InputError, OperationCancelled
from djhx_bilix.operations import CancellationToken


def test_ffmpeg_cancellation_terminates_active_process(monkeypatch):
    processes = []

    class HangingProcess:
        def __init__(self, *args, **kwargs):
            self.returncode = None
            self.terminated = False
            processes.append(self)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def poll(self):
            return self.returncode

        def terminate(self):
            self.terminated = True
            self.returncode = -15

        def wait(self, timeout=None):
            return self.returncode

    monkeypatch.setattr(media.subprocess, "Popen", HangingProcess)
    token = CancellationToken()
    timer = threading.Timer(0.05, token.cancel)
    timer.start()
    try:
        with pytest.raises(OperationCancelled):
            media.FFmpeg(Path("ffmpeg"))._run(["-version"], cancel=token)
    finally:
        timer.join(timeout=1)
    assert len(processes) == 1 and processes[0].terminated


def test_cancelled_metadata_request_does_not_parse_or_continue(monkeypatch, settings):
    token = CancellationToken()
    requests = []

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, url, **kwargs):
            requests.append(url)
            token.cancel()
            return SimpleNamespace(raise_for_status=lambda: None, text="invalid")

    monkeypatch.setattr(auth.requests, "Session", Session)
    client = BilibiliClient(settings, cancel=token)
    with pytest.raises(OperationCancelled):
        client.fetch("https://www.bilibili.com/video/BV1j4411W7F7")
    assert len(requests) == 1


def test_qr_login_emits_image_and_scanned_state_without_secret(monkeypatch, settings):
    secret = "DUMMY_PRIVATE_VALUE"
    responses = [
        SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"data": {"code": 86090}}),
        SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"data": {"code": 0}},
            cookies=SimpleNamespace(get_dict=lambda: {"SESSDATA": secret}),
        ),
    ]

    class Session:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, url, **kwargs):
            if "generate" in url:
                return SimpleNamespace(
                    raise_for_status=lambda: None,
                    json=lambda: {"data": {"url": "https://example.test/qr", "qrcode_key": secret}},
                )
            return responses.pop(0)

    monkeypatch.setattr(auth.requests, "Session", Session)
    monkeypatch.setattr(auth.time, "sleep", lambda _: None)
    notifications, events = [], []
    auth.login(settings, notifications.append, event=events.append)
    assert [event.state for event in events] == ["qr_ready", "scanned", "success"]
    assert events[0].qr_image.startswith(b"\x89PNG")
    assert all(event.qr_image is None for event in events[1:])
    assert secret not in "".join(map(repr, events))
    assert settings.token_file.read_text() == f"SESSDATA={secret}"
    assert not list(settings.config_dir.glob("login-*.png"))


def test_cancelled_qr_login_does_not_save_credentials(monkeypatch, settings):
    class Session:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, url, **kwargs):
            assert "generate" in url, "cancelled login must not poll"
            return SimpleNamespace(
                raise_for_status=lambda: None,
                json=lambda: {"data": {"url": "https://example.test/qr", "qrcode_key": "secret"}},
            )

    monkeypatch.setattr(auth.requests, "Session", Session)
    token = CancellationToken()
    events = []

    def event(value):
        events.append(value)
        if value.state == "qr_ready":
            token.cancel()

    with pytest.raises(OperationCancelled):
        auth.login(settings, lambda _: None, cancel=token, event=event)
    assert [entry.state for entry in events] == ["qr_ready", "cancelled"]
    assert not settings.token_file.exists()
    assert not list(settings.config_dir.glob("login-*.png"))


def test_cancelled_login_request_reports_cancelled_not_network_error(monkeypatch, settings):
    token = CancellationToken()

    class Session:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, url, **kwargs):
            token.cancel()
            raise RequestException("request included a secret")

    monkeypatch.setattr(auth.requests, "Session", Session)
    events = []
    with pytest.raises(OperationCancelled):
        auth.login(settings, lambda _: None, cancel=token, event=events.append)
    assert [event.state for event in events] == ["cancelled"]
    assert not settings.token_file.exists()
    assert not list(settings.config_dir.glob("login-*.png"))


def test_gui_settings_save_is_atomic_and_loadable(settings, monkeypatch, tmp_path):
    monkeypatch.delenv("BILIX_DOWNLOAD_DIR")
    directory = tmp_path / "下载 目录"
    saved = save_settings(settings, download_dir=directory, ffmpeg="C:\\Tools\\ffmpeg.exe")
    assert saved.download_dir == directory
    assert load_settings().download_dir == directory
    assert load_settings().ffmpeg == "C:\\Tools\\ffmpeg.exe"
    original = settings.config_file.read_bytes()
    with pytest.raises(InputError):
        save_settings(settings, download_dir=directory, ffmpeg=" ")
    assert settings.config_file.read_bytes() == original

    def fail_replace(*args):
        raise OSError("injected write failure")

    monkeypatch.setattr(config.os, "replace", fail_replace)
    with pytest.raises(OSError):
        save_settings(settings, download_dir=tmp_path / "other", ffmpeg=None)
    assert settings.config_file.read_bytes() == original
    assert not list(settings.config_dir.glob(".config-*"))
