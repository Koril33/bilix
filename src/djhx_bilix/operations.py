"""Framework-independent operation state shared by CLI and desktop clients."""

import time
from dataclasses import dataclass
from threading import Event

from .errors import OperationCancelled


class CancellationToken:
    """Thread-safe cooperative cancellation for downloads and QR login."""

    def __init__(self) -> None:
        self._event = Event()

    def cancel(self) -> None:
        self._event.set()

    def cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        if self.cancelled():
            raise OperationCancelled("操作已取消")

    def wait(self, seconds: float) -> bool:
        """Wait up to seconds; return True when cancellation was requested."""
        return self._event.wait(seconds)

    def checkpoint(self) -> None:
        self.raise_if_cancelled()


class TaskControl(CancellationToken):
    """Cancellation scope and cooperative pause, independent of presentation."""

    def __init__(self, *parents: CancellationToken) -> None:
        super().__init__()
        self.parents = parents
        self._paused = Event()

    def cancelled(self) -> bool:
        return super().cancelled() or any(parent.cancelled() for parent in self.parents)

    def pause(self) -> None:
        self._paused.set()

    def resume(self) -> None:
        self._paused.clear()

    @property
    def paused(self) -> bool:
        return self._paused.is_set()

    def checkpoint(self) -> None:
        self.raise_if_cancelled()
        while self.paused:
            self.raise_if_cancelled()
            self._event.wait(0.1)

    def wait(self, seconds: float) -> bool:
        deadline = time.monotonic() + seconds
        while not self.cancelled() and time.monotonic() < deadline:
            self._event.wait(min(0.1, max(0, deadline - time.monotonic())))
        return self.cancelled()


@dataclass(frozen=True)
class StageEvent:
    """Coarse download stage, independent of byte-level progress callbacks."""

    stage: str
    detail: str = ""
    ffmpeg: str = ""
