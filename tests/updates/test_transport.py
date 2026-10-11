"""Exercise the real urllib/TLS transport against a private HTTPS test service."""

import hashlib
import socket
import ssl
import threading
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event

import pytest

from djhx_bilix.updater.client import Distribution, Transport, UpdateClient, _Redirects
from djhx_bilix.updater.protocol import MAX_METADATA, UpdateCanceled, UpdateError, verify_bundle


@pytest.fixture
def https_service(tmp_path, monkeypatch, signed_update):
    x509 = pytest.importorskip("cryptography.x509")
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519

    key = ed25519.Ed25519PrivateKey.generate()
    name = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, "Private updater test")])
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.DNSName("github.com"), x509.DNSName("bilix.djhx.site")]
            ),
            critical=False,
        )
        .sign(key, None)
    )
    certfile = tmp_path / "test-certificate.pem"
    keyfile = tmp_path / "test-private.key"
    certfile.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    keyfile.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    state = {"calls": [], "primary": "ok", "package": signed_update["content"]}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            state["calls"].append((self.headers["Host"], self.path, dict(self.headers)))
            primary = self.headers["Host"] == "github.com"
            if self.path == "/redirect":
                self.send_response(302)
                self.send_header("Location", "http://bilix.djhx.site/insecure")
                self.end_headers()
                return
            if primary and state["primary"] == "503":
                self.send_error(503)
                return
            name = self.path.rsplit("/", 1)[1]
            body = (
                b"x" * (MAX_METADATA + 1)
                if name == "oversized"
                else signed_update["blobs"].get(name, state["package"])
            )
            if primary and state["primary"] == "bad-signature" and name == "stable.json.sig":
                body = b'{"format":1,"algorithm":"Ed25519","key_id":"unknown"}'
            if primary and state["primary"] == "truncated" and name.endswith(".exe"):
                body = body[:-1]
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile, keyfile)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    connect = socket.create_connection

    def local_connection(address, *args, **kwargs):
        # Preserve the actual hostname for SNI and TLS verification; only route the socket.
        assert address[0] in {"github.com", "bilix.djhx.site"}
        return connect(server.server_address, *args, **kwargs)

    monkeypatch.setattr(socket, "create_connection", local_connection)
    transport = Transport(Event())
    transport.opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _Redirects(),
        urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=str(certfile))),
    )
    try:
        yield transport, state
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


@pytest.mark.parametrize("failure", ["503", "bad-signature", "truncated", "ok"])
def test_real_https_download_and_primary_failure_fallback(https_service, tmp_path, failure):
    transport, state = https_service
    state["primary"] = failure
    client = UpdateClient(
        Distribution("windows-x64-portable", tmp_path / "current.exe"),
        transport.cancel,
        cache=tmp_path / "cache",
        transport=transport,
    )
    prepared = client.prepare()
    prepared.revalidate()
    assert state["calls"][0][0] == "github.com"
    assert not list(prepared.directory.glob("*.part"))
    if failure != "ok":
        assert any(host == "bilix.djhx.site" for host, *_ in state["calls"])
    for _, _, headers in state["calls"]:
        assert "Cookie" not in headers and "Authorization" not in headers
        assert headers["Accept-Encoding"] == "identity"


def test_tls_untrusted_certificate_rejected(https_service):
    transport, _ = https_service
    transport.opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), _Redirects(), urllib.request.HTTPSHandler()
    )
    with pytest.raises(urllib.error.URLError, match="CERTIFICATE_VERIFY_FAILED"):
        transport.metadata("https://github.com/stable.json")


def test_https_redirect_cannot_downgrade_to_http(https_service):
    transport, state = https_service
    with pytest.raises(UpdateError, match="来源不受支持"):
        transport.metadata("https://github.com/redirect")
    assert len(state["calls"]) == 1


def test_metadata_size_limit_with_real_response(https_service):
    transport, _ = https_service
    with pytest.raises(UpdateError, match="过大"):
        transport.metadata("https://github.com/oversized")


def test_oversized_download_leaves_no_installable_file(https_service, tmp_path):
    transport, state = https_service
    state["package"] = b"x" * 200000
    client = UpdateClient(
        Distribution("windows-x64-portable", tmp_path / "current.exe"),
        transport.cancel,
        cache=tmp_path / "cache",
        transport=transport,
    )
    # The first chunk already exceeds the authenticated size; neither mirror can install it.
    with pytest.raises(UpdateError, match="超出"):
        client.prepare()
    assert not list(client.cache.rglob("*.part"))
    assert not list(client.cache.rglob("*.exe"))
    transport.cancel.set()
    with pytest.raises(UpdateCanceled):
        client.prepare()


def test_cancel_during_real_transfer_removes_partial_and_does_not_switch_mirror(
    https_service, signed_update, tmp_path
):
    transport, state = https_service
    content = b"verified large test package" * 20000
    state["package"] = content
    for artifact in signed_update["manifest"]["artifacts"]:
        artifact["bytes"] = len(content)
        artifact["sha256"] = hashlib.sha256(content).hexdigest()
    signed_update["blobs"].update(signed_update["bundle"]())
    client = UpdateClient(
        Distribution("windows-x64-portable", tmp_path / "current.exe"),
        transport.cancel,
        cache=tmp_path / "cache",
        transport=transport,
    )

    def cancel_after_first_block(state, count, total):
        if state == "downloading":
            assert 0 < count < total
            transport.cancel.set()

    with pytest.raises(UpdateCanceled):
        client.prepare(cancel_after_first_block)
    assert not list(client.cache.rglob("*.part"))
    assert not list(client.cache.rglob("*.exe"))
    assert not any(host == "bilix.djhx.site" for host, *_ in state["calls"])


def test_corrupt_same_size_download_fails_sha256(https_service, signed_update, tmp_path):
    transport, state = https_service
    _, artifact = verify_bundle(signed_update["blobs"], "windows-x64-portable")
    state["package"] = b"x" * artifact.size
    with pytest.raises(UpdateError, match="SHA256"):
        transport.download(artifact.urls[0], tmp_path / "partial", artifact, lambda *_: None)
