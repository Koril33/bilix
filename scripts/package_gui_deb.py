"""Turn the verified Linux standalone runtime into a rootless .deb package.

Build on Ubuntu 22.04 amd64 after scripts/build_gui_linux.py. The resulting
package still needs clean Ubuntu/Debian desktop install and upgrade tests.
"""

import argparse
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

from gui_release import (
    ROOT,
    STANDALONE_NAME,
    artifact_manifest,
    collect_licenses,
    copy_sources,
    deb_version,
    require_version_identity,
    sha256,
)

from djhx_bilix import __version__

BUILD = ROOT / "build" / "gui" / "linux"
DIST = ROOT / "dist" / "gui"
PACKAGE = "djhx-bilix-gui"
ARCH = "amd64"


def require_environment() -> None:
    require_version_identity()
    if sys.platform != "linux" or platform.machine() != "x86_64":
        raise RuntimeError("The first .deb must be built on Linux x86_64")
    release = platform.freedesktop_os_release()
    if release.get("ID") != "ubuntu" or release.get("VERSION_ID") != "22.04":
        raise RuntimeError("Build on Ubuntu 22.04 x64 for the supported glibc baseline")
    if sys.version_info[:3] != (3, 14, 8):
        raise RuntimeError("GUI release packaging requires CPython 3.14.8")
    for name in ("dpkg-deb", "dpkg-shlibdeps", "readelf"):
        if shutil.which(name) is None:
            raise RuntimeError(f"Install the Debian build tool providing {name}")


def require_smoked(executable: Path) -> None:
    record = BUILD / "smoke.txt"
    if not executable.is_file() or not record.is_file():
        raise RuntimeError("Build and start-check the Linux GUI first")
    content = record.read_text(encoding="utf-8")
    if "exit_code=0\n" not in content or f"sha256={sha256(executable)}\n" not in content:
        raise RuntimeError("The Linux GUI start check is stale")


def elf_files(directory: Path) -> list[Path]:
    files = []
    for path in directory.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        with path.open("rb") as stream:
            if stream.read(4) == b"\x7fELF":
                files.append(path)
    return files


def private_shlibs(source_root: Path, binaries: list[Path]) -> None:
    """Describe bundled SONAMEs so dpkg-shlibdeps does not require system Qt."""
    entries = set()
    for binary in binaries:
        if ".so" not in binary.name:
            continue
        result = subprocess.run(["readelf", "-d", str(binary)], capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(f"Could not inspect bundled ELF {binary}: {result.stderr.strip()}")
        match = re.search(r"\(SONAME\).*?\[([^\]]+)\]", result.stdout)
        if match is None:
            continue  # Plugins without SONAME do not need shlibs metadata.
        soname = match.group(1)
        parts = re.fullmatch(r"(.+)\.so\.(.+)", soname)
        if parts is None:
            parts = re.fullmatch(r"(.+)-([^-]+)\.so", soname)
        if parts is None:
            raise RuntimeError(f"Unsupported bundled library SONAME: {soname}")
        library, version = parts.groups()
        entries.add(f"{library} {version} {PACKAGE} (>= {deb_version()})")
    if not entries:
        raise RuntimeError("No bundled shared libraries found for Debian dependency scan")
    (source_root / "debian" / "shlibs.local").write_text(
        "\n".join(sorted(entries)) + "\n", encoding="utf-8"
    )


def shared_library_dependencies(source_root: Path, runtime: Path) -> list[str]:
    """Resolve package requirements from every bundled ELF, including Qt plugins."""
    binaries = elf_files(runtime)
    if not binaries:
        raise RuntimeError("The standalone directory contains no ELF binaries")
    private_shlibs(source_root, binaries)
    private_directories = sorted({str(path.parent) for path in binaries if ".so" in path.name})
    dependencies = set()
    for offset in range(0, len(binaries), 40):
        chunk = binaries[offset : offset + 40]
        command = [
            "dpkg-shlibdeps",
            "-O",
            f"-x{PACKAGE}",
            *[f"-l{path}" for path in private_directories],
        ]
        command.extend(f"-e{path}" for path in chunk)
        result = subprocess.run(command, cwd=source_root, capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(
                "dpkg-shlibdeps could not resolve bundled ELF requirements:\n"
                + result.stderr.strip()
            )
        for line in result.stdout.splitlines():
            if line.startswith("shlibs:Depends="):
                dependencies.update(
                    item.strip() for item in line.partition("=")[2].split(",") if item.strip()
                )
    dependencies = {
        dependency
        for dependency in dependencies
        if dependency != PACKAGE and not dependency.startswith(f"{PACKAGE} ")
    }
    return sorted(dependencies)


def stage_package(source_root: Path, maintainer: str) -> tuple[Path, Path]:
    package_root = source_root / "debian" / PACKAGE
    runtime = package_root / "usr" / "lib" / PACKAGE
    runtime.parent.mkdir(parents=True)
    shutil.copytree(BUILD / STANDALONE_NAME, runtime)
    if not (runtime / "bilix-gui").is_file():
        raise RuntimeError("The Linux standalone entry executable is missing")

    launcher = package_root / "usr" / "bin" / "bilix-gui"
    launcher.parent.mkdir(parents=True)
    launcher.write_text(f'#!/bin/sh\nexec /usr/lib/{PACKAGE}/bilix-gui "$@"\n', encoding="utf-8")
    launcher.chmod(0o755)
    desktop = package_root / "usr" / "share" / "applications" / f"{PACKAGE}.desktop"
    desktop.parent.mkdir(parents=True)
    desktop.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Version=1.0\n"
        "Name=BiliX\n"
        "GenericName=Video downloader\n"
        "Comment=Download supported Bilibili videos\n"
        "Exec=bilix-gui\n"
        f"Icon={PACKAGE}\n"
        "Terminal=false\n"
        "Categories=Network;AudioVideo;\n"
        "StartupNotify=true\n",
        encoding="utf-8",
    )
    icon = (
        package_root
        / "usr"
        / "share"
        / "icons"
        / "hicolor"
        / "scalable"
        / "apps"
        / f"{PACKAGE}.svg"
    )
    icon.parent.mkdir(parents=True)
    shutil.copy2(ROOT / "scripts" / "installer" / "bilix-gui.svg", icon)

    doc = package_root / "usr" / "share" / "doc" / PACKAGE
    doc.mkdir(parents=True)
    shutil.copy2(ROOT / "LICENSE", doc / "LICENSE")
    shutil.copy2(ROOT / "THIRD_PARTY_NOTICES.md", doc / "THIRD_PARTY_NOTICES.md")
    collect_licenses(doc / "LICENSES", linux=True)
    source_dir = source_root / "SOURCES"
    copy_sources(source_dir, linux=True)
    shutil.copy2(source_dir / "SOURCE-ACCESS.md", doc / "SOURCE-ACCESS.md")

    # dpkg-shlibdeps needs a source control file beside debian/<package>/.
    (source_root / "debian" / "control").write_text(
        f"Source: {PACKAGE}\n"
        "Section: net\n"
        "Priority: optional\n"
        f"Maintainer: {maintainer}\n"
        "Standards-Version: 4.7.0\n\n"
        f"Package: {PACKAGE}\n"
        "Architecture: any\n"
        "Depends: ${shlibs:Depends}, ffmpeg\n"
        "Description: BiliX desktop video downloader\n"
        " PySide6 frontend for the BiliX downloader.\n",
        encoding="utf-8",
    )
    dynamic_deps = shared_library_dependencies(source_root, runtime)
    required = ["ffmpeg", *dynamic_deps]
    required = list(dict.fromkeys(required))
    if not any(dep.startswith("libc6 ") or dep == "libc6" for dep in required):
        raise RuntimeError("Generated dependencies did not include libc6; inspect the ELF scan")
    installed_kib = (
        sum(p.stat().st_size for p in package_root.rglob("*") if p.is_file()) + 1023
    ) // 1024
    control = package_root / "DEBIAN" / "control"
    control.parent.mkdir()
    control.write_text(
        f"Package: {PACKAGE}\n"
        f"Version: {deb_version()}\n"
        "Section: net\n"
        "Priority: optional\n"
        f"Architecture: {ARCH}\n"
        f"Maintainer: {maintainer}\n"
        f"Installed-Size: {installed_kib}\n"
        f"Depends: {', '.join(required)}\n"
        "Homepage: https://github.com/Koril33/bilix\n"
        "Description: BiliX desktop video downloader\n"
        " PySide6 interface for supported Bilibili downloads.\n"
        " Includes its own Python and Qt runtime. FFmpeg comes from the\n"
        " Ubuntu/Debian package declared above.\n",
        encoding="utf-8",
    )
    return package_root, source_dir


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--maintainer",
        required=True,
        help='Debian maintainer, for example "Name <mail@example.org>"',
    )
    args = parser.parse_args()
    if not re.fullmatch(r"[^<>\r\n]+ <[^<>\s@]+@[^<>\s@]+>", args.maintainer):
        parser.error("--maintainer must be a single 'Name <email>' value")
    require_environment()
    require_smoked(BUILD / STANDALONE_NAME / "bilix-gui")
    DIST.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="gui-deb-", dir=BUILD) as raw_temporary:
        temporary = Path(raw_temporary)
        package_root, source_dir = stage_package(temporary, args.maintainer)
        deb = DIST / f"{PACKAGE}_{deb_version()}_{ARCH}.deb"
        subprocess.run(
            ["dpkg-deb", "--build", "--root-owner-group", str(package_root), str(deb)],
            check=True,
        )
        source_archive = DIST / f"{PACKAGE}_{__version__}_source.tar.gz"
        with tarfile.open(source_archive, "w:gz") as archive:
            archive.add(source_dir, arcname=f"{PACKAGE}-{__version__}-source")
    subprocess.run(["dpkg-deb", "--field", str(deb)], check=True)
    subprocess.run(["dpkg-deb", "--contents", str(deb)], check=True, stdout=subprocess.DEVNULL)
    artifact_manifest(
        [deb, source_archive],
        DIST / "release-manifest-linux.json",
        checksums_destination=DIST / "SHA256SUMS-linux.txt",
    )
    print(f"Prepared GUI .deb: {deb}")
    print(f"Prepared BiliX source archive: {source_archive}")


if __name__ == "__main__":
    main()
