"""Session-only task history, immutable attempts and serial batch execution.

No credentials, media URLs or Qt objects are retained in this model. A batch is
bounded at creation; callbacks run outside the model lock. Front ends consume
immutable snapshots and identify rows by opaque IDs, never row numbers.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from uuid import uuid4

from .bilibili.client import BilibiliClient
from .config import load_settings
from .errors import InputError, OperationCancelled, safe_error
from .feedback import TransferSample
from .models import (
    CODECS,
    OUTPUT_MODES,
    QUALITY_NAMES,
    DownloadPlan,
    OutputResult,
    VideoInfo,
    VideoTarget,
)
from .operations import CancellationToken, TaskControl
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
    "exporting",
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
    naming_template: str = "{title}"
    proxy: str | None = None
    concurrency: int = 1
    mode: str = "merged"
    cover: bool = False

    def __post_init__(self) -> None:
        if self.mode not in OUTPUT_MODES:
            raise InputError("未知下载方式")
        object.__setattr__(self, "save", self.save.expanduser().absolute())
        from .filenames import validate_template
        from .network import validate_proxy

        validate_template(self.naming_template)
        validate_proxy(self.proxy)
        if type(self.concurrency) is not int or not 1 <= self.concurrency <= 4:
            raise InputError("同时下载数必须为 1 到 4 的整数")

    def description(self) -> str:
        return (
            f"{QUALITY_NAMES.get(self.quality, '自动')} / {self.codec or '自动编码'} / "
            f"{self.audio.upper()} · 严格 {'开' if self.strict else '关'} · "
            f"覆盖 {'开' if self.overwrite else '关'} · {self.save} · "
            f"FFmpeg {self.ffmpeg or '自动查找'} · {OUTPUT_MODES[self.mode]}"
            + (" · 同时保存封面" if self.cover and self.mode != "cover" else "")
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
    planned_outputs: tuple[str, ...] = ()
    files: tuple[OutputResult, ...] = ()
    paused: bool = False


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
        self.pending: list[str] = []
        self.controls: dict[str, TaskControl] = {}
        self.schedule = TaskControl()
        self._path_locks: dict[Path, threading.Lock] = {}

    def _begin(self, enqueue: bool = False) -> str:
        if self.active_batch is not None and not enqueue:
            raise InputError("请等待当前批次结束，或先取消")
        batch_id = new_id()
        self.batches[batch_id] = Batch(batch_id)
        self.controls[batch_id] = TaskControl()
        if enqueue:
            self.pending.append(batch_id)
        else:
            self.active_batch = batch_id
        return batch_id

    def begin(self, specs: tuple[JobSpec, ...], options: DownloadOptions, *, enqueue=False) -> str:
        if not specs:
            raise InputError("至少需要一个来源")
        normalized = tuple(JobSpec(normalize_url(s.source), s.page) for s in specs)
        with self._lock:
            batch_id = self._begin(enqueue)
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
        *,
        enqueue: bool = False,
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
            batch_id = self._begin(enqueue)
            for task in selected:
                attempt = Attempt(
                    new_id(),
                    batch_id,
                    task.latest.number + 1,
                    options or task.latest.options,
                    files=(
                        tuple(
                            file
                            for file in task.latest.files
                            if file.state in {"completed", "skipped"}
                        )
                        if options is None
                        else ()
                    ),
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

    def next_batch(self) -> str | None:
        with self._lock:
            if self.active_batch or self.schedule.paused:
                return None
            while self.pending:
                batch_id = self.pending.pop(0)
                if not self.batches[batch_id].finished:
                    self.active_batch = batch_id
                    return batch_id
            return None

    def snapshot(self):
        with self._lock:
            return dict(self.tasks), dict(self.requests), dict(self.batches)

    def control(self, identity: str, parent: str, external=None) -> TaskControl:
        with self._lock:
            if identity not in self.controls:
                parents = [self.controls[parent]]
                if external is not None:
                    parents.append(external)
                self.controls[identity] = TaskControl(*parents)
            elif external is not None and external not in self.controls[identity].parents:
                self.controls[identity].parents += (external,)
            return self.controls[identity]

    def cancel_item(self, identity: str, emit: EventSink) -> None:
        with self._lock:
            task = self.tasks.get(identity)
            source = self.requests.get(identity)
            if task:
                self.control(task.latest.attempt_id, task.latest.batch_id).cancel()
                queued = task.latest.state == "queued"
            elif source:
                self.control(identity, source.batch_id).cancel()
                children = [t.task_id for t in self.tasks.values() if t.request_id == identity]
                queued = source.state == "queued"
            else:
                return
        if task and queued:
            self.event(identity, emit, state="canceled", detail="已取消")
        elif source:
            if queued:
                self.source_state(identity, "canceled", emit)
            for child in children:
                self.cancel_item(child, emit)

    def pause_item(self, identity: str, paused: bool, emit: EventSink) -> None:
        with self._lock:
            task = self.tasks.get(identity)
            if task is None or task.latest.state in TERMINAL:
                return
            control = self.control(task.latest.attempt_id, task.latest.batch_id)
            (control.pause if paused else control.resume)()
        self.event(identity, emit, paused=paused)

    def cancel_batch(self, batch_id: str, emit: EventSink) -> None:
        with self._lock:
            batch = self.batches[batch_id]
            self.controls[batch_id].cancel()
        for identity in (*batch.requests, *batch.tasks):
            self.cancel_item(identity, emit)

    def path_lock(self, output: Path):
        key = output.resolve()
        with self._lock:
            return self._path_locks.setdefault(key, threading.Lock())

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
            for target_index, target in enumerate(targets):
                task_id = new_id()
                options = source.options
                if target_index and options.cover and not target.episode_id:
                    options = replace(options, cover=False)
                # Explicit part metadata is supplied by discovery, never parsed from a label.
                spec = JobSpec(source.spec.source, str(target.page_number))
                self.tasks[task_id] = Task(
                    task_id,
                    request_id,
                    spec,
                    target.url,
                    target.label or target.url,
                    Identity(target.bvid, target.cid, target.episode_id),
                    (Attempt(new_id(), source.batch_id, 1, options),),
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
                export_transition = state == "exporting" and attempt.state in {
                    "loading",
                    "exporting",
                }
                if state not in ACTIVE or not (
                    export_transition or 0 <= ACTIVE.index(state) - ACTIVE.index(attempt.state) <= 1
                ):
                    raise ValueError(f"Illegal task transition {attempt.state} -> {state}")
            fields = {
                k: v
                for k, v in values.items()
                if k
                in {
                    "detail",
                    "error_code",
                    "action",
                    "planned_output",
                    "output",
                    "resolved_ffmpeg",
                    "paused",
                    "planned_outputs",
                    "files",
                }
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
            if self.active_batch == batch_id:
                self.active_batch = None
            return summary

    def clear(self, states: frozenset[str]) -> None:
        with self._lock:
            if self.active_batch or self.pending:
                raise InputError("运行期间不能清理记录")
            # Keep historical batch summaries immutable. No filesystem operations here.
            self.tasks = {i: t for i, t in self.tasks.items() if t.latest.state not in states}
            self._path_locks.clear()
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
    values = []
    if plan.video:
        values.extend(
            (
                QUALITY_NAMES.get(plan.video.quality, str(plan.video.quality)),
                CODECS.get(plan.video.codec, str(plan.video.codec)),
            )
        )
    if plan.audio:
        values.append(plan.audio.audio_kind.upper())
    if plan.mode != "merged":
        values.insert(0, OUTPUT_MODES[plan.mode])
    if any(f.kind == "cover" for f in plan.outputs) and plan.mode != "cover":
        values.append("同时保存封面")
    return " / ".join(values)


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
    external_cancel = cancel
    cancel = TaskControl(cancel, session.controls[batch_id])
    cached: dict[str, VideoInfo | None] = {}
    seen_paths: set[Path] = set()
    paths_guard = threading.Lock()
    workers = max(
        [session.requests[i].options.concurrency for i in batch.requests]
        + [session.tasks[i].latest.options.concurrency for i in batch.tasks]
        + [1]
    )

    def scoped_client(control, options):
        if client is not None and not isinstance(client, BilibiliClient):
            return client
        settings = replace(
            client.settings if isinstance(client, BilibiliClient) else load_settings(),
            proxy=options.proxy,
        )
        return BilibiliClient(settings, cancel=control)

    def process(task_ids):
        if workers > 1:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = [executor.submit(process_one, task_id) for task_id in task_ids]
                for future in futures:
                    future.result()
        else:
            for task_id in task_ids:
                process_one(task_id)

    def process_one(task_id):
        # Keep the legacy serial cancellation contract for unknown cancellation causes.
        task = session.tasks[task_id]
        if task.latest.state in TERMINAL:
            return
        control = session.control(task.latest.attempt_id, batch_id, cancel)
        while session.schedule.paused and not control.cancelled():
            control.wait(0.1)
        try:
            control.checkpoint()
        except OperationCancelled:
            session.event(task_id, emit, state="canceled", detail="已取消")
            if cancel.cancelled():
                raise
            return
        process_serial((task_id,), control)

    def process_serial(task_ids, control):
        for task_id in task_ids:
            control.checkpoint()
            task = session.tasks[task_id]
            options = task.latest.options
            session.event(task_id, emit, state="loading")
            try:
                target_client = scoped_client(control, options)
                video = cached.get(task_id) or (
                    target_client.fetch(task.target_url, metadata_only=True)
                    if options.mode == "cover" and isinstance(target_client, BilibiliClient)
                    else target_client.fetch(task.target_url)
                )
                control.checkpoint()
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
                    options.naming_template,
                    mode=options.mode,
                    cover=options.cover,
                )
                decision = conflict(plan.output, options.overwrite)
                with paths_guard:
                    duplicate = plan.output in seen_paths
                    seen_paths.add(plan.output)
                session.event(
                    task_id,
                    emit,
                    kind="plan",
                    planned_output=str(plan.output),
                    planned_outputs=tuple(str(f.output) for f in plan.outputs),
                    title=video.title,
                    selection=plan_description(plan),
                    warnings=plan.warnings,
                    conflict=decision,
                    duplicate=duplicate,
                )
                if decision == "blocked" and len(plan.outputs) == 1:
                    raise InputError(
                        "输出路径已存在但不是普通文件",
                        error_code="filesystem",
                        action="请调整保存路径",
                    )
                guards = []

                def record_file(value):
                    existing = session.tasks[task_id].latest.files
                    files = tuple(f for f in existing if f.kind != value.kind) + (value,)
                    successful = sum(f.state in {"completed", "skipped"} for f in files)
                    session.event(
                        task_id,
                        emit,
                        kind="artifact",
                        files=files,
                        output=str(
                            next(
                                (f.output for f in files if f.state in {"completed", "skipped"}), ""
                            )
                        ),
                        detail=f"已保存 {successful}/{len(plan.outputs)} 个文件",
                    )

                try:
                    for path in sorted(
                        {
                            f.output.with_suffix("") if f.kind == "cover" else f.output
                            for f in plan.outputs
                        }
                    ):
                        guard = session.path_lock(path)
                        while not guard.acquire(timeout=0.1):
                            control.checkpoint()
                        guards.append(guard)
                    control.checkpoint()
                    result = execute(
                        plan,
                        options.ffmpeg,
                        options.overwrite,
                        progress_sink(session, task_id, emit),
                        cancel=control,
                        proxy=options.proxy or "",
                        **(
                            {"artifact": record_file, "retained": task.latest.files}
                            if plan.mode != "merged" or len(plan.outputs) > 1
                            else {}
                        ),
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
                finally:
                    for guard in reversed(guards):
                        guard.release()
                failed = [f for f in result.files if f.state == "failed"]
                successful = sum(f.state in {"completed", "skipped"} for f in result.files)
                detail = "已存在，未校验" if result.skipped else "已校验并合并"
                if result.files:
                    detail = (
                        f"部分完成：{successful}/{len(result.files)} 个文件已保存；"
                        if failed and successful
                        else ""
                    ) + (
                        "；".join(f.detail for f in failed)
                        if failed
                        else f"已保存 {successful}/{len(result.files)} 个文件"
                    )
                session.event(
                    task_id,
                    emit,
                    state="failed" if failed else "skipped" if result.skipped else "completed",
                    output=str(result.output) if not failed or successful else "",
                    files=result.files,
                    detail=detail,
                    error_code="partial" if failed and successful else "download" if failed else "",
                    action="重试失败文件" if failed else "",
                )
            except OperationCancelled:
                if cancel.cancelled() or not control.cancelled():
                    raise
                session.event(task_id, emit, state="canceled", detail="已取消")
            except Exception as error:
                detail, code, action = safe_error(error)
                session.event(
                    task_id, emit, state="failed", detail=detail, error_code=code, action=action
                )

    try:
        for request_id in batch.requests:
            session.source_state(request_id, "queued", emit)
        for task_id in batch.tasks:
            session.event(task_id, emit)
        if workers == 1:
            process(batch.tasks)
        collected = list(batch.tasks)
        for request_id in batch.requests:
            cancel.raise_if_cancelled()
            source = session.requests[request_id]
            if source.state == "canceled":
                continue
            source_control = session.control(request_id, batch_id, cancel)
            session.source_state(request_id, "loading", emit)
            try:
                source_control.checkpoint()
                targets = discover(
                    scoped_client(source_control, source.options),
                    source.spec.source,
                    source.spec.page,
                    cancel=source_control,
                    **({"cover_only": True} if source.options.mode == "cover" else {}),
                )
                source_control.checkpoint()
                if not targets:
                    raise InputError("未找到可下载的选集")
                ids = session.register(request_id, targets)
                session.source_state(request_id, "discovered", emit)
                for task_id, target in zip(ids, targets, strict=True):
                    cached[task_id] = target.cached_info
                    session.event(task_id, emit)
                if workers == 1:
                    process(ids)
                else:
                    collected.extend(ids)
            except OperationCancelled:
                if cancel.cancelled() or not source_control.cancelled():
                    raise
                session.source_state(request_id, "canceled", emit)
            except Exception as error:
                session.source_state(request_id, "failed", emit, error)
        if workers > 1:
            process(collected)
    except (OperationCancelled, KeyboardInterrupt):
        cancel.cancel()
        external_cancel.cancel()
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
    client = client or BilibiliClient(replace(load_settings(), proxy=options.proxy), cancel=cancel)
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
            targets = discover(
                client,
                normalize_url(spec.source),
                spec.page,
                cancel=cancel,
                **({"cover_only": True} if options.mode == "cover" else {}),
            )
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
        for target_index, target in enumerate(targets):
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
                    options.naming_template,
                    mode=options.mode,
                    cover=options.cover and (target_index == 0 or bool(target.episode_id)),
                )
                for output_file in plan.outputs:
                    output = output_file.output
                    decision = conflict(output, options.overwrite)
                    emit(
                        dict(
                            type="preview",
                            source_index=index,
                            label=target.label,
                            title=info.title,
                            output=str(output),
                            selection=plan_description(plan),
                            warnings=plan.warnings,
                            conflict=decision,
                            duplicate=output in paths,
                            detail="输出路径已存在但不是普通文件" if decision == "blocked" else "",
                            action="请调整保存目录" if decision == "blocked" else "",
                        )
                    )
                    paths.add(output)
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
