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


def test_version_metadata_mismatch_blocks_validation(validation):
    with pytest.raises(RuntimeError, match="differs from installed"):
        validation.check_version_metadata("1.7.1", "1.3.2")
    assert validation.check_version_metadata("1.7.1", "1.7.1") == {
        "source": "1.7.1",
        "installed": "1.7.1",
    }


@pytest.fixture
def validation_checkout(validation, monkeypatch, tmp_path):
    initializer = tmp_path / "src" / "djhx_bilix" / "__init__.py"
    initializer.parent.mkdir(parents=True)
    initializer.write_text('__version__ = "1.7.1"\n', encoding="utf-8")
    monkeypatch.setattr(validation, "ROOT", tmp_path)
    monkeypatch.setattr(validation, "__version__", "1.7.1")
    return validation, initializer


def test_validation_reads_checkout_and_accepts_matching_wheel(validation_checkout, monkeypatch):
    validation, initializer = validation_checkout
    package = importlib.import_module("djhx_bilix")
    monkeypatch.setattr(package, "__file__", str(initializer.parents[2] / "wheel/__init__.py"))
    assert validation.check_checkout_version_identity("1.7.1") == {
        "source": "1.7.1",
        "installed": "1.7.1",
        "imported": "1.7.1",
    }


def test_validation_rejects_equal_old_wheel_and_metadata(validation_checkout, monkeypatch):
    validation, _ = validation_checkout
    monkeypatch.setattr(validation, "__version__", "1.7.0")
    with pytest.raises(RuntimeError, match="Checkout source version 1.7.1.*imported.*1.7.0"):
        validation.check_checkout_version_identity("1.7.0")


def test_validation_rejects_current_import_with_stale_metadata(validation_checkout):
    validation, _ = validation_checkout
    with pytest.raises(RuntimeError, match="differs from installed.*1.7.0"):
        validation.check_checkout_version_identity("1.7.0")


def test_validation_main_rejects_old_wheel_before_checks(validation_checkout, monkeypatch):
    validation, initializer = validation_checkout
    root = initializer.parents[2]
    (root / "uv.lock").write_text("fixture", encoding="utf-8")
    monkeypatch.setattr(validation, "__version__", "1.7.0")
    monkeypatch.setattr(validation.importlib.metadata, "version", lambda _name: "1.7.0")
    monkeypatch.setattr(validation.subprocess, "check_output", lambda *_args, **_kwargs: "")

    def forbidden(*_args, **_kwargs):
        pytest.fail("Old wheel reached Ruff, pytest, or executable checks")

    monkeypatch.setattr(validation.subprocess, "run", forbidden)
    assert validation.main(["--profile", "cli"]) == 1
    reports = list(root.glob("build/validation/1.7.0/*/result.json"))
    assert len(reports) == 1
    record = json.loads(reports[0].read_text(encoding="utf-8"))
    assert record["status"] == "failed" and record["checks"] == []
    assert "Checkout source version 1.7.1" in record["error"]


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
