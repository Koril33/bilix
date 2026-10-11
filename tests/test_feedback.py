"""Estimates are checked against controlled production times, including failure boundaries."""

import pytest

from djhx_bilix.feedback import TransferEstimator, TransferSample, feedback_text


def sample(name="video", sequence=1, done=0, total=6000, at=0, phase="receiving", attempt=1):
    return TransferSample(name, attempt, sequence, phase, done, total, at)


def active_pair():
    value = TransferEstimator()
    for name, total, done in (("video", 6000, 2000), ("audio", 2000, 100)):
        value.ingest(sample(name, total=total))
        value.ingest(sample(name, 2, done, total, 2))
    return value


def test_parallel_eta_uses_slowest_stream_and_ages_without_callbacks():
    value = active_pair()
    current = value.snapshot(2)
    assert current.speed == 1050
    assert current.eta == 38
    assert value.snapshot(5).speed == 0
    assert value.snapshot(5).eta is None
    assert value.snapshot(5).reason == "stalled"


def test_retry_resets_only_its_stream_and_rejects_old_attempts():
    value = active_pair()
    value.ingest(sample(sequence=1, at=2.1, phase="connecting", attempt=2))
    current = value.snapshot(2.2)
    assert current.speed == pytest.approx(100 / 2.2)
    assert current.eta is None
    assert not value.ingest(sample(sequence=10, done=4000, at=2.3))
    assert current.streams[0].completed == 0


def test_unknown_length_does_not_hide_speed_or_poison_remaining_known_stream():
    value = active_pair()
    value.ingest(sample("audio", 3, 100, None, 2.1))
    value.ingest(sample("audio", 4, 200, None, 3.2))
    assert value.snapshot(3.2).eta is None
    assert value.snapshot(3.2).speed > 0
    value.ingest(sample("audio", 5, 200, None, 3.3, "finished"))
    current = value.snapshot(3.3)
    assert current.eta == pytest.approx(4000 / (2000 / 3.3))
    assert current.speed == pytest.approx(2000 / 3.3)


@pytest.mark.parametrize("at,done,total", [(float("nan"), 1, 3), (0, -1, 3), (0, 1, 0)])
def test_invalid_samples_are_not_accepted(at, done, total):
    assert not TransferEstimator().ingest(sample(at=at, done=done, total=total))


def test_bounded_sampling_counter_reset_and_overflow():
    value = TransferEstimator(required=("video",))
    for i in range(10000):
        value.ingest(sample(sequence=i + 1, done=i, total=20000, at=i / 1000))
    assert len(value._points["video"]) <= 32
    assert value.snapshot(10).speed > 0
    value.ingest(sample(sequence=10001, done=0, total=20000, at=10.1))
    assert value.snapshot(10.1).speed is None
    value.ingest(sample(sequence=10002, done=20001, total=20000, at=12))
    assert value.snapshot(12).eta is None


def test_no_zero_or_unbounded_eta_text():
    value = active_pair()
    assert "传输约" in feedback_text(value.snapshot(2))
    assert "等待数据" in feedback_text(value.snapshot(5))
    assert "inf" not in feedback_text(value.snapshot(5))


def test_rich_ignores_old_samples_and_clears_known_total_on_retry(monkeypatch):
    from io import StringIO

    from rich.console import Console

    from djhx_bilix import presentation

    instances = []
    original = presentation.Progress

    class CapturedProgress(original):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            instances.append(self)

    monkeypatch.setattr(presentation, "Progress", CapturedProgress)
    monkeypatch.setattr(presentation, "console", Console(file=StringIO(), force_terminal=True))
    with presentation.download_progress() as update:
        update.feedback((sample(sequence=2, done=2000, at=2),), "task-attempt")
        update.feedback((sample(sequence=1, done=1000, at=1),), "task-attempt")
        assert instances[0].tasks[0].completed == 2000
        update.feedback((sample(at=3, total=None, phase="connecting", attempt=2),), "task-attempt")
        assert instances[0].tasks[0].completed == 0
        assert instances[0].tasks[0].total is None
