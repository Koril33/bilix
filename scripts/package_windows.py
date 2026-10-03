"""Package a verified Windows exe with its licenses and corresponding FFmpeg source.

Run with the same Python environment used to build the executable.
"""

import argparse
import importlib.metadata
import json
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

from djhx_bilix import __version__

ROOT = Path(__file__).resolve().parents[1]
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
)


def collect_licenses(destination: Path) -> None:
    destination.mkdir(parents=True)
    shutil.copy2(Path(sys.base_prefix) / "LICENSE.txt", destination / "Python-LICENSE.txt")
    records = []
    for name in RUNTIME_PACKAGES:
        distribution = importlib.metadata.distribution(name)
        licenses = [
            path
            for path in distribution.files or []
            if any(word in path.name.lower() for word in ("license", "copying", "notice"))
        ]
        folder = destination / name
        folder.mkdir()
        if name == "pypng":
            # This distribution carries its MIT license in the png.py header.
            module = Path(distribution.locate_file("png.py")).read_text(encoding="utf-8")
            header = module.split('"""', 1)[0]
            if "LICENCE (MIT)" not in header:
                raise RuntimeError("PyPNG license header is missing")
            (folder / "LICENSE.txt").write_text(header, encoding="utf-8")
        elif not licenses:
            raise RuntimeError(f"Missing license files for {name}")
        else:
            for index, path in enumerate(licenses):
                shutil.copy2(distribution.locate_file(path), folder / f"{index}-{path.name}")
        records.append({"name": name, "version": distribution.version})
    (destination / "DISTRIBUTIONS.json").write_text(
        json.dumps({"python": sys.version.split()[0], "packages": records}, indent=2) + "\n",
        encoding="utf-8",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path)
    parser.add_argument("output", type=Path)
    arguments = parser.parse_args()
    executable = arguments.executable.resolve()
    if not executable.is_file():
        parser.error("Executable does not exist")
    output = arguments.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="windows-package-", dir=output.parent) as temporary:
        directory = Path(temporary)
        shutil.copy2(executable, directory / "bilix.exe")
        for name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
            shutil.copy2(ROOT / name, directory / name)
        shutil.copytree(ROOT / "vendor/ffmpeg", directory / "vendor/ffmpeg")
        (directory / "scripts").mkdir()
        shutil.copy2(ROOT / "scripts/build_ffmpeg.sh", directory / "scripts/build_ffmpeg.sh")
        collect_licenses(directory / "LICENSES")
        (directory / "README.windows.md").write_text(
            f"# BiliX {__version__} / Windows x64\n\n"
            "解压后在 bilix.exe 所在目录打开 PowerShell：\n\n"
            "```powershell\n.\\bilix.exe --help\n.\\bilix.exe auth login\n"
            ".\\bilix.exe download BV1j4411W7F7\n"
            ".\\bilix.exe completion powershell | Out-String | Invoke-Expression\n```\n\n"
            "无需安装 Python。FFmpeg 对应源码、构建脚本和许可在 vendor/ffmpeg 与 scripts；"
            "Python/运行依赖许可在 LICENSES。\n\n"
            "完整说明：https://github.com/Koril33/bilix/blob/main/README.md\n"
            "仅下载具备访问和保存权限的内容；不支持 DRM 或将试看保存为正片。\n",
            encoding="utf-8",
        )
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for path in sorted(directory.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(directory).as_posix())
    print(f"Packaged {output.name} ({output.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
