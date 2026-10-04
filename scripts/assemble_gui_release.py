"""Verify platform packages and assemble one GUI release checksum manifest.

Run after the Windows and Linux packaging scripts have placed their final
artifacts in ``dist/gui``. Platform manifests stay separate so either build
can be repeated without silently erasing the other platform's checksums.
"""

import json
from pathlib import Path

from gui_release import ROOT, artifact_manifest, deb_version, sha256

from djhx_bilix import __version__

DIST = ROOT / "dist" / "gui"


def expected_names() -> dict[str, set[str]]:
    return {
        "windows": {
            f"BiliX-GUI-Portable-{__version__}-windows-x64.exe",
            f"BiliX-GUI-Setup-{__version__}-windows-x64.exe",
            f"BiliX-GUI-licenses-and-source-{__version__}-windows-x64.zip",
        },
        "linux": {
            f"djhx-bilix-gui_{deb_version()}_amd64.deb",
            f"djhx-bilix-gui_{__version__}_source.tar.gz",
        },
    }


def verified_platform_artifacts(directory: Path, platform: str, names: set[str]) -> list[Path]:
    manifest = directory / f"release-manifest-{platform}.json"
    checksums = directory / f"SHA256SUMS-{platform}.txt"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if data.get("version") != __version__:
        raise RuntimeError(f"{manifest.name} does not match GUI version {__version__}")
    records = data.get("artifacts")
    if not isinstance(records, list) or {r.get("name") for r in records} != names:
        raise RuntimeError(f"{manifest.name} has missing or unexpected artifacts")
    if len(records) != len(names):
        raise RuntimeError(f"{manifest.name} repeats an artifact")
    expected_lines = []
    paths = []
    for record in sorted(records, key=lambda value: value["name"]):
        path = directory / record["name"]
        if not path.is_file() or path.stat().st_size != record.get("bytes"):
            raise RuntimeError(f"Missing or wrong-size GUI artifact: {path.name}")
        digest = sha256(path)
        if digest != record.get("sha256"):
            raise RuntimeError(f"GUI artifact changed after packaging: {path.name}")
        expected_lines.append(f"{digest}  {path.name}\n")
        paths.append(path)
    if checksums.read_text(encoding="utf-8") != "".join(expected_lines):
        raise RuntimeError(f"{checksums.name} does not match its platform manifest")
    return paths


def assemble(directory: Path = DIST) -> list[Path]:
    artifacts = []
    for platform, names in expected_names().items():
        artifacts.extend(verified_platform_artifacts(directory, platform, names))
    artifact_manifest(artifacts, directory / "release-manifest.json")
    return artifacts


def main() -> None:
    for path in assemble():
        print(f"Verified GUI release artifact: {path}")


if __name__ == "__main__":
    main()
