"""Offline 1.7 design experiment; never imported by production entry points.

Pure task/attempt, conflict, progress and input experiments are usable without Qt.
The optional renderer uses synthetic data and an isolated profile, never the API.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import statistics
import subprocess
import sys
import time
from collections import deque
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from djhx_bilix.errors import InputError
from djhx_bilix.urls import normalize_url

TERMINAL = frozenset({"completed", "skipped", "failed", "canceled"})
NEXT = {
    "queued": {"loading"},
    "loading": {"downloading"},
    "downloading": {"checking_video"},
    "checking_video": {"checking_audio"},
    "checking_audio": {"muxing"},
    "muxing": {"committing"},
    "committing": {"completed"},
}


@dataclass(frozen=True)
class Options:
    save: Path
    quality: int | None = None
    codec: str | None = None
    audio: str = "aac"
    strict: bool = False
    overwrite: bool = False
    ffmpeg: str | None = None


@dataclass(frozen=True)
class Attempt:
    number: int
    options: Options
    batch_id: str
    state: str = "queued"
    sequence: int = 0


@dataclass(frozen=True)
class Task:
    task_id: str
    batch_id: str
    source: str
    page: str
    title: str
    attempts: tuple[Attempt, ...]

    @property
    def current(self) -> Attempt:
        return self.attempts[-1]


class Session:
    """Small immutable-record experiment, not a scheduler or persistent queue."""

    def __init__(self) -> None:
        self.tasks: dict[str, Task] = {}

    def add(self, batch: str, source: str, page: str, title: str, options: Options) -> Task:
        task = Task(
            uuid4().hex, batch, normalize_url(source), page, title, (Attempt(1, options, batch),)
        )
        self.tasks[task.task_id] = task
        return task

    def transition(self, task_id: str, attempt: int, sequence: int, state: str) -> bool:
        task = self.tasks[task_id]
        old = task.current
        if attempt < old.number:
            return False
        if attempt != old.number:
            raise ValueError("future attempt")
        if sequence <= old.sequence:
            return False
        if old.state in TERMINAL:
            if state == old.state:
                return False
            raise ValueError("terminal attempt cannot change")
        permitted = NEXT[old.state] | {"failed", "canceled"}
        if old.state in {"queued", "loading", "committing"}:
            permitted |= {"skipped"}
        if state not in permitted:
            raise ValueError("invalid transition")
        new = replace(old, state=state, sequence=sequence)
        self.tasks[task_id] = replace(task, attempts=(*task.attempts[:-1], new))
        return True

    def retry(
        self, task_id: str, *, current: Options | None = None, batch_id: str | None = None
    ) -> Task:
        task = self.tasks[task_id]
        if task.current.state not in {"failed", "canceled"}:
            raise ValueError("only failed or canceled attempts may retry")
        attempt = Attempt(
            task.current.number + 1, current or task.current.options, batch_id or uuid4().hex
        )
        task = replace(task, attempts=(*task.attempts, attempt))
        self.tasks[task_id] = task
        return task

    def visible(self, states: frozenset[str] | None = None) -> list[Task]:
        return [t for t in self.tasks.values() if states is None or t.current.state in states]


def conflict(output: Path, overwrite: bool) -> str:
    """Point-in-time estimate matching current execute's exists/is_file checks."""
    if not output.exists():
        return "new"
    if not output.is_file():
        return "blocked"
    return "replace" if overwrite else "skip"


@dataclass(frozen=True)
class Setting:
    effective: str
    source: str
    file_value: str | None


def setting(default: str, file_value: str | None, environment: str | None) -> Setting:
    # Current load_settings treats an empty environment string as no override.
    if environment:
        return Setting(environment, "environment", file_value)
    if file_value is not None:
        return Setting(file_value, "file", file_value)
    return Setting(default, "default", None)


def input_lines(text: str) -> list[tuple[int, str]]:
    """Proposed stdin parser: BOM/comments/line numbers, preserving duplicates."""
    records = []
    for number, raw in enumerate(text.removeprefix("\ufeff").splitlines(), 1):
        value = raw.strip()
        if not value or value.startswith("#"):
            continue
        try:
            records.append((number, normalize_url(value)))
        except InputError as error:
            raise InputError(f"第 {number} 行：{error}") from None
    return records


class Rate:
    """Windowed combined transfer rate; reset on stream-attempt/count changes."""

    def __init__(self) -> None:
        self.samples: deque[tuple[float, int]] = deque()
        self.previous: dict[str, tuple[int, int, int | None]] = {}

    def update(
        self, now: float, streams: dict[str, tuple[int, int, int | None]]
    ) -> tuple[float | None, float | None]:
        # Each tuple is (stream attempt, bytes, total). No wall-clock arithmetic.
        if self.samples and now <= self.samples[-1][0]:
            raise ValueError("time must increase")
        if any(
            done < 0 or (total is not None and total < done) for _, done, total in streams.values()
        ):
            raise ValueError("invalid byte counts")
        reset = any(
            name in self.previous
            and (attempt != self.previous[name][0] or done < self.previous[name][1])
            for name, (attempt, done, _) in streams.items()
        )
        if reset:
            self.samples.clear()
        self.previous = dict(streams)
        done = sum(item[1] for item in streams.values())
        self.samples.append((now, done))
        while len(self.samples) > 2 and self.samples[1][0] < now - 5:
            self.samples.popleft()
        elapsed = now - self.samples[0][0]
        rate = (done - self.samples[0][1]) / elapsed if elapsed > 0 else None
        known = set(streams) == {"video", "audio"} and all(
            item[2] is not None and item[2] > 0 for item in streams.values()
        )
        remaining = sum(item[2] for item in streams.values()) - done if known else None
        eta = remaining / rate if remaining is not None and rate and rate > 0 else None
        return rate, eta


def render(output: Path) -> dict:
    """Build an offscreen layout and probe the real 1.6 window without network."""
    from unittest.mock import patch

    from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
    from PySide6.QtGui import QFont, QFontDatabase
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QComboBox,
        QFormLayout,
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QPushButton,
        QScrollArea,
        QTableView,
        QVBoxLayout,
        QWidget,
    )

    from djhx_bilix.config import load_settings, save_settings
    from djhx_bilix.gui.app import MainWindow
    from djhx_bilix.gui.worker import JobSpec

    application = QApplication.instance() or QApplication([])
    # Offscreen has no desktop font fallback on this host. Load, never copy,
    # a system font; this is not evidence of native desktop font behavior.
    font_id = QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")
    if font_id >= 0:
        application.setFont(QFont(QFontDatabase.applicationFontFamilies(font_id)[0], 10))
    from djhx_bilix import __version__

    current_audit = {
        "baseline_probe": "not applicable; requires original 1.6.0 checkout",
        "source_version": __version__,
    }
    if __version__ == "1.6.0":
        profile = output / "profile"
        with patch.dict(
            os.environ,
            {"BILIX_CONFIG_DIR": str(profile), "BILIX_DOWNLOAD_DIR": str(output / "env-dir")},
        ):
            with patch("djhx_bilix.gui.app.run_download") as operation:
                window = MainWindow()
                specs = (JobSpec("BV1j4411W7F7"), JobSpec("BV12R4y1J75d"))
                window._prepare_queue(specs)
                window._on_event({"type": "state", "key": (0, 0), "state": "completed"})
                window._on_event({"type": "state", "key": (1, 0), "state": "failed"})
                window.quality_combo.setCurrentIndex(window.quality_combo.findData(80))
                with patch.object(window, "_start_operation") as start:
                    window._retry_failed()
                retry_options = start.call_args.args[1].args[1]
                current_audit = {
                    "rows_before_retry": 2,
                    "rows_after_retry": window.jobs_table.rowCount(),
                    "retry_quality_uses_current": retry_options.quality == 80,
                    "no_download_called": not operation.called,
                }
                window.close()
            saved = save_settings(load_settings(), download_dir=output / "file-dir", ffmpeg=None)
            current_audit["save_returns_file_value"] = saved.download_dir == output / "file-dir"
            current_audit["reload_uses_environment"] = (
                load_settings().download_dir == output / "env-dir"
            )

    class Table(QAbstractTableModel):
        def __init__(self, rows):
            super().__init__()
            self.rows = rows

        def rowCount(self, parent=QModelIndex()):  # noqa: N802
            return 0 if parent.isValid() else len(self.rows)

        def columnCount(self, parent=QModelIndex()):  # noqa: N802
            return 0 if parent.isValid() else 4

        def data(self, index, role=Qt.ItemDataRole.DisplayRole):
            if index.isValid() and role == Qt.ItemDataRole.DisplayRole:
                return self.rows[index.row()][index.column()]
            return None

        def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
            if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
                return ("视频 / 选集", "状态", "本次设置", "文件 / 下一步")[section]
            return None

    view = QWidget()
    view.setWindowTitle("BiliX 1.7 布局实验（合成数据）")
    layout = QVBoxLayout(view)
    layout.addWidget(QLabel("设计原型 · 合成数据 · 未连接下载内核"))
    controls = QWidget()
    form = QFormLayout(controls)
    form.addRow("视频地址", QLineEdit("BV1j4411W7F7"))
    form.addRow("保存到", QLineEdit("D:/Videos/BiliX"))
    form.addRow("画质", QLabel("自动：当前账号可获取的最高画质"))
    form.addRow("设置来源", QLabel("默认目录由 BILIX_DOWNLOAD_DIR 控制；本批可单独指定"))
    advanced_toggle = QCheckBox("更多选项")
    form.addRow(advanced_toggle)
    advanced = QGroupBox("高级选项")
    advanced_layout = QVBoxLayout(advanced)
    advanced_layout.addWidget(QLabel("编码：自动　音轨：AAC　严格匹配：关闭　覆盖：关闭"))
    advanced.setVisible(False)
    advanced_toggle.toggled.connect(advanced.setVisible)
    form.addRow(advanced)
    choices = QGroupBox("已读取：示例视频 · 可按视频勾选选集")
    choice_layout = QVBoxLayout(choices)
    for text in ("P1 开始使用 · 04:00", "P2 编码与音轨 · 06:20", "P3 常见问题 · 02:10"):
        item = QCheckBox(text)
        item.setChecked("P2" not in text)
        choice_layout.addWidget(item)
    form.addRow(choices)
    form.addRow(QLabel("已选 2 项 · 预览：新下载 1，已有会跳过 1；执行时重新检查"))
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setWidget(controls)
    layout.addWidget(scroll, 2)
    actions = QHBoxLayout()
    for text in ("预览计划", "开始本批下载", "按原设置重试所选项"):
        actions.addWidget(QPushButton(text))
    layout.addLayout(actions)
    filters = QComboBox()
    filters.addItems(["全部记录", "失败 / 取消"])
    layout.addWidget(filters)
    table = QTableView()
    table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
    table.horizontalHeader().setStretchLastSection(True)
    layout.addWidget(table, 3)
    rows = [
        ("示例 A · P1", "已完成", "自动 / AAC", "打开文件 / 复制路径"),
        ("示例 B · P3", "失败", "1080P / AAC", "画质不可获取；按原设置重试"),
        ("示例 C · P1", "已跳过", "自动 / AAC", "已有文件；未替换"),
    ]
    models = [Table(rows), Table([row for row in rows if row[1] == "失败"])]
    table.setModel(models[0])
    table.setColumnWidth(0, 190)
    table.setColumnWidth(1, 75)
    table.setColumnWidth(2, 130)
    table.resizeRowsToContents()
    filters.currentIndexChanged.connect(lambda index: table.setModel(models[index]))
    layout.addWidget(QLabel("会话记录保留 · 已完成 1 / 已跳过 1 / 失败 1 · 关闭后不保存"))
    filters.setCurrentIndex(1)
    filtered_rows = table.model().rowCount()
    filters.setCurrentIndex(0)
    advanced_toggle.setChecked(True)
    view.show()
    application.processEvents()
    expanded_visible = advanced.isVisible()
    advanced_toggle.setChecked(False)
    collapsed_hidden = not advanced.isVisible()
    screenshots = []
    for width, height, expanded in ((1100, 760, False), (800, 600, False), (800, 600, True)):
        advanced_toggle.setChecked(expanded)
        view.resize(width, height)
        view.show()
        application.processEvents()
        name = f"layout-{width}x{height}-{'advanced' if expanded else 'basic'}.png"
        if not view.grab().save(str(output / name)):
            raise RuntimeError("screenshot failed")
        screenshots.append({"file": name, "actual_size": [view.width(), view.height()]})
    timing = []
    for count in (100, 1000):
        samples = []
        model = Table(rows * (count // 3) + rows[: count % 3])
        for _ in range(5):
            began = time.perf_counter()
            table.setModel(model)
            table.scrollToBottom()
            application.processEvents()
            samples.append(round((time.perf_counter() - began) * 1000, 3))
            table.setModel(models[0])
        timing.append(
            {"rows": count, "samples_ms": samples, "median_ms": statistics.median(samples)}
        )
    view.close()
    return {
        "current_audit": current_audit,
        "font": application.font().family(),
        "interaction_checks": {
            "filtered_rows": filtered_rows,
            "restored_rows": table.model().rowCount(),
            "advanced_visible_when_expanded": expanded_visible,
            "advanced_hidden_when_collapsed": collapsed_hidden,
        },
        "screenshots": screenshots,
        "model_swap_probe": timing,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    # A new directory prevents reuse of old screenshots or configuration evidence.
    output.mkdir(parents=True, exist_ok=False)
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ.pop("BILIX_FFMPEG", None)
    from importlib.metadata import version
    from unittest.mock import patch

    with patch(
        "curl_cffi.requests.Session.request", side_effect=AssertionError("offline only")
    ) as api:
        experiment = render(output)
        network_calls = api.call_count

    record = {
        "kind": "design-experiment-not-release-validation",
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "prototype_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "qt_package": version("PySide6-Essentials"),
        "local_time": datetime.now(UTC).astimezone(timezone(timedelta(hours=8))).isoformat(),
        "network_request_calls": network_calls,
        "working_tree": subprocess.check_output(
            ["git", "status", "--porcelain"], text=True, encoding="utf-8"
        ).splitlines(),
        **experiment,
    }
    (output / "result.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
