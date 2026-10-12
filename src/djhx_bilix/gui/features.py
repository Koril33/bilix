"""Download editor, independent discovery and queue controls for the desktop shell."""

import json
from dataclasses import replace
from functools import partial
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice, QSize, Qt, QThread, QTimer, Slot
from PySide6.QtGui import QIcon, QImageReader, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTreeWidgetItem,
)

from djhx_bilix import __version__
from djhx_bilix.config import load_settings, save_settings
from djhx_bilix.errors import BilixError, InputError
from djhx_bilix.feedback import format_speed
from djhx_bilix.models import CODECS, QUALITY_NAMES, Stream, VideoInfo
from djhx_bilix.operations import CancellationToken
from djhx_bilix.planner import build_plan
from djhx_bilix.tasks import TERMINAL
from djhx_bilix.urls import parse_pages

from .colors import state_color
from .history import NODE_ROLE
from .preferences import GuiPreferences
from .worker import OperationWorker, run_session


class FeatureActions:
    def _init_features(self):
        self._aux = None
        self._ranges = {}
        self._range_pending = False
        self._range_timer = QTimer(self)
        self._range_timer.setInterval(200)
        self._range_timer.setSingleShot(True)
        self._range_timer.timeout.connect(self._apply_part_range)
        self.part_range_edit.textEdited.connect(self._range_edited)
        self.metadata_tree.currentItemChanged.connect(self._restore_range)
        self.metadata_tree.itemChanged.connect(self._selection_changed)
        self.metadata_tree.itemClicked.connect(self._parse_row_clicked)
        self.metadata_tree.setIconSize(QSize(64, 40))
        self._round_batches = []
        self._option_labels = {
            combo: [combo.itemText(i) for i in range(combo.count())]
            for combo in (self.quality_combo, self.codec_combo, self.audio_combo)
        }
        self.capability_summary = QLabel("媒体能力待识别")
        self.capability_summary.setWordWrap(True)
        self.quality_combo.parentWidget().layout().addWidget(self.capability_summary)
        for combo in (self.quality_combo, self.codec_combo, self.audio_combo):
            combo.currentIndexChanged.connect(self._update_capabilities)
        self.strict_check.toggled.connect(self._update_capabilities)
        self._preview_dialog.rejected.connect(self._cancel_aux_preview)
        self.cancel_selected_action = self.selection_menu.addAction(
            "取消选中项", self._cancel_selected
        )
        self.pause_selected_action = self.selection_menu.addAction(
            "暂停选中任务", self._pause_selected
        )
        self.resume_selected_action = self.selection_menu.addAction(
            "恢复选中任务", self._resume_selected
        )
        self._round_timer = QTimer(self)
        self._round_timer.setInterval(250)
        self._round_timer.timeout.connect(self._update_global_progress)
        self._restore_media_options()

    def _make_settings_tab(self):
        page = super()._make_settings_tab()
        layout = page.layout()
        layout.insertWidget(0, QLabel("<b>下载</b>"))
        extras = QFormLayout()
        self.naming_edit = QLineEdit()
        self.naming_edit.setToolTip(
            "字段：{title} {owner} {part} {page} {bvid} {cid} {quality} {codec}；自动保留身份后缀"
        )
        self.proxy_edit = QLineEdit()
        self.proxy_edit.setEchoMode(QLineEdit.EchoMode.PasswordEchoOnEdit)
        self.proxy_edit.setPlaceholderText("留空使用系统环境代理；BILIX_PROXY 优先")
        self.concurrency_spin = QSpinBox()
        self.concurrency_spin.setRange(1, 4)
        self.default_quality_combo = QComboBox()
        self.default_quality_combo.addItem("最高可用", None)
        for quality in sorted(QUALITY_NAMES, reverse=True):
            self.default_quality_combo.addItem(QUALITY_NAMES[quality], quality)
        self.default_codec_combo = QComboBox()
        for label, value in (("自动", None), ("AVC", "AVC"), ("HEVC", "HEVC"), ("AV1", "AV1")):
            self.default_codec_combo.addItem(label, value)
        for label, control in (
            ("命名模板", self.naming_edit),
            ("代理", self.proxy_edit),
            ("同时下载数", self.concurrency_spin),
            ("默认画质", self.default_quality_combo),
            ("默认编码", self.default_codec_combo),
        ):
            extras.addRow(label, control)
        layout.insertLayout(2, extras)
        note = QLabel(
            "业务默认对新提交任务生效；已运行和排队任务保留原参数。记住上次选择时优先使用上次媒体选项。"
        )
        note.setWordWrap(True)
        layout.insertWidget(3, note)
        layout.insertWidget(4, QLabel("<b>外观</b>"))
        tray_index = layout.indexOf(self.tray_check)
        layout.insertWidget(tray_index, QLabel("<b>系统集成</b>"))
        prefs = GuiPreferences()
        for key, combo in (
            ("defaultQuality", self.default_quality_combo),
            ("defaultCodec", self.default_codec_combo),
        ):
            raw = prefs.value(key, "")
            value = int(raw) if key == "defaultQuality" and str(raw).isdigit() else raw or None
            combo.setCurrentIndex(max(0, combo.findData(value)))
        return page

    def _load_settings_view(self):
        super()._load_settings_view()
        if self._settings is not None:
            settings = self._settings
            # Show the stored proxy; an environment override is separately explained.
            import os
            import tomllib

            stored = {}
            if settings.config_file.is_file():
                stored = tomllib.loads(settings.config_file.read_text(encoding="utf-8"))
            self.naming_edit.setText(settings.naming_template)
            self.proxy_edit.setText(stored.get("proxy", ""))
            self.concurrency_spin.setValue(settings.concurrency)
            if os.environ.get("BILIX_PROXY"):
                self.settings_hint.setText(
                    self.settings_hint.text() + "；代理被 BILIX_PROXY 环境变量覆盖"
                )
                self.settings_hint.show()
        self._extended_snapshot = self._extended_values()

    def _extended_values(self):
        return self.naming_edit.text(), self.proxy_edit.text(), self.concurrency_spin.value()

    def _save_settings(self):
        business = (self.default_output_edit.text(), self.ffmpeg_edit.text())
        changed = (
            business != self._business_snapshot
            or self._extended_values() != self._extended_snapshot
        )
        if changed:
            if self._settings is None or not business[0].strip():
                self._error("请修正配置并填写默认下载目录")
                return False
            try:
                save_settings(
                    self._settings,
                    download_dir=Path(business[0].strip()),
                    ffmpeg=business[1].strip() or None,
                    naming_template=self.naming_edit.text(),
                    proxy=self.proxy_edit.text(),
                    concurrency=self.concurrency_spin.value(),
                )
            except (BilixError, OSError) as error:
                self._error(
                    str(error)
                    if isinstance(error, BilixError)
                    else "业务设置无法保存，请检查配置与目录权限；界面偏好尚未保存"
                )
                return False
            self._load_settings_view()
        if not super()._save_settings():
            if changed:
                self._message("业务设置已保存；界面偏好未保存", 10000)
            return False
        if not self._prefs.commit(
            {
                "defaultQuality": self.default_quality_combo.currentData() or "",
                "defaultCodec": self.default_codec_combo.currentData() or "",
            }
        ):
            self._error("默认媒体选项未保存，请检查配置目录权限")
            return False
        self._message("设置已保存；业务默认对新提交任务生效", 5000)
        return True

    def _discard_gui_settings(self):
        super()._discard_gui_settings()
        for key, combo in (
            ("defaultQuality", self.default_quality_combo),
            ("defaultCodec", self.default_codec_combo),
        ):
            raw = self._prefs.value(key, "")
            value = int(raw) if key == "defaultQuality" and str(raw).isdigit() else raw or None
            combo.setCurrentIndex(max(0, combo.findData(value)))

    def _restore_media_options(self):
        super()._restore_media_options()
        for remembered, key, combo in (
            ("quality", "defaultQuality", self.quality_combo),
            ("codec", "defaultCodec", self.codec_combo),
        ):
            if not self._remember_options or self._prefs.value(remembered) is None:
                raw = self._prefs.value(key, "")
                value = int(raw) if remembered == "quality" and str(raw).isdigit() else raw or None
                combo.setCurrentIndex(max(0, combo.findData(value)))

    def _options(self, dry_run):
        options = super()._options(dry_run)
        settings = load_settings()
        return replace(
            options,
            naming_template=settings.naming_template,
            proxy=settings.proxy,
            concurrency=settings.concurrency,
        )

    def _set_busy(self, busy):
        super()._set_busy(busy)
        if getattr(self, "_update_install_pending", False):
            return
        for control in (
            self.default_output_edit,
            self.ffmpeg_edit,
            self.naming_edit,
            self.proxy_edit,
            self.concurrency_spin,
        ):
            control.setEnabled(self._settings is not None)
        for key in (
            self.settings_buttons.StandardButton.Ok,
            self.settings_buttons.StandardButton.Apply,
        ):
            self.settings_buttons.button(key).setEnabled(True)
        self._update_draft_actions()

    def _apply_appearance(self):
        super()._apply_appearance()
        for i in range(self.preview_table.topLevelItemCount()):
            row = self.preview_table.topLevelItem(i)
            state = {
                "new": "completed",
                "skip": "skipped",
                "replace": "replace",
                "blocked": "failed",
            }.get(row.data(1, Qt.ItemDataRole.UserRole), "")
            row.setForeground(2, state_color(state, self.palette()))
        for i in getattr(self, "_failed_parse", ()):
            root = self.metadata_tree.topLevelItem(i)
            if root:
                root.setForeground(1, state_color("failed", self.palette()))

    def _range_edited(self):
        self._range_pending = True
        self._range_timer.start()

    def _range_pages(self, root):
        pages = parse_pages(self.part_range_edit.text().strip() or None)
        available = {
            root.child(i).data(0, Qt.ItemDataRole.UserRole) for i in range(root.childCount())
        }
        missing = set(pages or ()) - available
        if missing:
            raise InputError("选集超出范围：" + ",".join(map(str, sorted(missing))))
        return pages

    def _range_failure(self, message):
        self.range_error.setText(message)
        self.part_range_edit.setStyleSheet("border: 2px solid #c74848;")
        self.part_range_edit.setToolTip(message)

    def _apply_part_range(self):
        if self.part_range_edit.composing:
            return False
        root = self._part_root()
        if root is None or not root.childCount():
            return True
        try:
            pages = self._range_pages(root)
        except BilixError as error:
            self._range_failure(str(error))
            return False
        self._range_timer.stop()
        self._range_pending = False
        self._ranges[id(root)] = self.part_range_edit.text()
        self.metadata_tree.blockSignals(True)
        for i in range(root.childCount()):
            child = root.child(i)
            child.setCheckState(
                0,
                Qt.CheckState.Checked
                if pages is None or child.data(0, Qt.ItemDataRole.UserRole) in pages
                else Qt.CheckState.Unchecked,
            )
        self.metadata_tree.blockSignals(False)
        self.range_error.clear()
        self.part_range_edit.setStyleSheet("")
        self._update_parse_summary()
        self._update_capabilities()
        return True

    def _restore_range(self, item, previous=None):
        if not hasattr(self, "_ranges"):
            return
        if previous and self._range_pending:
            self._ranges[id(previous.parent() or previous)] = self.part_range_edit.text()
        self._range_timer.stop()
        self._range_pending = False
        root = item.parent() or item if item else None
        self.part_range_edit.setText(self._ranges.get(id(root), ""))
        self.range_error.clear()
        self.part_range_edit.setStyleSheet("")
        if root and root.childCount() and self.part_range_edit.text() not in {"", "0"}:
            try:
                self._range_pages(root)
            except BilixError as error:
                self._range_failure(str(error))
        self._update_capabilities()

    def _selection_changed(self, item, column):
        if getattr(self, "_range_pending", False):
            return
        root = item.parent() or item
        parts = [
            str(root.child(i).data(0, Qt.ItemDataRole.UserRole))
            for i in range(root.childCount())
            if root.child(i).checkState(0) == Qt.CheckState.Checked
        ]
        if hasattr(self, "_ranges"):
            self._ranges[id(root)] = ",".join(parts) if parts else "0"
            if root is self._part_root():
                self.part_range_edit.setText(self._ranges[id(root)])
                self.part_range_edit.setPlaceholderText("自定义选择")
        self._update_capabilities()

    def _apply_all_ranges(self):
        roots = [self.metadata_tree.topLevelItem(i) for i in self._metadata]
        try:
            for root in roots:
                self._range_pages(root)
        except BilixError as error:
            self._range_failure(root.text(0) + "：" + str(error))
            return
        text = self.part_range_edit.text()
        self.metadata_tree.blockSignals(True)
        for root in roots:
            pages = self._range_pages(root)
            for i in range(root.childCount()):
                child = root.child(i)
                child.setCheckState(
                    0,
                    Qt.CheckState.Checked
                    if pages is None or child.data(0, Qt.ItemDataRole.UserRole) in pages
                    else Qt.CheckState.Unchecked,
                )
            self._ranges[id(root)] = text
        self.metadata_tree.blockSignals(False)
        self._range_pending = False
        self._range_timer.stop()
        self.range_error.clear()
        self.part_range_edit.setStyleSheet("")
        self._update_parse_summary()
        self._update_capabilities()

    def _start_download(self, dry_run=False, specs=None):
        if (
            specs is None
            and (self._range_pending or self.range_error.text())
            and not self._apply_part_range()
        ):
            self.part_range_edit.setFocus()
            return
        if dry_run:
            self.preview_table.clear()
        super()._start_download(dry_run, specs)

    def _update_draft_actions(self):
        super()._update_draft_actions()
        auxiliary = getattr(self, "_aux", None)
        if self._active_kind == "download" and not getattr(self, "_update_install_pending", False):
            selected = any(
                self.metadata_tree.topLevelItem(i).child(j).checkState(0) == Qt.CheckState.Checked
                for i in self._metadata
                for j in range(self.metadata_tree.topLevelItem(i).childCount())
            )
            ready = bool(self._retry_context) or (
                self._parse_complete
                and self._info_generation == self._input_generation
                and selected
            )
            self.start_button.setEnabled(
                bool(ready and not auxiliary and not self.urls_edit.composing)
            )
            self.start_button.setText("加入队列")
            self.plan_button.setEnabled(bool(ready and not auxiliary and not self._retry_context))
            self.info_button.setEnabled(not bool(auxiliary))
            self.retry_parse_button.setEnabled(
                bool(self._parse_complete and self._failed_parse and not auxiliary)
            )
        else:
            self.start_button.setText("下载")

    def _drain_pending(self):
        if (
            self._active_kind == "download"
            and self._pending_parse
            and self._draft_open
            and not getattr(self, "_aux", None)
        ):
            self._pending_parse = False
            self._start_info()
        else:
            super()._drain_pending()
        self._run_next_batch()

    def _start_operation(self, kind, operation):
        if kind in {"info", "plan"} and self._active_kind == "download":
            if self._aux or self._update_install_pending:
                return False
            self._job_serial += 1
            context = kind, self._job_serial, self._input_generation, self._account_revision
            token = CancellationToken()
            thread = QThread(self)
            worker = OperationWorker(operation, token, context)
            self._aux = (thread, worker, token, context)
            worker.moveToThread(thread)
            thread.started.connect(worker.run)
            worker.event.connect(self._receive_aux_event, Qt.ConnectionType.QueuedConnection)
            worker.done.connect(self._receive_aux_done, Qt.ConnectionType.QueuedConnection)
            worker.done.connect(thread.quit)
            thread.finished.connect(self._aux_finished)
            thread.finished.connect(worker.deleteLater)
            thread.finished.connect(thread.deleteLater)
            thread.start()
            return True
        return super()._start_operation(kind, operation)

    def _aux_valid(self, context):
        self._check_credentials(schedule=False)
        return bool(
            self._aux
            and context == self._aux[3]
            and context[2:] == (self._input_generation, self._account_revision)
        )

    @Slot(object)
    def _receive_aux_event(self, event):
        if self._aux_valid(event["_gui_context"]):
            self._on_event(event)

    @Slot(object)
    def _receive_aux_done(self, result):
        if self._aux_valid(result["_gui_context"]):
            kind = self._active_kind
            self._active_kind = result["_gui_context"][0]
            self._on_done(result)
            self._active_kind = kind

    @Slot()
    def _aux_finished(self):
        self._aux = None
        self._update_draft_actions()
        if self._close_pending:
            QTimer.singleShot(0, self.close)
        elif self._pending_parse:
            QTimer.singleShot(0, self._drain_pending)
        else:
            self._run_next_batch()

    def _cancel_aux_preview(self):
        if self._aux and self._aux[3][0] == "plan":
            self._aux[2].cancel()

    def _invalidate_info(self):
        if getattr(self, "_aux", None):
            self._aux[2].cancel()
        if hasattr(self, "_ranges"):
            self._ranges.clear()
        super()._invalidate_info()
        self._update_capabilities()

    def _close_draft(self):
        if getattr(self, "_aux", None):
            self._aux[2].cancel()
            self._input_generation += 1
        super()._close_draft()

    def _start_batch(self, batch_id):
        if not self._round_batches or all(
            self.session.batches[i].finished for i in self._round_batches
        ):
            self._round_batches = []
        self._round_batches.append(batch_id)
        batch = self.session.batches[batch_id]
        for identity in batch.requests:
            self.history_model.source(self.session.requests[identity])
        for identity in batch.tasks:
            task = self.session.tasks[identity]
            self.history_model.task(task, task.latest, self.session.requests[task.request_id])
        self.history_filter.set_state("all")
        self.filter_combo.setCurrentIndex(0)
        self.list_stack.setCurrentIndex(1)
        self._round_timer.start()
        self._update_retry_button()
        self._update_global_progress()
        self._run_next_batch()

    def _run_next_batch(self):
        if (
            self._thread is not None
            or self._close_pending
            or getattr(self, "_aux", None)
            or getattr(self, "_update_install_pending", False)
        ):
            return
        batch_id = self.session.next_batch()
        if batch_id:
            self._download_batch = batch_id
            self._start_operation("download", partial(run_session, self.session, batch_id))

    def _toggle_queue_pause(self):
        (
            self.session.schedule.resume
            if self.session.schedule.paused
            else self.session.schedule.pause
        )()
        self.pause_queue_button.setText("恢复队列" if self.session.schedule.paused else "暂停队列")
        self.pause_queue_button.setToolTip("当前任务继续；仅停止启动后续任务")
        self._run_next_batch()

    def _cancel_all(self):
        for batch_id, batch in tuple(self.session.batches.items()):
            if not batch.finished:
                self.session.cancel_batch(batch_id, self._on_event)
        self.session.schedule.resume()
        if self._active_kind == "download":
            self._cancel_active()
        self._run_next_batch()

    def _cancel_selected(self):
        tasks, sources = self._selected_ids()
        for identity in (*tasks, *sources):
            self.session.cancel_item(identity, self._on_event)

    def _pause_selected(self):
        for identity in self._selected_ids()[0]:
            self.session.pause_item(identity, True, self._on_event)

    def _resume_selected(self):
        for identity in self._selected_ids()[0]:
            self.session.pause_item(identity, False, self._on_event)

    def _update_retry_button(self, *_args):
        super()._update_retry_button(*_args)
        if self.session.pending:
            self.clear_success_action.setEnabled(False)
            self.clear_failed_action.setEnabled(False)
        if self._active_kind == "download" and not getattr(self, "_update_install_pending", False):
            states = self.history_model.counts
            self.retry_button.setEnabled(bool(states["failed"]))
            self.retry_canceled_action.setEnabled(bool(states["canceled"]))
            task_ids, sources = self._selected_ids()
            retryable = (
                bool(task_ids or sources)
                and all(
                    self.session.tasks[i].latest.state in {"failed", "canceled"} for i in task_ids
                )
                and all(self.session.requests[i].state in {"failed", "canceled"} for i in sources)
            )
            self.retry_selected_action.setEnabled(retryable)
            self.retry_current_action.setEnabled(retryable)
        if hasattr(self, "cancel_selected_action"):
            ids, sources = self._selected_ids()
            active = [
                self.session.tasks[i]
                for i in ids
                if self.session.tasks[i].latest.state not in TERMINAL
            ]
            self.cancel_selected_action.setEnabled(bool(active or sources))
            self.pause_selected_action.setEnabled(any(not t.latest.paused for t in active))
            self.resume_selected_action.setEnabled(any(t.latest.paused for t in active))

    def _row_menu(self, index):
        if index.column() != 3:
            return
        node = index.data(NODE_ROLE)
        rect = self.jobs_view.visualRect(index)
        from PySide6.QtGui import QCursor

        position = self.jobs_view.viewport().mapFromGlobal(QCursor.pos())
        if position.x() >= rect.right() - 32:
            super()._row_menu(index)
        elif node.state in {"completed", "skipped"}:
            task = self.session.tasks.get(node.identity)
            if task and task.latest.output:
                self._open_folder(Path(task.latest.output).parent)
        elif node.state in {"failed", "canceled"}:
            self._retry_ids(
                (node.identity,) if node.kind == "task" else (),
                (node.identity,) if node.kind == "source" else (),
            )
        elif node.kind == "task":
            self.session.pause_item(node.identity, not node.paused, self._on_event)
        else:
            self.session.cancel_item(node.identity, self._on_event)

    def _update_global_progress(self):
        task_snapshot, requests, batch_snapshot = self.session.snapshot()
        batches = [batch_snapshot[i] for i in self._round_batches]
        attempts = (
            [
                a
                for batch in batches
                for i in batch.tasks
                for a in task_snapshot[i].attempts
                if a.batch_id == batch.batch_id
            ]
            if batches and all(i in task_snapshot for b in batches for i in b.tasks)
            else []
        )
        total = len(attempts)
        ended = sum(a.state in TERMINAL for a in attempts)
        failed = sum(a.state == "failed" for a in attempts)
        unknown = any(
            requests[i].state in {"queued", "loading"} for b in batches for i in b.requests
        )
        active = any(not b.finished for b in batches)
        source_failed = sum(requests[i].state == "failed" for b in batches for i in b.requests)
        self.total_progress.setVisible(bool(batches))
        self.total_progress.setRange(0, 0 if unknown else max(1, total))
        self.total_progress.setValue(ended if total or active else 1)
        speeds = [
            row.estimator.snapshot().speed
            for row in self.history_model.tasks.values()
            if row.state == "downloading" and not row.paused and row.estimator
        ]
        speed = sum(v for v in speeds if v is not None) if speeds else None
        text = f"已结束 {ended}/{total}" + (" · 仍在读取" if unknown else "") + f" · 失败 {failed}"
        if source_failed:
            text += f" · 读取失败 {source_failed}"
        if active and speed is not None:
            text += " · " + format_speed(speed)
        self.total_progress.setFormat(text)
        title = "BiliX · " + text if active else f"BiliX {__version__}"
        self.setWindowTitle(title)
        if getattr(self, "tray", None):
            self.tray.setToolTip(title)
        self.pause_queue_button.setVisible(active)
        if active and self._thread is None:
            self.cancel_button.show()
            self.cancel_button.setEnabled(True)
            self.cancel_button.setText("取消任务…")
        if not active:
            self._round_timer.stop()

    def _update_capabilities(self, *_args):
        if not hasattr(self, "capability_summary"):
            return
        selected = []
        unknown = False
        for i, data in self._metadata.items():
            root = self.metadata_tree.topLevelItem(i)
            for j in range(root.childCount()):
                if root.child(j).checkState(0) != Qt.CheckState.Checked:
                    continue
                number = root.child(j).data(0, Qt.ItemDataRole.UserRole)
                pages = data.get("pages") or [{"number": 1, "cid": data["cid"]}]
                page = next((p for p in pages if p["number"] == number), None)
                if page and str(page.get("cid", "")) == str(data["cid"]):
                    selected.append(data)
                else:
                    unknown = True
        for combo, kind in (
            (self.quality_combo, "quality"),
            (self.codec_combo, "codec"),
            (self.audio_combo, "audio"),
        ):
            for i in range(combo.count()):
                value = combo.itemData(i)
                checks = []
                for data in selected:
                    if kind == "quality":
                        checks.append(
                            any(
                                s["quality"] == value
                                and (
                                    self.codec_combo.currentData() is None
                                    or s["codec"] == self.codec_combo.currentData()
                                )
                                for s in data["available_streams"]
                            )
                        )
                    elif kind == "codec":
                        checks.append(
                            any(
                                s["codec"] == value
                                and (
                                    self.quality_combo.currentData() is None
                                    or s["quality"] == self.quality_combo.currentData()
                                )
                                for s in data["available_streams"]
                            )
                        )
                    else:
                        checks.append(any(s["kind"] == value for s in data["available_audio"]))
                automatic = value is None or kind == "audio" and value == "best"
                unavailable = not automatic and bool(checks) and not any(checks) and not unknown
                combo.model().item(i).setEnabled(not unavailable)
                status = (
                    "当前不可获取"
                    if unavailable
                    else "部分可用"
                    if checks and not all(checks)
                    else "待确认"
                    if unknown
                    else ""
                )
                combo.setItemData(i, status, Qt.ItemDataRole.ToolTipRole)
                combo.setItemText(
                    i, self._option_labels[combo][i] + (" · " + status if status else "")
                )
        predictions = []
        for data in selected:
            info = VideoInfo(
                data["url"],
                data["title"],
                data["bvid"],
                data["cid"],
                data["duration"],
                (),
                tuple(
                    Stream(
                        s["quality"],
                        next(k for k, v in CODECS.items() if v == s["codec"]),
                        s["bandwidth"],
                        (),
                    )
                    for s in data["available_streams"]
                    if s["codec"] in CODECS.values()
                ),
                tuple(
                    Stream(s["id"], 0, s["bandwidth"], (), audio_kind=s["kind"])
                    for s in data["available_audio"]
                ),
                is_preview=data.get("is_preview", False),
                is_drm=data.get("is_drm", False),
            )
            try:
                plan = build_plan(
                    info,
                    Path("."),
                    self.quality_combo.currentData(),
                    self.codec_combo.currentData(),
                    self.strict_check.isChecked(),
                    self.audio_combo.currentData(),
                )
                predictions.append(
                    f"{QUALITY_NAMES.get(plan.video.quality)} · "
                    f"{CODECS.get(plan.video.codec)} · {plan.audio.audio_kind.upper()}"
                )
            except BilixError as error:
                predictions.append(str(error))
        text = (
            "实际选择：" + predictions[0]
            if len(predictions) == 1 and not unknown
            else "各选集分别选择"
            if selected or unknown
            else "媒体能力待识别"
        )
        if unknown:
            text += "；其他选集待预览确认"
        self.capability_summary.setText(text)
        self.capability_summary.setToolTip("\n".join(predictions))

    def _metadata_menu(self, position):
        item = self.metadata_tree.itemAt(position)
        if item is None:
            return
        self.metadata_tree.setCurrentItem(item)
        root = item.parent() or item
        index = self.metadata_tree.indexOfTopLevelItem(root)
        menu = QMenu(self.metadata_tree)
        if index in self._failed_parse:
            menu.addAction("重试此项", lambda: self._retry_parse(indices={index}))
        menu.addAction("查看来源信息", self._source_details)
        if index in self._metadata:
            menu.addAction("复制来源信息 JSON", self._copy_metadata)
        menu.exec(self.metadata_tree.viewport().mapToGlobal(position))

    def _parse_row_clicked(self, item, column):
        index = self.metadata_tree.indexOfTopLevelItem(item.parent() or item)
        if column == 1 and index in self._failed_parse:
            self._retry_parse(indices={index})

    def _source_details(self):
        self._show_metadata(self.metadata_tree.currentItem())
        dialog, layout, close = self._dialog("来源信息", 600, 380)
        text = QPlainTextEdit(self.parts_info.toPlainText())
        text.setReadOnly(True)
        layout.addWidget(text)
        layout.addWidget(close)
        dialog.show()

    def _preview_source_order(self):
        rows = [
            self.preview_table.takeTopLevelItem(0)
            for _ in range(self.preview_table.topLevelItemCount())
        ]
        self.preview_table.addTopLevelItems(
            sorted(rows, key=lambda r: r.data(0, Qt.ItemDataRole.UserRole))
        )

    def _on_event(self, event):
        if event["type"] == "cover":
            root = self.metadata_tree.topLevelItem(event["index"])
            buffer = QBuffer()
            buffer.setData(event["data"])
            buffer.open(QIODevice.OpenModeFlag.ReadOnly)
            reader = QImageReader(buffer)
            size = reader.size()
            if (
                size.width() <= 0
                or size.height() <= 0
                or size.width() > 8192
                or size.height() > 8192
            ):
                return
            reader.setScaledSize(size.scaled(64, 40, Qt.AspectRatioMode.KeepAspectRatio))
            image = reader.read()
            if root and not image.isNull():
                root.setIcon(
                    0,
                    QIcon(
                        QPixmap.fromImage(image).scaled(
                            64,
                            40,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                    ),
                )
            return
        super()._on_event(event)
        if event["type"] == "info":
            root = self.metadata_tree.topLevelItem(event["index"])
            if root and event.get("error"):
                root.setText(1, "解析失败 · 重试")
                root.setForeground(1, state_color("failed", self.palette()))
                root.setIcon(
                    0, self.style().standardIcon(self.style().StandardPixmap.SP_MessageBoxCritical)
                )
                root.setToolTip(1, event["error"])
            elif root:
                owner = event["metadata"].get("owner") or "作者未知"
                root.setText(0, root.text(0) + " · " + owner)
                root.setIcon(0, self.style().standardIcon(self.style().StandardPixmap.SP_MediaPlay))
            self._update_capabilities()
        elif event["type"] == "preview":
            conflict = event["conflict"]
            labels = {
                "new": "新建",
                "skip": "跳过：已存在，未校验",
                "replace": "替换",
                "blocked": "阻止",
            }
            output = event.get("output", "")
            row = QTreeWidgetItem(
                [
                    Path(output).name if output else event.get("label") or "无法生成文件",
                    output or "无计划路径",
                    labels[conflict],
                ]
            )
            row.setData(
                0,
                Qt.ItemDataRole.UserRole,
                (event["source_index"], self.preview_table.topLevelItemCount()),
            )
            row.setToolTip(
                2,
                "\n".join(
                    [
                        event.get("detail", ""),
                        event.get("action", ""),
                        event.get("selection", ""),
                        *event.get("warnings", ()),
                    ]
                )
                + ("\n本批输出路径重复" if event.get("duplicate") else ""),
            )
            row.setForeground(
                2,
                state_color(
                    {
                        "new": "completed",
                        "skip": "skipped",
                        "replace": "replace",
                        "blocked": "failed",
                    }[conflict],
                    self.palette(),
                ),
            )
            row.setData(1, Qt.ItemDataRole.UserRole, conflict)
            priority = {"blocked": 0, "replace": 1, "skip": 2, "new": 2}
            row.setData(2, Qt.ItemDataRole.UserRole, priority[conflict])
            position = next(
                (
                    i
                    for i in range(self.preview_table.topLevelItemCount())
                    if self.preview_table.topLevelItem(i).data(2, Qt.ItemDataRole.UserRole)
                    > priority[conflict]
                ),
                self.preview_table.topLevelItemCount(),
            )
            self.preview_table.insertTopLevelItem(position, row)

    def _build_details(self):
        super()._build_details()
        self.batch_combo.hide()
        self.batch_text.hide()
        button = QPushButton("复制诊断信息")
        button.clicked.connect(self._copy_task_diagnostics)
        self._details_dialog.layout().insertWidget(1, button)
        retry = QPushButton("重试 / 调整参数")
        retry.clicked.connect(self._retry_detail)
        self._details_dialog.layout().insertWidget(2, retry)
        self.detail_retry_button = retry
        folder = QPushButton("打开所在目录")
        folder.clicked.connect(self._detail_folder)
        self._details_dialog.layout().insertWidget(3, folder)
        self.detail_folder_button = folder

    def _retry_detail(self):
        node = self._diagnostic_node
        if node:
            self._details_dialog.hide()
            self._retry_ids(
                (node.identity,) if node.kind == "task" else (),
                (node.identity,) if node.kind == "source" else (),
                current=True,
            )

    def _detail_folder(self):
        task = self.session.tasks.get(self._diagnostic_node.identity)
        if task:
            path = task.latest.output or task.latest.planned_output
            if path and Path(path).parent.is_dir():
                self._open_folder(Path(path).parent)

    def _open_node_details(self, node, batch_id=None):
        self._diagnostic_node = node
        super()._open_node_details(node, batch_id)
        self.detail_retry_button.setVisible(bool(node and node.state in {"failed", "canceled"}))
        task = self.session.tasks.get(node.identity) if node else None
        self.detail_folder_button.setVisible(
            bool(task and (task.latest.output or task.latest.planned_output))
        )
        if node and node.kind == "source":
            request = self.session.requests.get(node.identity)
            if request:
                from .history import STATES

                self.details_summary.setText(
                    f"{node.title}\n状态：{STATES.get(node.state, node.state)}\n"
                    f"{request.detail}\n{request.action}"
                )

    def _copy_task_diagnostics(self):
        node = getattr(self, "_diagnostic_node", None)
        if node is None:
            return
        task = self.session.tasks.get(node.identity)
        data = {"version": __version__, "state": node.state, "task_id": node.identity}
        if task:
            data["attempts"] = [
                {
                    "number": a.number,
                    "batch_id": a.batch_id,
                    "state": a.state,
                    "error_code": a.error_code,
                    "detail": a.detail,
                    "action": a.action,
                    "output": a.output,
                    "planned_output": a.planned_output,
                    "ffmpeg": a.resolved_ffmpeg,
                }
                for a in task.attempts
            ]
        else:
            source = self.session.requests.get(node.identity)
            if source:
                data.update(
                    batch_id=source.batch_id,
                    origin=source.origin_request_id,
                    detail=source.detail,
                    error_code=source.error_code,
                    action=source.action,
                )
        QApplication.clipboard().setText(json.dumps(data, ensure_ascii=False, indent=2))

    def _maybe_apply_update(self):
        if self.session.pending or self.session.schedule.paused or getattr(self, "_aux", None):
            if getattr(self, "_update_install_pending", False):
                self._update_install_pending = False
                self._show_update_ready()
                self._message("更新暂未安装：请先完成或取消等待队列", 10000)
            return False
        return super()._maybe_apply_update()

    def closeEvent(self, event):
        if self._exit_requested and (self.session.pending or getattr(self, "_aux", None)):
            if self._thread is None and not self._close_pending:
                from PySide6.QtWidgets import QMessageBox

                answer = QMessageBox.question(
                    self,
                    "等待任务尚未完成",
                    "取消运行及等待任务并退出？任务不会跨重启保留。",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    self._exit_requested = False
                    event.ignore()
                    return
            if self._thread is None or self._close_pending:
                self._cancel_all()
                self.session.pending.clear()
                if self._aux:
                    self._close_pending = True
                    self._aux[2].cancel()
                    event.ignore()
                    return
        super().closeEvent(event)
