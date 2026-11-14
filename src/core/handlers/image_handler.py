"""
Image handler -- extracted from summarize_news5.py.

Downloads article images, converts unsupported formats (avif/webp) to PNG,
and enforces a minimum dimension filter.
"""

import hashlib
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

import certifi
import requests
import structlog

from src.core.github_visuals import is_github_social_preview_url
from src.security.url_validator import SecurityError, validate_url
from src.utils.filename import sanitize_filename_stem
from src.utils.http_constants import IMAGE_HEADERS

logger = structlog.get_logger()

MIN_ARTICLE_IMAGE_SIDE = 100
ARTICLE_IMAGE_TIMEOUT = (5, 15)


@dataclass(frozen=True)
class ArticleImageResult:
    path: str | None = None
    reason: str | None = None
    status_code: int | None = None

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
    "mf-name",
    "lcorner",
)

TRACKING_IMAGE_HOSTS = (
    "ads.linkedin.com",
    "analytics.brave.com",
    "facebook.com",
    "scorecardresearch.com",
    "google-analytics.com",
    "goatcounter.com",
    "doubleclick.net",
    "googlesyndication.com",
    "vgwort.de",
)

DECORATIVE_IMAGE_FILENAMES = frozenset({
    "leftarrow.gif", "rightarrow.gif", "tree-opened.gif", "tree-closed.gif",
    "tree-node.gif", "playstore.en.png",
})


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

    host = parsed.hostname or ""
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
    if any(host == suffix or host.endswith(f".{suffix}") for suffix in TRACKING_IMAGE_HOSTS):
        return True
    if host == "emoji.discourse-cdn.com" or path.rsplit("/", 1)[-1] in DECORATIVE_IMAGE_FILENAMES:
        return True
    if path.endswith("/rss.png") or path.endswith("/rss.gif"):
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
        if min(width, height) < MIN_ARTICLE_IMAGE_SIDE:
            return True
    # Resized thumbnails and image filenames with explicit output dimensions.
    dimensions = re.search(
        r"/thumbnail/(\d{1,5})x(\d{1,5})/|[-_](\d{1,5})x(\d{1,5})\.(?:jpe?g|png|gif|webp|avif)$",
        path,
    )
    if dimensions and min(int(side) for side in dimensions.groups() if side) < MIN_ARTICLE_IMAGE_SIDE:
        return True
    explicit_dimensions = {
        key: int(value)
        for key, value in re.findall(r"(?:^|[?&])(w|h|width|height)=(\d+)(?:&|$)", query)
    }
    if any(value < MIN_ARTICLE_IMAGE_SIDE for value in explicit_dimensions.values()):
        return True
    return False


def is_article_image_candidate(image_url: str, *, github_page: bool) -> bool:
    """Keep official GitHub cards and ignore repository names when filtering README images."""
    if github_page:
        try:
            parsed = urlparse(image_url)
            if is_github_social_preview_url(image_url):
                return True
        except ValueError:
            return False
        image_url = parsed._replace(path=f"/{parsed.path.rsplit('/', 1)[-1]}").geturl()
    return not is_low_signal_article_image_url(image_url)


def _reserve_image_path(date_dir: Path, title: str | None, extension: str, image_url: str) -> Path:
    """Reserve a unique final filename before concurrent download work starts."""
    if title:
        stem = sanitize_filename_stem(title)
    else:
        stem = hashlib.md5(image_url.encode()).hexdigest()

    index = 1
    while True:
        suffix = "" if index == 1 else f"_{index}"
        candidate = date_dir / f"{stem}{suffix}{extension}"
        try:
            descriptor = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            index += 1
            continue
        os.close(descriptor)
        return candidate


def download_article_image(
    image_url: str,
    referer_url: str,
    title: str | None = None,
) -> ArticleImageResult:
    """Save a usable image or report the reason it could not be used."""
    try:
        validate_url(image_url)
    except (SecurityError, ValueError):
        return ArticleImageResult(reason="invalid_url")

    try:
        with requests.get(
            image_url,
            headers={**IMAGE_HEADERS, "Referer": referer_url},
            verify=certifi.where(),
            stream=True,
            timeout=ARTICLE_IMAGE_TIMEOUT,
        ) as response:
            if response.status_code != 200:
                return ArticleImageResult(reason="http_status", status_code=response.status_code)

            content_type = response.headers.get("Content-Type", "").lower()
            if not content_type.startswith("image/"):
                return ArticleImageResult(reason="non_image_response")

            extension = get_extension_from_content_type(content_type)
            if not extension or extension == ".svg":
                return ArticleImageResult(reason="unsupported_format")

            return _save_image_response(response, extension, title, image_url)
    except requests.exceptions.Timeout:
        return ArticleImageResult(reason="timeout")
    except requests.exceptions.RequestException as exc:
        # Requests wraps streamed read timeouts as ConnectionError.
        if isinstance(exc.__context__, requests.packages.urllib3.exceptions.ReadTimeoutError):
            return ArticleImageResult(reason="timeout")
        return ArticleImageResult(reason="request_failed")
    except OSError:
        return ArticleImageResult(reason="write_failed")


def _save_image_response(
    response: requests.Response, extension: str, title: str | None, image_url: str
) -> ArticleImageResult:
    from PIL import Image

    date_dir = Path("output/images") / datetime.now().strftime("%Y%m%d")
    date_dir.mkdir(parents=True, exist_ok=True)
    convert_to_png = extension in {".avif", ".webp"}
    final_path = _reserve_image_path(date_dir, title, ".png" if convert_to_png else extension, image_url)
    temporary_path = date_dir / f".{uuid.uuid4().hex}{extension}.part"
    converted_path = date_dir / f".{uuid.uuid4().hex}.png.part" if convert_to_png else None
    saved = False
    try:
        with temporary_path.open("wb") as image_file:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    image_file.write(chunk)
            image_file.flush()
            os.fsync(image_file.fileno())

        try:
            with Image.open(temporary_path) as image:
                if min(image.size) < MIN_ARTICLE_IMAGE_SIDE:
                    return ArticleImageResult(reason="too_small")
                image.load()
                if converted_path:
                    try:
                        image.save(converted_path, "PNG")
                    except OSError:
                        return ArticleImageResult(reason="write_failed")
        except (OSError, ValueError, SyntaxError, Image.DecompressionBombError):
            return ArticleImageResult(reason="decode_failed")

        (converted_path or temporary_path).replace(final_path)
        saved = True
        logger.info("saved_article_image", path=str(final_path))
        return ArticleImageResult(path=str(final_path.absolute()))
    finally:
        for path in (temporary_path, converted_path, None if saved else final_path):
            if path is not None:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    logger.debug("article_image_cleanup_failed", path=str(path))


def save_article_image(image_url: str, referer_url: str, title: str | None = None) -> str | None:
    """Download an image, returning its absolute path or None for older callers."""
    try:
        result = download_article_image(image_url, referer_url, title)
    except Exception:
        logger.debug("article_image_download_failed", reason="exception")
        return None
    if result.reason:
        logger.debug("article_image_download_failed", reason=result.reason, status_code=result.status_code)
    return result.path
