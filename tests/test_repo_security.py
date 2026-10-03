import json

from scripts.check_secrets import summary


def test_scanner_summary_never_contains_secret_or_matched_source(tmp_path):
    report = tmp_path / "report.json"
    report.write_text(
        json.dumps(
            [
                {
                    "RuleID": "bilibili-session-cookie",
                    "File": "legacy.py",
                    "StartLine": 24,
                    "Commit": "0123456789abcdef",
                    "Secret": "AUDIT_DUMMY_SECRET",
                    "Match": "Cookie: SESSDATA=AUDIT_DUMMY_SECRET",
                    "Message": "A source line that must not be printed",
                }
            ]
        ),
        encoding="utf-8",
    )
    result = summary(report)
    assert result == [
        {
            "rule": "bilibili-session-cookie",
            "path": "legacy.py",
            "line": 24,
            "commit": "0123456789ab",
        }
    ]
    assert "AUDIT_DUMMY_SECRET" not in json.dumps(result)


def test_empty_secret_report_is_supported(tmp_path):
    report = tmp_path / "empty.json"
    report.write_text("[]", encoding="utf-8")
    assert summary(report) == []
