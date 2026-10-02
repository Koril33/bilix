import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from djhx_bilix.downloader import transfer
from djhx_bilix.errors import NetworkError
from djhx_bilix.models import Stream


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


def test_failed_http_keeps_existing_result(tmp_path):
    target = tmp_path / "video.m4s"
    target.write_bytes(b"previous attempt")
    with server(Handler) as url:
        with pytest.raises(NetworkError):
            transfer(Stream(32, 7, 100, (url + "/error",)), target, {}, attempts=1)
    assert target.read_bytes() == b"previous attempt"
