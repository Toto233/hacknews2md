#!/usr/bin/env python3
"""
WeChat Access Token Tool
Automatically retrieves WeChat access token using app ID and secret.
Stores tokens in SQLite database with expiration management.

This module is a backward-compatible facade.  The actual implementation
lives in ``src.integrations.wechat`` (token / media / draft submodules).
"""

from publisher_shared.wechat.draft import DraftManager
from publisher_shared.wechat.media import MediaManager
from publisher_shared.wechat.token import TokenManager


class WeChatAccessToken:
    """
    Unified WeChat client -- thin facade over TokenManager / MediaManager / DraftManager.

    All public method signatures are preserved for backward compatibility.
    """

    def __init__(self, appid: str, secret: str, db_path: str = "data/hacknews.db") -> None:
        self._token_mgr = TokenManager(appid, secret, db_path)
        self._media_mgr = MediaManager(self._token_mgr)
        self._draft_mgr = DraftManager(self._token_mgr, self._media_mgr)

    # -- Token management (delegated to TokenManager) --------------------

    def _init_database(self) -> None:
        self._token_mgr._init_database()

    def _save_token_to_db(self, access_token: str, expires_in: int) -> bool:
        return self._token_mgr._save_token_to_db(access_token, expires_in)

    def _load_token_from_db(self) -> str | None:
        return self._token_mgr._load_token_from_db()

    def get_access_token(self, force_refresh: bool = False, retry_count: int = 2) -> str | None:
        return self._token_mgr.get_access_token(force_refresh=force_refresh, retry_count=retry_count)

    def is_token_valid(self) -> bool:
        return self._token_mgr.is_token_valid()

    def get_token_info(self) -> dict:
        return self._token_mgr.get_token_info()

    def clear_expired_tokens(self) -> int:
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

    def get_draft(self, media_id: str) -> dict | None:
        return self._draft_mgr.get_draft(media_id)

    def add_draft(self, articles: list) -> str | None:
        return self._draft_mgr.add_draft(articles)

    def add_draft_smart(
        self,
        articles: list,
        default_thumb_media_id: str = None,
        thumb_image_path: str = None,
        strict_images: bool = False,
    ) -> str | None:
        return self._draft_mgr.add_draft_smart(
            articles,
            default_thumb_media_id=default_thumb_media_id,
            thumb_image_path=thumb_image_path,
            strict_images=strict_images,
        )

    def format_draft_list(self, draft_data: dict, show_content: bool = False) -> str:
        return self._draft_mgr.format_draft_list(draft_data, show_content=show_content)
