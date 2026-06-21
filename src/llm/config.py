"""LLM configuration loading with file-modification-time cache."""

import json
import logging
import os

logger = logging.getLogger(__name__)

# Config cache — avoids re-reading config.json on every LLM call
_llm_config_cache = None
_llm_config_mtime = 0


def load_llm_config():
    """加载LLM配置 (with file modification time cache).

    Only re-reads config.json if the file has been modified since last read.
    This eliminates the per-call disk I/O overhead.
    """
    global _llm_config_cache, _llm_config_mtime
    from src.llm.daily_status import _is_forbidden_gemini_model

    config_path = "config/config.json"
    try:
        current_mtime = os.path.getmtime(config_path)
    except OSError:
        current_mtime = 0

    if _llm_config_cache is not None and current_mtime == _llm_config_mtime:
        return _llm_config_cache

    with open(config_path, encoding="utf-8") as f:
        config = json.load(f)
        gemini_model = config.get("GEMINI_MODEL", "gemini-3-flash-preview")
        if _is_forbidden_gemini_model(gemini_model):
            logger.warning(f"[配置修正] 检测到禁用模型 {gemini_model}，自动改为 gemini-3-flash-preview")
            gemini_model = "gemini-3-flash-preview"
        result = {
            "grok": {
                "api_key": config.get("GROK_API_KEY"),
                "api_url": config.get("GROK_API_URL", "https://api.x.ai/v1/chat/completions"),
                "model": config.get("GROK_MODEL", "grok-3-beta"),
                "temperature": config.get("GROK_TEMPERATURE", 0.7),
                "max_tokens": config.get("GROK_MAX_TOKENS", 800),
            },
            "gemini": {
                "api_key": config.get("GEMINI_API_KEY"),
                "api_url": config.get(
                    "GEMINI_API_URL",
                    "https://generativelanguage.googleapis.com/v1beta/models/gemini-3-flash-preview:generateContent",
                ),
                "model": gemini_model,
                "temperature": config.get("GEMINI_TEMPERATURE", 0.7),
                "max_tokens": config.get("GEMINI_MAX_TOKENS", 800),
            },
            "moonshot": {
                "api_key": config.get("MOONSHOT_API_KEY"),
                "api_url": config.get("MOONSHOT_API_URL", "https://api.moonshot.cn/v1/chat/completions"),
                "model": config.get("MOONSHOT_MODEL", "moonshot-v1-8k"),
                "temperature": config.get("MOONSHOT_TEMPERATURE", 0.7),
                "max_tokens": config.get("MOONSHOT_MAX_TOKENS", 800),
            },
            "default": config.get("DEFAULT_LLM", "grok"),
        }

    _llm_config_cache = result
    _llm_config_mtime = current_mtime
    return result


def invalidate_llm_config_cache():
    """Force reload of LLM config on next call."""
    global _llm_config_cache, _llm_config_mtime
    _llm_config_cache = None
    _llm_config_mtime = 0
