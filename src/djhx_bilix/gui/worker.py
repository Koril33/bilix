"""Qt adapter for bounded operations in the shared, Qt-free task engine."""

from __future__ import annotations

import sys
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot

from djhx_bilix import __version__, auth
from djhx_bilix.bilibili.client import BilibiliClient
from djhx_bilix.config import load_settings
from djhx_bilix.errors import BilixError
from djhx_bilix.media import FFmpeg, find_ffmpeg
from djhx_bilix.operations import CancellationToken, OperationCancelled
from djhx_bilix.tasks import DownloadOptions, JobSpec, Session, run_batch, run_preview
from djhx_bilix.urls import normalize_url

EventSink = Callable[[dict[str, Any]], None]


def run_download(
    specs: tuple[JobSpec, ...], options: DownloadOptions, emit: EventSink, cancel: CancellationToken
) -> dict[str, int]:
    if options.dry_run:
        return run_preview(specs, options, emit, cancel)
    session = Session()
    return run_batch(session, session.begin(specs, options), emit, cancel)


def run_session(
    session: Session, batch_id: str, emit: EventSink, cancel: CancellationToken
) -> dict[str, int]:
    return run_batch(session, batch_id, emit, cancel)


def run_info(
    specs: tuple[JobSpec, ...], emit: EventSink, cancel: CancellationToken
) -> dict[str, int]:
    client = BilibiliClient(load_settings(), cancel=cancel)
    failures = 0
    for index, spec in enumerate(specs, 1):
        cancel.raise_if_cancelled()
        try:
            info = client.fetch(normalize_url(spec.source))
            cancel.raise_if_cancelled()
            emit(
                {
                    "type": "info",
                    "index": index - 1,
                    "spec": spec,
                    "metadata": info.public_dict(),
                }
            )
        except OperationCancelled:
            raise
        except BilixError as error:
            failures += 1
            emit({"type": "info", "index": index - 1, "spec": spec, "error": str(error)})
        except OSError:
            failures += 1
            emit({"type": "info", "index": index - 1, "spec": spec, "error": "文件或目录无法访问"})
    return {"failed": failures, "total": len(specs)}


def run_login(emit: EventSink, cancel: CancellationToken) -> None:
    auth.login(
        load_settings(),
        lambda _message: None,
        cancel=cancel,
        event=lambda event: emit({"type": "login", "state": event.state, "image": event.qr_image}),
    )


def run_status(_emit: EventSink, cancel: CancellationToken) -> dict[str, Any]:
    cancel.raise_if_cancelled()
    result = auth.status(BilibiliClient(load_settings(), cancel=cancel))
    cancel.raise_if_cancelled()
    return result


def run_doctor(_emit: EventSink, cancel: CancellationToken) -> str:
    settings = load_settings()
    cancel.raise_if_cancelled()
    executable = find_ffmpeg(settings.ffmpeg)
    version = FFmpeg(executable).version()
    cancel.raise_if_cancelled()
    return (
        f"BiliX {__version__}\nPython {sys.version.split()[0]}\n"
        f"FFmpeg：{executable}\n{version}\n配置目录：{settings.config_dir}"
    )


class OperationWorker(QObject):
    """Runs one bounded operation outside the Qt GUI thread."""

    event = Signal(object)
    done = Signal(object)

    def __init__(
        self,
        operation: Callable[[EventSink, CancellationToken], Any],
        cancel: CancellationToken,
    ) -> None:
        super().__init__()
        self.operation = operation
        self.cancel = cancel

    @Slot()
    def run(self) -> None:
        try:
            value = self.operation(self.event.emit, self.cancel)
        except OperationCancelled:
            self.done.emit({"state": "canceled"})
        except BilixError as error:
            self.done.emit({"state": "error", "message": str(error)})
        except (OSError, UnicodeError):
            self.done.emit({"state": "error", "message": "文件或目录无法访问，请检查路径和权限"})
        except Exception:
            # Third-party exceptions may include cookies or signed media URLs.
            self.done.emit({"state": "error", "message": "操作失败，请检查网络、设置或诊断信息"})
        else:
            self.done.emit({"state": "ok", "value": value})
