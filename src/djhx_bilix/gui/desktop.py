"""GUI scheduling, draft state and desktop lifecycle; download engine stays unchanged."""

import hashlib
import sys
from collections import Counter
from functools import partial
from pathlib import Path

from PySide6.QtCore import QEvent, Qt, QTimer, qVersion
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QTreeWidgetItem,
)

from djhx_bilix import __version__
from djhx_bilix.config import load_settings
from djhx_bilix.credentials import normalize_cookie
from djhx_bilix.errors import BilixError, InputError
from djhx_bilix.urls import normalize_url, parse_pages

from .appearance import apply_theme
from .preferences import GuiPreferences
from .worker import JobSpec, run_info


class DesktopActions:
    def _init_desktop(self):
        self._draft_open = False
        self._pending_parse = False
        self._pending_account = False
        self._parse_complete = False
        self._parse_sources = []
        self._failed_parse = set()
        self._account_revision = 0
        self._credential_key = object()
        self._job_serial = 0
        self._active_context = None
        self._last_summary = "就绪"
        self._download_summary = ""
        self._download_batch = None
        self._notified_batches = set()
        self._last_notified_batch = None
        self._retry_context = None
        self._saved_draft = None
        self._tray_hidden_windows = []
        self._in_tray = False
        self._tray_normal_state = Qt.WindowState.WindowNoState
        self._parse_timer = QTimer(self)
        self._parse_timer.setSingleShot(True)
        self._parse_timer.setInterval(500)
        self._parse_timer.timeout.connect(self._request_parse)
        self._message_timer = QTimer(self)
        self._message_timer.setSingleShot(True)
        self._message_timer.timeout.connect(lambda: self.status_text.setText(self._last_summary))
        self._prefs = GuiPreferences()
        self._theme_mode = self._prefs.theme()
        self._remember_options = self._pref("rememberMediaOptions", True, bool)
        self._show_feedback = self._pref("showTransferFeedback", True, bool)
        self._auto_update_enabled = self._pref("automaticUpdates", True, bool)
        self._tray_enabled = self._pref("minimizeToTray", True, bool)
        self._notify_enabled = self._pref("completionNotification", True, bool)
        for name, combo in (
            ("quality", self.quality_combo),
            ("codec", self.codec_combo),
            ("audio", self.audio_combo),
            ("mode", self.mode_combo),
        ):
            raw = self._prefs.value(name, "") if self._remember_options else ""
            value = int(raw) if name == "quality" and str(raw).isdigit() else raw or None
            index = combo.findData(value)
            if index >= 0:
                combo.setCurrentIndex(index)
        self.save_cover_check.setChecked(
            self._remember_options and self._pref("cover", False, bool)
        )
        self.strict_check.setChecked(self._remember_options and self._pref("strict", False, bool))
        self.advanced_toggle.setChecked(self._pref("advancedExpanded", False, bool))
        self.advanced_toggle.toggled.connect(
            lambda checked: self._prefs.setValue("advancedExpanded", checked)
        )
        self._apply_appearance()
        self._feedback_timer = QTimer(self)
        self._feedback_timer.setInterval(250)
        self._feedback_timer.timeout.connect(self._refresh_feedback)
        geometry = self._prefs.value("geometry")
        if geometry is not None and isinstance(geometry, bytes | type(self.saveGeometry())):
            self.restoreGeometry(geometry)
        available = self.screen().availableGeometry()
        self.resize(min(self.width(), available.width()), min(self.height(), available.height()))
        frame = self.frameGeometry()
        self.move(
            max(available.left(), min(frame.x(), available.right() - frame.width())),
            max(available.top(), min(frame.y(), available.bottom() - frame.height())),
        )
        for column in (1, 2):
            width = self._pref(f"column{column}", self.jobs_view.columnWidth(column), int)
            self.jobs_view.setColumnWidth(column, max(80, min(350, width)))
        self._discard_gui_settings()
        self._init_tray()
        self._update_draft_actions()
        self._update_counts()
        if self._prefs.status() == self._prefs.Status.FormatError:
            QTimer.singleShot(
                0,
                lambda: self._message(
                    "界面偏好格式错误，已使用安全默认；可在设置中恢复界面默认", 10000
                ),
            )

    def _pref(self, name, default, kind):
        return self._prefs.read(name, default, kind)

    def _apply_appearance(self):
        apply_theme(QApplication.instance(), self._theme_mode)
        delegate = self.jobs_view.itemDelegate()
        delegate.show_feedback = self._show_feedback
        self.jobs_view.setColumnWidth(2, self.jobs_view.columnWidth(2))
        self.jobs_view.doItemsLayout()
        self.jobs_view.viewport().update()

    def _system_theme_changed(self, *_args):
        self._apply_appearance()

    def _refresh_feedback(self):
        active = [
            row
            for row in self.history_model.tasks.values()
            if row.state == "downloading" and not row.paused and row.estimator is not None
        ]
        for row in active:
            self.history_model.refresh_feedback(row)
        if not active:
            self._feedback_timer.stop()

    def _restore_interface_defaults(self):
        answer = QMessageBox.question(
            self,
            "恢复界面默认",
            "恢复主题、媒体默认、进度显示、展开状态和窗口布局？\n"
            "账号、业务配置、托盘、通知及自动更新开关将保留。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            if not self._prefs.reset_interface():
                raise OSError
        except OSError:
            self._error("界面偏好无法恢复，请检查配置目录权限")
            return
        self._theme_mode, self._remember_options, self._show_feedback = "system", True, True
        self.jobs_view.setColumnWidth(1, 155)
        self.jobs_view.setColumnWidth(2, 220)
        self.resize(
            min(860, self.screen().availableGeometry().width()),
            min(660, self.screen().availableGeometry().height()),
        )
        self._discard_gui_settings()
        self._apply_appearance()
        self._message("界面默认已恢复；媒体默认在下一次空白草稿生效", 5000)

    def _message(self, text, timeout=0):
        text = text.replace("\n", " · ")
        self.status_text.setText(text)
        if not hasattr(self, "_message_timer"):
            return
        self._message_timer.stop()
        if timeout:
            self._message_timer.start(timeout)
        elif self._active_kind != "status":
            self._last_summary = text

    def _open_default_folder(self):
        if self._settings:
            self._open_folder(self._settings.download_dir)

    def _open_doctor(self):
        self._open_settings(2)
        self._start_doctor()

    def _open_draft(self, checked=False, *, text=None, read_clipboard=True):
        if self._close_pending:
            return
        if not self._retry_context and not self.urls_edit.toPlainText().strip():
            self._restore_media_options()
        self._check_credentials()
        self._restore_main()
        if text is None and read_clipboard and not self.urls_edit.toPlainText().strip():
            candidate = QApplication.clipboard().text()
            if self._has_supported_source(candidate):
                text = candidate
        if text is not None:
            if self._retry_context:
                self._error("请先关闭当前重试编辑，再添加新链接")
                return
            previous = self.urls_edit.toPlainText().strip()
            if previous and previous != text.strip():
                answer = QMessageBox.question(
                    self,
                    "加入链接",
                    "追加到现有草稿？\n选“否”替换，选“取消”保留草稿。",
                    QMessageBox.StandardButton.Yes
                    | QMessageBox.StandardButton.No
                    | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Yes,
                )
                if answer == QMessageBox.StandardButton.Cancel:
                    return
                if answer == QMessageBox.StandardButton.Yes:
                    text = previous + "\n" + text
            self.urls_edit.setPlainText(text.lstrip("\ufeff"))
        self._draft_dialog.show()
        self._draft_open = True
        self._draft_dialog.raise_()
        self._draft_dialog.activateWindow()
        self.urls_edit.setFocus()
        if (
            not self._retry_context
            and self.urls_edit.toPlainText().strip()
            and not self._parse_complete
        ):
            self._parse_timer.start()
        self._update_draft_actions()

    @staticmethod
    def _has_supported_source(text):
        for line in text.splitlines():
            try:
                normalize_url(line.strip())
                return True
            except BilixError:
                pass
        return False

    def _paste_draft(self):
        text = QApplication.clipboard().text()
        if self._has_supported_source(text):
            self._open_draft(text=text, read_clipboard=False)

    def dragEnterEvent(self, event):
        mime = event.mimeData()
        if (
            mime.hasText()
            and self._has_supported_source(mime.text())
            or any(
                url.isLocalFile() and Path(url.toLocalFile()).suffix.lower() == ".txt"
                for url in mime.urls()
            )
        ):
            event.acceptProposedAction()

    def dropEvent(self, event):
        values = []
        try:
            for url in event.mimeData().urls():
                if url.isLocalFile() and Path(url.toLocalFile()).suffix.lower() == ".txt":
                    values.append(Path(url.toLocalFile()).read_text(encoding="utf-8-sig"))
            if not values:
                values.append(event.mimeData().text())
        except (OSError, UnicodeError):
            self._error("链接列表无法读取，请使用 UTF-8 文本")
            return
        self._open_draft(text="\n".join(values), read_clipboard=False)
        event.acceptProposedAction()

    def _close_draft(self):
        self._draft_open = False
        self._parse_timer.stop()
        self._pending_parse = False
        if self._active_kind == "info":
            self._input_generation += 1
            self._parse_complete = False
            self._cancel_active()
        if self._retry_context:
            self._retry_context = None
            saved = self._saved_draft
            self._saved_draft = None
            self.urls_edit.setReadOnly(False)
            self._draft_dialog.setWindowTitle("新建下载")
            self.metadata_tree.setEnabled(True)
            if saved:
                self.urls_edit.setPlainText(saved[0])
                self._put_options(saved[1])
        self._update_draft_actions()

    def _invalidate_info(self):
        self._input_generation += 1
        self._metadata.clear()
        self.metadata_tree.clear()
        self._parse_total = self._parse_finished = self._parse_errors = 0
        self._parse_complete = False
        self._failed_parse.clear()
        self.parts_info.clear()
        self._pending_parse = False
        self._parse_timer.stop()
        if self._active_kind in ("info", "plan") and self._cancel:
            self._cancel.cancel()
        self.parse_summary.setText(
            "正在停止旧识别…" if self._active_kind == "info" else "输入完成后自动识别"
        )
        if self._draft_open and not self._retry_context and not self.urls_edit.composing:
            self._parse_timer.start()
        self._update_draft_actions()

    def _ime_changed(self):
        if self.urls_edit.composing:
            self._invalidate_info()
        elif self._draft_open:
            self._parse_timer.start()

    def _request_parse(self, checked=False):
        if self._close_pending or self._retry_context or self.urls_edit.composing:
            return
        self._parse_timer.stop()
        self._pending_parse = bool(self.urls_edit.toPlainText().strip())
        self._check_credentials(schedule=False)
        self._drain_pending()

    def _drain_pending(self):
        if (
            self._close_pending
            or self._thread is not None
            or getattr(self, "_update_install_pending", False)
        ):
            self._update_draft_actions()
            return
        if self._pending_account:
            self._pending_account = False
            self._start_status()
        elif self._pending_parse and self._draft_open and not self.urls_edit.composing:
            self._pending_parse = False
            self._start_info()
        self._update_draft_actions()

    def _start_info(self):
        if (
            (self._thread is not None and self._active_kind != "download")
            or self._retry_context
            or getattr(self, "_aux", None)
        ):
            return
        self._metadata.clear()
        self.metadata_tree.clear()
        self._failed_parse.clear()
        self._parse_complete = False
        self._info_generation = self._input_generation
        self._parse_sources = [
            (i, line.strip())
            for i, line in enumerate(self.urls_edit.toPlainText().lstrip("\ufeff").splitlines(), 1)
            if line.strip() and not line.lstrip().startswith("#")
        ]
        self._parse_total = len(self._parse_sources)
        self._parse_finished = self._parse_errors = 0
        valid = []
        for index, (line, source) in enumerate(self._parse_sources):
            root = QTreeWidgetItem([source, "等待读取"])
            self.metadata_tree.addTopLevelItem(root)
            try:
                normalize_url(source)
            except BilixError as error:
                root.setText(1, f"第 {line} 行：{error}")
                self._parse_finished += 1
                self._parse_errors += 1
                self._failed_parse.add(index)
            else:
                valid.append((index, JobSpec(source)))
        if not valid:
            self._parse_complete = True
            self._update_parse_summary()
            self._update_draft_actions()
            return
        self._run_parse(valid)

    def _reset_one_part(self, root, data):
        from djhx_bilix.urls import url_page

        page = url_page(data["url"])
        for child_index in range(root.childCount()):
            child = root.child(child_index)
            child.setCheckState(
                0,
                Qt.CheckState.Checked
                if page is None or child.data(0, Qt.ItemDataRole.UserRole) == page
                else Qt.CheckState.Unchecked,
            )

    def _run_parse(self, valid):
        mapping = [index for index, spec in valid]
        specs = tuple(spec for index, spec in valid)
        metadata_only = self.mode_combo.currentData() == "cover"
        self._metadata_only = metadata_only

        def operation(emit, cancel):
            return run_info(
                specs,
                lambda event: emit({**event, "index": mapping[event["index"]]}),
                cancel,
                **({"metadata_only": True} if metadata_only else {}),
            )

        self._start_operation("info", operation)
        self._update_parse_summary()

    def _retry_parse(self, checked=False, indices=None):
        if (
            (self._thread is not None and self._active_kind != "download")
            or not self._parse_complete
            or getattr(self, "_aux", None)
        ):
            return
        valid = []
        for index in tuple(
            self._failed_parse if indices is None else self._failed_parse.intersection(indices)
        ):
            source = self._parse_sources[index][1]
            try:
                normalize_url(source)
            except BilixError:
                continue
            self._failed_parse.remove(index)
            self._parse_finished -= 1
            self._parse_errors -= 1
            self.metadata_tree.topLevelItem(index).setText(1, "等待读取")
            valid.append((index, JobSpec(source)))
        if valid:
            self._parse_complete = False
            self._run_parse(sorted(valid))

    def _inputs(self, *, validate_page=True):
        if validate_page and self._metadata:
            specs = []
            for index, data in sorted(self._metadata.items()):
                root = self.metadata_tree.topLevelItem(index)
                parts = [
                    str(root.child(j).data(0, Qt.ItemDataRole.UserRole))
                    for j in range(root.childCount())
                    if root.child(j).checkState(0) == Qt.CheckState.Checked
                ]
                if (
                    self.mode_combo.currentData() == "cover"
                    and root.checkState(0) != Qt.CheckState.Unchecked
                ):
                    specs.append(JobSpec(data["url"]))
                elif parts:
                    specs.append(JobSpec(data["url"], ",".join(parts)))
            if not specs:
                raise InputError("请勾选至少一个有效选集")
            return tuple(specs)
        page = None
        if validate_page:
            parse_pages(page)
        specs = []
        for number, line in enumerate(
            self.urls_edit.toPlainText().lstrip("\ufeff").splitlines(), 1
        ):
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            try:
                normalize_url(line.strip())
            except BilixError as error:
                raise InputError(f"第 {number} 行：{error}") from None
            specs.append(JobSpec(line.strip(), page))
        if not specs:
            raise InputError("请输入至少一个视频 URL/BV 号")
        return tuple(specs)

    def _update_draft_actions(self):
        idle = (
            self._thread is None
            and not getattr(self, "_pending_account", False)
            and not getattr(self, "_update_install_pending", False)
        )
        ready = bool(self._retry_context) or bool(
            self._parse_complete
            and self._info_generation == self._input_generation
            and self._metadata
        )
        selected = any(
            root.child(j).checkState(0) == Qt.CheckState.Checked
            for index in self._metadata
            if (root := self.metadata_tree.topLevelItem(index)) is not None
            for j in range(root.childCount())
        )
        reason = (
            ""
            if idle and ready and (selected or self._retry_context)
            else ("等待当前操作结束" if not idle else "请等待识别完成并勾选有效选集")
        )
        for button in (self.start_button, self.plan_button):
            button.setEnabled(not bool(reason) and not self.urls_edit.composing)
            button.setToolTip(reason)
        self.plan_button.setEnabled(self.plan_button.isEnabled() and not bool(self._retry_context))
        self.info_button.setEnabled(idle and not bool(self._retry_context))
        self.retry_parse_button.setEnabled(
            idle and self._parse_complete and bool(self._failed_parse)
        )
        if getattr(self, "_pending_parse", False) and not idle:
            self.parse_summary.setText(
                "等待账号验证…" if self._active_kind == "status" else "当前操作结束后自动识别"
            )

    def _shortcut_download(self):
        if not self.urls_edit.composing and self.start_button.isEnabled():
            self._start_download()

    def _start_download(self, dry_run=False, specs=None):
        if (
            (self._thread is not None and self._active_kind != "download")
            or self._close_pending
            or getattr(self, "_update_install_pending", False)
        ):
            return
        if self._retry_context:
            if dry_run:
                return
            tasks, sources = self._retry_context
            try:
                batch_id = self.session.retry(tasks, sources, self._options(False), enqueue=True)
            except BilixError as error:
                self._error(str(error))
                return
            self._draft_dialog.reject()
            self._start_batch(batch_id)
            return
        self._check_credentials(schedule=False)
        if specs is None and (
            not self._parse_complete or self._info_generation != self._input_generation
        ):
            self._request_parse()
            return
        try:
            selected = specs if specs is not None else self._inputs()
            options = self._options(dry_run)
            if dry_run:
                from .worker import run_download

                self.preview_text.clear()
                self._preview_dialog.show()
                self._start_operation("plan", partial(run_download, selected, options))
                return
            batch_id = self.session.begin(selected, options, enqueue=True)
        except BilixError as error:
            self._error(str(error))
            return
        self._remember_media_options()
        self._draft_dialog.hide()
        self._draft_open = False
        self._pending_parse = False
        self._parse_timer.stop()
        self.urls_edit.clear()
        self._start_batch(batch_id)

    def _start_batch(self, batch_id):
        from .history import NODE_ROLE
        from .worker import run_session

        self._download_batch = batch_id
        selected = self.jobs_view.currentIndex().data(NODE_ROLE)
        self.history_model.rebuild(self.session)
        self.history_filter.set_state("all")
        self.filter_combo.setCurrentIndex(0)
        self.list_stack.setCurrentIndex(1)
        self.jobs_view.expandAll()
        self.jobs_view.scrollToBottom()
        if selected and selected.kind == "task" and selected.identity in self.history_model.tasks:
            node = self.history_model.tasks[selected.identity]
            self.jobs_view.setCurrentIndex(
                self.history_filter.mapFromSource(self.history_model.row_index(node))
            )
        self._message("准备下载…")
        self._start_operation("download", partial(run_session, self.session, batch_id))

    def _put_options(self, options):
        for combo, value in (
            (self.quality_combo, options.quality),
            (self.codec_combo, options.codec),
            (self.audio_combo, options.audio),
            (self.mode_combo, options.mode),
        ):
            combo.setCurrentIndex(max(0, combo.findData(value)))
        self.output_edit.setText(str(options.save))
        self.save_cover_check.setChecked(options.cover)
        self.strict_check.setChecked(options.strict)
        self.overwrite_check.setChecked(options.overwrite)

    def _retry_ids(self, tasks, sources, current=False):
        if self._thread is not None and self._active_kind != "download":
            return
        if current:
            if not (tasks or sources):
                return
            if self._retry_context:
                self._open_draft(read_clipboard=False)
                return
            self._saved_draft = (self.urls_edit.toPlainText(), self._options(False))
            options = (
                self.session.tasks[tasks[0]].latest.options
                if tasks
                else self.session.requests[sources[0]].options
            )
            self._retry_context = tasks, sources
            self.urls_edit.setPlainText(
                f"重试 {len(tasks)} 个任务 / {len(sources)} 个来源\n"
                "身份固定，调整下方参数后点击下载"
            )
            self.urls_edit.setReadOnly(True)
            self._put_options(options)
            self.metadata_tree.setEnabled(False)
            self._draft_dialog.setWindowTitle("调整参数后重试")
            self._open_draft(read_clipboard=False)
            return
        try:
            batch_id = self.session.retry(tasks, sources, enqueue=True)
        except BilixError as error:
            self._error(str(error))
            return
        self._start_batch(batch_id)

    def _apply_all_ranges(self):
        for index in range(self.metadata_tree.topLevelItemCount()):
            self.metadata_tree.setCurrentItem(self.metadata_tree.topLevelItem(index))
            self._apply_part_range()

    def _credential_fingerprint(self):
        if self._settings is None:
            return None, "bad"
        try:
            path = load_settings().token_file
            if not path.exists():
                return (str(path), None), "none"
            raw = path.read_bytes()
            key = str(path), hashlib.sha256(raw).hexdigest()
            normalize_cookie(raw.decode("utf-8"), require_session=True)
            return key, "valid"
        except (BilixError, OSError, UnicodeError):
            return (str(self._settings.token_file), "unreadable"), "bad"

    def _check_credentials(self, *, schedule=True):
        key, state = self._credential_fingerprint()
        if key != self._credential_key:
            self._credential_key = key
            self._account_revision += 1
            self._pending_account = state == "valid"
            self._invalidate_info()
            if state == "valid":
                self._set_account("本地凭据待验证，将自动查询账号状态", "凭据待验证")
            elif state == "none":
                self._set_account("本地未保存凭据，可扫码登录", "未登录")
            else:
                self._set_account("本地凭据无法读取或格式错误，请修复或退出登录", "凭据不可读")
        if schedule:
            QTimer.singleShot(0, self._drain_pending)

    def _offline_account(self):
        self._check_credentials()

    def _set_busy(self, busy):
        for control in self._business_controls:
            control.setEnabled(not busy and self._settings is not None)
        for button in self._busy_buttons:
            button.setEnabled(not busy)
        labels = {
            "download": "取消本批下载",
            "plan": "取消预览",
            "info": "取消解析",
            "login": "取消登录",
            "status": "取消账号验证",
            "doctor": "取消诊断",
        }
        self.cancel_button.setText(labels.get(self._active_kind, "取消"))
        self.cancel_button.setEnabled(busy)
        self.cancel_button.setVisible(busy)
        for widget in (self.default_output_edit, self.ffmpeg_edit):
            widget.setEnabled(not busy)
        for action in (
            self.login_action,
            self.status_action,
            self.logout_action,
            self.doctor_action,
        ):
            action.setEnabled(not busy)
        for key in (QDialogButtonBox.StandardButton.Ok, QDialogButtonBox.StandardButton.Apply):
            self.settings_buttons.button(key).setEnabled(not busy)
        self._update_retry_button()
        self._update_draft_actions()

    def _cancel_active(self):
        if self._active_kind == "info":
            self._pending_parse = False
            self._parse_timer.stop()
            self._parse_complete = False
        elif self._active_kind == "status":
            self._pending_account = False
        if self._cancel:
            self._cancel.cancel()
            self.cancel_button.setEnabled(False)
            self.cancel_button.setText("正在取消…")
            self._message("正在取消，请等待当前请求或媒体处理停止…")

    def _context_valid(self, context):
        if context != self._active_context:
            return False
        kind, job, generation, revision = context
        if kind in ("info", "plan", "status"):
            self._check_credentials(schedule=False)
            if revision != self._account_revision:
                return False
        return kind not in ("info", "plan") or generation == self._input_generation

    def _deliver_event(self, context, event):
        if self._context_valid(context):
            self._on_event(event)

    def _deliver_done(self, context, result):
        if self._context_valid(context):
            self._on_done(result)

    def _update_counts(self):
        counts = Counter(self.history_model.counts)
        reread = {r.origin_request_id for r in self.session.requests.values()}
        for identity, request in self.session.requests.items():
            row = self.history_model.sources.get(identity)
            if (
                identity not in reread
                and (row is None or not row.children)
                and request.state != "discovered"
            ):
                counts[request.state] += 1
        values = {
            "all": sum(counts.values()),
            "success": counts["completed"] + counts["skipped"],
            "failed": counts["failed"],
            "canceled": counts["canceled"],
        }
        values["active"] = values["all"] - sum(values[s] for s in ("success", "failed", "canceled"))
        for state, button in self.filter_buttons.items():
            text = self.filter_combo.itemText(self.filter_combo.findData(state))
            button.setText(f"{text} {values[state]}")
            button.setChecked(self.filter_combo.currentData() == state)
        primary = self.history_model.rowCount() > 0
        if self.new_button.property("primary") != primary:
            self.new_button.setProperty("primary", primary)
            self.new_button.style().unpolish(self.new_button)
            self.new_button.style().polish(self.new_button)

    def _row_menu(self, index):
        if index.column() == 3:
            self._update_retry_button()
            self.selection_menu.popup(
                self.jobs_view.viewport().mapToGlobal(self.jobs_view.visualRect(index).bottomLeft())
            )

    def _keyboard_menu(self):
        index = self.jobs_view.currentIndex()
        if index.isValid():
            self._update_retry_button()
            self.selection_menu.popup(
                self.jobs_view.viewport().mapToGlobal(self.jobs_view.visualRect(index).bottomLeft())
            )

    def _remember_media_options(self):
        if not self._remember_options:
            return
        for name, combo in (
            ("quality", self.quality_combo),
            ("codec", self.codec_combo),
            ("audio", self.audio_combo),
            ("mode", self.mode_combo),
        ):
            self._prefs.setValue(name, combo.currentData() or "")
        self._prefs.setValue("strict", self.strict_check.isChecked())
        self._prefs.setValue("cover", self.save_cover_check.isChecked())

    def _restore_media_options(self):
        for name, combo, default in (
            ("quality", self.quality_combo, None),
            ("codec", self.codec_combo, None),
            ("audio", self.audio_combo, "aac"),
            ("mode", self.mode_combo, "merged"),
        ):
            raw = self._prefs.value(name, default) if self._remember_options else default
            value = int(raw) if name == "quality" and str(raw).isdigit() else raw or default
            index = combo.findData(value)
            combo.setCurrentIndex(index if index >= 0 else combo.findData(default))
        self.save_cover_check.setChecked(
            self._remember_options and self._pref("cover", False, bool)
        )
        self.strict_check.setChecked(self._remember_options and self._pref("strict", False, bool))
        self.advanced_toggle.setChecked(self._pref("advancedExpanded", False, bool))

    def _discard_gui_settings(self):
        self.tray_check.setChecked(self._tray_enabled)
        self.notify_check.setChecked(self._notify_enabled)
        self.auto_update_check.setChecked(self._auto_update_enabled)
        self.theme_combo.setCurrentIndex(self.theme_combo.findData(self._theme_mode))
        self.remember_check.setChecked(self._remember_options)
        self.feedback_check.setChecked(self._show_feedback)

    def _discard_settings(self):
        self._load_settings_view()
        self._discard_gui_settings()

    def _accept_settings(self):
        if self._save_settings():
            self._settings_dialog.accept()

    def _init_tray(self):
        from PySide6.QtWidgets import QSystemTrayIcon

        self.tray = QSystemTrayIcon(
            QIcon(str(Path(__file__).parents[1] / "assets/bilix-64.png")), self
        )
        self.tray.setToolTip(f"BiliX {__version__}")
        menu = QMenu(self)
        menu.addAction("显示主窗口", self._restore_main)
        menu.addAction("新建下载", self._open_draft)
        menu.addAction("打开默认下载目录", self._open_default_folder)
        menu.addSeparator()
        self.tray_exit_action = menu.addAction("退出", self._request_exit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.messageClicked.connect(self._notification_clicked)
        if self._tray_available():
            self.tray.show()
        self._tray_watch = QTimer(self)
        self._tray_watch.setInterval(3000)
        self._tray_watch.timeout.connect(self._check_tray)
        self._tray_watch.start()

    def _tray_available(self):
        from PySide6.QtWidgets import QSystemTrayIcon

        return QSystemTrayIcon.isSystemTrayAvailable() and not self.tray.icon().isNull()

    def _check_tray(self):
        if self._tray_available():
            self.tray.show()
        elif self._in_tray:
            self._restore_main()
        else:
            self.tray.hide()

    def _tray_activated(self, reason):
        from PySide6.QtWidgets import QSystemTrayIcon

        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self._restore_main()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange and hasattr(self, "tray"):
            if self.isMinimized() and self._tray_enabled and self._tray_available():
                old = event.oldState()
                self._tray_normal_state = old & ~Qt.WindowState.WindowMinimized
                QTimer.singleShot(0, self._hide_to_tray)
        elif event.type() == QEvent.Type.PaletteChange and hasattr(self, "new_button"):
            self._refresh_icons()

    def _hide_to_tray(self, *, closing=False):
        if (
            self._close_pending
            or not (closing or self.isMinimized())
            or not self._tray_enabled
            or not self._tray_available()
        ):
            return
        if closing:
            self._tray_normal_state = self.windowState() & ~Qt.WindowState.WindowMinimized
        self.tray.show()
        self._tray_hidden_windows = [w for w in self.findChildren(QDialog) if w.isVisible()]
        for window in self._tray_hidden_windows:
            window.hide()
        self._in_tray = True
        self.hide()

    def _restore_main(self):
        if not hasattr(self, "_tray_hidden_windows"):
            return
        if not self.isVisible() or self.isMinimized():
            self.setWindowState(self._tray_normal_state)
            self.show()
        self.raise_()
        self.activateWindow()
        for window in self._tray_hidden_windows:
            window.show()
        self._tray_hidden_windows = []
        self._in_tray = False

    def _notify_batch(self, counts):
        from PySide6.QtWidgets import QSystemTrayIcon

        batch_id = self._download_batch
        if not batch_id or batch_id in self._notified_batches or self._close_pending:
            return
        self._notified_batches.add(batch_id)
        if (
            counts.get("canceled", 0)
            or counts.get("source_canceled", 0)
            or self._cancel
            and self._cancel.cancelled()
            or not self._notify_enabled
            or not self._tray_available()
            or not self.tray.supportsMessages()
        ):
            return
        failed = counts["failed"] + counts["source_failed"]
        title = "本批下载已结束，有失败项目" if failed else "本批下载完成"
        text = (
            f"完成 {counts['completed']} · 跳过 {counts['skipped']} · "
            f"失败 {counts['failed']} · 读取失败 {counts['source_failed']}"
        )
        self._last_notified_batch = batch_id
        try:
            self.tray.showMessage(
                f"BiliX · {title}",
                text,
                QSystemTrayIcon.MessageIcon.Warning
                if failed
                else QSystemTrayIcon.MessageIcon.Information,
            )
        except RuntimeError:
            pass

    def _notification_clicked(self):
        self._restore_main()
        batch = self.session.batches.get(self._last_notified_batch)
        if not batch:
            return
        nodes = [self.history_model.tasks[i] for i in batch.tasks if i in self.history_model.tasks]
        nodes += [
            self.history_model.sources[i] for i in batch.requests if i in self.history_model.sources
        ]
        if nodes:
            self._open_node_details(nodes[0], batch.batch_id)
        else:
            self.details_summary.setText("本批下载记录已清除")
            self.info_text.clear()
            self.batch_combo.clear()
            self.batch_combo.addItem(f"批次 {batch.batch_id[:8]}", batch.batch_id)
            self._show_batch()
            self._details_dialog.show()
            self._details_dialog.raise_()
            self._details_dialog.activateWindow()

    def _copy_diagnostics(self):
        text = (
            f"BiliX {__version__}\nPython {sys.version.split()[0]}\nQt {qVersion()}\n"
            f"平台 {sys.platform}\n当前操作 {self._active_kind or '空闲'}\n"
            f"媒体任务 {len(self.session.tasks)}\n托盘可用 {self._tray_available()}"
        )
        for line in self.doctor_text.toPlainText().splitlines():
            if line.startswith("ffmpeg version "):
                text += "\n" + " ".join(line.split()[:3])
                break
        dialog, layout, close = self._dialog("诊断摘要预览", 560, 360)
        preview = QPlainTextEdit(text)
        preview.setReadOnly(True)
        layout.addWidget(preview)
        buttons = QDialogButtonBox()
        copy = buttons.addButton("复制", QDialogButtonBox.ButtonRole.ActionRole)
        copy.clicked.connect(lambda: QApplication.clipboard().setText(text))
        layout.addWidget(buttons)
        layout.addWidget(close)
        dialog.show()

    def _error(self, message):
        if not self.isVisible() and not self._draft_dialog.isVisible():
            self._message(message)
        else:
            QMessageBox.warning(
                self._draft_dialog if self._draft_dialog.isVisible() else self, "BiliX", message
            )

    def _request_exit(self):
        self._exit_requested = True
        self.close()

    def closeEvent(self, event):
        if not self._exit_requested and self._tray_enabled and not self._close_pending:
            event.ignore()
            if self._tray_available():
                self._hide_to_tray(closing=True)
            else:
                self.showMinimized()
            return
        if self._thread is not None:
            if not self._close_pending:
                if self._active_kind == "download":
                    self._restore_main()
                    answer = QMessageBox.question(
                        self,
                        "下载进行中",
                        "停止本批下载并退出？",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.No,
                    )
                    if answer != QMessageBox.StandardButton.Yes:
                        self._exit_requested = False
                        event.ignore()
                        return
                self._close_pending = True
                self._pending_parse = self._pending_account = False
                self._parse_timer.stop()
                self._cancel_active()
            event.ignore()
            return
        self._close_pending = True
        if not self._stop_updater():
            event.ignore()
            return
        self._pending_parse = self._pending_account = False
        self._parse_timer.stop()
        self._tray_watch.stop()
        self._feedback_timer.stop()
        self._prefs.setValue("geometry", self.saveGeometry())
        for column in (1, 2):
            self._prefs.setValue(f"column{column}", self.jobs_view.columnWidth(column))
        self._prefs.sync()
        self.tray.hide()
        for dialog in self.findChildren(QDialog):
            dialog.hide()
        super().closeEvent(event)
        self.closed.emit()
