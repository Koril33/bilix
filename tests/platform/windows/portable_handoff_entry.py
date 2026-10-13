"""Nuitka-only test entry for a real GUI -> portable helper -> production GUI update.

Compile this entry separately with the ordinary portable distribution identity.
Never use it as the release GUI entry. BILIX_HANDOFF_FIXTURE explicitly enables
an offline signed transaction; --apply-update, --updated and --smoke-test always
use the normal production entry without test hooks.
"""

from __future__ import annotations

import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from djhx_bilix.gui import main as normal_main


def main() -> int:
    arguments = list(sys.argv[1:])
    raw_fixture = os.environ.get("BILIX_HANDOFF_FIXTURE")
    if arguments or not raw_fixture:
        return normal_main(arguments)

    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QGuiApplication

    from djhx_bilix import __version__
    from djhx_bilix.gui import app, updates
    from djhx_bilix.updater.client import BUNDLE_NAMES, PreparedUpdate, atomic_json
    from djhx_bilix.updater.processes import current_processes
    from djhx_bilix.updater.protocol import UpdateCanceled, read_json, sha256, verify_bundle

    fixture = Path(raw_fixture).resolve()
    report = Path(
        os.environ.get("BILIX_HANDOFF_REPORT") or fixture / "handoff-harness.json"
    ).resolve()
    state = {
        "schema": 1,
        "scope": "offline-signed-portable-transaction",
        "public_network_discovery": False,
        "version": __version__,
        "pid": os.getpid(),
        "parent_pid": os.getppid(),
        "argv0": sys.argv[0],
        "sys_executable": sys.executable,
        "original_argv0": getattr(globals().get("__compiled__"), "original_argv0", None),
        "fixture": str(fixture),
    }

    def record(stage: str, **values) -> None:
        state.update(stage=stage, recorded_at=datetime.now(UTC).isoformat(), **values)
        atomic_json(report, state)

    original_window = app.MainWindow
    original_client = updates.UpdateClient
    try:
        if sys.platform != "win32":
            raise RuntimeError("The frozen handoff test requires Windows")
        blobs = {name: (fixture / name).read_bytes() for name in BUNDLE_NAMES}
        _, artifact = verify_bundle(blobs, "windows-x64-portable")
        prepared = PreparedUpdate(artifact, fixture)
        prepared.revalidate()
        record("verified", artifact_version=artifact.version, package_sha256=artifact.sha256)

        class FixtureClient:
            def __init__(self, identity, cancel):
                if identity.artifact_id != artifact.artifact_id:
                    raise RuntimeError("Test build must embed the portable distribution identity")
                self.cancel = cancel

            def prepare(self, progress):
                if self.cancel.is_set():
                    raise UpdateCanceled("Test fixture preparation cancelled")
                progress("checking", 0, 0)
                prepared.revalidate()
                progress("verifying", artifact.size, artifact.size)
                return prepared

        class HandoffWindow(original_window):
            def __init__(self):
                super().__init__()
                if self._update_identity is None:
                    raise RuntimeError("Frozen portable distribution identity is required")
                self._handoff_deadline = time.monotonic() + 45
                self._handoff_poll = QTimer(self)
                self._handoff_poll.setInterval(50)
                self._handoff_poll.timeout.connect(self._click_ready_update)
                self._handoff_poll.start()
                QTimer.singleShot(0, lambda: self._check_update(manual=True))

            def _click_ready_update(self):
                if time.monotonic() >= self._handoff_deadline:
                    self._handoff_poll.stop()
                    record("failed", error="Automatic fixture preparation did not become ready")
                    self._request_exit()
                    return
                if self._prepared_update is None or self._update_thread is not None:
                    return
                self._handoff_poll.stop()
                identity = self._update_identity
                record(
                    "clicked",
                    executable=str(identity.executable),
                    old_sha256=sha256(identity.executable),
                    processes=current_processes(identity.executable),
                    window_visible=self.isVisible(),
                    qt_platform=QGuiApplication.platformName(),
                )
                # Emit the same Qt button signal as the user's actual update click.
                self.update_button.click()

            def _update_done(self, result):
                if self._update_handoff:
                    if "error" in result or result.get("canceled"):
                        record("failed", error=result.get("error") or "Handoff cancelled")
                    else:
                        transaction = Path(result["value"])
                        request = read_json((transaction / "request.json").read_bytes())
                        record("accepted", transaction=str(transaction), request=request)
                super()._update_done(result)

        updates.UpdateClient = FixtureClient
        app.MainWindow = HandoffWindow
        return normal_main(arguments)
    except Exception as exc:
        record("failed", error=str(exc))
        if sys.stderr is not None:
            print(str(exc), file=sys.stderr)
        return 1
    finally:
        updates.UpdateClient = original_client
        app.MainWindow = original_window


if __name__ == "__main__":
    raise SystemExit(main())
