"""Qt Widgets front end for the existing BiliX download engine."""

from __future__ import annotations

import json
import sys
from functools import partial
from pathlib import Path
from typing import Any

from platformdirs import user_downloads_path
from PySide6.QtCore import Qt, QThread, QTimer, QUrl
from PySide6.QtGui import QCloseEvent, QDesktopServices, QIcon, QInputMethodEvent, QPixmap
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
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from djhx_bilix import __version__, auth
from djhx_bilix.config import Settings, load_settings, save_settings
from djhx_bilix.credentials import normalize_cookie
from djhx_bilix.errors import BilixError, InputError
from djhx_bilix.media import FFmpeg, find_ffmpeg
from djhx_bilix.models import QUALITY_NAMES
from djhx_bilix.operations import CancellationToken
from djhx_bilix.planner import parse_quality
from djhx_bilix.tasks import TERMINAL, Session, summary_text
from djhx_bilix.urls import load_urls, normalize_url, parse_pages, url_page

from .worker import (
    DownloadOptions,
    JobSpec,
    OperationWorker,
    run_doctor,
    run_download,
    run_info,
    run_login,
    run_session,
    run_status,
)

_RETRY_ROLE = Qt.ItemDataRole.UserRole
_OUTPUT_ROLE = Qt.ItemDataRole.UserRole + 1
_STATE_ROLE = Qt.ItemDataRole.UserRole + 2
_TASK_ROLE = Qt.ItemDataRole.UserRole + 3

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


class UrlInput(QPlainTextEdit):
    """Keep the URL hint from overlapping a native IME composition."""

    hint = "粘贴 Bilibili 视频、番剧链接或 BV 号，每行一个"

    def __init__(self) -> None:
        super().__init__()
        self.setPlaceholderText(self.hint)
        self.setTabChangesFocus(True)

    def inputMethodEvent(self, event: QInputMethodEvent) -> None:
        self.setPlaceholderText("" if event.preeditString() else self.hint)
        super().inputMethodEvent(event)


class MainWindow(QMainWindow):
    """One active background operation; downloads form a serial, visible queue."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"BiliX {__version__}")
        available = self.screen().availableGeometry()
        width = max(320, available.width() - 16)
        # Wayland may report the whole output as available, including the
        # compositor panel and client-side window decoration.
        margin = 80 if QApplication.platformName() == "wayland" else 48
        height = max(240, available.height() - margin)
        self.setMinimumSize(min(760, width), min(590, height))
        self.resize(min(940, width), min(760, height))
        self._settings: Settings | None = None
        self._thread: QThread | None = None
        self._worker: OperationWorker | None = None
        self._cancel: CancellationToken | None = None
        self._active_kind: str | None = None
        self._close_pending = False
        self._qr_dialog: QDialog | None = None
        self._qr_label: QLabel | None = None
        self._qr_status: QLabel | None = None
        self._busy_buttons: list[QPushButton] = []
        self.session = Session()
        self._row_for_task: dict[str, int] = {}
        self._source_items: dict[str, QTreeWidgetItem] = {}
        self._event_versions: dict[str, tuple[str, int]] = {}
        self._metadata: dict[int, dict] = {}
        self._input_generation = 0
        self._info_generation = 0
        self._output_edited = False

        tabs = QTabWidget(self)
        self.setCentralWidget(tabs)
        tabs.addTab(self._make_download_tab(), "下载")
        tabs.addTab(self._make_account_tab(), "账号")
        tabs.addTab(self._make_settings_tab(), "设置")
        tabs.addTab(self._make_doctor_tab(), "诊断")
        self.statusBar().showMessage("就绪")
        self._load_settings_view()
        self._offline_account()
        self.urls_edit.textChanged.connect(self._invalidate_info)
        self.page_edit.textChanged.connect(self._reset_part_checks)
        self.output_edit.textEdited.connect(lambda _text: setattr(self, "_output_edited", True))

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
        self.urls_edit = UrlInput()
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

        self.quality_combo = QComboBox()
        self.quality_combo.addItem("自动 / 当前可获取的最高画质", None)
        for quality in sorted(QUALITY_NAMES, reverse=True):
            self.quality_combo.addItem(f"{QUALITY_NAMES[quality]} ({quality})", quality)
        options.addRow("画质", self.quality_combo)
        layout.addWidget(options_group)

        self.advanced_toggle = QCheckBox("高级选项")
        layout.addWidget(self.advanced_toggle)
        self.advanced_group = QWidget()
        advanced = QFormLayout(self.advanced_group)
        self.codec_combo = QComboBox()
        for label, value in (("自动", None), ("AVC", "AVC"), ("HEVC", "HEVC"), ("AV1", "AV1")):
            self.codec_combo.addItem(label, value)
        advanced.addRow("编码", self.codec_combo)
        self.audio_combo = QComboBox()
        for label, value in (
            ("AAC", "aac"),
            ("FLAC", "flac"),
            ("Dolby", "dolby"),
            ("最佳", "best"),
        ):
            self.audio_combo.addItem(label, value)
        advanced.addRow("音轨", self.audio_combo)
        self.page_edit = QLineEdit()
        self.page_edit.setPlaceholderText("留空遵循链接 ?p=；all 为全部；也可填 1,3,5-7")
        advanced.addRow("批量选集规则", self.page_edit)
        self.strict_check = QCheckBox("必须精确匹配画质 / 编码")
        self.overwrite_check = QCheckBox("校验成功后覆盖同名文件")
        advanced.addRow(self.strict_check)
        advanced.addRow(self.overwrite_check)
        layout.addWidget(self.advanced_group)
        self.advanced_group.hide()
        self.advanced_toggle.toggled.connect(self.advanced_group.setVisible)
        self.option_summary = QLabel()
        self.option_summary.setWordWrap(True)
        layout.addWidget(self.option_summary)
        for combo in (self.quality_combo, self.codec_combo, self.audio_combo):
            combo.currentIndexChanged.connect(self._update_option_summary)
        for check in (self.strict_check, self.overwrite_check):
            check.toggled.connect(self._update_option_summary)
        self.output_edit.textChanged.connect(self._update_option_summary)
        self.page_edit.textChanged.connect(self._update_option_summary)

        actions = QHBoxLayout()
        self.start_button = self._button("开始下载", self._start_download)
        self.plan_button = self._button("预览计划", lambda: self._start_download(True))
        self.retry_button = self._button("重试全部失败", self._retry_failed)
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

        history_actions = QHBoxLayout()
        history_actions.addWidget(self._button("重试选中（原参数）", self._retry_selected))
        history_actions.addWidget(
            self._button("重试选中（当前参数）", lambda: self._retry_selected(True))
        )
        history_actions.addWidget(
            self._button("重试全部取消", lambda: self._retry_matching("canceled"))
        )
        history_actions.addStretch()
        layout.addLayout(history_actions)
        self.history_tabs = QTabWidget()
        self.metadata_tree = QTreeWidget()
        self.metadata_tree.setHeaderLabels(["来源 / 可选选集", "时长 / 当前可获取媒体"])
        self.metadata_tree.setMinimumHeight(120)
        self.metadata_tree.currentItemChanged.connect(self._show_metadata)
        self.history_tabs.addTab(self.metadata_tree, "信息与选集")
        self.source_tree = QTreeWidget()
        self.source_tree.setHeaderLabels(["批次 / 来源", "读取状态", "说明"])
        self.source_tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self.history_tabs.addTab(self.source_tree, "来源记录")
        self.source_tree.currentItemChanged.connect(self._show_source)
        task_page = QWidget()
        task_layout = QVBoxLayout(task_page)
        self.filter_combo = QComboBox()
        for label, value in (
            ("全部任务", "all"),
            ("排队", "queued"),
            ("处理中", "active"),
            ("完成 / 跳过", "success"),
            ("失败", "failed"),
            ("取消", "canceled"),
        ):
            self.filter_combo.addItem(label, value)
        self.filter_combo.currentIndexChanged.connect(self._filter_tasks)
        task_layout.addWidget(self.filter_combo)
        self.batch_combo = QComboBox()
        self.batch_combo.addItem("已结束批次汇总", None)
        self.batch_combo.currentIndexChanged.connect(self._show_batch)
        task_layout.addWidget(self.batch_combo)
        self.jobs_table = QTableWidget(0, 4)
        self.jobs_table.setHorizontalHeaderLabels(["视频 / 选集", "状态", "进度", "文件 / 说明"])
        self.jobs_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.jobs_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.jobs_table.verticalHeader().setVisible(False)
        header = self.jobs_table.horizontalHeader()
        # Measure visible rows; rescanning the entire queue on each progress
        # update makes native tables stall when thousands of items change.
        header.setResizeContentsPrecision(0)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.jobs_table.doubleClicked.connect(self._open_selected_folder)
        task_layout.addWidget(self.jobs_table)
        self.jobs_table.setMinimumHeight(140)
        self.jobs_table.itemSelectionChanged.connect(self._show_attempts)
        self.history_tabs.addTab(task_page, "会话任务")
        self.history_tabs.setMinimumHeight(220)
        layout.addWidget(self.history_tabs, 4)

        progress_row = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("等待任务")
        progress_row.addWidget(self.progress_bar, 1)
        progress_row.addWidget(self._button("打开输出目录", self._open_selected_folder))
        layout.addLayout(progress_row)

        record_actions = QHBoxLayout()
        record_actions.addWidget(self._button("打开文件", self._open_selected_file, False))
        record_actions.addWidget(self._button("复制路径", self._copy_selected_path, False))
        record_actions.addWidget(
            self._button(
                "清理成功记录", lambda: self._clear_records(frozenset({"completed", "skipped"}))
            )
        )
        record_actions.addWidget(
            self._button(
                "清理失败 / 取消", lambda: self._clear_records(frozenset({"failed", "canceled"}))
            )
        )
        layout.addLayout(record_actions)
        info_group = QGroupBox("信息 / 尝试详情 / 冲突预览")
        info_layout = QVBoxLayout(info_group)
        self.info_text = QPlainTextEdit()
        self.info_text.setReadOnly(True)
        self.info_text.setMaximumHeight(145)
        info_layout.addWidget(self.info_text)
        info_layout.addWidget(self._button("复制选中来源 JSON", self._copy_metadata, False))
        layout.addWidget(info_group, 1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)
        return scroll

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
        self.default_output_edit.setText(
            str(settings.file_download_dir or user_downloads_path() / "djhx-bilix")
        )
        if not self._output_edited:
            self.output_edit.setText(str(settings.download_dir))
        self.ffmpeg_edit.setText(settings.file_ffmpeg or "")
        self.config_path_label.setText(str(settings.config_file))
        self.settings_hint.setText(
            f"生效下载目录：{settings.download_dir}（{settings.download_source}）\n"
            f"生效 FFmpeg：{settings.ffmpeg or '自动查找'}（{settings.ffmpeg_source}）。\n"
            "上方编辑文件值；环境变量优先。路径能否运行请使用诊断检查。"
        )

    def _save_settings(self) -> None:
        if self._settings is None:
            self._error("请先修正配置文件并重新打开程序")
            return
        if not self.default_output_edit.text().strip():
            self._error("请填写默认下载目录")
            return
        try:
            save_settings(
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
        self._load_settings_view()
        self.statusBar().showMessage("设置已保存，与 CLI 共用", 5000)

    def _choose_output(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "选择保存目录", self.output_edit.text())
        if directory:
            self._output_edited = True
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
        specs = []
        for index, (_line_number, value) in enumerate(values):
            selected = page
            if validate_page and index in self._metadata:
                root = self.metadata_tree.topLevelItem(index)
                parts = [
                    str(root.child(j).data(0, Qt.ItemDataRole.UserRole))
                    for j in range(root.childCount())
                    if root.child(j).checkState(0) == Qt.CheckState.Checked
                ]
                if not parts:
                    raise InputError(f"第 {index + 1} 个来源未勾选任何选集")
                selected = ",".join(parts)
            specs.append(JobSpec(value, selected))
        return tuple(specs)

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
            ffmpeg=load_settings().ffmpeg,
            dry_run=dry_run,
        )

    def _update_option_summary(self, *_args) -> None:
        self.option_summary.setText(
            f"画质 {self.quality_combo.currentText()} · 编码 {self.codec_combo.currentText()} · "
            f"音轨 {self.audio_combo.currentText()} · "
            f"严格 {'开' if self.strict_check.isChecked() else '关'} · "
            f"覆盖 {'开' if self.overwrite_check.isChecked() else '关'} · "
            f"选集 {self.page_edit.text() or '按来源勾选 / 链接默认'}"
        )

    def _invalidate_info(self) -> None:
        self._input_generation += 1
        self._metadata.clear()
        self.metadata_tree.clear()

    def _offline_account(self) -> None:
        if self._settings is None:
            self.account_label.setText("配置不可读，无法检查本地凭据")
            return
        path = self._settings.token_file
        try:
            if not path.exists():
                text = "本地未保存凭据，可扫码登录"
            else:
                normalize_cookie(path.read_text(encoding="utf-8"), require_session=True)
                text = "本地凭据已保存，尚未验证有效性；请查询状态"
        except (BilixError, OSError, UnicodeError):
            text = "本地凭据无法读取或格式错误，请重新扫码"
        self.account_label.setText(text)

    def _reset_part_checks(self) -> None:
        for index, metadata in self._metadata.items():
            root = self.metadata_tree.topLevelItem(index)
            if root is None:
                continue
            try:
                raw = self.page_edit.text().strip() or None
                selected = parse_pages(raw)
                if raw is None:
                    part = url_page(metadata["url"])
                    selected = (part,) if part else None
            except BilixError:
                continue
            for j in range(root.childCount()):
                child = root.child(j)
                number = child.data(0, Qt.ItemDataRole.UserRole)
                child.setCheckState(
                    0,
                    Qt.CheckState.Checked
                    if selected is None or number in selected
                    else Qt.CheckState.Unchecked,
                )

    def _show_metadata(self, item=None, *_args) -> None:
        if item is None:
            return
        root = item.parent() or item
        index = self.metadata_tree.indexOfTopLevelItem(root)
        value = self._metadata.get(index)
        if value:
            media = (
                ", ".join(f"{v['name']} {v['codec']}" for v in value["available_streams"])
                or "未知 / 不可获取"
            )
            audio = (
                ", ".join(v["kind"].upper() for v in value["available_audio"]) or "未知 / 不可获取"
            )
            self.info_text.setPlainText(
                f"{value['title']}\n作者：{value['owner']} · 时长 {value['duration']:.0f} 秒 · "
                f"BV {value['bvid'] or '无'} · CID {value['cid']} · "
                f"EP {value['episode_id'] or '无'}\n"
                f"当前读取选集媒体：{media} / {audio}\n"
                f"试看：{'是' if value['is_preview'] else '否'} · "
                f"DRM：{'是' if value['is_drm'] else '否'}\n"
                f"其他选集的权限及媒体在执行 / 预览时分别读取。\n{value['description']}"
            )

    def _copy_metadata(self) -> None:
        item = self.metadata_tree.currentItem()
        if item:
            index = self.metadata_tree.indexOfTopLevelItem(item.parent() or item)
            if index in self._metadata:
                QApplication.clipboard().setText(
                    json.dumps(self._metadata[index], ensure_ascii=False, indent=2)
                )

    def _show_source(self, item=None, *_args) -> None:
        if item:
            request = self.session.requests.get(item.data(0, Qt.ItemDataRole.UserRole))
            if request:
                self.info_text.setPlainText(
                    f"来源 {request.spec.source} · 选集 {request.spec.page or '链接默认'}\n"
                    f"{request.options.description()}\n{request.detail}\n{request.action}\n"
                    f"来源 ID {request.request_id} · 原来源 {request.origin_request_id or '无'}"
                )

    def _selected_ids(self) -> tuple[tuple[str, ...], tuple[str, ...]]:
        tasks = (
            tuple(
                self.jobs_table.item(row.row(), 0).data(_TASK_ROLE)
                for row in self.jobs_table.selectionModel().selectedRows()
                if not self.jobs_table.isRowHidden(row.row())
            )
            if self.history_tabs.currentIndex() == 2
            else ()
        )
        sources = (
            tuple(i.data(0, Qt.ItemDataRole.UserRole) for i in self.source_tree.selectedItems())
            if self.history_tabs.currentIndex() == 1
            else ()
        )
        return tasks, sources

    def _start_download(
        self, dry_run: bool = False, specs: tuple[JobSpec, ...] | None = None
    ) -> None:
        if self._thread is not None:
            return
        try:
            selected = specs if specs is not None else self._inputs()
            options = self._options(dry_run)
            if dry_run:
                self.info_text.setPlainText("冲突预览为读取时刻快照；执行和提交时会重新检查。")
                self._start_operation("plan", partial(run_download, selected, options))
                return
            batch_id = self.session.begin(selected, options)
        except BilixError as error:
            self._error(str(error))
            return
        self._start_batch(batch_id)

    def _start_batch(self, batch_id: str) -> None:
        self.history_tabs.setCurrentIndex(2)
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setFormat("准备批次…")
        self._start_operation("download", partial(run_session, self.session, batch_id))

    def _retry_failed(self) -> None:
        self._retry_matching("failed")

    def _retry_matching(self, state: str) -> None:
        tasks = tuple(i for i, t in self.session.tasks.items() if t.latest.state == state)
        sources = tuple(
            i
            for i, r in self.session.requests.items()
            if r.state == state
            and not any(n.origin_request_id == i for n in self.session.requests.values())
        )
        self._retry_ids(tasks, sources)

    def _retry_selected(self, current: bool = False) -> None:
        tasks, sources = self._selected_ids()
        self._retry_ids(tasks, sources, current)

    def _retry_ids(self, tasks, sources, current: bool = False) -> None:
        if self._thread is not None:
            return
        try:
            options = self._options(False) if current else None
            if (
                options is not None
                and QMessageBox.question(
                    self,
                    "确认重试参数",
                    f"{len(tasks)} 项任务 / {len(sources)} 个来源将使用当前参数：\n"
                    f"{options.description()}",
                )
                != QMessageBox.StandardButton.Yes
            ):
                return
            batch_id = self.session.retry(tasks, sources, options)
        except BilixError as error:
            self._error(str(error))
            return
        self._start_batch(batch_id)

    def _filter_tasks(self) -> None:
        selected = self.filter_combo.currentData()
        for task_id, row in self._row_for_task.items():
            state = self.jobs_table.item(row, 0).data(_STATE_ROLE)
            visible = (
                selected == "all"
                or selected == state
                or selected == "success"
                and state in {"completed", "skipped"}
                or selected == "active"
                and state not in TERMINAL
                and state != "queued"
            )
            self.jobs_table.setRowHidden(row, not visible)

    def _show_attempts(self) -> None:
        row = self.jobs_table.currentRow()
        if row < 0:
            return
        task = self.session.tasks.get(self.jobs_table.item(row, 0).data(_TASK_ROLE))
        if task:
            self.info_text.setPlainText(
                "\n\n".join(
                    f"尝试 {a.number} · {_STATES.get(a.state, a.state)} · 批次 {a.batch_id}\n"
                    f"{a.options.description()}\n实际 FFmpeg {a.resolved_ffmpeg or '未调用'}\n"
                    f"{a.detail}\n类别 {a.error_code or '无'} · {a.action}\n"
                    f"计划路径 {a.planned_output or '尚未生成'}\n实际输出 {a.output or '无'}"
                    for a in task.attempts
                )
            )

    def _show_batch(self) -> None:
        batch_id = self.batch_combo.currentData()
        batch = self.session.batches.get(batch_id)
        if batch and batch.finished:
            self.info_text.setPlainText(f"批次 {batch_id}\n" + summary_text(dict(batch.summary)))

    def _clear_records(self, states: frozenset[str]) -> None:
        if self._thread is not None:
            return
        self.session.clear(states)
        for row in reversed(range(self.jobs_table.rowCount())):
            if self.jobs_table.item(row, 0).data(_STATE_ROLE) in states:
                self.jobs_table.removeRow(row)
        self._row_for_task = {
            self.jobs_table.item(row, 0).data(_TASK_ROLE): row
            for row in range(self.jobs_table.rowCount())
        }
        for request_id, item in tuple(self._source_items.items()):
            if (
                request_id not in self.session.requests
                or self.session.requests[request_id].state in states
            ):
                self.source_tree.takeTopLevelItem(self.source_tree.indexOfTopLevelItem(item))
                del self._source_items[request_id]
        self._update_retry_button()

    def _open_selected_file(self) -> None:
        row = self.jobs_table.currentRow()
        if row < 0:
            return
        name = self.jobs_table.item(row, 0)
        output = name.data(_OUTPUT_ROLE)
        if (
            name.data(_STATE_ROLE) not in {"completed", "skipped"}
            or not output
            or not Path(output).is_file()
        ):
            self._error("尚无可打开的输出文件，或文件已被移动 / 删除")
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(output)):
            self._error("无法打开输出文件，请检查桌面关联程序")

    def _copy_selected_path(self) -> None:
        row = self.jobs_table.currentRow()
        if row >= 0:
            name = self.jobs_table.item(row, 0)
            output = name.data(_OUTPUT_ROLE)
            if (
                output
                and Path(output).is_file()
                and name.data(_STATE_ROLE) in {"completed", "skipped"}
            ):
                QApplication.clipboard().setText(output)
            else:
                self._error("尚无输出文件，或文件已被移动 / 删除")

    def _start_info(self) -> None:
        if self._thread is not None:
            return
        try:
            specs = self._inputs(validate_page=False)
        except BilixError as error:
            self._error(str(error))
            return
        self._metadata.clear()
        self.metadata_tree.clear()
        self._info_generation = self._input_generation
        for spec in specs:
            self.metadata_tree.addTopLevelItem(QTreeWidgetItem([spec.source, "等待读取"]))
        self.history_tabs.setCurrentIndex(0)
        self.info_text.setPlainText("逐个读取来源；其他选集的权限需分别检查。")
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
        self._invalidate_info()

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
        labels = {
            "download": "取消整个批次",
            "plan": "取消预览",
            "info": "取消信息读取",
            "login": "取消登录",
            "status": "取消状态查询",
            "doctor": "取消诊断",
        }
        self.cancel_button.setText(labels.get(self._active_kind, "取消当前操作"))
        for widget in (
            self.urls_edit,
            self.output_edit,
            self.page_edit,
            self.quality_combo,
            self.codec_combo,
            self.audio_combo,
            self.strict_check,
            self.overwrite_check,
            self.metadata_tree,
        ):
            widget.setEnabled(not busy)
        if not busy:
            self._update_retry_button()

    def _cancel_active(self) -> None:
        if self._cancel is not None:
            self._cancel.cancel()
            self.cancel_button.setEnabled(False)
            self.statusBar().showMessage("正在取消，请等待当前请求或媒体处理停止…")

    def _on_event(self, event: dict[str, Any]) -> None:
        kind = event["type"]
        if kind == "login":
            self._on_login_event(event)
            return
        if kind == "info":
            if self._info_generation != self._input_generation:
                return
            index = event["index"]
            root = self.metadata_tree.topLevelItem(index)
            if root is None:
                return
            if event.get("error"):
                root.setText(1, f"读取失败：{event['error']}；可再次查看信息")
                return
            data = event["metadata"]
            self._metadata[index] = data
            root.setText(0, data["title"])
            root.setText(1, f"已读取 · {len(data['pages']) or 1} 个选集")
            pages = data["pages"] or [
                dict(number=1, title=data["title"], duration=data["duration"])
            ]
            for page in pages:
                child = QTreeWidgetItem(
                    [
                        f"P{page['number']} {page['title']}",
                        f"{page['duration']:.0f} 秒 · 媒体待检查",
                    ]
                )
                child.setData(0, Qt.ItemDataRole.UserRole, page["number"])
                child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                child.setCheckState(0, Qt.CheckState.Checked)
                root.addChild(child)
            root.setExpanded(True)
            self._reset_part_checks()
            self.metadata_tree.setCurrentItem(root)
            return
        if kind == "preview":
            labels = {
                "new": "新建",
                "skip": "跳过（已存在，未校验）",
                "replace": "替换",
                "blocked": "阻塞",
            }
            detail = (
                f"[{event['source_index'] + 1}] {event.get('title', '')} "
                f"{event.get('label', '')} · {labels[event['conflict']]}\n"
            )
            detail += f"{event.get('selection', '')} → {event.get('output', '无计划路径')}\n"
            detail += "；".join(event.get("warnings", ()))
            if event.get("duplicate"):
                detail += "；本批次输出路径重复，将逐项重新检查"
            detail += event.get("detail", "") + " " + event.get("action", "")
            self.info_text.appendPlainText(detail)
            return
        if kind == "source":
            source = event["request"]
            item = self._source_items.get(source.request_id)
            if item is None:
                item = QTreeWidgetItem([f"{source.batch_id[:8]} · {source.spec.source}", "", ""])
                item.setData(0, Qt.ItemDataRole.UserRole, source.request_id)
                self.source_tree.addTopLevelItem(item)
                self._source_items[source.request_id] = item
            item.setText(
                1,
                {
                    "discovered": "已发现选集",
                    "loading": "读取中",
                    "failed": "失败",
                    "canceled": "取消",
                    "queued": "等待",
                }.get(source.state, source.state),
            )
            item.setText(2, f"{source.detail} {source.action}")
            return
        if "task" not in event:
            return
        task, attempt = event["task"], event["attempt"]
        stored = self.session.tasks.get(task.task_id)
        if stored is None or attempt.number > len(stored.attempts):
            return
        known = stored.attempts[attempt.number - 1]
        if known.attempt_id != attempt.attempt_id or attempt.sequence > known.sequence:
            return
        # Queued Qt signals may outlive an earlier attempt or preview. Ignore them.
        previous = self._event_versions.get(task.task_id)
        if previous and (previous[0] == attempt.attempt_id and attempt.sequence <= previous[1]):
            return
        row = self._row_for_task.get(task.task_id)
        if previous and previous[0] != attempt.attempt_id and row is not None:
            shown_number = self.jobs_table.item(row, 0).data(Qt.ItemDataRole.UserRole + 4)
            if shown_number is not None and attempt.number < shown_number:
                return
        self._event_versions[task.task_id] = (attempt.attempt_id, attempt.sequence)
        if row is None:
            row = self.jobs_table.rowCount()
            self.jobs_table.insertRow(row)
            for col in range(4):
                self.jobs_table.setItem(row, col, QTableWidgetItem(""))
            self._row_for_task[task.task_id] = row
        name = self.jobs_table.item(row, 0)
        name.setText(
            f"{event.get('title', task.label)} · P{task.spec.page} · 尝试 {attempt.number}"
        )
        name.setData(_TASK_ROLE, task.task_id)
        name.setData(Qt.ItemDataRole.UserRole + 4, attempt.number)
        name.setData(_STATE_ROLE, attempt.state)
        name.setData(_OUTPUT_ROLE, attempt.output)
        self.jobs_table.item(row, 1).setText(_STATES.get(attempt.state, attempt.state))
        detail = attempt.detail + ("；" + attempt.action if attempt.action else "")
        if kind == "plan":
            decision = {
                "new": "新建",
                "skip": "跳过（未校验）",
                "replace": "替换",
                "blocked": "阻塞",
            }[event["conflict"]]
            detail = f"{event['selection']} · {decision} → {attempt.planned_output}"
            if event.get("warnings"):
                detail += "；" + "；".join(event["warnings"])
            if event.get("duplicate"):
                detail += "；本批次输出路径重复"
        if attempt.output:
            detail += f" → {attempt.output}"
        if detail:
            self.jobs_table.item(row, 3).setText(detail)
            self.jobs_table.item(row, 3).setToolTip(detail)
        if kind == "progress":
            current = total = 0
            known = len(event["streams"]) == 2
            parts = []
            for stream, (done, expected) in event["streams"].items():
                current += done
                if expected:
                    total += expected
                    parts.append(f"{stream} {min(100, done * 100 // expected)}%")
                else:
                    known = False
                    parts.append(f"{stream} {_display_size(done)}")
            self.jobs_table.item(row, 2).setText(" · ".join(parts))
            self.progress_bar.setRange(0, 100 if known and total else 0)
            self.progress_bar.setValue(min(99, current * 100 // total) if known and total else 0)
            self.progress_bar.setFormat("%p%" if known and total else "下载中…")
        elif attempt.state not in TERMINAL:
            self.progress_bar.setRange(0, 0)
            self.progress_bar.setFormat(f"{_STATES[attempt.state]}…")
        else:
            self.jobs_table.item(row, 2).setText("")
        selected = self.filter_combo.currentData()
        visible = (
            selected == "all"
            or selected == attempt.state
            or selected == "success"
            and attempt.state in {"completed", "skipped"}
            or selected == "active"
            and attempt.state not in TERMINAL
            and attempt.state != "queued"
        )
        self.jobs_table.setRowHidden(row, not visible)

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
            if state == "ok":
                counts = result["value"]
                self.progress_bar.setRange(0, 100)
                self.progress_bar.setValue(
                    0 if counts["canceled"] or counts["source_canceled"] else 100
                )
                summary = summary_text(counts)
                self.progress_bar.setFormat("批次已结束")
                self.statusBar().showMessage(summary)
                self.info_text.appendPlainText(summary)
                for batch_id, batch in self.session.batches.items():
                    if batch.finished and self.batch_combo.findData(batch_id) < 0:
                        self.batch_combo.addItem(f"批次 {batch_id[:8]}", batch_id)
            else:
                self.progress_bar.setRange(0, 100)
                self.progress_bar.setValue(0)
                self.progress_bar.setFormat("已取消" if state == "canceled" else "操作失败")
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
                self._invalidate_info()
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
        self.retry_button.setEnabled(
            any(t.latest.state == "failed" for t in self.session.tasks.values())
            or any(
                r.state == "failed"
                and not any(n.origin_request_id == i for n in self.session.requests.values())
                for i, r in self.session.requests.items()
            )
        )

    def _error(self, message: str) -> None:
        QMessageBox.warning(self, "BiliX", message)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._thread is not None:
            if not self._close_pending:
                answer = QMessageBox.question(
                    self,
                    "操作进行中",
                    "停止当前操作并退出？未提交任务将取消，会话记录在退出后清除。",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    event.ignore()
                    return
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
    application.setDesktopFileName("djhx-bilix-gui")
    icon = QIcon()
    assets = Path(__file__).resolve().parents[1] / "assets"
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addFile(str(assets / f"bilix-{size}.png"))
    application.setWindowIcon(icon)
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
            if icon.isNull() or icon.pixmap(32, 32).isNull():
                raise OSError("无法加载应用图标")
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
