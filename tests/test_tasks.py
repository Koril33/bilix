"""Production task contracts; no Qt or network is required."""

from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from djhx_bilix import cli, tasks
from djhx_bilix.errors import DownloadError, InputError, NetworkError, OperationCancelled
from djhx_bilix.models import DownloadResult, Page, VideoTarget
from djhx_bilix.operations import CancellationToken, StageEvent
from djhx_bilix.planner import build_plan
from djhx_bilix.tasks import DownloadOptions, JobSpec, Session, conflict, run_batch, run_preview


@pytest.fixture
def options(tmp_path):
    return DownloadOptions(32, None, "aac", tmp_path / "输出", False, False, None)


def begin(options):
    session = Session()
    batch = session.begin((JobSpec("BV1j4411W7F7"),), options)
    return session, batch


def successful(plan, *_args, stage, **_kwargs):
    for state in tasks.ACTIVE[2:]:
        stage(StageEvent(state))
    stage(StageEvent("completed"))
    return DownloadResult(plan.output)


def test_retry_latest_attempt_snapshot_and_original_batch_immutable(
    monkeypatch, options, video_info
):
    session, batch = begin(options)
    monkeypatch.setattr(
        tasks, "execute", lambda *_a, **_k: (_ for _ in ()).throw(NetworkError("网络失败"))
    )
    client = SimpleNamespace(fetch=lambda _url: video_info)
    first_summary = run_batch(session, batch, lambda _e: None, CancellationToken(), client=client)
    task = next(iter(session.tasks.values()))
    assert task.latest.error_code == "network"
    with pytest.raises(FrozenInstanceError):
        task.latest.state = "completed"
    changed = replace(options, quality=16, overwrite=True)
    second_batch = session.retry((task.task_id,), options=changed)
    run_batch(session, second_batch, lambda _e: None, CancellationToken(), client=client)
    second_attempt = session.tasks[task.task_id].latest
    third_batch = session.retry((task.task_id,))
    assert session.tasks[task.task_id].latest.options == second_attempt.options
    monkeypatch.setattr(tasks, "execute", successful)
    summary = run_batch(session, third_batch, lambda _e: None, CancellationToken(), client=client)
    assert summary["completed"] == 1
    assert len(session.tasks[task.task_id].attempts) == 3
    assert dict(session.batches[batch].summary) == first_summary
    assert task.latest.options == options


def test_source_failure_is_not_a_fake_download_task_and_reread_keeps_snapshot(
    options, monkeypatch, video_info
):
    session, batch = begin(options)
    client = SimpleNamespace(fetch=lambda _url: (_ for _ in ()).throw(NetworkError("失败")))
    summary = run_batch(session, batch, lambda _e: None, CancellationToken(), client=client)
    assert summary["source_failed"] == 1 and summary["failed"] == summary["tasks"] == 0
    assert not session.tasks
    request_id = next(iter(session.requests))
    retry_batch = session.retry((), (request_id,))
    request = session.requests[session.batches[retry_batch].requests[0]]
    assert request.origin_request_id == request_id and request.options == options
    monkeypatch.setattr(tasks, "execute", successful)
    run_batch(
        session,
        retry_batch,
        lambda _e: None,
        CancellationToken(),
        client=SimpleNamespace(fetch=lambda _u: video_info),
    )
    assert len(session.tasks) == 1
    assert session.requests[request_id].state == "failed"


def test_retry_reloads_streams_and_refuses_changed_cid(options, video_info, monkeypatch):
    session, batch = begin(options)
    monkeypatch.setattr(
        tasks, "execute", lambda *_a, **_k: (_ for _ in ()).throw(NetworkError("失败"))
    )
    run_batch(
        session,
        batch,
        lambda _e: None,
        CancellationToken(),
        client=SimpleNamespace(fetch=lambda _u: video_info),
    )
    task_id = next(iter(session.tasks))
    retry_batch = session.retry((task_id,))
    monkeypatch.setattr(tasks, "execute", lambda *_a, **_k: pytest.fail("identity changed"))
    result = run_batch(
        session,
        retry_batch,
        lambda _e: None,
        CancellationToken(),
        client=SimpleNamespace(fetch=lambda _u: replace(video_info, cid="999")),
    )
    assert result["failed"] == 1
    assert session.tasks[task_id].latest.error_code == "identity_changed"
    assert "cdn.example" not in repr(session.tasks)


def test_one_terminal_per_attempt_and_committed_success_wins_cancel(
    options, video_info, monkeypatch
):
    session, batch = begin(options)
    token = CancellationToken()

    def execute(plan, *_a, stage, **kw):
        successful(plan, stage=stage)
        token.cancel()
        return DownloadResult(plan.output)

    monkeypatch.setattr(tasks, "execute", execute)
    events = []
    result = run_batch(
        session, batch, events.append, token, client=SimpleNamespace(fetch=lambda _u: video_info)
    )
    terminal = [e for e in events if e.get("attempt") and e["attempt"].state in tasks.TERMINAL]
    assert len(terminal) == 1 and result["completed"] == 1 and result["canceled"] == 0


def test_cancel_discovered_pending_parts_and_unread_sources(options, video_info, monkeypatch):
    session = Session()
    batch = session.begin((JobSpec(video_info.url), JobSpec("BV12R4y1J75d")), options)
    info = replace(
        video_info, pages=video_info.pages + (Page(2, "second", video_info.url + "?p=2", 4, "200"),)
    )
    client = SimpleNamespace(fetch=lambda _u: info)
    monkeypatch.setattr(
        tasks, "execute", lambda *_a, **_k: (_ for _ in ()).throw(OperationCancelled("取消"))
    )
    result = run_batch(session, batch, lambda _e: None, CancellationToken(), client=client)
    assert result["canceled"] == 2 and result["source_canceled"] == 1
    assert result["discovery_complete"] == 0
    assert len(session.tasks) == 2


def test_guard_busy_clear_illegal_transition_and_callbacks_outside_lock(options, video_info):
    session, batch = begin(options)
    with pytest.raises(InputError):
        session.begin((JobSpec(video_info.url),), options)
    with pytest.raises(InputError):
        session.clear(frozenset({"completed"}))
    request_id = session.batches[batch].requests[0]
    ids = session.register(request_id, (VideoTarget(video_info.url, video_info),))

    def callback(_event):
        assert not session._lock._is_owned()

    session.event(ids[0], callback, state="loading")
    with pytest.raises(ValueError):
        session.event(ids[0], callback, state="queued")


@pytest.mark.parametrize(
    "kind,overwrite,expected",
    [
        ("missing", False, "new"),
        ("file", False, "skip"),
        ("file", True, "replace"),
        ("directory", False, "blocked"),
        ("directory", True, "blocked"),
    ],
)
def test_conflict_is_read_only(tmp_path, kind, overwrite, expected):
    target = tmp_path / "target.mp4"
    if kind == "file":
        target.write_bytes(b"old")
    if kind == "directory":
        target.mkdir()
    assert conflict(target, overwrite) == expected
    if kind == "file":
        assert target.read_bytes() == b"old"


def test_preview_actual_fallback_duplicate_and_no_ffmpeg_or_writes(
    options, video_info, monkeypatch
):
    monkeypatch.setattr(tasks, "execute", lambda *_a, **_k: pytest.fail("preview must not execute"))
    events = []
    result = run_preview(
        (JobSpec(video_info.url), JobSpec(video_info.url)),
        replace(options, quality=80),
        events.append,
        CancellationToken(),
        client=SimpleNamespace(fetch=lambda _u: video_info),
    )
    assert result["planned"] == 2 and not options.save.exists()
    assert "480P" in events[0]["selection"] and events[0]["warnings"]
    assert events[1]["duplicate"]


def test_preview_blocked_and_drm_safe_actions(options, video_info):
    path = build_plan(video_info, options.save).output
    path.mkdir(parents=True)
    events = []
    result = run_preview(
        (JobSpec(video_info.url),),
        options,
        events.append,
        CancellationToken(),
        client=SimpleNamespace(fetch=lambda _u: video_info),
    )
    assert result["failed"] == 1 and events[0]["conflict"] == "blocked"
    events.clear()
    run_preview(
        (JobSpec(video_info.url),),
        options,
        events.append,
        CancellationToken(),
        client=SimpleNamespace(fetch=lambda _u: replace(video_info, is_drm=True)),
    )
    assert events[0]["error_code"] == "drm" and "重试" not in events[0]["action"]


def test_wrapped_error_keeps_internal_category():
    error = DownloadError("工作目录已保留", cause=NetworkError("连接失败"))
    assert error.error_code == "network"


def test_attempt_records_resolved_ffmpeg_without_mutating_options(options, video_info, monkeypatch):
    session, batch = begin(options)

    def execute(plan, *_args, stage, **_kwargs):
        stage(StageEvent("downloading", ffmpeg="resolved-ffmpeg"))
        return DownloadResult(plan.output)

    monkeypatch.setattr(tasks, "execute", execute)
    result = run_batch(
        session,
        batch,
        lambda _e: None,
        CancellationToken(),
        client=SimpleNamespace(fetch=lambda _u: video_info),
    )
    attempt = next(iter(session.tasks.values())).latest
    assert result["completed"] == 1 and attempt.resolved_ffmpeg == "resolved-ffmpeg"
    assert attempt.options.ffmpeg is None


def test_cli_download_cooperative_cancel_130(monkeypatch, video_info):
    monkeypatch.setattr(tasks.BilibiliClient, "fetch", lambda *_a: video_info)
    monkeypatch.setattr(
        tasks, "execute", lambda *_a, **_k: (_ for _ in ()).throw(OperationCancelled("取消"))
    )
    result = CliRunner().invoke(cli.app, ["download", video_info.url, "--quiet"])
    assert result.exit_code == 130 and "取消" in result.output


def test_windows_break_cooperates_and_restores_handlers(monkeypatch, video_info):
    import os
    import signal

    if os.name != "nt":
        pytest.skip("Windows console control event")
    before = {n: signal.getsignal(n) for n in (signal.SIGINT, signal.SIGBREAK)}
    monkeypatch.setattr(tasks.BilibiliClient, "fetch", lambda *_a: video_info)

    def interrupted_execute(*_args, cancel, **_kwargs):
        signal.getsignal(signal.SIGBREAK)(signal.SIGBREAK, None)
        cancel.raise_if_cancelled()

    monkeypatch.setattr(tasks, "execute", interrupted_execute)
    result = CliRunner().invoke(cli.app, ["download", video_info.url, "--quiet"])
    assert result.exit_code == 130 and "取消" in result.output
    assert {n: signal.getsignal(n) for n in before} == before


def test_unknown_exception_is_sanitized_and_batch_closed(options, monkeypatch):
    session, batch = begin(options)
    result = run_batch(
        session,
        batch,
        lambda _e: None,
        CancellationToken(),
        client=SimpleNamespace(
            fetch=lambda _u: (_ for _ in ()).throw(RuntimeError("Cookie=PRIVATE"))
        ),
    )
    assert result["source_failed"] == 1 and session.active_batch is None
    assert "PRIVATE" not in repr(session.requests)
