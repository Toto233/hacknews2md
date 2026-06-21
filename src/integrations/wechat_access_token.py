#!/usr/bin/env python3
"""
WeChat Access Token Tool
Automatically retrieves WeChat access token using app ID and secret.
Stores tokens in SQLite database with expiration management.

This module is a backward-compatible facade.  The actual implementation
lives in ``src.integrations.wechat`` (token / media / draft submodules).
"""

import sys

# Windows 下设置 UTF-8 编码输出，防止编码错误
if sys.platform == "win32":
    import io

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


from src.integrations.wechat.draft import DraftManager
from src.integrations.wechat.media import MediaManager
from src.integrations.wechat.token import TokenManager


class WeChatAccessToken:
    """
    Unified WeChat client -- thin facade over TokenManager / MediaManager / DraftManager.

    All public method signatures are preserved for backward compatibility.
    """

    def __init__(self, appid: str, secret: str, db_path: str = "data/hacknews.db"):
        self._token_mgr = TokenManager(appid, secret, db_path)
        self._media_mgr = MediaManager(self._token_mgr)
        self._draft_mgr = DraftManager(self._token_mgr, self._media_mgr)

    # -- Token management (delegated to TokenManager) --------------------

    def _init_database(self):
        self._token_mgr._init_database()

    def _save_token_to_db(self, access_token: str, expires_in: int):
        return self._token_mgr._save_token_to_db(access_token, expires_in)

    def _load_token_from_db(self) -> str | None:
        return self._token_mgr._load_token_from_db()

    def get_access_token(self, force_refresh: bool = False, retry_count: int = 2) -> str | None:
        return self._token_mgr.get_access_token(force_refresh=force_refresh, retry_count=retry_count)

    def is_token_valid(self) -> bool:
        return self._token_mgr.is_token_valid()

    def get_token_info(self) -> dict:
        return self._token_mgr.get_token_info()

    def clear_expired_tokens(self):
        return self._token_mgr.clear_expired_tokens()

    def get_all_tokens_info(self) -> list:
        return self._token_mgr.get_all_tokens_info()

    # -- Media uploads (delegated to MediaManager) -----------------------

    def upload_permanent_material(
        self, file_path: str, media_type: str = "image", title: str = None, introduction: str = None
    ) -> dict | None:
        return self._media_mgr.upload_permanent_material(file_path, media_type, title=title, introduction=introduction)

    def upload_image_for_article(self, file_path: str) -> str | None:
        return self._media_mgr.upload_image_for_article(file_path)

    def _calculate_file_md5(self, file_path: str) -> str:
        return self._media_mgr._calculate_file_md5(file_path)

    def _check_image_cache(self, file_path: str, upload_type: str = "article") -> dict | None:
        return self._media_mgr._check_image_cache(file_path, upload_type)

    def _save_image_upload(self, file_path: str, upload_type: str, media_id: str = None, media_url: str = "") -> bool:
        return self._media_mgr._save_image_upload(file_path, upload_type, media_id=media_id, media_url=media_url)

    # -- Draft management (delegated to DraftManager) --------------------

    def get_draft_list(self, offset: int = 0, count: int = 20, no_content: int = 0) -> dict | None:
        return self._draft_mgr.get_draft_list(offset=offset, count=count, no_content=no_content)

    def add_draft(self, articles: list) -> str | None:
        return self._draft_mgr.add_draft(articles)

    def add_draft_smart(
        self, articles: list, default_thumb_media_id: str = None, thumb_image_path: str = None
    ) -> str | None:
        return self._draft_mgr.add_draft_smart(
            articles, default_thumb_media_id=default_thumb_media_id, thumb_image_path=thumb_image_path
        )

    def format_draft_list(self, draft_data: dict, show_content: bool = False) -> str:
        return self._draft_mgr.format_draft_list(draft_data, show_content=show_content)


def main():
    # Load credentials from config (never hardcode)
    from src.utils.config import Config

    config = Config()
    wechat_config = config.get_wechat_config()
    APPID = wechat_config["appid"]
    SECRET = wechat_config["appsec"]

    # Create WeChat client with database storage
    wechat = WeChatAccessToken(APPID, SECRET)

    # Display current database status
    print("\n" + "=" * 50)
    print("WeChat Access Token Tool with SQLite Storage")
    print("=" * 50)

    # Show all tokens in database
    all_tokens = wechat.get_all_tokens_info()
    if all_tokens:
        print(f"\nTokens in database ({len(all_tokens)}):")
        for token in all_tokens:
            status = "[OK] Valid" if token["is_valid"] else "[WARN] Expired"
            print(f"  {token['appid']}: {token['access_token'][:20]}... - {status}")
        print()

    # Clean up expired tokens
    wechat.clear_expired_tokens()

    # Get access token (will check database first)
    print("\n" + "-" * 30)
    print("Getting access token...")
    token = wechat.get_access_token()

    if token:
        print("\n" + "=" * 50)
        print("SUCCESS: Access token retrieved!")
        print("=" * 50)

        # Display token info
        info = wechat.get_token_info()
        print(f"Access Token: {info['access_token'][:20]}...")
        print(f"Expires At: {info['expires_at']}")
        print(f"Valid: {info['is_valid']}")
        print(f"Remaining: {int(info['remaining_seconds'])} seconds")
        print(f"Database: {info['db_path']}")

        # Test draft list functionality
        print("\n" + "=" * 50)
        print("Testing Draft List Functionality")
        print("=" * 50)

        # Get draft list without content
        print("\n1. Getting draft list (no content)...")
        draft_data = wechat.get_draft_list(offset=0, count=10, no_content=1)
        if draft_data:
            print("Draft list retrieved successfully!")
            formatted = wechat.format_draft_list(draft_data, show_content=False)
            print(formatted)
        else:
            print("No drafts found or error occurred")

        # Get draft list with content (if drafts exist)
        if draft_data and draft_data.get("total_count", 0) > 0:
            print("\n2. Getting draft list (with content)...")
            draft_data_full = wechat.get_draft_list(offset=0, count=3, no_content=0)
            if draft_data_full:
                formatted_full = wechat.format_draft_list(draft_data_full, show_content=True)
                print(formatted_full)

        # Test token caching
        print("\n" + "-" * 30)
        print("Testing database cache...")
        token2 = wechat.get_access_token()
        print(f"Same token: {token == token2}")

    else:
        print("FAILED: Could not retrieve access token")


# Usage examples:
"""
# Basic usage with database storage:
from wechat_access_token import WeChatAccessToken

wechat = WeChatAccessToken("your_appid", "your_secret")
token = wechat.get_access_token()  # Automatically checks database first

# Get draft list:
draft_data = wechat.get_draft_list(offset=0, count=10, no_content=1)
if draft_data:
    formatted_output = wechat.format_draft_list(draft_data)
    print(formatted_output)

# Get draft list with full content:
draft_full = wechat.get_draft_list(offset=0, count=5, no_content=0)

# Custom database path:
wechat = WeChatAccessToken("your_appid", "your_secret", "custom_path.db")

# Check token status:
if wechat.is_token_valid():
    print("Token is valid")

# Get token info:
info = wechat.get_token_info()
print(f"Token expires in {info['remaining_seconds']} seconds")

# Force refresh token (bypass database cache):
new_token = wechat.get_access_token(force_refresh=True)

# Database management:
wechat.clear_expired_tokens()  # Remove expired tokens
all_tokens = wechat.get_all_tokens_info()  # View all tokens
"""

if __name__ == "__main__":
    main()
