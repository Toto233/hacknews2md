"""Tests for src/llm/llm_utils.py."""

import json
import sqlite3
from contextlib import contextmanager
from unittest.mock import patch, MagicMock

import pytest


@pytest.fixture
def llm_db(tmp_path):
    """Create a temp database and patch get_db in llm_utils to use it."""
    db_path = str(tmp_path / "test_llm.db")

    @contextmanager
    def _get_db(db_path_arg=None):
        conn = sqlite3.connect(db_path)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    with patch("src.llm.daily_status.get_db", _get_db):
        yield db_path


class TestIsForbiddenGeminiModel:
    """Tests for _is_forbidden_gemini_model pure function."""

    def test_gemini_2_5_pro(self):
        from src.llm.llm_utils import _is_forbidden_gemini_model
        assert _is_forbidden_gemini_model("gemini-2.5-pro") is True

    def test_gemini_2_5_flash(self):
        from src.llm.llm_utils import _is_forbidden_gemini_model
        assert _is_forbidden_gemini_model("gemini-2.5-flash") is True

    def test_gemini_3_flash(self):
        from src.llm.llm_utils import _is_forbidden_gemini_model
        assert _is_forbidden_gemini_model("gemini-3-flash-preview") is False

    def test_none(self):
        from src.llm.llm_utils import _is_forbidden_gemini_model
        assert _is_forbidden_gemini_model(None) is False

    def test_empty(self):
        from src.llm.llm_utils import _is_forbidden_gemini_model
        assert _is_forbidden_gemini_model("") is False


class TestIsStrictCappedGeminiModel:
    """Tests for _is_strict_capped_gemini_model pure function."""

    def test_gemini_3_flash(self):
        from src.llm.llm_utils import _is_strict_capped_gemini_model
        assert _is_strict_capped_gemini_model("gemini-3-flash-preview") is True

    def test_gemini_3_1_flash(self):
        from src.llm.llm_utils import _is_strict_capped_gemini_model
        assert _is_strict_capped_gemini_model("gemini-3.1-flash-lite") is False


class TestIsGeminiQuotaExceededError:
    """Tests for is_gemini_quota_exceeded_error pure function."""

    def test_quota_exceeded(self):
        from src.llm.llm_utils import is_gemini_quota_exceeded_error
        assert is_gemini_quota_exceeded_error("quota exceeded") is True

    def test_resource_exhausted(self):
        from src.llm.llm_utils import is_gemini_quota_exceeded_error
        assert is_gemini_quota_exceeded_error("resource_exhausted") is True

    def test_daily_limit(self):
        from src.llm.llm_utils import is_gemini_quota_exceeded_error
        assert is_gemini_quota_exceeded_error("daily limit reached") is True

    def test_normal_error(self):
        from src.llm.llm_utils import is_gemini_quota_exceeded_error
        assert is_gemini_quota_exceeded_error("connection timeout") is False

    def test_empty(self):
        from src.llm.llm_utils import is_gemini_quota_exceeded_error
        assert is_gemini_quota_exceeded_error("") is False

    def test_none(self):
        from src.llm.llm_utils import is_gemini_quota_exceeded_error
        assert is_gemini_quota_exceeded_error(None) is False


class TestEnsureLlmStatusTable:
    """Tests for _ensure_llm_status_table with database."""

    def test_creates_tables(self, llm_db):
        import src.llm.llm_utils as mod
        mod._ensure_llm_status_table()
        conn = sqlite3.connect(llm_db)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='llm_model_daily_status'"
        )
        assert cursor.fetchone() is not None
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='llm_model_daily_usage'"
        )
        assert cursor.fetchone() is not None
        conn.close()


class TestReserveDailyRequestSlot:
    """Tests for _reserve_daily_request_slot with database."""

    def test_first_request_succeeds(self, llm_db):
        import src.llm.llm_utils as mod
        mod._ensure_llm_status_table()
        result = mod._reserve_daily_request_slot("gemini", "gemini-3-flash-preview", 100)
        assert result is True

    def test_at_limit_returns_false(self, llm_db):
        import src.llm.llm_utils as mod
        mod._ensure_llm_status_table()
        # Fill up the quota
        for _ in range(3):
            mod._reserve_daily_request_slot("gemini", "gemini-3-flash-preview", 3)
        result = mod._reserve_daily_request_slot("gemini", "gemini-3-flash-preview", 3)
        assert result is False


class TestModelDisableToday:
    """Tests for is_model_disabled_today and disable_model_for_today."""

    def test_not_disabled_initially(self, llm_db):
        import src.llm.llm_utils as mod
        mod._ensure_llm_status_table()
        assert mod.is_model_disabled_today("gemini", "gemini-3-flash-preview") is False

    def test_disabled_after_disable(self, llm_db):
        import src.llm.llm_utils as mod
        mod._ensure_llm_status_table()
        mod.disable_model_for_today("gemini", "gemini-3-flash-preview", "test", "test error")
        assert mod.is_model_disabled_today("gemini", "gemini-3-flash-preview") is True


class TestRateLimiter:
    """Tests for RateLimiter class."""

    def test_allows_under_limit(self):
        from src.llm.llm_utils import RateLimiter
        limiter = RateLimiter()
        # Should not block
        limiter.wait_if_needed("test", max_requests=10, window_seconds=60)

    def test_tracks_requests(self):
        from src.llm.llm_utils import RateLimiter
        limiter = RateLimiter()
        for _ in range(5):
            limiter.wait_if_needed("test", max_requests=10, window_seconds=60)
        assert len(limiter.request_times.get("test", [])) == 5


class TestLoadLlmConfig:
    """Tests for load_llm_config with config file."""

    def test_reads_json(self, temp_config_file):
        import src.llm.llm_utils as mod
        import os
        original_cwd = os.getcwd()
        # Create config directory structure
        config_dir = os.path.dirname(temp_config_file)
        os.makedirs(os.path.join(config_dir, "config"), exist_ok=True)
        target = os.path.join(config_dir, "config", "config.json")
        import shutil
        shutil.copy2(temp_config_file, target)

        try:
            os.chdir(config_dir)
            config = mod.load_llm_config()
            assert "grok" in config
            assert "gemini" in config
            assert config["grok"]["api_key"] == "test-grok-key"
        finally:
            os.chdir(original_cwd)


class TestCallLlmRouter:
    """Tests for call_llm routing logic."""

    @patch("src.llm.llm_utils.call_grok_api")
    def test_routes_to_grok(self, mock_grok):
        from src.llm.llm_utils import call_llm
        mock_grok.return_value = "grok response"
        with patch("src.llm.llm_utils.load_llm_config") as mock_config:
            mock_config.return_value = {
                "grok": {"api_key": "key", "model": "grok-3-beta"},
                "gemini": {"api_key": "key", "model": "gemini-3-flash-preview"},
                "default": "grok"
            }
            result = call_llm("test prompt", llm_type="grok")
            assert result == "grok response"
            mock_grok.assert_called_once()

    @patch("src.llm.llm_utils.call_gemini_api")
    def test_routes_to_gemini(self, mock_gemini):
        from src.llm.llm_utils import call_llm
        mock_gemini.return_value = "gemini response"
        with patch("src.llm.llm_utils.load_llm_config") as mock_config:
            mock_config.return_value = {
                "grok": {"api_key": "key", "model": "grok-3-beta"},
                "gemini": {"api_key": "key", "model": "gemini-3-flash-preview"},
                "default": "gemini"
            }
            result = call_llm("test prompt", llm_type="gemini")
            assert result == "gemini response"
            mock_gemini.assert_called_once()
