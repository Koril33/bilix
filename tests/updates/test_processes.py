"""Windows process objects can outlive the executable they represented."""

import subprocess
import sys
import time
from pathlib import Path
from threading import Timer
from types import SimpleNamespace

import pytest

from djhx_bilix.updater import processes
from djhx_bilix.updater.protocol import UpdateError

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows process-handle regression")


@pytest.fixture
def child_process():
    children = []

    def start(exit_code=0):
        # The pipe keeps the child alive until the test deliberately releases it.
        child = subprocess.Popen(
            [
                sys.executable,
                "-I",
                "-B",
                "-c",
                "import sys; sys.stdin.buffer.read(1); sys.exit(int(sys.argv[1]))",
                str(exit_code),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        children.append(child)  # Retain the Windows process handle after child.wait().
        return child

    yield start

    for child in children:
        # Closing our pipe normally releases even a virtualenv launcher's inner process.
        if child.stdin is not None and not child.stdin.closed:
            child.stdin.close()
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            child.terminate()  # Only a process created by this fixture is ever stopped.
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)


def record(child):
    image = processes.process_image(child.pid)
    assert image == Path(sys.executable).resolve()
    return [{"pid": child.pid, "image": str(image)}]


@pytest.mark.parametrize("exit_code", [0, 259])
def test_exited_child_with_retained_handle_is_not_alive(child_process, exit_code):
    child = child_process(exit_code)
    original = record(child)
    child.stdin.close()
    assert child.wait(timeout=10) == exit_code

    # Popen still owns the process handle: OpenProcess may succeed for this dead PID.
    # Exit code 259 must also be recognised as exited, despite matching STILL_ACTIVE.
    assert processes.process_image(child.pid) is None
    started = time.monotonic()
    processes.wait_for_exit(original, timeout=0.1)
    assert time.monotonic() - started < 1


def test_active_child_is_identified_and_wait_timeout_does_not_stop_it(child_process):
    child = child_process()
    original = record(child)
    assert child.poll() is None

    with pytest.raises(UpdateError, match="尚未完全退出"):
        processes.wait_for_exit(original, timeout=0.05)

    assert child.poll() is None
    assert processes.process_image(child.pid) == Path(original[0]["image"])


def test_wait_observes_real_exit_while_launcher_retains_handle(child_process):
    child = child_process()
    original = record(child)
    release = Timer(0.2, child.stdin.close)
    release.start()
    try:
        processes.wait_for_exit(original, timeout=10)
    finally:
        release.join(timeout=10)
    assert not release.is_alive()
    assert child.wait(timeout=10) == 0
    assert processes.process_image(child.pid) is None


def test_wait_does_not_wait_for_live_pid_with_a_different_image(child_process, tmp_path):
    child = child_process()
    record(child)
    old_record = [{"pid": child.pid, "image": str(tmp_path / "previous-application.exe")}]

    processes.wait_for_exit(old_record, timeout=0.1)

    assert child.poll() is None


def test_exit_during_image_query_is_recognised_on_the_same_handle(child_process, monkeypatch):
    child = child_process()
    record(child)
    real_kernel = processes.ctypes.WinDLL("kernel32", use_last_error=True)

    def exit_before_query(*_args):
        # Reproduce the exit race after a handle was opened for a live process.
        child.stdin.close()
        assert child.wait(timeout=10) == 0
        processes.ctypes.set_last_error(6)
        return 0

    kernel = SimpleNamespace(
        OpenProcess=real_kernel.OpenProcess,
        QueryFullProcessImageNameW=exit_before_query,
        WaitForSingleObject=real_kernel.WaitForSingleObject,
        CloseHandle=real_kernel.CloseHandle,
    )
    monkeypatch.setattr(processes.ctypes, "WinDLL", lambda *_args, **_kwargs: kernel)

    assert processes.process_image(child.pid) is None


@pytest.mark.parametrize("error", [5, 8], ids=["access-denied", "unexpected-system-error"])
def test_open_process_errors_are_not_treated_as_exit(monkeypatch, error):
    class NativeFunction:
        def __call__(self, *_args):
            return 0

    kernel = SimpleNamespace(
        OpenProcess=NativeFunction(),
        QueryFullProcessImageNameW=NativeFunction(),
        WaitForSingleObject=NativeFunction(),
        CloseHandle=NativeFunction(),
    )
    monkeypatch.setattr(processes.ctypes, "WinDLL", lambda *_args, **_kwargs: kernel)
    monkeypatch.setattr(processes.ctypes, "get_last_error", lambda: error)

    with pytest.raises(UpdateError):
        processes.process_image(12345)
