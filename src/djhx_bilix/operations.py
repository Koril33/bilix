"""Framework-independent operation state shared by CLI and desktop clients."""

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


@dataclass(frozen=True)
class StageEvent:
    """Coarse download stage, independent of byte-level progress callbacks."""

    stage: str
    detail: str = ""
