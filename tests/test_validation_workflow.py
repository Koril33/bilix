"""Release evidence must fail closed on omitted or altered artifacts."""

import importlib
import json
from pathlib import Path

import pytest


@pytest.fixture
def validation(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    return importlib.import_module("validate")


def test_docs_check_reports_missing_relative_target(validation, tmp_path):
    (tmp_path / "site").mkdir()
    (tmp_path / "site/README.md").write_text("# Site", encoding="utf-8")
    (tmp_path / "README.md").write_text(
        "[missing](docs/missing.md)\n[remote](https://example.org)\n", encoding="utf-8"
    )
    with pytest.raises(RuntimeError, match="docs/missing.md"):
        validation.check_docs(tmp_path)


def test_pytest_summary_keeps_skip_reasons_and_failures(validation, tmp_path):
    report = tmp_path / "pytest.xml"
    report.write_text(
        '<testsuites><testsuite><testcase classname="gui" name="pass"/>'
        '<testcase classname="media" name="skip"><skipped message="missing encoder"/></testcase>'
        '<testcase name="fail"><failure/></testcase></testsuite></testsuites>',
        encoding="utf-8",
    )
    result = validation.pytest_summary(report)
    assert result["passed"] == 1
    assert result["failed"] == 1
    assert result["skipped"] == [{"test": "media.skip", "reason": "missing encoder"}]


def test_read_only_release_verification_rejects_tampering(validation, tmp_path, monkeypatch):
    monkeypatch.setattr(validation, "_verify_public_archive", lambda _path: None)
    monkeypatch.setattr(validation, "_verify_python_wheel", lambda _path: None)
    monkeypatch.setattr(validation, "_verify_python_sdist", lambda _path: None)
    monkeypatch.setattr(validation, "_verify_cli_zip", lambda _path: None)
    version = validation.__version__
    names = set.union(*validation.expected_names().values()) | {
        f"djhx_bilix-{version}-py3-none-any.whl",
        f"djhx_bilix-{version}.tar.gz",
        f"bilix-{version}-windows-x64.zip",
    }
    records = []
    for name in sorted(names):
        path = tmp_path / name
        path.write_bytes(b"fixture")
        records.append(
            {"name": name, "bytes": path.stat().st_size, "sha256": validation.sha256(path)}
        )
    manifest = tmp_path / "release-manifest.json"
    manifest.write_text(json.dumps({"version": version, "artifacts": records}), encoding="utf-8")
    checksums = tmp_path / "SHA256SUMS.txt"
    checksums.write_text(
        "".join(f"{item['sha256']}  {item['name']}\n" for item in records), encoding="utf-8"
    )
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    assert len(validation.verify_release(tmp_path)["artifacts"]) == 8
    assert before == {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    (tmp_path / records[0]["name"]).write_bytes(b"altered")
    with pytest.raises(RuntimeError, match="differs from manifest"):
        validation.verify_release(tmp_path)


def test_read_only_release_verification_rejects_incomplete_manifest(validation, tmp_path):
    (tmp_path / "release-manifest.json").write_text(
        json.dumps({"version": validation.__version__, "artifacts": []}), encoding="utf-8"
    )
    with pytest.raises(RuntimeError, match="missing, repeated or unexpected"):
        validation.verify_release(tmp_path)
