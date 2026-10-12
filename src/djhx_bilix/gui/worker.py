"""Qt adapter for bounded operations in the shared, Qt-free task engine."""

from __future__ import annotations

import sys
import threading
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from urllib.parse import urlsplit

from PySide6.QtCore import QObject, Signal, Slot

from djhx_bilix import __version__, auth
from djhx_bilix.bilibili.client import BilibiliClient
from djhx_bilix.config import load_settings
from djhx_bilix.errors import BilixError
from djhx_bilix.media import FFmpeg, find_ffmpeg
from djhx_bilix.network import session as request_session
from djhx_bilix.operations import CancellationToken, OperationCancelled
from djhx_bilix.tasks import DownloadOptions, JobSpec, Session, run_batch, run_preview
from djhx_bilix.urls import normalize_url

EventSink = Callable[[dict[str, Any]], None]
_art_cache = OrderedDict()
_art_lock = threading.Lock()


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
    covers = []
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
            if info.cover:
                covers.append((index - 1, info.cover))
        except OperationCancelled:
            raise
        except BilixError as error:
            failures += 1
            emit({"type": "info", "index": index - 1, "spec": spec, "error": str(error)})
        except OSError:
            failures += 1
            emit({"type": "info", "index": index - 1, "spec": spec, "error": "文件或目录无法访问"})

    def artwork(item):
        index, url = item
        try:
            url = "https:" + url if url.startswith("//") else url
            parsed = urlsplit(url)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.port not in (None, 80 if parsed.scheme == "http" else 443)
            ):
                return
            if not any(
                parsed.hostname.endswith("." + domain) or parsed.hostname == domain
                for domain in ("hdslb.com", "bilibili.com")
            ):
                return
            # Bilibili metadata still advertises HTTP cover URLs. Upgrade only
            # the allowed CDN hosts before requesting artwork without cookies.
            url = parsed._replace(scheme="https", netloc=parsed.hostname).geturl()
            cancel.raise_if_cancelled()
            with _art_lock:
                cached = _art_cache.get(url)
                if cached is not None:
                    _art_cache.move_to_end(url)
            if cached is not None:
                emit({"type": "cover", "index": index, "data": cached})
                return
            with request_session() as connection:
                response = connection.get(url, timeout=8, stream=True, allow_redirects=False)
                try:
                    if response.status_code != 200:
                        return
                    data = bytearray()
                    for chunk in response.iter_content():
                        cancel.raise_if_cancelled()
                        data.extend(chunk)
                        if len(data) > 2 * 1024 * 1024:
                            return
                    data = bytes(data)
                    with _art_lock:
                        _art_cache[url] = data
                        while (
                            len(_art_cache) > 64
                            or sum(map(len, _art_cache.values())) > 8 * 1024 * 1024
                        ):
                            _art_cache.popitem(last=False)
                    emit({"type": "cover", "index": index, "data": data})
                finally:
                    response.close()
        except OperationCancelled:
            raise
        except Exception:
            return  # Artwork never makes a valid video fail.

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(artwork, covers))
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
        context: tuple | None = None,
    ) -> None:
        super().__init__()
        self.operation = operation
        self.cancel = cancel
        self.context = context

    def _emit_event(self, event):
        self.event.emit({**event, "_gui_context": self.context})

    def _emit_done(self, result):
        self.done.emit({**result, "_gui_context": self.context})

    @Slot()
    def run(self) -> None:
        try:
            value = self.operation(self._emit_event, self.cancel)
        except OperationCancelled:
            self._emit_done({"state": "canceled"})
        except BilixError as error:
            self._emit_done({"state": "error", "message": str(error)})
        except (OSError, UnicodeError):
            self._emit_done({"state": "error", "message": "文件或目录无法访问，请检查路径和权限"})
        except Exception:
            # Third-party exceptions may include cookies or signed media URLs.
            self._emit_done({"state": "error", "message": "操作失败，请检查网络、设置或诊断信息"})
        else:
            if self.cancel.cancelled() and self.context and self.context[0] != "download":
                self._emit_done({"state": "canceled"})
            else:
                self._emit_done({"state": "ok", "value": value})
