"""
Image handler -- extracted from summarize_news5.py.

Downloads article images, converts unsupported formats (avif/webp) to PNG,
and enforces a minimum dimension filter.
"""

import hashlib
import logging
import os
import re
import uuid
from datetime import datetime
from urllib.parse import unquote, urlparse

import certifi
import requests

from src.security.url_validator import SecurityError, validate_url
from src.utils.http_constants import IMAGE_HEADERS

logger = logging.getLogger(__name__)

LOW_SIGNAL_IMAGE_TOKENS = (
    "logo",
    "lockup",
    "wordmark",
    "brandmark",
    "branding",
    "badge",
    "shield",
    "icon",
    "favicon",
    "touch-icon",
    "apple-touch-icon",
    "sprite",
    "avatar",
    "social",
    "share",
    "og-image",
    "cropped",
    "certified",
    "cc-by",
    "creative-commons",
    "app-store",
    "googleplay",
)


def get_extension_from_content_type(content_type: str) -> str | None:
    """Return a file extension (e.g. '.jpg') for the given Content-Type header value."""
    content_type = content_type.lower()
    if "jpeg" in content_type or "jpg" in content_type:
        return ".jpg"
    elif "png" in content_type:
        return ".png"
    elif "gif" in content_type:
        return ".gif"
    elif "webp" in content_type:
        return ".webp"
    elif "avif" in content_type:
        return ".avif"
    elif "svg" in content_type:
        return ".svg"
    return None


def is_low_signal_article_image_url(image_url: str) -> bool:
    """Return True for likely decorative image assets such as logos and badges."""
    try:
        parsed = urlparse(image_url)
    except Exception:
        return False

    host = parsed.netloc.lower()
    path = unquote(parsed.path).lower()
    query = unquote(parsed.query).lower()
    haystack = f"{host}/{path}?{query}"
    decoded_hex_parts = []
    for part in path.strip("/").split("/"):
        if len(part) >= 16 and re.fullmatch(r"[0-9a-f]+", part):
            try:
                decoded_hex_parts.append(bytes.fromhex(part).decode("utf-8", errors="ignore").lower())
            except ValueError:
                pass
    if decoded_hex_parts:
        haystack = f"{haystack} {' '.join(decoded_hex_parts)}"

    if path.endswith(".svg"):
        return True
    if "placeholder" in path:
        return True
    if host.endswith("twimg.com") and "/profile_images/" in path and re.search(
        r"_(?:normal|bigger|mini)\.[a-z0-9]+$", path
    ):
        return True
    if host == "news.ycombinator.com" and path.endswith("/s.gif"):
        return True
    if any(token in haystack for token in LOW_SIGNAL_IMAGE_TOKENS):
        return True
    dimension_match = re.search(r"(?:^|[/?_,])w_(\d+),h_(\d+)(?:[,_/?]|$)", haystack)
    if dimension_match:
        width = int(dimension_match.group(1))
        height = int(dimension_match.group(2))
        if width < 100 or height < 100:
            return True
    return False


def _reserve_image_path(date_dir: str, title: str | None, extension: str, image_url: str) -> str:
    """Reserve a unique final filename before concurrent download work starts."""
    if title:
        stem = re.sub(r'[<>:"/\\|?*]', "", title).replace(" ", "_")
        stem = re.sub(r"_{2,}", "_", stem)[:50] or "image"
    else:
        stem = hashlib.md5(image_url.encode()).hexdigest()

    index = 1
    while True:
        suffix = "" if index == 1 else f"_{index}"
        candidate = os.path.join(date_dir, f"{stem}{suffix}{extension}")
        try:
            descriptor = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            index += 1
            continue
        os.close(descriptor)
        return candidate


def save_article_image(
    image_url: str,
    referer_url: str,
    title: str | None = None,
) -> str | None:
    """Download an image and save it locally.

    Args:
        image_url:   Direct URL of the image.
        referer_url: Referer header value (usually the article URL).
        title:       Optional human-readable name used for the filename.

    Returns:
        Absolute path to the saved file, or ``None`` on failure.
    """
    # SSRF protection: validate image URL before fetching
    try:
        validate_url(image_url)
    except (SecurityError, ValueError) as e:
        logger.warning(f"[IMAGE] URL validation failed | {e} | url={image_url[:80]}")
        return None

    headers = {**IMAGE_HEADERS, "Referer": referer_url}

    try:
        from PIL import Image

        response = requests.get(image_url, headers=headers, verify=certifi.where(), stream=True)
        if response.status_code != 200:
            return None

        content_type = response.headers.get("Content-Type", "").lower()
        if not content_type.startswith("image/"):
            return None

        ext = get_extension_from_content_type(content_type)
        if not ext:
            return None
        if ext == ".svg":
            return None

        today = datetime.now()
        date_dir = os.path.join("output/images", f"{today.year:04d}{today.month:02d}{today.day:02d}")
        os.makedirs(date_dir, exist_ok=True)

        final_extension = ".png" if ext in {".avif", ".webp"} else ext
        final_path = _reserve_image_path(date_dir, title, final_extension, image_url)
        temporary_path = os.path.join(date_dir, f".{uuid.uuid4().hex}{ext}.part")
        converted_path: str | None = None
        saved = False
        try:
            with open(temporary_path, "wb") as image_file:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        image_file.write(chunk)
                image_file.flush()
                os.fsync(image_file.fileno())

            with Image.open(temporary_path) as image:
                width, height = image.size
                if width < 100 or height < 100:
                    return None
                if ext in {".avif", ".webp"}:
                    converted_path = os.path.join(date_dir, f".{uuid.uuid4().hex}.png.part")
                    image.save(converted_path, "PNG")

            os.replace(converted_path or temporary_path, final_path)
            saved = True
            logger.info("Saved article image: %s", final_path)
            return os.path.abspath(final_path)
        except Exception as exc:
            logger.error("Failed to process article image: %s", exc)
            return None
        finally:
            cleanup_paths = (temporary_path, converted_path)
            if not saved:
                cleanup_paths += (final_path,)
            for path in cleanup_paths:
                if path and os.path.exists(path):
                    try:
                        os.remove(path)
                    except OSError:
                        logger.debug("Could not remove temporary image path: %s", path)
    except Exception:
        return None
