"""Background operations shared by the Qt window and its interaction tests.

Only immutable options and plain event dictionaries cross the Qt thread boundary.
The download, account and configuration implementations remain in the shared core.
"""

from __future__ import annotations

import json
import re
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot

from djhx_bilix import __version__, auth
from djhx_bilix.bilibili.client import BilibiliClient
from djhx_bilix.config import load_settings
from djhx_bilix.errors import BilixError
from djhx_bilix.media import FFmpeg, find_ffmpeg
from djhx_bilix.models import CODECS, QUALITY_NAMES
from djhx_bilix.operations import CancellationToken, OperationCancelled
from djhx_bilix.planner import build_plan
from djhx_bilix.service import discover, execute
from djhx_bilix.urls import normalize_url

EventSink = Callable[[dict[str, Any]], None]


@dataclass(frozen=True)
class JobSpec:
    source: str
    page: str | None = None


@dataclass(frozen=True)
class DownloadOptions:
    quality: int | None
    codec: str | None
    audio: str
    save: Path
    strict: bool
    overwrite: bool
    ffmpeg: str | None
    dry_run: bool = False


def _retry_spec(spec: JobSpec, target: Any) -> JobSpec:
    """Retry the failed part only, even when the original URL selected all parts."""
    part = re.match(r"P(\d+)(?:\s|$)", target.label)
    if part:
        return JobSpec(spec.source, part.group(1))
    return JobSpec(target.url, None)


def _progress_sink(emit: EventSink, key: tuple[int, int]) -> Callable[[str, int, int | None], None]:
    # transfer calls progress concurrently for audio and video. Throttle UI
    # traffic without losing the final byte count of either stream.
    counts: dict[str, tuple[int, int | None]] = {}
    last_sent = 0.0
    lock = threading.Lock()

    def update(stream: str, completed: int, total: int | None) -> None:
        nonlocal last_sent
        with lock:
            counts[stream] = completed, total
            now = time.monotonic()
            if completed != total and now - last_sent < 0.15:
                return
            last_sent = now
            snapshot = dict(counts)
        emit({"type": "progress", "key": key, "streams": snapshot})

    return update


def run_download(
    specs: tuple[JobSpec, ...],
    options: DownloadOptions,
    emit: EventSink,
    cancel: CancellationToken,
) -> dict[str, int]:
    settings = load_settings()
    client = BilibiliClient(settings, cancel=cancel)
    totals = {"completed": 0, "skipped": 0, "failed": 0, "planned": 0}
    for source_index, spec in enumerate(specs):
        cancel.raise_if_cancelled()
        source_key = (source_index, 0)
        emit({"type": "state", "key": source_key, "state": "loading", "detail": "读取视频信息"})
        try:
            targets = discover(client, normalize_url(spec.source), spec.page, cancel=cancel)
        except OperationCancelled:
            raise
        except BilixError as error:
            totals["failed"] += 1
            emit({"type": "state", "key": source_key, "state": "failed", "detail": str(error)})
            continue
        except OSError:
            totals["failed"] += 1
            emit(
                {
                    "type": "state",
                    "key": source_key,
                    "state": "failed",
                    "detail": "文件或目录无法访问，请检查路径和权限",
                }
            )
            continue

        if not targets:
            totals["failed"] += 1
            emit(
                {
                    "type": "state",
                    "key": source_key,
                    "state": "failed",
                    "detail": "未找到可下载的选集",
                }
            )
            continue

        # Register every discovered part before starting the first transfer.
        # Cancellation then leaves a visible, retryable row for each pending part.
        for target_index, target in enumerate(targets):
            key = (source_index, target_index)
            emit(
                {
                    "type": "target",
                    "key": key,
                    "label": target.label or target.url,
                    "retry": _retry_spec(spec, target),
                }
            )
            emit({"type": "state", "key": key, "state": "queued", "detail": "等待下载"})

        for target_index, target in enumerate(targets):
            cancel.raise_if_cancelled()
            key = (source_index, target_index)
            emit({"type": "state", "key": key, "state": "loading", "detail": "读取可用画质"})
            try:
                video = target.cached_info or client.fetch(target.url)
                cancel.raise_if_cancelled()
                plan = build_plan(
                    video,
                    options.save,
                    options.quality,
                    options.codec,
                    options.strict,
                    options.audio,
                )
                selection = (
                    f"{QUALITY_NAMES.get(plan.video.quality, plan.video.quality)} / "
                    f"{CODECS.get(plan.video.codec, plan.video.codec)} / "
                    f"{plan.audio.audio_kind.upper()}"
                )
                emit(
                    {
                        "type": "plan",
                        "key": key,
                        "title": f"{video.title} · {target.label}" if target.label else video.title,
                        "output": str(plan.output),
                        "selection": selection,
                        "warnings": plan.warnings,
                    }
                )
                if options.dry_run:
                    totals["planned"] += 1
                    emit({"type": "state", "key": key, "state": "planned", "detail": "计划已生成"})
                    continue
                result = execute(
                    plan,
                    options.ffmpeg or settings.ffmpeg,
                    options.overwrite,
                    _progress_sink(emit, key),
                    cancel=cancel,
                    stage=lambda stage, key=key: emit(
                        {"type": "stage", "key": key, "stage": stage.stage, "detail": stage.detail}
                    ),
                )
                state = "skipped" if result.skipped else "completed"
                totals[state] += 1
                emit(
                    {
                        "type": "state",
                        "key": key,
                        "state": state,
                        "detail": "文件已存在" if result.skipped else "已完成校验与合并",
                        "output": str(result.output),
                    }
                )
            except OperationCancelled:
                emit({"type": "state", "key": key, "state": "canceled", "detail": "已取消"})
                raise
            except BilixError as error:
                totals["failed"] += 1
                emit({"type": "state", "key": key, "state": "failed", "detail": str(error)})
            except OSError:
                totals["failed"] += 1
                emit(
                    {
                        "type": "state",
                        "key": key,
                        "state": "failed",
                        "detail": "文件或目录无法访问，请检查路径和权限",
                    }
                )
    return totals


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
                    "text": f"[{index}] {spec.source}\n"
                    + json.dumps(info.public_dict(), ensure_ascii=False, indent=2),
                }
            )
        except OperationCancelled:
            raise
        except BilixError as error:
            failures += 1
            emit({"type": "info", "text": f"[{index}] {spec.source}\n失败：{error}"})
        except OSError:
            failures += 1
            emit({"type": "info", "text": f"[{index}] {spec.source}\n失败：文件或目录无法访问"})
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
