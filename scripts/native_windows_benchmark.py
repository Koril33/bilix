"""Observe first composed client frame and idle RSS of frozen Windows releases.

Run only in the already signed-in, dedicated Windows 10 validation VM. The
external frame observation is a conservative upper bound at 50 ms polling; it
is distinct from the in-process Qt Paint benchmark. OS caches are not flushed.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import platform
import statistics
import subprocess
import time
from ctypes import wintypes
from pathlib import Path


def main() -> int:
    import png
    import psutil

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seconds", type=int, default=1200)
    parser.add_argument("--first-samples", type=int, choices=range(0, 6), default=1)
    parser.add_argument("--repeat-samples", type=int, choices=range(1, 6), default=3)
    parser.add_argument(
        "--versions", nargs="+", choices=("1.7.0", "1.7.1"), default=("1.7.0", "1.7.1")
    )
    args = parser.parse_args()
    root = Path(os.environ["USERPROFILE"]) / "AppData/Local/Temp/bilix-171-validation"
    if os.name != "nt" or root != Path(r"C:\Users\koril\AppData\Local\Temp\bilix-171-validation"):
        raise RuntimeError("Dedicated Windows 10 validation VM required")
    if args.output.parent != root:
        raise RuntimeError("Output must be inside the dedicated validation root")
    args.output.mkdir(exist_ok=False)
    user = ctypes.WinDLL("user32", use_last_error=True)
    gdi = ctypes.WinDLL("gdi32", use_last_error=True)
    dwm = ctypes.WinDLL("dwmapi")
    user.SetProcessDpiAwarenessContext.argtypes = [wintypes.HANDLE]
    user.SetProcessDpiAwarenessContext(wintypes.HANDLE(-4))
    user.GetDC.argtypes = [wintypes.HWND]
    user.GetDC.restype = wintypes.HDC
    user.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.IsWindowVisible.argtypes = [wintypes.HWND]
    user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user.GetDpiForWindow.argtypes = [wintypes.HWND]
    user.GetDpiForWindow.restype = wintypes.UINT
    gdi.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi.CreateCompatibleDC.restype = wintypes.HDC
    gdi.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    gdi.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    gdi.SelectObject.argtypes = [wintypes.HDC, wintypes.HANDLE]
    gdi.SelectObject.restype = wintypes.HANDLE
    gdi.DeleteObject.argtypes = [wintypes.HANDLE]
    gdi.DeleteDC.argtypes = [wintypes.HDC]
    gdi.BitBlt.argtypes = [
        wintypes.HDC,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.HDC,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.DWORD,
    ]
    gdi.GetDIBits.argtypes = [
        wintypes.HDC,
        wintypes.HBITMAP,
        wintypes.UINT,
        wintypes.UINT,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.UINT,
    ]
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]

    class BitmapInfo(ctypes.Structure):
        _fields_ = [
            ("size", wintypes.DWORD),
            ("width", wintypes.LONG),
            ("height", wintypes.LONG),
            ("planes", wintypes.WORD),
            ("bits", wintypes.WORD),
            ("compression", wintypes.DWORD),
            ("image_size", wintypes.DWORD),
            ("xppm", wintypes.LONG),
            ("yppm", wintypes.LONG),
            ("colors", wintypes.DWORD),
            ("important_colors", wintypes.DWORD),
        ]

    def tree(process):
        try:
            return [process, *process.children(recursive=True)]
        except psutil.Error:
            return [process]

    def windows(pids):
        found = []

        @callback_type
        def visit(handle, unused):
            pid = wintypes.DWORD()
            user.GetWindowThreadProcessId(handle, ctypes.byref(pid))
            title = ctypes.create_unicode_buffer(256)
            if pid.value in pids and user.IsWindowVisible(handle):
                user.GetWindowTextW(handle, title, 256)
                if title.value.startswith("BiliX"):
                    found.append((handle, pid.value, title.value))
            return True

        user.EnumWindows(visit, 0)
        return found

    def client_pixels(handle):
        rect = wintypes.RECT()
        if not user.GetClientRect(handle, ctypes.byref(rect)):
            return None
        width, height = rect.right, rect.bottom
        if width < 300 or height < 200:
            return None
        origin = wintypes.POINT()
        if not user.ClientToScreen(handle, ctypes.byref(origin)):
            return None
        # Read the already composed desktop, cropped strictly to the client.
        # Acquiring a new Qt window's own DC before its first paint can interfere
        # with drawing in the VirtualBox display driver.
        dc = user.GetDC(None)
        memory_dc = gdi.CreateCompatibleDC(dc)
        bitmap = gdi.CreateCompatibleBitmap(dc, width, height)
        old = gdi.SelectObject(memory_dc, bitmap)
        try:
            dwm.DwmFlush()
            if not gdi.BitBlt(memory_dc, 0, 0, width, height, dc, origin.x, origin.y, 0x00CC0020):
                return None
            info = BitmapInfo(size=40, width=width, height=-height, planes=1, bits=32)
            data = ctypes.create_string_buffer(width * height * 4)
            gdi.SelectObject(memory_dc, old)
            if gdi.GetDIBits(dc, bitmap, 0, height, data, ctypes.byref(info), 0) != height:
                return None
            raw = data.raw
            # Reject blank surfaces. Saved frames must also be reviewed visually.
            # DWM's window-show animation can briefly move the title into the
            # nominal client crop. Ignore edges so a title alone cannot pass.
            colors = {
                raw[i : i + 3]
                for y in range(50, height - 50, 5)
                for x in range(20, width - 20, 31)
                for i in ((y * width + x) * 4,)
            }
            if len(colors) < 16:
                return None
            return width, height, raw
        finally:
            gdi.SelectObject(memory_dc, old)
            gdi.DeleteObject(bitmap)
            gdi.DeleteDC(memory_dc)
            user.ReleaseDC(None, dc)

    def save_png(path, frame):
        width, height, raw = frame
        rows = []
        for y in range(height):
            row = raw[y * width * 4 : (y + 1) * width * 4]
            rows.append(
                [v for x in range(0, len(row), 4) for v in (row[x + 2], row[x + 1], row[x])]
            )
        with path.open("wb") as stream:
            png.Writer(width, height, greyscale=False).write(stream, rows)

    report = {
        "status": "running",
        "platform": platform.platform(),
        "scope": "50 ms external first composed nonblank client-frame upper bound; "
        "native Windows composed desktop cropped to client rectangle; "
        "same-time process-tree RSS; fresh process each sample; OS caches not flushed",
        "records": [],
        "first_samples_per_version": args.first_samples,
        "repeat_samples_per_version": args.repeat_samples,
    }

    def write_report():
        temporary = args.output / "result.tmp"
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(args.output / "result.json")

    write_report()
    try:
        for round_name, count in (
            ("first-sequence", args.first_samples),
            ("repeat-sequence", args.repeat_samples),
        ):
            for version in args.versions:
                executable = root / f"BiliX-GUI-Portable-{version}-windows-x64.exe"
                executable_hash = hashlib.sha256(executable.read_bytes()).hexdigest()
                for sample in range(1, count + 1):
                    label = f"{version}-{round_name}-{sample}"
                    env = dict(
                        os.environ,
                        BILIX_CONFIG_DIR=str(args.output / (label + "-profile")),
                        BILIX_DOWNLOAD_DIR=str(args.output / "downloads"),
                    )
                    for key in (
                        "PYTHONPATH",
                        "QT_QPA_PLATFORM",
                        "QT_SCALE_FACTOR",
                        "QT_SCREEN_SCALE_FACTORS",
                        "QT_FONT_DPI",
                    ):
                        env.pop(key, None)
                    started = time.perf_counter()
                    child = subprocess.Popen([str(executable)], env=env, cwd=root)
                    parent = psutil.Process(child.pid)
                    record = {
                        "version": version,
                        "round": round_name,
                        "sample": sample,
                        "sha256": executable_hash,
                        "memory": [],
                        "frame": None,
                    }
                    observed = None
                    owned = [parent]
                    try:
                        while time.perf_counter() - started < 90:
                            owned = tree(parent)
                            rss = 0
                            live = []
                            for item in owned:
                                try:
                                    rss += item.memory_info().rss
                                    live.append(item.pid)
                                except psutil.Error:
                                    pass
                            elapsed = time.perf_counter() - started
                            record["memory"].append({"seconds": elapsed, "rss": rss, "pids": live})
                            if observed is None:
                                for handle, pid, title in windows(set(live)):
                                    frame = client_pixels(handle)
                                    if frame:
                                        observed = time.perf_counter()
                                        record["frame"] = {
                                            "observed_ms": (observed - started) * 1000,
                                            "pid": pid,
                                            "title": title,
                                            "dpi": user.GetDpiForWindow(handle),
                                            "size": list(frame[:2]),
                                        }
                                        save_png(args.output / (label + ".png"), frame)
                                        break
                            elif time.perf_counter() - observed >= 15:
                                idle = [
                                    m["rss"]
                                    for m in record["memory"]
                                    if m["seconds"] >= observed - started + 5
                                ]
                                record["idle_rss_median"] = statistics.median(idle)
                                record["idle_rss_min"] = min(idle)
                                record["idle_rss_max"] = max(idle)
                                break
                            if child.poll() is not None:
                                raise RuntimeError(
                                    f"Frozen process exited before observation: {child.returncode}"
                                )
                            time.sleep(0.05)
                        else:
                            raise RuntimeError("Native frame/idle observation timed out")
                    finally:
                        for item in reversed(owned):
                            try:
                                item.terminate()
                            except psutil.Error:
                                pass
                        _, alive = psutil.wait_procs(owned, timeout=5)
                        for item in alive:
                            try:
                                item.kill()
                            except psutil.Error:
                                pass
                        child.wait(timeout=10)
                    record["status"] = "passed"
                    report["records"].append(record)
                    write_report()
        report["status"] = "passed"
    except Exception as error:
        report["status"] = "failed"
        report["error"] = f"{type(error).__name__}: {error}"
        write_report()
        raise
    write_report()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
