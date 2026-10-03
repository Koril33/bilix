"""Run Gitleaks offline without printing secret values or copying ignored files."""

import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def summary(report: Path) -> list[dict]:
    if not report.exists():
        return []
    findings = json.loads(report.read_text(encoding="utf-8-sig")) or []
    return [
        {
            "rule": finding.get("RuleID"),
            "path": finding.get("File"),
            "line": finding.get("StartLine"),
            "commit": finding.get("Commit", "")[:12],
        }
        for finding in findings
    ]


def scan(binary: str, target: Path, report: Path, *, history: bool) -> int:
    command = [
        binary,
        "git" if history else "dir",
        "--no-banner",
        "--redact=100",
        "--config",
        str(ROOT / ".gitleaks.toml"),
        "--report-format",
        "json",
        "--report-path",
        str(report),
    ]
    if history:
        command.append("--log-opts=--all")
    result = subprocess.run([*command, str(target)], capture_output=True, cwd=ROOT)
    if result.returncode not in (0, 1):
        # A scanner error might echo source text. Preserve it privately, never print it.
        report.with_suffix(".error.log").write_bytes(result.stderr)
        print(f"Scanner failed; inspect {report.with_suffix('.error.log')} privately")
        return 2
    findings = summary(report)
    for finding in findings:
        print(json.dumps(finding, ensure_ascii=False))
    print(f"{'history' if history else 'working-tree'}: {len(findings)} findings")
    return result.returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scope", choices=("working-tree", "history", "both"), default="working-tree"
    )
    parser.add_argument("--binary", help="Path to a separately installed Gitleaks executable")
    args = parser.parse_args()
    binary = args.binary or shutil.which("gitleaks")
    if not binary or not Path(binary).is_file():
        parser.error("Install official Gitleaks or provide --binary; see SECURITY.md")
    binary = str(Path(binary).resolve())
    reports = ROOT / "build/security"
    reports.mkdir(parents=True, exist_ok=True)
    codes = []
    if args.scope in ("working-tree", "both"):
        paths = subprocess.check_output(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=ROOT,
        ).split(b"\0")
        with tempfile.TemporaryDirectory(prefix="working-tree-", dir=reports) as directory:
            export = Path(directory)
            for item in set(paths) - {b""}:
                relative = Path(item.decode("utf-8"))
                source = ROOT / relative
                if not source.exists():
                    continue  # A tracked file deleted in the working tree.
                if not source.resolve().is_relative_to(ROOT) or not source.is_file():
                    parser.error("Refusing to scan a path outside the repository or a submodule")
                destination = export / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
            codes.append(scan(binary, export, reports / "working-tree.json", history=False))
    if args.scope in ("history", "both"):
        codes.append(scan(binary, ROOT, reports / "history.json", history=True))
    raise SystemExit(max(codes))


if __name__ == "__main__":
    main()
