"""Design-contract experiments, distinct from production 1.7 feature tests."""

from pathlib import Path

import pytest

from djhx_bilix.errors import InputError
from scripts.prototypes.ux_17 import Options, Rate, Session, conflict, input_lines, setting


def test_session_keeps_old_batches_and_defaults_retry_to_failed_attempt_snapshot(tmp_path):
    session = Session()
    original = Options(tmp_path / "original", quality=32, ffmpeg="original-ffmpeg")
    changed = Options(tmp_path / "changed", quality=80, overwrite=True)
    done = session.add("batch-1", "BV1j4411W7F7", "1", "done", original)
    failed = session.add("batch-1", "BV1j4411W7F7", "2", "failed", original)
    session.transition(done.task_id, 1, 1, "skipped")
    session.transition(failed.task_id, 1, 1, "failed")
    session.add("batch-2", "BV12R4y1J75d", "1", "new", changed)
    retry = session.retry(failed.task_id)
    assert len(session.tasks) == 3
    assert retry.task_id == failed.task_id
    assert retry.current.number == 2
    assert retry.current.batch_id != retry.attempts[0].batch_id
    assert retry.attempts[0].batch_id == "batch-1"
    assert retry.current.options == original
    assert retry.attempts[0].state == "failed"
    assert session.tasks[done.task_id].current.state == "skipped"


def test_explicit_current_settings_only_affect_new_attempt(tmp_path):
    session = Session()
    old = Options(tmp_path / "old", quality=32)
    current = Options(tmp_path / "current", quality=80)
    task = session.add("batch", "BV1j4411W7F7", "1", "test", old)
    session.transition(task.task_id, 1, 1, "failed")
    retried = session.retry(task.task_id, current=current)
    assert retried.current.options == current
    assert retried.attempts[0].options == old
    session.transition(task.task_id, 2, 1, "failed")
    assert session.retry(task.task_id).current.options == current


def test_late_or_duplicate_events_cannot_rewrite_a_terminal_or_new_attempt(tmp_path):
    session = Session()
    task = session.add("batch", "BV1j4411W7F7", "1", "test", Options(tmp_path))
    assert session.transition(task.task_id, 1, 1, "failed")
    assert not session.transition(task.task_id, 1, 1, "failed")
    assert not session.transition(task.task_id, 1, 2, "failed")
    with pytest.raises(ValueError, match="terminal"):
        session.transition(task.task_id, 1, 3, "canceled")
    session.retry(task.task_id)
    assert not session.transition(task.task_id, 1, 4, "canceled")
    assert session.tasks[task.task_id].current.state == "queued"
    with pytest.raises(ValueError, match="future"):
        session.transition(task.task_id, 3, 1, "loading")
    with pytest.raises(ValueError, match="future"):
        session.transition(task.task_id, 3, 0, "loading")


def test_phase_order_and_failed_filter_do_not_modify_records(tmp_path):
    session = Session()
    task = session.add("batch", "BV1j4411W7F7", "1", "test", Options(tmp_path))
    with pytest.raises(ValueError, match="invalid transition"):
        session.transition(task.task_id, 1, 1, "completed")
    for number, state in enumerate(
        (
            "loading",
            "downloading",
            "checking_video",
            "checking_audio",
            "muxing",
            "committing",
            "completed",
        ),
        1,
    ):
        assert session.transition(task.task_id, 1, number, state)
    failed = session.add("batch", "BV12R4y1J75d", "1", "failed", Options(tmp_path))
    session.transition(failed.task_id, 1, 1, "failed")
    assert [t.task_id for t in session.visible(frozenset({"failed"}))] == [failed.task_id]
    assert len(session.visible()) == 2
    with pytest.raises(ValueError, match="only failed"):
        session.retry(task.task_id)


@pytest.mark.parametrize("overwrite", [False, True])
def test_conflicts_are_point_in_time_and_do_not_create_or_replace_files(tmp_path, overwrite):
    output = tmp_path / "result.mp4"
    assert conflict(output, overwrite) == "new"
    assert not output.exists()
    output.write_bytes(b"old-output")
    assert conflict(output, overwrite) == ("replace" if overwrite else "skip")
    assert output.read_bytes() == b"old-output"
    assert conflict(tmp_path, overwrite) == "blocked"


@pytest.mark.parametrize(
    ("file", "environment", "expected", "source"),
    [
        (None, None, "default", "default"),
        ("file", None, "file", "file"),
        ("file", "env", "env", "environment"),
        ("file", "", "file", "file"),
    ],
)
def test_config_source_keeps_saved_and_effective_values(file, environment, expected, source):
    result = setting("default", file, environment)
    assert (result.effective, result.source, result.file_value) == (expected, source, file)


def test_stdin_proposal_preserves_order_duplicates_and_actual_line_numbers():
    records = input_lines("\ufeff# note\nBV1j4411W7F7\n\nBV1j4411W7F7\n")
    assert [line for line, _ in records] == [2, 4]
    assert records[0][1] == records[1][1]
    with pytest.raises(InputError, match="第 4 行"):
        input_lines("# note\n\nBV1j4411W7F7\nhttps://invalid.example/video")


def test_combined_rate_has_transfer_eta_only_when_both_totals_are_known():
    rate = Rate()
    assert rate.update(0, {"video": (1, 0, 100), "audio": (1, 0, 100)}) == (None, None)
    assert rate.update(1, {"video": (1, 40, 100), "audio": (1, 10, 100)}) == (50, 3)
    speed, eta = rate.update(2, {"video": (1, 80, 100), "audio": (1, 20, None)})
    assert speed == 50
    assert eta is None


@pytest.mark.parametrize("new_attempt", [1, 2])
def test_retry_reset_never_produces_negative_rate_or_old_eta(new_attempt):
    rate = Rate()
    rate.update(0, {"video": (1, 0, 100), "audio": (1, 0, 100)})
    rate.update(1, {"video": (1, 80, 100), "audio": (1, 20, 100)})
    assert rate.update(2, {"video": (new_attempt, 0, 100), "audio": (1, 20, 100)}) == (None, None)
    speed, eta = rate.update(3, {"video": (new_attempt, 20, 100), "audio": (1, 40, 100)})
    assert speed == 40
    assert eta == 3.5


def test_stream_attempt_change_resets_even_when_count_has_caught_up():
    rate = Rate()
    rate.update(0, {"video": (1, 10, None)})
    rate.update(1, {"video": (1, 20, None)})
    assert rate.update(2, {"video": (2, 30, None)}) == (None, None)


def test_progress_rejects_invalid_time_and_byte_counts():
    rate = Rate()
    rate.update(1, {"video": (1, 0, 100)})
    with pytest.raises(ValueError, match="time"):
        rate.update(1, {"video": (1, 1, 100)})
    with pytest.raises(ValueError, match="byte"):
        rate.update(2, {"video": (1, 101, 100)})


def test_prototype_is_not_a_product_module():
    # No production import may accidentally publish these experimental semantics.
    root = Path(__file__).resolve().parents[2] / "src" / "djhx_bilix"
    assert all(
        "scripts.prototypes" not in path.read_text(encoding="utf-8") for path in root.rglob("*.py")
    )
