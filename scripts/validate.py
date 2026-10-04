"""Repeatable offline checks; keep evidence separate from immutable release files."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import platform
import re
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote, urlsplit

from assemble_gui_release import expected_names
from assemble_release import (
    _verify_cli_zip,
    _verify_public_archive,
    _verify_python_sdist,
    _verify_python_wheel,
)
from gui_release import ROOT, sha256

from djhx_bilix import __version__


def check_docs(root: Path = ROOT) -> dict:
    """Check relative Markdown file links without requiring network access."""
    documents = sorted(
        {*root.glob("*.md"), *(root / "docs").rglob("*.md"), root / "site/README.md"}
    )
    missing = []
    links = 0
    for document in documents:
        # Examples inside fenced code are not actual document links.
        content = re.sub(r"```.*?```", "", document.read_text(encoding="utf-8"), flags=re.S)
        for match in re.finditer(r"\]\((<[^>]+>|[^\s)]+)(?:\s+\"[^\"]*\")?\)", content):
            target = match[1].strip("<>")
            parsed = urlsplit(target)
            if parsed.scheme or target.startswith(("#", "//")):
                continue
            links += 1
            if not (document.parent / unquote(parsed.path)).exists():
                missing.append(f"{document.relative_to(root).as_posix()}: {target}")
    if missing:
        raise RuntimeError("Missing documentation targets: " + "; ".join(missing))
    return {"documents": len(documents), "local_file_links": links}


def verify_release(directory: Path) -> dict:
    """Read, hash and inspect a complete release; never reassemble or overwrite it."""
    directory = directory.resolve()
    manifest = json.loads((directory / "release-manifest.json").read_text(encoding="utf-8"))
    if manifest.get("version") != __version__:
        raise RuntimeError("Release version differs from this checkout; use its matching revision")
    expected = set.union(*expected_names().values()) | {
        f"djhx_bilix-{__version__}-py3-none-any.whl",
        f"djhx_bilix-{__version__}.tar.gz",
        f"bilix-{__version__}-windows-x64.zip",
    }
    records = manifest.get("artifacts", [])
    if len(records) != len(expected) or {record.get("name") for record in records} != expected:
        raise RuntimeError("Release manifest has missing, repeated or unexpected artifacts")
    sums = []
    for record in sorted(records, key=lambda item: item["name"]):
        path = directory / record["name"]
        if not path.resolve().is_relative_to(directory) or not path.is_file():
            raise RuntimeError(f"Missing or external release artifact: {path.name}")
        if path.stat().st_size != record.get("bytes") or sha256(path) != record.get("sha256"):
            raise RuntimeError(f"Release artifact differs from manifest: {path.name}")
        _verify_public_archive(path)
        if path.suffix == ".whl":
            _verify_python_wheel(path)
        elif path.name.startswith("djhx_bilix-"):
            _verify_python_sdist(path)
        elif path.name.startswith("bilix-"):
            _verify_cli_zip(path)
        sums.append(f"{record['sha256']}  {path.name}\n")
    if (directory / "SHA256SUMS.txt").read_text(encoding="utf-8") != "".join(sums):
        raise RuntimeError("Release checksums differ from the manifest")
    return {"version": __version__, "artifacts": records}


def pytest_summary(path: Path) -> dict:
    root = ET.parse(path).getroot()
    cases = list(root.iter("testcase"))
    skips = [
        {"test": f"{case.get('classname')}.{case.get('name')}", "reason": node.get("message")}
        for case in cases
        if (node := case.find("skipped")) is not None
    ]
    failures = sum(case.find("failure") is not None for case in cases)
    errors = sum(case.find("error") is not None for case in cases)
    return {
        "passed": len(cases) - len(skips) - failures - errors,
        "failed": failures,
        "errors": errors,
        "skipped": skips,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("cli", "gui"), default="gui")
    parser.add_argument("--release-dir", type=Path, help="Read-only final artifact inspection")
    parser.add_argument("--strict-skips", action="store_true", help="Fail on every pytest skip")
    args = parser.parse_args(argv)
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    evidence = ROOT / "build/validation" / __version__ / f"{args.profile}-{run_id}"
    evidence.mkdir(parents=True)
    record = {
        "schema_version": 1,
        "version": __version__,
        "profile": args.profile,
        "started_utc": datetime.now(UTC).isoformat(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "checks": [],
        "status": "failed",
    }
    environment = os.environ.copy()
    environment.update(
        PYTHONUTF8="1",
        BILIX_CONFIG_DIR=str(evidence / "profile"),
        BILIX_DOWNLOAD_DIR=str(evidence / "downloads"),
        QT_QPA_PLATFORM="offscreen",
    )
    environment.pop("BILIX_FFMPEG", None)

    def run(name: str, arguments: list[str], expected_exit: int = 0) -> None:
        started = time.monotonic()
        log = evidence / f"{name}.log"
        with log.open("wb") as stream:
            result = subprocess.run(
                [sys.executable, *arguments],
                cwd=ROOT,
                env=environment,
                stdout=stream,
                stderr=subprocess.STDOUT,
                timeout=600,
            )
        record["checks"].append(
            {
                "name": name,
                "exit": result.returncode,
                "seconds": round(time.monotonic() - started, 2),
            }
        )
        if result.returncode != expected_exit:
            raise RuntimeError(f"{name} failed; inspect {log.relative_to(ROOT)}")
        print(f"PASS {name}", flush=True)

    try:
        record["commit"] = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
        record["working_tree"] = subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=ROOT, text=True, encoding="utf-8"
        ).splitlines()
        record["lock_sha256"] = sha256(ROOT / "uv.lock")
        packages = ["pytest", "ruff", "djhx-bilix"]
        if args.profile == "gui":
            packages.extend(["PySide6-Essentials", "shiboken6", "pytest-qt"])
        # Fail here instead of allowing importorskip to silently omit the whole GUI suite.
        record["dependencies"] = {name: importlib.metadata.version(name) for name in packages}
        record["docs"] = check_docs()
        run("ruff-check", ["-m", "ruff", "check", "src", "tests", "scripts"])
        run("ruff-format", ["-m", "ruff", "format", "--check", "src", "tests", "scripts"])
        test_args = ["-m", "pytest", "-q", "--junitxml", str(evidence / "pytest.xml")]
        test_args.extend(["--basetemp", str(evidence / "pytest-temp")])
        if args.profile == "cli":
            test_args.extend(["--ignore", "tests/gui"])
        run("pytest", test_args)
        record["pytest"] = pytest_summary(evidence / "pytest.xml")
        if args.strict_skips and record["pytest"]["skipped"]:
            raise RuntimeError(
                "pytest skipped tests; review pytest.xml or provide missing capabilities"
            )
        run("cli-version", ["-m", "djhx_bilix", "--version"])
        run("cli-help", ["-m", "djhx_bilix", "--help"])
        run("cli-doctor", ["-m", "djhx_bilix", "doctor"])
        run("cli-suggestion", ["-m", "djhx_bilix", "donwload"], expected_exit=2)
        for shell in ("powershell", "bash", "zsh", "fish"):
            run(f"completion-{shell}", ["-m", "djhx_bilix", "completion", shell])
        if args.profile == "gui":
            run("gui-smoke", ["-m", "djhx_bilix.gui", "--smoke-test"])
        if args.release_dir:
            record["release"] = verify_release(args.release_dir)
            print("PASS release-artifacts", flush=True)
        record["status"] = "passed"
    except (
        OSError,
        RuntimeError,
        ValueError,
        ET.ParseError,
        importlib.metadata.PackageNotFoundError,
        subprocess.SubprocessError,
    ) as error:
        record["error"] = str(error)
        print(f"FAIL {error}", file=sys.stderr)
    finally:
        if (evidence / "pytest.xml").is_file():
            try:
                record["pytest"] = pytest_summary(evidence / "pytest.xml")
            except (OSError, ET.ParseError) as error:
                record["status"] = "failed"
                record["pytest_report_error"] = str(error)
        record["finished_utc"] = datetime.now(UTC).isoformat()
        (evidence / "result.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"Evidence: {evidence}")
    return int(record["status"] != "passed")


if __name__ == "__main__":
    raise SystemExit(main())
