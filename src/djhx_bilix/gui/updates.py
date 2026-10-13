"""Compact GUI updater controls, independent from media/account workers."""

from __future__ import annotations

from threading import Event

from PySide6.QtCore import QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QPushButton, QWidget

from djhx_bilix.updater.apply import handoff
from djhx_bilix.updater.client import UpdateClient, distribution, update_cache
from djhx_bilix.updater.protocol import UpdateCanceled, UpdateError


class UpdateJob(QThread):
    progress = Signal(str, object, object)
    done = Signal(object)

    def __init__(self, operation, parent):
        super().__init__(parent)
        self.cancel = Event()
        self.operation = operation

    def run(self):
        try:
            self.done.emit({"value": self.operation(self.cancel, self.progress.emit)})
        except UpdateCanceled:
            self.done.emit({"canceled": True})
        except Exception as exc:
            self.done.emit({"error": str(exc)})


class UpdateActions:
    def _init_updater(self):
        self._update_thread = None
        self._prepared_update = None
        self._update_install_pending = False
        self._update_handoff = False
        self._update_manual = False
        self._updater_closing = False
        self._update_identity = None
        self._update_identity_error = ""
        try:
            self._update_identity = distribution()
        except (UpdateError, OSError) as exc:
            self._update_identity_error = str(exc)
        self.update_status = QLabel()
        self.update_status.setObjectName("updateStatus")
        self.update_progress = QProgressBar()
        self.update_progress.setFixedWidth(90)
        self.update_progress.setRange(0, 100)
        self.update_progress.setTextVisible(False)
        self.update_progress.setFixedHeight(8)
        self.update_progress.hide()
        self.update_button = QPushButton("更新")
        self.update_button.clicked.connect(self._apply_update)
        self.update_button.hide()
        self.update_cancel = QPushButton("取消")
        self.update_cancel.clicked.connect(self._cancel_update_download)
        self.update_cancel.hide()
        self.update_folder = QPushButton("更新文件")
        self.update_folder.clicked.connect(self._open_update_folder)
        self.update_folder.hide()
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 6, 0)
        for widget in (
            self.update_status,
            self.update_progress,
            self.update_button,
            self.update_cancel,
            self.update_folder,
        ):
            layout.addWidget(widget)
        self.statusBar().insertWidget(0, row)
        self._update_timer = QTimer(self)
        self._update_timer.setInterval(30 * 60 * 1000)
        self._update_timer.timeout.connect(self._check_update)
        self._configure_update_timer()
        if self._auto_update_enabled and self._update_identity is not None:
            QTimer.singleShot(0, self._check_update)

    def _configure_update_timer(self):
        if not hasattr(self, "_update_timer"):
            return
        if self._auto_update_enabled and self._update_identity is not None:
            self._update_timer.start()
        else:
            self._update_timer.stop()
            if (
                self._update_thread is not None
                and not self._update_manual
                and not self._update_handoff
            ):
                self._update_thread.cancel.set()

    def _check_update(self, manual=False):
        if (
            self._updater_closing
            or self._close_pending
            or self._update_thread is not None
            or self._update_install_pending
        ):
            return
        if not manual and not self._auto_update_enabled:
            return
        if self._update_identity is None:
            if manual:
                self._error(
                    self._update_identity_error
                    or "当前 GUI 由 pip/源码环境管理，请使用原安装方式手动升级。"
                )
            return
        self._update_manual = manual
        self.update_button.hide()
        self._start_update_job(
            lambda cancel, progress: UpdateClient(
                self._update_identity,
                cancel,
            ).prepare(progress)
        )

    def _start_update_job(self, operation):
        job = UpdateJob(operation, self)
        job.progress.connect(self._update_progress)
        job.done.connect(self._update_done)
        job.finished.connect(self._update_finished)
        job.finished.connect(job.deleteLater)
        self._update_thread = job
        self.check_update_action.setEnabled(False)
        self.update_cancel.setEnabled(True)
        self.update_cancel.setVisible(not self._update_handoff)
        job.start()

    def _update_progress(self, state, count, total):
        if self._updater_closing:
            return
        text = {"checking": "正在检查更新…", "verifying": "正在校验更新…"}.get(state)
        self.update_progress.setVisible(state == "downloading")
        if state == "downloading":
            percentage = int(count * 100 / total) if total else 0
            self.update_progress.setValue(percentage)
            text = f"正在下载更新 · {percentage}%"
        self.update_status.setText(text or "正在准备更新…")

    def _update_done(self, result):
        self.update_progress.hide()
        self.update_cancel.hide()
        if self._updater_closing and not self._update_handoff:
            return
        if self._update_handoff:
            self._update_handoff = False
            if "error" not in result and not result.get("canceled"):
                self.update_status.setText("即将退出并更新…")
                self._exit_requested = True
                self._close_pending = True
                return  # Close after the update QThread has finished too.
            self._update_install_pending = False
            self._set_busy(False)
            self._configure_update_timer()
        if result.get("error"):
            self.update_status.setText("暂时无法更新")
            self.update_status.setToolTip(result["error"])
            self.update_folder.show()
            if self._update_manual:
                self._error(result["error"])
        elif result.get("canceled"):
            self.update_status.setText("更新下载已取消")
        elif result.get("value") is not None:
            self._prepared_update = result["value"]
            self._show_update_ready()
        else:
            self._prepared_update = None
            self.update_status.setText("已是最新版本" if self._update_manual else "")
        if (result.get("error") or result.get("canceled")) and self._prepared_update is not None:
            # Keep a retry entry without hiding the failure behind the old ready state.
            # handoff() revalidates cached bytes on every attempt.
            self.update_button.setText("重试更新" if result.get("error") else "更新")
            self.update_button.show()

    def _update_finished(self):
        self._update_thread = None
        self.check_update_action.setEnabled(True)
        if self._close_pending or self._updater_closing:
            QTimer.singleShot(0, self.close)

    def _show_update_ready(self):
        self.update_status.setText(f"{self._prepared_update.artifact.version} 更新已就绪")
        self.update_button.setText("更新")
        self.update_button.setToolTip("安装并重启；草稿和列表记录不会保留，等待本批下载结束。")
        self.update_button.show()
        self.update_folder.show()

    def _cancel_update_download(self):
        if self._update_thread is not None and not self._update_handoff:
            self._update_thread.cancel.set()
            self.update_cancel.setEnabled(False)

    def _open_update_folder(self):
        folder = self._prepared_update.directory if self._prepared_update else update_cache()
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _apply_update(self):
        if self._update_thread is not None or self._prepared_update is None:
            return
        if self._update_install_pending:
            self._update_install_pending = False
            self._show_update_ready()
            if self._thread is None:
                self._set_busy(False)
            return
        self._update_install_pending = True
        self._pending_parse = self._pending_account = False
        self._parse_timer.stop()
        self.update_status.setToolTip("更新会退出并重启；草稿和本次列表记录不会跨重启保留。")
        self._set_busy(True)
        self._maybe_apply_update()

    def _maybe_apply_update(self):
        if not self._update_install_pending:
            return False
        if self._thread is not None:
            self.update_status.setText("更新等待本批操作结束")
            self.update_button.setText("取消等待")
            return True
        if self._update_thread is not None:
            return True
        if self._settings is None:
            self._update_install_pending = False
            self._set_busy(False)
            self._error("请先修正配置文件，再安装更新")
            return False
        self._remember_media_options()
        self._prefs.sync()
        self.cancel_button.hide()
        self._update_timer.stop()
        self._update_handoff = True
        self._update_manual = True
        self.update_button.hide()
        self.update_status.setText("正在准备退出和更新…")
        self.update_status.setToolTip("更新会退出并重启；草稿和本次列表记录不会跨重启保留。")
        self._start_update_job(
            lambda cancel, progress: handoff(
                self._prepared_update,
                self._update_identity,
                self._settings.config_dir,
            )
        )
        return True

    def _stop_updater(self):
        self._updater_closing = True
        self._update_timer.stop()
        if self._update_thread is not None:
            self._update_thread.cancel.set()
            return False
        return True
