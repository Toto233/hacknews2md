import sqlite3
import subprocess
import sys
from unittest.mock import patch

from click.testing import CliRunner

from hn2md.state import JobStateMachine, Stage
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


def test_audit_command_records_structured_report(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    report = {"items": [], "issues": [], "blocking_count": 0}

    with patch("publisher.cli.run_audit", return_value=report):
        result = CliRunner().invoke(main, ["audit", "hackernews", "--date", "2026-06-27", "--json"])

    assert result.exit_code == 0, result.output
    assert '"blocking_count": 0' in result.output
    machine, _ = JobStateMachine.load_or_create(tmp_path / "output" / "jobs", "20260627")
    assert machine.job.audit_report == report


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
