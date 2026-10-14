from threading import Event

import pytest

from djhx_bilix.updater.client import Distribution, PreparedUpdate, UpdateClient, cache_lock
from djhx_bilix.updater.protocol import CHANNEL_URLS, UpdateCanceled, UpdateError, verify_bundle


class Mirror:
    def __init__(self, value, *, fail_metadata=False, bad_package=False, cancel=None):
        self.value = value
        self.fail_metadata = fail_metadata
        self.bad_package = bad_package
        self.cancel = cancel or Event()
        self.calls = []

    def check_cancel(self):
        if self.cancel.is_set():
            raise UpdateCanceled("canceled")

    def metadata(self, url, timeout=15):
        self.calls.append(url)
        if self.fail_metadata and "github.com" in url:
            raise OSError("unreachable")
        return self.value["blobs"][url.rsplit("/", 1)[1]]

    def download(self, url, path, artifact, progress):
        self.calls.append(url)
        path.write_bytes(
            b"corrupt" if self.bad_package and "github.com" in url else self.value["content"]
        )
        progress("downloading", artifact.size, artifact.size)


@pytest.mark.parametrize("failure", ["metadata", "package", "none"])
def test_github_first_fallback_and_authenticated_cache(signed_update, tmp_path, failure):
    mirror = Mirror(
        signed_update, fail_metadata=failure == "metadata", bad_package=failure == "package"
    )
    identity = Distribution("windows-x64-portable", tmp_path / "renamed.exe")
    client = UpdateClient(identity, Event(), cache=tmp_path / "cache", transport=mirror)
    prepared = client.prepare()
    assert mirror.calls[0] == CHANNEL_URLS[0]
    assert prepared.package.read_bytes() == signed_update["content"]
    assert not list(prepared.directory.glob("*.part"))
    if failure == "metadata":
        assert CHANNEL_URLS[1] in mirror.calls
    if failure == "package":
        assert prepared.artifact.urls[1] in mirror.calls
    mirror.calls.clear()
    assert client.prepare() == prepared
    assert not any(url.endswith(".exe") for url in mirror.calls)


def test_cached_package_tampering_cannot_install(signed_update):
    _, artifact = verify_bundle(signed_update["blobs"], "windows-x64-portable")
    prepared = PreparedUpdate(artifact, signed_update["directory"])
    prepared.package.write_bytes(b"tampered")
    with pytest.raises(UpdateError, match="SHA256"):
        prepared.revalidate()


def test_cancel_does_not_switch_to_another_mirror(signed_update, tmp_path):
    cancel = Event()
    cancel.set()
    mirror = Mirror(signed_update, cancel=cancel)
    client = UpdateClient(
        Distribution("windows-x64-portable", tmp_path / "current.exe"),
        cancel,
        cache=tmp_path / "cache",
        transport=mirror,
    )
    with pytest.raises(UpdateCanceled):
        client.prepare()
    assert mirror.calls == []


def test_preparation_lock_excludes_another_copy_and_releases_after_error(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    with cache_lock(cache):
        with pytest.raises(UpdateError, match="另一个"):
            with cache_lock(cache):
                pytest.fail("Another copy acquired a preparation lock")
    with pytest.raises(RuntimeError):
        with cache_lock(cache):
            raise RuntimeError("interrupted preparation")
    with cache_lock(cache):
        pass


def test_insufficient_space_never_downloads_package(signed_update, tmp_path, monkeypatch):
    from types import SimpleNamespace

    from djhx_bilix.updater import client as module

    monkeypatch.setattr(module.shutil, "disk_usage", lambda path: SimpleNamespace(free=1))
    mirror = Mirror(signed_update)
    client = UpdateClient(
        Distribution("windows-x64-portable", tmp_path / "current.exe"),
        Event(),
        cache=tmp_path / "cache",
        transport=mirror,
    )
    with pytest.raises(UpdateError, match="空间不足"):
        client.prepare()
    assert not any(url.endswith(".exe") for url in mirror.calls)


def test_current_version_does_not_download_or_offer_update(signed_update, tmp_path, monkeypatch):
    from djhx_bilix.updater import client as module

    monkeypatch.setattr(module, "__version__", "1.8.1")
    mirror = Mirror(signed_update)
    client = UpdateClient(
        Distribution("windows-x64-portable", tmp_path / "current.exe"),
        Event(),
        cache=tmp_path / "cache",
        transport=mirror,
    )
    assert client.prepare() is None
    assert not any(url.endswith(".exe") for url in mirror.calls)
