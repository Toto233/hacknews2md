"""Offline per-story editorial gates; all state is disposable and HTTP forbidden."""

import json
from pathlib import Path
from unittest.mock import Mock

from click.testing import CliRunner
import pytest

from hn2md.state import JobStateMachine
from hn2md.stages.audit import run_audit
from publisher.cli import main
from publisher.context import PublisherContext
from publisher.pipeline.runner import _hn_runtime_context, run_release
from publisher.constants import GenericStage
from publisher.sources.base import SourceDefinition
from publisher.story_editorial import (
    REVIEW_FIELDS, assemble_plan, check_story, require_applied_story_checks,
    require_reviewed_plan, reviewed_stories,
)
from src.db.connection import get_db
from src.utils.db_utils import init_database


def write_json(path: Path, value: dict) -> Path:
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.fixture
def editorial(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("requests.sessions.Session.request", Mock(side_effect=AssertionError("Live HTTP forbidden")))
    ctx = PublisherContext.create(tmp_path, "hackernews", "20260627")
    init_database(str(ctx.db_path))
    with get_db(str(ctx.db_path)) as conn:
        for story_id in (1, 2):
            conn.execute(
                "INSERT INTO news (id,title,news_url,article_content,discussion_content,"
                "content_source_type,content_source_url,screenshot,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (story_id, f"Story {story_id}", f"https://example.test/{story_id}",
                 "A documented result with evidence and limits. " * 30,
                 "A reader questions the benchmark. Another discusses methods. " * 10,
                 "full_text", f"https://example.test/{story_id}", "fixture.png", "2026-06-27 09:00:00"),
            )
    machine, _ = JobStateMachine.load_or_create(ctx.job_dir, ctx.period)
    paths = []
    for story_id in (1, 2):
        paths.append(write_json(tmp_path / f"story_{story_id}.json", {
            "id": story_id, "title_chs": f"新闻{story_id}",
            "content_summary": "这份研究描述方法、证据和局限。" * 24,
            "discuss_summary": "评论者关注验证方法和适用范围。" * 16,
            "editorial_review": {field: True for field in REVIEW_FIELDS},
        }))
    return ctx, machine, paths


def check_all(editorial):
    ctx, machine, paths = editorial
    return [check_story(ctx, machine, path) for path in paths]


def test_checks_one_draft_without_applying_or_exposing_sources(editorial):
    ctx, machine, paths = editorial
    result = check_story(ctx, machine, paths[0])
    assert result["ready"]
    assert result["summary_length"] >= 280
    assert "article_content" not in json.dumps(result)
    with get_db(str(ctx.db_path)) as conn:
        assert conn.execute("SELECT content_summary FROM news WHERE id=1").fetchone()[0] is None
    status = reviewed_stories(ctx, machine)
    assert [item["ready"] for item in status["items"]] == [True, False]


@pytest.mark.parametrize("mutation", ["source", "discussion", "draft", "review"])
def test_mutation_invalidates_only_affected_story(editorial, mutation):
    ctx, machine, paths = editorial
    results = check_all(editorial)
    other_receipt = Path(results[1]["receipt_file"])
    previous = other_receipt.read_bytes()
    if mutation in {"source", "discussion"}:
        column = "article_content" if mutation == "source" else "discussion_content"
        with get_db(str(ctx.db_path)) as conn:
            conn.execute(f"UPDATE news SET {column} = {column} || ? WHERE id = ?", ("changed evidence", 1))
    else:
        raw = json.loads(paths[0].read_text(encoding="utf-8"))
        if mutation == "draft":
            raw["title_chs"] = "已改标题"
        else:
            raw["editorial_review"]["source_fidelity"] = False
        write_json(paths[0], raw)
    status = reviewed_stories(ctx, machine)
    assert not status["ready"]
    assert [item["ready"] for item in status["items"]] == [False, True]
    if mutation != "review":
        assert check_story(ctx, machine, paths[0])["ready"]
        assert reviewed_stories(ctx, machine)["ready"]
    assert other_receipt.read_bytes() == previous


def test_failing_story_does_not_block_checking_other_story(editorial):
    ctx, machine, paths = editorial
    with get_db(str(ctx.db_path)) as conn:
        conn.execute("UPDATE news SET article_content='' WHERE id=1")
    assert not check_story(ctx, machine, paths[0])["ready"]
    assert check_story(ctx, machine, paths[1])["ready"]
    selection = write_json(ctx.project_root / "selection.json", {"ordered_ids": [2, 1], "tags": ["甲", "乙", "丙", "丁"]})
    output = ctx.project_root / "plan.json"
    with pytest.raises(ValueError, match="gates are not ready"):
        assemble_plan(ctx, machine, selection, output)
    assert not output.exists()


def test_assembly_copies_only_current_checked_text_and_exact_selection(editorial):
    ctx, machine, paths = editorial
    check_all(editorial)
    selection = write_json(ctx.project_root / "selection.json", {"ordered_ids": [2, 1], "tags": ["甲", "乙", "丙", "丁"]})
    output = ctx.project_root / "plan.json"
    result = assemble_plan(ctx, machine, selection, output)
    plan = json.loads(output.read_text(encoding="utf-8"))
    assert result["ordered_ids"] == [2, 1]
    assert [item["id"] for item in plan["items"]] == [2, 1]
    assert "editorial_review" not in plan["items"][0]
    plan["items"][0]["title_chs"] = "导入时偷偷改标题"
    with pytest.raises(ValueError, match="changed after checking"):
        require_reviewed_plan(ctx, machine, plan)
    write_json(selection, {"ordered_ids": [1], "tags": ["甲", "乙", "丙", "丁"]})
    with pytest.raises(ValueError, match="every retained story"):
        assemble_plan(ctx, machine, selection, output)


def test_visual_gate_precedes_assembly_and_uses_scoped_waiver(editorial):
    ctx, machine, paths = editorial
    check_all(editorial)
    with get_db(str(ctx.db_path)) as conn:
        conn.execute("UPDATE news SET screenshot=NULL WHERE id=1")
    status = reviewed_stories(ctx, machine)
    assert not status["ready"]
    assert "screenshot" in str(status["final_blockers"])
    machine.job.screenshot_waivers = [{
        "period": ctx.period, "news_id": 1, "news_url": "https://example.test/1",
        "run_id": machine.job.run_id, "approved_by": "user", "reason": "Approved one-run omission",
    }]
    assert reviewed_stories(ctx, machine)["ready"]


def test_keyword_review_is_available_before_render_and_reused(editorial):
    ctx, machine, paths = editorial
    with get_db(str(ctx.db_path)) as conn:
        conn.execute("INSERT INTO illegal_keywords (keyword) VALUES (?)", ("研究",))
    result = check_story(ctx, machine, paths[0])
    assert not result["ready"]
    warning = result["pending_keyword_reviews"][0]
    command = CliRunner().invoke(main, [
        "record-keyword-review", "hackernews", "--date", "20260627", "--item-file", str(paths[0]),
        "--keyword", warning["keyword"], "--sentence", warning["sentence"],
        "--classification", "neutral", "--decision", "用户已确认保留",
    ])
    assert command.exit_code == 0, command.output
    reloaded, _ = JobStateMachine.load_or_create(ctx.job_dir, ctx.period)
    assert check_story(ctx, reloaded, paths[0])["ready"]


def test_unchanged_source_exemption_is_reused_without_exempting_summary_minima(editorial):
    ctx, machine, paths = editorial
    with get_db(str(ctx.db_path)) as conn:
        conn.execute("UPDATE news SET content_source_type='public_page_summary' WHERE id=1")
    machine.record_audit_report(run_audit(_hn_runtime_context(ctx), period=ctx.period, include_summaries=False))
    machine.approve_audit()
    assert check_story(ctx, machine, paths[0])["ready"]
    assert check_story(ctx, machine, paths[1])["ready"]
    assert reviewed_stories(ctx, machine)["ready"]
    raw = json.loads(paths[0].read_text(encoding="utf-8"))
    raw["content_summary"] = "太短"
    write_json(paths[0], raw)
    with pytest.raises(ValueError, match="content_summary"):
        check_story(ctx, machine, paths[0])
    assert not reviewed_stories(ctx, machine)["ready"]


def test_applied_text_change_cannot_reuse_checked_manual_plan(editorial):
    ctx, machine, paths = editorial
    check_all(editorial)
    selection = write_json(ctx.project_root / "selection.json", {"ordered_ids": [1, 2], "tags": ["甲", "乙", "丙", "丁"]})
    plan_path = ctx.project_root / "plan.json"
    assemble_plan(ctx, machine, selection, plan_path)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    machine.job.stages["PLANNING"] = {"output_summary": {"manual": True, "plan_file": str(plan_path)}}
    with get_db(str(ctx.db_path)) as conn:
        for item in plan["items"]:
            conn.execute("UPDATE news SET title_chs=?, content_summary=?, discuss_summary=? WHERE id=?",
                         (item["title_chs"], item["content_summary"], item["discuss_summary"], item["id"]))
    require_applied_story_checks(ctx, machine)
    with get_db(str(ctx.db_path)) as conn:
        conn.execute("UPDATE news SET title_chs=? WHERE id=?", ("改变后的标题", 1))
    with pytest.raises(ValueError, match="Applied story 1"):
        require_applied_story_checks(ctx, machine)


@pytest.mark.parametrize("stage", [GenericStage.RENDERING, GenericStage.COVERING])
def test_strict_gate_stops_render_and_cover_before_side_effects(editorial, stage):
    ctx, machine, paths = editorial
    effect = Mock()
    source = SourceDefinition(name="hackernews", period_kind="date", stages={stage: lambda: effect}, audit_required_stages=(stage,))
    with pytest.raises(RuntimeError, match="audit blocked"):
        run_release(ctx, source, stages=(stage,))
    effect.run.assert_not_called()


def test_cli_checks_and_status_use_isolated_state(editorial):
    ctx, machine, paths = editorial
    runner = CliRunner()
    for path in paths:
        result = runner.invoke(main, ["check-story", "hackernews", "--date", "20260627", "--item-file", str(path)])
        assert result.exit_code == 0, result.output
        assert '"ready": true' in result.output
    result = runner.invoke(main, ["story-status", "hackernews", "--date", "20260627"])
    assert result.exit_code == 0, result.output


def test_known_verification_shell_is_blocked_at_story_check(editorial):
    ctx, machine, paths = editorial
    with get_db(str(ctx.db_path)) as conn:
        conn.execute("UPDATE news SET article_content=? WHERE id=?", (
            "Cloudflare: Verifying you are human. This may take a few seconds. "
            "This site needs to review the security of your connection before proceeding.", 1,
        ))
    result = check_story(ctx, machine, paths[0])
    assert not result["ready"]
    assert any(issue["code"] == "error_page" for issue in result["issues"])


def test_verification_phrase_inside_substantive_reporting_does_not_block(editorial):
    ctx, machine, paths = editorial
    with get_db(str(ctx.db_path)) as conn:
        conn.execute("UPDATE news SET article_content=? WHERE id=?", (
            'The browser displays "verify you are human". '
            + "This article explains the measured outcomes and limits. " * 30, 1,
        ))
    assert check_story(ctx, machine, paths[0])["ready"]


def test_runner_rejects_unchecked_manual_plan_before_constructing_stage(editorial):
    ctx, machine, paths = editorial
    raw = json.loads(paths[0].read_text(encoding="utf-8"))
    plan = write_json(ctx.project_root / "unchecked.json", {
        "items": [raw], "ordered_ids": [1], "tags": ["甲", "乙", "丙", "丁"],
    })
    factory = Mock()
    source = SourceDefinition(name="hackernews", period_kind="date", stages={GenericStage.PLANNING: factory}, audit_required_stages=())
    with pytest.raises(RuntimeError, match="gates are not ready"):
        run_release(ctx, source, stages=(GenericStage.PLANNING,), stage_kwargs={
            GenericStage.PLANNING: {"manual_plan_file": str(plan)},
        })
    factory.assert_not_called()


def test_story_audit_scopes_collect_warning_to_requested_id(editorial):
    ctx, machine, paths = editorial
    machine.job.stages["COLLECTING"] = {"output_summary": {"content_warnings": [
        {"id": 2, "reason": "handler_needed", "url": "https://example.test/2"},
    ]}}
    machine._save()
    assert check_story(ctx, machine, paths[0])["ready"]
    assert not check_story(ctx, machine, paths[1])["ready"]


def test_old_run_check_cannot_be_reused(editorial):
    ctx, machine, paths = editorial
    results = check_all(editorial)
    receipt_path = Path(results[0]["receipt_file"])
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["run_id"] = "older-run"
    write_json(receipt_path, receipt)
    assert [item["ready"] for item in reviewed_stories(ctx, machine)["items"]] == [False, True]


def test_actual_manual_plan_and_apply_pipeline_remains_offline(editorial):
    from publisher.sources import get_source

    ctx, machine, paths = editorial
    machine.job.stages["CAPTURING"] = {"success": True}
    machine._save()
    check_all(editorial)
    selection = write_json(ctx.project_root / "selection.json", {"ordered_ids": [2, 1], "tags": ["甲", "乙", "丙", "丁"]})
    plan_file = ctx.project_root / "plan.json"
    assemble_plan(ctx, machine, selection, plan_file)
    result = run_release(ctx, get_source("hackernews"),
                         stages=(GenericStage.PLANNING, GenericStage.APPLYING),
                         stage_kwargs={GenericStage.PLANNING: {"manual_plan_file": str(plan_file)}})
    assert result["completed_stages"] == ["PLANNING", "APPLYING"]
    reloaded, _ = JobStateMachine.load_or_create(ctx.job_dir, ctx.period)
    require_applied_story_checks(ctx, reloaded)
    with get_db(str(ctx.db_path)) as conn:
        assert conn.execute("SELECT length(content_summary) FROM news WHERE id=1").fetchone()[0] >= 280
