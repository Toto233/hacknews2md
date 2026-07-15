"""
Image handler -- extracted from summarize_news5.py.

Downloads article images, converts unsupported formats (avif/webp/svg) to PNG,
and enforces a minimum dimension filter.
"""

import hashlib
import logging
import os
import re
import time
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

    if any(token in haystack for token in LOW_SIGNAL_IMAGE_TOKENS):
        return True
    if path.endswith(".svg") and ("/assets/" in path or "/_astro/" in path or "/static/" in path):
        return True
    dimension_match = re.search(r"(?:^|[/?_,])w_(\d+),h_(\d+)(?:[,_/?]|$)", haystack)
    if dimension_match:
        width = int(dimension_match.group(1))
        height = int(dimension_match.group(2))
        if width < 100 or height < 100:
            return True
    return False


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

        today = datetime.now()
        date_dir = os.path.join("output/images", f"{today.year:04d}{today.month:02d}{today.day:02d}")
        if not os.path.exists(date_dir):
            os.makedirs(date_dir)

        if title:
            clean_title = re.sub(r'[<>:"/\\|?*]', "", title)
            clean_title = clean_title.replace(" ", "_")
            clean_title = re.sub(r"_{2,}", "_", clean_title)
            clean_title = clean_title[:50]
            index = 1
            while True:
                filename = f"{clean_title}{ext}" if index == 1 else f"{clean_title}_{index}{ext}"
                full_path = os.path.join(date_dir, filename)
                if not os.path.exists(full_path):
                    break
                index += 1
        else:
            filename = hashlib.md5(image_url.encode()).hexdigest() + ext
            full_path = os.path.join(date_dir, filename)

        with open(full_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
            f.flush()
            os.fsync(f.fileno())

        # Brief pause for Windows file-lock release
        time.sleep(0.1)

        try:
            with Image.open(full_path) as img:
                width, height = img.size
                if width < 100 or height < 100:
                    os.remove(full_path)
                    return None

                # Convert avif / webp / svg to PNG for broader compatibility
                if ext in [".avif", ".webp", ".svg"]:
                    png_path = full_path.replace(ext, ".png")
                    img.save(png_path, "PNG")
                    os.remove(full_path)
                    logger.info(f"已将 {ext} 图片转换为 png: {png_path}")
                    return os.path.abspath(png_path)

                return os.path.abspath(full_path)
        except Exception as e:
            logger.error(f"处理图片时出错: {e}")
            if os.path.exists(full_path):
                os.remove(full_path)
            return None
    except Exception:
        return None
