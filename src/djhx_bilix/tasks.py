"""Session-only task history, immutable attempts and serial batch execution.

No credentials, media URLs or Qt objects are retained in this model. A batch is
bounded at creation; callbacks run outside the model lock. Front ends consume
immutable snapshots and identify rows by opaque IDs, never row numbers.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from uuid import uuid4

from .bilibili.client import BilibiliClient
from .config import load_settings
from .errors import InputError, OperationCancelled, safe_error
from .feedback import TransferSample
from .models import CODECS, QUALITY_NAMES, DownloadPlan, VideoInfo, VideoTarget
from .operations import CancellationToken
from .planner import build_plan
from .service import discover, execute
from .urls import normalize_url

EventSink = Callable[[dict[str, Any]], None]
TERMINAL = frozenset({"completed", "skipped", "failed", "canceled"})
ACTIVE = (
    "queued",
    "loading",
    "downloading",
    "checking_video",
    "checking_audio",
    "muxing",
    "committing",
)


def new_id() -> str:
    return uuid4().hex


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

    def __post_init__(self) -> None:
        object.__setattr__(self, "save", self.save.expanduser().absolute())

    def description(self) -> str:
        return (
            f"{QUALITY_NAMES.get(self.quality, '自动')} / {self.codec or '自动编码'} / "
            f"{self.audio.upper()} · 严格 {'开' if self.strict else '关'} · "
            f"覆盖 {'开' if self.overwrite else '关'} · {self.save} · "
            f"FFmpeg {self.ffmpeg or '自动查找'}"
        )


@dataclass(frozen=True)
class SourceRequest:
    request_id: str
    batch_id: str
    spec: JobSpec
    options: DownloadOptions
    state: str = "queued"
    detail: str = ""
    error_code: str = ""
    action: str = ""
    origin_request_id: str | None = None


@dataclass(frozen=True)
class Identity:
    bvid: str
    cid: str
    episode_id: str

    def matches(self, info: VideoInfo) -> bool:
        return all(
            not expected or expected == actual
            for expected, actual in (
                (self.bvid, info.bvid),
                (self.cid, info.cid),
                (self.episode_id, info.episode_id),
            )
        )


@dataclass(frozen=True)
class Attempt:
    attempt_id: str
    batch_id: str
    number: int
    options: DownloadOptions
    state: str = "queued"
    sequence: int = 0
    detail: str = ""
    error_code: str = ""
    action: str = ""
    planned_output: str = ""
    output: str = ""
    resolved_ffmpeg: str = ""


@dataclass(frozen=True)
class Task:
    task_id: str
    request_id: str
    spec: JobSpec
    target_url: str
    label: str
    identity: Identity
    attempts: tuple[Attempt, ...]

    @property
    def latest(self) -> Attempt:
        return self.attempts[-1]


@dataclass(frozen=True)
class Batch:
    batch_id: str
    requests: tuple[str, ...] = ()
    tasks: tuple[str, ...] = ()
    finished: bool = False
    summary: tuple[tuple[str, int], ...] = ()


class Session:
    def __init__(self) -> None:
        self.tasks: dict[str, Task] = {}
        self.requests: dict[str, SourceRequest] = {}
        self.batches: dict[str, Batch] = {}
        self.active_batch: str | None = None
        self._lock = threading.RLock()

    def _begin(self) -> str:
        if self.active_batch is not None:
            raise InputError("请等待当前批次结束，或先取消")
        batch_id = new_id()
        self.batches[batch_id] = Batch(batch_id)
        self.active_batch = batch_id
        return batch_id

    def begin(self, specs: tuple[JobSpec, ...], options: DownloadOptions) -> str:
        if not specs:
            raise InputError("至少需要一个来源")
        normalized = tuple(JobSpec(normalize_url(s.source), s.page) for s in specs)
        with self._lock:
            batch_id = self._begin()
            ids = []
            for spec in normalized:
                request_id = new_id()
                self.requests[request_id] = SourceRequest(request_id, batch_id, spec, options)
                ids.append(request_id)
            self.batches[batch_id] = replace(self.batches[batch_id], requests=tuple(ids))
            return batch_id

    def retry(
        self,
        task_ids: tuple[str, ...],
        request_ids: tuple[str, ...] = (),
        options: DownloadOptions | None = None,
    ) -> str:
        with self._lock:
            selected = [self.tasks[i] for i in dict.fromkeys(task_ids)]
            sources = [self.requests[i] for i in dict.fromkeys(request_ids)]
            if not selected and not sources:
                raise InputError("请选择失败或取消的任务 / 来源")
            if any(t.latest.state not in {"failed", "canceled"} for t in selected):
                raise InputError("只能重试失败或取消的任务")
            if any(r.state not in {"failed", "canceled"} for r in sources):
                raise InputError("只能重新读取失败或取消的来源")
            batch_id = self._begin()
            for task in selected:
                attempt = Attempt(
                    new_id(), batch_id, task.latest.number + 1, options or task.latest.options
                )
                self.tasks[task.task_id] = replace(task, attempts=(*task.attempts, attempt))
            request_ids_new = []
            for source in sources:
                request_id = new_id()
                self.requests[request_id] = SourceRequest(
                    request_id,
                    batch_id,
                    source.spec,
                    options or source.options,
                    origin_request_id=source.request_id,
                )
                request_ids_new.append(request_id)
            self.batches[batch_id] = replace(
                self.batches[batch_id],
                requests=tuple(request_ids_new),
                tasks=tuple(t.task_id for t in selected),
            )
            return batch_id

    def source_state(
        self, request_id: str, state: str, emit: EventSink, error: Exception | None = None
    ) -> None:
        with self._lock:
            source = self.requests[request_id]
            if source.state in {"discovered", "failed", "canceled"}:
                return
            if state not in {"queued", "loading", "discovered", "failed", "canceled"}:
                raise ValueError("Illegal source state")
            if source.state == "loading" and state == "queued":
                raise ValueError("Source state cannot move backwards")
            detail, code, action = safe_error(error) if error else ("", "", "")
            source = replace(source, state=state, detail=detail, error_code=code, action=action)
            self.requests[request_id] = source
        emit({"type": "source", "request": source})

    def register(self, request_id: str, targets: tuple[VideoTarget, ...]) -> tuple[str, ...]:
        with self._lock:
            source = self.requests[request_id]
            ids = []
            for target in targets:
                task_id = new_id()
                # Explicit part metadata is supplied by discovery, never parsed from a label.
                spec = JobSpec(source.spec.source, str(target.page_number))
                self.tasks[task_id] = Task(
                    task_id,
                    request_id,
                    spec,
                    target.url,
                    target.label or target.url,
                    Identity(target.bvid, target.cid, target.episode_id),
                    (Attempt(new_id(), source.batch_id, 1, source.options),),
                )
                ids.append(task_id)
            batch = self.batches[source.batch_id]
            self.batches[source.batch_id] = replace(batch, tasks=(*batch.tasks, *ids))
            return tuple(ids)

    def event(
        self,
        task_id: str,
        emit: EventSink,
        *,
        state: str | None = None,
        kind: str = "task",
        **values: Any,
    ) -> bool:
        with self._lock:
            task = self.tasks[task_id]
            attempt = task.latest
            if attempt.state in TERMINAL:
                return False
            if state is not None and state not in TERMINAL:
                if state not in ACTIVE or not (
                    0 <= ACTIVE.index(state) - ACTIVE.index(attempt.state) <= 1
                ):
                    raise ValueError(f"Illegal task transition {attempt.state} -> {state}")
            fields = {
                k: v
                for k, v in values.items()
                if k
                in {"detail", "error_code", "action", "planned_output", "output", "resolved_ffmpeg"}
            }
            attempt = replace(
                attempt, **fields, state=state or attempt.state, sequence=attempt.sequence + 1
            )
            task = replace(task, attempts=(*task.attempts[:-1], attempt))
            self.tasks[task_id] = task
        emit({"type": kind, "task": task, "attempt": attempt, **values})
        return True

    def bind_identity(self, task_id: str, info: VideoInfo) -> None:
        with self._lock:
            task = self.tasks[task_id]
            self.tasks[task_id] = replace(
                task,
                identity=Identity(
                    task.identity.bvid or info.bvid,
                    task.identity.cid or info.cid,
                    task.identity.episode_id or info.episode_id,
                ),
            )

    def finish(self, batch_id: str) -> dict[str, int]:
        with self._lock:
            batch = self.batches[batch_id]
            if batch.finished:
                return dict(batch.summary)
            sources = [self.requests[i] for i in batch.requests]
            attempts = [
                a for i in batch.tasks for a in self.tasks[i].attempts if a.batch_id == batch_id
            ]
            if any(a.state not in TERMINAL for a in attempts) or any(
                r.state not in {"discovered", "failed", "canceled"} for r in sources
            ):
                raise ValueError("Cannot finish a batch with unfinished work")
            summary = {s: sum(a.state == s for a in attempts) for s in TERMINAL}
            summary.update(
                source_total=len(sources),
                source_failed=sum(r.state == "failed" for r in sources),
                source_canceled=sum(r.state == "canceled" for r in sources),
                tasks=len(attempts),
                planned=0,
                discovery_complete=int(all(r.state == "discovered" for r in sources)),
            )
            self.batches[batch_id] = replace(batch, finished=True, summary=tuple(summary.items()))
            self.active_batch = None
            return summary

    def clear(self, states: frozenset[str]) -> None:
        with self._lock:
            if self.active_batch:
                raise InputError("运行期间不能清理记录")
            # Keep historical batch summaries immutable. No filesystem operations here.
            self.tasks = {i: t for i, t in self.tasks.items() if t.latest.state not in states}
            referenced = {t.request_id for t in self.tasks.values()}
            self.requests = {
                i: r for i, r in self.requests.items() if r.state not in states or i in referenced
            }


def conflict(output: Path, overwrite: bool) -> str:
    if not output.exists():
        return "new"
    if not output.is_file():
        return "blocked"
    return "replace" if overwrite else "skip"


def plan_description(plan: DownloadPlan) -> str:
    return (
        f"{QUALITY_NAMES.get(plan.video.quality, plan.video.quality)} / "
        f"{CODECS.get(plan.video.codec, plan.video.codec)} / {plan.audio.audio_kind.upper()}"
    )


def summary_text(counts: dict[str, int]) -> str:
    unknown = "（发现未完成）" if not counts["discovery_complete"] else ""
    return (
        f"来源 {counts['source_total']} · 来源失败 {counts['source_failed']} · "
        f"来源取消 {counts['source_canceled']}；已发现任务 {counts['tasks']}{unknown}\n"
        f"计划 {counts['planned']} 项；完成 {counts['completed']} · 跳过 {counts['skipped']} · "
        f"失败 {counts['failed']} · 取消 {counts['canceled']}"
    )


def progress_sink(session: Session, task_id: str, emit: EventSink) -> Callable:
    counts: dict[str, tuple[int, int | None]] = {}
    samples: dict[str, TransferSample] = {}
    last_sent = 0.0
    lock = threading.Lock()

    def update(stream: str, completed: int, total: int | None) -> None:
        nonlocal last_sent
        with lock:
            if samples:
                return  # Structured feedback is authoritative; keep legacy adapters compatible.
            counts[stream] = completed, total
            now = time.monotonic()
            if completed != total and now - last_sent < 0.15:
                return
            last_sent = now
            snapshot = dict(counts)
        session.event(task_id, emit, kind="progress", streams=snapshot)

    def feedback(sample: TransferSample):
        nonlocal last_sent
        with lock:
            previous = samples.get(sample.stream)
            if previous and (sample.stream_attempt, sample.stream_sequence) <= (
                previous.stream_attempt,
                previous.stream_sequence,
            ):
                return
            samples[sample.stream] = sample
            counts[sample.stream] = (
                sample.completed_bytes,
                (
                    sample.total_bytes
                    or (sample.completed_bytes if sample.phase == "finished" else None)
                ),
            )
            important = (
                previous is None
                or previous.phase != sample.phase
                or previous.stream_attempt != sample.stream_attempt
                or previous.total_bytes != sample.total_bytes
            )
            if not important and sample.sampled_at - last_sent < 0.15:
                return
            last_sent = sample.sampled_at
            snapshot, latest = dict(counts), tuple(samples.values())
        session.event(task_id, emit, kind="progress", streams=snapshot, samples=latest)

    update.feedback = feedback
    return update


def run_batch(
    session: Session,
    batch_id: str,
    emit: EventSink,
    cancel: CancellationToken,
    *,
    client: BilibiliClient | None = None,
) -> dict[str, int]:
    batch = session.batches[batch_id]
    cached: dict[str, VideoInfo | None] = {}
    seen_paths: set[Path] = set()

    def process(task_ids):
        for task_id in task_ids:
            cancel.raise_if_cancelled()
            task = session.tasks[task_id]
            options = task.latest.options
            session.event(task_id, emit, state="loading")
            try:
                video = cached.get(task_id) or client.fetch(task.target_url)
                cancel.raise_if_cancelled()
                if not task.identity.matches(video):
                    raise InputError(
                        "来源选集身份已变化，请重新读取来源并创建新任务",
                        error_code="identity_changed",
                        action="请重新读取来源",
                    )
                session.bind_identity(task_id, video)
                plan = build_plan(
                    video,
                    options.save,
                    options.quality,
                    options.codec,
                    options.strict,
                    options.audio,
                )
                decision = conflict(plan.output, options.overwrite)
                duplicate = plan.output in seen_paths
                seen_paths.add(plan.output)
                session.event(
                    task_id,
                    emit,
                    kind="plan",
                    planned_output=str(plan.output),
                    title=video.title,
                    selection=plan_description(plan),
                    warnings=plan.warnings,
                    conflict=decision,
                    duplicate=duplicate,
                )
                if decision == "blocked":
                    raise InputError(
                        "输出路径已存在但不是普通文件",
                        error_code="filesystem",
                        action="请调整保存路径",
                    )
                result = execute(
                    plan,
                    options.ffmpeg,
                    options.overwrite,
                    progress_sink(session, task_id, emit),
                    cancel=cancel,
                    stage=lambda stage, tid=task_id: (
                        session.event(
                            tid,
                            emit,
                            state=stage.stage,
                            **({"resolved_ffmpeg": stage.ffmpeg} if stage.ffmpeg else {}),
                        )
                        if stage.stage not in TERMINAL
                        else None
                    ),
                )
                session.event(
                    task_id,
                    emit,
                    state="skipped" if result.skipped else "completed",
                    output=str(result.output),
                    detail="已存在，未校验" if result.skipped else "已校验并合并",
                )
            except OperationCancelled:
                raise
            except Exception as error:
                detail, code, action = safe_error(error)
                session.event(
                    task_id, emit, state="failed", detail=detail, error_code=code, action=action
                )

    try:
        client = client or BilibiliClient(load_settings(), cancel=cancel)
        for request_id in batch.requests:
            session.source_state(request_id, "queued", emit)
        for task_id in batch.tasks:
            session.event(task_id, emit)
        process(batch.tasks)
        for request_id in batch.requests:
            cancel.raise_if_cancelled()
            source = session.requests[request_id]
            session.source_state(request_id, "loading", emit)
            try:
                targets = discover(client, source.spec.source, source.spec.page, cancel=cancel)
                if not targets:
                    raise InputError("未找到可下载的选集")
                ids = session.register(request_id, targets)
                session.source_state(request_id, "discovered", emit)
                for task_id, target in zip(ids, targets, strict=True):
                    cached[task_id] = target.cached_info
                    session.event(task_id, emit)
                process(ids)
            except OperationCancelled:
                raise
            except Exception as error:
                session.source_state(request_id, "failed", emit, error)
    except (OperationCancelled, KeyboardInterrupt):
        cancel.cancel()
    except Exception as error:
        for request_id in batch.requests:
            session.source_state(request_id, "failed", emit, error)
        for task_id in session.batches[batch_id].tasks:
            detail, code, action = safe_error(error)
            session.event(
                task_id, emit, state="failed", detail=detail, error_code=code, action=action
            )
    finally:
        if cancel.cancelled():
            for request_id in batch.requests:
                session.source_state(request_id, "canceled", emit)
            for task_id in session.batches[batch_id].tasks:
                session.event(task_id, emit, state="canceled", detail="已取消")
    return session.finish(batch_id)


def run_preview(
    specs: tuple[JobSpec, ...],
    options: DownloadOptions,
    emit: EventSink,
    cancel: CancellationToken,
    *,
    client: BilibiliClient | None = None,
) -> dict[str, int]:
    """Read-only, independent from executable tasks and session history."""
    client = client or BilibiliClient(load_settings(), cancel=cancel)
    totals = dict(
        completed=0,
        skipped=0,
        failed=0,
        canceled=0,
        planned=0,
        source_total=len(specs),
        source_failed=0,
        source_canceled=0,
        tasks=0,
        discovery_complete=1,
    )
    paths: set[Path] = set()
    for index, spec in enumerate(specs):
        cancel.raise_if_cancelled()
        try:
            targets = discover(client, normalize_url(spec.source), spec.page, cancel=cancel)
        except OperationCancelled:
            raise
        except Exception as error:
            totals["source_failed"] += 1
            totals["discovery_complete"] = 0
            detail, code, action = safe_error(error)
            emit(
                dict(
                    type="preview",
                    source_index=index,
                    detail=detail,
                    error_code=code,
                    action=action,
                    conflict="blocked",
                )
            )
            continue
        totals["tasks"] += len(targets)
        for target in targets:
            cancel.raise_if_cancelled()
            try:
                info = target.cached_info or client.fetch(target.url)
                cancel.raise_if_cancelled()
                plan = build_plan(
                    info,
                    options.save,
                    options.quality,
                    options.codec,
                    options.strict,
                    options.audio,
                )
                decision = conflict(plan.output, options.overwrite)
                emit(
                    dict(
                        type="preview",
                        source_index=index,
                        label=target.label,
                        title=info.title,
                        output=str(plan.output),
                        selection=plan_description(plan),
                        warnings=plan.warnings,
                        conflict=decision,
                        duplicate=plan.output in paths,
                        detail="输出路径已存在但不是普通文件" if decision == "blocked" else "",
                        action="请调整保存目录" if decision == "blocked" else "",
                    )
                )
                paths.add(plan.output)
                totals["planned"] += 1
                if decision == "blocked":
                    totals["failed"] += 1
            except OperationCancelled:
                raise
            except Exception as error:
                totals["failed"] += 1
                detail, code, action = safe_error(error)
                emit(
                    dict(
                        type="preview",
                        source_index=index,
                        label=target.label,
                        detail=detail,
                        error_code=code,
                        action=action,
                        conflict="blocked",
                    )
                )
    return totals
