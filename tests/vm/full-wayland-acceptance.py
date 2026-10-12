"""Visible GNOME/KDE Wayland acceptance in a dedicated, logged-in test VM.

Widget actions use Qt; this does not claim native IME or compositor keyboard
injection. Frozen startup is checked separately through real Wayland messages.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--desktop", choices=("GNOME", "KDE"), required=True)
    args = parser.parse_args()
    assert os.getuid() != 0 and Path.home() == Path("/home/vagrant")
    target = Path("/etc/bilix-validation-target").read_text().strip()
    assert target in {
        "target=ubuntu2204",
        "target=debian13",
        "target=ubuntu2404",
        "target=debian12",
    }
    activation = subprocess.check_output(["systemctl", "--user", "show-environment"], text=True)
    allowed = {
        "DISPLAY",
        "WAYLAND_DISPLAY",
        "XAUTHORITY",
        "XDG_RUNTIME_DIR",
        "XDG_SESSION_TYPE",
        "XDG_CURRENT_DESKTOP",
        "DBUS_SESSION_BUS_ADDRESS",
    }
    for line in activation.splitlines():
        key, _, value = line.partition("=")
        if key in allowed:
            os.environ[key] = value
    assert os.environ.get("XDG_SESSION_TYPE") == "wayland"
    assert args.desktop in os.environ.get("XDG_CURRENT_DESKTOP", "")
    assert Path(os.environ["XDG_RUNTIME_DIR"], os.environ["WAYLAND_DISPLAY"]).is_socket()
    for key in ("QT_SCALE_FACTOR", "QT_SCREEN_SCALE_FACTORS", "QT_FONT_DPI"):
        assert not os.environ.get(key), f"Remove artificial scaling: {key}"
    os.environ["QT_QPA_PLATFORM"] = "wayland"
    output = (
        ROOT
        / "build/validation/native"
        / f"{target[7:]}-{args.desktop.lower()}-{uuid.uuid4().hex[:8]}"
    )
    output.mkdir(parents=True)
    local = Path.home() / f"bilix-wayland-{uuid.uuid4().hex[:8]}"
    local.mkdir()
    profile = local / "profile"
    profile.mkdir()
    (profile / "gui.ini").write_text("[v1]\nautomaticUpdates=false\nminimizeToTray=false\n")
    os.environ["BILIX_CONFIG_DIR"] = str(profile)
    os.environ["BILIX_DOWNLOAD_DIR"] = str(local / "下载 中文 空格")
    record = {
        "status": "running",
        "target": target,
        "desktop": args.desktop,
        "widget_inputs": "Qt actions; not physical keyboard/IME",
        "cases": [],
    }
    result = output / "result.json"
    try:
        compositor = "gnome-shell" if args.desktop == "GNOME" else "kwin_wayland"
        record["compositor"] = subprocess.check_output([compositor, "--version"], text=True).strip()
        record["installed_deb"] = subprocess.check_output(
            ["dpkg-query", "-W", "djhx-bilix-gui"], text=True
        ).strip()
        assert record["installed_deb"].endswith("1.7.8-1")
        binary = Path("/usr/lib/djhx-bilix-gui/bilix-gui")
        record["frozen_binary_sha256"] = hashlib.sha256(binary.read_bytes()).hexdigest()
        # A real compositor connection, assets, QR decoder and system FFmpeg.
        smoke = subprocess.run(
            [str(binary), "--smoke-test"], capture_output=True, text=True, timeout=90
        )
        assert smoke.returncode == 0, smoke.stderr
        record["frozen_smoke"] = smoke.stdout.strip()
        log = output / "frozen-wayland.log"
        with log.open("w") as stream:
            child = subprocess.Popen(
                [str(binary)],
                env={**os.environ, "WAYLAND_DEBUG": "1"},
                stdout=stream,
                stderr=subprocess.STDOUT,
            )
            try:
                time.sleep(5)
                assert child.poll() is None, "Frozen program exited before the window check"
                protocol = log.read_text()
                assert 'set_title("BiliX 1.7.8")' in protocol, protocol[-3000:]
                assert "xdg_toplevel" in protocol and ".configure(" in protocol
                record["frozen_wayland_window_configured"] = True
            finally:
                child.terminate()
                child.wait(timeout=15)

        from PySide6.QtCore import QTimer
        from PySide6.QtGui import QPalette
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication, QFileDialog, QLineEdit, QTreeWidgetItem

        from djhx_bilix.gui.app import MainWindow
        from djhx_bilix.models import Page, Stream, VideoInfo, VideoTarget
        from djhx_bilix.tasks import DownloadOptions, JobSpec

        application = QApplication([])
        window = MainWindow()
        record["qt_backend"] = application.platformName()
        assert record["qt_backend"] == "wayland"
        window.show()
        QTest.qWait(800)

        def capture(widget, label):
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                QTest.qWait(200)
                handle = widget.windowHandle()
                if widget.isVisible() and handle and handle.isExposed():
                    break
            else:
                raise AssertionError(f"Window not exposed: {label}; visible={widget.isVisible()}")
            available = widget.screen().availableGeometry()
            assert widget.width() <= available.width() and widget.height() <= available.height(), (
                label
            )
            image_path = output / (label + ".png")
            assert widget.grab().save(str(image_path))
            record["cases"].append(
                {
                    "label": label,
                    "size": [widget.width(), widget.height()],
                    "available": [available.width(), available.height()],
                    "dpr": widget.devicePixelRatioF(),
                    "image": image_path.name,
                    "exposed": True,
                }
            )

        scenario_errors = []

        def scenario():
            try:
                options = DownloadOptions(
                    None, None, "aac", output / "downloads", False, False, None
                )
                batch = window.session.begin((JobSpec("BV1j4411W7F7"),), options)
                source = window.session.batches[batch].requests[0]
                states = ("completed", "failed", "skipped", "canceled")
                targets = tuple(
                    VideoTarget(
                        f"https://www.bilibili.com/video/BV1j4411W7F7?p={i}",
                        label=f"合成状态 {state}",
                        page_number=i,
                        cid=str(i),
                    )
                    for i, state in enumerate(states, 1)
                )
                ids = window.session.register(source, targets)
                for task_id, state in zip(ids, states, strict=True):
                    for stage in ("queued", "loading", "downloading", state):
                        window.session.event(
                            task_id, window._on_event, state=stage, detail="合成界面验收原因"
                        )
                window.session.source_state(source, "discovered", window._on_event)
                window.session.finish(batch)
                window.jobs_view.expandAll()
                for mode in ("light", "dark", "system"):
                    window._theme_mode = mode
                    window._apply_appearance()
                    capture(window, f"tasks-{mode}")
                    record.setdefault("palettes", {})[mode] = {
                        role.name: window.palette().color(role).name()
                        for role in (
                            QPalette.ColorRole.Text,
                            QPalette.ColorRole.Base,
                            QPalette.ColorRole.PlaceholderText,
                        )
                    }
                url = "https://www.bilibili.com/video/BV1j4411W7F7"
                info = VideoInfo(
                    url,
                    "合成中文标题：选集与原生桌面",
                    "BV1j4411W7F7",
                    "100",
                    4,
                    tuple(Page(i, f"合成选集 {i}", f"{url}?p={i}", 4, str(i)) for i in range(1, 4)),
                    (Stream(32, 7, 200, ("https://cdn.example/video",)),),
                    (Stream(30280, 0, 192000, ("https://cdn.example/audio",)),),
                    owner="合成 UP 主",
                )
                window.urls_edit.setPlainText(url)
                window._parse_timer.stop()
                window._info_generation = window._input_generation
                window._parse_total = 1
                window.metadata_tree.addTopLevelItem(QTreeWidgetItem([url, ""]))
                window._on_event(dict(type="info", index=0, metadata=info.public_dict()))
                window._parse_complete = True
                window._open_draft(read_clipboard=False)
                capture(window._draft_dialog, "draft")
                window.part_range_edit.selectAll()
                QTest.keyClicks(window.part_range_edit, "1-2")
                QTest.qWait(300)
                assert window._inputs()[0].page == "1,2"
                capture(window._draft_dialog, "range")
                destination = local / "chooser"
                destination.mkdir(parents=True)
                chosen = []

                def accept_directory():
                    dialogs = [
                        w
                        for w in QApplication.topLevelWidgets()
                        if isinstance(w, QFileDialog) and w.isVisible()
                    ]
                    if (
                        not dialogs
                        or not dialogs[0].windowHandle()
                        or not dialogs[0].windowHandle().isExposed()
                    ):
                        (output / "chooser-waiting.json").write_text(
                            json.dumps({"destination": str(destination)})
                        )
                        return
                    assert len(dialogs) == 1
                    dialog = dialogs[0]
                    capture(dialog, "directory-chooser")
                    dialog.setDirectory(str(destination.parent))
                    editor = dialog.findChild(QLineEdit, "fileNameEdit")
                    assert editor is not None
                    editor.selectAll()
                    QTest.keyClicks(editor, str(destination))
                    QTest.qWait(200)
                    (output / "chooser-state.json").write_text(
                        json.dumps({"selected": dialog.selectedFiles(), "editor": editor.text()})
                    )
                    dialog.accept()
                    chosen.append(str(destination))

                QTimer.singleShot(400, accept_directory)
                QTimer.singleShot(180000, application.quit)
                window._choose_output()
                assert window.output_edit.text() == str(destination)
                record["directory_chooser"] = "Qt dialog" if chosen else "desktop native chooser"
                window._draft_dialog.hide()
                window._settings_dialog.show()
                window.settings_tabs.setCurrentIndex(1)
                capture(window._settings_dialog, "settings")
                window._settings_dialog.hide()
                window._open_node_details(window.history_model.tasks[ids[1]])
                capture(window._details_dialog, "failure-details")
                window._details_dialog.hide()
                window._open_shortcuts()
                capture(window._shortcuts_dialog, "shortcuts")
                window._shortcuts_dialog.hide()
                window.close()
                QTest.qWait(100)
                record["status"] = "passed"
            except Exception as error:
                scenario_errors.append(error)
            finally:
                application.quit()

        QTimer.singleShot(0, scenario)
        application.exec()
        if scenario_errors:
            raise scenario_errors[0]
    except Exception as error:
        record.update(status="failed", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        result.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
        print(f"{record['status']}: {result}", flush=True)


if __name__ == "__main__":
    main()
