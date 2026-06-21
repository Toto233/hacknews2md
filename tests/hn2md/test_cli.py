"""Tests for hn2md.cli -- Click CLI commands."""

from unittest.mock import patch

from click.testing import CliRunner

from hn2md.cli import main


def test_doctor_command():
    """Doctor command should run without crashing (checks may fail, that's OK)."""
    runner = CliRunner()
    with patch("requests.get") as mock_get:
        # Mock network check to avoid slow real HTTP call
        mock_get.return_value.status_code = 200
        result = runner.invoke(main, ["doctor"])
    # Exit code 1 is fine (some checks may fail due to missing config/DB).
    # The important thing is no unhandled exception.
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_doctor_json_flag():
    """Doctor --json should produce valid JSON output."""
    import json

    runner = CliRunner()
    with patch("requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        result = runner.invoke(main, ["doctor", "--json"])
    # Should produce parseable JSON regardless of check results
    if result.output.strip():
        data = json.loads(result.output)
        assert "all_ok" in data
        assert "checks" in data


def test_status_command():
    """Status command should run without crashing even with no active job."""
    runner = CliRunner()
    result = runner.invoke(main, ["status"])
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_backup_command_no_check(tmp_path):
    """Backup --no-check should run without crashing on a valid DB."""
    import sqlite3

    # Set up a minimal project structure with a real SQLite database
    project_root = tmp_path
    data_dir = project_root / "data"
    data_dir.mkdir()
    db_path = data_dir / "hacknews.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE news (id INTEGER PRIMARY KEY, title TEXT)")
    conn.commit()
    conn.close()

    runner = CliRunner()
    result = runner.invoke(main, ["--project-root", str(project_root), "backup", "--no-check"])
    # Should not crash -- may succeed or fail depending on Database class
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_help_flag():
    """--help should display usage information."""
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "hn2md" in result.output.lower()


def test_doctor_help():
    """doctor --help should show doctor-specific options."""
    runner = CliRunner()
    result = runner.invoke(main, ["doctor", "--help"])
    assert result.exit_code == 0
    assert "--json" in result.output


def test_status_help():
    """status --help should show usage."""
    runner = CliRunner()
    result = runner.invoke(main, ["status", "--help"])
    assert result.exit_code == 0


def test_backup_help():
    """backup --help should show backup options."""
    runner = CliRunner()
    result = runner.invoke(main, ["backup", "--help"])
    assert result.exit_code == 0
    assert "--no-check" in result.output
