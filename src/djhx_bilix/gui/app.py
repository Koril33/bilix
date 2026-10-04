"""Qt Widgets front end for the existing BiliX download engine."""

from __future__ import annotations

import sys
from functools import partial
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QThread, QTimer, QUrl
from PySide6.QtGui import QCloseEvent, QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from djhx_bilix import __version__, auth
from djhx_bilix.config import Settings, load_settings, save_settings
from djhx_bilix.errors import BilixError, InputError
from djhx_bilix.media import FFmpeg, find_ffmpeg
from djhx_bilix.models import QUALITY_NAMES
from djhx_bilix.operations import CancellationToken
from djhx_bilix.planner import parse_quality
from djhx_bilix.urls import load_urls, normalize_url, parse_pages

from .worker import (
    DownloadOptions,
    JobSpec,
    OperationWorker,
    run_doctor,
    run_download,
    run_info,
    run_login,
    run_status,
)

_RETRY_ROLE = Qt.ItemDataRole.UserRole
_OUTPUT_ROLE = Qt.ItemDataRole.UserRole + 1
_STATE_ROLE = Qt.ItemDataRole.UserRole + 2

_STAGES = {
    "downloading": "下载中",
    "checking_video": "校验视频",
    "checking_audio": "校验音频",
    "muxing": "合并音视频",
    "committing": "保存文件",
    "completed": "完成",
    "skipped": "跳过",
}
_STATES = {
    "queued": "排队中",
    "loading": "读取信息",
    "downloading": "下载中",
    "checking_video": "校验视频",
    "checking_audio": "校验音频",
    "muxing": "合并音视频",
    "committing": "保存文件",
    "completed": "完成",
    "skipped": "跳过",
    "failed": "失败",
    "canceled": "已取消",
    "planned": "已规划",
}


def _display_size(value: int) -> str:
    size = float(value)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024 or unit == "GiB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return str(value)


class MainWindow(QMainWindow):
    """One active background operation; downloads form a serial, visible queue."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"BiliX {__version__}")
        self.resize(940, 760)
        self.setMinimumSize(760, 590)
        self._settings: Settings | None = None
        self._thread: QThread | None = None
        self._worker: OperationWorker | None = None
        self._cancel: CancellationToken | None = None
        self._active_kind: str | None = None
        self._close_pending = False
        self._row_for_key: dict[tuple[int, int], int] = {}
        self._qr_dialog: QDialog | None = None
        self._qr_label: QLabel | None = None
        self._qr_status: QLabel | None = None
        self._busy_buttons: list[QPushButton] = []

        tabs = QTabWidget(self)
        self.setCentralWidget(tabs)
        tabs.addTab(self._make_download_tab(), "下载")
        tabs.addTab(self._make_account_tab(), "账号")
        tabs.addTab(self._make_settings_tab(), "设置")
        tabs.addTab(self._make_doctor_tab(), "诊断")
        self.statusBar().showMessage("就绪")
        self._load_settings_view()

    def _button(self, text: str, callback: Any, busy_sensitive: bool = True) -> QPushButton:
        button = QPushButton(text)
        button.clicked.connect(callback)
        if busy_sensitive:
            self._busy_buttons.append(button)
        return button

    def _make_download_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(9)

        input_group = QGroupBox("视频链接 / BV 号（每行一个）")
        input_layout = QVBoxLayout(input_group)
        self.urls_edit = QPlainTextEdit()
        self.urls_edit.setPlaceholderText("粘贴 Bilibili 视频、番剧链接或 BV 号，每行一个")
        self.urls_edit.setMaximumHeight(100)
        input_layout.addWidget(self.urls_edit)
        input_actions = QHBoxLayout()
        input_actions.addWidget(self._button("导入 URL 文件", self._import_urls))
        input_actions.addWidget(self._button("查看信息", self._start_info))
        input_actions.addStretch()
        input_layout.addLayout(input_actions)
        layout.addWidget(input_group)

        options_group = QGroupBox("下载选项")
        options = QFormLayout(options_group)
        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("保存目录")
        output_row = QHBoxLayout()
        output_row.addWidget(self.output_edit)
        output_row.addWidget(self._button("选择…", self._choose_output))
        options.addRow("保存到", output_row)

        selections = QHBoxLayout()
        self.quality_combo = QComboBox()
        self.quality_combo.addItem("自动 / 当前可获取的最高画质", None)
        for quality in sorted(QUALITY_NAMES, reverse=True):
            self.quality_combo.addItem(f"{QUALITY_NAMES[quality]} ({quality})", quality)
        selections.addWidget(QLabel("画质"))
        selections.addWidget(self.quality_combo, 3)
        self.codec_combo = QComboBox()
        for label, value in (("自动", None), ("AVC", "AVC"), ("HEVC", "HEVC"), ("AV1", "AV1")):
            self.codec_combo.addItem(label, value)
        selections.addWidget(QLabel("编码"))
        selections.addWidget(self.codec_combo, 1)
        self.audio_combo = QComboBox()
        for label, value in (
            ("AAC", "aac"),
            ("FLAC", "flac"),
            ("Dolby", "dolby"),
            ("最佳", "best"),
        ):
            self.audio_combo.addItem(label, value)
        selections.addWidget(QLabel("音轨"))
        selections.addWidget(self.audio_combo, 1)
        options.addRow("媒体", selections)

        page_row = QHBoxLayout()
        self.page_edit = QLineEdit()
        self.page_edit.setPlaceholderText("留空遵循链接中的 ?p=；all 为全部；也可填 1,3,5-7")
        page_row.addWidget(self.page_edit)
        self.strict_check = QCheckBox("必须精确匹配画质 / 编码")
        self.overwrite_check = QCheckBox("覆盖同名文件")
        page_row.addWidget(self.strict_check)
        page_row.addWidget(self.overwrite_check)
        options.addRow("选集", page_row)
        layout.addWidget(options_group)

        actions = QHBoxLayout()
        self.start_button = self._button("开始下载", self._start_download)
        self.plan_button = self._button("预览计划", lambda: self._start_download(True))
        self.retry_button = self._button("重试失败项", self._retry_failed)
        self.retry_button.setEnabled(False)
        self.cancel_button = QPushButton("取消当前操作")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._cancel_active)
        actions.addWidget(self.start_button)
        actions.addWidget(self.plan_button)
        actions.addWidget(self.retry_button)
        actions.addWidget(self.cancel_button)
        actions.addStretch()
        layout.addLayout(actions)

        self.jobs_table = QTableWidget(0, 4)
        self.jobs_table.setHorizontalHeaderLabels(["视频 / 选集", "状态", "进度", "文件 / 说明"])
        self.jobs_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.jobs_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.jobs_table.verticalHeader().setVisible(False)
        header = self.jobs_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.jobs_table.doubleClicked.connect(self._open_selected_folder)
        layout.addWidget(self.jobs_table, 4)

        progress_row = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("等待任务")
        progress_row.addWidget(self.progress_bar, 1)
        progress_row.addWidget(self._button("打开输出目录", self._open_selected_folder))
        layout.addLayout(progress_row)

        info_group = QGroupBox("视频信息 / 计划")
        info_layout = QVBoxLayout(info_group)
        self.info_text = QPlainTextEdit()
        self.info_text.setReadOnly(True)
        self.info_text.setMaximumHeight(145)
        info_layout.addWidget(self.info_text)
        layout.addWidget(info_group, 1)
        return page

    def _make_account_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.account_label = QLabel("点击“查询状态”查看当前账号。扫码登录会使用手机哔哩哔哩 App。")
        self.account_label.setWordWrap(True)
        layout.addWidget(self.account_label)
        buttons = QHBoxLayout()
        buttons.addWidget(self._button("扫码登录", self._start_login))
        buttons.addWidget(self._button("查询状态", self._start_status))
        buttons.addWidget(self._button("退出登录", self._logout))
        buttons.addStretch()
        layout.addLayout(buttons)
        layout.addStretch()
        return page

    def _make_settings_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        form = QFormLayout()
        self.default_output_edit = QLineEdit()
        output_row = QHBoxLayout()
        output_row.addWidget(self.default_output_edit)
        output_row.addWidget(self._button("选择…", self._choose_default_output))
        form.addRow("默认下载目录", output_row)
        self.ffmpeg_edit = QLineEdit()
        self.ffmpeg_edit.setPlaceholderText("留空时自动查找 FFmpeg")
        ffmpeg_row = QHBoxLayout()
        ffmpeg_row.addWidget(self.ffmpeg_edit)
        ffmpeg_row.addWidget(self._button("选择…", self._choose_ffmpeg))
        form.addRow("FFmpeg 路径", ffmpeg_row)
        self.config_path_label = QLabel()
        self.config_path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        form.addRow("配置文件", self.config_path_label)
        layout.addLayout(form)
        controls = QHBoxLayout()
        controls.addWidget(self._button("保存设置", self._save_settings))
        controls.addWidget(self._button("打开配置目录", self._open_config_folder))
        controls.addStretch()
        layout.addLayout(controls)
        self.settings_hint = QLabel(
            "设置与 CLI 共用 config.toml。"
            "BILIX_DOWNLOAD_DIR、BILIX_FFMPEG 等环境变量会优先于文件设置。"
        )
        self.settings_hint.setWordWrap(True)
        layout.addWidget(self.settings_hint)
        layout.addStretch()
        return page

    def _make_doctor_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("检查程序版本、配置目录和 FFmpeg；这项检查不会访问网络。"))
        buttons = QHBoxLayout()
        buttons.addWidget(self._button("运行诊断", self._start_doctor))
        buttons.addStretch()
        layout.addLayout(buttons)
        self.doctor_text = QPlainTextEdit()
        self.doctor_text.setReadOnly(True)
        layout.addWidget(self.doctor_text)
        return page

    def _load_settings_view(self) -> None:
        try:
            settings = load_settings()
        except BilixError as error:
            self._settings = None
            self.settings_hint.setText(f"配置无法读取：{error}。请修正配置文件后重新打开程序。")
            self.statusBar().showMessage("配置需要修正")
            return
        self._settings = settings
        self.default_output_edit.setText(str(settings.download_dir))
        self.output_edit.setText(str(settings.download_dir))
        self.ffmpeg_edit.setText(settings.ffmpeg or "")
        self.config_path_label.setText(str(settings.config_file))

    def _save_settings(self) -> None:
        if self._settings is None:
            self._error("请先修正配置文件并重新打开程序")
            return
        if not self.default_output_edit.text().strip():
            self._error("请填写默认下载目录")
            return
        previous = str(self._settings.download_dir)
        try:
            updated = save_settings(
                self._settings,
                download_dir=Path(self.default_output_edit.text().strip()).expanduser(),
                ffmpeg=self.ffmpeg_edit.text().strip() or None,
            )
        except BilixError as error:
            self._error(str(error))
            return
        except OSError:
            self._error("无法保存设置，请检查配置目录权限")
            return
        self._settings = updated
        if self.output_edit.text().strip() == previous:
            self.output_edit.setText(str(updated.download_dir))
        self.statusBar().showMessage("设置已保存，与 CLI 共用", 5000)

    def _choose_output(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "选择保存目录", self.output_edit.text())
        if directory:
            self.output_edit.setText(directory)

    def _choose_default_output(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self, "选择默认下载目录", self.default_output_edit.text()
        )
        if directory:
            self.default_output_edit.setText(directory)

    def _choose_ffmpeg(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self, "选择 FFmpeg 程序", self.ffmpeg_edit.text()
        )
        if path:
            self.ffmpeg_edit.setText(path)

    def _open_config_folder(self) -> None:
        if self._settings is not None:
            self._open_folder(self._settings.config_dir)

    def _open_folder(self, folder: Path) -> None:
        if not folder.is_dir():
            self._error("目录尚不存在")
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder))):
            self._error("无法打开目录，请检查桌面环境的文件管理器")

    def _open_selected_folder(self, *_args: Any) -> None:
        row = self.jobs_table.currentRow()
        if row >= 0:
            output = self.jobs_table.item(row, 0).data(_OUTPUT_ROLE)
            if output:
                self._open_folder(Path(output).parent)
                return
        self._open_folder(Path(self.output_edit.text().strip()).expanduser())

    def _import_urls(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self, "导入 UTF-8 URL 列表", "", "文本文件 (*.txt);;所有文件 (*)"
        )
        if not path:
            return
        try:
            urls = load_urls(Path(path))
        except BilixError as error:
            self._error(str(error))
            return
        if not urls:
            self._error("文件中没有可用的 URL 或 BV 号")
            return
        previous = self.urls_edit.toPlainText().strip()
        self.urls_edit.setPlainText("\n".join([previous, *urls] if previous else urls))
        self.statusBar().showMessage(f"已导入 {len(urls)} 个地址", 5000)

    def _inputs(self, *, validate_page: bool = True) -> tuple[JobSpec, ...]:
        values = [
            (line_number, line.strip())
            for line_number, line in enumerate(self.urls_edit.toPlainText().splitlines(), 1)
            if line.strip() and not line.lstrip().startswith("#")
        ]
        if not values:
            raise InputError("请输入至少一个视频 URL/BV 号，或导入 URL 文件")
        for line_number, value in values:
            try:
                normalize_url(value)
            except BilixError as error:
                raise InputError(f"第 {line_number} 行：{error}") from None
        page = self.page_edit.text().strip() or None if validate_page else None
        if validate_page:
            parse_pages(page)
        return tuple(JobSpec(value, page) for _line_number, value in values)

    def _options(self, dry_run: bool) -> DownloadOptions:
        raw_dir = self.output_edit.text().strip()
        if not raw_dir:
            raise InputError("请选择保存目录")
        save = Path(raw_dir).expanduser()
        if save.exists() and not save.is_dir():
            raise InputError("保存路径已存在但不是目录")
        quality = self.quality_combo.currentData()
        if quality is not None:
            parse_quality(str(quality))
        return DownloadOptions(
            quality=quality,
            codec=self.codec_combo.currentData(),
            audio=self.audio_combo.currentData(),
            save=save,
            strict=self.strict_check.isChecked(),
            overwrite=self.overwrite_check.isChecked(),
            ffmpeg=None,
            dry_run=dry_run,
        )

    def _new_row(self, key: tuple[int, int], label: str, retry: JobSpec) -> int:
        row = self.jobs_table.rowCount()
        if key[1] > 0:
            siblings = [
                index for (source, _part), index in self._row_for_key.items() if source == key[0]
            ]
            if siblings:
                row = max(siblings) + 1
                for existing_key, existing_row in tuple(self._row_for_key.items()):
                    if existing_row >= row:
                        self._row_for_key[existing_key] = existing_row + 1
        self.jobs_table.insertRow(row)
        for column, text in enumerate((label, _STATES["queued"], "", "")):
            self.jobs_table.setItem(row, column, QTableWidgetItem(text))
        name = self.jobs_table.item(row, 0)
        name.setData(_RETRY_ROLE, retry)
        name.setData(_STATE_ROLE, "queued")
        self._row_for_key[key] = row
        return row

    def _prepare_queue(self, specs: tuple[JobSpec, ...]) -> None:
        self.jobs_table.setRowCount(0)
        self._row_for_key.clear()
        for index, spec in enumerate(specs):
            self._new_row((index, 0), spec.source, spec)
        self.retry_button.setEnabled(False)
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setFormat("准备任务…")

    def _start_download(
        self, dry_run: bool = False, specs: tuple[JobSpec, ...] | None = None
    ) -> None:
        try:
            selected = specs if specs is not None else self._inputs()
            options = self._options(dry_run)
        except BilixError as error:
            self._error(str(error))
            return
        self._prepare_queue(selected)
        self._start_operation(
            "plan" if dry_run else "download",
            partial(run_download, selected, options),
        )

    def _retry_failed(self) -> None:
        specs = []
        for row in range(self.jobs_table.rowCount()):
            name = self.jobs_table.item(row, 0)
            if name.data(_STATE_ROLE) in ("failed", "canceled"):
                specs.append(name.data(_RETRY_ROLE))
        if specs:
            self._start_download(False, tuple(specs))

    def _start_info(self) -> None:
        try:
            specs = self._inputs(validate_page=False)
        except BilixError as error:
            self._error(str(error))
            return
        self.info_text.clear()
        self._start_operation("info", partial(run_info, specs))

    def _start_login(self) -> None:
        if not self._start_operation("login", run_login):
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("BiliX 扫码登录")
        dialog.setMinimumWidth(300)
        layout = QVBoxLayout(dialog)
        status = QLabel("正在获取二维码…")
        status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        image = QLabel()
        image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        image.setMinimumSize(240, 240)
        cancel = QPushButton("取消登录")
        cancel.clicked.connect(dialog.reject)
        layout.addWidget(status)
        layout.addWidget(image)
        layout.addWidget(cancel)
        dialog.rejected.connect(self._cancel_active)
        self._qr_dialog = dialog
        self._qr_label = image
        self._qr_status = status
        dialog.show()

    def _start_status(self) -> None:
        self.account_label.setText("正在查询账号状态…")
        self._start_operation("status", run_status)

    def _logout(self) -> None:
        if self._settings is None:
            self._error("配置无法读取")
            return
        if (
            QMessageBox.question(self, "确认退出登录", "删除本机保存的登录凭据？")
            != QMessageBox.StandardButton.Yes
        ):
            return
        try:
            auth.logout(load_settings())
        except (BilixError, OSError):
            self._error("无法删除登录凭据，请检查配置目录权限")
            return
        self.account_label.setText("已退出登录，本地凭据已删除。")

    def _start_doctor(self) -> None:
        self.doctor_text.setPlainText("正在检查…")
        self._start_operation("doctor", run_doctor)

    def _start_operation(self, kind: str, operation: Any) -> bool:
        if self._thread is not None:
            self._error("请等待当前操作结束，或先取消")
            return False
        self._active_kind = kind
        self._cancel = CancellationToken()
        thread = QThread(self)
        worker = OperationWorker(operation, self._cancel)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.event.connect(self._on_event)
        worker.done.connect(self._on_done)
        worker.done.connect(thread.quit)
        thread.finished.connect(self._on_thread_finished)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._thread = thread
        self._worker = worker
        self._set_busy(True)
        self.statusBar().showMessage("操作进行中…")
        thread.start()
        return True

    def _set_busy(self, busy: bool) -> None:
        for button in self._busy_buttons:
            button.setEnabled(not busy)
        self.cancel_button.setEnabled(busy)
        if not busy:
            self._update_retry_button()

    def _cancel_active(self) -> None:
        if self._cancel is not None:
            self._cancel.cancel()
            self.cancel_button.setEnabled(False)
            self.statusBar().showMessage("正在取消，请等待当前请求或媒体处理停止…")

    def _on_event(self, event: dict[str, Any]) -> None:
        kind = event["type"]
        if kind == "info":
            previous = self.info_text.toPlainText()
            self.info_text.setPlainText((previous + "\n\n" if previous else "") + event["text"])
            return
        if kind == "login":
            self._on_login_event(event)
            return
        key = event["key"]
        if kind == "target":
            row = self._row_for_key.get(key)
            if row is None:
                row = self._new_row(key, event["label"], event["retry"])
            name = self.jobs_table.item(row, 0)
            name.setText(event["label"])
            name.setData(_RETRY_ROLE, event["retry"])
            return
        row = self._row_for_key.get(key)
        if row is None:
            return
        name = self.jobs_table.item(row, 0)
        state_item = self.jobs_table.item(row, 1)
        progress_item = self.jobs_table.item(row, 2)
        detail_item = self.jobs_table.item(row, 3)
        if kind == "plan":
            name.setText(event["title"])
            name.setData(_OUTPUT_ROLE, event["output"])
            detail = event["selection"]
            if event["warnings"]:
                detail += "；" + "；".join(event["warnings"])
            detail_item.setText(f"{detail} → {event['output']}")
            detail_item.setToolTip(detail_item.text())
        elif kind == "progress":
            parts = []
            current = total = 0
            known = True
            for stream in ("video", "audio"):
                if stream not in event["streams"]:
                    known = False
                    continue
                done, expected = event["streams"][stream]
                current += done
                if expected:
                    total += expected
                    parts.append(f"{stream} {done * 100 // expected}%")
                else:
                    known = False
                    parts.append(f"{stream} {_display_size(done)}")
            progress_item.setText(" · ".join(parts))
            if known and total:
                self.progress_bar.setRange(0, 100)
                self.progress_bar.setValue(min(99, current * 100 // total))
                self.progress_bar.setFormat("%p%")
            else:
                self.progress_bar.setRange(0, 0)
                self.progress_bar.setFormat("下载中…")
        elif kind == "stage":
            stage = event["stage"]
            name.setData(_STATE_ROLE, stage)
            state_item.setText(_STAGES.get(stage, stage))
            self.statusBar().showMessage(f"{name.text()}：{state_item.text()}")
            self.progress_bar.setRange(0, 0)
            self.progress_bar.setFormat(f"{_STAGES.get(stage, stage)}…")
        elif kind == "state":
            state = event["state"]
            name.setData(_STATE_ROLE, state)
            state_item.setText(_STATES.get(state, state))
            if "output" in event:
                name.setData(_OUTPUT_ROLE, event["output"])
            if event.get("detail"):
                detail = event["detail"]
                if state in ("completed", "skipped") and event.get("output"):
                    detail = f"{detail} → {event['output']}"
                detail_item.setText(detail)
                detail_item.setToolTip(detail)
            if state in ("completed", "skipped"):
                self.progress_bar.setRange(0, 100)
                self.progress_bar.setValue(100)
                self.progress_bar.setFormat("完成" if state == "completed" else "已跳过")
            self.statusBar().showMessage(f"{name.text()}：{state_item.text()}")

    def _on_login_event(self, event: dict[str, Any]) -> None:
        if self._qr_status is None:
            return
        state = event["state"]
        if state == "qr_ready":
            raw = event.get("image")
            pixmap = QPixmap()
            if not raw or not pixmap.loadFromData(raw):
                self._qr_status.setText("二维码图片无法读取，请取消后重试")
                return
            if self._qr_label is not None:
                self._qr_label.setPixmap(
                    pixmap.scaled(
                        240,
                        240,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
            self._qr_status.setText("请使用哔哩哔哩手机 App 扫码")
        elif state == "scanned":
            self._qr_status.setText("已扫码，请在手机上确认登录")
        elif state == "expired":
            self._qr_status.setText("二维码已过期，请取消后重新扫码")
        elif state == "success":
            self._qr_status.setText("登录成功")

    def _on_done(self, result: dict[str, Any]) -> None:
        kind = self._active_kind
        state = result["state"]
        if kind in ("download", "plan"):
            if state == "canceled":
                self._mark_unfinished("canceled", "操作已取消，可重试")
                self.progress_bar.setRange(0, 100)
                self.progress_bar.setValue(0)
                self.progress_bar.setFormat("已取消")
                self.statusBar().showMessage("操作已取消")
            elif state == "ok":
                counts = result["value"]
                self.progress_bar.setRange(0, 100)
                self.progress_bar.setValue(100)
                self.progress_bar.setFormat("批量处理完成")
                self.statusBar().showMessage(
                    f"完成 {counts['completed']} · 跳过 {counts['skipped']} · "
                    f"失败 {counts['failed']} · 计划 {counts['planned']}"
                )
            else:
                self._mark_unfinished("failed", result.get("message", "操作失败，可重试"))
                self.progress_bar.setRange(0, 100)
                self.progress_bar.setValue(0)
                self.progress_bar.setFormat("操作失败")
                self.statusBar().showMessage("操作失败")
        elif kind == "status" and state == "ok":
            info = result["value"]
            if not info.get("logged_in"):
                self.account_label.setText(
                    "登录已失效，请重新扫码" if info.get("expired") else "未登录"
                )
            else:
                membership = "年度大会员" if info.get("vip_type") == 2 else "大会员"
                if not info.get("vip"):
                    membership = "普通账号"
                self.account_label.setText(
                    f"已登录：{info.get('name', '')} · UID {info.get('uid', '')} · "
                    f"等级 {info.get('level', '')} · {membership}"
                )
        elif kind == "login":
            if state == "ok":
                self.account_label.setText("登录成功，凭据已保存。可点击“查询状态”查看账号。")
            if self._qr_dialog is not None:
                if state == "ok":
                    self._qr_dialog.accept()
                else:
                    self._qr_dialog.reject()
                self._qr_dialog = None
                self._qr_label = None
                self._qr_status = None
        elif kind == "doctor":
            self.doctor_text.setPlainText(
                result["value"] if state == "ok" else result.get("message", "已取消")
            )
        elif kind == "info" and state == "ok":
            summary = result["value"]
            self.statusBar().showMessage(
                f"信息读取完成：{summary['total'] - summary['failed']} 成功 · "
                f"{summary['failed']} 失败"
            )
        elif kind == "status" and state == "error":
            self.account_label.setText("账号状态查询失败，请检查网络后重试。")
        elif kind == "status" and state == "canceled":
            self.account_label.setText("账号状态查询已取消。")
        if state == "error":
            if not self._close_pending:
                self._error(result["message"])
        elif state == "canceled":
            self.statusBar().showMessage("操作已取消", 5000)

    def _on_thread_finished(self) -> None:
        self._thread = None
        self._worker = None
        self._cancel = None
        self._active_kind = None
        self._set_busy(False)
        if self._close_pending:
            QTimer.singleShot(0, self.close)

    def _update_retry_button(self) -> None:
        failed = any(
            self.jobs_table.item(row, 0).data(_STATE_ROLE) in ("failed", "canceled")
            for row in range(self.jobs_table.rowCount())
        )
        self.retry_button.setEnabled(failed)

    def _mark_unfinished(self, state: str, detail: str) -> None:
        terminal = {"completed", "skipped", "failed", "canceled", "planned"}
        for row in range(self.jobs_table.rowCount()):
            name = self.jobs_table.item(row, 0)
            if name.data(_STATE_ROLE) in terminal:
                continue
            name.setData(_STATE_ROLE, state)
            self.jobs_table.item(row, 1).setText(_STATES[state])
            detail_item = self.jobs_table.item(row, 3)
            detail_item.setText(detail)
            detail_item.setToolTip(detail)

    def _error(self, message: str) -> None:
        QMessageBox.warning(self, "BiliX", message)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._thread is not None:
            self._close_pending = True
            self._cancel_active()
            event.ignore()
            return
        super().closeEvent(event)


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    smoke_test = arguments == ["--smoke-test"]
    if arguments and not smoke_test:
        _report_startup_error("用法：bilix-gui [--smoke-test]")
        return 2
    application = QApplication.instance() or QApplication([sys.argv[0]])
    application.setApplicationName("BiliX")
    window = MainWindow()
    if smoke_test:
        try:
            from io import BytesIO

            import qrcode
            from qrcode.image.pure import PyPNGImage

            executable = find_ffmpeg(load_settings().ffmpeg)
            if not executable.is_file():
                raise OSError("FFmpeg 程序不存在")
            FFmpeg(executable).version()
            qr_png = BytesIO()
            qrcode.make("bilix-smoke-test", image_factory=PyPNGImage).save(qr_png)
            if not QPixmap().loadFromData(qr_png.getvalue()):
                raise OSError("无法加载二维码 PNG 图片")
        except (BilixError, OSError) as error:
            _report_startup_error(f"BiliX GUI 自检失败：{error}")
            return 1
        if sys.stdout is not None:
            print(f"BiliX GUI {__version__} 自检通过")
        return 0
    window.show()
    return application.exec()


def _report_startup_error(message: str) -> None:
    if sys.stderr is not None:
        print(message, file=sys.stderr)
    elif sys.platform == "win32":
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, "BiliX", 0x10)
