import sqlite3
import json
from datetime import datetime
from pathlib import Path

import pytest

from hn2md.context import RuntimeContext
from hn2md.state import JobStateMachine, PublishJob
from hn2md.stages.audit import require_audit_clear_or_exempt, run_audit
from src.utils.db_utils import init_database


def _ctx(tmp_path: Path) -> RuntimeContext:
    output = tmp_path / "output"
    return RuntimeContext(
        project_root=tmp_path,
        db_path=tmp_path / "data" / "hacknews.db",
        output_dir=output,
        job_dir=output / "jobs",
        markdown_dir=output / "markdown",
        images_dir=output / "images",
        codex_dir=output / "codex",
        config_path=tmp_path / "config" / "config.json",
    )


def _machine(tmp_path: Path, date: str = "20260628") -> JobStateMachine:
    now = datetime.now().isoformat()
    job = PublishJob(date=date, created_at=now, updated_at=now)
    path = tmp_path / f"publish_job_{date}.json"
    job.to_json(path)
    return JobStateMachine(job, path)


def test_audit_returns_structured_report_without_doi_requirement(tmp_path) -> None:
    ctx = _ctx(tmp_path)
    init_database(str(ctx.db_path))
    with sqlite3.connect(ctx.db_path) as conn:
        conn.execute(
            """
            INSERT INTO news (
                id, title, news_url, article_content, discussion_content,
                content_summary, discuss_summary, content_source_type,
                content_source_url, created_at
            ) VALUES (
                1, 'Paper', 'https://paper.example', 'abstract text long enough for audit checks',
                'discussion', 'summary', '', 'public_abstract', NULL,
                datetime('now', 'localtime')
            )
            """
        )

    report = run_audit(ctx)

    codes = {issue["code"] for issue in report["issues"]}
    assert {"content_short", "abstract_source_missing", "discussion_summary_missing"} <= codes
    assert "abstract_doi_missing" not in codes
    assert report["blocking_count"] == len(report["issues"])
    assert report["items"][0]["content_source_type"] == "public_abstract"
    assert "content_source_doi" not in report["items"][0]


def test_gate_blocks_until_audit_is_clean_or_approved(tmp_path) -> None:
    machine = _machine(tmp_path)

    with pytest.raises(RuntimeError, match="audit required"):
        require_audit_clear_or_exempt(machine)

    machine.record_audit_report({"issues": [{"code": "source_missing"}], "blocking_count": 1})
    with pytest.raises(RuntimeError, match="audit blocked"):
        require_audit_clear_or_exempt(machine)

    machine.approve_audit()
    assert require_audit_clear_or_exempt(machine) is True


def test_clean_audit_does_not_need_exemption(tmp_path) -> None:
    machine = _machine(tmp_path)
    machine.record_audit_report({"issues": [], "blocking_count": 0})

    assert require_audit_clear_or_exempt(machine) is False


def test_audit_blocks_fallback_source_until_human_review(tmp_path) -> None:
    ctx = _ctx(tmp_path)
    init_database(str(ctx.db_path))
    with sqlite3.connect(ctx.db_path) as conn:
        conn.execute(
            """
            INSERT INTO news (
                id, title, news_url, article_content, discussion_content,
                content_summary, discuss_summary, content_source_type,
                content_source_url, created_at
            ) VALUES (
                1, 'Blocked page', 'https://example.com/story',
                'Source fallback: local crawler could not retrieve full text, metadata only for review.',
                'discussion', 'summary', 'discussion summary',
                'public_page_summary', 'https://example.com/story',
                datetime('now', 'localtime')
            )
            """
        )

    report = run_audit(ctx)

    codes = {issue["code"] for issue in report["issues"]}
    assert "fallback_source_requires_review" in codes


def test_audit_accepts_human_supplied_content_source(tmp_path) -> None:
    ctx = _ctx(tmp_path)
    init_database(str(ctx.db_path))
    with sqlite3.connect(ctx.db_path) as conn:
        conn.execute(
            """
            INSERT INTO news (
                id, title, news_url, article_content, discussion_content,
                content_summary, discuss_summary, content_source_type,
                content_source_url, created_at
            ) VALUES (
                1, 'Human supplied', 'https://example.com/story',
                '人工补齐的正文，长度足够用于审计通过。人工补齐的正文，长度足够用于审计通过。人工补齐的正文，长度足够用于审计通过。人工补齐的正文，长度足够用于审计通过。人工补齐的正文，长度足够用于审计通过。人工补齐的正文，长度足够用于审计通过。人工补齐的正文，长度足够用于审计通过。人工补齐的正文，长度足够用于审计通过。',
                'discussion', 'summary', 'discussion summary',
                'human_supplied', 'https://example.com/story',
                datetime('now', 'localtime')
            )
            """
        )

    report = run_audit(ctx)

    assert report["blocking_count"] == 0


def test_audit_merges_collect_content_warnings_from_ledger(tmp_path) -> None:
    ctx = _ctx(tmp_path)
    init_database(str(ctx.db_path))
    period = datetime.now().strftime("%Y%m%d")
    ctx.job_dir.mkdir(parents=True)
    (ctx.job_dir / f"publish_job_{period}.json").write_text(
        json.dumps(
            {
                "date": period,
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
                "status": "COLLECTING",
                "stages": {
                    "COLLECTING": {
                        "stage": "COLLECTING",
                        "status": "SUCCESS",
                        "started_at": datetime.now().isoformat(),
                        "finished_at": datetime.now().isoformat(),
                        "output_summary": {
                            "content_warnings": [
                                {
                                    "id": 3838,
                                    "url": "https://pudding.cool/story",
                                    "domain": "pudding.cool",
                                    "reason": "content_missing",
                                    "action_required": "human_input_or_handler",
                                    "failure_count": 2,
                                }
                            ]
                        },
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    report = run_audit(ctx)

    assert report["blocking_count"] == 1
    assert report["issues"][0]["code"] == "collect_content_warning"
    assert report["issues"][0]["action_required"] == "human_input_or_handler"
