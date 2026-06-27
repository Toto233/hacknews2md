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
