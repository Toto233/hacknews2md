"""
X/Twitter content handler -- extracted from summarize_news5.py.

Provides multiple strategies for fetching tweet content:
  1. twscrape (primary, async, supports replies)
  2. vxtwitter API (lightweight, no auth)
  3. Selenium fallback (full browser rendering)
  4. Screenshot capture with cookie authentication
"""

import logging
import os
import re
import time
from datetime import datetime
from urllib.parse import urlparse

import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from src.security.url_validator import SecurityError, validate_url
from src.utils.http_constants import DEFAULT_HEADERS

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# URL detection helpers
# ---------------------------------------------------------------------------


def _is_x_url(url: str) -> bool:
    """Check whether *url* belongs to X / Twitter."""
    try:
        netloc = urlparse(url).netloc.lower()
        return any(domain in netloc for domain in ["x.com", "twitter.com", "mobile.twitter.com", "m.twitter.com"])
    except Exception:
        return False


def _extract_tweet_id(url: str) -> str:
    """Extract the numeric tweet ID from a Twitter / X URL."""
    try:
        parsed = urlparse(url)
        parts = [p for p in parsed.path.split("/") if p]
        if "status" in parts:
            idx = parts.index("status")
            if idx + 1 < len(parts):
                candidate = parts[idx + 1]
                candidate = candidate.split("?")[0].split("#")[0]
                if candidate.isdigit():
                    return candidate
        return ""
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# vxtwitter API (no auth required)
# ---------------------------------------------------------------------------


def _fetch_x_via_vxtwitter(tweet_id: str) -> tuple[str, list[str]]:
    """Fetch tweet text and media via the vxtwitter public API."""
    if not tweet_id:
        return "", []

    api = f"https://api.vxtwitter.com/Twitter/status/{tweet_id}"
    headers = {
        "User-Agent": DEFAULT_HEADERS["User-Agent"],
        "Accept": "application/json",
    }

    try:
        resp = requests.get(api, headers=headers, timeout=15)
        if resp.status_code != 200:
            return "", []

        data = resp.json()
        text = data.get("text") or ""
        image_urls: list[str] = []

        for u in data.get("mediaURLs") or []:
            if isinstance(u, str) and u.startswith("http"):
                image_urls.append(u)

        for m in data.get("media_extended") or []:
            u = (m.get("url") or m.get("source")) if isinstance(m, dict) else None
            if u and isinstance(u, str) and u.startswith("http"):
                image_urls.append(u)

        # Deduplicate while preserving order
        seen: set = set()
        deduped: list[str] = []
        for u in image_urls:
            if u not in seen:
                seen.add(u)
                deduped.append(u)

        return text, deduped
    except Exception as e:
        logging.warning(f"_fetch_x_via_vxtwitter failed for {tweet_id}: {e}")
        return "", []


# ---------------------------------------------------------------------------
# Selenium fallback
# ---------------------------------------------------------------------------


def _fetch_x_via_selenium(url: str) -> tuple[str, list[str]]:
    """Fetch tweet content via headless Selenium (sync)."""
    # SSRF protection: validate URL before fetching
    try:
        validate_url(url)
    except (SecurityError, ValueError) as e:
        logger.warning(f"[X] URL validation failed | {e} | url={url[:80]}")
        return "", []

    options = ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1400,1000")
    options.add_argument("--lang=en-US")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )

    driver = None
    try:
        driver = webdriver.Chrome(options=options)
        driver.get(url)
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'article [data-testid="tweetText"]'))
        )

        text_blocks: list[str] = []
        for el in driver.find_elements(By.CSS_SELECTOR, 'article [data-testid="tweetText"]'):
            try:
                t = el.text.strip()
                if t:
                    text_blocks.append(t)
            except Exception:
                pass
        text = "\n\n".join(text_blocks).strip()

        image_urls: list[str] = []
        for img in driver.find_elements(
            By.CSS_SELECTOR,
            'article [data-testid="tweetPhoto"] img, article img[src*="pbs.twimg.com/media"]',
        ):
            try:
                src = img.get_attribute("src")
                if src and src.startswith("http"):
                    image_urls.append(src)
            except Exception:
                pass

        # Deduplicate
        seen: set = set()
        deduped: list[str] = []
        for u in image_urls:
            if u not in seen:
                seen.add(u)
                deduped.append(u)

        return text, deduped[:5]
    except Exception as e:
        logging.warning(f"_fetch_x_via_selenium failed for {url}: {e}")
        return "", []
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# twscrape (primary method -- async, supports replies)
# ---------------------------------------------------------------------------

_twscrape_api = None


async def _init_twscrape() -> bool:
    """Initialise the twscrape API singleton from config.json credentials."""
    global _twscrape_api
    if _twscrape_api is not None:
        return True

    try:
        import json as _json

        from twscrape import API

        config_path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "config", "config.json")
        if not os.path.exists(config_path):
            logger.warning("[X] config.json does not exist, cannot init twscrape")
            return False

        with open(config_path, encoding="utf-8") as f:
            config = _json.load(f)

        twitter_cfg = config.get("twitter", {})
        if not twitter_cfg:
            logger.warning("[X] 'twitter' section missing from config.json")
            return False

        _twscrape_api = API()
        username = twitter_cfg.get("username", "")

        # Cookie-based auth (preferred for Google-login users)
        auth_token = twitter_cfg.get("auth_token", "")
        ct0 = twitter_cfg.get("ct0", "")
        if auth_token and ct0:
            cookies_str = f"auth_token={auth_token}; ct0={ct0}"
            cookie_user = username or "x_user"
            try:
                await _twscrape_api.pool.add_account_cookies(cookie_user, cookies_str)
                logger.info(f"[X] twscrape cookie login OK | {cookie_user}")
            except Exception as e:
                logger.info(f"[X] twscrape add_account_cookies: {e}")
            return True

        # Fallback to username/password
        password = twitter_cfg.get("password", "")
        email = twitter_cfg.get("email", "")
        email_password = twitter_cfg.get("email_password", "")

        if not username or not password:
            logger.warning("[X] No twitter credentials or cookie in config.json")
            return False

        try:
            await _twscrape_api.pool.add_account(
                username=username,
                password=password,
                email=email,
                email_password=email_password,
            )
            await _twscrape_api.pool.login_all()
            logger.info(f"[X] twscrape account login OK | {username}")
        except Exception as e:
            logger.info(f"[X] twscrape add_account: {e}")

        return True
    except ImportError:
        logger.warning("[X] twscrape not installed")
        return False
    except Exception as e:
        logger.error(f"[X] twscrape init failed: {e}")
        return False


async def _fetch_x_via_twscrape(tweet_id: str, url: str) -> tuple[str, list[str]]:
    """Fetch tweet content + replies via twscrape."""
    if not tweet_id:
        return "", []

    if not await _init_twscrape():
        return "", []

    try:
        twid = int(tweet_id)

        # 1. Fetch main tweet
        tweet = await _twscrape_api.tweet_details(twid)
        if not tweet:
            logger.warning(f"[X] twscrape tweet not found | ID:{tweet_id}")
            return "", []

        parts: list[str] = []
        author = tweet.user.displayname if tweet.user else "Unknown"
        parts.append(f"@{tweet.user.username}: {tweet.rawContent}" if tweet.user else tweet.rawContent)

        # Collect images
        image_urls: list[str] = []
        if tweet.media:
            for photo in tweet.media.photos or []:
                if photo.url:
                    image_urls.append(photo.url)

        # 2. Fetch replies
        replies: list[str] = []
        try:
            async for reply in _twscrape_api.tweet_replies(twid, limit=20):
                if reply and reply.rawContent:
                    reply_author = reply.user.displayname if reply.user else "Unknown"
                    replies.append(f"@{reply.user.username}: {reply.rawContent}" if reply.user else reply.rawContent)
                    # Collect images from replies
                    if reply.media:
                        for photo in reply.media.photos or []:
                            if photo.url and len(image_urls) < 5:
                                image_urls.append(photo.url)
        except Exception as e:
            logger.warning(f"[X] twscrape reply fetch failed: {e}")

        if replies:
            parts.append("\n--- 评论/回复 ---")
            parts.extend(replies[:15])  # Max 15 replies

        content = "\n\n".join(parts)
        logger.info(
            f"[X] twscrape OK | tweet len:{len(tweet.rawContent)} | replies:{len(replies)} | images:{len(image_urls)}"
        )
        return content, image_urls

    except Exception as e:
        logger.error(f"[X] twscrape fetch failed: {e}")
        return "", []


# ---------------------------------------------------------------------------
# Screenshot tweet page (Selenium + cookie auth)
# ---------------------------------------------------------------------------


async def _screenshot_x_tweet(url: str, title: str) -> str | None:
    """Capture a screenshot of the tweet page using Selenium + cookie auth."""
    # SSRF protection: validate URL before fetching
    try:
        validate_url(url)
    except (SecurityError, ValueError) as e:
        logger.warning(f"[X] URL validation failed | {e} | url={url[:80]}")
        return None

    try:
        import json as _json

        config_path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "config", "config.json")
        if not os.path.exists(config_path):
            return None
        with open(config_path, encoding="utf-8") as f:
            config = _json.load(f)
        twitter_cfg = config.get("twitter", {})
        auth_token = twitter_cfg.get("auth_token", "")
        ct0 = twitter_cfg.get("ct0", "")
        if not auth_token or not ct0:
            return None

        today = datetime.now()
        date_dir = os.path.join("output/images", f"{today.year:04d}{today.month:02d}{today.day:02d}")
        if not os.path.exists(date_dir):
            os.makedirs(date_dir)
        clean_title = re.sub(r'[<>:"/\\|?*]', "", title).replace(" ", "_")
        clean_title = re.sub(r"_{2,}", "_", clean_title)[:50]
        image_save_path = os.path.join(date_dir, f"{clean_title}_screenshot.png")

        options = ChromeOptions()
        options.add_argument("--headless")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1280,1024")
        options.add_argument(
            "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )

        driver = None
        try:
            driver = webdriver.Chrome(options=options)
            # Visit x.com first to set cookies
            driver.get("https://x.com")
            time.sleep(2)
            driver.add_cookie(
                {
                    "name": "auth_token",
                    "value": auth_token,
                    "domain": ".x.com",
                    "path": "/",
                }
            )
            driver.add_cookie(
                {
                    "name": "ct0",
                    "value": ct0,
                    "domain": ".x.com",
                    "path": "/",
                }
            )
            # Navigate to the tweet
            driver.get(url)
            time.sleep(8)
            driver.save_screenshot(image_save_path)
            saved = os.path.abspath(image_save_path)
            logger.info(f"[X] screenshot OK | {saved}")
            return saved
        except Exception as e:
            logger.warning(f"[X] screenshot failed: {e}")
            return None
        finally:
            if driver:
                driver.quit()
    except Exception as e:
        logger.warning(f"[X] screenshot error: {e}")
        return None
