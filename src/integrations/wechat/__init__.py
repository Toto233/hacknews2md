"""
WeChat integration package.

Submodules:
    token  - TokenManager: access token lifecycle (DB persistence, refresh)
    media  - MediaManager: permanent material & article image uploads with cache
    draft  - DraftManager: draft list, add, smart-add, formatting
"""

from src.integrations.wechat.draft import DraftManager
from src.integrations.wechat.media import MediaManager
from src.integrations.wechat.token import TokenManager

__all__ = ["TokenManager", "MediaManager", "DraftManager"]
