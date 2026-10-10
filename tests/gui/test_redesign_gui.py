"""Focused 1.7.4 scheduling and desktop regressions, without live services."""

from dataclasses import replace
from threading import Event
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt, QThread
from PySide6.QtGui import QInputMethodEvent
from PySide6.QtWidgets import QApplication

from djhx_bilix.bilibili.client import BilibiliClient
from djhx_bilix.errors import NetworkError
from djhx_bilix.gui import app


def window_with_info(qtbot, monkeypatch, video_info):
    monkeypatch.setattr(BilibiliClient, "fetch", lambda self, url: replace(video_info, url=url))
    window = app.MainWindow()
    qtbot.addWidget(window)
    window.show()
    return window


def wait_parsed(qtbot, window):
    qtbot.waitUntil(lambda: window._thread is None and window._parse_complete, timeout=5000)


def test_auto_parse_partial_success_duplicates_and_main_thread(qtbot, monkeypatch, video_info):
    window = window_with_info(qtbot, monkeypatch, video_info)
    thread_ids = []
    original = window._on_event

    def on_event(event):
        thread_ids.append(QThread.currentThread())
        original(event)

    monkeypatch.setattr(window, "_on_event", on_event)
    window._open_draft(
        text=f"{video_info.url}\nhttps://evil.example/x\n{video_info.url}", read_clipboard=False
    )
    wait_parsed(qtbot, window)
    assert len(window._inputs()) == 2 and window._parse_errors == 1
    assert "未加入下载" in window.parse_summary.full_text
    assert window.start_button.isEnabled()
    assert all(thread is QApplication.instance().thread() for thread in thread_ids)
    window.metadata_tree.topLevelItem(0).setCheckState(0, Qt.CheckState.Unchecked)
    assert len(window._inputs()) == 1


def test_old_events_and_done_cannot_replace_edited_draft(qtbot, monkeypatch, video_info):
    started, release = Event(), Event()
    calls = []

    def fetch(self, url):
        calls.append(url)
        if len(calls) == 1:
            started.set()
            release.wait(3)
        return replace(video_info, url=url, title="new" if "BV12" in url else "old")

    window = window_with_info(qtbot, monkeypatch, video_info)
    monkeypatch.setattr(BilibiliClient, "fetch", fetch)
    window._open_draft(text=video_info.url, read_clipboard=False)
    window._request_parse()
    qtbot.waitUntil(started.is_set)
    window.urls_edit.setPlainText("BV12R4y1J75d")
    window._request_parse()
    release.set()
    wait_parsed(qtbot, window)
    assert len(calls) == 2
    assert next(iter(window._metadata.values()))["title"] == "new"


def test_ime_defers_auto_parse_and_explicit_cancel_does_not_restart(qtbot, monkeypatch, video_info):
    window = window_with_info(qtbot, monkeypatch, video_info)
    calls = []

    def fetch(self, url):
        calls.append(url)
        return replace(video_info, url=url)

    monkeypatch.setattr(BilibiliClient, "fetch", fetch)
    window._open_draft(text=video_info.url, read_clipboard=False)
    QApplication.sendEvent(window.urls_edit, QInputMethodEvent("zhong", []))
    qtbot.wait(550)
    assert not calls
    QApplication.sendEvent(window.urls_edit, QInputMethodEvent())
    wait_parsed(qtbot, window)
    assert len(calls) == 1
    window._start_operation("info", lambda emit, cancel: cancel.wait(2))
    window._cancel_active()
    qtbot.waitUntil(lambda: window._thread is None)
    qtbot.wait(550)
    assert len(calls) == 1 and not window.start_button.isEnabled()


def test_busy_draft_waits_then_parses_without_appending_download(qtbot, monkeypatch, video_info):
    window = window_with_info(qtbot, monkeypatch, video_info)
    window._start_operation("test", lambda emit, cancel: cancel.wait(3))
    window._open_draft(text=video_info.url, read_clipboard=False)
    window._request_parse()
    assert window.urls_edit.isEnabled() and not window.start_button.isEnabled()
    assert window._pending_parse and not window.session.batches
    window._cancel_active()
    wait_parsed(qtbot, window)
    assert window.start_button.isEnabled() and not window.session.batches


@pytest.mark.parametrize("state", ["valid", "expired", "network"])
def test_token_auto_validation_once_and_failure_distinction(
    qtbot, monkeypatch, settings, video_info, state
):
    settings.config_dir.mkdir()
    settings.token_file.write_text("SESSDATA=FAKE_OFFLINE", encoding="utf-8")
    calls = []

    def status(emit, cancel):
        calls.append(True)
        if state == "network":
            raise NetworkError("offline")
        return {
            "logged_in": state == "valid",
            "expired": state == "expired",
            "name": "offline",
            "vip": True,
            "vip_type": 2,
        }

    monkeypatch.setattr(app, "run_status", status)
    window = window_with_info(qtbot, monkeypatch, video_info)
    window._open_draft(text=video_info.url, read_clipboard=False)
    wait_parsed(qtbot, window)
    assert len(calls) == 1
    if state == "valid":
        assert "大会员" in window.account_button.text()
    elif state == "expired":
        assert "失效" in window.account_button.text()
    else:
        assert "待验证" in window.account_button.text()
        assert settings.token_file.exists()
    window._open_settings(0)
    qtbot.wait(30)
    assert len(calls) == 1


def test_external_credential_delete_rejects_old_status_result(qtbot, monkeypatch, settings):
    settings.config_dir.mkdir()
    settings.token_file.write_text("SESSDATA=FAKE_OFFLINE", encoding="utf-8")
    started, release = Event(), Event()

    def status(emit, cancel):
        started.set()
        release.wait(2)
        return {"logged_in": True, "name": "stale"}

    monkeypatch.setattr(app, "run_status", status)
    window = app.MainWindow()
    qtbot.addWidget(window)
    qtbot.waitUntil(started.is_set)
    settings.token_file.unlink()
    release.set()
    qtbot.waitUntil(lambda: window._thread is None)
    assert window.account_button.text() == "未登录 ▾"


def test_minimize_restore_lost_tray_and_close_draft_keep_worker(qtbot, monkeypatch, video_info):
    window = window_with_info(qtbot, monkeypatch, video_info)
    monkeypatch.setattr(window, "_tray_available", lambda: True)
    monkeypatch.setattr(window.tray, "show", lambda: None)
    window._open_draft(read_clipboard=False)
    window._start_operation("test", lambda emit, cancel: cancel.wait(2))
    window.showMinimized()
    qtbot.waitUntil(lambda: not window.isVisible())
    assert window._in_tray and window._thread is not None
    monkeypatch.setattr(window, "_tray_available", lambda: False)
    window._check_tray()
    assert window.isVisible() and window._draft_dialog.isVisible()
    window._draft_dialog.reject()
    assert not window._cancel.cancelled()
    window._cancel_active()
    qtbot.waitUntil(lambda: window._thread is None)


def test_notifications_are_once_per_batch_and_cancel_has_no_completed_notice(qtbot, monkeypatch):
    window = app.MainWindow()
    qtbot.addWidget(window)
    messages = []
    monkeypatch.setattr(window, "_tray_available", lambda: True)
    monkeypatch.setattr(
        window,
        "tray",
        SimpleNamespace(
            supportsMessages=lambda: True,
            showMessage=lambda *args: messages.append(args),
            hide=lambda: None,
        ),
    )
    counts = dict(completed=2, skipped=1, failed=1, source_failed=1, canceled=0, source_canceled=0)
    window._download_batch = "first"
    window._notify_batch(counts)
    window._notify_batch(counts)
    window._download_batch = "canceled"
    window._notify_batch({**counts, "canceled": 1})
    assert len(messages) == 1 and "有失败项目" in messages[0][0]
    assert "读取失败 1" in messages[0][1]


def test_gui_settings_cancel_apply_and_overwrite_not_restored(qtbot, tmp_path):
    window = app.MainWindow()
    qtbot.addWidget(window)
    window._open_settings()
    window.tray_check.setChecked(False)
    window._settings_dialog.reject()
    assert window.tray_check.isChecked()
    window.tray_check.setChecked(False)
    assert window._save_settings()
    window.overwrite_check.setChecked(True)
    window._remember_media_options()
    other = app.MainWindow()
    qtbot.addWidget(other)
    assert not other._tray_enabled and not other.overwrite_check.isChecked()
