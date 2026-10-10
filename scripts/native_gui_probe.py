"""Native production-window evidence, controlled from a local command file.

Run in the dedicated test desktop with isolated settings. This is a source or
installed-wheel harness, not a frozen-program startup benchmark. Queue inputs
are synthetic; native keyboard/IME and desktop screenshots are separate evidence.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import platform
import time
from collections import Counter
from pathlib import Path

START = time.perf_counter()


def memory() -> int | None:
    if os.name == "nt":
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
                (name, ctypes.c_size_t)
                for name in (
                    "peak",
                    "working",
                    "paged_peak",
                    "paged",
                    "nonpaged_peak",
                    "nonpaged",
                    "pagefile",
                    "peak_pagefile",
                )
            ]

        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        kernel = ctypes.WinDLL("kernel32")
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        psapi = ctypes.WinDLL("psapi")
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
        if psapi.GetProcessMemoryInfo(
            kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb
        ):
            return counters.working
    elif Path("/proc/self/status").is_file():
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seconds", type=int, default=600)
    parser.add_argument("--download", help="Real media sample for an isolated performance run")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "下载 中文 空格").mkdir()
    os.environ["BILIX_CONFIG_DIR"] = str(args.output / "profile")
    os.environ["BILIX_DOWNLOAD_DIR"] = str(args.output / "下载 中文 空格")
    from PySide6.QtCore import QEvent, QObject, Qt, QTimer
    from PySide6.QtGui import QTextLayout
    from PySide6.QtWidgets import QApplication

    from djhx_bilix import __version__
    from djhx_bilix.gui.app import MainWindow

    application = QApplication([])
    backend = application.platformName()
    if backend in {"offscreen", "minimal", "vnc"}:
        raise RuntimeError(f"Native desktop required; got {backend}")
    window = MainWindow()
    try:
        import psutil
    except ImportError:
        psutil = None
    cjk_layout = QTextLayout("中文下载", window.font())
    cjk_layout.beginLayout()
    cjk_layout.createLine()
    cjk_layout.endLayout()
    cjk_fonts = [
        {"family": run.rawFont().familyName(), "glyphs": list(run.glyphIndexes())}
        for run in cjk_layout.glyphRuns()
    ]
    record = dict(
        version=__version__,
        python=platform.python_version(),
        platform=platform.platform(),
        backend=backend,
        session=os.environ.get("XDG_SESSION_TYPE"),
        display=os.environ.get("DISPLAY"),
        wayland=os.environ.get("WAYLAND_DISPLAY"),
        pid=os.getpid(),
        first_paint_ms=None,
        key_events=0,
        ime_commits=0,
        ime_preedits=0,
        memory_samples=[],
        memory_tree_samples=[],
        real_download=None,
        actions=[],
        status="running",
    )
    last_command = None
    ids = ()
    batch_id = None
    tick = 0

    def write_record() -> None:
        temporary = args.output / "result.tmp"
        temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(args.output / "result.json")

    def snapshot() -> dict:
        screen = window.screen()
        focus = application.focusWidget()
        table = window.jobs_view
        nodes = list(window.history_model.tasks.values())
        rows = len(nodes)
        indexes = [
            window.history_filter.mapFromSource(window.history_model.row_index(node))
            for node in nodes
        ]
        last_index = indexes[-1] if indexes else None
        region = table.viewport().visibleRegion()
        on_screen = [
            index
            for index in indexes
            if index.isValid() and region.intersects(table.visualRect(index))
        ]
        last_visible = bool(
            last_index and last_index.isValid() and region.contains(table.visualRect(last_index))
        )
        current = table.currentIndex()
        node = current.data(Qt.ItemDataRole.UserRole) if current.isValid() else None
        return dict(
            visible=window.isVisible(),
            active=window.isActiveWindow(),
            exposed=bool(window.windowHandle() and window.windowHandle().isExposed()),
            size=[window.width(), window.height()],
            frame=[
                window.frameGeometry().x(),
                window.frameGeometry().y(),
                window.frameGeometry().width(),
                window.frameGeometry().height(),
            ],
            screen=[screen.geometry().width(), screen.geometry().height()],
            available=[screen.availableGeometry().width(), screen.availableGeometry().height()],
            available_rect=[
                screen.availableGeometry().x(),
                screen.availableGeometry().y(),
                screen.availableGeometry().width(),
                screen.availableGeometry().height(),
            ],
            advanced_visible=window.advanced_group.isVisible(),
            visible_rows=sum(index.isValid() for index in indexes),
            table_visible_rows=len(on_screen),
            last_task_visible=last_visible,
            last_task_text=nodes[-1].title if nodes else None,
            last_task_progress=nodes[-1].progress if nodes else None,
            filter_state=window.filter_combo.currentData(),
            task_states=dict(Counter(t.latest.state for t in window.session.tasks.values())),
            device_pixel_ratio=window.devicePixelRatioF(),
            logical_dpi=screen.logicalDotsPerInch(),
            focus=focus.metaObject().className() if focus else None,
            url_text=window.urls_edit.toPlainText(),
            placeholder=window.urls_edit.placeholderText(),
            focus_text=focus.text() if focus and hasattr(focus, "text") else None,
            outer_scroll=0,
            selected_row=node.row if node and node.kind == "task" else None,
            progress_text=window.status_text.full_text,
            font_family=window.font().family(),
            cjk_fonts=cjk_fonts,
            output=window.output_edit.text(),
            rows=rows,
            table_scroll=table.verticalScrollBar().value() if table else None,
            memory_bytes=memory(),
            key_events=record["key_events"],
            ime_commits=record["ime_commits"],
            ime_preedits=record["ime_preedits"],
        )

    class Events(QObject):
        def eventFilter(self, watched, event):
            if event.type() == QEvent.Type.KeyPress:
                record["key_events"] += 1
            elif event.type() == QEvent.Type.InputMethod:
                if event.commitString():
                    record["ime_commits"] += 1
                if event.preeditString():
                    record["ime_preedits"] += 1
            elif watched is window and event.type() == QEvent.Type.Paint:
                if record["first_paint_ms"] is None:
                    record["first_paint_monotonic"] = time.perf_counter()
                    record["first_paint_ms"] = (record["first_paint_monotonic"] - START) * 1000
                    QTimer.singleShot(0, ready)
            return False

    def ready() -> None:
        record["ready"] = snapshot()
        window.grab().save(str(args.output / "first-window.png"))
        if backend == "xcb":
            application.primaryScreen().grabWindow(0).save(str(args.output / "first-desktop.png"))
        write_record()

    observer = Events()
    application.installEventFilter(observer)

    def command() -> None:
        nonlocal last_command, ids, batch_id, tick
        command_file = args.output / "command.json"
        if not command_file.is_file():
            return
        try:
            request = json.loads(command_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if request.get("id") == last_command:
            return
        last_command = request.get("id")
        started = time.perf_counter()
        try:
            action = request["action"]
            if action == "focus_url":
                window.urls_edit.setFocus(Qt.FocusReason.OtherFocusReason)
            elif action == "resize":
                window.resize(int(request["width"]), int(request["height"]))
                window._options_dialog.setVisible(bool(request.get("advanced", False)))
            elif action == "directory":
                QTimer.singleShot(0, window._choose_output)
            elif action == "queue":
                from djhx_bilix.models import VideoTarget
                from djhx_bilix.tasks import DownloadOptions, JobSpec

                count = int(request.get("count", 1000))
                if not 1 <= count <= 1000:
                    raise ValueError("Probe count must be 1..1000")
                options = DownloadOptions(
                    None, None, "aac", args.output / "downloads", False, False, None
                )
                batch_id = window.session.begin((JobSpec("BV1j4411W7F7"),), options)
                source_id = window.session.batches[batch_id].requests[0]
                targets = tuple(
                    VideoTarget(
                        f"https://www.bilibili.com/video/BV1j4411W7F7?p={i}",
                        label=f"P{i} 原生交互合成任务",
                        page_number=i,
                        cid=str(i),
                    )
                    for i in range(1, count + 1)
                )
                ids = window.session.register(source_id, targets)
                for task_id in ids:
                    for state in ("queued", "loading", "downloading"):
                        window.session.event(task_id, window._on_event, state=state)
                window.session.source_state(source_id, "discovered", window._on_event)
                tick = 0
            elif action == "finish_queue":
                for task_id in ids:
                    window.session.event(
                        task_id,
                        window._on_event,
                        state="failed",
                        detail="合成队列测试终态；没有网络请求",
                    )
                window.session.finish(batch_id)
                batch_id = None
            elif action == "filter":
                index = window.filter_combo.findData(request["state"])
                if index < 0:
                    raise ValueError("Unknown task filter: " + str(request["state"]))
                window.filter_combo.setCurrentIndex(index)
            elif action == "focus_table":
                window.jobs_view.setFocus(Qt.FocusReason.OtherFocusReason)
            elif action == "settings_dpi":
                os.startfile("ms-settings:display")
            elif action == "download":
                if batch_id or window._thread:
                    raise RuntimeError("Another operation is active")
                window.urls_edit.setPlainText(request["url"])
                window.quality_combo.setCurrentIndex(window.quality_combo.findData(16))
                window.codec_combo.setCurrentIndex(window.codec_combo.findData("HEVC"))
                record["real_download"] = {"url": request["url"], "started": time.perf_counter()}
                window._start_download()
                if not window._thread:
                    raise RuntimeError("Download did not start")
            elif action == "snapshot":
                pass
            elif action == "close":
                if batch_id:
                    for task_id in ids:
                        window.session.event(task_id, window._on_event, state="canceled")
                    window.session.finish(batch_id)
                    batch_id = None
                window.close()
            else:
                raise ValueError(f"Unknown probe action: {action}")
            response = dict(
                id=last_command,
                action=action,
                status="passed",
                seconds=time.perf_counter() - started,
                snapshot=snapshot(),
            )
            window.grab().save(str(args.output / f"action-{last_command}.png"))
            if backend == "xcb":
                application.primaryScreen().grabWindow(0).save(
                    str(args.output / f"desktop-{last_command}.png")
                )
        except Exception as error:
            response = dict(
                id=last_command, status="failed", error=f"{type(error).__name__}: {error}"
            )
        record["actions"].append(response)
        (args.output / "response.json").write_text(
            json.dumps(response, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        write_record()

    def progress() -> None:
        nonlocal tick
        record["memory_samples"].append(memory())
        if psutil is not None:
            try:
                parent = psutil.Process()
                processes = [parent, *parent.children(recursive=True)]
                rss = 0
                members = []
                for process in processes:
                    try:
                        name = process.name()
                        working = process.memory_info().rss
                        rss += working
                        members.append({"pid": process.pid, "name": name, "rss": working})
                    except psutil.NoSuchProcess:
                        continue
                record["memory_tree_samples"].append(
                    {
                        "seconds": time.perf_counter(),
                        "rss": rss,
                        "processes": len(members),
                        "members": members,
                    }
                )
            except psutil.Error as error:
                record.setdefault("memory_sampling_errors", []).append(str(error))
        if (
            record["real_download"]
            and "finished" not in record["real_download"]
            and not window._thread
        ):
            record["real_download"]["finished"] = time.perf_counter()
            record["real_download"]["states"] = [
                t.latest.state for t in window.session.tasks.values()
            ]
            record["real_download"]["files"] = [
                str(p.relative_to(args.output)) for p in args.output.rglob("*.mp4")
            ]
            write_record()
            QTimer.singleShot(1000, window.close)
        if batch_id:
            tick += 1
            for task_id in ids[(tick * 50) % len(ids) :][:50]:
                window.session.event(
                    task_id,
                    window._on_event,
                    kind="progress",
                    streams={"video": (min(tick, 999), 1000), "audio": (min(tick, 999), 1000)},
                )
        record["progress_ticks"] = tick

    timer = QTimer()
    timer.timeout.connect(command)
    timer.start(100)
    samples = QTimer()
    samples.timeout.connect(progress)
    samples.start(100)
    window.show()
    if args.download:

        def start_sample():
            (args.output / "command.json").write_text(
                json.dumps({"id": "real-download", "action": "download", "url": args.download}),
                encoding="utf-8",
            )

        QTimer.singleShot(10000, start_sample)
    QTimer.singleShot(args.seconds * 1000, window.close)
    result = application.exec()
    record["final"] = snapshot()
    record["status"] = "passed" if record["first_paint_ms"] is not None else "failed"
    write_record()
    return result


if __name__ == "__main__":
    raise SystemExit(main())
