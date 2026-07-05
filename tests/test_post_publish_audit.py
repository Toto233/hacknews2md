"""Tests for the post-publish audit and JSONL writer."""

from __future__ import annotations

import json
from pathlib import Path

from src.utils.jsonl_writer import append_jsonl, read_jsonl


# ── JSONL writer tests ──────────────────────────────────────────────


def test_append_jsonl_creates_file(tmp_path: Path) -> None:
    p = tmp_path / "sub" / "trail.jsonl"
    append_jsonl(p, {"check": "test", "message": "hello"})
    assert p.exists()
    lines = p.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["check"] == "test"
    assert rec["message"] == "hello"
    assert "ts" in rec  # auto-injected


def test_append_jsonl_appends(tmp_path: Path) -> None:
    p = tmp_path / "trail.jsonl"
    append_jsonl(p, {"a": 1})
    append_jsonl(p, {"b": 2})
    records = read_jsonl(p)
    assert len(records) == 2
    assert records[0]["a"] == 1
    assert records[1]["b"] == 2


def test_read_jsonl_missing_file(tmp_path: Path) -> None:
    assert read_jsonl(tmp_path / "nope.jsonl") == []


def test_append_jsonl_preserves_provided_ts(tmp_path: Path) -> None:
    p = tmp_path / "trail.jsonl"
    append_jsonl(p, {"ts": "2026-01-01T00:00:00+08:00", "x": True})
    rec = read_jsonl(p)[0]
    assert rec["ts"] == "2026-01-01T00:00:00+08:00"


# ── Post-publish audit integration ──────────────────────────────────


def _make_ledger(job_dir: Path, date_str: str, publish_receipt: dict) -> None:
    """Write a minimal job ledger with a PUBLISHING receipt."""
    ledger = {
        "date": date_str,
        "status": "DONE",
        "stages": {
            "PUBLISHING": {
                "output_summary": publish_receipt,
                "success": True,
            }
        },
    }
    (job_dir / f"publish_job_{date_str}.json").write_text(
        json.dumps(ledger, ensure_ascii=False), encoding="utf-8"
    )


def test_post_publish_audit_dry_run(tmp_path: Path) -> None:
    from datetime import datetime
    from hn2md.stages.post_publish_audit import run_post_publish_audit

    date_str = datetime.now().strftime("%Y%m%d")
    job_dir = tmp_path / "jobs"
    job_dir.mkdir()
    db_path = tmp_path / "test.db"
    output_dir = tmp_path / "output"

    _make_ledger(job_dir, date_str, {"wechat_media_id": None, "dry_run": True})

    result = run_post_publish_audit(job_dir, db_path, output_dir, dry_run=True)
    assert result["blocking_count"] == 0
    assert len(result["findings"]) > 0
    # Verify JSONL was written
    jsonl_path = Path(result["jsonl_path"])
    assert jsonl_path.exists()
    records = read_jsonl(jsonl_path)
    assert len(records) == len(result["findings"])
    # All records should have the date
    for rec in records:
        assert rec["date"] == date_str


def test_post_publish_audit_missing_media_id(tmp_path: Path) -> None:
    from datetime import datetime
    from hn2md.stages.post_publish_audit import run_post_publish_audit

    date_str = datetime.now().strftime("%Y%m%d")
    job_dir = tmp_path / "jobs"
    job_dir.mkdir()
    db_path = tmp_path / "test.db"
    output_dir = tmp_path / "output"

    _make_ledger(job_dir, date_str, {"wechat_media_id": None})

    result = run_post_publish_audit(job_dir, db_path, output_dir, dry_run=False)
    assert result["blocking_count"] >= 1
    codes = [f["check"] for f in result["findings"]]
    assert "wechat_media_id" in codes


def test_post_publish_audit_clean_publish(tmp_path: Path) -> None:
    from datetime import datetime
    from hn2md.stages.post_publish_audit import run_post_publish_audit

    date_str = datetime.now().strftime("%Y%m%d")
    job_dir = tmp_path / "jobs"
    job_dir.mkdir()
    db_path = tmp_path / "test.db"
    output_dir = tmp_path / "output"

    _make_ledger(
        job_dir,
        date_str,
        {
            "wechat_media_id": "wx_media_123",
            "skipped_images": [],
            "compressed_images": [],
            "keyword_warnings": [],
        },
    )

    result = run_post_publish_audit(job_dir, db_path, output_dir, dry_run=False)
    assert result["blocking_count"] == 0
    # media_id should be info, not blocking
    media_findings = [f for f in result["findings"] if f["check"] == "wechat_media_id"]
    assert len(media_findings) == 1
    assert media_findings[0]["severity"] == "info"


def test_post_publish_audit_with_keyword_warnings(tmp_path: Path) -> None:
    from datetime import datetime
    from hn2md.stages.post_publish_audit import run_post_publish_audit

    date_str = datetime.now().strftime("%Y%m%d")
    job_dir = tmp_path / "jobs"
    job_dir.mkdir()
    db_path = tmp_path / "test.db"
    output_dir = tmp_path / "output"

    _make_ledger(
        job_dir,
        date_str,
        {
            "wechat_media_id": "wx_media_456",
            "keyword_warnings": [
                {"keyword": "AI", "line": 10, "sentence": "AI is great"},
            ],
        },
    )

    result = run_post_publish_audit(job_dir, db_path, output_dir, dry_run=False)
    kw_findings = [f for f in result["findings"] if f["check"] == "keyword_review"]
    assert len(kw_findings) == 1
    assert kw_findings[0]["severity"] == "warning"
    assert "1 keyword hit" in kw_findings[0]["message"]


def test_post_publish_audit_jsonl_append_only(tmp_path: Path) -> None:
    """Running audit twice appends, not overwrites."""
    from datetime import datetime
    from hn2md.stages.post_publish_audit import run_post_publish_audit

    date_str = datetime.now().strftime("%Y%m%d")
    job_dir = tmp_path / "jobs"
    job_dir.mkdir()
    db_path = tmp_path / "test.db"
    output_dir = tmp_path / "output"

    _make_ledger(job_dir, date_str, {"wechat_media_id": "wx1", "keyword_warnings": []})

    r1 = run_post_publish_audit(job_dir, db_path, output_dir, dry_run=False)
    r2 = run_post_publish_audit(job_dir, db_path, output_dir, dry_run=False)

    jsonl_path = Path(r1["jsonl_path"])
    records = read_jsonl(jsonl_path)
    assert len(records) == len(r1["findings"]) + len(r2["findings"])
