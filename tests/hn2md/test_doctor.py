"""Tests for hn2md.commands.doctor -- environment readiness checks."""

from unittest.mock import MagicMock, patch

from hn2md.commands.doctor import CheckResult, run_doctor, run_doctor_json


def _disable_ci_mode(monkeypatch):
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("HN2MD_DOCTOR_CI", raising=False)


def test_check_result_tuple():
    """CheckResult is a NamedTuple with name, ok, detail fields."""
    r = CheckResult("test", True, "ok")
    assert r.name == "test"
    assert r.ok is True
    assert r.detail == "ok"


def test_check_result_failure():
    """CheckResult can represent a failed check."""
    r = CheckResult("database", False, "file not found")
    assert r.name == "database"
    assert r.ok is False
    assert r.detail == "file not found"


def test_check_result_tuple_unpacking():
    """CheckResult supports tuple unpacking."""
    r = CheckResult("test", True, "all good")
    name, ok, detail = r
    assert name == "test"
    assert ok is True
    assert detail == "all good"


def test_check_result_equality():
    """Two CheckResults with same values should be equal."""
    r1 = CheckResult("x", True, "ok")
    r2 = CheckResult("x", True, "ok")
    assert r1 == r2


def test_check_result_immutable():
    """CheckResult should be immutable (NamedTuple)."""
    r = CheckResult("test", True, "ok")
    try:
        r.name = "changed"  # type: ignore[misc]
        assert False, "Should have raised AttributeError"
    except AttributeError:
        pass


def test_run_doctor_returns_list(tmp_path):
    """run_doctor should return a list of CheckResult, even with missing deps."""
    ctx = MagicMock()
    ctx.db_path = tmp_path / "data" / "nonexistent.db"
    ctx.config_path = tmp_path / "config" / "nonexistent.json"
    ctx.output_dir = tmp_path / "output"

    # Only mock the network call to keep the test fast.
    # All other checks are wrapped in try/except inside run_doctor.
    with patch("requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        results = run_doctor(ctx)

    assert isinstance(results, list)
    assert len(results) >= 1
    for r in results:
        assert isinstance(r, CheckResult)


def test_run_doctor_reports_python_version():
    """run_doctor should always include a Python version check."""
    ctx = MagicMock()
    ctx.db_path = "/nonexistent/db.db"
    ctx.config_path = "/nonexistent/config.json"
    ctx.output_dir = "/nonexistent/output"

    with patch("requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        results = run_doctor(ctx)

    python_checks = [r for r in results if "Python" in r.name]
    assert len(python_checks) == 1
    # We're running 3.11+ in this environment
    assert python_checks[0].ok is True


def test_run_doctor_json_returns_dict(tmp_path, monkeypatch):
    """run_doctor_json should return a dict with all_ok and checks keys."""
    _disable_ci_mode(monkeypatch)
    ctx = MagicMock()
    ctx.db_path = tmp_path / "data" / "nonexistent.db"
    ctx.config_path = tmp_path / "config" / "nonexistent.json"
    ctx.output_dir = tmp_path / "output"

    with patch("requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        result = run_doctor_json(ctx)

    assert isinstance(result, dict)
    assert "all_ok" in result
    assert "checks" in result
    assert isinstance(result["checks"], list)
    # With missing DB/config, all_ok should be False
    assert result["all_ok"] is False


def test_run_doctor_json_check_items(tmp_path):
    """Each check in the JSON output should have name, ok, detail."""
    ctx = MagicMock()
    ctx.db_path = tmp_path / "data" / "nonexistent.db"
    ctx.config_path = tmp_path / "config" / "nonexistent.json"
    ctx.output_dir = tmp_path / "output"

    with patch("requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        result = run_doctor_json(ctx)

    for item in result["checks"]:
        assert "name" in item
        assert "ok" in item
        assert "detail" in item
        assert isinstance(item["ok"], bool)


def test_generic_ci_env_does_not_change_doctor_strict_mode(tmp_path, monkeypatch):
    """GitHub's global CI env should not change doctor semantics during pytest."""
    monkeypatch.setenv("CI", "true")
    ctx = MagicMock()
    ctx.db_path = tmp_path / "data" / "hacknews.db"
    ctx.config_path = tmp_path / "config" / "config.json"
    ctx.output_dir = tmp_path / "output"

    with patch("requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        result = run_doctor_json(ctx)

    assert result["all_ok"] is False


def test_run_doctor_json_allows_missing_runtime_secrets_in_explicit_ci_doctor_mode(tmp_path, monkeypatch):
    """The workflow can explicitly run doctor without local publish secrets/data."""
    monkeypatch.setenv("HN2MD_DOCTOR_CI", "true")
    ctx = MagicMock()
    ctx.db_path = tmp_path / "data" / "hacknews.db"
    ctx.config_path = tmp_path / "config" / "config.json"
    ctx.output_dir = tmp_path / "output"

    with patch("requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        result = run_doctor_json(ctx)

    assert result["all_ok"] is True
    checks = {item["name"]: item for item in result["checks"]}
    assert checks["SQLite database"]["ok"] is True
    assert "skipped in CI" in checks["SQLite database"]["detail"]
    assert checks["config/config.json"]["ok"] is True
    assert "skipped in CI" in checks["config/config.json"]["detail"]
    assert checks["WeChat credentials"]["ok"] is True
    assert "skipped in CI" in checks["WeChat credentials"]["detail"]
    assert checks["LLM API keys"]["ok"] is True
    assert "skipped in CI" in checks["LLM API keys"]["detail"]


def test_explicit_ci_doctor_mode_skips_runtime_database_even_when_empty_file_exists(tmp_path, monkeypatch):
    """CI doctor should not fail on an empty SQLite file created during earlier checks."""
    monkeypatch.setenv("HN2MD_DOCTOR_CI", "true")
    db_path = tmp_path / "data" / "hacknews.db"
    db_path.parent.mkdir(parents=True)
    db_path.write_bytes(b"")
    ctx = MagicMock()
    ctx.db_path = db_path
    ctx.config_path = tmp_path / "config" / "config.json"
    ctx.output_dir = tmp_path / "output"

    with patch("requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        result = run_doctor_json(ctx)

    assert result["all_ok"] is True
    checks = {item["name"]: item for item in result["checks"]}
    assert checks["SQLite database"]["ok"] is True
    assert "skipped in CI" in checks["SQLite database"]["detail"]
