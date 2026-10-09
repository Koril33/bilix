"""Shared, fail-closed release helpers for the optional desktop application."""

import ast
import hashlib
import importlib.metadata
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import djhx_bilix
from djhx_bilix import __version__

ROOT = Path(__file__).resolve().parents[1]
GUI_ENTRY = ROOT / "scripts" / "gui_entry.py"
STANDALONE_NAME = "gui_entry.dist"
RUNTIME_PACKAGES = (
    "curl-cffi",
    "platformdirs",
    "pypng",
    "qrcode",
    "typer",
    "rich",
    "click",
    "cffi",
    "certifi",
    "colorama",
    "markdown-it-py",
    "mdurl",
    "pycparser",
    "pygments",
    "shellingham",
    "typing-extensions",
    "PySide6-Essentials",
    "shiboken6",
)


def source_version(content: bytes, label: str) -> str:
    """Read the unique constant version without running application code."""
    try:
        tree = ast.parse(content.decode("utf-8-sig"))
    except (UnicodeDecodeError, SyntaxError) as exc:
        raise RuntimeError(f"{label} is not valid UTF-8 Python source") from exc
    versions = []
    for statement in tree.body:
        if isinstance(statement, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__version__"
            for target in statement.targets
        ):
            if not isinstance(statement.value, ast.Constant) or not isinstance(
                statement.value.value, str
            ):
                raise RuntimeError(f"{label} version is not a constant string")
            versions.append(statement.value.value)
    if len(versions) != 1:
        raise RuntimeError(f"{label} must declare exactly one source version")
    return versions[0]


def require_version_identity() -> dict[str, str]:
    """Refuse stale installed metadata or imports from another build checkout."""
    initializer = ROOT / "src" / "djhx_bilix" / "__init__.py"
    expected = source_version(initializer.read_bytes(), "Build checkout")
    installed = importlib.metadata.version("djhx-bilix")
    if expected != __version__ or expected != installed:
        raise RuntimeError(
            f"Build checkout version {expected}, imported version {__version__}, and installed "
            f"djhx-bilix metadata {installed} differ; reinstall this checkout in an isolated "
            "environment and remove stale generated metadata from the import path"
        )
    if not djhx_bilix.__file__ or Path(djhx_bilix.__file__).resolve() != initializer.resolve():
        raise RuntimeError(
            "Build imports djhx-bilix from another checkout; use this editable source"
        )
    return {"source": expected, "imported": __version__, "installed": installed}


def version_parts() -> tuple[str, bool]:
    """Return a numeric OS file version and whether this is a preview build."""
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:\.dev(\d+))?", __version__)
    if match is None:
        raise RuntimeError(f"Unsupported GUI release version: {__version__}")
    major, minor, patch, dev = match.groups()
    numeric = f"{major}.{minor}.{patch}.0"
    return numeric, dev is not None


def deb_version() -> str:
    """Map PEP 440 dev releases below the matching stable Debian version."""
    _, preview = version_parts()
    return f"{__version__.replace('.dev', '~dev')}-1" if preview else f"{__version__}-1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact_manifest(
    paths: list[Path], destination: Path, *, checksums_destination: Path | None = None
) -> None:
    """Record only final distributable artifacts, never intermediate build files."""
    records = [
        {"name": path.name, "bytes": path.stat().st_size, "sha256": sha256(path)}
        for path in sorted(paths, key=lambda value: value.name)
    ]
    destination.write_text(
        json.dumps({"version": __version__, "artifacts": records}, indent=2) + "\n",
        encoding="utf-8",
    )
    if checksums_destination is None:
        checksums_destination = destination.parent / "SHA256SUMS.txt"
    checksums_destination.write_text(
        "".join(f"{record['sha256']}  {record['name']}\n" for record in records),
        encoding="utf-8",
    )


def _license_paths(distribution: importlib.metadata.Distribution) -> list[Path]:
    return [
        path
        for path in distribution.files or ()
        if any(word in path.name.casefold() for word in ("license", "licence", "copying", "notice"))
        and "dist-info" in str(path)
    ]


def collect_licenses(destination: Path, *, linux: bool) -> None:
    """Copy exact installed wheel notices and fail if a required notice is absent.

    Qt's community wheels declare several alternative open-source licenses in
    METADATA. BiliX distributes them under their GPL-3.0-only option and ships
    the complete GPL text from this repository beside the original wheel data.
    """
    destination.mkdir(parents=True, exist_ok=True)
    python_license = next(
        (
            path
            for name in ("LICENSE.txt", "LICENSE")
            if (path := Path(sys.base_prefix) / name).is_file()
        ),
        None,
    )
    if python_license is None:
        raise RuntimeError("Python runtime license is missing from the build interpreter")
    shutil.copy2(python_license, destination / "Python-LICENSE.txt")
    shutil.copy2(ROOT / "LICENSE", destination / "BiliX-GPL-3.0.txt")
    distributions = []
    for name in RUNTIME_PACKAGES:
        if linux and name == "colorama":
            # colorama is a Windows-only conditional dependency of Rich.
            continue
        distribution = importlib.metadata.distribution(name)
        target = destination / name.lower()
        target.mkdir()
        licenses = _license_paths(distribution)
        metadata = distribution.metadata
        qt_wheel = name in {"PySide6-Essentials", "shiboken6"}
        if name == "pypng":
            # The pypng wheel places its MIT license in the module header.
            header = Path(distribution.locate_file("png.py")).read_text(encoding="utf-8")
            header = header.split('"""', 1)[0]
            if "LICENCE (MIT)" not in header:
                raise RuntimeError("PyPNG license header is missing")
            (target / "LICENSE.txt").write_text(header, encoding="utf-8")
        elif not licenses and not (linux and qt_wheel):
            raise RuntimeError(f"No installed license files found for {name}")
        else:
            for index, license_path in enumerate(licenses):
                shutil.copy2(
                    distribution.locate_file(license_path), target / f"{index}-{license_path.name}"
                )
        if qt_wheel:
            declared = metadata.get("License", "")
            if "GPL-3.0-only" not in declared:
                raise RuntimeError(f"The {name} wheel no longer declares a GPL-3.0-only option")
            (target / "WHEEL-LICENSE.txt").write_text(
                f"{name} {distribution.version}\nLicense: {declared}\n"
                "BiliX uses the GPL-3.0-only option; see ../BiliX-GPL-3.0.txt.\n"
                + (
                    "The wheel's original notice is copied alongside this file.\n"
                    if licenses
                    else "The upstream Linux wheel has no separate license file; "
                    "this notice reproduces its METADATA license expression.\n"
                ),
                encoding="utf-8",
            )
        distributions.append({"name": name, "version": distribution.version})
    nuitka = importlib.metadata.distribution("Nuitka")
    nuitka_target = destination / "nuitka-runtime"
    nuitka_target.mkdir()
    for filename in ("LICENSE-RUNTIME.txt", "NOTICE.txt"):
        candidates = [p for p in _license_paths(nuitka) if p.name == filename]
        if not candidates:
            raise RuntimeError(f"Nuitka {filename} is missing")
        shutil.copy2(nuitka.locate_file(candidates[0]), nuitka_target / filename)
    if not linux:
        for path in sorted((ROOT / "vendor" / "ffmpeg" / "toolchain-licenses").glob("*.txt")):
            shutil.copy2(path, destination / path.name)
    (destination / "DISTRIBUTIONS.json").write_text(
        json.dumps(
            {
                "python": sys.version.split()[0],
                "nuitka": nuitka.version,
                "packages": distributions,
                "linux_ffmpeg": "system package dependency" if linux else "bundled 7.1.5 binary",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


SOURCE_ROOT_FILES = (
    "pyproject.toml",
    "uv.lock",
    ".python-version",
    "README.md",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
)
SOURCE_DIRECTORIES = {"src", "scripts", "tests", "docs"}
FORBIDDEN_SOURCE_PARTS = {".git", ".vagrant", ".venv", "__pycache__", "build", "dist"}
FORBIDDEN_SOURCE_NAMES = {".env", "id_rsa", "id_ed25519", "credentials"}
FORBIDDEN_SOURCE_SUFFIXES = {".key", ".pem", ".p12", ".pfx", ".rsa"}


def _source_file_list() -> list[Path]:
    """List release sources from Git or a NUL-delimited VM build manifest."""
    manifest = os.environ.get("BILIX_SOURCE_FILE_LIST")
    if manifest:
        raw = Path(manifest).read_bytes()
    else:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(ROOT),
                "ls-files",
                "--cached",
                "--others",
                "--exclude-standard",
                "-z",
            ],
            check=True,
            capture_output=True,
        )
        raw = result.stdout
    if not raw or not raw.endswith(b"\0"):
        raise RuntimeError("Source file list is empty or not NUL-delimited")
    return [Path(os.fsdecode(item)) for item in raw.split(b"\0") if item]


def copy_sources(destination: Path, *, linux: bool) -> None:
    """Copy only Git-selected release sources, excluding VM state and credentials."""
    destination.mkdir()
    selected = set(_source_file_list())
    missing = set(SOURCE_ROOT_FILES) - {str(path) for path in selected}
    if missing:
        raise RuntimeError(f"Required release sources missing: {', '.join(sorted(missing))}")
    root = ROOT.resolve()
    for relative in sorted(selected):
        parts = relative.parts
        if (
            not parts
            or relative.is_absolute()
            or ".." in parts
            or any(part.lower() in FORBIDDEN_SOURCE_PARTS for part in parts)
            or relative.name.lower() in FORBIDDEN_SOURCE_NAMES
            or relative.suffix.lower() in FORBIDDEN_SOURCE_SUFFIXES
        ):
            raise RuntimeError(f"Unsafe release source path: {relative}")
        allowed = (
            len(parts) == 1
            and parts[0] in SOURCE_ROOT_FILES
            or parts[0] in SOURCE_DIRECTORIES
            or not linux
            and parts[:2] == ("vendor", "ffmpeg")
        )
        if not allowed or linux and relative.suffix.lower() == ".exe":
            continue
        source = ROOT / relative
        if source.is_symlink():
            raise RuntimeError(f"Symlink release source is unsupported: {relative}")
        if not source.is_file():
            continue
        if not source.resolve().is_relative_to(root):
            raise RuntimeError(f"Release source escapes repository: {relative}")
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    (destination / "SOURCE-ACCESS.md").write_text(
        f"# BiliX GUI {__version__} source access\n\n"
        "The BiliX application source, build scripts and locked dependencies are\n"
        "enclosed here. The exact Qt 6.11.2 source archive is available at\n"
        "https://download.qt.io/archive/qt/6.11/6.11.2/single/"
        "qt-everywhere-src-6.11.2.tar.xz\n"
        "The exact Qt for Python 6.11.2 source archive is available at\n"
        "https://download.qt.io/official_releases/QtForPython/pyside6/"
        "PySide6-6.11.2-src/pyside-setup-everywhere-src-6.11.2.tar.xz\n"
        "These upstream archives must remain freely accessible from the public\n"
        "binary release instructions; provide a mirror if access changes.\n"
        + (
            "FFmpeg is supplied by the distribution's ffmpeg package.\n"
            if linux
            else "The corresponding Windows FFmpeg 7.1.5 source archive is enclosed.\n"
        ),
        encoding="utf-8",
    )
