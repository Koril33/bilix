"""Observe frozen BiliX startup and idle RSS on a visible dedicated X11 desktop.

The first-frame metric is an external upper bound: 50 ms observation plus Xlib
capture cost, not an in-process Qt Paint timestamp or monitor scanout. Client
pixels must be nonblank and agree with the visible desktop crop. By default each phase
launches five fresh processes per version, alternating version order; counts
can be configured independently for the first and repeated sequences. OS caches
are not flushed, so first-sequence is not an OS-cold measurement.
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.util
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


class Attributes(ctypes.Structure):
    _fields_ = [
        *[(name, ctypes.c_int) for name in ("x", "y", "width", "height", "border", "depth")],
        ("visual", ctypes.c_void_p),
        ("root", ctypes.c_ulong),
        *[
            (name, ctypes.c_int)
            for name in ("window_class", "bit_gravity", "win_gravity", "backing_store")
        ],
        ("backing_planes", ctypes.c_ulong),
        ("backing_pixel", ctypes.c_ulong),
        ("save_under", ctypes.c_int),
        ("colormap", ctypes.c_ulong),
        ("map_installed", ctypes.c_int),
        ("map_state", ctypes.c_int),
        ("all_event_masks", ctypes.c_long),
        ("your_event_mask", ctypes.c_long),
        ("do_not_propagate_mask", ctypes.c_long),
        ("override_redirect", ctypes.c_int),
        ("screen", ctypes.c_void_p),
    ]


class Image(ctypes.Structure):
    # Xlib ABI: https://www.x.org/releases/current/doc/libX11/libX11/libX11.html
    _fields_ = [
        *[(name, ctypes.c_int) for name in ("width", "height", "xoffset", "format")],
        ("data", ctypes.c_void_p),
        *[
            (name, ctypes.c_int)
            for name in (
                "byte_order",
                "bitmap_unit",
                "bitmap_bit_order",
                "bitmap_pad",
                "depth",
                "bytes_per_line",
                "bits_per_pixel",
            )
        ],
        ("red_mask", ctypes.c_ulong),
        ("green_mask", ctypes.c_ulong),
        ("blue_mask", ctypes.c_ulong),
        ("obdata", ctypes.c_void_p),
        ("functions", ctypes.c_void_p * 6),
    ]


class MessageData(ctypes.Union):
    _fields_ = [
        ("bytes", ctypes.c_char * 20),
        ("shorts", ctypes.c_short * 10),
        ("longs", ctypes.c_long * 5),
    ]


class ClientMessage(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_int),
        ("serial", ctypes.c_ulong),
        ("send_event", ctypes.c_int),
        ("display", ctypes.c_void_p),
        ("window", ctypes.c_ulong),
        ("message_type", ctypes.c_ulong),
        ("format", ctypes.c_int),
        ("data", MessageData),
    ]


class Event(ctypes.Union):
    _fields_ = [("client", ClientMessage), ("padding", ctypes.c_long * 24)]


@dataclass(frozen=True)
class Frame:
    width: int
    height: int
    stride: int
    pixel_bytes: int
    rgb_offsets: tuple[int, int, int]
    data: bytes

    def rgb(self, x: int, y: int) -> tuple[int, int, int]:
        start = y * self.stride + x * self.pixel_bytes
        return tuple(self.data[start + offset] for offset in self.rgb_offsets)

    def colors(self, threshold: int = 16) -> int:
        colors = set()
        for index in range(0, self.width * self.height, 31):
            y, x = divmod(index, self.width)
            colors.add(self.rgb(x, y))
            if len(colors) >= threshold:
                break
        return len(colors)

    def agrees(self, desktop: Frame, x: int, y: int) -> float:
        same = total = 0
        for index in range(0, self.width * self.height, 67):
            row, column = divmod(index, self.width)
            same += self.rgb(column, row) == desktop.rgb(x + column, y + row)
            total += 1
        return same / total

    def save(self, path: Path, png) -> None:
        def rows():
            for y in range(self.height):
                start = y * self.stride
                source = self.data[start : start + self.width * self.pixel_bytes]
                row = bytearray(self.width * 3)
                for channel, offset in enumerate(self.rgb_offsets):
                    row[channel::3] = source[offset :: self.pixel_bytes]
                yield row

        with path.open("wb") as stream:
            png.Writer(self.width, self.height, greyscale=False).write(stream, rows())


class Desktop:
    def __init__(self):
        library = ctypes.util.find_library("X11")
        if not library:
            raise RuntimeError("libX11 is required for native observation")
        self.x = ctypes.CDLL(library)
        pointer, integer, window = ctypes.c_void_p, ctypes.c_int, ctypes.c_ulong
        self.x.XOpenDisplay.argtypes = [ctypes.c_char_p]
        self.x.XOpenDisplay.restype = pointer
        self.x.XDefaultRootWindow.argtypes = [pointer]
        self.x.XDefaultRootWindow.restype = window
        self.x.XInternAtom.argtypes = [pointer, ctypes.c_char_p, integer]
        self.x.XInternAtom.restype = window
        self.x.XGetWindowProperty.argtypes = [
            pointer,
            window,
            window,
            ctypes.c_long,
            ctypes.c_long,
            integer,
            window,
            ctypes.POINTER(window),
            ctypes.POINTER(integer),
            ctypes.POINTER(window),
            ctypes.POINTER(window),
            ctypes.POINTER(pointer),
        ]
        self.x.XGetWindowAttributes.argtypes = [pointer, window, ctypes.POINTER(Attributes)]
        self.x.XTranslateCoordinates.argtypes = [
            pointer,
            window,
            window,
            integer,
            integer,
            ctypes.POINTER(integer),
            ctypes.POINTER(integer),
            ctypes.POINTER(window),
        ]
        self.x.XGetImage.argtypes = [
            pointer,
            window,
            integer,
            integer,
            ctypes.c_uint,
            ctypes.c_uint,
            window,
            integer,
        ]
        self.x.XGetImage.restype = ctypes.POINTER(Image)
        self.x.XFree.argtypes = [pointer]
        self.x.XSync.argtypes = [pointer, integer]
        self.x.XFlush.argtypes = [pointer]
        self.x.XSendEvent.argtypes = [
            pointer,
            window,
            integer,
            ctypes.c_long,
            ctypes.POINTER(Event),
        ]
        self.x.XCloseDisplay.argtypes = [pointer]
        self.errors = []
        handler_type = ctypes.CFUNCTYPE(integer, pointer, pointer)

        @handler_type
        def protocol_error(display, error):
            self.errors.append(True)
            return 0

        self._error_handler = protocol_error
        self.x.XSetErrorHandler.argtypes = [handler_type]
        self.x.XSetErrorHandler(self._error_handler)
        self.display = self.x.XOpenDisplay(os.environ["DISPLAY"].encode())
        if not self.display:
            raise RuntimeError("Cannot open the signed-in X11 desktop; check XAUTHORITY")
        self.root = self.x.XDefaultRootWindow(self.display)
        self.atoms = {}

    def atom(self, name):
        if name not in self.atoms:
            self.atoms[name] = self.x.XInternAtom(self.display, name.encode(), 0)
        return self.atoms[name]

    def property(self, window, name):
        kind, count, after = ctypes.c_ulong(), ctypes.c_ulong(), ctypes.c_ulong()
        format_ = ctypes.c_int()
        data = ctypes.c_void_p()
        result = self.x.XGetWindowProperty(
            self.display,
            window,
            self.atom(name),
            0,
            65536,
            0,
            0,
            ctypes.byref(kind),
            ctypes.byref(format_),
            ctypes.byref(count),
            ctypes.byref(after),
            ctypes.byref(data),
        )
        try:
            if result or not data or after.value:
                return None
            if format_.value == 32:
                values = ctypes.cast(data, ctypes.POINTER(ctypes.c_ulong))
                return [int(values[i]) for i in range(count.value)]
            if format_.value == 8:
                return ctypes.string_at(data, count.value).decode("utf-8", errors="replace")
            return None
        finally:
            if data:
                self.x.XFree(data)

    def attributes(self, window):
        attributes = Attributes()
        if not self.x.XGetWindowAttributes(self.display, window, ctypes.byref(attributes)):
            return None
        return attributes

    def fingerprint(self):
        root = self.attributes(self.root)
        if root is None:
            raise RuntimeError("The desktop root window disappeared")
        resources = self.property(self.root, "RESOURCE_MANAGER") or ""
        return {
            "size": [root.width, root.height],
            "depth": root.depth,
            "xft": [line for line in resources.splitlines() if line.lower().startswith("xft.")],
        }

    def windows(self, pids, version):
        active = self.property(self.root, "_NET_ACTIVE_WINDOW") or []
        for window in self.property(self.root, "_NET_CLIENT_LIST") or []:
            pid = self.property(window, "_NET_WM_PID") or []
            title = self.property(window, "_NET_WM_NAME") or self.property(window, "WM_NAME") or ""
            if pid and pid[0] in pids and title.startswith(f"BiliX {version}") and window in active:
                attributes = self.attributes(window)
                if attributes is not None and attributes.map_state == 2:
                    yield window, pid[0], title, attributes

    def capture(self, window, width, height):
        self.errors.clear()
        self.x.XSync(self.display, 0)
        image = self.x.XGetImage(self.display, window, 0, 0, width, height, ctypes.c_ulong(-1), 2)
        if not image:
            return None
        try:
            value = image.contents
            if (value.red_mask, value.green_mask, value.blue_mask) != (0xFF0000, 0xFF00, 0xFF):
                raise RuntimeError("The benchmark requires a TrueColor RGB desktop")
            if value.bits_per_pixel not in (24, 32):
                raise RuntimeError(f"Unsupported X11 pixel width: {value.bits_per_pixel}")
            pixel_bytes = value.bits_per_pixel // 8
            offsets = (
                (2, 1, 0)
                if value.byte_order == 0
                else ((0, 1, 2) if pixel_bytes == 3 else (1, 2, 3))
            )
            return Frame(
                value.width,
                value.height,
                value.bytes_per_line,
                pixel_bytes,
                offsets,
                ctypes.string_at(value.data, value.bytes_per_line * value.height),
            )
        finally:
            # XDestroyImage is also a macro; invoke the image's documented destructor.
            destroy = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.POINTER(Image))(
                image.contents.functions[1]
            )
            destroy(image)

    def first_frame(self, pids, version):
        for window, pid, title, attributes in self.windows(pids, version):
            if attributes.width < 300 or attributes.height < 200:
                continue
            x, y, child = ctypes.c_int(), ctypes.c_int(), ctypes.c_ulong()
            if not self.x.XTranslateCoordinates(
                self.display,
                window,
                self.root,
                0,
                0,
                ctypes.byref(x),
                ctypes.byref(y),
                ctypes.byref(child),
            ):
                continue
            root = self.attributes(self.root)
            if root is None or min(x.value, y.value) < 0:
                continue
            if x.value + attributes.width > root.width or y.value + attributes.height > root.height:
                continue
            client = self.capture(window, attributes.width, attributes.height)
            if client is None or client.colors() < 16:
                continue
            desktop = self.capture(self.root, root.width, root.height)
            if desktop is None or desktop.colors() < 16:
                continue
            agreement = client.agrees(desktop, x.value, y.value)
            if agreement < 0.9:
                continue
            return (
                {
                    "window": window,
                    "pid": pid,
                    "title": title,
                    "client_size": [client.width, client.height],
                    "client_position": [x.value, y.value],
                    "minimum_sampled_colors": 16,
                    "desktop_rgb_agreement": agreement,
                    "mapped": True,
                    "active": True,
                },
                client,
                desktop,
            )
        return None

    def close_owned(self, window, pids):
        pid = self.property(window, "_NET_WM_PID") or []
        if not pid or pid[0] not in pids:
            return
        event = Event()
        event.client = ClientMessage(
            type=33,
            send_event=1,
            display=self.display,
            window=window,
            message_type=self.atom("WM_PROTOCOLS"),
            format=32,
        )
        event.client.data.longs[0] = self.atom("WM_DELETE_WINDOW")
        self.x.XSendEvent(self.display, window, 0, 0, ctypes.byref(event))
        self.x.XFlush(self.display)

    def close(self):
        self.x.XCloseDisplay(self.display)


def require_desktop(psutil):
    import pwd

    marker = Path("/etc/bilix-validation-target").read_text().strip()
    if (
        marker
        not in {
            f"target={name}"
            for name in (
                "ubuntu2204",
                "ubuntu2204clean",
                "ubuntu2404",
                "debian12",
                "debian13",
            )
        }
        or pwd.getpwuid(os.geteuid()).pw_name != "vagrant"
    ):
        raise RuntimeError("Dedicated Linux validation VM and signed-in vagrant user required")
    display = os.environ.get("DISPLAY", "")
    if os.environ.get("XDG_SESSION_TYPE") != "x11" or not re.fullmatch(r":\d+(?:\.\d+)?", display):
        raise RuntimeError(
            "A local visible X11 session is required; headless/offscreen is rejected"
        )
    active_tty = Path("/sys/class/tty/tty0/active").read_text().strip()
    vt = "vt" + active_tty.removeprefix("tty")
    number = display.split(".")[0]
    for process in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            info = process.info
            command = info["cmdline"] or []
            if info["name"] in {"Xorg", "X"} and number in command and vt in command:
                return {
                    "marker": marker,
                    "display": display,
                    "active_tty": active_tty,
                    "xorg_pid": info["pid"],
                    "xorg_arguments": command,
                }
        except psutil.Error:
            pass
    raise RuntimeError(
        "DISPLAY must belong to Xorg on the currently visible VT; Xvfb/Xephyr rejected"
    )


def executable(path):
    path = path.expanduser().resolve()
    if not path.is_file() or not os.access(path, os.X_OK):
        raise RuntimeError(f"Frozen executable is unavailable: {path}")
    with path.open("rb") as stream:
        if stream.read(5) != b"\x7fELF\x02":
            raise RuntimeError(f"Pass the actual frozen ELF binary, not a launcher: {path}")
    return path, hashlib.file_digest(path.open("rb"), "sha256").hexdigest()


def owned_tree(parent, known, psutil):
    try:
        for process in [parent, *parent.children(recursive=True)]:
            known[process.pid] = process
    except psutil.Error:
        pass
    return [process for process in known.values() if process.is_running()]


def memory_sample(processes, started, psutil):
    before = time.perf_counter()
    values = {}
    for process in processes:
        try:
            values[process.pid] = process.memory_info().rss
        except psutil.Error:
            pass
    return {
        "seconds": before - started,
        "rss": sum(values.values()),
        "pids": sorted(values),
        "rss_by_pid": values,
        "collection_ms": (time.perf_counter() - before) * 1000,
    }


def summarize(records):
    result = []
    for phase in ("first-sequence", "repeat-sequence"):
        for version in ("1.7.0", "1.7.1"):
            selected = [r for r in records if r["round"] == phase and r["version"] == version]
            frames = [r["frame"]["observed_ms"] for r in selected]
            idle = [r["idle_rss_median"] for r in selected]
            result.append(
                {
                    "round": phase,
                    "version": version,
                    "samples": len(selected),
                    "frame_ms": {
                        "median": statistics.median(frames),
                        "min": min(frames),
                        "max": max(frames),
                    },
                    "idle_rss_median_bytes": statistics.median(idle),
                }
            )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old-binary", type=Path, required=True, help="Published 1.7.0 frozen ELF")
    parser.add_argument("--new-binary", type=Path, required=True, help="Final 1.7.1 frozen ELF")
    parser.add_argument(
        "--output", type=Path, required=True, help="New directory below /home/vagrant"
    )
    parser.add_argument("--samples", type=int, default=5, help="Samples per version per phase")
    parser.add_argument(
        "--first-samples", type=int, help="Override first-sequence samples per version"
    )
    parser.add_argument(
        "--repeat-samples", type=int, help="Override repeat-sequence samples per version"
    )
    parser.add_argument("--idle-seconds", type=float, default=15)
    parser.add_argument("--settle-seconds", type=float, default=5)
    parser.add_argument("--startup-timeout", type=float, default=90)
    args = parser.parse_args()
    first_samples = args.first_samples if args.first_samples is not None else args.samples
    repeat_samples = args.repeat_samples if args.repeat_samples is not None else args.samples
    if not all(1 <= n <= 10 for n in (args.samples, first_samples, repeat_samples)) or not (
        1 <= args.idle_seconds <= 60
    ):
        parser.error("Samples must be 1..10 and idle time 1..60 seconds")
    if not 0 <= args.settle_seconds <= 30 or not 1 <= args.startup_timeout <= 180:
        parser.error("Settle time must be 0..30 and startup timeout 1..180 seconds")
    if sys.platform != "linux" or platform.machine() != "x86_64" or os.geteuid() == 0:
        raise RuntimeError("Run as the signed-in user in the dedicated Linux amd64 VM")
    import png
    import psutil

    session = require_desktop(psutil)
    binaries = {"1.7.0": executable(args.old_binary), "1.7.1": executable(args.new_binary)}
    output = args.output.expanduser().resolve()
    if not output.is_relative_to(Path("/home/vagrant")):
        raise RuntimeError("Output must stay below the dedicated user's /home/vagrant")
    desktop = Desktop()
    try:
        fingerprint = desktop.fingerprint()
        output.mkdir(parents=True, exist_ok=False)
        report = {
            "schema_version": 1,
            "status": "running",
            "started_utc": datetime.now(UTC).isoformat(),
            "platform": platform.platform(),
            "python": platform.python_version(),
            "dependencies": {
                name: importlib.metadata.version(name) for name in ("psutil", "pypng")
            },
            "session": session,
            "desktop": fingerprint,
            "records": [],
            "scope": "External launch-to-first nonblank mapped/active client pixels agreeing with "
            "visible root capture; upper bound includes 50ms polling and capture overhead; "
            "100ms same-sweep process-tree RSS; fresh isolated profile each launch; "
            "OS caches not flushed; saved frames require visual review",
            "plan": {
                "first_samples_per_version": first_samples,
                "repeat_samples_per_version": repeat_samples,
                "expected_records": 2 * (first_samples + repeat_samples),
                "idle_seconds": args.idle_seconds,
                "settle_seconds": args.settle_seconds,
                "frame_poll_ms": 50,
                "memory_poll_ms": 100,
                "default_five_per_phase": first_samples == repeat_samples == 5,
            },
        }

        def write_report():
            temporary = output / "result.tmp"
            temporary.write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            temporary.replace(output / "result.json")

        write_report()
        try:
            for phase_index, phase in enumerate(("first-sequence", "repeat-sequence")):
                phase_samples = first_samples if phase_index == 0 else repeat_samples
                for sample in range(1, phase_samples + 1):
                    order = ("1.7.0", "1.7.1") if (sample + phase_index) % 2 else ("1.7.1", "1.7.0")
                    for version in order:
                        if desktop.fingerprint() != fingerprint:
                            raise RuntimeError(
                                "Desktop dimensions/depth/Xft resources changed during comparison"
                            )
                        binary, digest = binaries[version]
                        label = f"{version}-{phase}-{sample}"
                        profile = output / (label + "-profile")
                        env = os.environ.copy()
                        for key in (
                            "PYTHONPATH",
                            "PYTHONHOME",
                            "LD_LIBRARY_PATH",
                            "LD_PRELOAD",
                            "BILIX_FFMPEG",
                            "QT_PLUGIN_PATH",
                            "QT_QPA_PLATFORM_PLUGIN_PATH",
                            "QT_SCALE_FACTOR",
                            "QT_SCREEN_SCALE_FACTORS",
                            "QT_FONT_DPI",
                            "QT_DEVICE_PIXEL_RATIO",
                            "QT_AUTO_SCREEN_SCALE_FACTOR",
                            "QT_ENABLE_HIGHDPI_SCALING",
                        ):
                            env.pop(key, None)
                        env.update(
                            QT_QPA_PLATFORM="xcb",
                            BILIX_CONFIG_DIR=str(profile),
                            BILIX_DOWNLOAD_DIR=str(output / (label + "-downloads")),
                        )
                        record = {
                            "version": version,
                            "round": phase,
                            "sample": sample,
                            "binary": str(binary),
                            "sha256": digest,
                            "status": "running",
                            "memory": [],
                            "frame": None,
                        }
                        known, child, frames = {}, None, None
                        started = time.perf_counter()
                        next_memory = next_frame = started
                        observed = None
                        try:
                            with (output / (label + ".log")).open("wb") as log:
                                child = subprocess.Popen(
                                    [str(binary)],
                                    cwd=binary.parent,
                                    env=env,
                                    stdin=subprocess.DEVNULL,
                                    stdout=log,
                                    stderr=subprocess.STDOUT,
                                    start_new_session=True,
                                )
                                parent = psutil.Process(child.pid)
                                known[parent.pid] = parent
                                while True:
                                    now = time.perf_counter()
                                    live = owned_tree(parent, known, psutil)
                                    if child.poll() is not None or not live:
                                        raise RuntimeError(
                                            f"Frozen process exited early: {child.poll()}"
                                        )
                                    if now >= next_memory:
                                        measurement = memory_sample(live, started, psutil)
                                        if not measurement["pids"]:
                                            raise RuntimeError(
                                                "No live owned processes for the RSS sample"
                                            )
                                        record["memory"].append(measurement)
                                        next_memory = time.perf_counter() + 0.1
                                    if observed is None and now >= next_frame:
                                        captured = desktop.first_frame(
                                            {p.pid for p in live}, version
                                        )
                                        if captured:
                                            observed = time.perf_counter()
                                            info, client, screen = captured
                                            info["observed_ms"] = (observed - started) * 1000
                                            record["frame"] = info
                                            frames = client, screen
                                        next_frame = time.perf_counter() + 0.05
                                    if observed is None and now - started > args.startup_timeout:
                                        raise RuntimeError(
                                            "No visible painted version window before timeout"
                                        )
                                    if (
                                        observed is not None
                                        and now
                                        >= observed + args.settle_seconds + args.idle_seconds
                                    ):
                                        idle_start = observed - started + args.settle_seconds
                                        samples = [
                                            m
                                            for m in record["memory"]
                                            if m["seconds"] >= idle_start
                                        ]
                                        values = [m["rss"] for m in samples]
                                        if len(values) < args.idle_seconds * 5:
                                            raise RuntimeError(
                                                "Idle sampling coverage below 50% of the 100ms plan"
                                            )
                                        intervals = [
                                            b["seconds"] - a["seconds"]
                                            for a, b in zip(samples, samples[1:])
                                        ]
                                        record.update(
                                            idle_rss_median=statistics.median(values),
                                            idle_rss_min=min(values),
                                            idle_rss_max=max(values),
                                            idle_sample_count=len(values),
                                            idle_sampling_span_s=samples[-1]["seconds"]
                                            - samples[0]["seconds"],
                                            memory_interval_median_ms=statistics.median(intervals)
                                            * 1000,
                                            memory_interval_max_ms=max(intervals) * 1000,
                                        )
                                        break
                                    time.sleep(0.005)
                                record["status"] = "passed"
                        except BaseException as error:
                            record.update(status="failed", error=f"{type(error).__name__}: {error}")
                            raise
                        finally:
                            processes = list(known.values())
                            if record["frame"]:
                                desktop.close_owned(record["frame"]["window"], set(known))
                            _, alive = psutil.wait_procs(processes, timeout=3)
                            for process in alive:
                                try:
                                    process.terminate()
                                except psutil.Error:
                                    pass
                            _, alive = psutil.wait_procs(alive, timeout=3)
                            for process in alive:
                                try:
                                    process.kill()
                                except psutil.Error:
                                    pass
                            if child is not None:
                                child.wait(timeout=10)
                            report["records"].append(record)
                            write_report()
                        if frames:
                            frames[0].save(output / (label + "-client.png"), png)
                            frames[1].save(output / (label + "-desktop.png"), png)
                        print(
                            f"PASS {label}: {record['frame']['observed_ms']:.1f} ms; "
                            f"idle RSS {record['idle_rss_median'] / 1048576:.1f} MiB",
                            flush=True,
                        )
            report.update(
                status="passed",
                summary=summarize(report["records"]),
                finished_utc=datetime.now(UTC).isoformat(),
            )
        except BaseException as error:
            report.update(
                status="failed",
                error=f"{type(error).__name__}: {error}",
                finished_utc=datetime.now(UTC).isoformat(),
            )
            raise
        finally:
            write_report()
    finally:
        desktop.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
