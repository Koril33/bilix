"""Verify and publish the existing trusted stable/main/amd64 APT repository.

Immutable pool/by-hash files are installed first, ordinary indexes next, and
Release.gpg/Release/InRelease last. The final three files are separate renames,
not a single atomic transaction. Failed staging directories remain for diagnosis.
No old repository files are deleted. --check performs no remote writes.
An interrupted SSH session can leave an owned lock. Inspect owner.json and its
matching staging record, confirm no uploader remains active, then release only
that owned lock before retrying. Never discard staging or another operation's lock.
"""

from __future__ import annotations

import argparse
import base64
import bz2
import gzip
import hashlib
import inspect
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import tarfile
import tempfile
import time
import uuid
from pathlib import Path, PurePosixPath

REMOTE_HOST = "bilix@djhx.site"
REMOTE_ROOT = "/var/www/bilix.djhx.site/apt"
TRUSTED_FINGERPRINT = "201A20E104EF3C72CE573F7E61323BAA3BB87821"
KEY_PATH = "keys/bilix-archive-key.asc"
RELEASE_PATH = "dists/stable/Release"
ALGORITHMS = {"MD5Sum": "md5", "SHA1": "sha1", "SHA256": "sha256", "SHA512": "sha512"}
MAX_INDEX = 64 * 1024 * 1024
MAX_TOTAL = 4 * 1024**3


def safe_path(value: str) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or value != path.as_posix()
        or path.is_absolute()
        or ".." in path.parts
        or not re.fullmatch(r"[A-Za-z0-9_./+~-]+", value)
    ):
        raise ValueError(f"Unsafe APT path: {value!r}")
    return value


def ordinary_path(path: Path, *, directory=False) -> None:
    for candidate in (path, *path.parents):
        info = candidate.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(
            stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0
        ):
            raise ValueError("APT inputs must not use symlinks or reparse points")
    info = path.stat()
    if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
        raise ValueError("Expected a regular APT file or directory")


def digest(path: Path, algorithm="sha256") -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, algorithm).hexdigest()


def deb822(data: bytes) -> list[dict[str, str]]:
    records = []
    for block in data.decode("utf-8").strip().split("\n\n"):
        fields: dict[str, str] = {}
        previous = None
        for line in block.splitlines():
            if line.startswith((" ", "\t")) and previous:
                fields[previous] += "\n" + line.strip()
            else:
                key, separator, value = line.partition(":")
                if not separator or key in fields or not re.fullmatch(r"[A-Za-z0-9-]+", key):
                    raise ValueError("Malformed or duplicate APT metadata field")
                fields[key] = value.strip()
                previous = key
        if fields:
            records.append(fields)
    return records


def _gpg(arguments: list[str]) -> bytes:
    result = subprocess.run(arguments, check=True, capture_output=True, timeout=60)
    return result.stdout


def verify_signatures(directory: Path) -> str:
    """Use an isolated public-only keyring, anchored to the existing fingerprint."""
    key = directory / KEY_PATH
    if key.stat().st_size > 1024 * 1024 or b"PRIVATE KEY" in key.read_bytes():
        raise ValueError("Expected the existing public APT key only")
    with tempfile.TemporaryDirectory(prefix="bilix-apt-verification-") as temporary:
        home = Path(temporary)
        home.chmod(0o700)
        options = ["gpg", "--batch", "--no-options", "--homedir", home.as_posix()]
        shown = _gpg([*options, "--with-colons", "--show-keys", key.as_posix()])
        primary = []
        pending_primary = False
        for line in shown.decode("utf-8").splitlines():
            fields = line.split(":")
            if fields[0] in {"sec", "ssb"}:
                raise ValueError("Private key material cannot be published")
            if fields[0] in {"pub", "sub"} and (
                fields[1] in {"r", "e", "d"}
                or (fields[6] not in {"", "0"} and int(fields[6]) <= time.time())
            ):
                raise ValueError("Expired, revoked or disabled APT signing key")
            if fields[0] == "pub":
                pending_primary = True
            elif fields[0] == "fpr" and pending_primary:
                primary.append(fields[9].upper())
                pending_primary = False
        if primary != [TRUSTED_FINGERPRINT]:
            raise ValueError("APT public key differs from the existing trusted fingerprint")
        keyring = home / "trusted.gpg"
        _gpg([*options, "--dearmor", "--output", keyring.as_posix(), key.as_posix()])
        verifier = [
            "gpgv",
            "--homedir",
            home.as_posix(),
            "--keyring",
            keyring.as_posix(),
            "--status-fd",
            "1",
        ]

        def verify(arguments):
            paths = [item.as_posix() if isinstance(item, Path) else str(item) for item in arguments]
            output = _gpg([*verifier, *paths]).decode("utf-8")
            statuses = [
                line.split() for line in output.splitlines() if line.startswith("[GNUPG:] ")
            ]
            valid = [fields for fields in statuses if len(fields) > 1 and fields[1] == "VALIDSIG"]
            forbidden = ("BADSIG", "ERRSIG", "EXPSIG", "EXPKEYSIG", "REVKEYSIG", "KEYREVOKED")
            if (
                len(valid) != 1
                or len(valid[0]) < 11
                or TRUSTED_FINGERPRINT not in (valid[0][2].upper(), valid[0][-1].upper())
                or any(len(fields) > 1 and fields[1] in forbidden for fields in statuses)
                or (valid[0][5] != "0" and int(valid[0][5]) <= time.time())
                or valid[0][9] not in {"8", "9", "10", "11"}
            ):
                raise ValueError("APT signature is not valid under the existing trust root")

        verify([directory / (RELEASE_PATH + ".gpg"), directory / RELEASE_PATH])
        plaintext = home / "inrelease.txt"
        verify(["--output", plaintext, directory / "dists/stable/InRelease"])
        if (
            plaintext.read_bytes().replace(b"\r\n", b"\n")
            != (directory / RELEASE_PATH).read_bytes()
        ):
            raise ValueError("InRelease and detached-signed Release contain different metadata")
    return TRUSTED_FINGERPRINT


def verify_public(directory: Path) -> dict:
    directory = directory.absolute()
    ordinary_path(directory, directory=True)
    files: dict[str, Path] = {}
    for path in directory.rglob("*"):
        ordinary_path(path, directory=path.is_dir())
        if path.is_file():
            name = safe_path(path.relative_to(directory).as_posix())
            files[name] = path
    for name in (KEY_PATH, RELEASE_PATH, RELEASE_PATH + ".gpg", "dists/stable/InRelease"):
        if name not in files or files[name].stat().st_size > 1024 * 1024:
            raise ValueError(f"Missing or oversized APT signing material: {name}")
    if sum(path.stat().st_size for path in files.values()) > MAX_TOTAL:
        raise ValueError("APT public tree exceeds the publication size limit")
    fingerprint = verify_signatures(directory)
    release_records = deb822(files[RELEASE_PATH].read_bytes())
    if len(release_records) != 1:
        raise ValueError("Release must contain one metadata record")
    release = release_records[0]
    for key, expected in {
        "Suite": "stable",
        "Codename": "stable",
        "Architectures": "amd64",
        "Components": "main",
        "Acquire-By-Hash": "yes",
    }.items():
        if release.get(key) != expected:
            raise ValueError(f"Unexpected APT Release {key}")
    sections = {}
    logical_contents: dict[str, bytes] = {}
    for field, algorithm in ALGORITHMS.items():
        values = {}
        for line in release.get(field, "").splitlines():
            if not line:
                continue
            checksum, size, name = line.split()
            name = safe_path(name)
            if name in values or not re.fullmatch(r"[0-9a-f]+", checksum):
                raise ValueError("Invalid or duplicate Release checksum")
            index = "dists/stable/" + name
            if index not in files:
                # Aptly 1.4.0 index_files.go's onlyGzip publishes .gz while
                # recording both compressed and logical uncompressed hashes.
                if (
                    name not in {"Contents-amd64", "main/Contents-amd64"}
                    or index + ".gz" not in files
                ):
                    raise ValueError(f"Missing or oversized signed APT index: {index}")
                if index not in logical_contents:
                    with gzip.open(files[index + ".gz"], "rb") as stream:
                        logical_contents[index] = stream.read(MAX_INDEX + 1)
                data = logical_contents[index]
                actual_size = len(data)
                actual_hash = hashlib.new(algorithm, data).hexdigest()
            else:
                actual_size = files[index].stat().st_size
                actual_hash = digest(files[index], algorithm)
            if actual_size > MAX_INDEX or actual_size != int(size) or actual_hash != checksum:
                raise ValueError(f"Signed APT index differs: {index}")
            values[index] = checksum
        sections[field] = values
    signed_indexes = set(sections["SHA256"])
    if (
        not signed_indexes
        or not sections["SHA512"]
        or any(values and set(values) != signed_indexes for values in sections.values())
    ):
        raise ValueError("Release checksum sections must cover the same indexes")
    package_index = "dists/stable/main/binary-amd64/Packages"
    if package_index not in signed_indexes:
        raise ValueError("Release does not authenticate the amd64 Packages index")
    for field, values in sections.items():
        for name, checksum in values.items():
            if name in logical_contents:
                if name + ".gz" not in signed_indexes:
                    raise ValueError("Logical Contents must have an authenticated gzip variant")
                continue
            hashed = str(PurePosixPath(name).parent / "by-hash" / field / checksum)
            if hashed not in files or digest(files[hashed], ALGORITHMS[field]) != checksum:
                raise ValueError(f"Missing or inconsistent current by-hash index: {name}")
    for name in signed_indexes:
        if name.endswith((".gz", ".bz2")):
            uncompressed = name.rsplit(".", 1)[0]
            opener = gzip.open if name.endswith(".gz") else bz2.open
            with opener(files[name], "rb") as stream:
                expanded = stream.read(MAX_INDEX + 1)
            plain = logical_contents.get(uncompressed)
            if plain is None and uncompressed in files:
                plain = files[uncompressed].read_bytes()
            if uncompressed not in signed_indexes or expanded != plain:
                raise ValueError(f"Compressed APT index differs from its plain index: {name}")
    packages = deb822(files[package_index].read_bytes())
    seen = set()
    for package in packages:
        name = safe_path(package.get("Filename", ""))
        version = package.get("Version", "")
        expected = f"pool/main/d/djhx-bilix-gui/djhx-bilix-gui_{version}_amd64.deb"
        if (
            package.get("Package") != "djhx-bilix-gui"
            or package.get("Architecture") != "amd64"
            or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+-[1-9][0-9]*", version)
            or name != expected
            or name in seen
            or name not in files
        ):
            raise ValueError("Unexpected, duplicate or missing APT package")
        seen.add(name)
        if files[name].stat().st_size != int(package.get("Size", "-1")) or digest(
            files[name]
        ) != package.get("SHA256"):
            raise ValueError(f"APT package differs from Packages index: {name}")
    if not packages:
        raise ValueError("APT Packages index is empty")
    selected = []
    aliases = []
    for name, path in sorted(files.items()):
        if "/by-hash/" in name:
            prefix, algorithm, checksum = name.rsplit("/", 2)
            if algorithm not in ALGORITHMS or prefix.rsplit("/", 1)[0] not in {
                str(PurePosixPath(index).parent) for index in signed_indexes
            }:
                raise ValueError(f"Unexpected by-hash location: {name}")
            if re.fullmatch(r"[0-9a-f]+", checksum):
                if digest(path, ALGORITHMS[algorithm]) != checksum:
                    raise ValueError(f"Incorrect content-addressed APT file: {name}")
            elif re.fullmatch(
                r"(?:Packages(?:\.(?:gz|bz2))?|Contents-amd64(?:\.gz)?|Release)(?:\.old)?", checksum
            ):
                # Aptly may leave regular-file aliases after export. They are mutable
                # implementation details, not public content-addressed objects.
                aliases.append(name)
                continue
            else:
                raise ValueError(f"Unexpected by-hash filename: {name}")
        elif name.startswith("pool/"):
            if not re.fullmatch(
                r"pool/main/d/djhx-bilix-gui/djhx-bilix-gui_[0-9]+\.[0-9]+\.[0-9]+-[1-9][0-9]*_amd64\.deb",
                name,
            ):
                raise ValueError(f"Unexpected pool file: {name}")
        elif name not in signed_indexes | {
            KEY_PATH,
            RELEASE_PATH,
            RELEASE_PATH + ".gpg",
            "dists/stable/InRelease",
        }:
            raise ValueError(f"Unexpected APT public file: {name}")
        selected.append({"path": name, "bytes": path.stat().st_size, "sha256": digest(path)})
    return {
        "fingerprint": fingerprint,
        "files": selected,
        "ignored_aliases": aliases,
        "logical_indexes": sorted(logical_contents),
    }


def remote_operation(payload, root="/var/www/bilix.djhx.site/apt", check_identity=True):
    """Self-contained server operation; also exercised against isolated test roots."""
    import hashlib
    import json
    import os
    import re
    import stat
    import tarfile
    import time
    from pathlib import Path

    root = Path(root)
    if root.resolve() != root or not root.is_dir():
        raise RuntimeError("Unexpected APT root")
    if check_identity:
        import pwd

        if os.getuid() == 0 or pwd.getpwuid(os.getuid()).pw_name != "bilix":
            raise RuntimeError("APT publication must run as bilix")
    if not os.access(root, os.W_OK | os.X_OK):
        raise RuntimeError("APT root is not writable")
    if stat.S_IMODE(root.stat().st_mode) & 0o055 != 0o055:
        raise RuntimeError("APT root is not publicly readable and traversable")
    records = payload["files"]
    by_name = {}
    for item in records:
        name = item["path"]
        if (
            not re.fullmatch(r"(?:pool/|dists/stable/|keys/)[A-Za-z0-9_./+~-]+", name)
            or any(part in {"", ".", ".."} for part in name.split("/"))
            or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"])
            or not isinstance(item["bytes"], int)
            or item["bytes"] < 0
            or name in by_name
        ):
            raise RuntimeError("Invalid APT publication manifest")
        by_name[name] = item

    def checked(name, base=root):
        path = base / name
        for candidate in (path, *path.parents):
            if candidate == base.parent:
                break
            if candidate.is_symlink():
                raise RuntimeError("Symlink in APT publication path")
            if candidate.exists() and candidate != path and not candidate.is_dir():
                raise RuntimeError("Non-directory in APT publication path")
        if path.exists() and not stat.S_ISREG(path.stat().st_mode):
            raise RuntimeError("APT destination is not a regular file")
        return path

    def matches(path, item):
        if path.stat().st_size != item["bytes"]:
            return False
        with path.open("rb") as stream:
            checksum = hashlib.sha256()
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                checksum.update(chunk)
        return checksum.hexdigest() == item["sha256"]

    def immutable(name):
        return name.startswith(("pool/", "keys/")) or "/by-hash/" in name

    def preflight():
        for name, item in by_name.items():
            path = checked(name)
            if path.exists() and stat.S_IMODE(path.stat().st_mode) & 0o004 != 0o004:
                raise RuntimeError("Existing APT file is not publicly readable: " + name)
            if path.exists() and immutable(name) and not matches(path, item):
                raise RuntimeError("Refusing to change immutable APT file or existing key: " + name)
            for parent in path.parents:
                if parent.exists() and not os.access(parent, os.W_OK | os.X_OK):
                    raise RuntimeError("APT destination directory is not writable")
                if parent.exists() and stat.S_IMODE(parent.stat().st_mode) & 0o055 != 0o055:
                    raise RuntimeError("Existing APT directory is not publicly traversable")
                if parent == root:
                    break

    action = payload["action"]
    if action == "check":
        preflight()
        return {"status": "checked", "account": "bilix", "files": len(records)}
    token = payload["token"]
    if not re.fullmatch(r"[0-9a-f]{32}", token):
        raise RuntimeError("Invalid staging identity")
    stage = root / (".staging-" + token)
    lock = root / ".publish-lock"

    def report(status, **extra):
        data = {"status": status, "token": token, "time": int(time.time()), **extra}
        (stage / "status.json").write_text(json.dumps(data, sort_keys=True), encoding="utf-8")

    def release_lock():
        owner = lock / "owner.json"
        if (
            lock.is_symlink()
            or owner.is_symlink()
            or json.loads(owner.read_text())["token"] != token
        ):
            raise RuntimeError("Publication lock belongs to another operation")
        owner.unlink()
        lock.rmdir()

    if action == "begin":
        preflight()
        lock.mkdir(mode=0o700)
        try:
            (lock / "owner.json").write_text(json.dumps({"token": token}), encoding="utf-8")
            stage.mkdir(mode=0o700)
            (stage / "manifest.json").write_text(
                json.dumps(records, sort_keys=True), encoding="utf-8"
            )
            report("awaiting-upload")
        except Exception:
            # This call created the lock exclusively; owner.json may not have
            # finished writing. Only these known paths can be removed here.
            (lock / "owner.json").unlink(missing_ok=True)
            lock.rmdir()
            raise
        return {"status": "staged", "staging": str(stage)}
    if lock.is_symlink() or (lock / "owner.json").is_symlink():
        raise RuntimeError("Missing or unsafe APT transaction")
    if json.loads((lock / "owner.json").read_text())["token"] != token:
        raise RuntimeError("APT transaction is owned by another operation")
    completed = []
    phase = "verifying-upload"
    try:
        if stage.is_symlink() or not stage.is_dir() or (stage / "manifest.json").is_symlink():
            raise RuntimeError("Missing or unsafe APT staging")
        if action == "abort":
            report("upload-failed")
            return {"status": "upload-failed", "staging": str(stage)}
        if action != "commit":
            raise RuntimeError("Unknown APT operation")
        if json.loads((stage / "manifest.json").read_text()) != records:
            raise RuntimeError("APT transaction differs from its preparation")
        preflight()
        source_root = stage / "files"
        source_root.mkdir(mode=0o700)
        archive_path = checked("upload.tar", stage)
        with tarfile.open(archive_path, "r:") as archive:
            members = archive.getmembers()
            if len(members) != len(records) or {item.name for item in members} != set(by_name):
                raise RuntimeError("Uploaded APT archive has missing or unexpected entries")
            for member in members:
                item = by_name[member.name]
                if not member.isfile() or member.size != item["bytes"]:
                    raise RuntimeError("APT archive contains non-file or wrong-size entries")
                path = checked(member.name, source_root)
                path.parent.mkdir(parents=True, exist_ok=True)
                stream = archive.extractfile(member)
                with path.open("xb") as target, stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        target.write(chunk)
                    target.flush()
                    os.fsync(target.fileno())
                if not matches(path, item):
                    raise RuntimeError("Uploaded APT bytes differ from the verified manifest")
        preflight()
        final = ("dists/stable/Release.gpg", "dists/stable/Release", "dists/stable/InRelease")
        order = sorted(by_name, key=lambda name: (0 if immutable(name) else 1, name))
        order = [name for name in order if name not in final] + list(final)
        phase = "activating"
        report("activating", completed=[])
        for name in order:
            item = by_name[name]
            source = checked(name, source_root)
            target = checked(name)
            missing = []
            parent = target.parent
            while not parent.exists():
                missing.append(parent)
                parent = parent.parent
            for parent in reversed(missing):
                parent.mkdir(mode=0o755)
                parent.chmod(0o755)  # Do not let a restrictive umask hide public files.
            source.chmod(0o644)
            if immutable(name):
                if not target.exists():
                    os.link(source, target)  # exclusive creation, never overwrites a racing writer
                if not matches(target, item):
                    raise RuntimeError("Immutable APT destination changed during publication")
                source.unlink()  # Avoid a staging hard link to a public immutable file.
            else:
                os.replace(source, target)
            completed.append(name)
            if hasattr(os, "O_DIRECTORY"):
                descriptor = os.open(target.parent, os.O_DIRECTORY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            report("activating", completed=completed)
        report("published", completed=completed, atomic_group=False)
        return {
            "status": "published",
            "files": len(records),
            "staging": str(stage),
            "atomic_group": False,
        }
    except Exception:
        if not stage.is_symlink() and stage.is_dir():
            report(
                "failed",
                phase=phase,
                completed=completed,
                atomic_group=False,
                recovery="Inspect this staging record, then rerun the same verified public tree. "
                "Release signatures may temporarily disagree; never disable APT verification.",
            )
        raise
    finally:
        release_lock()


def ssh_tools(*, system=None, system_root=None) -> tuple[str, str]:
    """Prefer native Windows OpenSSH even when Git's GPG directory leads PATH."""
    if (system or os.name) == "nt":
        root = Path(system_root or os.environ.get("SystemRoot", "C:/Windows"))
        binaries = [root / "System32/OpenSSH" / f"{name}.exe" for name in ("ssh", "scp")]
        return tuple(
            str(path) if path.is_file() else name for path, name in zip(binaries, ("ssh", "scp"))
        )
    return "ssh", "scp"


def _publish_verified(directory: Path, ssh_key: Path, report: dict, *, check=False) -> dict:
    ordinary_path(
        ssh_key.absolute()
    )  # Only inspect key path metadata, never read credential bytes.
    options = ["-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes", "-i", str(ssh_key.absolute())]
    ssh, scp = ssh_tools()
    code = (
        inspect.getsource(remote_operation)
        + "\nprint(json.dumps(remote_operation(json.load(sys.stdin))))"
    )
    code = "import json, sys\n" + code
    encoded = base64.b64encode(code.encode("utf-8")).decode("ascii")
    command = "python3 -c " + shlex.quote(f'import base64;exec(base64.b64decode("{encoded}"))')
    token = uuid.uuid4().hex

    def remote(action):
        payload = {"action": action, "token": token, "files": report["files"]}
        try:
            result = subprocess.run(
                [ssh, *options, REMOTE_HOST, command],
                input=json.dumps(payload).encode("utf-8"),
                check=False,
                capture_output=True,
                timeout=300,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(
                f"APT remote {action} timed out; server outcome must be checked"
            ) from None
        if result.returncode:
            detail = result.stderr.decode("utf-8", errors="replace")[-1200:]
            raise RuntimeError(f"APT remote {action} failed (exit {result.returncode}): {detail}")
        return json.loads(result.stdout)

    if check:
        return {
            **remote("check"),
            "fingerprint": report["fingerprint"],
            "ignored_aliases": report["ignored_aliases"],
            "logical_indexes": report["logical_indexes"],
        }
    with tempfile.TemporaryDirectory(prefix="bilix-apt-upload-") as temporary:
        archive_path = Path(temporary) / "upload.tar"
        with tarfile.open(archive_path, "w") as archive:
            for item in report["files"]:
                path = directory / item["path"]
                ordinary_path(path)
                info = tarfile.TarInfo(item["path"])
                info.size = item["bytes"]
                info.mode = 0o644
                with path.open("rb") as stream:
                    archive.addfile(info, stream)
        ownership = (
            f"Inspect {REMOTE_ROOT}/.publish-lock/owner.json and "
            f"{REMOTE_ROOT}/.staging-{token}/status.json (owner token {token}). "
            "If a lock remains, confirm no active publisher and release only this matching lock "
            "before rerunning the same verified public tree; never remove another owner's lock."
        )
        try:
            remote("begin")
        except Exception as error:
            raise RuntimeError(
                f"APT preparation failed or its outcome is unknown. {ownership} {error}"
            ) from None
        try:
            subprocess.run(
                [
                    scp,
                    "-S",
                    ssh,
                    *options,
                    str(archive_path),
                    f"{REMOTE_HOST}:{REMOTE_ROOT}/.staging-{token}/upload.tar",
                ],
                check=True,
                capture_output=True,
                timeout=1800,
            )
        except Exception:
            try:
                remote("abort")
            except Exception:
                raise RuntimeError(
                    f"APT upload failed; lock release could not be confirmed. {ownership}"
                ) from None
            raise RuntimeError(
                f"APT upload failed; its lock was released and staging remains at "
                f"{REMOTE_ROOT}/.staging-{token}."
            ) from None
        try:
            result = remote("commit")
        except Exception:
            raise RuntimeError(
                f"APT activation failed; evidence remains at {REMOTE_ROOT}/.staging-{token}. "
                f"{ownership} Do not disable signature verification."
            ) from None
        return {
            **result,
            "fingerprint": report["fingerprint"],
            "ignored_aliases": report["ignored_aliases"],
            "logical_indexes": report["logical_indexes"],
        }


def publish(directory: Path, ssh_key: Path, *, check=False) -> dict:
    initial = verify_public(directory)
    with tempfile.TemporaryDirectory(prefix="bilix-apt-snapshot-") as temporary:
        snapshot = Path(temporary) / "public"
        snapshot.mkdir()
        for item in initial["files"]:
            source = directory / item["path"]
            ordinary_path(source)
            destination = snapshot / item["path"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(source, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(descriptor, "rb") as stream, destination.open("xb") as output:
                shutil.copyfileobj(stream, output)
        # Revalidate the fixed snapshot; an aptly export may have changed the
        # input between its first verification and the snapshot copy.
        verified = verify_public(snapshot)
        verified["ignored_aliases"] = initial["ignored_aliases"]
        return _publish_verified(snapshot, ssh_key, verified, check=check)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--directory", type=Path, required=True, help="Complete signed APT public tree"
    )
    parser.add_argument("--ssh-key", type=Path, required=True, help="Existing bilix SSH key path")
    parser.add_argument(
        "--check", action="store_true", help="Read-only verification; no remote writes"
    )
    args = parser.parse_args()
    print(json.dumps(publish(args.directory, args.ssh_key, check=args.check), sort_keys=True))


if __name__ == "__main__":
    main()
