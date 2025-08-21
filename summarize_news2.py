import os
import sqlite3
import aiohttp
import asyncio
from bs4 import BeautifulSoup
from datetime import datetime
import json
import urllib3
import re
import colorama
from urllib.parse import urljoin, urlparse, parse_qs, quote_plus
import logging
import time
import brotli
from PIL import Image
import hashlib
import chardet
import gzip
import zlib
from io import BytesIO
from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled
import traceback

from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import base64

import db_utils
from llm_business import generate_summary, generate_summary_from_image, translate_title
from proxy_config import ProxyConfig


# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# Load config
with open('config.json', 'r', encoding='utf-8') as f:
    config = json.load(f)
    GROK_API_KEY = config.get('GROK_API_KEY')
    GROK_API_URL = config.get('GROK_API_URL', 'https://api.x.ai/v1/chat/completions')
    GROK_MODEL = config.get('GROK_MODEL', 'grok-3-beta')
    GROK_TEMPERATURE = config.get('GROK_TEMPERATURE', 0.7)
    GROK_MAX_TOKENS = config.get('GROK_MAX_TOKENS', 200)
    GEMINI_API_KEY = config.get('GEMINI_API_KEY')
    GEMINI_API_URL = config.get('GEMINI_API_URL', 'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent')
    DEFAULT_LLM = config.get('DEFAULT_LLM', 'grok')


colorama.init()

# Proxy globals default
AIOHTTP_PROXY = None
REQUESTS_PROXIES = None
SOCKS_PROXY_ENABLED = False
ENABLE_SCREENSHOT = os.environ.get('HN2MD_ENABLE_SCREENSHOT', '1') != '0'


# ----------------------------
# Helpers: non-blocking LLM
# ----------------------------
async def async_generate_summary(text: str, prompt_type: str) -> str:
    return await asyncio.to_thread(generate_summary, text, prompt_type)


async def async_translate_title(title: str, content_summary: str) -> str:
    return await asyncio.to_thread(translate_title, title, content_summary)


async def async_generate_summary_from_image(base64_image_data: str, prompt: str, llm_type: str) -> str:
    return await asyncio.to_thread(generate_summary_from_image, base64_image_data, prompt, llm_type)


# ----------------------------
# Networking helpers (async)
# ----------------------------
async def fetch_with_retry(session, url, headers=None, max_retries=3):
    # Optional explicit proxy (http/https). For socks proxies we will use requests fallback below
    proxy_url = AIOHTTP_PROXY
    if headers is None:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Cache-Control': 'max-age=0',
            'Upgrade-Insecure-Requests': '1'
        }

    for attempt in range(max_retries):
        try:
            if proxy_url:
                async with session.get(url, headers=headers, ssl=False, proxy=proxy_url, timeout=aiohttp.ClientTimeout(total=20)) as response:
                    content = await response.read()
                    encoding = response.headers.get('Content-Encoding')
                    if encoding == 'gzip':
                        content = gzip.decompress(content)
                    elif encoding == 'deflate':
                        content = zlib.decompress(content)
                    elif encoding == 'br':
                        content = brotli.decompress(content)
                    return content, response.headers.get('Content-Type', ''), encoding or ''
            async with session.get(url, headers=headers, ssl=False, timeout=aiohttp.ClientTimeout(total=20)) as response:
                content = await response.read()
                encoding = response.headers.get('Content-Encoding')
                if encoding == 'gzip':
                    content = gzip.decompress(content)
                elif encoding == 'deflate':
                    content = zlib.decompress(content)
                elif encoding == 'br':
                    content = brotli.decompress(content)
                return content, response.headers.get('Content-Type', ''), encoding or ''
        except Exception as e:
            print(f"获取 {url} 失败 (尝试 {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)
            else:
                return None, '', ''


async def fetch_with_requests_fallback(url, headers=None, max_retries=3):
    # For socks proxies (requests supports them), run in thread
    if headers is None:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Cache-Control': 'max-age=0',
            'Upgrade-Insecure-Requests': '1'
        }
    def _do_request():
        import requests
        # Check socks support
        try:
            import socks  # noqa: F401
        except Exception:
            print("警告: 使用socks代理但未安装PySocks，请安装 'pip install requests[socks]' 或 'pip install PySocks'")
        for attempt in range(max_retries):
            try:
                resp = requests.get(url, headers=headers, verify=False, timeout=20, proxies=REQUESTS_PROXIES)
                if resp.status_code == 200:
                    return resp.content, resp.headers.get('Content-Type', ''), resp.headers.get('Content-Encoding', '')
            except Exception:
                if attempt == max_retries - 1:
                    return None, '', ''
        return None, '', ''
    return await asyncio.to_thread(_do_request)


# ----------------------------
# SQLite single-connection helper
# ----------------------------
class AsyncDB:
    def __init__(self, db_path: str):
        # check_same_thread=False allows using the same connection from different threads
        # We still guard all operations via asyncio.Lock to serialize DB access
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.lock = asyncio.Lock()
        self._configure()

    def _configure(self) -> None:
        try:
            cur = self.conn.cursor()
            cur.execute('PRAGMA journal_mode=WAL;')
            cur.execute('PRAGMA synchronous=NORMAL;')
            cur.execute('PRAGMA busy_timeout=10000;')  # 10s busy timeout
            self.conn.commit()
        except Exception as e:
            print(f"配置SQLite失败: {e}")

    async def execute(self, sql: str, params: tuple = ()) -> None:
        async with self.lock:
            cur = self.conn.cursor()
            cur.execute(sql, params)
            self.conn.commit()

    async def fetchone(self, sql: str, params: tuple = ()):  # -> tuple | None
        async with self.lock:
            cur = self.conn.cursor()
            cur.execute(sql, params)
            return cur.fetchone()

    async def fetchall(self, sql: str, params: tuple = ()):  # -> list[tuple]
        async with self.lock:
            cur = self.conn.cursor()
            cur.execute(sql, params)
            return cur.fetchall()

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass


def _is_x_url(url: str) -> bool:
    try:
        netloc = urlparse(url).netloc.lower()
        return any(domain in netloc for domain in ['x.com', 'twitter.com', 'mobile.twitter.com', 'm.twitter.com'])
    except Exception:
        return False


def _extract_tweet_id(url: str) -> str:
    try:
        parsed = urlparse(url)
        parts = [p for p in parsed.path.split('/') if p]
        if 'status' in parts:
            idx = parts.index('status')
            if idx + 1 < len(parts):
                candidate = parts[idx + 1]
                candidate = candidate.split('?')[0].split('#')[0]
                if candidate.isdigit():
                    return candidate
        return ''
    except Exception:
        return ''


def _fetch_x_via_cdn(tweet_id: str) -> tuple:
    if not tweet_id:
        return '', []
    api_url = f"https://cdn.syndication.twimg.com/widgets/tweet?id={tweet_id}"
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36',
            'Accept': 'application/json,text/html;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9,zh-CN;q=0.8'
        }
        import requests
        resp = requests.get(api_url, headers=headers, timeout=15)
        if resp.status_code != 200:
            return '', []
        data = resp.json()
        raw_text = data.get('text') or data.get('full_text') or ''
        text = ''
        if raw_text:
            try:
                text = BeautifulSoup(raw_text, 'html.parser').get_text(separator=' ', strip=True)
            except Exception:
                text = str(raw_text)
        image_urls = []
        photos = data.get('photos') or []
        for photo in photos:
            url = photo.get('url') or ''
            if url:
                image_urls.append(url)
        media = data.get('media') or []
        for m in media:
            m_url = m.get('url') or m.get('media_url_https') or m.get('media_url') or ''
            if m_url:
                image_urls.append(m_url)
        seen = set(); deduped = []
        for u in image_urls:
            if u not in seen:
                seen.add(u); deduped.append(u)
        return text, deduped
    except Exception as e:
        logging.warning(f"_fetch_x_via_cdn failed for {tweet_id}: {e}")
        return '', []


def _fetch_x_via_selenium(url: str) -> tuple:
    options = ChromeOptions()
    options.add_argument('--headless=new')
    options.add_argument('--disable-gpu')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--window-size=1400,1000')
    options.add_argument('--lang=en-US')
    options.add_experimental_option('excludeSwitches', ['enable-automation'])
    options.add_experimental_option('useAutomationExtension', False)
    options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36')

    driver = None
    try:
        driver = webdriver.Chrome(options=options)
        driver.get(url)
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'article [data-testid="tweetText"]'))
        )
        text_blocks = []
        for el in driver.find_elements(By.CSS_SELECTOR, 'article [data-testid="tweetText"]'):
            try:
                t = el.text.strip()
                if t:
                    text_blocks.append(t)
            except Exception:
                pass
        text = '\n\n'.join(text_blocks).strip()

        image_urls = []
        for img in driver.find_elements(By.CSS_SELECTOR, 'article [data-testid="tweetPhoto"] img, article img[src*="pbs.twimg.com/media"]'):
            try:
                src = img.get_attribute('src')
                if src and src.startswith('http'):
                    image_urls.append(src)
            except Exception:
                pass
        seen = set(); deduped = []
        for u in image_urls:
            if u not in seen:
                seen.add(u); deduped.append(u)
        return text, deduped[:5]
    except Exception as e:
        logging.warning(f"_fetch_x_via_selenium failed for {url}: {e}")
        return '', []
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


def _fetch_x_via_oembed(url: str) -> tuple:
    try:
        api = f"https://publish.twitter.com/oembed?omit_script=1&hide_thread=1&hide_media=0&url={quote_plus(url)}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36',
            'Accept': 'application/json',
        }
        import requests
        resp = requests.get(api, headers=headers, timeout=15)
        if resp.status_code != 200:
            return '', []
        data = resp.json()
        html = data.get('html') or ''
        if not html:
            return '', []
        soup = BeautifulSoup(html, 'html.parser')
        text = soup.get_text(separator=' ', strip=True)
        image_urls = []
        for img in soup.find_all('img'):
            src = img.get('src')
            if src and src.startswith('http'):
                image_urls.append(src)
        seen = set(); deduped = []
        for u in image_urls:
            if u not in seen:
                seen.add(u); deduped.append(u)
        return text, deduped
    except Exception as e:
        logging.warning(f"_fetch_x_via_oembed failed for {url}: {e}")
        return '', []


def _fetch_via_jina(url: str) -> tuple:
    try:
        parsed = urlparse(url)
        base = f"http://{parsed.netloc}{parsed.path}"
        proxy_url = f"https://r.jina.ai/{base}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36',
            'Accept': 'text/html, */*'
        }
        import requests
        resp = requests.get(proxy_url, headers=headers, timeout=20)
        if resp.status_code != 200:
            return '', []
        soup = BeautifulSoup(resp.text, 'html.parser')
        text = soup.get_text(separator=' ', strip=True)
        image_urls = []
        for img in soup.find_all('img'):
            src = img.get('src')
            if src and 'pbs.twimg.com' in src:
                image_urls.append(src)
        seen = set(); deduped = []
        for u in image_urls:
            if u not in seen:
                seen.add(u); deduped.append(u)
        return text, deduped[:5]
    except Exception as e:
        logging.warning(f"_fetch_via_jina failed for {url}: {e}")
        return '', []


def _fetch_via_nitter(tweet_id: str) -> tuple:
    if not tweet_id:
        return '', []
    mirrors = [
        'https://nitter.net',
        'https://nitter.pufe.org',
        'https://nitter.fdn.fr',
        'https://nitter.poast.org',
    ]
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9,zh-CN;q=0.8'
    }
    import requests
    for base in mirrors:
        try:
            url = f"{base}/i/status/{tweet_id}"
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, 'html.parser')
            text_el = soup.select_one('.main-tweet .tweet-content') or soup.select_one('.tweet-content')
            text = text_el.get_text(separator=' ', strip=True) if text_el else ''
            image_urls = []
            for img in soup.select('.attachments .attachment.image img, .main-tweet .attachments img'):
                src = img.get('src')
                if not src:
                    continue
                if src.startswith('//'):
                    src = 'https:' + src
                elif src.startswith('/'):
                    src = base + src
                image_urls.append(src)
            for a in soup.select('.attachments .attachment.image a.still-image, a.still-image, a.image'):
                href = a.get('href')
                if not href:
                    continue
                if href.startswith('//'):
                    href = 'https:' + href
                elif href.startswith('/'):
                    href = base + href
                image_urls.append(href)
            seen = set(); deduped = []
            for u in image_urls:
                if u not in seen:
                    seen.add(u); deduped.append(u)
            if text:
                return text, deduped
        except Exception as e:
            logging.warning(f"_fetch_via_nitter failed for {base} id={tweet_id}: {e}")
            continue
    return '', []


def _fetch_via_vxtwitter(tweet_id: str) -> tuple:
    if not tweet_id:
        return '', []
    api = f"https://api.vxtwitter.com/Twitter/status/{tweet_id}"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36',
        'Accept': 'application/json'
    }
    try:
        import requests
        resp = requests.get(api, headers=headers, timeout=15)
        if resp.status_code != 200:
            return '', []
        data = resp.json()
        text = data.get('text') or ''
        image_urls = []
        media_urls = data.get('mediaURLs') or []
        for u in media_urls:
            if isinstance(u, str) and u.startswith('http'):
                image_urls.append(u)
        media_ext = data.get('media_extended') or []
        for m in media_ext:
            u = (m.get('url') or m.get('source')) if isinstance(m, dict) else None
            if u and isinstance(u, str) and u.startswith('http'):
                image_urls.append(u)
        seen = set(); deduped = []
        for u in image_urls:
            if u not in seen:
                seen.add(u); deduped.append(u)
        return text, deduped
    except Exception as e:
        logging.warning(f"_fetch_via_vxtwitter failed for {tweet_id}: {e}")
        return '', []


def get_summary_from_screenshot(news_url, title, llm_type):
    today = datetime.now()
    date_dir = os.path.join('images', f"{today.year:04d}{today.month:02d}{today.day:02d}")
    if not os.path.exists(date_dir):
        os.makedirs(date_dir)

    clean_title = re.sub(r'[<>:"/\\|?*]', '', title)
    clean_title = clean_title.replace(' ', '_')
    clean_title = re.sub(r'_{2,}', '_', clean_title)
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

    print(f"Screenshot will be saved to: {image_save_path}")

    options = ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1200")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/98.0.4758.102 Safari/537.36")

    driver = None
    saved_screenshot_path = None

    try:
        print(f"Attempting to initialize WebDriver for {news_url}")
        driver = webdriver.Chrome(options=options)
        print(f"WebDriver initialized. Navigating to {news_url}")
        driver.get(news_url)
        print(f"Waiting 10 seconds for page load: {news_url}")
        time.sleep(10)
        driver.save_screenshot(image_save_path)
        print(f"Screenshot saved to {image_save_path}")
        saved_screenshot_path = os.path.abspath(image_save_path)

        with open(image_save_path, "rb") as image_file:
            base64_image_data = base64.b64encode(image_file.read()).decode('utf-8')
        if not base64_image_data:
            raise ValueError("Failed to load or encode screenshot.")

        image_prompt = (
            '这是一个关于网页的截图。请用中文描述其内容，字数在200到250字之间。总结应专业、简洁，并符合中文新闻报道的习惯。'
            '如果图片内容无法辨认，或者无法理解，请只返回"null"。不要添加任何其他说明或开场白，直接给出总结。网页标题是："{}"。'.format(title)
        )
        _ = generate_summary_from_image(base64_image_data, image_prompt, llm_type)
    except Exception as e:
        print(f"Error in get_summary_from_screenshot for {news_url}: {e}")
        saved_screenshot_path = None
    finally:
        if driver:
            print(f"Quitting WebDriver for {news_url}")
            driver.quit()

    return saved_screenshot_path


async def get_article_content_async(session, url, title):
    parsed_url = urlparse(url)
    video_id = None
    is_youtube = False

    if parsed_url.netloc in ('www.youtube.com', 'youtube.com') and parsed_url.path == '/watch':
        query_params = parse_qs(parsed_url.query)
        if 'v' in query_params:
            video_id = query_params['v'][0]
            is_youtube = True
    elif parsed_url.netloc == 'youtu.be':
        video_id = parsed_url.path.lstrip('/')
        is_youtube = True

    if is_youtube and video_id:
        print(f"检测到YouTube链接, 视频ID: {video_id}")
        article_content = ""
        image_urls = []
        image_paths = []
        try:
            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
            transcript = transcript_list.find_generated_transcript(['zh-Hans', 'zh-Hant', 'en'])
            transcript_data = transcript.fetch()
            article_content = " ".join([item.text for item in transcript_data])
            print("成功获取YouTube文字稿")
        except (NoTranscriptFound, TranscriptsDisabled):
            print(f"视频 {video_id} 没有找到可用的文字稿或文字稿已禁用")
            article_content = f"无法获取视频 {title} 的文字稿。"
        except Exception as e:
            print(f"获取YouTube文字稿时出错: {str(e)}")
            article_content = f"获取视频 {title} 文字稿时出错。"

        thumbnail_url = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
        print(f"YouTube缩略图URL: {thumbnail_url}")
        thumbnail_path = save_article_image(thumbnail_url, url, f"{title}_1")
        if thumbnail_path:
            print(f"YouTube缩略图已保存到: {thumbnail_path}")
            image_urls.append(thumbnail_url)
            image_paths.append(thumbnail_path)
        else:
            print("保存YouTube缩略图失败")
        return article_content, image_urls, image_paths

    if _is_x_url(url):
        print("检测到X/Twitter链接，尝试通过公开接口获取...")
        tweet_id = _extract_tweet_id(url)
        x_text, x_images = _fetch_x_via_cdn(tweet_id)
        if not x_text:
            print("CDN接口获取失败或无内容，尝试使用Selenium渲染...")
            x_text, x_images = _fetch_x_via_selenium(url)
        if not x_text:
            print("Selenium渲染失败或无内容，尝试oEmbed接口...")
            x_text, x_images = _fetch_x_via_oembed(url)
        if not x_text:
            print("oEmbed失败或无内容，尝试vxtwitter API...")
            x_text, x_images = _fetch_via_vxtwitter(tweet_id)
        if not x_text:
            print("vxtwitter失败或无内容，尝试Nitter镜像...")
            x_text, x_images = _fetch_via_nitter(tweet_id)
        if not x_text:
            print("Nitter也失败，尝试使用r.jina.ai代理获取...")
            x_text, x_images = _fetch_via_jina(url)
        if x_text:
            print("成功提取X/Twitter内容")
            if not x_images:
                _, vx_images = _fetch_via_vxtwitter(tweet_id)
                if vx_images:
                    x_images = vx_images
            if not x_images:
                j_text, j_images = _fetch_via_jina(url)
                if j_images:
                    x_images = j_images
            if not x_images:
                _, n_images = _fetch_via_nitter(tweet_id)
                if n_images:
                    x_images = n_images
            image_urls = []
            image_paths = []
            for i, img_url in enumerate(x_images[:3], 1):
                saved = save_article_image(img_url, url, f"{title}_{i}")
                if saved:
                    image_urls.append(img_url)
                    image_paths.append(saved)
            return x_text, image_urls, image_paths

    print("非YouTube链接，执行标准内容获取...")
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Accept-Encoding': 'gzip, deflate',
        'Connection': 'keep-alive',
        'Cache-Control': 'max-age=0',
        'Upgrade-Insecure-Requests': '1'
    }

    try:
        # Decide fetch path based on proxy type
        if SOCKS_PROXY_ENABLED:
            content, content_type, _ = await fetch_with_requests_fallback(url, headers)
        else:
            content, content_type, _ = await fetch_with_retry(session, url, headers)
        if content is None or len(content) < 256:
            print(f"aiohttp 抓取失败或内容过短({len(content or b'')})，尝试 requests 回退: {url}")
            content, content_type, _ = await fetch_with_requests_fallback(url, headers)
            if content is None:
                return "", [], []

        final_encoding = 'utf-8'
        if 'charset=' in content_type:
            final_encoding = content_type.split('charset=')[-1]
        else:
            detected = chardet.detect(content)
            if detected and detected['encoding']:
                final_encoding = detected['encoding']

        try:
            soup = BeautifulSoup(content, 'lxml', from_encoding=final_encoding)
        except Exception:
            soup = BeautifulSoup(content, 'html.parser', from_encoding=final_encoding)

        print(f"页面标题: {soup.title.string.strip() if soup.title and soup.title.string else 'No title found'}")

        images = []
        seen_srcs = set()
        min_dimension = 50

        for img in soup.find_all('img'):
            src = img.get('src') or img.get('data-src')
            if not src:
                continue
            try:
                parsed_src = urlparse(src)
                if not parsed_src.scheme and not parsed_src.netloc:
                    if src.startswith('//'):
                        src = urlparse(url).scheme + ':' + src
                    else:
                        src = urljoin(url, src)
                elif not parsed_src.scheme:
                    src = urlparse(url).scheme + '://' + src
                if not urlparse(src).scheme in ('http', 'https'):
                    continue
            except ValueError:
                continue

            if not src or src.lower().endswith(('.svg', '.gif')) or src.startswith('data:image'):
                continue
            if src in seen_srcs:
                continue
            seen_srcs.add(src)

            width, height = 0, 0
            width_attr = img.get('width', '0').strip('px% ')
            height_attr = img.get('height', '0').strip('px% ')
            try:
                if width_attr.isdigit():
                    width = int(width_attr)
                if height_attr.isdigit():
                    height = int(height_attr)
            except ValueError:
                pass

            style = img.get('style', '')
            if style:
                width_match = re.search(r'width:\s*(\d+)', style)
                height_match = re.search(r'height:\s*(\d+)', style)
                if width_match and width == 0:
                    try:
                        width = int(width_match.group(1))
                    except ValueError:
                        pass
                if height_match and height == 0:
                    try:
                        height = int(height_match.group(1))
                    except ValueError:
                        pass

            if width >= min_dimension and height >= min_dimension:
                images.append({'url': src, 'size': width * height, 'width': width, 'height': height})
                continue

            actual_width, actual_height = 0, 0
            try:
                img_headers = {**headers, 'Accept': 'image/*,*/*'}
                async with session.get(src, headers=img_headers, ssl=False, timeout=aiohttp.ClientTimeout(total=5)) as img_response:
                    if img_response.status == 200:
                        content_type_img = img_response.headers.get('Content-Type', '').lower()
                        if not content_type_img.startswith('image/'):
                            continue
                    img_data_stream = BytesIO()
                    read_bytes = 0
                    max_read_bytes = 5 * 1024 * 1024
                    async for chunk in img_response.content.iter_chunked(8192):
                        img_data_stream.write(chunk)
                        read_bytes += len(chunk)
                        if read_bytes > max_read_bytes:
                            break
                    if read_bytes <= max_read_bytes:
                        img_data_stream.seek(0)
                        try:
                            with Image.open(img_data_stream) as img_obj:
                                actual_width, actual_height = img_obj.size
                        except Exception:
                            pass
            except Exception:
                pass

            if actual_width >= min_dimension and actual_height >= min_dimension:
                width, height = actual_width, actual_height
            else:
                continue

            images.append({'url': src, 'size': width * height, 'width': width, 'height': height})

        image_urls = []
        image_paths = []
        if images:
            images.sort(key=lambda x: x['size'], reverse=True)
            for i, img in enumerate(images[:3], 1):
                image_url = img['url']
                image_path = save_article_image(image_url, url, f"{title}_{i}")
                if image_path:
                    image_urls.append(image_url)
                    image_paths.append(image_path)

        selectors_to_remove = [
            'script', 'style', 'nav', 'footer', 'header', 'aside', 'form', 'button', 'input',
            '.sidebar', '#sidebar', '.comments', '#comments', '.related-posts', '.author-bio',
            '.cookie-consent', '.modal', '[role="dialog"]', '[aria-hidden="true"]'
        ]
        for selector in selectors_to_remove:
            for tag in soup.select(selector):
                tag.decompose()

        article_content = ''
        potential_containers = [
            'article', 'main', 'div[role="main"]',
            '.entry-content', '.post-content', '.article-body', '.article-content',
            '.content', '#content', '#main-content', '#main', '.post', '.article'
        ]
        for selector in potential_containers:
            main_content = soup.select_one(selector)
            if main_content:
                paragraphs = main_content.find_all(['p', 'div', 'section'])
                if paragraphs:
                    text_blocks = [p.get_text(strip=True) for p in paragraphs]
                    article_content = "\n\n".join(block for block in text_blocks if len(block.split()) > 5)
                else:
                    article_content = main_content.get_text(separator=' ', strip=True)
                if len(article_content.split()) > 50:
                    break
                else:
                    article_content = ''

        if not article_content or len(article_content.split()) < 50:
            print("语义化提取失败或内容过少，尝试清理body内容...")
            body_tag = soup.find('body')
            if body_tag:
                paragraphs = body_tag.find_all(['p', 'div', 'section'])
                if paragraphs:
                    text_blocks = [p.get_text(strip=True) for p in paragraphs]
                    article_content = "\n\n".join(block for block in text_blocks if len(block.split()) > 5)
                else:
                    article_content = body_tag.get_text(separator=' ', strip=True)
            else:
                print("未找到body标签，使用整个文档文本")
                article_content = soup.get_text(separator=' ', strip=True)

        article_content = re.sub(r'\s{2,}', ' ', article_content)
        article_content = re.sub(r'(\n\s*){2,}', '\n\n', article_content)

        # 最后兜底：若正文仍为空，尝试 r.jina.ai 可读性代理
        cleaned = article_content.strip()
        if not cleaned or len(cleaned) < 100:
            try:
                parsed = urlparse(url)
                q = f"?{parsed.query}" if parsed.query else ""
                base = f"http://{parsed.netloc}{parsed.path}{q}"
                proxy_url = f"https://r.jina.ai/{base}"
                if SOCKS_PROXY_ENABLED:
                    r_content, r_ct, _ = await fetch_with_requests_fallback(proxy_url, headers)
                else:
                    r_content, r_ct, _ = await fetch_with_retry(session, proxy_url, headers)
                if r_content:
                    rsoup = BeautifulSoup(r_content, 'html.parser')
                    body_text = rsoup.get_text(separator=' ', strip=True)
                    if body_text and len(body_text) > len(cleaned):
                        cleaned = body_text
                        print("使用 r.jina.ai 代理作为正文兜底")
            except Exception as e:
                print(f"r.jina.ai 兜底失败: {e}")

        return cleaned, image_urls, image_paths
    except Exception:
        print(f"处理文章时发生未知错误: {url}\n{traceback.format_exc()}")
        return "", [], []


async def get_discussion_content_async(session, url):
    if not url:
        return ""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 13_2_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/13.0.3 Mobile/15E148 Safari/604.1'
        }
        if SOCKS_PROXY_ENABLED:
            content, _, _ = await fetch_with_requests_fallback(url, headers)
        else:
            content, _, _ = await fetch_with_retry(session, url, headers)
        if content is None or len(content) < 128:
            print(f"aiohttp 抓取讨论失败或过短({len(content or b'')})，尝试 requests 回退: {url}")
            content, _, _ = await fetch_with_requests_fallback(url, headers)
            if content is None:
                return ""
        soup = BeautifulSoup(content, 'html.parser')
        comments = soup.find_all('div', class_='comment')
        text = '\n'.join([comment.get_text(strip=True) for comment in comments[:10]])
        return text[:3000]
    except Exception as e:
        print(f"Error fetching discussion content: {e}")
        return ""


def save_article_image(image_url, referer_url, title=None):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
        'Accept-Encoding': 'gzip, deflate, br',
        'Referer': referer_url
    }

    try:
        import requests
        response = requests.get(image_url, headers=headers, verify=False, stream=True)
        if response.status_code == 200:
            content_type = response.headers.get('Content-Type', '').lower()
            if not content_type.startswith('image/'):
                return None
            ext = get_extension_from_content_type(content_type)
            if not ext:
                return None
            today = datetime.now()
            date_dir = os.path.join('images', f"{today.year:04d}{today.month:02d}{today.day:02d}")
            if not os.path.exists(date_dir):
                os.makedirs(date_dir)
            if title:
                clean_title = re.sub(r'[<>:"/\\|?*]', '', title)
                clean_title = clean_title.replace(' ', '_')
                clean_title = re.sub(r'_{2,}', '_', clean_title)
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
            with open(full_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            try:
                with Image.open(full_path) as img:
                    width, height = img.size
                    if width < 100 or height < 100:
                        os.remove(full_path)
                        return None
                    return full_path
            except Exception:
                if os.path.exists(full_path):
                    os.remove(full_path)
                return None
        return None
    except Exception:
        return None


def get_extension_from_content_type(content_type: str) -> str | None:
    content_type = content_type.lower()
    if 'jpeg' in content_type or 'jpg' in content_type:
        return '.jpg'
    elif 'png' in content_type:
        return '.png'
    elif 'gif' in content_type:
        return '.gif'
    elif 'webp' in content_type:
        return '.webp'
    elif 'svg' in content_type:
        return '.svg'
    return None


async def process_single_news(session, news_item, illegal_keywords, fetch_semaphore: asyncio.Semaphore, llm_semaphore: asyncio.Semaphore, db: 'AsyncDB'):
    async with fetch_semaphore:
        news_id, title, news_url, discuss_url, article_content, discussion_content = news_item[:6]

        if (article_content is None or len(str(article_content).strip()) == 0) and news_url:
            print(f"\n处理文章: {title}")
            print(f"URL: {news_url}")
            article_content, image_urls, image_paths = await get_article_content_async(session, news_url, title)
            print(f"抓取文章正文完成，长度: {len(article_content or '')}")
            if article_content and len(article_content.strip()) > 0:
                await db.execute('UPDATE news SET article_content = ? WHERE id = ?', (article_content.strip(), news_id))
                # 写入后立即回读确认
                latest = await db.fetchone('SELECT article_content FROM news WHERE id = ?', (news_id,))
                if latest and latest[0]:
                    article_content = latest[0]
                print(f"DB回读 article_content 长度: {len(article_content or '')}")
                if image_urls:
                    await db.execute('UPDATE news SET largest_image = ? WHERE id = ?', (image_urls[0], news_id))
                    if len(image_urls) > 1:
                        await db.execute('UPDATE news SET image_2 = ? WHERE id = ?', (image_urls[1], news_id))
                    if len(image_urls) > 2:
                        await db.execute('UPDATE news SET image_3 = ? WHERE id = ?', (image_urls[2], news_id))
                    for i, path in enumerate(image_paths, 1):
                        print(f"第{i}张图片已保存到: {path}")
            print("文章内容和图片已更新")

        if not discussion_content and discuss_url:
            print(f"\n获取讨论内容: {title}")
            discussion_content = await get_discussion_content_async(session, discuss_url)
            await db.execute('UPDATE news SET discussion_content = ? WHERE id = ?', (discussion_content, news_id))
            print(f"讨论内容已更新: {title}")

        result = await db.fetchone('SELECT article_content, discussion_content FROM news WHERE id = ?', (news_id,))
        if result:
            db_article_content, db_discussion_content = result
            if db_article_content:
                article_content = db_article_content
            if db_discussion_content:
                discussion_content = db_discussion_content

        content_summary = ""
        discuss_summary = ""

        if article_content and len(article_content.strip()) > 0:
            print(f"为文章生成摘要: {title}")
            async with llm_semaphore:
                content_summary = await async_generate_summary(article_content.strip(), 'article')
            print(f"文章摘要生成完成: {title}")
        else:
            print(f"文章内容为空，跳过摘要生成: {title}")

        if not content_summary:
            # 仅当数据库中的 article_content 仍为空时才进行截图兜底（与旧逻辑保持一致）
            if (not article_content or len(article_content.strip()) == 0) and ENABLE_SCREENSHOT:
                # 双重确认：再从数据库读取一次最新正文
                latest = await db.fetchone('SELECT article_content FROM news WHERE id = ?', (news_id,))
                if latest and latest[0]:
                    article_content = latest[0]
                print(f"二次校验 article_content 长度: {len(article_content or '')}")
            
            if (not article_content or len(article_content.strip()) == 0) and ENABLE_SCREENSHOT:
                print(f"Text summarization failed and article_content is empty/short for '{title}', attempting screenshot processing.")
                screenshot_image_path = await asyncio.to_thread(get_summary_from_screenshot, news_url, title, DEFAULT_LLM)
                if screenshot_image_path:
                    print(f"Screenshot successfully saved to: {screenshot_image_path}")
                    await db.execute('UPDATE news SET image_3= ? WHERE id = ?', (screenshot_image_path, news_id))
                    try:
                        with open(screenshot_image_path, "rb") as image_file:
                            base64_image_data = base64.b64encode(image_file.read()).decode('utf-8')
                        image_prompt = (
                            '这是一个关于网页的截图。请用中文描述其内容，字数在200到250字之间。总结应专业、简洁，并符合中文新闻报道的习惯。'
                            '如果图片内容无法辨认，或者无法理解，请只返回"null"。不要添加任何其他说明或开场白，直接给出总结。网页标题是："{}"。'.format(title)
                        )
                        async with llm_semaphore:
                            content_summary = await async_generate_summary_from_image(base64_image_data, image_prompt, DEFAULT_LLM)
                        if content_summary:
                            await db.execute('UPDATE news SET content_summary = ? WHERE id = ?', (content_summary, news_id))
                            print("已将图片摘要保存到 content_summary 字段。")
                    except Exception as e:
                        print(f"图片摘要生成或保存失败: {e}")
                else:
                    print(f"Screenshot processing failed for '{title}'.")
            else:
                print(f"文本摘要失败，但已存在 article_content，跳过截图兜底: {title}")

        if discussion_content:
            print(f"为讨论生成摘要: {title}")
            async with llm_semaphore:
                discuss_summary = await async_generate_summary(discussion_content, 'discussion')
            print(f"讨论摘要生成完成: {title}")
        else:
            print(f"讨论内容为空，跳过摘要生成: {title}")

        result = await db.fetchone('SELECT title_chs FROM news WHERE id = ?', (news_id,))
        if result and not result[0] and content_summary:
            async with llm_semaphore:
                title_chs = await async_translate_title(title, content_summary)
            if title_chs:
                await db.execute('UPDATE news SET title_chs = ? WHERE id = ?', (title_chs, news_id))
                print(f"已翻译标题: {title_chs}")

        content_illegal_keywords = db_utils.check_illegal_content(content_summary, illegal_keywords)
        discuss_illegal_keywords = db_utils.check_illegal_content(discuss_summary, illegal_keywords)
        if content_illegal_keywords:
            print(f"\n{colorama.Fore.YELLOW}警告: 文章摘要包含违法关键字:{colorama.Fore.RESET}")
            print(db_utils.highlight_keywords(content_summary, content_illegal_keywords))
        if discuss_illegal_keywords:
            print(f"\n{colorama.Fore.YELLOW}警告: 讨论摘要包含违法关键字:{colorama.Fore.RESET}")
            print(db_utils.highlight_keywords(discuss_summary, discuss_illegal_keywords))

        if content_summary or discuss_summary:
            await db.execute(
                'UPDATE news SET content_summary = ?, discuss_summary = ? WHERE id = ?',
                (content_summary, discuss_summary, news_id)
            )
            print(f"摘要已更新: {title}")

        return f"完成处理: {title}"


async def process_news_parallel():
    db_utils.init_database()
    illegal_keywords = db_utils.get_illegal_keywords()

    db = AsyncDB('hacknews.db')
    news_items = await db.fetchall('''
    SELECT id, title, news_url, discuss_url, article_content, discussion_content, largest_image, image_2, image_3 
    FROM news 
    WHERE title_chs IS NULL OR title_chs = '' 
       OR article_content IS NULL 
       OR discussion_content IS NULL 
       OR content_summary IS NULL OR content_summary = '' 
       OR discuss_summary IS NULL OR discuss_summary = ''
    ''')

    if not news_items:
        print("没有需要处理的新闻")
        return

    print(f"开始并行处理 {len(news_items)} 条新闻...")

    max_fetch_concurrency = int(os.environ.get('HN2MD_FETCH_CONCURRENCY', '5'))
    max_llm_concurrency = int(os.environ.get('HN2MD_LLM_CONCURRENCY', '3'))
    fetch_semaphore = asyncio.Semaphore(max_fetch_concurrency)
    llm_semaphore = asyncio.Semaphore(max_llm_concurrency)

    async with aiohttp.ClientSession(trust_env=True) as session:
        tasks = [
            process_single_news(session, item, illegal_keywords, fetch_semaphore, llm_semaphore, db)
            for item in news_items
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                print(f"处理新闻时发生错误: {result}")
            else:
                print(result)

    print("\n所有新闻处理完成")
    db.close()


def _init_proxy_env():
    # Prepare proxy settings for both aiohttp (http/https) and requests
    cfg = ProxyConfig()
    proxies = cfg.get_proxies()
    aiohttp_proxy = None
    socks_enabled = False
    if proxies:
        # Detect protocol
        proxy_url = proxies.get('http') or proxies.get('https')
        if proxy_url:
            if proxy_url.startswith('http://') or proxy_url.startswith('https://'):
                aiohttp_proxy = proxy_url
            # socks proxies handled by requests fallback
            if proxy_url.startswith('socks5://') or proxy_url.startswith('socks4://'):
                socks_enabled = True
    return aiohttp_proxy, proxies if proxies else None, socks_enabled


async def main_async():
    if DEFAULT_LLM.lower() == 'grok' and not GROK_API_KEY:
        print("错误: GROK_API_KEY配置变量未设置")
        return
    elif DEFAULT_LLM.lower() == 'gemini' and not GEMINI_API_KEY:
        print("错误: GEMINI_API_KEY配置变量未设置")
        return
    global AIOHTTP_PROXY, REQUESTS_PROXIES, SOCKS_PROXY_ENABLED
    AIOHTTP_PROXY, REQUESTS_PROXIES, SOCKS_PROXY_ENABLED = _init_proxy_env()
    db_utils.init_database()
    await process_news_parallel()
    print("所有新闻项目处理完成。")


if __name__ == '__main__':
    asyncio.run(main_async())


