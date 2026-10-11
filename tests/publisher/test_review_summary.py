"""Offline completion scenarios: CLI audit calls are mocked in disposable roots."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from publisher.cli import main


def _result(tmp_path: Path, severity: str | None, is_new: bool) -> dict:
    issue = {
        "severity": severity,
        "check": "astro_output" if severity == "blocking" else "image_preflight",
        "message": "A target needs attention",
        "details": {"source_body": "PRIVATE_BODY" * 1000},
    }
    active = [issue] if severity else []
    return {
        "findings": active + [
            {"severity": "info", "check": "source", "message": "OLD_INFO" * 1000}
        ],
        "new_findings": active if is_new else [],
        "blocking_count": int(severity == "blocking"),
        "recommendations": [{"code": "GENERIC_ADVICE", "reason": "REASON" * 1000}],
        "daily_summary": {
            "date": "20260627", "status": "DONE", "story_count": 10,
            "wechat_media_id": "wx_existing", "astro_status": "pushed",
            "astro_commit": "commit_existing", "compact_message": "USE_COMPACT",
        },
        "snapshot_path": str(tmp_path / "review.json"),
        "jsonl_path": str(tmp_path / "review.jsonl"),
    }


@pytest.mark.parametrize(
    ("severity", "is_new", "exit_code", "new_count"),
    [(None, False, 0, 0), ("warning", True, 0, 1),
     ("warning", False, 0, 0), ("blocking", False, 1, 0)],
)
def test_brief_review_keeps_outcomes_and_active_issues_without_full_evidence(
    tmp_path: Path, monkeypatch, severity: str | None, is_new: bool,
    exit_code: int, new_count: int,
) -> None:
    monkeypatch.chdir(tmp_path)
    audit = _result(tmp_path, severity, is_new)
    with patch("hn2md.stages.post_publish_audit.run_post_publish_audit", return_value=audit) as run:
        result = CliRunner().invoke(main, [
            "review-run", "hackernews", "--date", "2026-06-27", "--brief",
        ])
    assert result.exit_code == exit_code, result.output
    run.assert_called_once()
    brief, _ = json.JSONDecoder().raw_decode(result.output)
    assert brief["wechat_media_id"] == "wx_existing"
    assert brief["astro_commit"] == "commit_existing"
    assert brief["story_count"] == 10
    assert brief["new_issue_count"] == new_count
    assert brief["blocking_count"] == int(severity == "blocking")
    assert len(brief["issues"]) == int(severity is not None)
    if severity:
        assert brief["issues"][0]["new"] == is_new
    assert brief["snapshot_path"] == audit["snapshot_path"]
    for omitted in ("PRIVATE_BODY", "OLD_INFO", "GENERIC_ADVICE", "USE_COMPACT"):
        assert omitted not in result.output
    assert len(result.output) < 1200


def test_full_json_review_retains_diagnostic_evidence(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    audit = _result(tmp_path, "warning", True)
    with patch("hn2md.stages.post_publish_audit.run_post_publish_audit", return_value=audit):
        result = CliRunner().invoke(main, [
            "review-run", "hackernews", "--date", "2026-06-27", "--json",
        ])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == audit


def test_conflicting_review_formats_fail_before_writing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    with patch("hn2md.stages.post_publish_audit.run_post_publish_audit") as run:
        result = CliRunner().invoke(main, ["review-run", "hackernews", "--brief", "--json"])
    assert result.exit_code == 2
    run.assert_not_called()
    assert not (tmp_path / "output").exists()


def test_standard_review_does_not_prompt_compaction(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    audit = _result(tmp_path, None, False)
    audit["findings"] = []
    audit["recommendations"] = []
    audit["daily_summary"]["compact_safe"] = True
    with patch("hn2md.stages.post_publish_audit.run_post_publish_audit", return_value=audit):
        result = CliRunner().invoke(main, ["review-run", "hackernews", "--date", "2026-06-27"])
    assert result.exit_code == 0, result.output
    assert "USE_COMPACT" not in result.output
