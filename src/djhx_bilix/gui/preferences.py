"""GUI-only typed preferences; business TOML parsing is deliberately independent."""

import os
from datetime import UTC, datetime
from pathlib import Path

from platformdirs import user_config_path
from PySide6.QtCore import QSettings

INTERFACE_KEYS = (
    "themeMode",
    "rememberMediaOptions",
    "showTransferFeedback",
    "advancedExpanded",
    "quality",
    "codec",
    "audio",
    "mode",
    "cover",
    "strict",
    "geometry",
    "column1",
    "column2",
    "defaultQuality",
    "defaultCodec",
)


class GuiPreferences:
    Status = QSettings.Status

    def __init__(self):
        directory = Path(
            os.environ.get("BILIX_CONFIG_DIR")
            or user_config_path(appname="djhx-bilix", appauthor="djhx")
        ).expanduser()
        self.path = directory / "gui.ini"
        self._open()

    def _open(self):
        self.store = QSettings(str(self.path), QSettings.Format.IniFormat)
        self.store.setAtomicSyncRequired(True)
        self.store.setFallbacksEnabled(False)
        self.store.beginGroup("v1")

    def value(self, key, default=None):
        return self.store.value(key, default)

    def read(self, key, default, kind):
        value = self.value(key, default)
        try:
            if kind is bool:
                if str(value).lower() in {"true", "1"}:
                    return True
                if str(value).lower() in {"false", "0"}:
                    return False
                return default
            return kind(value)
        except (TypeError, ValueError):
            return default

    def theme(self):
        value = self.value("themeMode", "system")
        return (
            value if isinstance(value, str) and value in {"system", "light", "dark"} else "system"
        )

    def setValue(self, key, value):
        self.store.setValue(key, value)

    def sync(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        except OSError:
            return False
        self.store.sync()
        return self.status() == self.Status.NoError

    def status(self):
        return self.store.status()

    def commit(self, values):
        previous = {key: self.value(key) for key in values}
        for key, value in values.items():
            self.setValue(key, value)
        if self.sync():
            return True
        # Roll back pending in-memory values as well as leaving the old atomic file intact.
        for key, value in previous.items():
            if value is None:
                self.store.remove(key)
            else:
                self.setValue(key, value)
        return False

    def reset_interface(self):
        preserved = {
            key: self.value(key)
            for key in ("minimizeToTray", "completionNotification", "automaticUpdates")
        }
        if self.status() == self.Status.FormatError:
            self.path.rename(
                self.path.with_name(f"gui.ini.corrupt-{datetime.now(UTC):%Y%m%d%H%M%S%f}.bak")
            )
            self._open()
        for key in INTERFACE_KEYS:
            self.store.remove(key)
        for key, value in preserved.items():
            if value is not None:
                self.setValue(key, value)
        return self.sync()
