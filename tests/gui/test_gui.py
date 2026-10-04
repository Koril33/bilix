"""Offline UI and worker checks for the optional PySide6 front end."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

import qrcode  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from qrcode.image.pure import PyPNGImage  # noqa: E402

from djhx_bilix.errors import InputError, OperationCancelled  # noqa: E402
from djhx_bilix.gui import app, worker  # noqa: E402
from djhx_bilix.models import DownloadResult, VideoTarget  # noqa: E402
from djhx_bilix.operations import CancellationToken, StageEvent  # noqa: E402


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


def test_download_worker_continues_after_target_failure(
    monkeypatch, settings, video_info, tmp_path
):
    class Client:
        def __init__(self, _settings, *, cancel):
            assert cancel is not None

    monkeypatch.setattr(worker, "load_settings", lambda: settings)
    monkeypatch.setattr(worker, "BilibiliClient", Client)
    monkeypatch.setattr(
        worker,
        "discover",
        lambda _client, _url, _page, *, cancel: (
            VideoTarget(video_info.url, video_info, "P1 first"),
            VideoTarget(video_info.url + "?p=2", video_info, "P2 second"),
        ),
    )
    calls = []

    def execute(plan, _ffmpeg, _overwrite, progress, *, cancel, stage):
        calls.append(plan)
        stage(StageEvent("downloading"))
        progress("video", 100, 100)
        progress("audio", 100, 100)
        if len(calls) == 2:
            raise InputError("模拟第二项失败")
        return DownloadResult(plan.output)

    monkeypatch.setattr(worker, "execute", execute)
    events = []
    options = worker.DownloadOptions(None, None, "aac", tmp_path, False, False, None)
    result = worker.run_download(
        (worker.JobSpec("BV1j4411W7F7"),), options, events.append, CancellationToken()
    )
    assert result == {"completed": 1, "skipped": 0, "failed": 1, "planned": 0}
    assert len(calls) == 2
    assert [
        event["state"]
        for event in events
        if event["type"] == "state" and event["state"] in ("completed", "failed")
    ] == [
        "completed",
        "failed",
    ]
    retry = [event["retry"] for event in events if event["type"] == "target"]
    assert retry == [
        worker.JobSpec("BV1j4411W7F7", "1"),
        worker.JobSpec("BV1j4411W7F7", "2"),
    ]


def test_worker_cancellation_stops_before_next_source(monkeypatch, settings, video_info, tmp_path):
    token = CancellationToken()
    seen = []

    class Client:
        def __init__(self, _settings, *, cancel):
            pass

    monkeypatch.setattr(worker, "load_settings", lambda: settings)
    monkeypatch.setattr(worker, "BilibiliClient", Client)

    def discover(_client, url, _page, *, cancel):
        seen.append(url)
        return (VideoTarget(video_info.url, video_info),)

    monkeypatch.setattr(worker, "discover", discover)

    def execute(plan, _ffmpeg, _overwrite, _progress, *, cancel, stage):
        token.cancel()
        return DownloadResult(plan.output)

    monkeypatch.setattr(worker, "execute", execute)
    options = worker.DownloadOptions(None, None, "aac", tmp_path, False, False, None)
    with pytest.raises(OperationCancelled):
        worker.run_download(
            (worker.JobSpec("BV1j4411W7F7"), worker.JobSpec("BV12R4y1J75d")),
            options,
            lambda _event: None,
            token,
        )
    assert len(seen) == 1


def test_discovered_parts_are_all_retryable_when_first_part_is_canceled(
    monkeypatch, settings, video_info, tmp_path
):
    class Client:
        def __init__(self, _settings, *, cancel):
            pass

    monkeypatch.setattr(worker, "load_settings", lambda: settings)
    monkeypatch.setattr(worker, "BilibiliClient", Client)
    monkeypatch.setattr(
        worker,
        "discover",
        lambda *_args, **_kwargs: (
            VideoTarget(video_info.url, video_info, "P1 first"),
            VideoTarget(video_info.url + "?p=2", video_info, "P2 second"),
        ),
    )
    monkeypatch.setattr(
        worker,
        "execute",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OperationCancelled("已取消")),
    )
    events = []
    options = worker.DownloadOptions(None, None, "aac", tmp_path, False, False, None)
    with pytest.raises(OperationCancelled):
        worker.run_download(
            (worker.JobSpec("BV1j4411W7F7"),), options, events.append, CancellationToken()
        )
    assert [event["key"] for event in events if event["type"] == "target"] == [
        (0, 0),
        (0, 1),
    ]


def test_gui_buttons_drive_plan_and_failed_retry(qtbot, monkeypatch, tmp_path):
    window = app.MainWindow()
    qtbot.addWidget(window)
    window.urls_edit.setPlainText("BV1j4411W7F7")
    window.output_edit.setText(str(tmp_path))
    calls = []

    def download(specs, options, emit, cancel):
        calls.append((specs, options))
        emit({"type": "target", "key": (0, 0), "label": "P1 test", "retry": specs[0]})
        emit(
            {
                "type": "plan",
                "key": (0, 0),
                "title": "test",
                "output": str(tmp_path / "test.mp4"),
                "selection": "1080P / AVC / AAC",
                "warnings": (),
            }
        )
        state = "planned" if options.dry_run else "failed"
        emit({"type": "state", "key": (0, 0), "state": state, "detail": "模拟失败"})
        return {
            "completed": 0,
            "skipped": 0,
            "failed": int(not options.dry_run),
            "planned": int(options.dry_run),
        }

    monkeypatch.setattr(app, "run_download", download)
    qtbot.mouseClick(window.plan_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: window._thread is None, timeout=5000)
    assert calls[0][1].dry_run is True
    assert window.jobs_table.item(0, 1).text() == "已规划"
    qtbot.mouseClick(window.start_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: window._thread is None, timeout=5000)
    assert calls[1][1].dry_run is False
    assert window.retry_button.isEnabled()
    qtbot.mouseClick(window.retry_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: window._thread is None, timeout=5000)
    assert len(calls) == 3
    assert calls[2][0] == (worker.JobSpec("BV1j4411W7F7"),)


def test_global_download_error_marks_remaining_rows_failed_and_retryable(qtbot, monkeypatch):
    window = app.MainWindow()
    qtbot.addWidget(window)
    window.urls_edit.setPlainText("BV1j4411W7F7\nBV12R4y1J75d")
    errors = []
    monkeypatch.setattr(window, "_error", errors.append)
    monkeypatch.setattr(
        app,
        "run_download",
        lambda *_args: (_ for _ in ()).throw(InputError("模拟配置错误")),
    )
    qtbot.mouseClick(window.start_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: window._thread is None, timeout=5000)
    assert [window.jobs_table.item(row, 1).text() for row in range(2)] == ["失败", "失败"]
    assert window.retry_button.isEnabled()
    assert errors == ["模拟配置错误"]


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
    window.close()
    assert window._close_pending
    qtbot.waitUntil(lambda: window._thread is None and not window.isVisible(), timeout=5000)


def test_qr_login_and_account_status_are_offline(qtbot, monkeypatch):
    window = app.MainWindow()
    qtbot.addWidget(window)
    import io

    buffer = io.BytesIO()
    qrcode.make("offline-test", image_factory=PyPNGImage).save(buffer)

    def login(emit, _cancel):
        emit({"type": "login", "state": "qr_ready", "image": buffer.getvalue()})
        emit({"type": "login", "state": "scanned", "image": None})

    monkeypatch.setattr(app, "run_login", login)
    window._start_login()
    qtbot.waitUntil(lambda: window._thread is None, timeout=5000)
    assert "登录成功" in window.account_label.text()
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


def test_cancelled_status_query_clears_loading_message(qtbot, monkeypatch):
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


def test_settings_saved_for_cli_and_used_as_download_default(qtbot, tmp_path):
    window = app.MainWindow()
    qtbot.addWidget(window)
    destination = tmp_path / "新的下载目录"
    window.default_output_edit.setText(str(destination))
    window.ffmpeg_edit.setText("")
    window._save_settings()
    assert window._settings is not None
    assert window._settings.config_file.read_text(encoding="utf-8").startswith("download_dir = ")
    assert window.output_edit.text() == str(destination)


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


def test_progress_label_tracks_download_and_media_stage(qtbot):
    window = app.MainWindow()
    qtbot.addWidget(window)
    window._prepare_queue((worker.JobSpec("BV1j4411W7F7"),))
    key = (0, 0)
    window._on_event(
        {
            "type": "progress",
            "key": key,
            "streams": {"video": (50, 100), "audio": (25, 100)},
        }
    )
    assert window.progress_bar.value() == 37
    assert window.progress_bar.format() == "%p%"
    window._on_event({"type": "stage", "key": key, "stage": "checking_video", "detail": ""})
    assert window.progress_bar.format() == "校验视频…"


@pytest.mark.parametrize("state", ["completed", "skipped"])
def test_finished_job_keeps_output_path_visible(qtbot, tmp_path, state):
    window = app.MainWindow()
    qtbot.addWidget(window)
    window._prepare_queue((worker.JobSpec("BV1j4411W7F7"),))
    output = str(tmp_path / "video.mp4")
    window._on_event(
        {
            "type": "plan",
            "key": (0, 0),
            "title": "video",
            "output": output,
            "selection": "1080P / AVC / AAC",
            "warnings": (),
        }
    )
    window._on_event(
        {
            "type": "state",
            "key": (0, 0),
            "state": state,
            "detail": "已完成校验与合并" if state == "completed" else "文件已存在",
            "output": output,
        }
    )
    assert output in window.jobs_table.item(0, 3).text()
    assert window.jobs_table.item(0, 0).data(app._OUTPUT_ROLE) == output


def test_multi_part_rows_stay_grouped_with_their_source(qtbot):
    window = app.MainWindow()
    qtbot.addWidget(window)
    first = worker.JobSpec("BV1j4411W7F7")
    second = worker.JobSpec("BV12R4y1J75d")
    window._prepare_queue((first, second))
    window._on_event({"type": "target", "key": (0, 0), "label": "P1 first", "retry": first})
    window._on_event({"type": "target", "key": (0, 1), "label": "P2 second", "retry": first})
    window._on_event({"type": "state", "key": (1, 0), "state": "failed", "detail": "test"})
    assert [window.jobs_table.item(row, 0).text() for row in range(3)] == [
        "P1 first",
        "P2 second",
        second.source,
    ]
    assert window.jobs_table.item(2, 1).text() == "失败"


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
