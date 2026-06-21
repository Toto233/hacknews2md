"""
WeChat Access Token management.

Handles token lifecycle: fetch from API, persist in SQLite, reload on restart,
auto-refresh on expiry.  Also initialises the image_uploads cache table used by
the media module.
"""

import json
import logging
import sqlite3
import time
from datetime import datetime, timedelta

import requests

logger = logging.getLogger(__name__)


class TokenManager:
    """WeChat access-token persistence and refresh."""

    def __init__(self, appid: str, secret: str, db_path: str = "data/hacknews.db"):
        self.appid = appid
        self.secret = secret
        self.db_path = db_path
        self.access_token: str | None = None
        self.expires_at: datetime | None = None
        self._init_database()

    # ------------------------------------------------------------------
    # Database bootstrap
    # ------------------------------------------------------------------

    def _init_database(self) -> None:
        """Create tables if they do not exist."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS access_tokens (
                        appid          TEXT PRIMARY KEY,
                        access_token   TEXT      NOT NULL,
                        created_at     TIMESTAMP NOT NULL,
                        expires_at     TIMESTAMP NOT NULL,
                        expires_in     INTEGER   NOT NULL
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS image_uploads (
                        id           INTEGER PRIMARY KEY AUTOINCREMENT,
                        file_path    TEXT    NOT NULL,
                        file_name    TEXT    NOT NULL,
                        file_md5     TEXT    NOT NULL,
                        file_size    INTEGER NOT NULL,
                        upload_date  DATE    NOT NULL,
                        upload_type  TEXT    NOT NULL,
                        media_id     TEXT,
                        media_url    TEXT    NOT NULL,
                        appid        TEXT    NOT NULL,
                        created_at   TIMESTAMP NOT NULL,
                        UNIQUE(file_md5, upload_date, upload_type, appid)
                    )
                """)
                conn.commit()
                logger.info(f"Database initialized: {self.db_path}")
        except Exception as e:
            logger.error(f"Database initialization error: {e}")

    # ------------------------------------------------------------------
    # Token persistence
    # ------------------------------------------------------------------

    def _save_token_to_db(self, access_token: str, expires_in: int) -> bool:
        """Persist a freshly obtained token."""
        try:
            created_at = datetime.now()
            expires_at = created_at + timedelta(seconds=expires_in - 300)
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO access_tokens "
                    "(appid, access_token, created_at, expires_at, expires_in) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (self.appid, access_token, created_at, expires_at, expires_in),
                )
                conn.commit()
            self.access_token = access_token
            self.expires_at = expires_at
            logger.info(f"Token saved to database, expires at: {expires_at}")
            return True
        except Exception as e:
            logger.error(f"Error saving token to database: {e}")
            return False

    def _load_token_from_db(self) -> str | None:
        """Return a valid cached token, or *None*."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute(
                    "SELECT access_token, expires_at, created_at, expires_in FROM access_tokens WHERE appid = ?",
                    (self.appid,),
                )
                row = cursor.fetchone()
                if not row:
                    logger.info("No token found in database")
                    return None
                expires_at = datetime.fromisoformat(row["expires_at"])
                if datetime.now() < expires_at:
                    self.access_token = row["access_token"]
                    self.expires_at = expires_at
                    remaining = (expires_at - datetime.now()).total_seconds()
                    logger.info(f"Valid token found in database (expires in {int(remaining)} seconds)")
                    return row["access_token"]
                logger.info("Token in database has expired")
                conn.execute("DELETE FROM access_tokens WHERE appid = ?", (self.appid,))
                conn.commit()
                return None
        except Exception as e:
            logger.error(f"Error loading token from database: {e}")
            return None

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def get_access_token(self, force_refresh: bool = False, retry_count: int = 2) -> str | None:
        """
        Return a usable access token.

        Checks the local DB first (unless *force_refresh*), then requests a
        new one from the WeChat API with up to *retry_count* attempts.
        """
        if not force_refresh:
            db_token = self._load_token_from_db()
            if db_token:
                return db_token

        url = "https://api.weixin.qq.com/cgi-bin/token"
        params = {
            "grant_type": "client_credential",
            "appid": self.appid,
            "secret": self.secret,
        }

        for attempt in range(retry_count):
            try:
                if attempt > 0:
                    logger.info(f"Retrying to get access token (attempt {attempt + 1}/{retry_count})...")
                else:
                    logger.info("Requesting new access token from WeChat API...")

                response = requests.get(url, params=params, timeout=10)
                response.raise_for_status()
                data = response.json()

                if "access_token" in data:
                    token = data["access_token"]
                    expires_in = data.get("expires_in", 7200)
                    if self._save_token_to_db(token, expires_in):
                        logger.info("New access token retrieved and saved!")
                        logger.debug(f"Token: {token[:20]}...")
                    else:
                        logger.warning("Token retrieved but failed to save to database")
                    return token

                error_code = data.get("errcode", "unknown")
                error_msg = data.get("errmsg", "unknown error")
                logger.error(f"WeChat API error {error_code}: {error_msg}")
                if attempt < retry_count - 1:
                    logger.info("Will retry in 2 seconds...")
                    time.sleep(2)
                continue

            except (requests.exceptions.RequestException, json.JSONDecodeError, Exception) as e:
                logger.error(f"Error: {e}")
                if attempt < retry_count - 1:
                    logger.info("Will retry in 2 seconds...")
                    time.sleep(2)
                continue

        return None

    def is_token_valid(self) -> bool:
        if not self.access_token or not self.expires_at:
            return self._load_token_from_db() is not None
        return datetime.now() < self.expires_at

    def get_token_info(self) -> dict:
        if not self.access_token:
            self._load_token_from_db()
        return {
            "access_token": self.access_token,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "is_valid": self.is_token_valid(),
            "remaining_seconds": (self.expires_at - datetime.now()).total_seconds() if self.expires_at else 0,
            "db_path": self.db_path,
        }

    def clear_expired_tokens(self) -> int:
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("DELETE FROM access_tokens WHERE datetime(expires_at) < datetime('now')")
                deleted = cursor.rowcount
                conn.commit()
                logger.info(f"Cleared {deleted} expired tokens from database")
                return deleted
        except Exception as e:
            logger.error(f"Error clearing expired tokens: {e}")
            return 0

    def get_all_tokens_info(self) -> list:
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute(
                    "SELECT appid, access_token, created_at, expires_at, expires_in, "
                    "datetime(expires_at) > datetime('now') AS is_valid "
                    "FROM access_tokens ORDER BY created_at DESC"
                )
                return [
                    {
                        "appid": r["appid"],
                        "access_token": r["access_token"][:20] + "...",
                        "created_at": r["created_at"],
                        "expires_at": r["expires_at"],
                        "expires_in": r["expires_in"],
                        "is_valid": bool(r["is_valid"]),
                    }
                    for r in cursor.fetchall()
                ]
        except Exception as e:
            logger.error(f"Error getting tokens info: {e}")
            return []
