"""Tests for src/utils/config.py."""

import json
import os
from unittest.mock import patch

import pytest


class TestConfig:
    """Tests for Config class."""

    def test_load_valid_file(self, tmp_path):
        from src.utils.config import Config
        config_data = {"GROK_API_KEY": "test-key", "wechat": {"appid": "wx123"}}
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(config_data), encoding="utf-8")

        config = Config(str(config_path))
        assert config.get("GROK_API_KEY") == "test-key"

    def test_missing_file(self, tmp_path):
        from src.utils.config import Config
        config = Config(str(tmp_path / "nonexistent.json"))
        # Should not raise, just return empty/defaults
        assert config.get("missing_key", "default") == "default"

    def test_get_wechat_config_from_json(self, tmp_path):
        from src.utils.config import Config
        config_data = {"wechat": {"appid": "wx123", "appsec": "secret456"}}
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(config_data), encoding="utf-8")

        config = Config(str(config_path))
        wechat = config.get_wechat_config()
        assert wechat["appid"] == "wx123"
        assert wechat["appsec"] == "secret456"

    @patch.dict(os.environ, {"WECHAT_APPID": "env_appid", "WECHAT_APPSEC": "env_secret"})
    def test_env_override(self, tmp_path):
        from src.utils.config import Config
        config_data = {"wechat": {"appid": "file_appid", "appsec": "file_secret"}}
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(config_data), encoding="utf-8")

        config = Config(str(config_path))
        wechat = config.get_wechat_config()
        assert wechat["appid"] == "env_appid"
        assert wechat["appsec"] == "env_secret"

    def test_get_nested_key(self, tmp_path):
        from src.utils.config import Config
        config_data = {"wechat": {"appid": "wx123"}}
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(config_data), encoding="utf-8")

        config = Config(str(config_path))
        assert config.get("wechat.appid") == "wx123"

    def test_get_missing_key_returns_default(self, tmp_path):
        from src.utils.config import Config
        config_path = tmp_path / "config.json"
        config_path.write_text("{}", encoding="utf-8")

        config = Config(str(config_path))
        assert config.get("nonexistent", "fallback") == "fallback"
