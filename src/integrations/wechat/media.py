"""WeChat media uploads with local caching (permanent material & article images)."""

import hashlib
import json
import logging
import os
import sqlite3
import time
from datetime import datetime

import requests

logger = logging.getLogger(__name__)


class MediaManager:
    """Upload images / thumbs / permanent materials to WeChat."""

    def __init__(self, token_manager):
        self._tm = token_manager

    @property
    def appid(self) -> str:
        return self._tm.appid

    @property
    def db_path(self) -> str:
        return self._tm.db_path

    @staticmethod
    def _calculate_file_md5(file_path: str) -> str:
        h = hashlib.md5()
        try:
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    h.update(chunk)
            return h.hexdigest()
        except Exception as e:
            logger.error(f"Error calculating MD5 for {file_path}: {e}")
            return ""

    def _check_image_cache(self, file_path: str, upload_type: str = "article") -> dict | None:
        if not os.path.exists(file_path):
            return None
        file_md5 = self._calculate_file_md5(file_path)
        if not file_md5:
            return None
        today = datetime.now().date().isoformat()
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT * FROM image_uploads "
                    "WHERE file_md5=? AND upload_date=? AND upload_type=? AND appid=? "
                    "ORDER BY created_at DESC LIMIT 1",
                    (file_md5, today, upload_type, self.appid),
                ).fetchone()
                if row:
                    return {
                        "media_id": row["media_id"],
                        "media_url": row["media_url"],
                        "file_name": row["file_name"],
                        "file_size": row["file_size"],
                        "upload_type": row["upload_type"],
                        "cached": True,
                    }
        except Exception as e:
            logger.error(f"Error checking image cache: {e}")
        return None

    def _save_image_upload(self, file_path: str, upload_type: str, media_id: str = None, media_url: str = "") -> bool:
        if not os.path.exists(file_path):
            return False
        file_md5 = self._calculate_file_md5(file_path)
        if not file_md5:
            return False
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO image_uploads "
                    "(file_path,file_name,file_md5,file_size,upload_date,"
                    "upload_type,media_id,media_url,appid,created_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        file_path,
                        os.path.basename(file_path),
                        file_md5,
                        os.path.getsize(file_path),
                        datetime.now().date().isoformat(),
                        upload_type,
                        media_id,
                        media_url,
                        self.appid,
                        datetime.now(),
                    ),
                )
                conn.commit()
                logger.info(f"Image upload cached: {os.path.basename(file_path)} ({upload_type})")
                return True
        except Exception as e:
            logger.error(f"Error saving image upload record: {e}")
            return False

    def upload_permanent_material(
        self, file_path: str, media_type: str = "image", title: str = None, introduction: str = None
    ) -> dict | None:
        """Upload a permanent material (image/voice/video/thumb). Returns {media_id, url, type, file_path, cached}."""
        if media_type in ("image", "thumb"):
            cached = self._check_image_cache(file_path, media_type)
            if cached:
                logger.info(f"Using cached {media_type}: {cached['file_name']} (media_id: {cached['media_id']})")
                return {
                    "media_id": cached["media_id"],
                    "url": cached["media_url"],
                    "type": media_type,
                    "file_path": file_path,
                    "cached": True,
                }
        if media_type not in ("image", "voice", "video", "thumb"):
            logger.error("media_type must be one of ['image', 'voice', 'video', 'thumb']")
            return None
        if not os.path.exists(file_path):
            logger.error(f"File not found: {file_path}")
            return None
        if media_type == "video" and not title:
            logger.error("Video media requires title parameter")
            return None
        access_token = self._tm.get_access_token()
        if not access_token:
            logger.error("Could not get access token")
            return None
        url = f"https://api.weixin.qq.com/cgi-bin/material/add_material?access_token={access_token}&type={media_type}"
        for attempt in range(2):
            try:
                logger.info(f"{'Retrying' if attempt > 0 else 'Uploading'} permanent {media_type}: {file_path}")
                with open(file_path, "rb") as f:
                    files = {"media": (os.path.basename(file_path), f, "application/octet-stream")}
                    data = {}
                    if media_type == "video" and title:
                        data = {"description": json.dumps({"title": title, "introduction": introduction or ""})}
                    response = requests.post(url, files=files, data=data, timeout=60)
                    response.raise_for_status()
                result = response.json()
                if "media_id" in result:
                    media_id = result["media_id"]
                    media_url = result.get("url", "N/A")
                    logger.info(f"Successfully uploaded permanent material! Media ID: {media_id}")
                    if media_url != "N/A":
                        logger.info(f"Media URL: {media_url}")
                    if media_type in ("image", "thumb"):
                        self._save_image_upload(file_path, media_type, media_id, media_url)
                    return {
                        "media_id": media_id,
                        "url": media_url,
                        "type": media_type,
                        "file_path": file_path,
                        "cached": False,
                    }
                logger.error(f"WeChat API error {result.get('errcode')}: {result.get('errmsg')}")
                if attempt == 0:
                    time.sleep(1)
                    continue
                return None
            except Exception as e:
                logger.error(f"Upload error: {e}")
                if attempt == 0:
                    time.sleep(1)
                    continue
                return None
        return None

    def upload_image_for_article(self, file_path: str) -> str | None:
        """Upload an image for article content (non-permanent). Returns URL on success."""
        cached = self._check_image_cache(file_path, "article")
        if cached:
            logger.info(f"Using cached article image: {cached['file_name']} -> {cached['media_url']}")
            return cached["media_url"]
        if not os.path.exists(file_path):
            logger.error(f"File not found: {file_path}")
            return None
        file_ext = os.path.splitext(file_path)[1].lower()
        if file_ext not in (".jpg", ".jpeg", ".png", ".webp"):
            logger.error("Only jpg/png/webp formats are supported")
            return None
        if os.path.getsize(file_path) > 1024 * 1024:
            logger.warning(f"[SKIP] File exceeds 1MB auto-upload limit: {file_path}")
            return None
        access_token = self._tm.get_access_token()
        if not access_token:
            logger.error("Could not get access token")
            return None
        url = f"https://api.weixin.qq.com/cgi-bin/media/uploadimg?access_token={access_token}"
        mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
        for attempt in range(2):
            try:
                logger.info(f"{'Retrying' if attempt > 0 else 'Uploading'} article image: {file_path}")
                with open(file_path, "rb") as f:
                    files = {
                        "media": (os.path.basename(file_path), f, mime_map.get(file_ext, "application/octet-stream"))
                    }
                    response = requests.post(url, files=files, timeout=30)
                    response.raise_for_status()
                result = response.json()
                if "url" in result and result.get("errcode", 0) == 0:
                    image_url = result["url"]
                    logger.info(f"Successfully uploaded article image! URL: {image_url}")
                    self._save_image_upload(file_path, "article", None, image_url)
                    return image_url
                logger.error(f"WeChat API error {result.get('errcode')}: {result.get('errmsg')}")
                if attempt == 0:
                    time.sleep(1)
                    continue
                return None
            except Exception as e:
                logger.error(f"Upload error: {e}")
                if attempt == 0:
                    time.sleep(1)
                    continue
                return None
        return None
