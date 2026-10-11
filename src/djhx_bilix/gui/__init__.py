"""Optional desktop front end; importing this package does not require Qt."""

from __future__ import annotations

import os
import sys


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] in {"--apply-update", "--install-deb"}:
        from djhx_bilix.updater.apply import dispatch

        return dispatch(arguments)
    try:
        from .app import main as run_app
    except ModuleNotFoundError as error:
        if error.name and error.name.startswith("PySide6"):
            message = "BiliX GUI 需要 PySide6。请安装 djhx-bilix[gui]，或使用 GUI 独立安装包。"
            if sys.stderr is not None:
                print(message, file=sys.stderr)
            elif os.name == "nt":
                # Windows gui-scripts have no attached console. Keep the error
                # actionable even if the optional Qt dependency is missing.
                import ctypes

                ctypes.windll.user32.MessageBoxW(None, message, "BiliX", 0x10)
            return 2
        raise
    return run_app(argv)


__all__ = ["main"]
