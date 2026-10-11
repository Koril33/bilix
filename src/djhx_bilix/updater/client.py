"""Isolated update downloads, authenticated cache, and build/install identity."""

from __future__ import annotations

import hashlib
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import Event

from platformdirs import user_cache_path

from djhx_bilix import __version__

from .protocol import (
    ARTIFACT_IDS,
    ASSETS,
    CHANNEL_URLS,
    MAX_METADATA,
    Artifact,
    UpdateCanceled,
    UpdateError,
    encode_json,
    read_json,
    safe_download_url,
    select_artifact,
    validate_channel,
    verify_bundle,
    verify_signed,
    version,
)

BUNDLE_NAMES = (
    "stable.json",
    "stable.json.sig",
    "update-manifest.json",
    "update-manifest.json.sig",
)
LINUX_EXECUTABLE = Path("/usr/lib/djhx-bilix-gui/bilix-gui")
PACKAGE = "djhx-bilix-gui"
INNO_KEY = (
    "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\"
    "{3C888838-39AF-40C1-839B-A89F07E908AD}_is1"
)


@dataclass(frozen=True)
class Distribution:
    artifact_id: str
    executable: Path
    package_version: str = __version__

    @property
    def kind(self) -> str:
        return ARTIFACT_IDS[self.artifact_id][2]


def installed_deb_version() -> str:
    result = subprocess.run(
        ["/usr/bin/dpkg-query", "-W", "-f=${db:Status-Status} ${Version}", PACKAGE],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if result.returncode or not result.stdout.startswith("installed "):
        raise UpdateError("未找到已安装的 BiliX GUI deb 记录")
    return result.stdout.split()[1]


def installer_location() -> Path:
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, INNO_KEY, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY
        ) as key:
            location = winreg.QueryValueEx(key, "InstallLocation")[0]
        return Path(location).resolve()
    except OSError as exc:
        raise UpdateError("当前用户的安装记录不可用，请手动运行安装器") from exc


def distribution() -> Distribution | None:
    """Only release builds have this payload; pip/source environments stay external."""
    identity = ASSETS / "distribution.json"
    if not identity.is_file():
        return None
    data = read_json(identity.read_bytes())
    artifact_id = data.get("artifact_id")
    if (
        data.get("schema") != 1
        or data.get("product") != "bilix"
        or data.get("version") != __version__
        or artifact_id not in ARTIFACT_IDS
    ):
        raise UpdateError("发行身份不明确，请使用手动升级")
    version(__version__)  # Stable updates do not switch preview installs to stable.
    executable = Path(sys.argv[0]).resolve()
    if sys.platform == "win32" and platform.machine().lower() in {"amd64", "x86_64"}:
        if sys.getwindowsversion().major < 10 or not artifact_id.startswith("windows-x64-"):
            raise UpdateError("当前 Windows 或架构不支持此更新渠道")
        if artifact_id.endswith("installer"):
            expected = installer_location() / "runtime" / "BiliX-GUI.exe"
            if executable != expected:
                raise UpdateError("程序位置与安装记录不一致，请手动升级")
        return Distribution(artifact_id, executable)
    if sys.platform == "linux" and platform.machine() == "x86_64":
        if artifact_id != "linux-amd64-deb" or executable != LINUX_EXECUTABLE:
            raise UpdateError("程序不是受支持位置的 deb 安装版")
        libc, libc_version = platform.libc_ver()
        if libc != "glibc" or tuple(int(p) for p in libc_version.split(".")[:2]) < (2, 35):
            raise UpdateError("当前系统低于 GUI 更新的 glibc 2.35 基线")
        return Distribution(artifact_id, executable, installed_deb_version())
    raise UpdateError("当前平台或架构不支持 GUI 自动更新")


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    handle, raw_path = tempfile.mkstemp(prefix=".update-", dir=path.parent)
    temporary = Path(raw_path)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(encode_json(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def update_cache() -> Path:
    return user_cache_path("djhx-bilix", appauthor=False) / "updates"


@contextmanager
def cache_lock(cache: Path):
    """An OS lock is released on process exit, including crashes; no stale PID cleanup."""
    with (cache / "prepare.lock").open("a+b") as stream:
        # Windows byte-range locks also prohibit reading another owner's byte.
        # Inspect the size without reading it, then attempt the nonblocking lock.
        if os.fstat(stream.fileno()).st_size == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise UpdateError("另一个 BiliX 实例正在准备更新，请稍后重试") from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


class _Redirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        safe_download_url(newurl)
        return super().redirect_request(request, fp, code, message, headers, newurl)


class Transport:
    """No Bilibili session, token, cookies, or relaxed TLS settings are reused."""

    def __init__(self, cancel: Event):
        self.cancel = cancel
        self.opener = urllib.request.build_opener(_Redirects())

    def _open(self, url: str, timeout: float):
        self.check_cancel()
        request = urllib.request.Request(
            safe_download_url(url),
            headers={
                "User-Agent": f"BiliX-Updater/{__version__}",
                "Accept-Encoding": "identity",
            },
        )
        response = self.opener.open(request, timeout=timeout)
        safe_download_url(response.url)
        return response

    def check_cancel(self):
        if self.cancel.is_set():
            raise UpdateCanceled("更新下载已取消")

    def metadata(self, url: str, timeout: float = 15) -> bytes:
        deadline = time.monotonic() + timeout
        with self._open(url, timeout) as response:
            chunks = []
            size = 0
            while True:
                self.check_cancel()
                if time.monotonic() > deadline:
                    raise UpdateError("更新元数据请求超时")
                block = response.read1(min(8192, MAX_METADATA + 1 - size))
                if not block:
                    break
                chunks.append(block)
                size += len(block)
                if size > MAX_METADATA:
                    raise UpdateError("更新元数据过大")
            raw = b"".join(chunks)
        self.check_cancel()
        if len(raw) > MAX_METADATA:
            raise UpdateError("更新元数据过大")
        return raw

    def download(self, url: str, path: Path, artifact: Artifact, progress) -> None:
        count = 0
        digest = hashlib.sha256()
        last_progress = 0
        with self._open(url, 30) as response, path.open("wb") as stream:
            while True:
                self.check_cancel()
                block = response.read1(128 * 1024)
                if not block:
                    break
                count += len(block)
                if count > artifact.size:
                    raise UpdateError("更新下载超出清单大小")
                stream.write(block)
                digest.update(block)
                now = time.monotonic()
                if now - last_progress >= 0.1 or count == artifact.size:
                    progress("downloading", count, artifact.size)
                    last_progress = now
            stream.flush()
            os.fsync(stream.fileno())
        if count != artifact.size or digest.hexdigest() != artifact.sha256:
            raise UpdateError("更新下载大小或 SHA256 不匹配")


@dataclass(frozen=True)
class PreparedUpdate:
    artifact: Artifact
    directory: Path

    @property
    def package(self) -> Path:
        return self.directory / self.artifact.filename

    def revalidate(self, keys=None) -> Artifact:
        blobs = {name: (self.directory / name).read_bytes() for name in BUNDLE_NAMES}
        _, artifact = verify_bundle(blobs, self.artifact.artifact_id, keys)
        if artifact != self.artifact:
            raise UpdateError("缓存清单在下载后改变")
        artifact.verify_file(self.package)
        return artifact


class UpdateClient:
    def __init__(
        self,
        identity: Distribution,
        cancel: Event,
        *,
        cache: Path | None = None,
        transport=None,
        keys=None,
    ):
        self.identity = identity
        self.cancel = cancel
        self.cache = cache if cache is not None else update_cache()
        self.transport = transport if transport is not None else Transport(cancel)
        self.keys = keys

    def _signed_pair(self, urls, validator):
        errors = []
        for url in urls:
            self.transport.check_cancel()
            try:
                deadline = time.monotonic() + 15
                raw = self.transport.metadata(url)
                remaining = max(0.1, deadline - time.monotonic())
                signature = self.transport.metadata(url + ".sig", remaining)
                data = verify_signed(raw, signature, self.keys)
                validator(data, raw)
                return data, raw, signature
            except UpdateCanceled:
                raise
            except (UpdateError, OSError, urllib.error.URLError, TimeoutError) as exc:
                errors.append(f"{url.split('/')[2]}: {exc}")
        raise UpdateError("两个更新源均不可用或未通过验证：" + "；".join(errors))

    def prepare(self, progress=lambda *_: None) -> PreparedUpdate | None:
        self.cache.mkdir(parents=True, exist_ok=True, mode=0o700)
        with cache_lock(self.cache):
            return self._prepare(progress)

    def _prepare(self, progress) -> PreparedUpdate | None:
        watermark_file = self.cache / "trusted-channel.json"
        watermark = read_json(watermark_file.read_bytes()) if watermark_file.exists() else {}
        sequence = watermark.get("sequence", 0)
        previous_hash = watermark.get("sha256", "")
        if type(sequence) is not int or sequence < 0:
            raise UpdateError("本地更新序号记录损坏")
        progress("checking", 0, 0)
        channel, channel_raw, channel_sig = self._signed_pair(
            CHANNEL_URLS,
            lambda data, raw: validate_channel(
                data, sequence=sequence, previous_hash=previous_hash, raw=raw
            ),
        )

        def check_manifest(data, raw):
            if (
                len(raw) != channel["manifest_bytes"]
                or hashlib.sha256(raw).hexdigest() != channel["manifest_sha256"]
            ):
                raise UpdateError("更新清单哈希不匹配")
            select_artifact(data, channel, self.identity.artifact_id)

        manifest, manifest_raw, manifest_sig = self._signed_pair(
            channel["manifest_urls"],
            check_manifest,
        )
        artifact = select_artifact(manifest, channel, self.identity.artifact_id)
        atomic_json(
            watermark_file,
            {
                "sequence": channel["metadata_sequence"],
                "sha256": hashlib.sha256(channel_raw).hexdigest(),
            },
        )
        newer = version(artifact.version) > version(__version__)
        if self.identity.kind == "deb" and version(artifact.version) >= version(__version__):
            newer = (
                subprocess.run(
                    [
                        "/usr/bin/dpkg",
                        "--compare-versions",
                        artifact.package_version,
                        "gt",
                        self.identity.package_version,
                    ],
                    check=False,
                    timeout=10,
                ).returncode
                == 0
            )
        if not newer:
            return None
        directory = self.cache / artifact.sha256
        directory.mkdir(exist_ok=True, mode=0o700)
        blobs = dict(zip(BUNDLE_NAMES, (channel_raw, channel_sig, manifest_raw, manifest_sig)))
        for name, raw in blobs.items():
            # All bytes are already authenticated; interrupted writes are rejected on next load.
            (directory / name).write_bytes(raw)
        prepared = PreparedUpdate(artifact, directory)
        if prepared.package.exists():
            try:
                prepared.revalidate(self.keys)
                return prepared
            except UpdateError:
                prepared.package.unlink()
        if shutil.disk_usage(directory).free < artifact.size * 2 + 100 * 1024**2:
            raise UpdateError("更新缓存所在磁盘空间不足")
        temporary = directory / (artifact.filename + ".part")
        errors = []
        for url in artifact.urls:
            self.transport.check_cancel()
            try:
                self.transport.download(url, temporary, artifact, progress)
                self.transport.check_cancel()
                progress("verifying", artifact.size, artifact.size)
                artifact.verify_file(temporary)
                os.replace(temporary, prepared.package)
                prepared.revalidate(self.keys)
                return prepared
            except UpdateCanceled:
                raise
            except (UpdateError, OSError, urllib.error.URLError, TimeoutError) as exc:
                errors.append(f"{url.split('/')[2]}: {exc}")
            finally:
                temporary.unlink(missing_ok=True)
        raise UpdateError("更新包下载失败：" + "；".join(errors))
