"""Version 1 update protocol: signatures cover the original JSON bytes."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

MAX_METADATA = 256 * 1024
MAX_ARTIFACT = 2 * 1024**3
WEBSITE = "https://bilix.djhx.site"
GITHUB = "https://github.com/Koril33/bilix/releases"
CHANNEL_URLS = (f"{GITHUB}/latest/download/stable.json", f"{WEBSITE}/updates/stable.json")
ASSETS = Path(__file__).resolve().parents[1] / "assets"
ARTIFACT_IDS = {
    "windows-x64-portable": ("windows", "x64", "portable", "user"),
    "windows-x64-installer": ("windows", "x64", "installer", "user"),
    "linux-amd64-deb": ("linux", "amd64", "deb", "system"),
}


class UpdateError(Exception):
    """An update cannot be trusted, prepared, or applied."""


class UpdateCanceled(UpdateError):
    pass


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise UpdateError("更新 JSON 含重复字段")
        result[key] = value
    return result


def read_json(raw: bytes) -> dict:
    if not raw or len(raw) > MAX_METADATA:
        raise UpdateError("更新元数据大小不合法")
    try:
        result = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise UpdateError("更新元数据格式不合法") from exc
    if not isinstance(result, dict):
        raise UpdateError("更新元数据必须是对象")
    return result


def encode_json(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def timestamp(value) -> None:
    if not isinstance(value, str) or len(value) > 40 or not value.endswith("Z"):
        raise UpdateError("更新发布时间必须是 UTC ISO 8601 时间")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
        if parsed.tzinfo is None:
            raise ValueError
    except ValueError as exc:
        raise UpdateError("更新发布时间不合法") from exc


def digest(value) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
        raise UpdateError("更新 SHA256 不合法")
    return value


def number(value, maximum: int) -> int:
    if type(value) is not int or not 0 < value <= maximum:
        raise UpdateError("更新数值不合法")
    return value


def version(value: str) -> tuple[int, int, int]:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", value):
        raise UpdateError("stable 只接受正式三段版本号")
    return tuple(int(part) for part in value.split("."))


def release_tag(value: str, app_version: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(
        rf"v{re.escape(app_version)}(?:-r[1-9][0-9]*)?", value
    ):
        raise UpdateError("发行标签与版本不匹配")
    return value


def filename(value: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) > 180
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]*", value)
        or ".." in value
    ):
        raise UpdateError("更新文件名不合法")
    return value


def release_urls(tag: str, name: str) -> list[str]:
    return [f"{GITHUB}/download/{tag}/{name}", f"{WEBSITE}/releases/{tag}/{name}"]


def safe_download_url(url: str) -> str:
    """Allow GitHub's asset CDN redirects, but never HTTP or URL credentials."""
    try:
        parsed = urlsplit(url)
        allowed = {
            "github.com",
            "release-assets.githubusercontent.com",
            "objects.githubusercontent.com",
            "github-releases.githubusercontent.com",
            "bilix.djhx.site",
        }
        if (
            parsed.scheme != "https"
            or parsed.hostname not in allowed
            or parsed.username
            or parsed.password
            or parsed.fragment
            or parsed.port not in (None, 443)
        ):
            raise ValueError
    except ValueError as exc:
        raise UpdateError("更新链接或重定向来源不受支持") from exc
    return url


def trusted_keys() -> dict[str, str]:
    data = read_json((ASSETS / "update-keys.json").read_bytes())
    if data.get("format") != 1 or not isinstance(data.get("keys"), dict) or not data["keys"]:
        raise UpdateError("程序内置更新公钥不可用")
    return data["keys"]


def verify_signed(raw: bytes, signature: bytes, keys: dict[str, str] | None = None) -> dict:
    # Metadata is interpreted only after authentication. The signature envelope is bounded.
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    if len(raw) > MAX_METADATA:
        raise UpdateError("更新元数据过大")
    envelope = read_json(signature)
    if (
        type(envelope.get("format")) is not int
        or envelope["format"] != 1
        or envelope.get("algorithm") != "Ed25519"
    ):
        raise UpdateError("不支持的更新签名格式")
    try:
        public = (trusted_keys() if keys is None else keys)[envelope["key_id"]]
        public_bytes = base64.b64decode(public, validate=True)
        sig_bytes = base64.b64decode(envelope["signature"], validate=True)
        Ed25519PublicKey.from_public_bytes(public_bytes).verify(sig_bytes, raw)
    except (InvalidSignature, ValueError, KeyError, TypeError) as exc:
        raise UpdateError("更新签名无效或签名密钥不受信任") from exc
    return read_json(raw)


def common(data: dict) -> None:
    if type(data.get("schema")) is not int or data["schema"] != 1:
        raise UpdateError("不支持的更新协议版本")
    if data.get("product") != "bilix" or data.get("channel") != "stable":
        raise UpdateError("更新产品或渠道不匹配")
    version(data.get("version"))


def validate_channel(
    data: dict, *, sequence: int = 0, previous_hash: str = "", raw: bytes = b""
) -> dict:
    common(data)
    timestamp(data.get("issued_at"))
    current = number(data.get("metadata_sequence"), 2**53 - 1)
    if current < sequence or (
        current == sequence and previous_hash and hashlib.sha256(raw).hexdigest() != previous_hash
    ):
        raise UpdateError("更新元数据序号倒退或相同序号内容改变")
    tag = release_tag(data.get("release_tag"), data["version"])
    digest(data.get("manifest_sha256"))
    number(data.get("manifest_bytes"), MAX_METADATA)
    if data.get("manifest_urls") != release_urls(tag, "update-manifest.json"):
        raise UpdateError("更新清单来源不合法")
    return data


@dataclass(frozen=True)
class Artifact:
    artifact_id: str
    version: str
    tag: str
    filename: str
    size: int
    sha256: str
    urls: tuple[str, ...]
    package_version: str

    def verify_file(self, path: Path) -> None:
        if not path.is_file() or path.stat().st_size != self.size or sha256(path) != self.sha256:
            raise UpdateError("更新包大小或 SHA256 校验失败")


def select_artifact(manifest: dict, channel: dict, artifact_id: str) -> Artifact:
    common(manifest)
    timestamp(manifest.get("published_at"))
    if (
        manifest["version"] != channel["version"]
        or manifest.get("release_tag") != channel["release_tag"]
        or type(manifest.get("min_updater_schema")) is not int
        or manifest.get("min_updater_schema") != 1
        or manifest.get("config_compatibility") != "backup-before-migration"
    ):
        raise UpdateError("清单版本或兼容性不匹配")
    if manifest.get("release_notes_url") != f"{GITHUB}/tag/{manifest['release_tag']}":
        raise UpdateError("发行说明链接不合法")
    entries = manifest.get("artifacts")
    if not isinstance(entries, list) or not 1 <= len(entries) <= 32:
        raise UpdateError("更新产物列表不合法")
    matches = [
        item
        for item in entries
        if isinstance(item, dict) and item.get("artifact_id") == artifact_id
    ]
    if len(matches) != 1 or artifact_id not in ARTIFACT_IDS:
        raise UpdateError("没有唯一匹配当前安装形式的更新包")
    item = matches[0]
    platform, arch, kind, scope = ARTIFACT_IDS[artifact_id]
    if [item.get(k) for k in ("platform", "arch", "package_type", "install_scope")] != [
        platform,
        arch,
        kind,
        scope,
    ]:
        raise UpdateError("更新包平台、架构或安装身份不匹配")
    name = filename(item.get("filename"))
    package_version = item.get("package_version")
    if kind == "deb":
        if (
            not isinstance(package_version, str)
            or not re.fullmatch(rf"{re.escape(manifest['version'])}-[1-9][0-9]*", package_version)
            or name != f"djhx-bilix-gui_{package_version}_amd64.deb"
        ):
            raise UpdateError("Debian 包名或版本不匹配")
        if item.get("os_constraints") != {"glibc_min": "2.35"}:
            raise UpdateError("不支持的 Linux 兼容性要求")
    else:
        label = "Portable" if kind == "portable" else "Setup"
        if (
            package_version != manifest["version"]
            or name != f"BiliX-GUI-{label}-{manifest['version']}-windows-x64.exe"
            or item.get("os_constraints") != {"windows_min": 10}
        ):
            raise UpdateError("Windows 包名、版本或兼容性不匹配")
    urls = release_urls(manifest["release_tag"], name)
    if item.get("urls") != urls:
        raise UpdateError("更新包镜像位置不合法")
    return Artifact(
        artifact_id,
        manifest["version"],
        manifest["release_tag"],
        name,
        number(item.get("bytes"), MAX_ARTIFACT),
        digest(item.get("sha256")),
        tuple(urls),
        package_version,
    )


def verify_bundle(
    blobs: dict[str, bytes], artifact_id: str, keys: dict[str, str] | None = None, **watermark
) -> tuple[dict, Artifact]:
    channel = validate_channel(
        verify_signed(blobs["stable.json"], blobs["stable.json.sig"], keys),
        raw=blobs["stable.json"],
        **watermark,
    )
    raw = blobs["update-manifest.json"]
    if (
        len(raw) != channel["manifest_bytes"]
        or hashlib.sha256(raw).hexdigest() != channel["manifest_sha256"]
    ):
        raise UpdateError("更新清单与渠道描述绑定不匹配")
    manifest = verify_signed(raw, blobs["update-manifest.json.sig"], keys)
    return channel, select_artifact(manifest, channel, artifact_id)
