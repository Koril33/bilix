"""Verify and stage the Python, CLI and GUI artifacts for one public release.

Run after ``uv build``, Windows CLI packaging, both GUI packaging scripts,
and ``scripts/assemble_gui_release.py``. Only the files listed in the output
manifest should be uploaded to the release page.
"""

import json
import re
import shutil
import tarfile
import zipfile
from email.parser import Parser
from io import BytesIO
from pathlib import Path, PurePosixPath

from assemble_gui_release import DIST as GUI_DIST
from assemble_gui_release import assemble as assemble_gui
from gui_release import ROOT, artifact_manifest, deb_version, sha256, source_version

from djhx_bilix import __version__

PYTHON_DIST = ROOT / "dist" / f"python-{__version__}"
CLI_DIST = ROOT / "dist" / "cli"
RELEASE_DIST = ROOT / "dist" / f"release-{__version__}"
FORBIDDEN_ARCHIVE_PARTS = {".git", ".vagrant", ".venv", "__pycache__"}
FORBIDDEN_ARCHIVE_NAMES = {".env", "id_rsa", "id_ed25519", "credentials"}
FORBIDDEN_ARCHIVE_SUFFIXES = {".key", ".pem", ".p12", ".pfx", ".rsa"}
DEB_REQUIRED_FILES = {
    "usr/bin/bilix-gui",
    "usr/lib/djhx-bilix-gui/bilix-gui",
    "usr/share/applications/djhx-bilix-gui.desktop",
    "usr/share/icons/hicolor/scalable/apps/djhx-bilix-gui.svg",
    "usr/share/doc/djhx-bilix-gui/LICENSE",
    "usr/share/doc/djhx-bilix-gui/THIRD_PARTY_NOTICES.md",
    "usr/share/doc/djhx-bilix-gui/SOURCE-ACCESS.md",
    "usr/share/doc/djhx-bilix-gui/LICENSES/BiliX-GPL-3.0.txt",
    "usr/share/doc/djhx-bilix-gui/LICENSES/Python-LICENSE.txt",
    "usr/share/doc/djhx-bilix-gui/LICENSES/nuitka-runtime/LICENSE-RUNTIME.txt",
    "usr/share/doc/djhx-bilix-gui/LICENSES/nuitka-runtime/NOTICE.txt",
    "usr/share/doc/djhx-bilix-gui/LICENSES/pyside6-essentials/WHEEL-LICENSE.txt",
}


def _verify_public_member(name: str, *, allow_certifi_bundle: bool = False) -> None:
    path = PurePosixPath(name.replace("\\", "/"))
    expected_certifi_bundle = PurePosixPath("usr/lib/djhx-bilix-gui/certifi/cacert.pem")
    if (
        not name
        or any(ord(character) < 32 for character in name)
        or path.is_absolute()
        or ".." in path.parts
        or (path.parts and ":" in path.parts[0])
        or any(part.lower() in FORBIDDEN_ARCHIVE_PARTS for part in path.parts)
        or path.name.lower() in FORBIDDEN_ARCHIVE_NAMES
        or (
            path.suffix.lower() in FORBIDDEN_ARCHIVE_SUFFIXES
            and not (allow_certifi_bundle and path == expected_certifi_bundle)
        )
    ):
        raise RuntimeError(f"Public archive includes an unsafe path: {name}")


def _read_ar_members(path: Path) -> dict[str, bytes]:
    """Read the small Debian ar container without relying on dpkg tools."""
    members = {}
    archive_size = path.stat().st_size
    with path.open("rb") as stream:
        if stream.read(8) != b"!<arch>\n":
            raise RuntimeError(f"Debian package has an invalid ar header: {path.name}")
        while header := stream.read(60):
            if len(header) != 60 or header[58:] != b"`\n":
                raise RuntimeError("Debian package has a malformed ar member")
            try:
                name = header[:16].decode("ascii").strip().removesuffix("/")
                size = int(header[48:58].decode("ascii").strip())
            except (UnicodeDecodeError, ValueError) as exc:
                raise RuntimeError("Debian package has a malformed ar member") from exc
            if name in members or size < 0 or size > archive_size - stream.tell():
                raise RuntimeError(f"Debian package repeats or corrupts ar member: {name}")
            body = stream.read(size)
            if len(body) != size or (size % 2 and stream.read(1) != b"\n"):
                raise RuntimeError(f"Debian package truncates ar member: {name}")
            members[name] = body
    return members


def _verify_deb_tar(payload: bytes, label: str) -> dict[str, tarfile.TarInfo]:
    """Reject unsafe paths and special entries before inspecting required files."""
    entries = {}
    try:
        with tarfile.open(fileobj=BytesIO(payload), mode="r:*") as archive:
            for member in archive:
                _verify_public_member(member.name, allow_certifi_bundle=label == "data")
                name = str(PurePosixPath(member.name.replace("\\", "/")))
                if not (member.isfile() or member.isdir()):
                    raise RuntimeError(
                        f"Debian {label} includes a link or special file: {member.name}"
                    )
                if name in entries:
                    raise RuntimeError(f"Debian {label} repeats path: {member.name}")
                entries[name] = member
    except (tarfile.TarError, OSError) as exc:
        raise RuntimeError(f"Cannot inspect Debian {label} archive") from exc
    return entries


def _verify_deb(path: Path) -> None:
    members = _read_ar_members(path)
    if members.get("debian-binary") != b"2.0\n":
        raise RuntimeError("Debian package has the wrong format version")
    control_names = [name for name in members if name.startswith("control.tar.")]
    data_names = [name for name in members if name.startswith("data.tar.")]
    if len(control_names) != 1 or len(data_names) != 1 or len(members) != 3:
        raise RuntimeError("Debian package lacks exactly one control and data archive")
    control_name, data_name = control_names[0], data_names[0]
    if not all(name.endswith((".zst", ".xz", ".gz", ".bz2")) for name in (control_name, data_name)):
        raise RuntimeError("Debian package has an unsupported tar compression format")

    control_entries = _verify_deb_tar(members[control_name], "control")
    control = control_entries.get("control")
    if control is None or not control.isfile():
        raise RuntimeError("Debian package lacks its control file")
    with tarfile.open(fileobj=BytesIO(members[control_name]), mode="r:*") as archive:
        control_file = archive.extractfile(control)
        if control_file is None or control.size > 1_000_000:
            raise RuntimeError("Debian control file is unavailable or oversized")
        try:
            content = control_file.read().decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RuntimeError("Debian control file is not UTF-8") from exc
    fields = {}
    for line in content.splitlines():
        if not line or line[0] in " \t":
            continue
        field, separator, value = line.partition(":")
        if not separator or field in fields:
            raise RuntimeError("Debian control file has malformed or repeated fields")
        fields[field] = value.strip()
    expected = {
        "Package": "djhx-bilix-gui",
        "Version": deb_version(),
        "Architecture": "amd64",
    }
    for field, value in expected.items():
        if fields.get(field) != value:
            raise RuntimeError(f"Debian control field {field} does not match {value}")
    if not re.fullmatch(r"[^<>\r\n]+ <[^<>\s@]+@[^<>\s@]+>", fields.get("Maintainer", "")):
        raise RuntimeError("Debian control file lacks a valid Maintainer")

    data_entries = _verify_deb_tar(members[data_name], "data")
    missing = sorted(
        name
        for name in DEB_REQUIRED_FILES
        if name not in data_entries
        or not data_entries[name].isfile()
        or not data_entries[name].size
    )
    if missing:
        raise RuntimeError(f"Debian data archive lacks required files: {missing}")
    for name in ("usr/bin/bilix-gui", "usr/lib/djhx-bilix-gui/bilix-gui"):
        if not data_entries[name].mode & 0o111:
            raise RuntimeError(f"Debian executable lacks execute permission: {name}")
    with tarfile.open(fileobj=BytesIO(members[data_name]), mode="r:*") as archive:
        desktop = data_entries["usr/share/applications/djhx-bilix-gui.desktop"]
        if desktop.size > 64_000:
            raise RuntimeError("Debian desktop entry is oversized")
        desktop_file = archive.extractfile(desktop)
        if desktop_file is None:
            raise RuntimeError("Debian desktop entry cannot be read")
        try:
            desktop_fields = desktop_file.read().decode("utf-8").splitlines()
        except UnicodeDecodeError as exc:
            raise RuntimeError("Debian desktop entry is not UTF-8") from exc
        for line in (
            "[Desktop Entry]",
            "Type=Application",
            "Exec=bilix-gui",
            "Icon=djhx-bilix-gui",
        ):
            if line not in desktop_fields:
                raise RuntimeError(f"Debian desktop entry lacks {line}")


def _verify_public_archive(path: Path) -> None:
    if path.suffix == ".zip" or path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            for member in archive.infolist():
                _verify_public_member(member.filename)
                if member.external_attr >> 16 & 0o170000 == 0o120000:
                    raise RuntimeError(f"Public archive includes a symlink: {member.filename}")
    elif path.name.endswith(".tar.gz"):
        with tarfile.open(path, "r:gz") as archive:
            for member in archive:
                _verify_public_member(member.name)
                if member.issym() or member.islnk():
                    raise RuntimeError(f"Public archive includes a symlink: {member.name}")
    elif path.suffix == ".deb":
        _verify_deb(path)


def _verify_python_identity(metadata: bytes, source: bytes, label: str) -> None:
    """Read package identity without executing archived application source."""
    try:
        headers = Parser().parsestr(metadata.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise RuntimeError(f"Python {label} identity is not valid UTF-8 source/metadata") from exc
    names = headers.get_all("Name", [])
    versions = headers.get_all("Version", [])
    if len(names) != 1 or re.sub(r"[-_.]+", "-", names[0].lower()) != "djhx-bilix":
        raise RuntimeError(f"Python {label} metadata has the wrong or repeated package name")
    if versions != [__version__]:
        raise RuntimeError(f"Python {label} metadata has the wrong or repeated version")
    if source_version(source, f"Python {label} source") != __version__:
        raise RuntimeError(f"Python {label} source version differs from release metadata")


def _verify_python_wheel(path: Path) -> None:
    if path.name != f"djhx_bilix-{__version__}-py3-none-any.whl":
        raise RuntimeError("Python wheel filename has the wrong version or tag")
    with zipfile.ZipFile(path) as archive:
        if archive.testzip() is not None:
            raise RuntimeError(f"Wheel ZIP integrity check failed: {path.name}")
        names = archive.namelist()
        metadata = f"djhx_bilix-{__version__}.dist-info/METADATA"
        initializer = "djhx_bilix/__init__.py"
        if (
            metadata not in names
            or initializer not in names
            or "djhx_bilix/gui/app.py" not in names
        ):
            raise RuntimeError("Python wheel lacks its metadata or GUI source")
        metadata_names = [name for name in names if name.endswith(".dist-info/METADATA")]
        if metadata_names != [metadata] or names.count(initializer) != 1:
            raise RuntimeError("Python wheel has mixed or repeated package identity")
        if any(archive.getinfo(name).file_size > 1_000_000 for name in (metadata, initializer)):
            raise RuntimeError("Python wheel package identity is oversized")
        _verify_python_identity(archive.read(metadata), archive.read(initializer), "wheel")


def _verify_python_sdist(path: Path) -> None:
    if path.name != f"djhx_bilix-{__version__}.tar.gz":
        raise RuntimeError("Python sdist filename has the wrong version")
    with tarfile.open(path, "r:gz") as archive:
        names = archive.getnames()
        prefix = f"djhx_bilix-{__version__}/"
        for name in (
            "LICENSE",
            "src/djhx_bilix/gui/app.py",
            "scripts/assemble_gui_release.py",
            "PKG-INFO",
            "src/djhx_bilix/__init__.py",
        ):
            if prefix + name not in names:
                raise RuntimeError(f"Python sdist lacks {name}")
        if any(name != prefix.rstrip("/") and not name.startswith(prefix) for name in names):
            raise RuntimeError("Python sdist contains mixed source version roots")
        identity = []
        for name in (prefix + "PKG-INFO", prefix + "src/djhx_bilix/__init__.py"):
            member = archive.getmember(name)
            if names.count(name) != 1 or not member.isfile() or member.size > 1_000_000:
                raise RuntimeError(
                    "Python sdist has repeated, invalid or oversized package identity"
                )
            stream = archive.extractfile(member)
            if stream is None:
                raise RuntimeError("Python sdist package identity cannot be read")
            identity.append(stream.read())
        _verify_python_identity(*identity, "sdist")


def _verify_cli_zip(path: Path) -> None:
    with zipfile.ZipFile(path) as archive:
        if archive.testzip() is not None:
            raise RuntimeError(f"CLI ZIP integrity check failed: {path.name}")
        names = set(archive.namelist())
        for name in (
            "bilix.exe",
            "LICENSE",
            "THIRD_PARTY_NOTICES.md",
            "README.windows.md",
            "LICENSES/Python-LICENSE.txt",
            "LICENSES/nuitka-runtime/LICENSE-RUNTIME.txt",
            "LICENSES/nuitka-runtime/NOTICE.txt",
            "LICENSES/DISTRIBUTIONS.json",
            "vendor/ffmpeg/COPYING.GPLv3",
            "scripts/build_ffmpeg.sh",
        ):
            if name not in names:
                raise RuntimeError(f"CLI ZIP lacks {name}")
        if not any(name.endswith("ffmpeg-7.1.5.tar.xz") for name in names):
            raise RuntimeError("CLI ZIP lacks the corresponding FFmpeg source")


def stage_release(destination: Path = RELEASE_DIST) -> list[Path]:
    gui_paths = assemble_gui(GUI_DIST)
    wheel = PYTHON_DIST / f"djhx_bilix-{__version__}-py3-none-any.whl"
    sdist = PYTHON_DIST / f"djhx_bilix-{__version__}.tar.gz"
    cli = CLI_DIST / f"bilix-{__version__}-windows-x64.zip"
    for path in (wheel, sdist, cli):
        if not path.is_file():
            raise RuntimeError(f"Required release artifact is missing: {path}")
    _verify_python_wheel(wheel)
    _verify_python_sdist(sdist)
    _verify_cli_zip(cli)
    for path in (*gui_paths, wheel, sdist, cli):
        _verify_public_archive(path)

    sources = [*gui_paths, wheel, sdist, cli]
    expected = {path.name for path in sources} | {"release-manifest.json", "SHA256SUMS.txt"}
    destination.mkdir(parents=True, exist_ok=True)
    unexpected = {path.name for path in destination.iterdir()} - expected
    if unexpected:
        raise RuntimeError(f"Release directory has unlisted files: {sorted(unexpected)}")
    staged = []
    for source in sources:
        target = destination / source.name
        shutil.copy2(source, target)
        if sha256(target) != sha256(source):
            raise RuntimeError(f"Release staging changed {source.name}")
        staged.append(target)
    artifact_manifest(staged, destination / "release-manifest.json")
    manifest = json.loads((destination / "release-manifest.json").read_text(encoding="utf-8"))
    if len(manifest["artifacts"]) != 8:
        raise RuntimeError("A complete release needs five GUI files, two Python files, and CLI ZIP")
    return staged


def main() -> None:
    for path in stage_release():
        print(f"Verified and staged: {path}")


if __name__ == "__main__":
    main()
