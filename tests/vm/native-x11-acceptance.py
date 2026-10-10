"""Real X11/IBus desktop acceptance at Xft DPI 96, 144 and 192.

Run as vagrant after native-desktop-setup.sh, a visible XFCE login, an installed
candidate deb and the offline /home/vagrant test runtime. Uses production source
widgets; this is not a frozen-program startup benchmark. Thousand-task data and
progress are synthetic and make no network requests. Evidence is kept separately
from release artifacts. The maintainer controls VM power and display geometry.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import struct
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VM_HOME = Path("/home/vagrant")
PYTHON = VM_HOME / "bilix-work/.venv/bin/python"
TARGETS = {
    "ubuntu2204": ("ubuntu", "22.04"),
    "ubuntu2204clean": ("ubuntu", "22.04"),
    "ubuntu2404": ("ubuntu", "24.04"),
    "debian12": ("debian", "12"),
    "debian13": ("debian", "13"),
}
SCALE_ENV = (
    "QT_SCALE_FACTOR",
    "QT_SCREEN_SCALE_FACTORS",
    "QT_FONT_DPI",
    "QT_AUTO_SCREEN_SCALE_FACTOR",
    "QT_ENABLE_HIGHDPI_SCALING",
    "QT_USE_PHYSICAL_DPI",
    "GDK_SCALE",
    "GDK_DPI_SCALE",
)


def run(*command: str, timeout=15, input=None, check=True) -> subprocess.CompletedProcess:
    return subprocess.run(
        command, input=input, capture_output=True, text=True, timeout=timeout, check=check
    )


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def guard() -> str:
    if sys.platform != "linux" or Path.home() != VM_HOME or os.getuid() == 0:
        raise RuntimeError("Run as the dedicated VM's vagrant user")
    marker = Path("/etc/bilix-validation-target").read_text().strip()
    target = marker.removeprefix("target=")
    if marker != "target=" + target or target not in TARGETS:
        raise RuntimeError("Unsupported dedicated VM marker")
    release = dict(
        line.split("=", 1)
        for line in Path("/etc/os-release").read_text().splitlines()
        if "=" in line and not line.startswith("#")
    )
    identity = tuple(release[key].strip('"') for key in ("ID", "VERSION_ID"))
    if identity != TARGETS[target]:
        raise RuntimeError(f"VM marker/OS mismatch: {target}, {identity}")
    if any(os.environ.get(name) for name in SCALE_ENV):
        raise RuntimeError("Remove environment scaling overrides; actual Xft DPI is required")
    if os.environ.get("QT_QPA_PLATFORM", "xcb") != "xcb" or os.environ.get("WAYLAND_DISPLAY"):
        raise RuntimeError("This acceptance requires a visible Xorg session, not another backend")
    for binary in (
        "xdotool",
        "xclip",
        "xrdb",
        "xrandr",
        "xprop",
        "xwininfo",
        "ibus",
        "ibus-daemon",
    ):
        if shutil.which(binary) is None:
            raise RuntimeError(f"Install the native desktop prerequisite: {binary}")
    if not PYTHON.is_file():
        raise RuntimeError("Prepare the offline /home/vagrant test runtime first")
    return target


def check_png(path: Path) -> None:
    with path.open("rb") as stream:
        header = stream.read(24)
    assert header[:8] == b"\x89PNG\r\n\x1a\n", path
    width, height = struct.unpack(">II", header[16:24])
    assert width > 100 and height > 100 and path.stat().st_size > 1000, path


class Controller:
    def __init__(self, directory: Path, evidence: Path, window: str | None = None):
        self.directory = directory
        self.evidence = evidence
        self.window = window

    def command(self, action: str, timeout=30, **values) -> dict:
        request = {"id": uuid.uuid4().hex, "action": action, **values}
        write_json(self.directory / "command.json", request)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            time.sleep(0.1)
            try:
                result = read_json(self.directory / "response.json")
            except (OSError, ValueError):
                continue
            if result.get("id") == request["id"]:
                assert result.get("status") == "passed", result
                return result
        raise TimeoutError(f"Probe action did not complete: {action}")

    def key(self, *keys: str) -> None:
        run("xdotool", "key", "--clearmodifiers", "--delay", "100", *keys)
        time.sleep(0.15)

    def mark(self, label: str, result: dict) -> dict:
        for prefix, suffix in (("desktop-", "desktop"), ("action-", "window")):
            source = self.directory / f"{prefix}{result['id']}.png"
            target = self.evidence / f"{label}-{suffix}.png"
            check_png(source)
            shutil.copy2(source, target)
        result["evidence"] = [f"{label}-desktop.png", f"{label}-window.png"]
        write_json(self.evidence / f"{label}.json", result)
        return result

    def snapshot(self, label: str) -> dict:
        return self.mark(label, self.command("snapshot"))

    def tab_to(self, label: str, text: str, *, limit=80) -> dict:
        trace = []
        for _ in range(limit):
            result = self.command("snapshot")
            snapshot = result["snapshot"]
            trace.append(
                {
                    key: snapshot[key]
                    for key in ("focus", "focus_text", "outer_scroll", "key_events")
                }
            )
            if snapshot["focus_text"] == text:
                result["focus_trace"] = trace
                return self.mark(label, result)
            self.key("Tab")
        raise AssertionError(f"Keyboard could not reach {text}: {trace}")


def fit(snapshot: dict, window: str) -> dict:
    # XFCE/Qt can report an unscaled workarea origin alongside scaled dimensions.
    # Compare the native frame and EWMH workarea entirely in physical X11 pixels.
    root_properties = run("xprop", "-root", "_NET_CURRENT_DESKTOP", "_NET_WORKAREA").stdout
    values = dict(
        (line.partition("(")[0], line.partition("=")[2].strip())
        for line in root_properties.splitlines()
        if "=" in line
    )
    desktop = int(values["_NET_CURRENT_DESKTOP"])
    workareas = [int(part.strip()) for part in values["_NET_WORKAREA"].split(",")]
    assert len(workareas) % 4 == 0 and len(workareas) >= (desktop + 1) * 4, root_properties
    ax, ay, aw, ah = workareas[desktop * 4 : (desktop + 1) * 4]
    geometry = run("xdotool", "getwindowgeometry", "--shell", window).stdout
    dimensions = dict(line.split("=", 1) for line in geometry.splitlines() if "=" in line)
    window_info = run("xwininfo", "-id", window).stdout
    native_client = {}
    for field in ("Absolute upper-left X", "Absolute upper-left Y", "Width", "Height"):
        match = re.search(rf"^\s*{re.escape(field)}:\s*(-?\d+)\s*$", window_info, re.M)
        assert match, window_info
        native_client[field] = int(match[1])
    extent_property = run("xprop", "-id", window, "_NET_FRAME_EXTENTS").stdout
    extents = [int(part.strip()) for part in extent_property.partition("=")[2].split(",")]
    assert len(extents) == 4 and all(value >= 0 for value in extents), extent_property
    left, right, top, bottom = extents
    # Older xdotool releases add the client-relative origin twice; xwininfo's
    # absolute origin is authoritative across both old and new distributions.
    x = native_client["Absolute upper-left X"] - left
    y = native_client["Absolute upper-left Y"] - top
    width = native_client["Width"] + left + right
    height = native_client["Height"] + top + bottom
    record = {
        "coordinate_space": "physical X11 pixels",
        "window": window,
        "root_properties": root_properties,
        "client_geometry": native_client,
        "xwininfo": window_info,
        "xdotool_geometry_diagnostic": dimensions,
        "frame_extents_property": extent_property,
        "frame": [x, y, width, height],
        "workarea": [ax, ay, aw, ah],
        "qt_frame": snapshot["frame"],
        "qt_available_rect": snapshot["available_rect"],
        "device_pixel_ratio": snapshot["device_pixel_ratio"],
    }
    assert width <= aw and height <= ah, record
    assert ax <= x and ay <= y and x + width <= ax + aw and y + height <= ay + ah, record
    return record


def start_ibus(ibus_socket: Path, record: dict) -> None:
    address = f"unix:path={ibus_socket}"
    run("ibus-daemon", "--daemonize", "--replace", "--xim", f"--address={address}")
    time.sleep(2)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if not ibus_socket.is_socket():
            time.sleep(0.25)
            continue
        engines = run("ibus", "list-engine", timeout=5, check=False)
        matching = [line for line in engines.stdout.splitlines() if "libpinyin" in line]
        if engines.returncode == 0 and matching:
            selection = run("ibus", "engine", "libpinyin", timeout=5, check=False)
            actual = run("ibus", "engine", timeout=5, check=False)
            if actual.returncode == 0 and actual.stdout.strip() == "libpinyin":
                record["ibus_ready"] = {
                    "socket": str(ibus_socket),
                    "available_engine": matching,
                    "set_exit": selection.returncode,
                    "set_stderr": selection.stderr,
                    "selected_engine": actual.stdout.strip(),
                }
                return
            record["ibus_engine_failures"].append(
                {
                    "set_exit": selection.returncode,
                    "set_stderr": selection.stderr,
                    "query_exit": actual.returncode,
                    "query_stdout": actual.stdout,
                    "query_stderr": actual.stderr,
                }
            )
        else:
            record["ibus_engine_failures"].append(
                {"list_exit": engines.returncode, "list_stderr": engines.stderr}
            )
        time.sleep(0.25)
    raise RuntimeError("Private IBus socket/libpinyin engine did not become ready")


def exercise(control: Controller, ready: dict) -> dict:
    report = {"synthetic_queue": True, "queue_uses_network": False, "initial": ready}
    control.command("focus_url")
    control.key("ctrl+a", "BackSpace")
    run("xdotool", "type", "--clearmodifiers", "--delay", "120", "zhongwenshuru")
    time.sleep(0.4)
    composition = control.command("snapshot")
    if composition["snapshot"]["url_text"] == "zhongwenshuru":
        control.key("ctrl+a", "BackSpace")
        run("xdotool", "keydown", "Shift_L")
        time.sleep(0.15)
        run("xdotool", "keyup", "Shift_L")
        run("xdotool", "type", "--clearmodifiers", "--delay", "120", "zhongwenshuru")
        time.sleep(0.4)
        composition = control.command("snapshot")
        report["ime_mode_switched_with_shift"] = True
    if composition["snapshot"]["ime_preedits"] == 0:
        control.key("ctrl+a", "BackSpace", "ctrl+space")
        run("xdotool", "type", "--clearmodifiers", "--delay", "120", "zhongwenshuru")
        time.sleep(0.4)
        composition = control.command("snapshot")
        report["ime_triggered_with_control_space"] = True
    assert composition["snapshot"]["placeholder"] == "", composition
    assert composition["snapshot"]["ime_preedits"] > 0, composition
    report["ime_composition"] = control.mark("ime-composition", composition)
    control.key("space")
    commit = control.snapshot("ime-commit")
    assert commit["snapshot"]["url_text"] == "中文输入", commit
    assert commit["snapshot"]["ime_commits"] > ready["ime_commits"], commit
    report["ime_commit"] = commit
    control.key("Tab")
    forward = control.snapshot("tab-forward")
    assert forward["snapshot"]["focus"] == "QLineEdit", forward
    control.key("shift+Tab")
    backward = control.snapshot("tab-backward")
    assert backward["snapshot"]["focus"] == "UrlInput", backward
    assert backward["snapshot"]["url_text"] == "中文输入", backward
    report.update(tab_forward=forward, tab_backward=backward)

    destination = control.directory / "下载 中文 空格" / "验收 子目录"
    destination.mkdir()
    before = control.command("snapshot")["snapshot"]["output"]
    assert before != str(destination)
    control.command("directory")
    dialog = run(
        "xdotool", "search", "--sync", "--onlyvisible", "--name", "^选择保存目录$", timeout=10
    ).stdout.splitlines()
    assert dialog, "The real directory chooser did not become visible"
    report["directory_dialog"] = control.snapshot("directory-dialog")
    report["directory_window_id"] = dialog[-1]
    clipboard = subprocess.Popen(
        ["xclip", "-selection", "clipboard", "-in", "-quiet"],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        clipboard.stdin.write(str(destination))
        clipboard.stdin.close()
        control.key("ctrl+l", "ctrl+a", "ctrl+v", "Return")
        control.key("Return")
        directory = control.snapshot("directory-accepted")
        assert directory["snapshot"]["output"] == str(destination), directory
        assert (
            run(
                "xdotool", "search", "--onlyvisible", "--name", "^选择保存目录$", check=False
            ).returncode
            != 0
        ), "Directory chooser did not close after acceptance"
        report["directory"] = directory
    finally:
        if clipboard.poll() is None:
            clipboard.terminate()
        clipboard.wait(timeout=5)

    available_width, available_height = ready["available"]
    small_width = min(760, available_width - 16)
    small_height = min(590, available_height - 48)
    control.command("resize", width=small_width, height=small_height, advanced=False)
    control.command("focus_url")
    small = control.tab_to("small-keyboard-action", "下载")
    assert small["snapshot"]["size"] == [small_width, small_height], small
    assert not small["snapshot"]["advanced_visible"] and small["snapshot"]["outer_scroll"] == 0
    assert small["snapshot"]["key_events"] > backward["snapshot"]["key_events"]
    small["physical_fit"] = fit(small["snapshot"], control.window)
    write_json(control.evidence / "small-keyboard-action.json", small)
    report["small"] = small

    control.command(
        "resize",
        width=min(940, available_width - 16),
        height=min(760, available_height - 48),
        advanced=False,
    )
    queue = control.mark("queue", control.command("queue", count=1000))
    assert queue["snapshot"]["rows"] == queue["snapshot"]["visible_rows"] == 1000
    control.command("focus_table")
    control.key("ctrl+End")
    end = control.snapshot("ctrl-end")
    assert end["snapshot"]["selected_row"] == 999 and end["snapshot"]["table_scroll"] > 900
    assert end["snapshot"]["key_events"] > queue["snapshot"]["key_events"]
    assert control.window, "A native X11 window ID is required for pointer scrolling"
    geometry = run("xdotool", "getwindowgeometry", "--shell", control.window).stdout
    dimensions = dict(line.split("=", 1) for line in geometry.splitlines() if "=" in line)
    width, height = int(dimensions["WIDTH"]), int(dimensions["HEIGHT"])
    pointer_x, pointer_y = width - 8, height // 2
    run(
        "xdotool",
        "mousemove",
        "--window",
        control.window,
        str(pointer_x),
        str(pointer_y),
    )
    time.sleep(0.2)
    run("xdotool", "click", "--repeat", "15", "--delay", "100", "5")
    time.sleep(0.3)
    pointer_scroll = control.snapshot("native-outer-scroll")
    assert pointer_scroll["snapshot"]["outer_scroll"] == 0
    pointer_scroll["native_pointer"] = {
        "tool": "xdotool",
        "window": control.window,
        "physical_geometry": dimensions,
        "window_relative_physical_point": [pointer_x, pointer_y],
        "button": 5,
        "repeat": 15,
        "synthetic_queue": True,
    }
    write_json(control.evidence / "native-outer-scroll.json", pointer_scroll)
    control.command("focus_table")
    control.key("ctrl+Home", "ctrl+End")
    scroll = control.snapshot("last-task-visible")
    assert scroll["snapshot"]["focus"] == "QTreeView", scroll
    assert scroll["snapshot"]["selected_row"] == 999, scroll
    assert (
        scroll["snapshot"]["last_task_visible"] and "P1000" in scroll["snapshot"]["last_task_text"]
    )
    assert scroll["snapshot"]["table_visible_rows"] > 0 and scroll["snapshot"]["outer_scroll"] == 0
    time.sleep(3)
    progress = control.snapshot("progress")
    assert progress["snapshot"]["last_task_visible"], progress
    assert progress["snapshot"]["last_task_progress"], progress
    assert progress["snapshot"]["last_task_progress"] != queue["snapshot"]["last_task_progress"]
    assert "%" in progress["snapshot"]["last_task_progress"], progress
    empty = control.mark("filter-empty", control.command("filter", state="failed"))
    assert empty["snapshot"]["filter_state"] == "failed" and empty["snapshot"]["visible_rows"] == 0
    active = control.mark("filter-active", control.command("filter", state="active"))
    assert active["snapshot"]["visible_rows"] == 1000
    finish = control.mark("finish-queue", control.command("finish_queue"))
    assert finish["snapshot"]["task_states"] == {"failed": 1000}, finish
    assert finish["snapshot"]["visible_rows"] == 0, finish
    terminal = control.mark("filter-terminal", control.command("filter", state="failed"))
    assert terminal["snapshot"]["visible_rows"] == terminal["snapshot"]["rows"] == 1000
    control.command("focus_table")
    control.key("ctrl+Home", "ctrl+End")
    terminal_visible = control.snapshot("terminal-last-task")
    assert terminal_visible["snapshot"]["selected_row"] == 999
    assert terminal_visible["snapshot"]["last_task_visible"], terminal_visible
    report.update(
        queue=queue,
        ctrl_end=end,
        native_outer_scroll=pointer_scroll,
        scroll=scroll,
        progress=progress,
        empty_filter=empty,
        active_filter=active,
        finish=finish,
        terminal=terminal,
        terminal_visible=terminal_visible,
    )
    return report


def worker(args, target: str) -> None:
    args.output.mkdir(parents=False, exist_ok=False)
    run_directory = VM_HOME / f"bilix-native-x11-{target}-{args.dpi}-{uuid.uuid4().hex[:8]}"
    env = os.environ.copy()
    env.update(QT_QPA_PLATFORM="xcb", QT_IM_MODULE="ibus", XMODIFIERS="@im=ibus", LANG="C.UTF-8")
    ibus_socket = VM_HOME / f"bilix-native-ibus-{uuid.uuid4().hex}.sock"
    ibus_address = f"unix:path={ibus_socket}"
    os.environ["IBUS_ADDRESS"] = env["IBUS_ADDRESS"] = ibus_address
    record = {
        "schema_version": 1,
        "target": target,
        "status": "running",
        "xft_dpi": args.dpi,
        "synthetic_queue": True,
        "frozen_startup_benchmark": False,
        "started_at": datetime.now(UTC).isoformat(),
        "probe_directory": str(run_directory),
        "ibus_address": ibus_address,
        "ibus_engine_failures": [],
    }
    child = None
    try:
        identity_code = (
            "import djhx_bilix,importlib.metadata,json;from pathlib import Path;"
            "print(json.dumps({'source':djhx_bilix.__file__,'version':djhx_bilix.__version__,"
            "'installed':importlib.metadata.version('djhx-bilix')}))"
        )
        identity = json.loads(run(str(PYTHON), "-c", identity_code).stdout)
        assert identity["source"] == str(VM_HOME / "bilix-work/src/djhx_bilix/__init__.py")
        assert identity["version"] == identity["installed"], identity
        deb = run("dpkg-query", "-W", "-f=${Version}", "djhx-bilix-gui").stdout.strip()
        assert deb == identity["version"] + "-1", (deb, identity)
        product = VM_HOME / "bilix-work/src/djhx_bilix/gui/app.py"
        source_bytes = product.read_bytes().replace(b"\r\n", b"\n")
        checkout_bytes = (ROOT / "src/djhx_bilix/gui/app.py").read_bytes().replace(b"\r\n", b"\n")
        assert source_bytes == checkout_bytes, "Refresh offline GUI source from the final checkout"
        record.update(
            runtime_identity=identity,
            installed_deb=deb,
            gui_source_sha256=hashlib.sha256(source_bytes).hexdigest(),
        )
        run("xrdb", "-merge", input=f"Xft.dpi: {args.dpi}\n")
        resources = run("xrdb", "-query").stdout
        assert re.search(rf"^Xft\.dpi:\s*{args.dpi}\s*$", resources, re.M), resources
        record["xresources"] = resources
        start_ibus(ibus_socket, record)
        with (args.output / "probe.log").open("w", encoding="utf-8") as log:
            child = subprocess.Popen(
                [
                    str(PYTHON),
                    str(ROOT / "scripts/native_gui_probe.py"),
                    "--output",
                    str(run_directory),
                    "--seconds",
                    "600",
                ],
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                if (run_directory / "result.json").is_file():
                    break
                if child.poll() is not None:
                    raise RuntimeError(f"Production-window probe exited {child.returncode}")
                time.sleep(0.1)
            else:
                raise TimeoutError("Native first paint did not arrive")
            initial = read_json(run_directory / "result.json")
            assert initial["backend"] == "xcb" and initial["session"] == "x11", initial
            assert initial["version"] == identity["version"], initial
            windows = run(
                "xdotool", "search", "--onlyvisible", "--pid", str(child.pid), "--name", "^BiliX "
            ).stdout.splitlines()
            assert windows, "The native production window did not become visible"
            run("xdotool", "windowactivate", "--sync", windows[0])
            time.sleep(0.3)
            control = Controller(run_directory, args.output, windows[0])
            settled = control.snapshot("initial-visible")
            ready = settled["snapshot"]
            record["first_paint_ready"] = initial["ready"]
            assert ready["visible"] and ready["active"] and ready["exposed"], ready
            assert ready["device_pixel_ratio"] == args.dpi / 96, ready
            settled["physical_fit"] = fit(ready, windows[0])
            write_json(args.output / "initial-visible.json", settled)
            record["initial_physical_fit"] = settled["physical_fit"]
            assert ready["cjk_fonts"] and all(
                font["glyphs"] and all(glyph > 0 for glyph in font["glyphs"])
                for font in ready["cjk_fonts"]
            ), ready
            assert any("Noto" in font["family"] for font in ready["cjk_fonts"]), ready
            for filename in ("first-window.png", "first-desktop.png"):
                check_png(run_directory / filename)
                shutil.copy2(run_directory / filename, args.output / filename)
            record["checks"] = exercise(control, ready)
            control.command("close")
            assert child.wait(timeout=10) == 0
        record["version"] = initial["version"]
        record["status"] = "passed"
    except Exception as error:
        record["error"] = f"{type(error).__name__}: {error}"
        record["status"] = "failed"
        raise
    finally:
        if child and child.poll() is None:
            try:
                Controller(run_directory, args.output).command("close", timeout=3)
                child.wait(timeout=5)
            except (AssertionError, OSError, TimeoutError, subprocess.TimeoutExpired):
                child.terminate()
                child.wait(timeout=10)
        if (run_directory / "result.json").is_file():
            shutil.copy2(run_directory / "result.json", args.output / "probe-result.json")
        try:
            ibus_exit = run("ibus", "exit", timeout=5, check=False)
            record["ibus_exit"] = {
                "exit": ibus_exit.returncode,
                "stderr": ibus_exit.stderr,
            }
            ibus_socket.unlink(missing_ok=True)
        except (OSError, subprocess.TimeoutExpired) as error:
            record["ibus_cleanup_error"] = f"{type(error).__name__}: {error}"
        record["finished_at"] = datetime.now(UTC).isoformat()
        write_json(args.output / "acceptance.json", record)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--display", default=":0")
    parser.add_argument(
        "--dpi", type=int, choices=(96, 144, 192), help="One DPI; default is all three"
    )
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    target = guard()
    os.environ.update(
        DISPLAY=args.display,
        XAUTHORITY=str(VM_HOME / ".Xauthority"),
        XDG_SESSION_TYPE="x11",
        LANG="C.UTF-8",
    )
    xrandr = run("xrandr", "--current").stdout
    outputs = re.findall(r"^(\S+) connected", xrandr, re.M)
    assert outputs and all(
        name not in ("screen", "default") and not name.startswith("XWAYLAND") for name in outputs
    ), xrandr
    wm = run("xprop", "-root", "_NET_SUPPORTING_WM_CHECK", "_NET_WORKAREA").stdout
    assert "window id # 0x" in wm and "_NET_WORKAREA(CARDINAL)" in wm, wm
    if args.worker:
        assert args.dpi and args.output and os.environ.get("DBUS_SESSION_BUS_ADDRESS")
        worker(args, target)
        return
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    output = args.output or ROOT / "build/validation/native" / f"{target}-{stamp}"
    output = output.resolve()
    if not output.is_relative_to(ROOT / "build"):
        raise RuntimeError("Keep native evidence in this repository's ignored build directory")
    output.mkdir(parents=True, exist_ok=False)
    resources = run("xrdb", "-query").stdout
    # Qt prefers desktop Xsettings over xrdb. Use the logged-in XFCE bus,
    # rather than a worker's private IBus session, to set actual desktop DPI.
    sessions = run("pgrep", "-u", str(os.getuid()), "-x", "xfce4-session").stdout.split()
    assert len(sessions) == 1, sessions
    desktop_env = dict(
        part.split(b"=", 1)
        for part in Path(f"/proc/{sessions[0]}/environ").read_bytes().split(b"\0")
        if b"=" in part
    )
    desktop_bus = desktop_env[b"DBUS_SESSION_BUS_ADDRESS"].decode()

    def desktop_dpi(value=None):
        command = [
            "env",
            f"DBUS_SESSION_BUS_ADDRESS={desktop_bus}",
            "xfconf-query",
            "-c",
            "xsettings",
            "-p",
            "/Xft/DPI",
        ]
        if value is not None:
            command += ["-s", str(value)]
        return run(*command).stdout.strip()

    original_desktop_dpi = desktop_dpi()
    record = {
        "schema_version": 1,
        "target": target,
        "status": "running",
        "xrandr": xrandr,
        "window_manager": wm,
        "synthetic_queue": True,
        "frozen_startup_benchmark": False,
        "probe_sha256": hashlib.sha256(
            (ROOT / "scripts/native_gui_probe.py").read_bytes()
        ).hexdigest(),
        "cases": [],
    }
    try:
        for dpi in (args.dpi,) if args.dpi else (96, 144, 192):
            desktop_dpi(dpi)
            assert desktop_dpi() == str(dpi)
            time.sleep(0.5)
            case_output = output / f"dpi-{dpi}"
            child = subprocess.Popen(
                [
                    "dbus-run-session",
                    "--",
                    str(PYTHON),
                    str(Path(__file__).resolve()),
                    "--worker",
                    "--display",
                    args.display,
                    "--dpi",
                    str(dpi),
                    "--output",
                    str(case_output),
                ],
                start_new_session=True,
            )
            try:
                exit_code = child.wait(timeout=300)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGTERM)
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait(timeout=5)
                raise TimeoutError(f"Native DPI {dpi} worker timed out") from None
            case = read_json(case_output / "acceptance.json")
            record["cases"].append(case)
            assert exit_code == 0 and case["status"] == "passed", case
            print(f"Passed native X11 {target} DPI {dpi}; evidence {case_output}", flush=True)
        record["status"] = "passed"
    except Exception as error:
        record.update(status="failed", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        desktop_dpi(original_desktop_dpi)
        record["desktop_dpi_restored"] = desktop_dpi() == original_desktop_dpi
        assert record["desktop_dpi_restored"]
        restore = run("xrdb", "-load", input=resources, check=False)
        record["xresources_restored"] = restore.returncode == 0
        if not record["xresources_restored"]:
            record["status"] = "failed"
        write_json(output / "result.json", record)
    assert record["status"] == "passed", record


if __name__ == "__main__":
    main()
