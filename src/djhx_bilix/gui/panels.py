"""List-first shell and one non-modal download editor."""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTabWidget,
    QToolBar,
    QTreeView,
    QTreeWidget,
    QVBoxLayout,
    QWidget,
)

from djhx_bilix import __version__
from djhx_bilix.models import QUALITY_NAMES

from .appearance import TaskDelegate, action_icon
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
        changed = text != self.full_text
        self.full_text = text
        self.setToolTip(text)
        super().setText(
            self.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, max(1, self.width()))
        )
        if changed:
            self.updateGeometry()

    def sizeHint(self):
        size = super().sizeHint()
        size.setWidth(self.fontMetrics().horizontalAdvance(self.full_text))
        return size

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
        help_key = QShortcut(QKeySequence("F1"), dialog)
        help_key.setAutoRepeat(False)
        help_key.activated.connect(self._open_shortcuts)
        return dialog, layout, close

    def _open_shortcuts(self):
        if not hasattr(self, "_shortcuts_dialog"):
            self._shortcuts_dialog, layout, close = self._dialog("快捷键", 560, 470)
            text = QPlainTextEdit()
            text.setReadOnly(True)
            text.setPlainText("\n".join(f"{key}  {label}" for key, label in self._shortcut_help))
            layout.addWidget(text)
            layout.addWidget(QLabel("列表快捷键仅在列表有焦点时生效；不可用动作不会执行。"))
            layout.addWidget(close)
        self._shortcuts_dialog.show()
        self._shortcuts_dialog.raise_()
        self._shortcuts_dialog.activateWindow()

    def _build_ui(self, input_type):
        self.setAcceptDrops(True)
        self._build_draft(input_type)
        self._build_details()
        self._build_about()
        self._settings_dialog, settings_layout, _close = self._dialog("BiliX 设置", 560, 440)
        self.settings_tabs = QTabWidget()
        for page, title in (
            (self._make_account_tab(), "账号"),
            (self._make_settings_tab(), "常规"),
            (self._make_doctor_tab(), "诊断"),
        ):
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(page)
            scroll.setFrameShape(QScrollArea.Shape.NoFrame)
            self.settings_tabs.addTab(scroll, title)
        settings_layout.addWidget(self.settings_tabs)
        self.settings_buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Apply
        )
        for key, text in (
            (QDialogButtonBox.StandardButton.Ok, "确定"),
            (QDialogButtonBox.StandardButton.Cancel, "取消"),
            (QDialogButtonBox.StandardButton.Apply, "应用"),
        ):
            self.settings_buttons.button(key).setText(text)
            self.settings_buttons.button(key).setAutoDefault(False)
        self.settings_buttons.accepted.connect(self._accept_settings)
        self.settings_buttons.rejected.connect(self._settings_dialog.reject)
        self.settings_buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(
            self._save_settings
        )
        self._settings_dialog.rejected.connect(self._discard_settings)
        settings_layout.addWidget(self.settings_buttons)
        self._preview_dialog, preview_layout, close = self._dialog("文件预览", 740, 500)
        preview_layout.addWidget(QLabel("预览是读取时刻的快照；执行和提交时会重新检查。"))
        self.preview_text = QPlainTextEdit()
        self.preview_text.setReadOnly(True)
        preview_layout.addWidget(self.preview_text)
        preview_layout.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)
        self._preview_dialog.rejected.connect(
            lambda: self._cancel_active() if self._active_kind == "plan" else None
        )

        files = self.menuBar().addMenu("文件")
        self.new_action = files.addAction("新建下载…", self._open_draft)
        self.new_action.setShortcut("Ctrl+N")
        self.import_action = files.addAction("导入链接列表…", self._import_urls)
        self.import_action.setShortcut("Ctrl+O")
        files.addAction("打开下载目录", self._open_default_folder)
        files.addSeparator()
        self.exit_action = files.addAction("退出", self._request_exit)
        self.exit_action.setShortcut("Ctrl+Q")
        self.exit_action.setAutoRepeat(False)
        self.account_menu = self.menuBar().addMenu("账号")
        self.login_action = self.account_menu.addAction("扫码登录", self._start_login)
        self.status_action = self.account_menu.addAction("重新验证账号", self._start_status)
        self.logout_action = self.account_menu.addAction("退出登录", self._logout)
        tools = self.menuBar().addMenu("工具")
        settings_action = tools.addAction("设置…", lambda: self._open_settings(1))
        settings_action.setShortcut("Ctrl+,")
        self.doctor_action = tools.addAction("运行诊断", self._open_doctor)
        tools.addAction("打开配置目录", self._open_config_folder)
        help_menu = self.menuBar().addMenu("帮助")
        self.shortcuts_action = help_menu.addAction("快捷键…", self._open_shortcuts)
        self.shortcuts_action.setShortcut("F1")
        self.shortcuts_action.setAutoRepeat(False)
        self.about_action = help_menu.addAction("关于 BiliX", self._open_about)
        self.check_update_action = help_menu.addAction(
            "检查更新", lambda: self._check_update(manual=True)
        )
        help_menu.addAction("复制诊断信息…", self._copy_diagnostics)

        toolbar = QToolBar("下载操作", self)
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(toolbar)
        self.new_button = QPushButton("新建下载")
        self.new_button.clicked.connect(self._open_draft)
        toolbar.addWidget(self.new_button)
        self.retry_button = toolbar.addAction("重试失败", self._retry_failed)
        self.clear_success_action = toolbar.addAction(
            "清除完成/跳过", lambda: self._clear_records(frozenset({"completed", "skipped"}))
        )
        self.selection_button = QPushButton("更多操作")
        self.selection_menu = QMenu(self.selection_button)
        self.open_action = self.selection_menu.addAction("打开文件", self._open_selected_file)
        self.folder_action = self.selection_menu.addAction(
            "打开所在目录", self._open_selected_folder
        )
        self.copy_action = self.selection_menu.addAction("复制路径", self._copy_selected_path)
        self.selection_menu.addSeparator()
        self.retry_selected_action = self.selection_menu.addAction(
            "重试选中项（原参数）", self._retry_selected
        )
        self.retry_current_action = self.selection_menu.addAction(
            "调整参数后重试…", lambda: self._retry_selected(True)
        )
        self.details_action = self.selection_menu.addAction("详情…", self._open_details)
        self.selection_menu.addSeparator()
        self.retry_canceled_action = self.selection_menu.addAction(
            "重试全部取消", lambda: self._retry_matching("canceled")
        )
        self.clear_failed_action = self.selection_menu.addAction(
            "清除失败/取消记录", lambda: self._clear_records(frozenset({"failed", "canceled"}))
        )
        self._list_shortcuts = (
            (self.details_action, "Ctrl+D", "查看选中项详情（列表）"),
            (self.retry_selected_action, "Ctrl+R", "按原参数重试选中项（列表）"),
            (self.folder_action, "Ctrl+Shift+O", "打开所在目录（列表）"),
            (self.copy_action, "Ctrl+Shift+C", "复制文件路径（列表）"),
        )
        self._shortcut_help = (
            ("Ctrl+N", "新建下载"),
            ("Ctrl+O", "导入链接文件"),
            ("Ctrl+,", "设置"),
            ("Ctrl+V", "粘贴链接 / 编辑框普通粘贴"),
            ("Ctrl+Enter / Ctrl+Return", "提交下载（下载窗口）"),
            ("Shift+F10 / 菜单键", "打开列表菜单"),
            *((key, label) for _, key, label in self._list_shortcuts),
            ("F1", "快捷键帮助"),
            ("Ctrl+Q", "退出（主窗口）"),
            ("Esc", "关闭当前对话框"),
            ("Tab / Shift+Tab", "移动焦点"),
        )
        self.selection_button.setMenu(self.selection_menu)
        self.selection_menu.aboutToShow.connect(self._update_retry_button)
        toolbar.addWidget(self.selection_button)
        self._refresh_icons()

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 6, 16, 8)
        layout.setSpacing(8)
        self.setCentralWidget(page)
        filters = QHBoxLayout()
        self.filter_combo = QComboBox()  # State adapter, not another visible filter.
        self.filter_combo.hide()
        self.filter_buttons = {}
        for text, value in (
            ("全部", "all"),
            ("进行中", "active"),
            ("完成/跳过", "success"),
            ("失败", "failed"),
            ("已取消", "canceled"),
        ):
            self.filter_combo.addItem(text, value)
            button = QPushButton(text + " 0")
            button.setCheckable(True)
            button.clicked.connect(
                lambda checked=False, value=value: self.filter_combo.setCurrentIndex(
                    self.filter_combo.findData(value)
                )
            )
            self.filter_buttons[value] = button
            filters.addWidget(button)
        filters.addStretch()
        self.filter_combo.currentIndexChanged.connect(self._filter_tasks)
        layout.addLayout(filters)
        self.history_model = HistoryModel(self)
        self.history_filter = HistoryFilter(self)
        self.history_filter.setSourceModel(self.history_model)
        self.jobs_view = QTreeView()
        self.jobs_view.setObjectName("downloadList")
        self.jobs_view.setModel(self.history_filter)
        self.jobs_view.setItemDelegate(TaskDelegate(self.jobs_view))
        self.jobs_view.setUniformRowHeights(True)
        self.jobs_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.jobs_view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.jobs_view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.jobs_view.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2):
            self.jobs_view.header().setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
        self.jobs_view.header().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.jobs_view.setColumnWidth(1, 155)
        self.jobs_view.setColumnWidth(2, 220)
        self.jobs_view.setColumnWidth(3, 45)
        for action, key, _ in self._list_shortcuts:
            self.jobs_view.addAction(action)
            action.setShortcut(key)
            action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            action.setAutoRepeat(False)
        self.jobs_view.doubleClicked.connect(self._activate_row)
        self.jobs_view.clicked.connect(self._row_menu)
        self.jobs_view.selectionModel().selectionChanged.connect(self._update_retry_button)
        self.jobs_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.jobs_view.customContextMenuRequested.connect(self._context_menu)
        self.list_stack = QStackedWidget()
        self.empty_label = QWidget()
        empty_layout = QVBoxLayout(self.empty_label)
        empty_layout.addStretch()
        logo = QLabel()
        logo.setPixmap(
            QIcon(str(Path(__file__).parents[1] / "assets/bilix-128.png")).pixmap(72, 72)
        )
        empty_layout.addWidget(logo, 0, Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(QLabel("还没有下载任务"), 0, Qt.AlignmentFlag.AlignCenter)
        self.empty_new_button = QPushButton("＋ 新建下载")
        self.empty_new_button.setProperty("primary", True)
        self.empty_new_button.clicked.connect(self._open_draft)
        empty_layout.addWidget(self.empty_new_button, 0, Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(
            QLabel("拖入链接，或按 Ctrl+V 粘贴"), 0, Qt.AlignmentFlag.AlignCenter
        )
        empty_layout.addStretch()
        self.list_stack.addWidget(self.empty_label)
        self.list_stack.addWidget(self.jobs_view)
        layout.addWidget(self.list_stack, 1)
        self.status_text = ElidedLabel("就绪")
        self.status_text.setObjectName("operationStatus")
        self.statusBar().addWidget(self.status_text, 1)
        self.account_status = ElidedLabel("未登录")
        self.account_status.setMinimumWidth(72)
        self.account_status.setMaximumWidth(250)
        self.account_status.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred
        )
        self.statusBar().addPermanentWidget(self.account_status)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.clicked.connect(self._cancel_active)
        self.statusBar().addPermanentWidget(self.cancel_button)
        self.cancel_button.hide()
        self.paste_shortcut = QShortcut(QKeySequence("Ctrl+V"), self)
        self.paste_shortcut.activated.connect(self._paste_draft)
        self.menu_shortcut = QShortcut(QKeySequence("Shift+F10"), self.jobs_view)
        self.menu_shortcut.activated.connect(self._keyboard_menu)

    def _refresh_icons(self):
        self.new_button.setIcon(action_icon("new", self.palette()))
        self.retry_button.setIcon(action_icon("retry", self.palette()))
        self.clear_success_action.setIcon(action_icon("clear", self.palette()))

    def _build_draft(self, input_type):
        self._draft_dialog, outer, close = self._dialog("新建下载", 700, 700)
        self._draft_dialog.rejected.connect(self._close_draft)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 4, 0)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        layout.addWidget(QLabel("链接 / BV 号"))
        self.urls_edit = input_type()
        self.urls_edit.setObjectName("urlInput")
        self.urls_edit.setMinimumHeight(75)
        self.urls_edit.setMaximumHeight(115)
        layout.addWidget(self.urls_edit)
        self.parse_row = QWidget()
        parse_layout = QHBoxLayout(self.parse_row)
        parse_layout.setContentsMargins(0, 0, 0, 0)
        self.parse_summary = ElidedLabel("粘贴后自动识别")
        parse_layout.addWidget(self.parse_summary, 1)
        self.info_button = QPushButton("重新识别")
        self.info_button.clicked.connect(self._request_parse)
        parse_layout.addWidget(self.info_button)
        self.retry_parse_button = QPushButton("重试失败项")
        self.retry_parse_button.clicked.connect(self._retry_parse)
        parse_layout.addWidget(self.retry_parse_button)
        layout.addWidget(self.parse_row)
        self.metadata_tree = QTreeWidget()
        self.metadata_tree.setHeaderLabels(["识别结果 / 选集", "时长 / 提示"])
        self.metadata_tree.setMinimumHeight(110)
        self.metadata_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.metadata_tree.currentItemChanged.connect(self._show_metadata)
        self.metadata_tree.itemChanged.connect(self._update_parse_summary)
        layout.addWidget(self.metadata_tree, 1)
        actions = QHBoxLayout()
        for text, mode in (("全选", "all"), ("全不选", "none"), ("反选", "invert")):
            actions.addWidget(
                self._button(text, lambda checked=False, mode=mode: self._select_parts(mode))
            )
        self.part_range_edit = QLineEdit()
        self.part_range_edit.setPlaceholderText("1,3,5-7")
        actions.addWidget(self.part_range_edit, 1)
        actions.addWidget(self._button("应用", self._apply_part_range))
        actions.addWidget(self._button("应用到全部", self._apply_all_ranges))
        layout.addLayout(actions)
        hint = QLabel("普通多 P 默认全部；链接指定 P 时仅该 P。范围须点击应用。")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.parts_info = QPlainTextEdit()
        self.parts_info.setReadOnly(True)
        self.parts_info.setMaximumHeight(65)
        self.parts_info.hide()
        details = QCheckBox("来源信息")
        details.toggled.connect(self.parts_info.setVisible)
        layout.addWidget(details)
        layout.addWidget(self.parts_info)
        copy_info = self._button("复制来源信息 JSON", self._copy_metadata, False)
        copy_info.setVisible(False)
        details.toggled.connect(copy_info.setVisible)
        layout.addWidget(copy_info)
        directory = QHBoxLayout()
        directory.addWidget(QLabel("保存到"))
        self.output_edit = QLineEdit()
        self.output_edit.setObjectName("outputDirectory")
        directory.addWidget(self.output_edit, 1)
        directory.addWidget(self._button("选择…", self._choose_output, False))
        layout.addLayout(directory)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("画质"))
        self.quality_combo = QComboBox()
        self.quality_combo.addItem("最高可用", None)
        for quality in sorted(QUALITY_NAMES, reverse=True):
            self.quality_combo.addItem(QUALITY_NAMES[quality], quality)
        controls.addWidget(self.quality_combo, 1)
        self.advanced_toggle = QPushButton("更多选项 ▾")
        self.advanced_toggle.setCheckable(True)
        controls.addWidget(self.advanced_toggle)
        layout.addLayout(controls)
        self.advanced_group = QWidget()
        form = QFormLayout(self.advanced_group)
        self.codec_combo = QComboBox()
        for text, value in (("自动", None), ("AVC", "AVC"), ("HEVC", "HEVC"), ("AV1", "AV1")):
            self.codec_combo.addItem(text, value)
        form.addRow("视频编码", self.codec_combo)
        self.audio_combo = QComboBox()
        for text, value in (("AAC", "aac"), ("FLAC", "flac"), ("Dolby", "dolby"), ("最佳", "best")):
            self.audio_combo.addItem(text, value)
        form.addRow("音频格式", self.audio_combo)
        self.page_edit = QLineEdit()
        self.page_edit.setPlaceholderText("选集范围通过上方应用，不自动改变勾选")
        self.page_edit.hide()
        self.strict_check = QCheckBox("严格匹配画质和编码")
        self.overwrite_check = QCheckBox("替换同名文件（新文件校验成功后才替换）")
        form.addRow(self.strict_check)
        form.addRow(self.overwrite_check)
        self.advanced_group.hide()
        self.advanced_toggle.toggled.connect(self.advanced_group.setVisible)
        layout.addWidget(self.advanced_group)
        self.option_summary = ElidedLabel()
        outer.addWidget(self.option_summary)
        buttons = QHBoxLayout()
        self.plan_button = QPushButton("文件预览")
        self.plan_button.clicked.connect(lambda: self._start_download(True))
        buttons.addWidget(self.plan_button)
        buttons.addStretch()
        buttons.addWidget(close)
        self.start_button = QPushButton("下载")
        self.start_button.setObjectName("startDownload")
        self.start_button.setProperty("primary", True)
        self.start_button.setAutoDefault(False)
        self.start_button.clicked.connect(self._start_download)
        buttons.addWidget(self.start_button)
        outer.addLayout(buttons)
        self.download_shortcut = QShortcut(QKeySequence("Ctrl+Return"), self._draft_dialog)
        self.download_shortcut.activated.connect(self._shortcut_download)
        self.download_enter_shortcut = QShortcut(QKeySequence("Ctrl+Enter"), self._draft_dialog)
        self.download_enter_shortcut.activated.connect(self._shortcut_download)
        self.download_shortcut.setAutoRepeat(False)
        self.download_enter_shortcut.setAutoRepeat(False)
        for combo in (self.quality_combo, self.codec_combo, self.audio_combo):
            combo.currentIndexChanged.connect(self._update_option_summary)
        for check in (self.strict_check, self.overwrite_check):
            check.toggled.connect(self._update_option_summary)
        self._update_option_summary()

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

    def _build_about(self):
        self._about_dialog, layout, close = self._dialog("关于 BiliX", 480, 380)
        logo = QLabel()
        logo.setPixmap(
            QIcon(str(Path(__file__).parents[1] / "assets/bilix-128.png")).pixmap(64, 64)
        )
        layout.addWidget(logo, 0, Qt.AlignmentFlag.AlignCenter)
        self.about_name = QLabel("<h2>BiliX</h2>")
        self.about_version = QLabel(f"版本 {__version__}")
        layout.addWidget(self.about_name, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.about_version, 0, Qt.AlignmentFlag.AlignCenter)
        form = QFormLayout()
        for name, value, url in (
            ("官网", "bilix.djhx.site", "https://bilix.djhx.site"),
            ("GitHub", "github.com/Koril33/bilix", "https://github.com/Koril33/bilix"),
            ("作者", "dingjinghui", None),
            ("邮箱", "dingjinghui33@163.com", "mailto:dingjinghui33@163.com"),
        ):
            label = QLabel(f'<a href="{url}">{value}</a>' if url else value)
            label.setOpenExternalLinks(True)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
            form.addRow(name, label)
        layout.addLayout(form)
        layout.addStretch()
        layout.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)

    def _open_about(self):
        self._restore_main()
        self._about_dialog.show()
        self._about_dialog.raise_()
        self._about_dialog.activateWindow()

    def _open_settings(self, section=1):
        if not self._settings_dialog.isVisible():
            self._discard_settings()
        self._check_credentials()
        self.settings_tabs.setCurrentIndex(int(section))
        self._settings_dialog.show()
        self._settings_dialog.raise_()
