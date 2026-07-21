import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from hn2md.state import JobStateMachine, Stage, StageReceipt
from publisher.cli import main
from src.utils.db_utils import init_database


def test_status_reports_not_started_for_missing_hackernews_run(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(main, ["status", "hackernews", "--date", "2026-06-27"])

    assert result.exit_code == 0, result.output
    assert "Status: NOT_STARTED" in result.output
    assert "Source: hackernews" in result.output
    assert "Period: 20260627" in result.output


def test_status_reads_existing_hn_ledger(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    job_dir = tmp_path / "output" / "jobs"
    job_dir.mkdir(parents=True)
    machine, _ = JobStateMachine.load_or_create(job_dir, "20260627")
    machine.transition(Stage.FETCHING)

    result = CliRunner().invoke(main, ["status", "hackernews", "--date", "2026-06-27"])

    assert result.exit_code == 0, result.output
    assert "Source: hackernews" in result.output
    assert "Period: 20260627" in result.output
    assert "Status: FETCHING" in result.output


def test_release_dry_run_calls_runner(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    with patch("publisher.cli.run_release", return_value={"completed_stages": ["FETCHING"]}) as run:
        result = CliRunner().invoke(
            main,
            ["release", "hackernews", "--date", "2026-06-27", "--dry-run"],
        )

    assert result.exit_code == 0, result.output
    assert "Release complete" in result.output
    run.assert_called_once()


def test_release_from_stage_publishing_targets_wechat_only(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    with patch("publisher.cli.run_release", return_value={"completed_stages": ["PUBLISHING"]}) as run:
        result = CliRunner().invoke(
            main,
            [
                "release",
                "hackernews",
                "--date",
                "2026-06-27",
                "--from-stage",
                "PUBLISHING",
                "--target",
                "wechat",
                "--rerun",
            ],
        )

    assert result.exit_code == 0, result.output
    _, kwargs = run.call_args
    assert [stage.value for stage in kwargs["stages"]] == ["PUBLISHING"]
    assert kwargs["targets"] == ("wechat",)
    assert kwargs["rerun"] is True


def test_validate_source_reports_hackernews_contract_ok() -> None:
    result = CliRunner().invoke(main, ["validate-source", "hackernews"])

    assert result.exit_code == 0, result.output
    assert "Source contract OK: hackernews" in result.output


def test_python_module_entrypoint_invokes_publisher_cli() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "publisher.cli", "validate-source", "hackernews"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Source contract OK: hackernews" in result.stdout


def test_graph_prints_hackernews_stage_order() -> None:
    result = CliRunner().invoke(main, ["graph", "hackernews"])

    assert result.exit_code == 0, result.output
    assert "Source: hackernews" in result.output
    assert "FETCHING -> COLLECTING -> PLANNING -> APPLYING -> RENDERING -> COVERING -> PUBLISHING" in result.output


def test_collect_command_runs_collect_stage_with_concurrency(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    with patch("publisher.cli.run_release", return_value={"completed_stages": ["COLLECTING"]}) as run:
        result = CliRunner().invoke(main, ["collect", "hackernews", "--date", "2026-06-27", "--concurrency", "5"])

    assert result.exit_code == 0, result.output
    _, kwargs = run.call_args
    assert [stage.value for stage in kwargs["stages"]] == ["COLLECTING"]
    assert kwargs["stage_kwargs"]["COLLECTING"]["concurrency"] == 5


def test_collect_command_supports_rerun(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    with patch("publisher.cli.run_release", return_value={"completed_stages": ["COLLECTING"]}) as run:
        result = CliRunner().invoke(main, ["collect", "hackernews", "--date", "2026-06-27", "--rerun"])

    assert result.exit_code == 0, result.output
    _, kwargs = run.call_args
    assert [stage.value for stage in kwargs["stages"]] == ["COLLECTING"]
    assert kwargs["rerun"] is True


def test_hackernews_fetch_does_not_pass_producthunt_options(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    with patch("publisher.cli.run_release", return_value={"completed_stages": ["FETCHING"]}) as run:
        result = CliRunner().invoke(main, ["fetch", "hackernews", "--date", "2026-06-27"])

    assert result.exit_code == 0, result.output
    _, kwargs = run.call_args
    assert kwargs.get("stage_kwargs") in (None, {})


def test_producthunt_fetch_uses_month_period_and_producthunt_database(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    with patch("publisher.cli.run_release", return_value={"completed_stages": ["FETCHING"]}) as run:
        result = CliRunner().invoke(
            main,
            ["fetch", "producthunt", "--year", "2026", "--month", "6"],
        )

    assert result.exit_code == 0, result.output
    ctx = run.call_args.args[0]
    _, kwargs = run.call_args
    assert ctx.period == "202606"
    assert ctx.db_path == tmp_path / "data" / "producthunt.db"
    assert [stage.value for stage in kwargs["stages"]] == ["FETCHING"]


def test_producthunt_release_from_render_uses_month_period(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    with patch("publisher.cli.run_release", return_value={"completed_stages": ["RENDERING"]}) as run:
        result = CliRunner().invoke(
            main,
            [
                "release",
                "producthunt",
                "--year",
                "2026",
                "--month",
                "6",
                "--from-stage",
                "RENDERING",
                "--dry-run",
            ],
        )

    assert result.exit_code == 0, result.output
    ctx = run.call_args.args[0]
    _, kwargs = run.call_args
    assert ctx.period == "202606"
    assert ctx.db_path == tmp_path / "data" / "producthunt.db"
    assert [stage.value for stage in kwargs["stages"]] == ["RENDERING", "COVERING", "PUBLISHING"]
    assert kwargs["dry_run"] is True


def test_plan_command_imports_manual_plan(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    plan = tmp_path / "plan.json"
    plan.write_text("{}", encoding="utf-8")

    with patch("publisher.cli.run_release", return_value={"completed_stages": ["PLANNING"]}) as run:
        result = CliRunner().invoke(
            main,
            ["plan", "hackernews", "--date", "2026-06-27", "--manual-plan", str(plan)],
        )

    assert result.exit_code == 0, result.output
    _, kwargs = run.call_args
    assert [stage.value for stage in kwargs["stages"]] == ["PLANNING"]
    assert kwargs["stage_kwargs"]["PLANNING"]["manual_plan_file"] == str(plan)


def test_publish_command_targets_wechat_and_passes_artifacts(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    with patch("publisher.cli.run_release", return_value={"completed_stages": ["PUBLISHING"]}) as run:
        result = CliRunner().invoke(
            main,
            [
                "publish",
                "hackernews",
                "--date",
                "2026-06-27",
                "article.md",
                "--cover-image",
                "cover.png",
                "--target",
                "wechat",
                "--rerun",
            ],
        )

    assert result.exit_code == 0, result.output
    _, kwargs = run.call_args
    assert [stage.value for stage in kwargs["stages"]] == ["PUBLISHING"]
    assert kwargs["targets"] == ("wechat",)
    assert kwargs["rerun"] is True
    assert kwargs["stage_kwargs"]["PUBLISHING"] == {
        "markdown_file": "article.md",
        "cover_image": "cover.png",
    }


def test_cover_command_can_register_external_cover(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    cover = tmp_path / "cover.png"
    cover.write_bytes(b"png")

    with patch("publisher.cli.run_release", return_value={"completed_stages": ["COVERING"]}) as run:
        result = CliRunner().invoke(
            main,
            [
                "cover",
                "hackernews",
                "--date",
                "2026-06-27",
                "article.md",
                "--mode",
                "external",
                "--cover-image",
                str(cover),
                "--target-word",
                "幽灵锁漏洞",
                "--display-title",
                "短标题",
            ],
        )

    assert result.exit_code == 0, result.output
    _, kwargs = run.call_args
    assert [stage.value for stage in kwargs["stages"]] == ["COVERING"]
    assert kwargs["stage_kwargs"]["COVERING"] == {
        "markdown_file": "article.md",
        "mode": "external",
        "target_word": "幽灵锁漏洞",
        "display_title": "短标题",
        "cover_image": str(cover),
    }


def test_export_context_writes_db_snapshot(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    db_path = tmp_path / "data" / "hacknews.db"
    init_database(str(db_path))
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO news (
                id, title, news_url, discuss_url, article_content,
                discussion_content, content_source_type, content_source_url,
                created_at
            )
            VALUES (
                1, 'Story', 'https://example.com/story',
                'https://news.ycombinator.com/item?id=1',
                'article body', 'discussion body', 'human_supplied',
                'https://example.com/story', '2026-06-27 10:00:00'
            )
            """
        )

    result = CliRunner().invoke(main, ["export-context", "hackernews", "--date", "2026-06-27"])

    assert result.exit_code == 0, result.output
    context_path = Path(result.output.strip().split(": ", 1)[1])
    payload = json.loads(context_path.read_text(encoding="utf-8"))
    assert payload["count"] == 1
    assert payload["items"][0]["id"] == 1
    assert payload["items"][0]["article_content"] == "article body"
    assert payload["items"][0]["discussion_content"] == "discussion body"


def test_draft_plan_writes_compact_manual_material(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    db_path = tmp_path / "data" / "hacknews.db"
    init_database(str(db_path))
    article = "article body " * 20
    discussion = "discussion body " * 20
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO news (
                id, title, news_url, discuss_url, article_content,
                discussion_content, title_chs, content_summary, discuss_summary,
                content_source_type, content_source_url, created_at
            )
            VALUES (
                1, 'Story', 'https://example.com/story',
                'https://news.ycombinator.com/item?id=1',
                ?, ?, '旧中文标题', '旧正文摘要', '旧讨论摘要',
                'scraped', 'https://example.com/story', '2026-06-27 10:00:00'
            )
            """,
            (article, discussion),
        )

    result = CliRunner().invoke(
        main,
        [
            "draft-plan",
            "hackernews",
            "--date",
            "2026-06-27",
            "--article-chars",
            "20",
            "--discussion-chars",
            "15",
        ],
    )

    assert result.exit_code == 0, result.output
    draft_path = Path(result.output.strip().split(": ", 1)[1])
    payload = json.loads(draft_path.read_text(encoding="utf-8"))
    item = payload["items"][0]
    assert payload["period"] == "20260627"
    assert payload["ordered_ids"] == [1]
    assert payload["tags"] == []
    assert item["id"] == 1
    assert item["title_chs"] == "旧中文标题"
    assert item["content_summary"] == "旧正文摘要"
    assert item["article_length"] == len(article)
    assert item["discussion_length"] == len(discussion)
    assert item["article_excerpt"] == article[:20].rstrip() + "..."
    assert item["discussion_excerpt"] == discussion[:15].rstrip() + "..."


def test_audit_command_records_structured_report(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    report = {"items": [], "issues": [], "blocking_count": 0}

    with patch("publisher.cli.run_audit", return_value=report):
        result = CliRunner().invoke(main, ["audit", "hackernews", "--date", "2026-06-27", "--json"])

    assert result.exit_code == 0, result.output
    assert '"blocking_count": 0' in result.output
    machine, _ = JobStateMachine.load_or_create(tmp_path / "output" / "jobs", "20260627")
    assert machine.job.audit_report == report


def test_audit_command_does_not_expose_post_publish_review() -> None:
    result = CliRunner().invoke(main, ["audit", "--help"])

    assert result.exit_code == 0, result.output
    assert "--post-publish" not in result.output
    assert "review-run" not in result.output


def test_review_run_command_runs_post_publish_review(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    audit_result = {
        "findings": [{"severity": "info", "check": "wechat_media_id", "message": "ok"}],
        "blocking_count": 0,
        "jsonl_written": 1,
        "jsonl_path": str(tmp_path / "output" / "reviews" / "run_review_20260627.jsonl"),
    }

    with patch("hn2md.stages.post_publish_audit.run_post_publish_audit", return_value=audit_result) as run:
        result = CliRunner().invoke(
            main,
            [
                "review-run",
                "hackernews",
                "--date",
                "2026-06-27",
                "--json",
                "--verbose",
            ],
        )

    assert result.exit_code == 0, result.output
    assert '"blocking_count": 0' in result.output
    run.assert_called_once()
    _, kwargs = run.call_args
    assert kwargs["job_dir"] == tmp_path / "output" / "jobs"
    assert kwargs["db_path"] == tmp_path / "data" / "hacknews.db"
    assert kwargs["output_dir"] == tmp_path / "output"
    assert kwargs["dry_run"] is False
    assert kwargs["verbose"] is True


def test_repair_astro_generates_output_and_updates_done_ledger(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    db_path = tmp_path / "data" / "hacknews.db"
    init_database(str(db_path))
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO news (
                id, title, title_chs, news_url, discuss_url, content_summary,
                discuss_summary, created_at
            )
            VALUES (
                1, 'Story', '中文标题', 'https://example.com/story',
                'https://news.ycombinator.com/item?id=1', '正文摘要', '讨论摘要',
                '2026-06-27 10:00:00'
            )
            """
        )
    plan = tmp_path / "output" / "codex" / "plan.json"
    plan.parent.mkdir(parents=True)
    plan.write_text(
        json.dumps({"ordered_ids": [1], "tags": ["AI", "科技", "开源", "工具"], "items": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    astro_repo = tmp_path / "astro"
    (astro_repo / "src" / "data" / "blog").mkdir(parents=True)
    deployment = tmp_path / "config" / "deployment.local.json"
    deployment.parent.mkdir(parents=True)
    deployment.write_text(
        json.dumps(
            {
                "astro": {
                    "enabled": True,
                    "repo_path": str(astro_repo),
                    "blog_subdir": "src/data/blog",
                }
            }
        ),
        encoding="utf-8",
    )
    machine, _ = JobStateMachine.load_or_create(tmp_path / "output" / "jobs", "20260627")
    machine.job.status = Stage.DONE.value
    machine.record_receipt(
        StageReceipt(
            stage=Stage.APPLYING.value,
            started_at="2026-06-27T10:00:00",
            finished_at="2026-06-27T10:00:01",
            success=True,
            output_summary={"plan_file": str(plan)},
        )
    )

    result = CliRunner().invoke(main, ["repair-astro", "hackernews", "--date", "2026-06-27"])

    assert result.exit_code == 0, result.output
    machine, _ = JobStateMachine.load_or_create(tmp_path / "output" / "jobs", "20260627")
    render_summary = machine.job.stages[Stage.RENDERING.value]["output_summary"]
    astro_file = render_summary["astro_file"]
    assert astro_file.endswith(".md")
    assert (astro_repo / "src" / "data" / "blog" / Path(astro_file).name).exists()
    assert render_summary["astro_repaired"] is True
    assert "Astro repair complete" in result.output


def test_audit_approve_command_records_exemption(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    machine, _ = JobStateMachine.load_or_create(tmp_path / "output" / "jobs", "20260627")
    machine.record_audit_report({"items": [], "issues": [{"code": "content_short"}], "blocking_count": 1})

    result = CliRunner().invoke(main, ["audit", "hackernews", "--date", "2026-06-27", "--approve"])

    assert result.exit_code == 0, result.output
    machine, _ = JobStateMachine.load_or_create(tmp_path / "output" / "jobs", "20260627")
    assert machine.job.audit_exemption["issue_snapshot"] == [{"code": "content_short"}]


def test_mark_source_updates_content_provenance(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    db_path = tmp_path / "data" / "hacknews.db"
    init_database(str(db_path))
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO news (id, title, news_url, created_at)
            VALUES (1, 'Story', 'https://example.com/story', '2026-06-27 10:00:00')
            """
        )

    result = CliRunner().invoke(
        main,
        [
            "mark-source",
            "hackernews",
            "1",
            "--date",
            "2026-06-27",
            "--type",
            "human_supplied",
            "--url",
            "https://example.com/story",
        ],
    )

    assert result.exit_code == 0, result.output
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT content_source_type, content_source_url FROM news WHERE id=1"
        ).fetchone()
    assert row == ("human_supplied", "https://example.com/story")


def test_set_content_updates_article_and_source(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    db_path = tmp_path / "data" / "hacknews.db"
    init_database(str(db_path))
    body_file = tmp_path / "body.txt"
    body_file.write_text("人工补齐正文。" * 30, encoding="utf-8")
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO news (id, title, news_url, created_at)
            VALUES (1, 'Story', 'https://example.com/story', '2026-06-27 10:00:00')
            """
        )

    result = CliRunner().invoke(
        main,
        [
            "set-content",
            "hackernews",
            "1",
            "--date",
            "2026-06-27",
            "--file",
            str(body_file),
            "--source-type",
            "human_supplied",
            "--source-url",
            "https://example.com/story",
        ],
    )

    assert result.exit_code == 0, result.output
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT article_content, content_source_type, content_source_url FROM news WHERE id=1"
        ).fetchone()
    assert row == ("人工补齐正文。" * 30, "human_supplied", "https://example.com/story")


def test_skip_story_can_delete_and_add_domain_filter(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    db_path = tmp_path / "data" / "hacknews.db"
    init_database(str(db_path))
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO news (id, title, news_url, created_at)
            VALUES (3839, '403', 'https://www.marfapublicradio.org/story', '2026-06-27 10:00:00')
            """
        )

    result = CliRunner().invoke(
        main,
        [
            "skip-story",
            "hackernews",
            "3839",
            "--date",
            "2026-06-27",
            "--filter-domain",
            "--reason",
            "403",
        ],
    )

    assert result.exit_code == 0, result.output
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM news WHERE id=3839").fetchone()[0] == 0
        filter_row = conn.execute(
            "SELECT domain, reason FROM filtered_domains WHERE domain='marfapublicradio.org'"
        ).fetchone()
    assert filter_row == ("marfapublicradio.org", "403")
    machine, _ = JobStateMachine.load_or_create(tmp_path / "output" / "jobs", "20260627")
    assert machine.job.skipped_stories == [
        {
            "id": 3839,
            "title": "403",
            "news_url": "https://www.marfapublicradio.org/story",
            "reason": "403",
            "skipped_at": machine.job.skipped_stories[0]["skipped_at"],
        }
    ]


def test_filter_domain_adds_hackernews_filter_without_deleting_story(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    db_path = tmp_path / "data" / "hacknews.db"
    init_database(str(db_path))
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO news (id, title, news_url, created_at)
            VALUES (4001, 'Reuters story', 'https://www.reuters.com/world/story', datetime('now', 'localtime'))
            """
        )

    result = CliRunner().invoke(
        main,
        ["filter-domain", "hackernews", "https://www.reuters.com/world/story", "--reason", "paywall"],
    )

    assert result.exit_code == 0, result.output
    with sqlite3.connect(db_path) as conn:
        story_count = conn.execute("SELECT COUNT(*) FROM news WHERE id=4001").fetchone()[0]
        filter_row = conn.execute(
            "SELECT domain, reason FROM filtered_domains WHERE domain='reuters.com'"
        ).fetchone()
    assert story_count == 1
    assert filter_row == ("reuters.com", "paywall")


def test_filter_domain_rejects_unsupported_source(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(main, ["filter-domain", "producthunt", "example.com"])

    assert result.exit_code != 0
    assert "does not support domain filtering" in result.output


def test_filter_domain_rejects_malformed_or_unsafe_domain_inputs(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    for domain in ("not a domain", "mailto:foo@example.com", "https://user@example.com/story"):
        result = CliRunner().invoke(main, ["filter-domain", "hackernews", domain])

        assert result.exit_code != 0
        assert "invalid domain or URL" in result.output


def test_filter_domain_normalizes_url_with_port(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(
        main,
        ["filter-domain", "hackernews", "https://www.example.com:8443/story"],
    )

    assert result.exit_code == 0, result.output
    with sqlite3.connect(tmp_path / "data" / "hacknews.db") as conn:
        filter_row = conn.execute(
            "SELECT domain FROM filtered_domains WHERE domain='example.com'"
        ).fetchone()
    assert filter_row == ("example.com",)
