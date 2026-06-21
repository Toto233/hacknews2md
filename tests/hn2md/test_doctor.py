"""Tests for hn2md.commands.doctor -- environment readiness checks."""

from unittest.mock import MagicMock, patch

from hn2md.commands.doctor import CheckResult, run_doctor, run_doctor_json


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


def test_run_doctor_json_returns_dict(tmp_path):
    """run_doctor_json should return a dict with all_ok and checks keys."""
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
