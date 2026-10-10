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
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from djhx_bilix import __version__, auth
from djhx_bilix.config import load_settings, save_settings
from djhx_bilix.credentials import normalize_cookie
from djhx_bilix.errors import BilixError, InputError
from djhx_bilix.media import FFmpeg, find_ffmpeg
from djhx_bilix.operations import CancellationToken
from djhx_bilix.planner import parse_quality
from djhx_bilix.tasks import Session, summary_text
from djhx_bilix.urls import load_urls, normalize_url, parse_pages, url_page

from .history import NODE_ROLE
from .panels import CompactUi, duration
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
        self.composing = False
        self.setPlaceholderText(self.hint)
        self.setTabChangesFocus(True)

    def inputMethodEvent(self, event: QInputMethodEvent) -> None:
        self.composing = bool(event.preeditString())
        self.setPlaceholderText("" if self.composing else self.hint)
        super().inputMethodEvent(event)


class MainWindow(CompactUi, QMainWindow):
    """One active background operation; downloads form a serial, visible queue."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"BiliX {__version__}")
        available = self.screen().availableGeometry()
        width = max(320, available.width() - 16)
        margin = 80 if QApplication.platformName() == "wayland" else 48
        height = max(240, available.height() - margin)
        self.setMinimumSize(min(700, width), min(540, height))
        self.resize(min(860, width), min(660, height))
        self._settings = None
        self._thread = self._worker = self._cancel = self._active_kind = None
        self._close_pending = False
        self._qr_dialog = self._qr_label = self._qr_status = None
        self._busy_buttons = []
        self.session = Session()
        self._event_versions = {}
        self._metadata = {}
        self._input_generation = self._info_generation = 0
        self._output_edited = False
        self._parse_total = self._parse_finished = self._parse_errors = 0
        self._build_ui(UrlInput)
        self._load_settings_view()
        self._offline_account()
        self.urls_edit.textChanged.connect(self._invalidate_info)
        self.output_edit.textEdited.connect(lambda _text: setattr(self, "_output_edited", True))
        self._update_retry_button()

    def _message(self, text, timeout=0):
        self.status_text.setText(text.replace("\n", " · "))

    def _button(self, text: str, callback: Any, busy_sensitive: bool = True) -> QPushButton:
        button = QPushButton(text)
        button.clicked.connect(callback)
        if busy_sensitive:
            self._busy_buttons.append(button)
        return button

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
            self._message("配置需要修正")
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
        if self._thread is not None:
            return
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
        self._message("设置已保存，与 CLI 共用", 5000)

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

    def _selected_task(self):
        index = self.jobs_view.currentIndex()
        node = index.data(NODE_ROLE) if index.isValid() else None
        return self.session.tasks.get(node.identity) if node and node.kind == "task" else None

    def _open_selected_folder(self, *_args):
        task = self._selected_task()
        if task and task.latest.output:
            self._open_folder(Path(task.latest.output).parent)
        else:
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
        self._message(f"已导入 {len(urls)} 个地址", 5000)

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

    def _update_option_summary(self, *_args):
        values = []
        if self.quality_combo.currentData() is not None:
            values.append(self.quality_combo.currentText())
        if self.codec_combo.currentData() is not None:
            values.append(self.codec_combo.currentText())
        if self.audio_combo.currentData() != "aac":
            values.append(self.audio_combo.currentText())
        if self.strict_check.isChecked():
            values.append("严格匹配画质和编码")
        if self.overwrite_check.isChecked():
            values.append("替换同名文件")
        if self.page_edit.text():
            values.append("选集范围 " + self.page_edit.text())
        self.option_summary.setText(" · ".join(values))
        self.option_summary.setVisible(bool(values))

    def _invalidate_info(self):
        had_info = bool(self._metadata)
        self._input_generation += 1
        self._metadata.clear()
        self.metadata_tree.clear()
        self._parse_total = self._parse_finished = self._parse_errors = 0
        self.parse_row.hide()
        self.parts_info.clear()
        if had_info:
            self._message("链接或账号已改变，需要重新解析后选择选集")

    def _set_account(self, text, chip):
        self.account_label.setText(text)
        self.account_button.setText(chip + " ▾")
        self.account_button.setToolTip(text)

    def _offline_account(self):
        if self._settings is None:
            self._set_account("配置不可读，无法检查本地凭据", "凭据不可读")
            return
        path = self._settings.token_file
        try:
            if not path.exists():
                self._set_account("本地未保存凭据，可扫码登录", "未登录")
            else:
                normalize_cookie(path.read_text(encoding="utf-8"), require_session=True)
                self._set_account("本地凭据已保存，尚未验证有效性；请查询状态", "凭据待验证")
        except (BilixError, OSError, UnicodeError):
            self._set_account("本地凭据无法读取或格式错误，请重新扫码", "凭据不可读")

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

    def _show_metadata(self, item=None, *_args):
        if item is None:
            return
        root = item.parent() or item
        value = self._metadata.get(self.metadata_tree.indexOfTopLevelItem(root))
        if value:
            media = (
                ", ".join(f"{v['name']} {v['codec']}" for v in value["available_streams"])
                or "未知 / 不可获取"
            )
            audio = (
                ", ".join(v["kind"].upper() for v in value["available_audio"]) or "未知 / 不可获取"
            )
            self.parts_info.setPlainText(
                f"{value['title']}\n"
                f"作者：{value['owner']} · "
                f"时长 {duration(value['duration'])}\n"
                f"当前读取选集媒体：{media} / {audio}\n"
                f"其他选集的媒体和权限在预览 / 执行时分别读取。\n"
                f"{value['description']}"
            )
        else:
            self.parts_info.setPlainText(root.text(1))

    def _copy_metadata(self) -> None:
        item = self.metadata_tree.currentItem()
        if item:
            index = self.metadata_tree.indexOfTopLevelItem(item.parent() or item)
            if index in self._metadata:
                QApplication.clipboard().setText(
                    json.dumps(self._metadata[index], ensure_ascii=False, indent=2)
                )

    def _update_parse_summary(self, *_args):
        if not self._parse_total:
            return
        selected = total = 0
        for index in self._metadata:
            root = self.metadata_tree.topLevelItem(index)
            if root:
                total += root.childCount()
                selected += sum(
                    root.child(j).checkState(0) == Qt.CheckState.Checked
                    for j in range(root.childCount())
                )
        if self._active_kind == "info":
            text = f"正在解析（{self._parse_finished} / {self._parse_total}）…"
        elif self._parse_errors:
            text = (
                f"已解析 {len(self._metadata)} / {self._parse_total} · "
                f"{self._parse_errors} 个读取失败"
            )
        elif self._parse_total == 1 and self._metadata:
            text = (
                f"已解析 · "
                f"{next(iter(self._metadata.values()))['title']} · "
                f"已选 {selected} / {total} 集"
            )
        else:
            text = f"已解析 {len(self._metadata)} 个视频 · 已选 {selected} / {total} 集"
        self.parse_summary.setText(text)
        self.parse_row.show()

    def _part_root(self):
        item = self.metadata_tree.currentItem()
        return (item.parent() or item) if item else self.metadata_tree.topLevelItem(0)

    def _select_parts(self, mode):
        root = self._part_root()
        if root is None or self._thread is not None:
            return
        for i in range(root.childCount()):
            child = root.child(i)
            checked = (
                mode == "all" or mode == "invert" and child.checkState(0) != Qt.CheckState.Checked
            )
            child.setCheckState(0, Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self._update_parse_summary()

    def _apply_part_range(self):
        root = self._part_root()
        if root is None or self._thread is not None:
            return
        try:
            pages = parse_pages(self.part_range_edit.text().strip() or None)
        except BilixError as error:
            self._error(str(error))
            return
        for i in range(root.childCount()):
            child = root.child(i)
            child.setCheckState(
                0,
                Qt.CheckState.Checked
                if pages is None or child.data(0, Qt.ItemDataRole.UserRole) in pages
                else Qt.CheckState.Unchecked,
            )
        self._update_parse_summary()

    def _shortcut_download(self):
        if not self.urls_edit.composing and self._thread is None:
            self._start_download()

    def _selected_ids(self):
        tasks, sources = [], []
        reread = {r.origin_request_id for r in self.session.requests.values()}
        for index in self.jobs_view.selectionModel().selectedRows():
            node = index.data(NODE_ROLE)
            if node.kind == "task":
                tasks.append(node.identity)
            elif not node.children and node.identity not in reread:
                sources.append(node.identity)
        return tuple(tasks), tuple(sources)

    def _start_download(
        self, dry_run: bool = False, specs: tuple[JobSpec, ...] | None = None
    ) -> None:
        if self._thread is not None:
            return
        try:
            selected = specs if specs is not None else self._inputs()
            options = self._options(dry_run)
            if dry_run:
                self.preview_text.clear()
                self._preview_dialog.show()
                self._start_operation("plan", partial(run_download, selected, options))
                return
            batch_id = self.session.begin(selected, options)
        except BilixError as error:
            self._error(str(error))
            return
        self._start_batch(batch_id)

    def _start_batch(self, batch_id):
        self._message("准备下载… · 当前下载结束后可添加新链接")
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

    def _filter_tasks(self):
        self.history_filter.set_state(self.filter_combo.currentData())
        self._update_retry_button()

    def _show_attempts(self):
        task = self._selected_task()
        if task:
            self.info_text.setPlainText(
                "\n\n".join(
                    (
                        f"尝试 {a.number} · "
                        f"{_STATES.get(a.state, a.state)} · "
                        f"批次 {a.batch_id}\n"
                        f"{a.options.description()}\n"
                        f"实际 FFmpeg {a.resolved_ffmpeg or '未调用'}\n"
                        f"{a.detail}\n"
                        f"类别 {a.error_code or '无'} · "
                        f"{a.action}\n"
                        f"计划路径 {a.planned_output or '尚未生成'}\n"
                        f"实际输出 {a.output or '无'}"
                    )
                    for a in task.attempts
                )
            )

    def _open_details(self, *_args):
        index = self.jobs_view.currentIndex()
        node = index.data(NODE_ROLE) if index.isValid() else None
        if node is None:
            return
        self.batch_combo.clear()
        self.batch_combo.addItem("所属批次", None)
        self.batch_text.clear()
        task = self._selected_task()
        if task:
            attempt = task.latest
            text = (
                f"{task.label} · "
                f"P{task.spec.page}\n"
                f"{_STATES.get(attempt.state, attempt.state)}\n"
                f"{attempt.detail} {attempt.action}\n"
                f"输出：{attempt.output or '尚无输出'}"
            )
            self._show_attempts()
            batch_ids = list(dict.fromkeys(a.batch_id for a in task.attempts))
        else:
            request = self.session.requests.get(node.identity)
            if request is None:
                return
            text = f"{node.title}\n{request.detail} {request.action}"
            self.info_text.setPlainText(
                f"{request.spec.source}\n"
                f"{request.options.description()}\n"
                f"请求 {request.request_id} · "
                f"原请求 {request.origin_request_id or '无'}"
            )
            batch_ids = [request.batch_id]
        self.details_summary.setText(text)
        for batch_id in batch_ids:
            self.batch_combo.addItem(f"批次 {batch_id[:8]}", batch_id)
        self.batch_combo.setCurrentIndex(len(batch_ids))
        self._details_dialog.show()

    def _activate_row(self, index):
        node = index.data(NODE_ROLE)
        if node.children:
            return
        task = self._selected_task()
        if task and task.latest.state in {"completed", "skipped"}:
            self._open_selected_file()
        else:
            self._open_details()

    def _context_menu(self, position):
        index = self.jobs_view.indexAt(position)
        if index.isValid() and not self.jobs_view.selectionModel().isSelected(index):
            self.jobs_view.setCurrentIndex(index)
        self._update_retry_button()
        self.selection_menu.popup(self.jobs_view.viewport().mapToGlobal(position))

    def _show_batch(self):
        batch = self.session.batches.get(self.batch_combo.currentData())
        self.batch_text.setPlainText(
            summary_text(dict(batch.summary))
            if batch and batch.finished
            else "批次进行中"
            if batch
            else ""
        )

    def _clear_records(self, states):
        if self._thread is not None:
            return
        self.session.clear(states)
        self.history_model.rebuild(self.session)
        self._event_versions = {
            i: v for i, v in self._event_versions.items() if i in self.session.tasks
        }
        self.list_stack.setCurrentIndex(1 if self.history_model.roots else 0)
        self._update_retry_button()

    def _selected_output(self):
        task = self._selected_task()
        if task and task.latest.state in {"completed", "skipped"} and task.latest.output:
            return Path(task.latest.output)

    def _open_selected_file(self):
        output = self._selected_output()
        if not output or not output.is_file():
            self._error("尚无可打开的输出文件，或文件已被移动 / 删除")
        elif not QDesktopServices.openUrl(QUrl.fromLocalFile(str(output))):
            self._error("无法打开输出文件，请检查桌面关联程序")

    def _copy_selected_path(self):
        output = self._selected_output()
        if output and output.is_file():
            QApplication.clipboard().setText(str(output))
        else:
            self._error("尚无输出文件，或文件已被移动 / 删除")

    def _start_info(self):
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
        self._parse_total, self._parse_finished, self._parse_errors = len(specs), 0, 0
        for spec in specs:
            self.metadata_tree.addTopLevelItem(QTreeWidgetItem([spec.source, "等待读取"]))
        self._start_operation("info", partial(run_info, specs))
        self._update_parse_summary()

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
        if self._thread is not None:
            return
        self.account_label.setText("正在查询账号状态…")
        self._start_operation("status", run_status)

    def _logout(self) -> None:
        if self._thread is not None:
            return
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
        self._set_account("已退出登录，本地凭据已删除。", "未登录")
        self._invalidate_info()

    def _start_doctor(self) -> None:
        if self._thread is not None:
            return
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
        self._message("操作进行中…")
        thread.start()
        return True

    def _set_busy(self, busy):
        for button in self._busy_buttons:
            button.setEnabled(not busy)
        self.cancel_button.setEnabled(busy)
        labels = {
            "download": "取消本批下载",
            "plan": "取消预览",
            "info": "取消解析",
            "login": "取消登录",
            "status": "取消查询",
            "doctor": "取消诊断",
        }
        self.cancel_button.setText(labels.get(self._active_kind, "取消"))
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
            self.default_output_edit,
            self.ffmpeg_edit,
            self.part_range_edit,
        ):
            widget.setEnabled(not busy)
        self.import_action.setEnabled(not busy)
        self._update_retry_button()

    def _cancel_active(self) -> None:
        if self._cancel is not None:
            self._cancel.cancel()
            self.cancel_button.setEnabled(False)
            self.cancel_button.setText("正在取消…")
            self._message("正在取消，请等待当前请求或媒体处理停止…")

    def _on_event(self, event):
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
            self._parse_finished += 1
            if event.get("error"):
                self._parse_errors += 1
                root.setText(1, "读取失败：" + event["error"])
            else:
                data = event["metadata"]
                self._metadata[index] = data
                root.setText(0, data["title"])
                root.setText(1, duration(data["duration"]))
                pages = data["pages"] or [
                    dict(number=1, title=data["title"], duration=data["duration"])
                ]
                for page in pages:
                    child = QTreeWidgetItem(
                        [f"P{page['number']} {page['title']}", duration(page["duration"])]
                    )
                    child.setData(0, Qt.ItemDataRole.UserRole, page["number"])
                    child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    child.setCheckState(0, Qt.CheckState.Checked)
                    root.addChild(child)
                root.setExpanded(True)
                self._reset_part_checks()
                self.metadata_tree.setCurrentItem(root)
            self._update_parse_summary()
            return
        if kind == "preview":
            decision = {
                "new": "新建",
                "skip": "跳过（已存在，未校验）",
                "replace": "替换",
                "blocked": "阻止",
            }[event["conflict"]]
            detail = (
                f"[{event['source_index'] + 1}] {event.get('title', '')} "
                f"{event.get('label', '')} · "
                f"{decision}\n"
                f"{event.get('selection', '')} → {event.get('output', '无计划路径')}\n"
            )
            detail += "；".join(event.get("warnings", ()))
            if event.get("duplicate"):
                detail += "；本批次输出路径重复，将逐项重新检查"
            detail += event.get("detail", "") + " " + event.get("action", "")
            self.preview_text.appendPlainText(detail)
            return
        if kind == "source":
            self.history_model.source(event["request"])
            self.list_stack.setCurrentIndex(1)
            self._update_retry_button()
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
        previous = self._event_versions.get(task.task_id)
        if previous and previous[0] == attempt.attempt_id and attempt.sequence <= previous[1]:
            return
        node = self.history_model.tasks.get(task.task_id)
        if node and attempt.number < node.attempt:
            return
        self._event_versions[task.task_id] = attempt.attempt_id, attempt.sequence
        progress = None
        if kind == "progress":
            names = {"video": "视频", "audio": "音频"}
            parts = []
            for stream, (done, expected) in event["streams"].items():
                value = f"{min(100, done * 100 // expected)}%" if expected else _display_size(done)
                parts.append(f"{names.get(stream, stream)} {value}")
            progress = " · ".join(parts)
        row = self.history_model.task(
            task,
            attempt,
            self.session.requests[task.request_id],
            title=event.get("title"),
            progress=progress,
        )
        self.jobs_view.expand(
            self.history_filter.mapFromSource(self.history_model.row_index(row.parent))
        )
        self.list_stack.setCurrentIndex(1)
        counts = self.history_model.counts
        self._message(
            f"{_STATES.get(attempt.state, attempt.state)} · "
            f"完成 {counts['completed']} · "
            f"跳过 {counts['skipped']} · "
            f"失败 {counts['failed']} · "
            f"已发现 {len(self.history_model.tasks)} 项任务"
        )
        if kind != "progress":
            self._update_retry_button()

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

    def _on_done(self, result):
        kind, state = self._active_kind, result["state"]
        if kind in ("download", "plan"):
            if state == "ok":
                counts = result["value"]
                summary = summary_text(counts)
                self._message(
                    f"{'预览' if kind == 'plan' else '下载'}已结束 · "
                    f"完成 {counts['completed']} · "
                    f"跳过 {counts['skipped']} · "
                    f"失败 {counts['failed']} · "
                    f"读取失败 {counts['source_failed']} · "
                    f"取消 {counts['canceled'] + counts['source_canceled']}"
                )
                if kind == "plan":
                    self.preview_text.appendPlainText(summary)
            else:
                self._message("已取消" if state == "canceled" else "操作失败")
        elif kind == "status" and state == "ok":
            info = result["value"]
            if not info.get("logged_in"):
                self._set_account(
                    "登录已失效，请重新扫码" if info.get("expired") else "未登录",
                    "登录已失效" if info.get("expired") else "未登录",
                )
            else:
                membership = "年度大会员" if info.get("vip_type") == 2 else "大会员"
                if not info.get("vip"):
                    membership = "普通账号"
                self._set_account(
                    (
                        f"已登录：{info.get('name', '')} · "
                        f"UID {info.get('uid', '')} · "
                        f"等级 {info.get('level', '')} · "
                        f"{membership}"
                    ),
                    f"已登录：{info.get('name') or '账号'}",
                )
            self._invalidate_info()
        elif kind == "login":
            if state == "ok":
                self._invalidate_info()
                self._set_account("登录成功，凭据已保存。可点击查询状态查看账号。", "凭据待验证")
            if self._qr_dialog is not None:
                self._qr_dialog.accept() if state == "ok" else self._qr_dialog.reject()
                self._qr_dialog = self._qr_label = self._qr_status = None
        elif kind == "doctor":
            self.doctor_text.setPlainText(
                result["value"] if state == "ok" else result.get("message", "已取消")
            )
        elif kind == "info":
            self._active_kind = None  # Parsing summary now describes results, not loading.
            self._update_parse_summary()
            self._active_kind = kind
            self._message(f"解析结束 · {len(self._metadata)} 成功 · {self._parse_errors} 失败")
        elif kind == "status":
            self.account_label.setText(
                "账号状态查询已取消。"
                if state == "canceled"
                else "账号状态查询失败，请检查网络后重试。"
            )
        if state == "error" and not self._close_pending:
            self._error(result["message"])
        elif state == "canceled":
            self._message("操作已取消")

    def _on_thread_finished(self) -> None:
        self._thread = None
        self._worker = None
        self._cancel = None
        self._active_kind = None
        self._set_busy(False)
        if self._close_pending:
            QTimer.singleShot(0, self.close)

    def _update_retry_button(self, *_args):
        if not hasattr(self, "history_model"):
            return
        idle = self._thread is None
        states = self.history_model.counts
        reread = {r.origin_request_id for r in self.session.requests.values()}
        sources = [r for i, r in self.session.requests.items() if i not in reread]
        failed = states["failed"] or any(r.state == "failed" for r in sources)
        canceled = states["canceled"] or any(r.state == "canceled" for r in sources)
        self.retry_button.setEnabled(bool(idle and failed))
        self.retry_canceled_action.setEnabled(bool(idle and canceled))
        self.clear_success_action.setEnabled(
            bool(idle and (states["completed"] or states["skipped"]))
        )
        self.clear_failed_action.setEnabled(bool(idle and (failed or canceled)))
        task_ids, source_ids = self._selected_ids()
        retryable = (
            bool(task_ids or source_ids)
            and all(self.session.tasks[i].latest.state in {"failed", "canceled"} for i in task_ids)
            and all(self.session.requests[i].state in {"failed", "canceled"} for i in source_ids)
        )
        self.retry_selected_action.setEnabled(idle and retryable)
        self.retry_current_action.setEnabled(idle and retryable)
        output = self._selected_output()
        self.open_action.setEnabled(bool(output and output.is_file()))
        self.copy_action.setEnabled(self.open_action.isEnabled())
        task = self._selected_task()
        folder = (
            Path(task.latest.output).parent
            if task and task.latest.output
            else Path(self.output_edit.text().strip()).expanduser()
        )
        self.folder_action.setEnabled(self.jobs_view.currentIndex().isValid() and folder.is_dir())
        self.details_action.setEnabled(self.jobs_view.currentIndex().isValid())
        self.selection_button.setEnabled(self.jobs_view.currentIndex().isValid())

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
