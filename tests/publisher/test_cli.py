from unittest.mock import patch

from click.testing import CliRunner

from hn2md.state import JobStateMachine, Stage
from publisher.cli import main


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


def test_graph_prints_hackernews_stage_order() -> None:
    result = CliRunner().invoke(main, ["graph", "hackernews"])

    assert result.exit_code == 0, result.output
    assert "Source: hackernews" in result.output
    assert "FETCHING -> COLLECTING -> PLANNING -> APPLYING -> RENDERING -> COVERING -> PUBLISHING" in result.output
