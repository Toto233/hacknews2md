"""
Screenshot handler -- extracted from summarize_news5.py.

Captures a full-page screenshot via headless Selenium and optionally
generates an LLM summary from the screenshot image.
"""

import base64
import logging
import os
import re
import time
from datetime import datetime

from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions

from src.llm.llm_business import generate_summary_from_image
from src.security.url_validator import SecurityError, validate_url

logger = logging.getLogger(__name__)


def save_page_screenshot(url: str, title: str) -> str | None:
    """Save a page screenshot to disk (landscape, WeChat-friendly).

    Args:
        url:   Web page URL.
        title: Page title, used to generate the filename.

    Returns:
        Absolute path to the saved screenshot, or ``None`` on failure.
    """
    today = datetime.now()
    date_dir = os.path.join("output/images", f"{today.year:04d}{today.month:02d}{today.day:02d}")
    if not os.path.exists(date_dir):
        os.makedirs(date_dir)

    clean_title = re.sub(r'[<>:"/\\|?*]', "", title)
    clean_title = clean_title.replace(" ", "_")
    clean_title = re.sub(r"_{2,}", "_", clean_title)
    clean_title = clean_title[:50]
    ext = ".png"

    index = 1
    base_filename = clean_title
    while True:
        filename = f"{base_filename}{ext}" if index == 1 else f"{base_filename}_{index}{ext}"
        image_save_path = os.path.join(date_dir, filename)
        if not os.path.exists(image_save_path):
            break
        index += 1

    logger.info(f"[SCREENSHOT] preparing | '{title[:40]}...' | path:{image_save_path}")

    options = ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    driver = None
    saved_screenshot_path = None

    # SSRF protection: validate URL before passing to Selenium
    try:
        validate_url(url)
    except (SecurityError, ValueError) as e:
        logger.warning(f"[SCREENSHOT] URL validation failed | {e} | url={url[:80]}")
        return None

    try:
        logger.debug(f"[SCREENSHOT] init WebDriver | {url}")
        driver = webdriver.Chrome(options=options)
        logger.debug(f"[SCREENSHOT] navigating | {url}")
        driver.get(url)
        logger.debug("[SCREENSHOT] waiting 10s for page load")
        time.sleep(10)
        driver.save_screenshot(image_save_path)
        saved_screenshot_path = os.path.abspath(image_save_path)
        logger.info(f"[SCREENSHOT] OK | {saved_screenshot_path}")
    except Exception as e:
        logger.error(f"[SCREENSHOT] failed | err:{e}")
        saved_screenshot_path = None
    finally:
        if driver:
            logger.debug("[SCREENSHOT] closing WebDriver")
            driver.quit()

    return saved_screenshot_path


def get_summary_from_screenshot(
    news_url: str,
    title: str,
    llm_type: str,
) -> str | None:
    """Capture a screenshot and generate an LLM summary from it.

    Args:
        news_url: The web page URL.
        title:    Page title (used in the LLM prompt and filename).
        llm_type: LLM identifier passed to ``generate_summary_from_image``.

    Returns:
        Absolute path to the saved screenshot, or ``None`` on failure.
    """
    saved_screenshot_path = save_page_screenshot(news_url, title)

    if not saved_screenshot_path:
        return None

    try:
        with open(saved_screenshot_path, "rb") as image_file:
            base64_image_data = base64.b64encode(image_file.read()).decode("utf-8")
        if not base64_image_data:
            raise ValueError("Failed to load or encode screenshot.")

        image_prompt = (
            "这是一个关于网页的截图。请用中文描述其内容，字数在200到250字之间。"
            "总结应专业、简洁，并符合中文新闻报道的习惯。"
            '如果图片内容无法辨认，或者无法理解，请只返回"null"。'
            "不要添加任何其他说明或开场白，直接给出总结。"
            f'网页标题是："{title}"。'
        )
        _ = generate_summary_from_image(base64_image_data, image_prompt, llm_type)
    except Exception as e:
        logger.error(f"Error in get_summary_from_screenshot for {news_url}: {e}")
        return None

    return saved_screenshot_path
