"""Compact widgets and on-demand dialogs; business actions stay in MainWindow."""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QTabWidget,
    QToolButton,
    QTreeView,
    QTreeWidget,
    QVBoxLayout,
    QWidget,
)

from djhx_bilix.models import QUALITY_NAMES

from .history import HistoryFilter, HistoryModel


def duration(value):
    if not value or value < 0:
        return "未知"
    seconds = int(value)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    return f"{hours}:{minutes:02}:{seconds:02}" if hours else f"{minutes}:{seconds:02}"


class ElidedLabel(QLabel):
    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self.full_text = text
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setText(text)

    def setText(self, text):
        self.full_text = text
        self.setToolTip(text)
        super().setText(
            self.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, max(1, self.width()))
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.setText(self.full_text)


class CompactUi:
    def _dialog(self, title, width=640, height=460):
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        geometry = self.screen().availableGeometry()
        dialog.resize(min(width, geometry.width() - 32), min(height, geometry.height() - 64))
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(16, 16, 16, 16)
        close = QPushButton("关闭")
        close.clicked.connect(dialog.reject)
        close.setAutoDefault(False)
        return dialog, layout, close

    def _build_ui(self, input_type):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)
        self.setCentralWidget(page)
        header = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(QIcon(str(Path(__file__).parents[1] / "assets/bilix-64.png")).pixmap(28, 28))
        header.addWidget(icon)
        brand = QLabel("BiliX")
        brand.setStyleSheet("font-size: 18px; font-weight: 600;")
        header.addWidget(brand)
        header.addStretch()
        self.account_button = QPushButton("未登录 ▾")
        self.account_button.setMaximumWidth(230)
        self.account_button.clicked.connect(lambda: self._open_settings(0))
        header.addWidget(self.account_button)
        header.addWidget(self._button("设置", lambda: self._open_settings(1), False))
        layout.addLayout(header)
        input_row = QHBoxLayout()
        input_row.addWidget(QLabel("视频链接 / BV 号"))
        input_row.addStretch()
        self.info_button = self._button("解析", self._start_info)
        input_row.addWidget(self.info_button)
        more = QToolButton()
        more.setText("更多")
        more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(more)
        self.import_action = menu.addAction("导入链接列表…", self._import_urls)
        more.setMenu(menu)
        input_row.addWidget(more)
        layout.addLayout(input_row)
        self.urls_edit = input_type()
        self.urls_edit.setObjectName("urlInput")
        self.urls_edit.setFixedHeight(64)
        layout.addWidget(self.urls_edit)
        self.parse_row = QWidget()
        parse_layout = QHBoxLayout(self.parse_row)
        parse_layout.setContentsMargins(0, 0, 0, 0)
        self.parse_summary = ElidedLabel()
        parse_layout.addWidget(self.parse_summary, 1)
        self.parts_button = self._button("选择选集", lambda: self._parts_dialog.show())
        parse_layout.addWidget(self.parts_button)
        layout.addWidget(self.parse_row)
        self.parse_row.hide()
        directory = QHBoxLayout()
        directory.addWidget(QLabel("保存到"))
        self.output_edit = QLineEdit()
        self.output_edit.setObjectName("outputDirectory")
        directory.addWidget(self.output_edit, 1)
        directory.addWidget(self._button("选择…", self._choose_output))
        layout.addLayout(directory)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("画质"))
        self.quality_combo = QComboBox()
        self.quality_combo.addItem("最高可用", None)
        for quality in sorted(QUALITY_NAMES, reverse=True):
            self.quality_combo.addItem(QUALITY_NAMES[quality], quality)
        controls.addWidget(self.quality_combo, 1)
        self.advanced_toggle = self._button("更多选项…", lambda: self._options_dialog.show())
        controls.addWidget(self.advanced_toggle)
        self.plan_button = self._button("文件预览", lambda: self._start_download(True))
        controls.addWidget(self.plan_button)
        self.start_button = self._button("下载", self._start_download)
        self.start_button.setObjectName("startDownload")
        self.start_button.setDefault(True)
        self.start_button.setStyleSheet(
            "QPushButton { background: #2859c5; color: white; padding: 5px 18px; "
            "border-radius: 5px; }"
            " QPushButton:disabled { background: #8694ab; }"
        )
        controls.addWidget(self.start_button)
        layout.addLayout(controls)
        self.option_summary = ElidedLabel()
        layout.addWidget(self.option_summary)
        self._build_options()
        self._build_parts()
        self._build_details()
        self._settings_dialog, settings_layout, close = self._dialog("BiliX 设置", 680, 520)
        self.settings_tabs = QTabWidget()
        self.settings_tabs.addTab(self._make_account_tab(), "账号")
        self.settings_tabs.addTab(self._make_settings_tab(), "下载设置")
        self.settings_tabs.addTab(self._make_doctor_tab(), "关于与诊断")
        settings_layout.addWidget(self.settings_tabs)
        settings_layout.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)
        self._preview_dialog, preview_layout, close = self._dialog("文件预览", 760, 520)
        preview_layout.addWidget(QLabel("预览是读取时刻的快照；执行和提交时会重新检查。"))
        self.preview_text = QPlainTextEdit()
        self.preview_text.setReadOnly(True)
        preview_layout.addWidget(self.preview_text)
        preview_layout.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)
        self._preview_dialog.rejected.connect(
            lambda: self._cancel_active() if self._active_kind == "plan" else None
        )
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("下载列表"))
        self.filter_combo = QComboBox()
        for text, value in (
            ("全部", "all"),
            ("等待", "queued"),
            ("处理中", "active"),
            ("完成 / 跳过", "success"),
            ("失败", "failed"),
            ("取消", "canceled"),
        ):
            self.filter_combo.addItem(text, value)
        self.filter_combo.currentIndexChanged.connect(self._filter_tasks)
        toolbar.addWidget(self.filter_combo)
        toolbar.addStretch()
        self.selection_button = QPushButton("选中项 ▾")
        self.selection_menu = QMenu(self.selection_button)
        self.open_action = self.selection_menu.addAction("打开文件", self._open_selected_file)
        self.folder_action = self.selection_menu.addAction(
            "打开所在目录", self._open_selected_folder
        )
        self.copy_action = self.selection_menu.addAction("复制路径", self._copy_selected_path)
        self.selection_menu.addSeparator()
        self.retry_selected_action = self.selection_menu.addAction(
            "重试 / 重新读取（原参数）", self._retry_selected
        )
        self.retry_current_action = self.selection_menu.addAction(
            "按当前参数重试…", lambda: self._retry_selected(True)
        )
        self.selection_menu.addSeparator()
        self.details_action = self.selection_menu.addAction("详情…", self._open_details)
        self.selection_button.setMenu(self.selection_menu)
        self.selection_menu.aboutToShow.connect(self._update_retry_button)
        toolbar.addWidget(self.selection_button)
        actions = QPushButton("列表操作 ▾")
        menu = QMenu(actions)
        self.retry_button = menu.addAction("重试全部失败", self._retry_failed)
        self.retry_canceled_action = menu.addAction(
            "重试全部取消", lambda: self._retry_matching("canceled")
        )
        menu.addSeparator()
        self.clear_success_action = menu.addAction(
            "清除已完成 / 跳过记录",
            lambda: self._clear_records(frozenset({"completed", "skipped"})),
        )
        self.clear_failed_action = menu.addAction(
            "清除失败 / 取消记录", lambda: self._clear_records(frozenset({"failed", "canceled"}))
        )
        menu.aboutToShow.connect(self._update_retry_button)
        actions.setMenu(menu)
        toolbar.addWidget(actions)
        layout.addLayout(toolbar)
        self.history_model = HistoryModel(self)
        self.history_filter = HistoryFilter(self)
        self.history_filter.setSourceModel(self.history_model)
        self.jobs_view = QTreeView()
        self.jobs_view.setObjectName("downloadList")
        self.jobs_view.setModel(self.history_filter)
        self.jobs_view.setUniformRowHeights(True)
        self.jobs_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.jobs_view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.jobs_view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.jobs_view.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.jobs_view.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        self.jobs_view.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        self.jobs_view.setColumnWidth(1, 150)
        self.jobs_view.setColumnWidth(2, 160)
        self.jobs_view.doubleClicked.connect(self._activate_row)
        self.jobs_view.selectionModel().selectionChanged.connect(self._update_retry_button)
        self.jobs_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.jobs_view.customContextMenuRequested.connect(self._context_menu)
        self.list_stack = QStackedWidget()
        self.empty_label = QLabel("在上方粘贴链接并点击下载\n需要选择选集时，先点击解析。")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.list_stack.addWidget(self.empty_label)
        self.list_stack.addWidget(self.jobs_view)
        layout.addWidget(self.list_stack, 1)
        bottom = QHBoxLayout()
        self.status_text = ElidedLabel("就绪 · 多 P 默认全部；链接指定 P 时仅下载该 P")
        self.status_text.setObjectName("operationStatus")
        bottom.addWidget(self.status_text, 1)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._cancel_active)
        bottom.addWidget(self.cancel_button)
        layout.addLayout(bottom)
        self.download_shortcut = QShortcut(QKeySequence("Ctrl+Return"), self)
        self.download_shortcut.activated.connect(self._shortcut_download)
        self.download_enter_shortcut = QShortcut(QKeySequence("Ctrl+Enter"), self)
        self.download_enter_shortcut.activated.connect(self._shortcut_download)
        for combo in (self.quality_combo, self.codec_combo, self.audio_combo):
            combo.currentIndexChanged.connect(self._update_option_summary)
        for check in (self.strict_check, self.overwrite_check):
            check.toggled.connect(self._update_option_summary)
        self.page_edit.textChanged.connect(self._update_option_summary)
        self._update_option_summary()

    def _build_options(self):
        self._options_dialog, layout, close = self._dialog("更多下载选项", 650, 360)
        self.advanced_group = self._options_dialog
        form = QFormLayout()
        self.codec_combo = QComboBox()
        for text, value in (("自动", None), ("AVC", "AVC"), ("HEVC", "HEVC"), ("AV1", "AV1")):
            self.codec_combo.addItem(text, value)
        form.addRow("视频编码", self.codec_combo)
        self.audio_combo = QComboBox()
        for text, value in (("AAC", "aac"), ("FLAC", "flac"), ("Dolby", "dolby"), ("最佳", "best")):
            self.audio_combo.addItem(text, value)
        form.addRow("音频", self.audio_combo)
        self.page_edit = QLineEdit()
        self.page_edit.setPlaceholderText("留空遵循链接指定 P；all 为全部；例如 1,3,5-7")
        form.addRow("选集范围", self.page_edit)
        form.addRow(self._button("应用范围到全部已解析视频", self._reset_part_checks))
        self.strict_check = QCheckBox("严格匹配指定画质和编码，不可用时不下载")
        self.overwrite_check = QCheckBox("替换同名文件（新文件校验成功后才替换）")
        form.addRow(self.strict_check)
        form.addRow(self.overwrite_check)
        layout.addLayout(form)
        hint = QLabel(
            "自动模式优先选择可获取的最高画质。AVC 通常兼容性更好。\n"
            "指定音频不可获取时会失败。已解析视频的选择以勾选为准；范围需要点击应用。"
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch()
        layout.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)

    def _build_parts(self):
        self._parts_dialog, layout, close = self._dialog("选择选集", 720, 520)
        self.metadata_tree = QTreeWidget()
        self.metadata_tree.setHeaderLabels(["视频 / 选集", "时长"])
        self.metadata_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.metadata_tree.currentItemChanged.connect(self._show_metadata)
        self.metadata_tree.itemChanged.connect(self._update_parse_summary)
        layout.addWidget(self.metadata_tree, 1)
        actions = QHBoxLayout()
        for text, mode in (("全选", "all"), ("全不选", "none"), ("反选", "invert")):
            actions.addWidget(
                self._button(text, lambda _checked=False, mode=mode: self._select_parts(mode))
            )
        self.part_range_edit = QLineEdit()
        self.part_range_edit.setPlaceholderText("1,3,5-7")
        actions.addWidget(self.part_range_edit, 1)
        actions.addWidget(self._button("应用", self._apply_part_range))
        layout.addLayout(actions)
        self.parts_info = QPlainTextEdit()
        self.parts_info.setReadOnly(True)
        self.parts_info.setMaximumHeight(100)
        layout.addWidget(self.parts_info)
        buttons = QHBoxLayout()
        buttons.addWidget(self._button("复制安全信息 JSON", self._copy_metadata, False))
        buttons.addStretch()
        buttons.addWidget(close)
        layout.addLayout(buttons)

    def _build_details(self):
        self._details_dialog, layout, close = self._dialog("下载详情", 720, 520)
        self.details_summary = QLabel()
        self.details_summary.setWordWrap(True)
        layout.addWidget(self.details_summary)
        technical = QCheckBox("参数与技术详情")
        layout.addWidget(technical)
        self.info_text = QPlainTextEdit()
        self.info_text.setReadOnly(True)
        self.info_text.hide()
        technical.toggled.connect(self.info_text.setVisible)
        layout.addWidget(self.info_text, 1)
        self.batch_combo = QComboBox()
        self.batch_combo.addItem("所属批次", None)
        self.batch_combo.currentIndexChanged.connect(self._show_batch)
        layout.addWidget(self.batch_combo)
        self.batch_text = QPlainTextEdit()
        self.batch_text.setReadOnly(True)
        self.batch_text.setMaximumHeight(100)
        layout.addWidget(self.batch_text)
        layout.addStretch()
        layout.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)

    def _open_settings(self, section=1):
        self.settings_tabs.setCurrentIndex(int(section))
        self._settings_dialog.show()
        self._settings_dialog.raise_()
