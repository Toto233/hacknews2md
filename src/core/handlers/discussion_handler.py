"""
Discussion content handler -- extracted from summarize_news5.py.

Parses Hacker News discussion pages (main post + comments) using
aiohttp for fetching and BeautifulSoup for parsing, with a Selenium
fallback for JavaScript-rendered content.
"""

import asyncio
import logging
import os
import re
import time
import traceback

from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from src.security.url_validator import SecurityError, validate_url

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Selenium fallback (sync, meant for asyncio.to_thread)
# ---------------------------------------------------------------------------


def _fetch_discussion_via_selenium(url: str) -> str:
    """Fetch discussion page HTML via headless Selenium (synchronous)."""
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
        WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        time.sleep(2)
        html = driver.page_source
        return html
    except Exception as e:
        logger.warning(f"[SELENIUM] fetch failed: {e}")
        return ""
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Main async entry point
# ---------------------------------------------------------------------------


async def get_discussion_content_async(url: str) -> str:
    """Fetch and parse a Hacker News discussion page.

    Tries aiohttp first, falls back to Selenium if the response is
    too short or the request fails.

    Returns:
        Concatenated text of the main post and top-level comments,
        or an empty string on failure.
    """
    if not url:
        return ""

    # SSRF protection: validate URL before fetching
    try:
        validate_url(url)
    except (SecurityError, ValueError) as e:
        logger.warning(f"[DISCUSSION] URL validation failed | {e} | url={url[:80]}")
        return ""

    logger.info(f"[DISCUSSION] starting | URL: {url[:80]}...")

    try:
        import aiohttp
        from bs4 import BeautifulSoup

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }

        # --- Try aiohttp first -------------------------------------------
        html = None
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as response:
                    if response.status == 200:
                        html = await response.text()
                        logger.info(f"[DISCUSSION] aiohttp OK | len:{len(html)}")
                    else:
                        logger.warning(f"[DISCUSSION] aiohttp status:{response.status}")
            except Exception as e:
                logger.warning(f"[DISCUSSION] aiohttp failed:{e}")

        # --- Selenium fallback if content is too short --------------------
        if not html or len(html) < 1000:
            logger.info("[DISCUSSION] aiohttp insufficient, trying Selenium...")
            try:
                html = await asyncio.to_thread(_fetch_discussion_via_selenium, url)
                if html:
                    logger.info(f"[DISCUSSION] Selenium OK | len:{len(html)}")
            except Exception as e:
                logger.error(f"[DISCUSSION] Selenium failed:{e}")

        if not html:
            logger.error("[DISCUSSION] all methods failed")
            return ""

        # --- Parse HTML ---------------------------------------------------
        soup = BeautifulSoup(html, "html.parser")

        all_content = ""

        # Extract main post -- try multiple selectors
        main_post = None
        title = ""
        link_url = ""

        # Method 1: standard tr.athing structure
        main_post = soup.select_one("tr.athing")
        if main_post:
            title_elem = (
                main_post.select_one("span.titleline > a")
                or main_post.select_one("a.titlelink")
                or main_post.select_one("td.title > a")
            )
            if title_elem:
                title = title_elem.get_text(strip=True)
                link_url = title_elem.get("href", "")
                if link_url and not link_url.startswith("http"):
                    if link_url.startswith("item?id="):
                        link_url = f"https://news.ycombinator.com/{link_url}"
                    elif link_url.startswith("/"):
                        link_url = f"https://news.ycombinator.com{link_url}"

        # Method 2: fallback selectors
        if not title:
            title_elem = soup.select_one("span.titleline > a, a.titlelink, td.title > a")
            if title_elem:
                title = title_elem.get_text(strip=True)
                link_url = title_elem.get("href", "")

        if title:
            all_content += f"标题: {title}\n\n"
            if link_url and link_url.startswith("http"):
                all_content += f"链接: {link_url}\n\n"

        # Main post body (if any)
        main_text = soup.select_one("div.toptext, tr.athing + tr td.default")
        if not main_text:
            main_text = soup.select_one("table.fatitem td.default")
        if main_text:
            text = main_text.get_text(strip=True)
            if text and len(text) > 10:
                all_content += f"正文: {text}\n\n"

        main_content_length = len(all_content)

        # --- Extract comments ---------------------------------------------
        comments: list[str] = []
        comment_count = 0
        total_comment_length = 0
        max_comment_length = 3000

        comment_elements = []

        # Try multiple selectors
        comment_elements = soup.select("tr.comtr")
        logger.info(f"使用 tr.comtr 选择器找到 {len(comment_elements)} 条评论")

        if not comment_elements:
            comment_elements = soup.select('tr[class*="comtr"]')
            logger.info(f"使用 tr[class*='comtr'] 选择器找到 {len(comment_elements)} 条评论")

        if not comment_elements:
            comment_elements = soup.select("div.comment")
            logger.info(f"使用 div.comment 选择器找到 {len(comment_elements)} 条评论")

        if not comment_elements:
            comment_elements = soup.select(".comment-tree .comment, .comment")
            logger.info(f"使用通用comment选择器找到 {len(comment_elements)} 条评论")

        total_comments_found = len(comment_elements)
        logger.info(f"总共找到 {total_comments_found} 条评论元素")

        max_comments_to_process = 30

        for i, comment_elem in enumerate(comment_elements):
            if i >= max_comments_to_process:
                break

            try:
                classes = comment_elem.get("class", [])
                if isinstance(classes, list) and "coll" in classes:
                    continue

                # HN tr.comtr structure
                if comment_elem.name == "tr" and ("comtr" in str(classes)):
                    comment_cell = comment_elem.select_one("td.default")
                    if not comment_cell:
                        continue

                    commenter = comment_cell.select_one("a.hnuser") or comment_cell.select_one('a[href*="user?id="]')
                    commenter_text = commenter.get_text(strip=True) if commenter else "匿名"

                    # Indentation level
                    indent_elem = comment_elem.select_one("td.ind")
                    indent_level = 0
                    if indent_elem:
                        img = indent_elem.select_one("img")
                        if img:
                            width = img.get("width") or img.get("style", "")
                            if width:
                                try:
                                    if isinstance(width, str) and "width" in width:
                                        match = re.search(r"width[:\s]+(\d+)", width)
                                        if match:
                                            indent_level = int(match.group(1)) // 40
                                    else:
                                        indent_level = int(str(width)) // 40
                                except Exception:
                                    indent_level = 0

                    if indent_level > 3:
                        continue

                    comment_text = (
                        comment_cell.select_one("div.commtext.c00")
                        or comment_cell.select_one("div.commtext")
                        or comment_cell.select_one("span.commtext")
                        or comment_cell
                    )

                    if comment_text:
                        comment_content = comment_text.get_text(strip=True)
                        if comment_content and len(comment_content) > 5:
                            if any(
                                skip in comment_content.lower() for skip in ["reply", "permalink", "parent", "root"]
                            ):
                                if len(comment_content) < 50:
                                    continue

                            indent_prefix = "  " * indent_level
                            formatted_comment = f"{indent_prefix}{commenter_text}: {comment_content}"
                            comment_length = len(formatted_comment)

                            if total_comment_length + comment_length > max_comment_length:
                                if comments:
                                    break
                                else:
                                    max_chars = max_comment_length - total_comment_length - 3
                                    formatted_comment = (
                                        f"{indent_prefix}{commenter_text}: {comment_content[:max_chars]}..."
                                    )
                                    comment_length = len(formatted_comment)

                            comments.append(formatted_comment)
                            total_comment_length += comment_length + 2
                            comment_count += 1

                # Generic comment structure (div.comment, etc.)
                else:
                    commenter = comment_elem.select_one('.commenter, .author, a.hnuser, a[href*="user?id="]')
                    commenter_text = commenter.get_text(strip=True) if commenter else "匿名"

                    comment_text = (
                        comment_elem.select_one(".comment-content, .commtext, .comment-text, span.commtext")
                        or comment_elem
                    )

                    if comment_text:
                        comment_content = comment_text.get_text(strip=True)
                        if comment_content and len(comment_content) > 5:
                            formatted_comment = f"{commenter_text}: {comment_content}"
                            comment_length = len(formatted_comment)

                            if total_comment_length + comment_length > max_comment_length:
                                if comments:
                                    break
                                else:
                                    max_chars = max_comment_length - total_comment_length - 3
                                    formatted_comment = f"{commenter_text}: {comment_content[:max_chars]}..."
                                    comment_length = len(formatted_comment)

                            comments.append(formatted_comment)
                            total_comment_length += comment_length + 2
                            comment_count += 1

            except Exception as e:
                logger.warning(f"[DISCUSSION] comment parse error | #{i} | err:{e}")
                continue

        if comments:
            all_content += f"评论 (共找到{total_comments_found}条，显示{comment_count}条):\n\n"
            all_content += "\n\n".join(comments)
            logger.info(
                f"[DISCUSSION] OK | total len:{len(all_content)} | "
                f"main:{main_content_length} | comments:{total_comment_length} | "
                f"count:{comment_count}/{total_comments_found}"
            )
        else:
            logger.warning(f"[DISCUSSION] no comments | HTML:{len(html)} | main:{main_content_length}")
            if os.environ.get("DEBUG_HTML"):
                debug_file = f"debug_discussion_{int(time.time())}.html"
                with open(debug_file, "w", encoding="utf-8") as f:
                    f.write(html)
                logger.info(f"[DEBUG] HTML saved: {debug_file}")

        return all_content

    except Exception as e:
        logger.error(f"[DISCUSSION] error: {e}")
        traceback.print_exc()
        return ""
