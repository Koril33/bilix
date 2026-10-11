"""Offline UI and worker checks for the optional PySide6 front end."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

import qrcode  # noqa: E402
from qrcode.image.pure import PyPNGImage  # noqa: E402

from djhx_bilix.errors import InputError, OperationCancelled  # noqa: E402
from djhx_bilix.gui import app, worker  # noqa: E402
from djhx_bilix.operations import CancellationToken  # noqa: E402


def test_input_validation_and_page_override(qtbot):
    window = app.MainWindow()
    qtbot.addWidget(window)
    window.urls_edit.setPlainText(
        "# note\nBV1j4411W7F7\n\nhttps://www.bilibili.com/video/BV1j4411W7F7?p=2"
    )
    window.page_edit.setText("all")
    specs = window._inputs()
    assert len(specs) == 2
    assert [spec.page for spec in specs] == ["all", "all"]
    window.page_edit.setText("3-1")
    with pytest.raises(InputError):
        window._inputs()
    window.page_edit.setText("")
    window.urls_edit.setPlainText("https://evil.example/steal")
    with pytest.raises(InputError, match="第 1 行"):
        window._inputs()
    window.urls_edit.setPlainText("# note\n\nBV1j4411W7F7\nhttps://evil.example/steal")
    with pytest.raises(InputError, match="第 4 行"):
        window._inputs()


def test_import_urls_handles_bom_comments_and_existing_text(qtbot, tmp_path, monkeypatch):
    window = app.MainWindow()
    qtbot.addWidget(window)
    list_file = tmp_path / "links.txt"
    list_file.write_text("\ufeff# comment\nBV1j4411W7F7\n\nBV12R4y1J75d\n", encoding="utf-8")
    monkeypatch.setattr(
        app.QFileDialog, "getOpenFileName", lambda *_args: (str(list_file), "文本文件")
    )
    window.urls_edit.setPlainText("BV1yG4y1R7xR")
    window._import_urls()
    assert window.urls_edit.toPlainText().splitlines() == [
        "BV1yG4y1R7xR",
        "BV1j4411W7F7",
        "BV12R4y1J75d",
    ]


def test_close_requests_cancellation_and_waits_for_worker(qtbot, monkeypatch):
    window = app.MainWindow()
    qtbot.addWidget(window)
    window.show()

    def doctor(_emit, cancel):
        while not cancel.wait(0.01):
            pass
        raise OperationCancelled("操作已取消")

    monkeypatch.setattr(app, "run_doctor", doctor)
    window._start_doctor()
    qtbot.waitUntil(lambda: window._thread is not None, timeout=5000)
    monkeypatch.setattr(
        app.QMessageBox, "question", lambda *_a, **_k: app.QMessageBox.StandardButton.Yes
    )
    window._request_exit()
    assert window._close_pending
    qtbot.waitUntil(lambda: window._thread is None and not window.isVisible(), timeout=5000)


def test_qr_login_and_account_status_are_offline(qtbot, monkeypatch):
    window = app.MainWindow()
    qtbot.addWidget(window)
    import io

    buffer = io.BytesIO()
    qrcode.make("offline-test", image_factory=PyPNGImage).save(buffer)

    def login(emit, _cancel):
        settings = app.load_settings()
        settings.config_dir.mkdir(parents=True, exist_ok=True)
        settings.token_file.write_text("SESSDATA=FAKE_OFFLINE_DUMMY", encoding="utf-8")
        emit({"type": "login", "state": "qr_ready", "image": buffer.getvalue()})
        emit({"type": "login", "state": "scanned", "image": None})

    monkeypatch.setattr(app, "run_login", login)
    window._start_login()
    qtbot.waitUntil(lambda: window._thread is None, timeout=5000)
    assert window._qr_dialog is None and app.load_settings().token_file.is_file()
    monkeypatch.setattr(
        app,
        "run_status",
        lambda _emit, _cancel: {
            "logged_in": True,
            "name": "test",
            "uid": 123,
            "level": 4,
            "vip": False,
        },
    )
    window._start_status()
    qtbot.waitUntil(lambda: window._thread is None, timeout=5000)
    assert "UID 123" in window.account_label.text()


def test_cancelled_status_query_clears_loading_message(qtbot, monkeypatch, settings):
    settings.config_dir.mkdir()
    settings.token_file.write_text("SESSDATA=FAKE_OFFLINE_DUMMY", encoding="utf-8")
    window = app.MainWindow()
    qtbot.addWidget(window)
    monkeypatch.setattr(
        app,
        "run_status",
        lambda _emit, _cancel: (_ for _ in ()).throw(OperationCancelled("操作已取消")),
    )
    window._start_status()
    qtbot.waitUntil(lambda: window._thread is None, timeout=5000)
    assert window.account_label.text() == "账号状态查询已取消。"


def test_qr_png_is_rendered_in_memory(qtbot):
    window = app.MainWindow()
    qtbot.addWidget(window)
    import io

    buffer = io.BytesIO()
    qrcode.make("offline-test", image_factory=PyPNGImage).save(buffer)
    window._qr_label = app.QLabel()
    window._qr_status = app.QLabel()
    window._on_login_event({"state": "qr_ready", "image": buffer.getvalue()})
    assert window._qr_label.pixmap() is not None
    assert not window._qr_label.pixmap().isNull()
    assert "扫码" in window._qr_status.text()


def test_settings_saved_for_cli_and_environment_remains_effective(qtbot, tmp_path):
    window = app.MainWindow()
    qtbot.addWidget(window)
    destination = tmp_path / "新的下载目录"
    window.default_output_edit.setText(str(destination))
    window.ffmpeg_edit.setText("")
    window._save_settings()
    assert window._settings is not None
    assert window._settings.config_file.read_text(encoding="utf-8").startswith("download_dir = ")
    assert window.output_edit.text() == str(tmp_path / "downloads")
    assert window.default_output_edit.text() == str(destination)


def test_config_write_error_does_not_show_raw_os_path(qtbot, monkeypatch):
    window = app.MainWindow()
    qtbot.addWidget(window)
    messages = []
    monkeypatch.setattr(window, "_error", messages.append)
    monkeypatch.setattr(
        app,
        "save_settings",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(PermissionError("private/profile")),
    )
    window._save_settings()
    assert messages == ["无法保存设置，请检查配置目录权限"]


def test_unknown_worker_error_has_no_third_party_details(qtbot):
    token = CancellationToken()
    operation = worker.OperationWorker(
        lambda _emit, _cancel: (_ for _ in ()).throw(RuntimeError("secret-cookie=123")), token
    )
    results = []
    operation.done.connect(results.append)
    operation.run()
    assert results[0]["state"] == "error"
    assert "secret-cookie" not in results[0]["message"]


def test_smoke_test_constructs_window_and_checks_ffmpeg(qtbot, tmp_path, monkeypatch):
    executable = tmp_path / "ffmpeg.exe"
    executable.write_bytes(b"fake")
    monkeypatch.setattr(app, "find_ffmpeg", lambda _configured=None: executable)
    monkeypatch.setattr(app.FFmpeg, "version", lambda self: "ffmpeg test")
    assert app.main(["--smoke-test"]) == 0


def test_no_console_startup_error_uses_windows_message_box(monkeypatch):
    if os.name != "nt":
        pytest.skip("Windows gui-scripts behavior")
    import ctypes

    messages = []
    monkeypatch.setattr(app.sys, "stderr", None)
    monkeypatch.setattr(
        ctypes.windll.user32,
        "MessageBoxW",
        lambda _owner, message, _title, _flags: messages.append(message),
    )
    assert app.main(["--invalid-option"]) == 2
    assert messages == ["用法：bilix-gui [--smoke-test]"]
