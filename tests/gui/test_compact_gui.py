"""Focused 1.7.3 behavior checks without live accounts or network."""

import os
from dataclasses import replace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtGui import QInputMethodEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QScrollArea, QTreeView, QTreeWidgetItem  # noqa: E402

from djhx_bilix.errors import NetworkError  # noqa: E402
from djhx_bilix.gui.app import MainWindow  # noqa: E402
from djhx_bilix.models import Page, VideoTarget  # noqa: E402
from djhx_bilix.tasks import DownloadOptions, JobSpec  # noqa: E402


def test_compact_layout_and_dialogs_do_not_push_list(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    window.resize(700, 540)
    window.show()
    QApplication.processEvents()
    assert not window.centralWidget().findChildren(QScrollArea)
    assert isinstance(window.jobs_view, QTreeView)
    assert window.list_stack.currentWidget() is window.empty_label
    assert not window.cancel_button.isVisible() and not window.start_button.isVisible()
    assert window.new_button.isVisible()
    assert window.list_stack.height() > 350
    before = window.list_stack.geometry()
    window._open_draft(read_clipboard=False)
    QApplication.processEvents()
    assert window.list_stack.geometry() == before


def test_ime_blocks_shortcut(qtbot, monkeypatch):
    window = MainWindow()
    qtbot.addWidget(window)
    calls = []
    monkeypatch.setattr(window, "_start_download", lambda: calls.append(True))
    QApplication.sendEvent(window.urls_edit, QInputMethodEvent("zhong", []))
    window._shortcut_download()
    assert not calls
    QApplication.sendEvent(window.urls_edit, QInputMethodEvent("", []))
    window.start_button.setEnabled(True)
    window._shortcut_download()
    assert calls == [True]


def test_parts_range_is_explicit_and_selection_stays_per_source(qtbot, video_info):
    window = MainWindow()
    qtbot.addWidget(window)
    window.urls_edit.setPlainText(video_info.url + "\n" + video_info.url)
    window._info_generation = window._input_generation
    window._parse_total = 2
    for i in range(2):
        window.metadata_tree.addTopLevelItem(QTreeWidgetItem([video_info.url, ""]))
        info = replace(video_info, pages=video_info.pages + (Page(2, "P2", video_info.url, 4),))
        window._on_event(dict(type="info", index=i, metadata=info.public_dict()))
    window.metadata_tree.setCurrentItem(window.metadata_tree.topLevelItem(0))
    window._select_parts("none")
    window.part_range_edit.setText("2")
    window._apply_part_range()
    assert [s.page for s in window._inputs()] == ["2", "1,2"]
    window.page_edit.setText("1")
    assert [s.page for s in window._inputs()] == ["2", "1,2"]
    window._reset_part_checks()
    assert [s.page for s in window._inputs()] == ["1", "1"]


def test_source_failure_retry_and_parent_group_scope(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    options = DownloadOptions(None, None, "aac", tmp_path, False, False, None)
    batch = window.session.begin((JobSpec("BV1j4411W7F7"),), options)
    request = window.session.batches[batch].requests[0]
    window.session.source_state(request, "failed", window._on_event, NetworkError("网络失败"))
    window.session.finish(batch)
    window.filter_combo.setCurrentIndex(window.filter_combo.findData("failed"))
    window.jobs_view.setCurrentIndex(window.history_filter.index(0, 0))
    assert window._selected_ids() == ((), (request,))
    window._update_retry_button()
    assert window.retry_selected_action.isEnabled()
    batch = window.session.begin((JobSpec("BV1j4411W7F7"),), options)
    request = window.session.batches[batch].requests[0]
    target = VideoTarget(
        "https://www.bilibili.com/video/BV1j4411W7F7", label="video", page_number=1
    )
    ids = window.session.register(request, (target,))
    window.session.event(ids[0], window._on_event, state="failed", detail="失败")
    parent = window.history_model.sources[request]
    qtbot.wait(50)
    window.jobs_view.setCurrentIndex(
        window.history_filter.mapFromSource(window.history_model.row_index(parent))
    )
    assert window._selected_ids() == ((), ())


def test_filter_does_not_select_hidden_tasks(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    batch = window.session.begin(
        (JobSpec("BV1j4411W7F7"),), DownloadOptions(None, None, "aac", tmp_path, False, False, None)
    )
    request = window.session.batches[batch].requests[0]
    targets = tuple(
        VideoTarget(
            f"https://www.bilibili.com/video/BV1j4411W7F7?p={i}", label=f"part {i}", page_number=i
        )
        for i in (1, 2)
    )
    ids = window.session.register(request, targets)
    window.session.event(ids[0], window._on_event, state="failed", detail="失败")
    window.session.event(ids[1], window._on_event, state="canceled", detail="取消")
    window.session.source_state(request, "discovered", window._on_event)
    window.session.finish(batch)
    node = window.history_model.tasks[ids[1]]
    window.jobs_view.setCurrentIndex(
        window.history_filter.mapFromSource(window.history_model.row_index(node))
    )
    window.filter_combo.setCurrentIndex(window.filter_combo.findData("failed"))
    assert ids[1] not in window._selected_ids()[0]
    assert window.history_filter.rowCount(window.history_filter.index(0, 0)) == 1


def test_busy_settings_cancel_and_account_chip(qtbot, settings):
    settings.config_dir.mkdir()
    settings.token_file.write_text("SESSDATA=FAKE_OFFLINE_DUMMY", encoding="utf-8")
    window = MainWindow()
    qtbot.addWidget(window)
    assert window.account_button.text() == "凭据待验证 ▾"
    window._start_operation("test", lambda emit, cancel: cancel.wait(5))
    assert not window.start_button.isEnabled() and not window.default_output_edit.isEnabled()
    window._open_settings()
    assert window._settings_dialog.isVisible()
    window._cancel_active()
    assert window.cancel_button.text() == "正在取消…"
    qtbot.waitUntil(lambda: window._thread is None)
    assert not window.start_button.isEnabled()  # Empty/unparsed drafts cannot be submitted.
