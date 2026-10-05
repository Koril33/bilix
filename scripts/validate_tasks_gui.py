"""Offline production GUI layout and 100/1000-task interaction measurements.

Synthetic inputs, no clients, no credentials, no network. Run five fresh
processes for startup/working-set comparison; these are source/offscreen
measurements, not a substitute for native package/desktop acceptance.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import platform
import statistics
import time
from pathlib import Path

START = time.perf_counter()
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    os.environ["BILIX_CONFIG_DIR"] = str(args.output / "profile")
    os.environ["BILIX_DOWNLOAD_DIR"] = str(args.output / "下载 中文 空格")
    from PySide6.QtGui import QFont, QFontDatabase
    from PySide6.QtWidgets import QApplication

    from djhx_bilix import __version__
    from djhx_bilix.gui.app import MainWindow
    from djhx_bilix.models import VideoTarget
    from djhx_bilix.operations import CancellationToken
    from djhx_bilix.tasks import DownloadOptions, JobSpec, run_batch

    application = QApplication([])
    if os.name == "nt":
        font_id = QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")
        if font_id >= 0:
            application.setFont(QFont(QFontDatabase.applicationFontFamilies(font_id)[0], 10))
    window = MainWindow()
    window.show()
    application.processEvents()
    result = dict(
        version=__version__,
        system=platform.platform(),
        startup_ms=(time.perf_counter() - START) * 1000,
        idle_memory_bytes=memory(),
        rows=[],
        layout=[],
    )
    options = DownloadOptions(None, None, "aac", args.output / "下载", False, False, None)
    for count in (100, 1000):
        batch = window.session.begin((JobSpec("BV1j4411W7F7"),), options)
        request_id = window.session.batches[batch].requests[0]
        targets = tuple(
            VideoTarget(
                f"https://www.bilibili.com/video/BV1j4411W7F7?p={i}",
                label=f"P{i} 合成任务 标题",
                page_number=i,
                cid=str(i),
            )
            for i in range(1, count + 1)
        )
        ids = window.session.register(request_id, targets)
        started = time.perf_counter()
        for task_id in ids:
            window.session.event(task_id, window._on_event, state="failed", detail="合成网络故障")
        window.session.source_state(request_id, "discovered", window._on_event)
        window.session.finish(batch)
        window.history_tabs.setCurrentIndex(2)
        application.processEvents()
        create_ms = (time.perf_counter() - started) * 1000
        timings = {"filter": [], "details": [], "retry_model": []}
        for _ in range(5):
            started = time.perf_counter()
            window.filter_combo.setCurrentIndex(window.filter_combo.findData("failed"))
            window._filter_tasks()
            application.processEvents()
            timings["filter"].append((time.perf_counter() - started) * 1000)
            started = time.perf_counter()
            window.jobs_table.setCurrentCell(0, 0)
            window._show_attempts()
            application.processEvents()
            timings["details"].append((time.perf_counter() - started) * 1000)
            started = time.perf_counter()
            retry = window.session.retry((ids[0],))
            window.session.event(ids[0], window._on_event, state="failed", detail="合成重试失败")
            window.session.finish(retry)
            application.processEvents()
            timings["retry_model"].append((time.perf_counter() - started) * 1000)
        for width, height, advanced in ((1100, 760, False), (800, 600, False), (800, 600, True)):
            window.resize(width, height)
            window.advanced_toggle.setChecked(advanced)
            application.processEvents()
            window.grab().save(str(args.output / f"{count}-{width}x{height}-{advanced}.png"))
            scroll = window.centralWidget().widget(0)
            result["layout"].append(
                dict(
                    tasks=count,
                    width=window.width(),
                    height=window.height(),
                    advanced=advanced,
                    horizontal_scroll_max=scroll.horizontalScrollBar().maximum(),
                    vertical_scroll_max=scroll.verticalScrollBar().maximum(),
                )
            )
        loaded_memory = memory()
        retry = window.session.retry(ids)
        token = CancellationToken()
        token.cancel()
        started = time.perf_counter()
        # An inert client proves that cancelling known queued tasks does not
        # fetch media. This measures model/UI acknowledgement, not an active
        # network transfer or FFmpeg subprocess cancellation.
        summary = run_batch(window.session, retry, window._on_event, token, client=object())
        application.processEvents()
        cancel_ms = (time.perf_counter() - started) * 1000
        assert summary["canceled"] == count
        started = time.perf_counter()
        window._clear_records(frozenset({"canceled"}))
        application.processEvents()
        clear_ms = (time.perf_counter() - started) * 1000
        assert not window.session.tasks
        result["rows"].append(
            dict(
                tasks=count,
                create_ms=create_ms,
                loaded_memory_bytes=loaded_memory,
                queued_cancel_ms=cancel_ms,
                clear_ms=clear_ms,
                interactions={
                    name: dict(
                        samples_ms=values, median_ms=statistics.median(values), worst_ms=max(values)
                    )
                    for name, values in timings.items()
                    if values
                },
            )
        )
    result["final_memory_bytes"] = memory()
    (args.output / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    window.close()
    print(args.output / "result.json")


if __name__ == "__main__":
    main()
