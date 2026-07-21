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


def test_post_publish_audit_jsonl_deduplicates_repeated_findings(tmp_path: Path) -> None:
    """Running the same audit twice should not duplicate identical findings."""
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
    assert r1["jsonl_written"] > 0
    assert r2["jsonl_written"] == 0
    assert len(records) == r1["jsonl_written"]


def test_post_publish_audit_tolerates_malformed_jsonl_line(tmp_path: Path) -> None:
    from datetime import datetime

    from hn2md.stages.post_publish_audit import run_post_publish_audit

    date_str = datetime.now().strftime("%Y%m%d")
    job_dir = tmp_path / "jobs"
    job_dir.mkdir()
    db_path = tmp_path / "test.db"
    output_dir = tmp_path / "output"
    _make_ledger(job_dir, date_str, {"wechat_media_id": "wx1", "keyword_warnings": []})
    jsonl_path = output_dir / "reviews" / f"run_review_{date_str}.jsonl"
    jsonl_path.parent.mkdir(parents=True)
    jsonl_path.write_text('{"broken":\n', encoding="utf-8")

    first = run_post_publish_audit(job_dir, db_path, output_dir, dry_run=False)
    second = run_post_publish_audit(job_dir, db_path, output_dir, dry_run=False)

    integrity_findings = [
        finding for finding in first["findings"] if finding["check"] == "jsonl_integrity"
    ]
    assert len(integrity_findings) == 1
    assert integrity_findings[0]["severity"] == "warning"
    assert first["jsonl_written"] > 0
    assert second["jsonl_written"] == 0


def test_post_publish_audit_tolerates_invalid_utf8_jsonl_line(tmp_path: Path) -> None:
    from datetime import datetime

    from hn2md.stages.post_publish_audit import run_post_publish_audit

    date_str = datetime.now().strftime("%Y%m%d")
    job_dir = tmp_path / "jobs"
    job_dir.mkdir()
    db_path = tmp_path / "test.db"
    output_dir = tmp_path / "output"
    _make_ledger(job_dir, date_str, {"wechat_media_id": "wx1", "keyword_warnings": []})
    jsonl_path = output_dir / "reviews" / f"run_review_{date_str}.jsonl"
    jsonl_path.parent.mkdir(parents=True)
    jsonl_path.write_bytes(b'{"message":"' + bytes([0xE4, 0xB8]) + b'"}\n')

    result = run_post_publish_audit(job_dir, db_path, output_dir, dry_run=False)

    integrity_findings = [
        finding for finding in result["findings"] if finding["check"] == "jsonl_integrity"
    ]
    assert len(integrity_findings) == 1
    assert integrity_findings[0]["details"]["lines"] == [1]


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


def test_post_publish_audit_reports_astro_skip_reason(tmp_path: Path) -> None:
    from datetime import datetime

    from hn2md.stages.post_publish_audit import run_post_publish_audit

    date_str = datetime.now().strftime("%Y%m%d")
    job_dir = tmp_path / "jobs"
    job_dir.mkdir()
    db_path = tmp_path / "test.db"
    output_dir = tmp_path / "output"
    md_file = output_dir / "hacknews.md"
    md_file.parent.mkdir(parents=True, exist_ok=True)
    md_file.write_text("# md\n", encoding="utf-8")
    _make_ledger(
        job_dir,
        date_str,
        {"wechat_media_id": "wx1", "markdown_file": str(md_file)},
        {"astro_file": None, "astro_skipped": True, "astro_skip_reason": "Astro repository not found: C:/missing"},
    )

    result = run_post_publish_audit(job_dir, db_path, output_dir, dry_run=False)

    astro = [f for f in result["findings"] if f["check"] == "astro_output"]
    assert len(astro) == 1
    assert astro[0]["date"] == date_str
    assert astro[0]["severity"] == "warning"
    assert astro[0]["message"] == "Astro skipped during render: Astro repository not found: C:/missing"


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


def test_post_publish_review_reads_historical_stage_receipts(tmp_path: Path) -> None:
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
    old_collect = {
        "success": True,
        "retry_count": 0,
        "output_summary": {
            "content_warnings": [
                {
                    "id": 42,
                    "url": "https://example.com/story",
                    "reason": "article_content_missing",
                    "action_required": "human_input_or_handler",
                }
            ]
        },
    }
    latest_collect = {
        "success": True,
        "retry_count": 0,
        "output_summary": {"content_warnings": []},
    }
    ledger = {
        "date": date_str,
        "status": "DONE",
        "stages": {
            "COLLECTING": latest_collect,
            "PUBLISHING": {
                "success": True,
                "output_summary": {"wechat_media_id": "wx1", "markdown_file": str(md_file)},
            },
        },
        "receipts": {"COLLECTING": [old_collect, latest_collect]},
    }
    (job_dir / f"publish_job_{date_str}.json").write_text(json.dumps(ledger), encoding="utf-8")

    result = run_post_publish_audit(job_dir, db_path, output_dir, dry_run=False)

    history_findings = [
        finding
        for finding in result["findings"]
        if finding["check"] == "stage_warning"
        and finding.get("details", {}).get("warning_key") == "content_warnings"
    ]
    assert len(history_findings) == 1
    assert history_findings[0]["severity"] == "blocking"
    assert history_findings[0]["details"]["warnings"] == old_collect["output_summary"]["content_warnings"]


def test_post_publish_review_deduplicates_rerun_receipt_warnings(tmp_path: Path) -> None:
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
    first_collect = {
        "success": True,
        "retry_count": 1,
        "output_summary": {
            "content_warnings": [
                {"id": 42, "url": "https://example.com/story", "reason": "article_content_missing"}
            ]
        },
    }
    latest_collect = {
        "success": True,
        "retry_count": 2,
        "output_summary": {
            "content_warnings": [
                {
                    "id": 42,
                    "url": "https://example.com/story",
                    "reason": "article_content_missing",
                    "failure_count": 2,
                }
            ]
        },
    }
    ledger = {
        "date": date_str,
        "status": "DONE",
        "stages": {
            "COLLECTING": latest_collect,
            "PUBLISHING": {"success": True, "output_summary": {"wechat_media_id": "wx1", "markdown_file": str(md_file)}},
        },
        "receipts": {"COLLECTING": [first_collect, latest_collect]},
    }
    (job_dir / f"publish_job_{date_str}.json").write_text(json.dumps(ledger), encoding="utf-8")

    result = run_post_publish_audit(job_dir, db_path, output_dir, dry_run=False)

    retries = [finding for finding in result["findings"] if finding["check"] == "stage_retry"]
    warnings = [
        finding
        for finding in result["findings"]
        if finding["check"] == "stage_warning" and finding["details"]["warning_key"] == "content_warnings"
    ]
    assert retries[0]["details"]["retry_count"] == 2
    assert len(retries) == 1
    assert len(warnings) == 1


def test_post_publish_review_downgrades_skipped_warning_and_recovered_failure(tmp_path: Path) -> None:
    from datetime import datetime

    from hn2md.stages.post_publish_audit import run_post_publish_audit
    from src.utils.db_utils import init_database

    date_str = datetime.now().strftime("%Y%m%d")
    job_dir = tmp_path / "jobs"
    job_dir.mkdir()
    db_path = tmp_path / "test.db"
    output_dir = tmp_path / "output"
    init_database(str(db_path))
    md_file = output_dir / "hacknews.md"
    md_file.parent.mkdir(parents=True, exist_ok=True)
    md_file.write_text("# Test\n", encoding="utf-8")
    failed_publish = {"success": False, "error": "temporary whitelist failure", "output_summary": {}}
    completed_publish = {
        "success": True,
        "retry_count": 1,
        "output_summary": {"wechat_media_id": "wx1", "markdown_file": str(md_file)},
    }
    ledger = {
        "date": date_str,
        "status": "DONE",
        "stages": {
            "COLLECTING": {
                "success": True,
                "output_summary": {
                    "content_warnings": [
                        {"id": 42, "url": "https://example.com/skipped", "reason": "fallback_content_requires_review"}
                    ]
                },
            },
            "PUBLISHING": completed_publish,
        },
        "receipts": {"PUBLISHING": [failed_publish, completed_publish]},
        "skipped_stories": [
            {
                "id": 42,
                "news_url": "https://example.com/skipped",
                "reason": "human review",
                "skipped_at": "2026-07-20T12:00:00",
            }
        ],
    }
    (job_dir / f"publish_job_{date_str}.json").write_text(json.dumps(ledger), encoding="utf-8")

    result = run_post_publish_audit(job_dir, db_path, output_dir, dry_run=False)

    skipped_warning = next(
        finding
        for finding in result["findings"]
        if finding["check"] == "resolution" and finding["details"].get("resolution") == "story_skipped"
    )
    recovered_failure = next(
        finding
        for finding in result["findings"]
        if finding["check"] == "resolution" and finding["details"].get("resolution") == "stage_recovered"
    )
    assert skipped_warning["severity"] == "info"
    assert recovered_failure["severity"] == "info"
    assert recovered_failure["details"]["recovered"] is True
    assert result["blocking_count"] == 0


def test_post_publish_review_keeps_unrecorded_missing_story_blocking(tmp_path: Path) -> None:
    from datetime import datetime

    from hn2md.stages.post_publish_audit import run_post_publish_audit
    from src.utils.db_utils import init_database

    date_str = datetime.now().strftime("%Y%m%d")
    job_dir = tmp_path / "jobs"
    job_dir.mkdir()
    db_path = tmp_path / "test.db"
    output_dir = tmp_path / "output"
    init_database(str(db_path))
    md_file = output_dir / "hacknews.md"
    md_file.parent.mkdir(parents=True, exist_ok=True)
    md_file.write_text("# Test\n", encoding="utf-8")
    ledger = {
        "date": date_str,
        "status": "DONE",
        "stages": {
            "COLLECTING": {
                "success": True,
                "output_summary": {
                    "content_warnings": [
                        {"id": 42, "url": "https://example.com/missing", "action_required": "human_input"}
                    ]
                },
            },
            "PUBLISHING": {
                "success": True,
                "output_summary": {"wechat_media_id": "wx1", "markdown_file": str(md_file)},
            },
        },
    }
    (job_dir / f"publish_job_{date_str}.json").write_text(json.dumps(ledger), encoding="utf-8")

    result = run_post_publish_audit(job_dir, db_path, output_dir, dry_run=False)

    assert result["blocking_count"] == 1
    assert any(finding["check"] == "stage_warning" for finding in result["findings"])
    assert not any(
        finding["check"] == "resolution" and finding["details"].get("resolution") == "story_skipped"
        for finding in result["findings"]
    )


def test_post_publish_review_reads_historical_process_findings_once(tmp_path: Path) -> None:
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
    keyword_warning = {"keyword": "test", "line": 1, "sentence": "test line"}
    old_publish = {
        "success": True,
        "output_summary": {
            "wechat_media_id": "old",
            "skipped_images": ["https://example.com/large.png"],
            "keyword_warnings": [keyword_warning],
        },
    }
    latest_publish = {
        "success": True,
        "output_summary": {
            "wechat_media_id": "latest",
            "markdown_file": str(md_file),
            "keyword_warnings": [keyword_warning],
        },
    }
    old_collect = {
        "success": False,
        "error": "'gbk' codec can't encode character",
        "output_summary": {},
    }
    latest_collect = {"success": True, "output_summary": {}}
    ledger = {
        "date": date_str,
        "status": "DONE",
        "stages": {"COLLECTING": latest_collect, "PUBLISHING": latest_publish},
        "receipts": {
            "COLLECTING": [old_collect, latest_collect],
            "PUBLISHING": [old_publish, latest_publish],
        },
    }
    (job_dir / f"publish_job_{date_str}.json").write_text(json.dumps(ledger), encoding="utf-8")

    result = run_post_publish_audit(job_dir, db_path, output_dir, dry_run=False)

    image_warnings = [
        finding
        for finding in result["findings"]
        if finding["check"] == "image_preflight" and finding["severity"] == "warning"
    ]
    keyword_warnings = [finding for finding in result["findings"] if finding["check"] == "keyword_review"]
    environment_warnings = [
        finding for finding in result["findings"] if finding["check"] == "environment_compatibility"
    ]
    assert len(image_warnings) == 1
    assert len(keyword_warnings) == 1
    assert len(environment_warnings) == 1


def test_post_publish_review_downgrades_resolved_content_warning(tmp_path: Path) -> None:
    import sqlite3
    from datetime import datetime

    from hn2md.stages.post_publish_audit import run_post_publish_audit
    from src.utils.db_utils import init_database

    date_str = datetime.now().strftime("%Y%m%d")
    job_dir = tmp_path / "jobs"
    job_dir.mkdir()
    db_path = tmp_path / "test.db"
    output_dir = tmp_path / "output"
    init_database(str(db_path))

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO news (
                id, title, news_url, article_content, content_source_url, created_at
            ) VALUES (?, ?, ?, ?, ?, datetime('now', 'localtime'))
            """,
            (
                42,
                "Introducing Hy3",
                "https://hy.tencent.com/research/hy3",
                "Resolved Hy3 article body. " * 160,
                "https://hy.tencent.com/research/hy3",
            ),
        )

    md_file = output_dir / "hacknews.md"
    md_file.parent.mkdir(parents=True, exist_ok=True)
    md_file.write_text("https://hy.tencent.com/research/hy3\n", encoding="utf-8")
    ledger = {
        "date": date_str,
        "status": "DONE",
        "stages": {
            "COLLECTING": {
                "success": True,
                "retry_count": 0,
                "output_summary": {
                    "content_warnings": [
                        {
                            "id": 42,
                            "url": "https://hy.tencent.com/research/hy3",
                            "domain": "hy.tencent.com",
                            "reason": "article_content_missing",
                            "action_required": "human_input_or_handler",
                            "failure_count": 1,
                        }
                    ]
                },
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

    resolutions = [f for f in result["findings"] if f["check"] == "resolution"]
    assert resolutions[0]["details"]["resolution"] == "content_repaired"
    assert resolutions[0]["details"]["warnings"][0]["id"] == 42
    snapshot = json.loads(Path(result["snapshot_path"]).read_text(encoding="utf-8"))
    assert snapshot["blocking_count"] == 0
    assert snapshot["findings"] == result["findings"]
    jsonl_records = [json.loads(line) for line in Path(result["jsonl_path"]).read_text(encoding="utf-8").splitlines()]
    assert any(record["check"] == "resolution" for record in jsonl_records)
    assert result["blocking_count"] == 0


def test_post_publish_review_downgrades_resolved_discussion_warning(tmp_path: Path) -> None:
    import sqlite3
    from datetime import datetime

    from hn2md.stages.post_publish_audit import run_post_publish_audit
    from src.utils.db_utils import init_database

    date_str = datetime.now().strftime("%Y%m%d")
    job_dir = tmp_path / "jobs"
    job_dir.mkdir()
    db_path = tmp_path / "test.db"
    output_dir = tmp_path / "output"
    init_database(str(db_path))

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO news (
                id, title, news_url, discuss_url, discussion_content, created_at
            ) VALUES (?, ?, ?, ?, ?, datetime('now', 'localtime'))
            """,
            (
                43,
                "Running Train",
                "https://example.com/running-train",
                "https://news.ycombinator.com/item?id=48876505",
                "HN discussion body. " * 80,
            ),
        )

    md_file = output_dir / "hacknews.md"
    md_file.parent.mkdir(parents=True, exist_ok=True)
    md_file.write_text("https://news.ycombinator.com/item?id=48876505\n", encoding="utf-8")
    ledger = {
        "date": date_str,
        "status": "DONE",
        "stages": {
            "COLLECTING": {
                "success": True,
                "retry_count": 0,
                "output_summary": {
                    "discussion_warnings": [
                        {
                            "id": 43,
                            "title": "Running Train",
                            "url": "https://news.ycombinator.com/item?id=48876505",
                            "reason": "discussion_missing_after_retry",
                            "action_required": "human_input_or_handler",
                            "attempts": 2,
                        }
                    ]
                },
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

    resolutions = [f for f in result["findings"] if f["check"] == "resolution"]
    assert resolutions[0]["details"]["resolution"] == "discussion_repaired"
    assert resolutions[0]["details"]["warnings"][0]["id"] == 43
    assert result["blocking_count"] == 0


def test_post_publish_review_flags_environment_compatibility_errors(tmp_path: Path) -> None:
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
            "PUBLISHING": {
                "success": False,
                "retry_count": 2,
                "error": "'gbk' codec can't encode character '\\u2717' in position 2",
                "output_summary": {"wechat_media_id": "wx1", "markdown_file": str(md_file)},
            },
            "REPAIRING": {
                "success": False,
                "retry_count": 0,
                "error": "Unexpected UTF-8 BOM (decode using utf-8-sig): line 1 column 1",
                "output_summary": {},
            },
            "CHECKING": {
                "success": False,
                "retry_count": 0,
                "error": "Missing file specification after redirection operator. The '<' operator is reserved for future use.",
                "output_summary": {},
            },
        },
    }
    (job_dir / f"publish_job_{date_str}.json").write_text(json.dumps(ledger), encoding="utf-8")

    result = run_post_publish_audit(job_dir, db_path, output_dir, dry_run=False)

    findings = [f for f in result["findings"] if f["check"] == "environment_compatibility"]
    for finding in findings:
        finding.pop("ts", None)
    assert findings == [
        {
            "date": date_str,
            "check": "environment_compatibility",
            "severity": "warning",
            "message": "Detected 3 shell/encoding compatibility issue(s)",
            "details": {
                "issues": [
                    {
                        "stage": "PUBLISHING",
                        "kind": "windows_console_encoding",
                        "hint": "Set PYTHONIOENCODING=utf-8 and PYTHONUTF8=1 before running Python publisher commands.",
                        "error": "'gbk' codec can't encode character '\\u2717' in position 2",
                    },
                    {
                        "stage": "REPAIRING",
                        "kind": "utf8_bom",
                        "hint": "Write JSON with UTF-8 without BOM; avoid Windows PowerShell 5.1 Set-Content -Encoding utf8 for machine JSON.",
                        "error": "Unexpected UTF-8 BOM (decode using utf-8-sig): line 1 column 1",
                    },
                    {
                        "stage": "CHECKING",
                        "kind": "bash_syntax_in_powershell",
                        "hint": "Use PowerShell here-strings or python -c instead of bash heredoc/redirection syntax.",
                        "error": "Missing file specification after redirection operator. The '<' operator is reserved for future use.",
                    },
                ]
            },
        }
    ]
