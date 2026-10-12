"""Queue isolation, concurrency, naming and actual HTTP pause/resume contracts."""

import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from http.server import BaseHTTPRequestHandler
from types import SimpleNamespace

import pytest
from test_transfer import server

from djhx_bilix import tasks
from djhx_bilix.config import load_settings, save_settings
from djhx_bilix.downloader import transfer
from djhx_bilix.errors import InputError, NetworkError, OperationCancelled
from djhx_bilix.filenames import validate_template
from djhx_bilix.models import DownloadResult, Stream
from djhx_bilix.network import validate_proxy
from djhx_bilix.operations import CancellationToken, StageEvent, TaskControl
from djhx_bilix.planner import build_plan
from djhx_bilix.tasks import DownloadOptions, JobSpec, Session, run_batch


def options(tmp_path, **kwargs):
    return DownloadOptions(None, None, "aac", tmp_path, False, False, None, **kwargs)


def successful(plan, *_args, stage, **_kwargs):
    for state in tasks.ACTIVE[2:]:
        stage(StageEvent(state))
    return DownloadResult(plan.output)


def test_enqueue_snapshots_and_only_one_active_batch(tmp_path, video_info, monkeypatch):
    session = Session()
    first = session.begin((JobSpec(video_info.url),), options(tmp_path), enqueue=True)
    second = session.begin(
        (JobSpec(video_info.url),), options(tmp_path, concurrency=2), enqueue=True
    )
    assert session.active_batch is None and session.next_batch() == first
    assert session.next_batch() is None and session.pending == [second]
    monkeypatch.setattr(tasks, "execute", successful)
    run_batch(
        session,
        first,
        lambda _e: None,
        CancellationToken(),
        client=SimpleNamespace(fetch=lambda _u: video_info),
    )
    summary = session.batches[first].summary
    assert session.next_batch() == second
    assert session.batches[first].summary == summary
    assert session.requests[session.batches[second].requests[0]].options.concurrency == 2


def test_single_cancel_does_not_cancel_sibling_or_batch(tmp_path, video_info, monkeypatch):
    session = Session()
    batch = session.begin((JobSpec(video_info.url), JobSpec(video_info.url)), options(tmp_path))
    token = CancellationToken()
    calls = []

    def execute(plan, *_args, cancel, stage, **_kwargs):
        calls.append(plan)
        if len(calls) == 1:
            identity = next(
                t.task_id for t in session.tasks.values() if t.latest.state == "loading"
            )
            session.cancel_item(identity, lambda _e: None)
            cancel.raise_if_cancelled()
        return successful(plan, stage=stage)

    monkeypatch.setattr(tasks, "execute", execute)
    result = run_batch(
        session, batch, lambda _e: None, token, client=SimpleNamespace(fetch=lambda _u: video_info)
    )
    assert result["canceled"] == result["completed"] == 1
    assert not token.cancelled() and result["failed"] == 0


def test_concurrent_distinct_outputs_overlap_but_same_output_is_serial(
    tmp_path, video_info, monkeypatch
):
    session = Session()
    barrier = threading.Barrier(2)
    batch = session.begin(
        (JobSpec(video_info.url), JobSpec("BV12R4y1J75d")), options(tmp_path, concurrency=2)
    )
    client = SimpleNamespace(
        fetch=lambda url: (
            video_info
            if video_info.bvid in url
            else replace(video_info, bvid="BV12R4y1J75d", url=url)
        )
    )

    def execute(plan, *_args, stage, **_kwargs):
        barrier.wait(timeout=3)
        return successful(plan, stage=stage)

    monkeypatch.setattr(tasks, "execute", execute)
    result = run_batch(session, batch, lambda _e: None, CancellationToken(), client=client)
    assert result["completed"] == 2
    assert session.path_lock(tmp_path / "x") is session.path_lock(tmp_path / "." / "x")


def test_pause_then_cancel_wakes_local_control_only():
    parent = CancellationToken()
    control = TaskControl(parent)
    control.pause()
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(control.checkpoint)
        assert not future.done()
        control.cancel()
        with pytest.raises(OperationCancelled):
            future.result(timeout=2)
    assert not parent.cancelled()


def test_cancel_waiting_for_same_output_does_not_wait_for_paused_owner(
    tmp_path, video_info, monkeypatch
):
    session = Session()
    batch = session.begin(
        (JobSpec(video_info.url), JobSpec(video_info.url)), options(tmp_path, concurrency=2)
    )
    release = threading.Event()
    waiting = threading.Event()
    canceled = threading.Event()

    def emit(_event):
        states = [task.latest.state for task in session.tasks.values()]
        if "downloading" in states and "loading" in states:
            waiting.set()
        if "canceled" in states:
            canceled.set()

    def execute(plan, *_args, stage, **_kwargs):
        stage(StageEvent("downloading"))
        assert release.wait(5)
        return successful(plan, stage=stage)

    monkeypatch.setattr(tasks, "execute", execute)
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(
            run_batch,
            session,
            batch,
            emit,
            CancellationToken(),
            client=SimpleNamespace(fetch=lambda _u: video_info),
        )
        owner = None
        try:
            assert waiting.wait(3)
            owner = next(
                task.task_id
                for task in session.tasks.values()
                if task.latest.state == "downloading"
            )
            session.pause_item(owner, True, emit)
            task_id = next(
                task.task_id for task in session.tasks.values() if task.latest.state == "loading"
            )
            session.cancel_item(task_id, emit)
            assert canceled.wait(2)
            assert not future.done()
            assert session.tasks[owner].latest.paused
        finally:
            if owner:
                session.pause_item(owner, False, emit)
            release.set()
        result = future.result(timeout=3)
    assert result["completed"] == result["canceled"] == 1


class RangeHandler(BaseHTTPRequestHandler):
    body = b"a" * (512 * 1024)
    requests = []
    changed = False
    invalid = False

    def log_message(self, *_args):
        pass

    def do_GET(self):
        type(self).requests.append(dict(self.headers))
        offset = int(self.headers.get("Range", "bytes=0-").split("=")[1].split("-")[0])
        resume = bool(offset and not self.changed)
        body = b"b" * len(self.body) if self.changed and offset else self.body
        self.send_response(206 if resume else 200)
        self.send_header("ETag", '"changed"' if self.changed and offset else '"original"')
        if resume:
            start = offset + 1 if self.invalid else offset
            self.send_header("Content-Range", f"bytes {start}-{len(body) - 1}/{len(body)}")
        self.send_header("Content-Length", str(len(body) - offset if resume else len(body)))
        self.end_headers()
        try:
            for i in range(offset if resume else 0, len(body), 8192):
                self.wfile.write(body[i : i + 8192])
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass


@pytest.mark.parametrize("changed,invalid", [(False, False), (True, False), (False, True)])
def test_real_pause_resume_validates_range_and_resource(tmp_path, changed, invalid):
    RangeHandler.requests = []
    RangeHandler.changed, RangeHandler.invalid = changed, invalid
    control = TaskControl()
    paused = threading.Event()
    once = []
    reports = []
    target = tmp_path / "video.m4s"

    def progress(_stream, done, _total):
        if done and not once:
            once.append(done)
            control.pause()

    def report(sample):
        reports.append(sample)
        if sample.phase == "paused":
            paused.set()

    with server(RangeHandler) as url, ThreadPoolExecutor(1) as pool:
        future = pool.submit(
            transfer,
            Stream(32, 7, 1, (url,)),
            target,
            {},
            progress,
            attempts=1,
            cancel=control,
            feedback=report,
        )
        assert paused.wait(3)
        assert not future.done()
        saved = target.stat().st_size
        assert 0 < saved < len(RangeHandler.body)
        control.resume()
        if invalid:
            with pytest.raises(NetworkError):
                future.result(timeout=5)
        else:
            future.result(timeout=5)
            assert target.read_bytes() == (
                b"b" * len(RangeHandler.body) if changed else RangeHandler.body
            )
    assert RangeHandler.requests[1]["Range"] == f"bytes={saved}-"
    assert RangeHandler.requests[1]["If-Range"] == '"original"'
    if not invalid:
        assert reports[-1].phase == "finished"


@pytest.mark.parametrize(
    "template", ["{title.__class__}", "{title!r}", "{title:20}", "{missing}", "{", ""]
)
def test_template_does_not_allow_python_expression_or_formats(template):
    with pytest.raises(InputError):
        validate_template(template)


def test_template_keeps_identity_and_sanitizes_paths(tmp_path, video_info):
    plan = build_plan(video_info, tmp_path, naming_template="../{owner}/{title}")
    assert plan.output.parent == tmp_path
    assert video_info.bvid in plan.output.name and video_info.cid in plan.output.name
    assert ".." not in plan.output.name


@pytest.mark.parametrize(
    "value", [1, "http://[invalid", "http://host:bad", "http://host/path", "ftp://host"]
)
def test_invalid_proxy_is_safe_input_error(value):
    with pytest.raises(InputError):
        validate_proxy(value)


def test_settings_roundtrip_proxy_template_concurrency(settings, monkeypatch):
    save_settings(
        settings,
        download_dir=settings.download_dir,
        ffmpeg=None,
        naming_template="{owner}_{title}",
        proxy="http://127.0.0.1:8080",
        concurrency=3,
    )
    actual = load_settings()
    assert actual.concurrency == 3 and actual.naming_template == "{owner}_{title}"
    assert actual.proxy == "http://127.0.0.1:8080"
    monkeypatch.setenv("BILIX_PROXY", "socks5h://127.0.0.1:1080")
    assert load_settings().proxy == "socks5h://127.0.0.1:1080"
    save_settings(actual, download_dir=actual.download_dir, ffmpeg=None)
    assert load_settings().file_proxy == "http://127.0.0.1:8080"
