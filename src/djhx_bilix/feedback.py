"""Bounded, Qt/Rich-free transfer sampling and estimates shared by both frontends."""

import math
import threading
import time
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class TransferSample:
    stream: str
    stream_attempt: int
    stream_sequence: int
    phase: str
    completed_bytes: int
    total_bytes: int | None
    sampled_at: float


@dataclass(frozen=True)
class StreamFeedback:
    stream: str
    completed: int
    total: int | None
    phase: str
    speed: float | None = None
    eta: float | None = None


@dataclass(frozen=True)
class TransferFeedback:
    streams: tuple[StreamFeedback, ...]
    speed: float | None
    eta: float | None
    reason: str


class TransferEstimator:
    """Production-time samples; snapshot time ages stalled streams without new chunks."""

    def __init__(self, required=("video", "audio"), *, window=5.0, warmup=1.0, stall=3.0):
        self.required = tuple(required)
        self.window, self.warmup, self.stall = window, warmup, stall
        self._latest = {}
        self._points = {}
        self._lock = threading.RLock()

    def ingest(self, sample: TransferSample) -> bool:
        if (
            sample.stream not in self.required
            or sample.stream_attempt < 1
            or sample.stream_sequence < 1
            or sample.phase
            not in {"connecting", "receiving", "retrying", "finished", "failed", "paused"}
            or sample.completed_bytes < 0
            or not math.isfinite(sample.sampled_at)
            or (sample.total_bytes is not None and sample.total_bytes <= 0)
        ):
            return False
        with self._lock:
            previous = self._latest.get(sample.stream)
            if previous and (
                sample.stream_attempt < previous.stream_attempt
                or sample.stream_attempt == previous.stream_attempt
                and (
                    sample.stream_sequence <= previous.stream_sequence
                    or sample.sampled_at < previous.sampled_at
                    or previous.phase in {"finished", "failed"}
                )
            ):
                return False
            reset = (
                previous is None
                or sample.stream_attempt != previous.stream_attempt
                or sample.completed_bytes < previous.completed_bytes
                or sample.total_bytes != previous.total_bytes
                or sample.phase == "connecting"
            )
            points = self._points.setdefault(sample.stream, deque(maxlen=32))
            if reset:
                points.clear()
            self._latest[sample.stream] = sample
            if sample.phase == "receiving":
                point = (sample.sampled_at, sample.completed_bytes)
                # Replace the newest point inside a sampling interval, preserving the baseline.
                if len(points) > 1 and point[0] - points[-2][0] < 0.25:
                    points[-1] = point
                else:
                    points.append(point)
            return True

    def snapshot(self, now=None) -> TransferFeedback:
        now = time.monotonic() if now is None else now
        with self._lock:
            streams = []
            for name in self.required:
                sample = self._latest.get(name)
                if sample is None:
                    streams.append(StreamFeedback(name, 0, None, "connecting"))
                    continue
                phase, speed, eta = sample.phase, None, None
                if phase == "receiving" and math.isfinite(now) and now >= sample.sampled_at:
                    points = self._points[name]
                    while len(points) > 2 and points[1][0] <= now - self.window:
                        points.popleft()
                    # The timestamp of the last byte increase, not a repeated zero-byte sample.
                    changed_at = points[-1][0] if points else sample.sampled_at
                    for point in reversed(points):
                        if point[1] < sample.completed_bytes:
                            break
                        changed_at = point[0]
                    if now - changed_at >= self.stall:
                        phase, speed = "stalled", 0.0
                    elif points and now - points[0][0] >= self.warmup:
                        elapsed = now - points[0][0]
                        speed = max(0.0, (sample.completed_bytes - points[0][1]) / elapsed)
                        if (
                            sample.total_bytes is not None
                            and sample.completed_bytes <= sample.total_bytes
                            and speed > 0
                        ):
                            eta = (sample.total_bytes - sample.completed_bytes) / speed
                if phase == "finished":
                    speed = 0.0
                streams.append(
                    StreamFeedback(
                        name, sample.completed_bytes, sample.total_bytes, phase, speed, eta
                    )
                )
            active = [s for s in streams if s.phase != "finished"]
            values = [s.speed for s in active if s.speed is not None]
            speed = sum(values) if values else None
            eta = (
                max((s.eta for s in active), default=None)
                if (active and all(s.eta is not None and s.speed and s.speed > 0 for s in active))
                else None
            )
            reason = (
                "finished"
                if not active
                else "waiting"
                if any(s.phase in {"connecting", "retrying", "failed"} for s in active)
                else "stalled"
                if any(s.phase == "stalled" for s in active)
                else "unknown"
                if any(s.total is None for s in active)
                else "warming"
                if any(s.speed is None for s in active)
                else "receiving"
            )
            return TransferFeedback(tuple(streams), speed, eta, reason)


def format_speed(speed: float | None) -> str:
    if speed is None:
        return "测速中…"
    for unit in ("B/s", "KiB/s", "MiB/s", "GiB/s"):
        if speed < 1024 or unit == "GiB/s":
            return f"{speed:.0f} {unit}" if unit == "B/s" else f"{speed:.1f} {unit}"
        speed /= 1024
    raise AssertionError("unreachable")


def format_eta(eta: float | None) -> str:
    if eta is None:
        return "时间未知"
    seconds = max(5, math.ceil(eta / 5) * 5)
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"约 {hours} 小时 {minutes} 分"
    if minutes:
        return f"约 {minutes} 分 {seconds} 秒"
    return f"约 {seconds} 秒"


def feedback_text(value: TransferFeedback) -> str:
    if value.reason == "finished":
        return "传输结束，等待校验"
    if value.eta is not None:
        return f"{format_speed(value.speed)} · 传输{format_eta(value.eta)}"
    labels = {
        "waiting": "等待连接",
        "stalled": "等待数据",
        "unknown": "传输时间未知",
        "warming": "测速中…",
        "receiving": "传输时间未知",
    }
    label = labels[value.reason]
    return f"{format_speed(value.speed)} · {label}" if value.speed is not None else label
