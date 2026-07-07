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


def _make_ledger(job_dir: Path, date_str: str, publish_receipt: dict, render_receipt: dict | None = None) -> None:
    """Write a minimal job ledger with a PUBLISHING receipt."""
    ledger = {
        "date": date_str,
        "status": "DONE",
        "stages": {
            "RENDERING": {
                "output_summary": render_receipt or {},
                "success": True,
            },
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
    # Dry-run: no media_id is info, but completeness check warns (no markdown file)
    non_info = [f for f in result["findings"] if f.get("severity") in ("warning", "blocking")]
    assert result["jsonl_written"] == len(non_info)
    # The "rendered markdown file not found" warning should be in JSONL
    if non_info:
        records = read_jsonl(Path(result["jsonl_path"]))
        assert len(records) == len(non_info)


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

    # Create a fake markdown file so completeness check doesn't warn
    md_file = tmp_path / "output" / f"hacknews_{date_str}.md"
    md_file.parent.mkdir(parents=True, exist_ok=True)
    md_file.write_text("# Test\n", encoding="utf-8")

    _make_ledger(
        job_dir,
        date_str,
        {
            "wechat_media_id": "wx_media_123",
            "skipped_images": [],
            "compressed_images": [],
            "keyword_warnings": [],
            "markdown_file": str(md_file),
        },
    )

    result = run_post_publish_audit(job_dir, db_path, output_dir, dry_run=False)
    assert result["blocking_count"] == 0
    # Clean publish with existing markdown → all info, nothing to JSONL
    non_info = [f for f in result["findings"] if f.get("severity") in ("warning", "blocking")]
    assert result["jsonl_written"] == len(non_info)
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

    # Use keyword_warnings to trigger actual JSONL writes (non-info findings)
    _make_ledger(
        job_dir,
        date_str,
        {
            "wechat_media_id": "wx1",
            "keyword_warnings": [{"keyword": "test", "line": 1, "sentence": "test line"}],
        },
    )

    r1 = run_post_publish_audit(job_dir, db_path, output_dir, dry_run=False)
    r2 = run_post_publish_audit(job_dir, db_path, output_dir, dry_run=False)

    jsonl_path = Path(r1["jsonl_path"])
    records = read_jsonl(jsonl_path)
    assert len(records) == r1["jsonl_written"] + r2["jsonl_written"]


def test_post_publish_audit_verbose_writes_info_to_jsonl(tmp_path: Path) -> None:
    """With verbose=True, info findings also go to JSONL."""
    from datetime import datetime
    from hn2md.stages.post_publish_audit import run_post_publish_audit

    date_str = datetime.now().strftime("%Y%m%d")
    job_dir = tmp_path / "jobs"
    job_dir.mkdir()
    db_path = tmp_path / "test.db"
    output_dir = tmp_path / "output"

    _make_ledger(job_dir, date_str, {"wechat_media_id": "wx1", "keyword_warnings": []})

    result = run_post_publish_audit(job_dir, db_path, output_dir, dry_run=False, verbose=True)
    assert result["jsonl_written"] == len(result["findings"])
    assert result["jsonl_written"] > 0  # info findings should be written


def test_post_publish_audit_default_only_writes_non_info(tmp_path: Path) -> None:
    """By default, only warning/blocking go to JSONL — not info."""
    from datetime import datetime
    from hn2md.stages.post_publish_audit import run_post_publish_audit

    date_str = datetime.now().strftime("%Y%m%d")
    job_dir = tmp_path / "jobs"
    job_dir.mkdir()
    db_path = tmp_path / "test.db"
    output_dir = tmp_path / "output"

    _make_ledger(job_dir, date_str, {"wechat_media_id": "wx1", "keyword_warnings": []})

    result = run_post_publish_audit(job_dir, db_path, output_dir, dry_run=False, verbose=False)
    non_info = [f for f in result["findings"] if f.get("severity") in ("warning", "blocking")]
    assert result["jsonl_written"] == len(non_info)
    # If everything is clean, nothing written to JSONL
    if not non_info:
        assert result["jsonl_written"] == 0


def test_post_publish_audit_completeness_matches_story_urls(tmp_path: Path) -> None:
    from datetime import datetime

    from hn2md.stages.post_publish_audit import run_post_publish_audit
    from src.utils.db_utils import init_database

    date_str = datetime.now().strftime("%Y%m%d")
    job_dir = tmp_path / "jobs"
    job_dir.mkdir()
    db_path = tmp_path / "test.db"
    output_dir = tmp_path / "output"
    init_database(str(db_path))

    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with __import__("sqlite3").connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO news (id, title, news_url, discuss_url, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                1001,
                "Story",
                "https://example.com/story",
                "https://news.ycombinator.com/item?id=999999",
                created_at,
            ),
        )

    md_file = output_dir / "hacknews.md"
    md_file.parent.mkdir(parents=True, exist_ok=True)
    md_file.write_text(
        "原文链接：https://example.com/story\n论坛讨论链接：https://news.ycombinator.com/item?id=999999\n",
        encoding="utf-8",
    )
    _make_ledger(job_dir, date_str, {"wechat_media_id": "wx1", "markdown_file": str(md_file)})

    result = run_post_publish_audit(job_dir, db_path, output_dir, dry_run=False)

    completeness = [f for f in result["findings"] if f["check"] == "completeness"]
    assert completeness == [
        {
            "date": date_str,
            "check": "completeness",
            "severity": "info",
            "message": "All 1 stories present in markdown",
        }
    ]


def test_post_publish_audit_uses_render_receipt_for_astro_output(tmp_path: Path) -> None:
    from datetime import datetime

    from hn2md.stages.post_publish_audit import run_post_publish_audit

    date_str = datetime.now().strftime("%Y%m%d")
    job_dir = tmp_path / "jobs"
    job_dir.mkdir()
    db_path = tmp_path / "test.db"
    output_dir = tmp_path / "output"
    md_file = output_dir / "hacknews.md"
    astro_file = tmp_path / "astro" / "src" / "data" / "blog" / "hacknews.md"
    md_file.parent.mkdir(parents=True, exist_ok=True)
    astro_file.parent.mkdir(parents=True, exist_ok=True)
    md_file.write_text("# md\n", encoding="utf-8")
    astro_file.write_text("# astro\n", encoding="utf-8")
    _make_ledger(
        job_dir,
        date_str,
        {"wechat_media_id": "wx1", "markdown_file": str(md_file)},
        {"astro_file": str(astro_file)},
    )

    result = run_post_publish_audit(job_dir, db_path, output_dir, dry_run=False)

    astro = [f for f in result["findings"] if f["check"] == "astro_output"]
    assert astro == [
        {
            "date": date_str,
            "check": "astro_output",
            "severity": "info",
            "message": f"Astro output found: {astro_file}",
        }
    ]


def test_post_publish_review_surfaces_stage_retries_and_warnings(tmp_path: Path) -> None:
    from datetime import datetime

    from hn2md.stages.post_publish_audit import run_post_publish_audit

    date_str = datetime.now().strftime("%Y%m%d")
    job_dir = tmp_path / "jobs"
    job_dir.mkdir()
    db_path = tmp_path / "test.db"
    output_dir = tmp_path / "output"
    md_file = output_dir / "hacknews.md"
    md_file.parent.mkdir(parents=True, exist_ok=True)
    md_file.write_text("# Test\n", encoding="utf-8")
    ledger = {
        "date": date_str,
        "status": "DONE",
        "stages": {
            "COLLECTING": {
                "success": True,
                "retry_count": 0,
                "output_summary": {
                    "image_warnings": [
                        {"id": 1, "title": "Story", "image_url": "https://example.com/a.svg", "reason": "save_failed"}
                    ],
                    "content_warnings": [],
                    "discussion_warnings": [],
                },
            },
            "RENDERING": {
                "success": True,
                "retry_count": 1,
                "error": None,
                "output_summary": {},
            },
            "PUBLISHING": {
                "success": True,
                "retry_count": 0,
                "output_summary": {"wechat_media_id": "wx1", "markdown_file": str(md_file)},
            },
        },
    }
    (job_dir / f"publish_job_{date_str}.json").write_text(json.dumps(ledger), encoding="utf-8")

    result = run_post_publish_audit(job_dir, db_path, output_dir, dry_run=False)

    stage_retry = [f for f in result["findings"] if f["check"] == "stage_retry"]
    stage_warning = [f for f in result["findings"] if f["check"] == "stage_warning"]
    for finding in stage_retry + stage_warning:
        finding.pop("ts", None)
    assert stage_retry == [
        {
            "date": date_str,
            "check": "stage_retry",
            "severity": "warning",
            "message": "RENDERING retried 1 time(s)",
            "details": {"stage": "RENDERING", "retry_count": 1, "error": None},
        }
    ]
    assert stage_warning == [
        {
            "date": date_str,
            "check": "stage_warning",
            "severity": "warning",
            "message": "COLLECTING reported 1 image_warnings",
            "details": {
                "stage": "COLLECTING",
                "warning_key": "image_warnings",
                "warnings": [
                    {
                        "id": 1,
                        "title": "Story",
                        "image_url": "https://example.com/a.svg",
                        "reason": "save_failed",
                    }
                ],
            },
        }
    ]
