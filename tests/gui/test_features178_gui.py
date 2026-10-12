"""User-visible 1.7.8 contracts, with isolated workers and download snapshots."""

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QTreeWidgetItem

from djhx_bilix import tasks
from djhx_bilix.config import load_settings
from djhx_bilix.gui.app import MainWindow
from djhx_bilix.models import DownloadResult, Page
from djhx_bilix.operations import StageEvent
from djhx_bilix.tasks import JobSpec


def parsed(qtbot, video_info):
    window = MainWindow()
    qtbot.addWidget(window)
    window.urls_edit.setPlainText(video_info.url)
    window._info_generation = window._input_generation
    window._parse_total = 1
    window.metadata_tree.addTopLevelItem(QTreeWidgetItem([video_info.url, ""]))
    window._on_event(dict(type="info", index=0, metadata=video_info.public_dict()))
    window._parse_complete = True
    window._update_draft_actions()
    return window


def successful(plan, *_args, stage, **_kwargs):
    for state in tasks.ACTIVE[2:]:
        stage(StageEvent(state))
    return DownloadResult(plan.output)


def test_range_typing_updates_and_immediate_submit_flushes(qtbot, video_info, monkeypatch):
    info = replace(
        video_info, pages=video_info.pages + (Page(2, "second", video_info.url + "?p=2", 4, "200"),)
    )
    window = parsed(qtbot, info)
    submitted = []
    monkeypatch.setattr(window, "_start_batch", submitted.append)
    window.part_range_edit.clear()
    qtbot.keyClicks(window.part_range_edit, "2")
    assert window._range_pending
    window._start_download()
    batch = window.session.batches[submitted[0]]
    assert window.session.requests[batch.requests[0]].spec.page == "2"


def test_invalid_range_keeps_selection_and_blocks_submit(qtbot, video_info, monkeypatch):
    window = parsed(qtbot, video_info)
    qtbot.keyClicks(window.part_range_edit, "2")
    qtbot.waitUntil(lambda: bool(window.range_error.text()))
    assert window._inputs()[0].page == "1"
    submitted = []
    monkeypatch.setattr(window, "_start_batch", submitted.append)
    window._start_download()
    assert submitted == []


def test_download_has_independent_parse_and_accepts_waiting_batch(qtbot, video_info, monkeypatch):
    window = MainWindow()
    qtbot.addWidget(window)
    monkeypatch.setattr(tasks.BilibiliClient, "fetch", lambda *_a: video_info)
    monkeypatch.setattr(tasks, "execute", successful)

    def running(_emit, cancel):
        cancel.wait(5)
        cancel.raise_if_cancelled()

    window._start_operation("download", running)
    original = window._thread
    window._open_draft(text=video_info.url, read_clipboard=False)
    window._request_parse()
    qtbot.waitUntil(lambda: window._parse_complete and window._aux is None)
    assert window._thread is original and window.start_button.isEnabled()
    window._start_download()
    assert len(window.session.pending) == 1 and window._thread is original
    window._cancel_active()
    qtbot.waitUntil(lambda: window._thread is None and not window.session.pending)
    assert window.history_model.counts["completed"] == 1


def test_busy_saved_defaults_do_not_change_waiting_snapshot(qtbot, video_info, tmp_path):
    window = parsed(qtbot, video_info)
    window.session.schedule.pause()
    window._start_download()
    batch_id = window.session.pending[0]
    saved = window.session.requests[window.session.batches[batch_id].requests[0]].options
    window.default_output_edit.setText(str(tmp_path / "new"))
    window.naming_edit.setText("{owner}_{title}")
    window.concurrency_spin.setValue(3)
    window.theme_combo.setCurrentIndex(window.theme_combo.findData("dark"))
    assert window._save_settings()
    assert load_settings().concurrency == 3
    assert window.session.requests[window.session.batches[batch_id].requests[0]].options == saved
    window._cancel_all()
    qtbot.waitUntil(lambda: window._thread is None and not window.session.pending)


def test_capabilities_show_actual_selection_and_disable_only_known_unavailable(qtbot, video_info):
    window = parsed(qtbot, video_info)
    assert "480P" in window.capability_summary.text()
    assert not window.quality_combo.model().item(window.quality_combo.findData(120)).isEnabled()
    assert window.quality_combo.model().item(window.quality_combo.findData(32)).isEnabled()
    info = replace(
        video_info,
        pages=video_info.pages + (Page(2, "unknown", video_info.url + "?p=2", 4, "200"),),
    )
    window._metadata[0] = info.public_dict()
    root = window.metadata_tree.topLevelItem(0)
    child = QTreeWidgetItem(["P2"])
    child.setData(0, Qt.ItemDataRole.UserRole, 2)
    child.setCheckState(0, Qt.CheckState.Checked)
    root.addChild(child)
    window._update_capabilities()
    assert "待预览确认" in window.capability_summary.text()
    assert window.quality_combo.model().item(window.quality_combo.findData(120)).isEnabled()


def test_preview_table_orders_risky_rows_and_keeps_failures(qtbot, video_info):
    window = parsed(qtbot, video_info)
    for i, conflict in enumerate(("new", "replace", "blocked", "skip")):
        event = dict(type="preview", source_index=i, conflict=conflict, detail="safe reason")
        if conflict != "blocked":
            event["output"] = str(Path("output") / f"{i}.mp4")
        window._on_event(event)
    assert window.preview_table.topLevelItemCount() == 4
    assert window.preview_table.topLevelItem(0).text(2) == "阻止"
    assert window.preview_table.topLevelItem(0).text(1) == "无计划路径"
    window._preview_source_order()
    assert window.preview_table.topLevelItem(0).text(2) == "新建"


def test_failure_status_short_diagnostic_excludes_credentials(qtbot, video_info):
    window = parsed(qtbot, video_info)
    options = replace(window._options(False), proxy="http://FAKE_USER:FAKE_PASSWORD@127.0.0.1:8000")
    batch = window.session.begin((JobSpec(video_info.url),), options)
    request_id = window.session.batches[batch].requests[0]
    from djhx_bilix.models import VideoTarget

    identity = window.session.register(request_id, (VideoTarget(video_info.url),))[0]
    window.session.event(identity, window._on_event, state="failed", detail="long safe error" * 30)
    node = window.history_model.tasks[identity]
    index = window.history_model.row_index(node, 1)
    assert "long" not in index.data()
    assert "long" in index.data(Qt.ItemDataRole.ToolTipRole)
    window._open_node_details(node)
    window._copy_task_diagnostics()
    assert "FAKE_PASSWORD" not in QApplication.clipboard().text()
    assert not window.batch_combo.isVisible()


def test_queue_statistics_do_not_include_old_history_or_filter(qtbot, video_info):
    window = parsed(qtbot, video_info)
    window.session.schedule.pause()
    window._start_download()
    window._update_global_progress()
    assert "仍在读取" in window.total_progress.format()
    before = window.total_progress.format()
    window.filter_combo.setCurrentIndex(window.filter_combo.findData("failed"))
    window._update_global_progress()
    assert window.total_progress.format() == before
    window._cancel_all()
    qtbot.waitUntil(lambda: window._thread is None and not window.session.pending)
