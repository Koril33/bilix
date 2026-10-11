import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from djhx_bilix.downloader import transfer
from djhx_bilix.errors import NetworkError, OperationCancelled
from djhx_bilix.models import Stream
from djhx_bilix.operations import CancellationToken


@contextmanager
def server(handler):
    instance = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=instance.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{instance.server_port}"
    finally:
        instance.shutdown()
        instance.server_close()
        thread.join()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == "/error":
            self.send_response(503)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Length", "1000" if self.path == "/truncated" else "4")
        self.end_headers()
        self.wfile.write(b"abcd")
        self.close_connection = True


def test_real_http_truncation_is_not_success(tmp_path):
    with server(Handler) as url:
        with pytest.raises(NetworkError):
            transfer(
                Stream(32, 7, 100, (url + "/truncated",)), tmp_path / "video.m4s", {}, attempts=2
            )
    assert (tmp_path / "video.m4s").read_bytes() == b"abcd"


def test_backup_after_http_error(tmp_path):
    with server(Handler) as url:
        transfer(
            Stream(32, 7, 100, (url + "/error", url + "/ok")),
            tmp_path / "video.m4s",
            {},
            attempts=2,
        )
    assert (tmp_path / "video.m4s").read_bytes() == b"abcd"


def test_structured_feedback_resets_before_backup_connection(tmp_path):
    reports = []
    with server(Handler) as url:
        transfer(
            Stream(32, 7, 100, (url + "/truncated", url + "/ok")),
            tmp_path / "video.m4s",
            {},
            attempts=2,
            feedback=reports.append,
        )
    starts = [s for s in reports if s.phase == "connecting"]
    assert [(s.stream_attempt, s.completed_bytes) for s in starts] == [(1, 0), (2, 0)]
    assert any(s.phase == "retrying" and s.stream_attempt == 1 for s in reports)
    assert reports[-1].phase == "finished"
    assert reports[-1].completed_bytes == reports[-1].total_bytes == 4
    assert all(s.stream == "video" for s in reports)


def test_failed_http_keeps_existing_result(tmp_path):
    target = tmp_path / "video.m4s"
    target.write_bytes(b"previous attempt")
    with server(Handler) as url:
        with pytest.raises(NetworkError):
            transfer(Stream(32, 7, 100, (url + "/error",)), target, {}, attempts=1)
    assert target.read_bytes() == b"previous attempt"


def test_cancelled_transfer_does_not_retry_or_claim_completion(tmp_path):
    token = CancellationToken()
    reports = []

    def progress(stream, completed, expected):
        reports.append((completed, expected))
        if completed:
            token.cancel()

    with server(Handler) as url:
        with pytest.raises(OperationCancelled):
            transfer(
                Stream(32, 7, 100, (url + "/ok",)),
                tmp_path / "video.m4s",
                {},
                progress,
                attempts=3,
                cancel=token,
            )
    assert any(completed for completed, _ in reports)
    assert (tmp_path / "video.m4s").stat().st_size <= 4


@pytest.mark.parametrize("cancel_at_end", [False, True])
def test_short_stream_close_lifecycle_under_parallel_transfers(tmp_path, cancel_at_end):
    # Fast EOF/close used to race the native cleanup callback in curl-cffi 0.13.
    # Exercise the actual native client, with one Session per transfer as in production.
    with server(Handler) as url:

        def once(index):
            token = CancellationToken()
            target = tmp_path / f"{index}.m4s"

            def progress(_stream, completed, _expected):
                if cancel_at_end and completed:
                    token.cancel()

            if cancel_at_end:
                with pytest.raises(OperationCancelled):
                    transfer(Stream(16, 7, 4, (url + "/ok",)), target, {}, progress, cancel=token)
            else:
                transfer(Stream(16, 7, 4, (url + "/ok",)), target, {}, progress, cancel=token)
            assert target.read_bytes() == b"abcd"

        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(once, range(32)))
