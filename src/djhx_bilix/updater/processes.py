"""Small process identity/wait helpers; never terminate another application."""

from __future__ import annotations

import ctypes
import os
import sys
import time
from pathlib import Path

from .protocol import UpdateError


def process_image(pid: int) -> Path | None:
    if sys.platform != "win32":
        try:
            return Path(f"/proc/{pid}/exe").resolve(strict=True)
        except OSError:
            return None
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        error = ctypes.get_last_error()
        if error == 5:
            raise UpdateError("无法查询相关进程，请关闭其他实例后手动更新")
        return None
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(buffer))
        if not kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            raise UpdateError("无法确认相关进程是否退出")
        return Path(buffer.value).resolve()
    finally:
        kernel.CloseHandle(handle)


def process_ids() -> list[int]:
    if sys.platform != "win32":
        return [int(path.name) for path in Path("/proc").iterdir() if path.name.isdecimal()]
    from ctypes import wintypes

    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    pids = (wintypes.DWORD * 32768)()
    size = wintypes.DWORD()
    if not psapi.EnumProcesses(pids, ctypes.sizeof(pids), ctypes.byref(size)):
        raise UpdateError("无法检查运行中的其他实例")
    return list(pids[: size.value // ctypes.sizeof(wintypes.DWORD)])


def other_instances(executable: Path, *, exclude: set[int] | None = None) -> list[int]:
    found = []
    for pid in process_ids():
        if pid == 0 or pid in (exclude or set()):
            continue
        try:
            image = process_image(pid)
        except UpdateError:
            # Protected system processes cannot run this per-user installed executable.
            continue
        if image == executable.resolve():
            found.append(pid)
    return found


def current_processes(executable: Path) -> list[dict]:
    pids = [os.getpid()]
    parent = os.getppid()
    if process_image(parent) == executable:
        pids.append(parent)  # Nuitka onefile bootstrap remains alive until the child exits.
    result = []
    for pid in pids:
        image = process_image(pid)
        if image is None:
            raise UpdateError("无法建立当前应用进程记录")
        result.append({"pid": pid, "image": str(image)})
    return result


def wait_for_exit(processes: list[dict], timeout: float = 90, *, abort: Path | None = None) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if abort is not None and abort.exists():
            raise UpdateError("更新交接已取消，当前应用继续运行")
        alive = False
        for process in processes:
            pid = process.get("pid")
            if type(pid) is not int or pid <= 0 or pid == os.getpid():
                raise UpdateError("更新进程记录不合法")
            image = process_image(pid)
            # A reused PID with a different image must not be waited on or killed.
            alive |= image is not None and image == Path(process["image"]).resolve()
        if not alive:
            return
        time.sleep(0.2)
    raise UpdateError("应用尚未完全退出，请关闭其他实例后重试")
