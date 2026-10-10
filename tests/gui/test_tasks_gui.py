"""GUI history, independent previews and per-source selection contracts."""

import os
from dataclasses import replace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import Qt  # noqa: E402

from djhx_bilix import tasks  # noqa: E402
from djhx_bilix.config import load_settings  # noqa: E402
from djhx_bilix.errors import InputError, NetworkError  # noqa: E402
from djhx_bilix.gui import app, worker  # noqa: E402
from djhx_bilix.models import DownloadResult, Page  # noqa: E402
from djhx_bilix.operations import CancellationToken  # noqa: E402


def setup_window(qtbot, monkeypatch, video_info):
    window = app.MainWindow()
    qtbot.addWidget(window)
    window.urls_edit.setPlainText(video_info.url)
    monkeypatch.setattr(tasks.BilibiliClient, "fetch", lambda *_a: video_info)
    window._start_info()
    qtbot.waitUntil(lambda: window._thread is None, timeout=5000)
    return window


def wait(qtbot, window):
    qtbot.waitUntil(lambda: window._thread is None, timeout=5000)


def test_history_retry_selected_snapshot_keeps_other_rows(qtbot, monkeypatch, video_info):
    pages = video_info.pages + (Page(2, "second", video_info.url + "?p=2", 4, "200"),)

    def fetch(_self, url):
        return replace(video_info, pages=pages, url=url, cid="200" if "p=2" in url else "100")

    window = setup_window(qtbot, monkeypatch, video_info)
    monkeypatch.setattr(tasks.BilibiliClient, "fetch", fetch)
    window._start_info()
    wait(qtbot, window)
    calls = []

    def execute(plan, *a, **kw):
        calls.append(plan.video.quality)
        raise NetworkError("测试失败")

    monkeypatch.setattr(tasks, "execute", execute)
    window.quality_combo.setCurrentIndex(window.quality_combo.findData(32))
    window._start_download()
    wait(qtbot, window)
    assert len(window.history_model.tasks) == 2
    first_id = next(iter(window.session.tasks))
    original_summary = window.session.batches[next(iter(window.session.batches))].summary
    window.quality_combo.setCurrentIndex(window.quality_combo.findData(16))
    node = window.history_model.tasks[first_id]
    window.jobs_view.setCurrentIndex(
        window.history_filter.mapFromSource(window.history_model.row_index(node))
    )
    window._retry_selected()
    wait(qtbot, window)
    assert calls == [32, 32, 32]
    assert len(window.history_model.tasks) == 2
    assert len(window.session.tasks[first_id].attempts) == 2
    assert window.session.batches[next(iter(window.session.batches))].summary == original_summary
    window._show_attempts()
    assert "尝试 1" in window.info_text.toPlainText() and "尝试 2" in window.info_text.toPlainText()


def test_preview_preserves_task_history_and_is_read_only(qtbot, monkeypatch, video_info):
    window = setup_window(qtbot, monkeypatch, video_info)
    monkeypatch.setattr(
        tasks, "execute", lambda *_a, **_k: (_ for _ in ()).throw(NetworkError("失败"))
    )
    window._start_download()
    wait(qtbot, window)
    before = dict(window.session.tasks)
    window.urls_edit.setPlainText(video_info.url)
    window._start_info()
    wait(qtbot, window)
    window._start_download(True)
    wait(qtbot, window)
    assert window.session.tasks == before and len(window.history_model.tasks) == 1
    assert "新建" in window.preview_text.toPlainText()


def test_readable_metadata_and_empty_part_selection_rejected(qtbot, monkeypatch, video_info):
    pages = video_info.pages + (Page(2, "second", video_info.url + "?p=2", 4, "200"),)
    window = setup_window(
        qtbot, monkeypatch, replace(video_info, pages=pages, url=video_info.url + "?p=2")
    )
    window._start_info()
    wait(qtbot, window)
    root = window.metadata_tree.topLevelItem(0)
    assert root.child(0).checkState(0) == Qt.CheckState.Unchecked
    assert root.child(1).checkState(0) == Qt.CheckState.Checked
    assert window._inputs()[0].page == "2"
    assert (
        "作者" in window.parts_info.toPlainText()
        and "available_streams" not in window.parts_info.toPlainText()
    )
    root.child(1).setCheckState(0, Qt.CheckState.Unchecked)
    with pytest.raises(InputError, match="勾选"):
        window._inputs()
    window.page_edit.setText("all")
    window._reset_part_checks()
    assert window._inputs()[0].page == "1,2"
    window._copy_metadata()
    assert "available_streams" in app.QApplication.clipboard().text()


def test_stale_info_after_input_edit_is_ignored(qtbot, video_info):
    window = app.MainWindow()
    qtbot.addWidget(window)
    window.urls_edit.setPlainText(video_info.url)
    window._info_generation = window._input_generation
    window.urls_edit.setPlainText("BV12R4y1J75d")
    window._on_event(dict(type="info", index=0, metadata=video_info.public_dict()))
    assert not window._metadata


def test_filter_retry_and_clear_use_ids_and_do_not_touch_files(
    qtbot, monkeypatch, video_info, tmp_path
):
    window = setup_window(qtbot, monkeypatch, video_info)
    output = tmp_path / "output.mp4"
    output.write_bytes(b"media")
    monkeypatch.setattr(tasks, "execute", lambda *_a, **_k: DownloadResult(output, True))
    window._start_download()
    wait(qtbot, window)
    window.filter_combo.setCurrentIndex(window.filter_combo.findData("failed"))
    assert window.history_filter.rowCount() == 0
    window._clear_records(frozenset({"skipped"}))
    assert not window.session.tasks and not window.history_model.tasks
    assert output.read_bytes() == b"media"


def test_settings_file_value_effective_env_and_explicit_task_override(qtbot, monkeypatch, tmp_path):
    window = app.MainWindow()
    qtbot.addWidget(window)
    assert "BILIX_DOWNLOAD_DIR" in window.settings_hint.text()
    window.output_edit.setText(str(tmp_path / "task"))
    window._output_edited = True
    window.default_output_edit.setText(str(tmp_path / "file"))
    window.ffmpeg_edit.setText("file-ffmpeg")
    monkeypatch.setenv("BILIX_FFMPEG", "env-ffmpeg")
    window._save_settings()
    assert window.output_edit.text() == str(tmp_path / "task")
    assert window.ffmpeg_edit.text() == "file-ffmpeg"
    assert window._options(False).ffmpeg == "env-ffmpeg"
    assert load_settings().file_download_dir == tmp_path / "file"


def test_offline_credential_state_does_not_access_network(qtbot, monkeypatch, settings):
    monkeypatch.setattr(
        tasks.BilibiliClient, "fetch", lambda *_a: pytest.fail("startup must be offline")
    )
    settings.config_dir.mkdir()
    settings.token_file.write_text("SESSDATA=FAKE_OFFLINE_DUMMY", encoding="utf-8")
    window = app.MainWindow()
    qtbot.addWidget(window)
    assert "待验证" in window.account_label.text()
    settings.token_file.write_text("broken", encoding="utf-8")
    window._offline_account()
    assert "格式错误" in window.account_label.text()


def test_close_running_can_return_without_cancel(qtbot, monkeypatch):
    window = app.MainWindow()
    qtbot.addWidget(window)
    window.show()

    def operation(_emit, cancel):
        cancel.wait(3)
        cancel.raise_if_cancelled()

    window._start_operation("download", operation)
    monkeypatch.setattr(
        app.QMessageBox, "question", lambda *_a, **_k: app.QMessageBox.StandardButton.No
    )
    window.close()
    assert not window._cancel.cancelled() and not window._close_pending
    window._cancel_active()
    wait(qtbot, window)


def test_worker_adapter_and_failure_categories(monkeypatch, video_info, tmp_path):
    monkeypatch.setattr(tasks.BilibiliClient, "fetch", lambda *_a: video_info)
    monkeypatch.setattr(
        tasks, "execute", lambda *_a, **_k: (_ for _ in ()).throw(NetworkError("失败"))
    )
    events = []
    result = worker.run_download(
        (worker.JobSpec(video_info.url),),
        worker.DownloadOptions(None, None, "aac", tmp_path, False, False, None),
        events.append,
        CancellationToken(),
    )
    assert result["failed"] == 1 and result["source_failed"] == 0
    assert any(e.get("attempt") and e["attempt"].error_code == "network" for e in events)


def test_native_ime_composition_hides_hint_and_restores_after_commit_or_cancel(qtbot):
    from PySide6.QtGui import QInputMethodEvent
    from PySide6.QtWidgets import QApplication

    window = app.MainWindow()
    qtbot.addWidget(window)
    window.show()
    window._open_draft(read_clipboard=False)
    editor = window.urls_edit
    editor.setFocus()
    QApplication.sendEvent(editor, QInputMethodEvent("zhongwen", []))
    assert editor.toPlainText() == "" and editor.placeholderText() == ""
    commit = QInputMethodEvent()
    commit.setCommitString("中文")
    QApplication.sendEvent(editor, commit)
    assert editor.toPlainText() == "中文" and editor.placeholderText() == editor.hint
    editor.clear()
    QApplication.sendEvent(editor, QInputMethodEvent("shuru", []))
    QApplication.sendEvent(editor, QInputMethodEvent())
    assert editor.toPlainText() == "" and editor.placeholderText() == editor.hint


def test_url_tab_navigation_reaches_actions_without_changing_input(qtbot):
    window = app.MainWindow()
    qtbot.addWidget(window)
    window.show()
    window._open_draft(read_clipboard=False)
    editor = window.urls_edit
    editor.setPlainText("BV1j4411W7F7")
    editor.setFocus()
    window._draft_dialog.activateWindow()
    qtbot.waitUntil(editor.hasFocus)
    qtbot.keyClick(editor, Qt.Key.Key_Tab)
    assert not editor.hasFocus()
    assert window._draft_dialog.focusWidget() is not editor
    qtbot.keyClick(
        window._draft_dialog.focusWidget(), Qt.Key.Key_Tab, Qt.KeyboardModifier.ShiftModifier
    )
    assert editor.hasFocus() and editor.toPlainText() == "BV1j4411W7F7"


def test_wayland_startup_leaves_space_for_compositor_panel_and_decoration(qtbot, monkeypatch):
    monkeypatch.setattr(app.QApplication, "platformName", staticmethod(lambda: "wayland"))
    window = app.MainWindow()
    qtbot.addWidget(window)
    assert window.height() <= max(240, window.screen().availableGeometry().height() - 80)
