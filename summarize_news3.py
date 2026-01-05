import os
import sqlite3
import asyncio
from datetime import datetime
import json
import re
import colorama
from urllib.parse import urlparse, parse_qs, quote_plus
import logging
import time
import hashlib
import base64
import traceback
from typing import Tuple, List, Optional

from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# Crawl4AI imports
from crawl4ai import AsyncWebCrawler, LLMExtractionStrategy, ChunkingStrategy

import db_utils
from llm_business import generate_summary, generate_summary_from_image, translate_title
from proxy_config import ProxyConfig

# Disable SSL warnings
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Additional imports for fallback logic
import requests
from bs4 import BeautifulSoup

# PDF processing imports
import io
try:
    import PyPDF2
    PDF_LIBRARY = 'pypdf2'
except ImportError:
    PDF_LIBRARY = None

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
    MIN_ARTICLE_CONTENT_CHARS = int(config.get('MIN_ARTICLE_CONTENT_CHARS', 30))

colorama.init()

# Global settings
ENABLE_SCREENSHOT = os.environ.get('HN2MD_ENABLE_SCREENSHOT', '1') != '0'

# ----------------------------
# Helpers: non-blocking LLM
# ----------------------------
async def async_generate_summary(text: str, prompt_type: str, model: str = None) -> str:
    return await asyncio.to_thread(generate_summary, text, prompt_type, None, model)

async def async_translate_title(title: str, content_summary: str, model: str = None) -> str:
    return await asyncio.to_thread(translate_title, title, content_summary, None, model)

async def async_generate_summary_from_image(base64_image_data: str, prompt: str, llm_type: str) -> str:
    return await asyncio.to_thread(generate_summary_from_image, base64_image_data, prompt, llm_type)

# ----------------------------
# SQLite single-connection helper
# ----------------------------
class AsyncDB:
    def __init__(self, db_path: str):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.lock = asyncio.Lock()
        self._configure()

    def _configure(self) -> None:
        try:
            cur = self.conn.cursor()
            cur.execute('PRAGMA journal_mode=WAL;')
            cur.execute('PRAGMA synchronous=NORMAL;')
            cur.execute('PRAGMA busy_timeout=10000;')
            self.conn.commit()
        except Exception as e:
            print(f"配置SQLite失败: {e}")

    async def execute(self, sql: str, params: tuple = ()) -> None:
        async with self.lock:
            cur = self.conn.cursor()
            cur.execute(sql, params)
            self.conn.commit()

    async def fetchone(self, sql: str, params: tuple = ()): 
        async with self.lock:
            cur = self.conn.cursor()
            cur.execute(sql, params)
            return cur.fetchone()

    async def fetchall(self, sql: str, params: tuple = ()): 
        async with self.lock:
            cur = self.conn.cursor()
            cur.execute(sql, params)
            return cur.fetchall()

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass

# ----------------------------
# Crawl4AI Web Crawler
# ----------------------------
class NewsCrawler:
    def __init__(self):
        # 配置 Crawl4AI - 使用简化的配置
        self.crawler = AsyncWebCrawler()

    async def crawl_article(self, url: str) -> Tuple[str, List[str]]:
        """
        使用 Crawl4AI 抓取文章内容
        返回: (文章内容, 图片URL列表)
        """
        try:
            print(f"使用 Crawl4AI 抓取: {url}")
            
            # 使用简化的爬取方式
            result = await self.crawler.arun(url=url)
            
            if result.success:
                # 提取内容
                content = ""
                images = []
                
                # 从原始HTML中提取内容
                if hasattr(result, 'html'):
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(result.html, 'html.parser')
                    
                    # 提取图片
                    for img in soup.find_all('img'):
                        src = img.get('src') or img.get('data-src')
                        if src and src.startswith('http'):
                            images.append(src)
                    
                    # 智能提取主要内容
                    content = self._extract_main_content(soup)
                
                # 清理内容
                content = re.sub(r'\s{2,}', ' ', content)
                content = re.sub(r'(\n\s*){2,}', '\n\n', content)

                # 确保内容是可打印的文本，过滤掉二进制字符
                content = ''.join(char for char in content if char.isprintable() or char.isspace())

                print(f"Crawl4AI 抓取成功，内容长度: {len(content)}")
                return content.strip(), images[:5]  # 最多返回5张图片
            else:
                print(f"Crawl4AI 抓取失败: {result.error}")
                return "", []
                
        except Exception as e:
            print(f"Crawl4AI 抓取出错: {e}")
            return "", []

    def _extract_main_content(self, soup) -> str:
        """
        智能提取网页的主要内容
        """
        # 移除不需要的元素
        for tag in soup.find_all(['script', 'style', 'nav', 'footer', 'header', 'aside', 'menu']):
            tag.decompose()
        
        # 移除常见的导航和广告元素
        for selector in [
            '.nav', '.navigation', '.menu', '.sidebar', '.ad', '.advertisement',
            '.header', '.footer', '.breadcrumb', '.pagination', '.social-share',
            '[class*="nav"]', '[class*="menu"]', '[class*="sidebar"]', '[class*="ad"]',
            '[id*="nav"]', '[id*="menu"]', '[id*="sidebar"]', '[id*="ad"]'
        ]:
            for tag in soup.select(selector):
                tag.decompose()
        
        # 优先选择可能包含主要内容的元素
        content_selectors = [
            'article', 'main', '.content', '.post-content', '.article-content', 
            '.entry-content', '.post-body', '.article-body', '.story-content',
            '[role="main"]', '[role="article"]', '.main-content', '.primary-content'
        ]
        
        main_content = None
        for selector in content_selectors:
            main_content = soup.select_one(selector)
            if main_content:
                break
        
        # 如果没有找到主要内容区域，尝试其他策略
        if not main_content:
            # 查找包含最多文本的元素
            text_elements = soup.find_all(['p', 'div', 'section'])
            if text_elements:
                # 选择包含最多文本的元素
                main_content = max(text_elements, key=lambda x: len(x.get_text()))
        
        if main_content:
            # 清理主要内容区域
            for tag in main_content.find_all(['script', 'style', 'nav', 'footer', 'header', 'aside']):
                tag.decompose()
            return main_content.get_text(separator=' ', strip=True)
        
        # 如果还是没找到，返回body的文本
        body = soup.find('body')
        if body:
            return body.get_text(separator=' ', strip=True)
        
        return ""

# ----------------------------
# Special URL Handlers
# ----------------------------
def _is_x_url(url: str) -> bool:
    """检查是否为X/Twitter链接"""
    try:
        netloc = urlparse(url).netloc.lower()
        return any(domain in netloc for domain in ['x.com', 'twitter.com', 'mobile.twitter.com', 'm.twitter.com'])
    except Exception:
        return False

def _extract_tweet_id(url: str) -> str:
    """提取推文ID"""
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

def _fetch_x_via_vxtwitter(tweet_id: str) -> Tuple[str, List[str]]:
    """通过vxtwitter API获取推文内容"""
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
        
        # 去重
        seen = set()
        deduped = []
        for u in image_urls:
            if u not in seen:
                seen.add(u)
                deduped.append(u)
        
        return text, deduped
    except Exception as e:
        logging.warning(f"_fetch_x_via_vxtwitter failed for {tweet_id}: {e}")
        return '', []

def _fetch_x_via_selenium(url: str) -> Tuple[str, List[str]]:
    """使用Selenium获取X/Twitter内容"""
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
        
        # 去重
        seen = set()
        deduped = []
        for u in image_urls:
            if u not in seen:
                seen.add(u)
                deduped.append(u)
        
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

# ----------------------------
# PDF Handler
# ----------------------------
async def get_pdf_content(url: str) -> str:
    """从PDF URL提取文本内容"""
    if PDF_LIBRARY is None:
        print("未安装PyPDF2库，无法处理PDF文件")
        return ""

    try:
        # 下载PDF文件
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            'Accept': 'application/pdf,*/*'
        }

        # 尝试下载PDF，增加重试机制
        max_retries = 3
        for attempt in range(max_retries):
            try:
                loop = asyncio.get_event_loop()
                response = await loop.run_in_executor(
                    None,
                    lambda: requests.get(url, headers=headers, verify=False, timeout=30, stream=True)
                )

                if response.status_code == 200:
                    break

                print(f"下载PDF失败（尝试 {attempt + 1}/{max_retries}），状态码: {response.status_code}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2)  # 等待2秒后重试

            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                print(f"PDF下载连接错误（尝试 {attempt + 1}/{max_retries}）: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2)
                else:
                    raise
        else:
            print(f"所有重试均失败，状态码: {response.status_code}")
            return ""

        # 检查Content-Type
        content_type = response.headers.get('Content-Type', '').lower()
        if 'pdf' not in content_type:
            print(f"内容类型不是PDF: {content_type}")
            return ""

        # 使用PyPDF2提取文本
        pdf_file = io.BytesIO(response.content)
        pdf_reader = PyPDF2.PdfReader(pdf_file)

        # 提取所有页面的文本
        text_content = []
        total_pages = len(pdf_reader.pages)
        print(f"PDF共有 {total_pages} 页")

        for page_num in range(total_pages):
            page = pdf_reader.pages[page_num]
            text = page.extract_text()
            if text:
                text_content.append(text)

        # 合并所有页面的文本
        full_text = '\n\n'.join(text_content)

        # 清理文本
        full_text = re.sub(r'\s+', ' ', full_text).strip()
        full_text = ''.join(char for char in full_text if char.isprintable() or char.isspace())

        print(f"成功提取PDF文本，共 {len(full_text)} 字符")
        return full_text

    except Exception as e:
        print(f"提取PDF内容时出错: {e}")
        traceback.print_exc()
        return ""

# ----------------------------
# YouTube Handler
# ----------------------------
async def get_youtube_content(url: str, title: str) -> Tuple[str, List[str], List[str]]:
    """获取YouTube视频内容"""
    parsed_url = urlparse(url)
    video_id = None

    if parsed_url.netloc in ('www.youtube.com', 'youtube.com') and parsed_url.path == '/watch':
        query_params = parse_qs(parsed_url.query)
        if 'v' in query_params:
            video_id = query_params['v'][0]
    elif parsed_url.netloc == 'youtu.be':
        video_id = parsed_url.path.lstrip('/')

    if not video_id:
        return "", [], []

    print(f"检测到YouTube链接, 视频ID: {video_id}")
    
    try:
        from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled
        
        transcript_list = YouTubeTranscriptApi().list(video_id)
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

    # 获取缩略图
    thumbnail_url = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
    print(f"YouTube缩略图URL: {thumbnail_url}")

    thumbnail_path = save_article_image(thumbnail_url, url, f"{title}_1")
    image_paths = [thumbnail_path] if thumbnail_path else []

    return article_content, image_paths, image_paths

# ----------------------------
# Image Handler
# ----------------------------
def save_article_image(image_url: str, referer_url: str, title: Optional[str] = None) -> Optional[str]:
    """保存文章图片"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
        'Accept-Encoding': 'gzip, deflate, br',
        'Referer': referer_url
    }

    try:
        import requests
        from PIL import Image
        
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
                f.flush()  # 确保数据写入磁盘
                os.fsync(f.fileno())  # 强制刷新到磁盘

            # Windows文件锁释放需要时间，添加短暂延迟
            import time
            time.sleep(0.1)

            try:
                with Image.open(full_path) as img:
                    width, height = img.size
                    if width < 100 or height < 100:
                        os.remove(full_path)
                        return None

                    # 如果是 avif、webp 或 svg 格式，转换为 png
                    if ext in ['.avif', '.webp', '.svg']:
                        png_path = full_path.replace(ext, '.png')
                        img.save(png_path, 'PNG')
                        os.remove(full_path)  # 删除原始文件
                        print(f"已将 {ext} 图片转换为 png: {png_path}")
                        return os.path.abspath(png_path)

                    return os.path.abspath(full_path)
            except Exception as e:
                print(f"处理图片时出错: {e}")
                if os.path.exists(full_path):
                    os.remove(full_path)
                return None
        return None
    except Exception:
        return None

def get_extension_from_content_type(content_type: str) -> Optional[str]:
    """根据Content-Type获取文件扩展名"""
    content_type = content_type.lower()
    if 'jpeg' in content_type or 'jpg' in content_type:
        return '.jpg'
    elif 'png' in content_type:
        return '.png'
    elif 'gif' in content_type:
        return '.gif'
    elif 'webp' in content_type:
        return '.webp'
    elif 'avif' in content_type:
        return '.avif'
    elif 'svg' in content_type:
        return '.svg'
    return None

# ----------------------------
# Screenshot Handler
# ----------------------------
def save_page_screenshot(url: str, title: str) -> Optional[str]:
    """保存网页截图到本地

    Args:
        url: 网页URL
        title: 网页标题，用于生成文件名

    Returns:
        截图文件的绝对路径，失败返回None
    """
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
        print(f"Attempting to initialize WebDriver for {url}")
        driver = webdriver.Chrome(options=options)
        print(f"WebDriver initialized. Navigating to {url}")
        driver.get(url)
        print(f"Waiting 10 seconds for page load: {url}")
        time.sleep(10)
        driver.save_screenshot(image_save_path)
        print(f"Screenshot saved to {image_save_path}")
        saved_screenshot_path = os.path.abspath(image_save_path)
    except Exception as e:
        print(f"Error in save_page_screenshot for {url}: {e}")
        saved_screenshot_path = None
    finally:
        if driver:
            print(f"Quitting WebDriver for {url}")
            driver.quit()

    return saved_screenshot_path

def get_summary_from_screenshot(news_url: str, title: str, llm_type: str) -> Optional[str]:
    """通过截图获取摘要"""
    # 调用独立的截图保存方法
    saved_screenshot_path = save_page_screenshot(news_url, title)

    if not saved_screenshot_path:
        return None

    try:
        with open(saved_screenshot_path, "rb") as image_file:
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
        return None

    return saved_screenshot_path

# ----------------------------
# Fallback Content Extraction
# ----------------------------
async def fallback_content_extraction(url: str, title: str) -> Tuple[str, List[str], List[str]]:
    """回退方案：使用requests和BeautifulSoup进行内容提取"""
    print("使用回退方案：requests + BeautifulSoup 获取内容...")

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
        # 在异步上下文中运行同步请求
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: requests.get(url, headers=headers, verify=False, timeout=20)
        )

        print("\n回退方案调试信息:")
        print(f"状态码: {response.status_code}")
        print(f"原始编码: {response.encoding}")
        print(f"Apparent Encoding: {response.apparent_encoding}")
        print(f"Content-Type: {response.headers.get('Content-Type', 'unknown')}")

        response.raise_for_status()

        # 检查是否为HTML内容
        content_type = response.headers.get('Content-Type', '').lower()
        if 'text/html' not in content_type and 'text/plain' not in content_type and 'application/xhtml+xml' not in content_type:
            print(f"非文本内容类型: {content_type}，跳过")
            return "", [], []

        content = response.content

        # 确定最终编码
        final_encoding = response.encoding if response.encoding else response.apparent_encoding or 'utf-8'
        print(f"最终用于解析的编码: {final_encoding}")

        try:
            soup = BeautifulSoup(content, 'lxml', from_encoding=final_encoding)
        except Exception as e_lxml:
            print(f"使用lxml解析失败 (编码: {final_encoding}): {e_lxml}，尝试html.parser...")
            try:
                soup = BeautifulSoup(content, 'html.parser', from_encoding=final_encoding)
            except Exception as e_parser:
                print(f"使用html.parser解析也失败 (编码: {final_encoding}): {e_parser}")
                try:
                    raw_text = content.decode(final_encoding, errors='ignore')
                    print("解析HTML失败，尝试返回原始文本内容")
                    cleaned_text = re.sub(r'<script.*?</script>', '', raw_text, flags=re.DOTALL | re.IGNORECASE)
                    cleaned_text = re.sub(r'<style.*?</style>', '', cleaned_text, flags=re.DOTALL | re.IGNORECASE)
                    cleaned_text = re.sub(r'<.*?>', ' ', cleaned_text)
                    cleaned_text = re.sub(r'\s+', ' ', cleaned_text).strip()
                    if len(cleaned_text) < 50:
                        print("解析后文本内容过短，视作失败")
                        return "", [], []
                    return cleaned_text, [], []
                except Exception as decode_err:
                    print(f"解码原始文本也失败: {decode_err}")
                    return "", [], []

        print(f"页面标题: {soup.title.string.strip() if soup.title and soup.title.string else 'No title found'}")

        # 图片处理逻辑
        images = []
        seen_srcs = set()
        for img in soup.find_all('img'):
            src = img.get('src') or img.get('data-src')
            if src and src not in seen_srcs:
                if src.startswith('//'):
                    src = 'https:' + src
                elif src.startswith('/'):
                    parsed = urlparse(url)
                    src = f"{parsed.scheme}://{parsed.netloc}{src}"
                if src.startswith('http'):
                    images.append(src)
                    seen_srcs.add(src)

        # 保存图片，只保留本地路径
        image_paths = []
        for i, img_url in enumerate(images[:3], 1):
            saved = save_article_image(img_url, url, f"{title}_{i}")
            if saved:
                image_paths.append(saved)

        # 替换远端URL为本地路径
        images = image_paths

        # 提取文本内容
        for tag in soup(['script', 'style', 'nav', 'header', 'footer', 'aside']):
            tag.decompose()

        article_content = ""
        article = soup.find('article')
        if article:
            article_content = article.get_text(separator=' ', strip=True)
        else:
            main = soup.find('main') or soup.find('div', class_=re.compile(r'(content|article|post)', re.I))
            if main:
                article_content = main.get_text(separator=' ', strip=True)
            else:
                article_content = soup.get_text(separator=' ', strip=True)

        # 清理文本，确保是纯文本
        article_content = re.sub(r'\s+', ' ', article_content).strip()

        # 确保内容是可打印的文本，过滤掉二进制字符
        article_content = ''.join(char for char in article_content if char.isprintable() or char.isspace())
        article_content = article_content.strip()

        if len(article_content) < 50:
            print("回退方案提取的文本内容过短，视作失败")
            return "", [], []

        print(f"回退方案成功提取内容，长度: {len(article_content)} 字符")
        return article_content, image_paths, image_paths

    except Exception as e:
        print(f"回退方案失败: {e}")
        traceback.print_exc()
        return "", [], []

# ----------------------------
# Main Content Extraction
# ----------------------------
async def get_article_content_async(url: str, title: str) -> Tuple[str, List[str], List[str]]:
    """获取文章内容的主函数"""
    parsed_url = urlparse(url)

    # 检查是否为PDF链接
    if url.lower().endswith('.pdf'):
        print("检测到PDF链接，尝试提取文本...")
        pdf_content = await get_pdf_content(url)

        # 无论PDF文本提取是否成功，都尝试生成截图
        print("正在为PDF生成截图...")
        pdf_screenshot_path = await asyncio.to_thread(save_page_screenshot, url, title)

        if pdf_content:
            print(f"成功提取PDF内容，长度: {len(pdf_content)}")
            if pdf_screenshot_path:
                print(f"PDF截图已保存到: {pdf_screenshot_path}")
                return pdf_content, [], [pdf_screenshot_path]
            else:
                print("PDF截图生成失败，但已提取文本内容")
                return pdf_content, [], []
        else:
            print("PDF文本提取失败")
            if pdf_screenshot_path:
                print(f"虽然PDF文本提取失败，但截图已保存到: {pdf_screenshot_path}")
                # 返回空文本，但包含截图路径，后续可以用截图生成摘要
                return "", [], [pdf_screenshot_path]
            else:
                print("PDF文本提取和截图都失败")
                return "", [], []

    # 检查是否为YouTube链接
    if parsed_url.netloc in ('www.youtube.com', 'youtube.com', 'youtu.be'):
        return await get_youtube_content(url, title)
    
    # 检查是否为X/Twitter链接
    if _is_x_url(url):
        print("检测到X/Twitter链接，尝试获取内容...")
        tweet_id = _extract_tweet_id(url)
        
        # 尝试多种方式获取X/Twitter内容
        text, images = _fetch_x_via_vxtwitter(tweet_id)
        if not text:
            print("vxtwitter API失败，尝试Selenium...")
            text, images = _fetch_x_via_selenium(url)
        
        if text:
            print("成功提取X/Twitter内容")
            image_paths = []
            for i, img_url in enumerate(images[:3], 1):
                saved = save_article_image(img_url, url, f"{title}_{i}")
                if saved:
                    image_paths.append(saved)
            return text, image_paths, image_paths
    
    # 使用 Crawl4AI 获取普通网页内容
    print("使用 Crawl4AI 获取网页内容...")
    crawler = NewsCrawler()
    content, image_urls = await crawler.crawl_article(url)

    # 如果 Crawl4AI 没有获取到内容，使用回退方案
    if not content or len(content.strip()) < MIN_ARTICLE_CONTENT_CHARS:
        print(f"Crawl4AI 未获取到有效内容 (长度: {len(content) if content else 0})，启动回退方案...")
        fallback_content, fallback_image_urls, fallback_image_paths = await fallback_content_extraction(url, title)

        if fallback_content and len(fallback_content.strip()) >= MIN_ARTICLE_CONTENT_CHARS:
            print("回退方案成功获取内容")
            return fallback_content, fallback_image_urls, fallback_image_paths
        else:
            print("回退方案也未能获取到有效内容")

    # 保存图片（仅在 Crawl4AI 成功时），只保留本地路径
    image_paths = []
    for i, img_url in enumerate(image_urls[:3], 1):
        saved = save_article_image(img_url, url, f"{title}_{i}")
        if saved:
            image_paths.append(saved)

    return content, image_paths, image_paths

# ----------------------------
# Discussion Content
# ----------------------------
async def get_discussion_content_async(url: str) -> str:
    """获取讨论内容，包括主贴和限制字数的评论"""
    if not url:
        return ""
    
    try:
        print(f"开始获取讨论内容: {url}")
        
        import aiohttp
        from bs4 import BeautifulSoup
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        }
        
        # 首先尝试使用 aiohttp 获取
        html = None
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as response:
                    if response.status == 200:
                        html = await response.text()
                        print(f"成功获取HTML，长度: {len(html)}")
                    else:
                        print(f"HTTP状态码错误: {response.status}")
            except Exception as e:
                print(f"aiohttp请求失败: {e}")
        
        # 如果 aiohttp 失败，尝试使用 Selenium
        if not html or len(html) < 1000:
            print("aiohttp获取的内容可能不完整，尝试使用Selenium...")
            try:
                html = await asyncio.to_thread(_fetch_discussion_via_selenium, url)
                if html:
                    print(f"Selenium成功获取HTML，长度: {len(html)}")
            except Exception as e:
                print(f"Selenium获取失败: {e}")
                traceback.print_exc()
        
        if not html:
            print("无法获取页面HTML内容")
            return ""
        
        # 解析HTML
        soup = BeautifulSoup(html, 'html.parser')
        
        all_content = ""
        
        # 提取主贴内容 - 尝试多种选择器
        main_post = None
        title = ""
        link_url = ""
        
        # 方法1: 标准的 tr.athing 结构
        main_post = soup.select_one('tr.athing')
        if main_post:
            title_elem = main_post.select_one('span.titleline > a')
            if not title_elem:
                title_elem = main_post.select_one('a.titlelink')
            if not title_elem:
                title_elem = main_post.select_one('td.title > a')
            
            if title_elem:
                title = title_elem.get_text(strip=True)
                link_url = title_elem.get('href', '')
                # 处理相对链接
                if link_url and not link_url.startswith('http'):
                    if link_url.startswith('item?id='):
                        link_url = f"https://news.ycombinator.com/{link_url}"
                    elif link_url.startswith('/'):
                        link_url = f"https://news.ycombinator.com{link_url}"
        
        # 方法2: 如果没有找到，尝试其他结构
        if not title:
            title_elem = soup.select_one('span.titleline > a, a.titlelink, td.title > a')
            if title_elem:
                title = title_elem.get_text(strip=True)
                link_url = title_elem.get('href', '')
        
        if title:
            all_content += f"标题: {title}\n\n"
            if link_url and link_url.startswith('http'):
                all_content += f"链接: {link_url}\n\n"
        
        # 提取主贴文本（如果有）
        main_text = soup.select_one('div.toptext, tr.athing + tr td.default')
        if not main_text:
            # 尝试查找主贴的文本内容区域
            main_text = soup.select_one('table.fatitem td.default')
        
        if main_text:
            text = main_text.get_text(strip=True)
            if text and len(text) > 10:  # 过滤掉太短的内容
                all_content += f"正文: {text}\n\n"
        
        # 计算主贴内容长度
        main_content_length = len(all_content)
        
        # 提取评论
        comments = []
        comment_count = 0
        total_comment_length = 0
        max_comment_length = 5000
        
        # 尝试多种选择器来获取评论
        comment_elements = []
        
        # 方法1: Hacker News 标准的 tr.comtr 结构
        comment_elements = soup.select('tr.comtr')
        print(f"使用 tr.comtr 选择器找到 {len(comment_elements)} 条评论")
        
        # 方法2: 如果没有找到，尝试其他选择器
        if not comment_elements:
            comment_elements = soup.select('tr[class*="comtr"]')
            print(f"使用 tr[class*='comtr'] 选择器找到 {len(comment_elements)} 条评论")
        
        if not comment_elements:
            comment_elements = soup.select('div.comment')
            print(f"使用 div.comment 选择器找到 {len(comment_elements)} 条评论")
        
        if not comment_elements:
            comment_elements = soup.select('.comment-tree .comment, .comment')
            print(f"使用通用comment选择器找到 {len(comment_elements)} 条评论")
        
        # 记录找到的评论总数
        total_comments_found = len(comment_elements)
        print(f"总共找到 {total_comments_found} 条评论元素")
        
        # 限制处理的评论数量
        max_comments_to_process = 30
        
        for i, comment_elem in enumerate(comment_elements):
            if i >= max_comments_to_process:
                break
            
            try:
                # 检查是否是折叠的评论
                classes = comment_elem.get('class', [])
                if isinstance(classes, list) and 'coll' in classes:
                    continue
                
                # 针对Hacker News的tr.comtr结构
                if comment_elem.name == 'tr' and ('comtr' in str(classes)):
                    comment_cell = comment_elem.select_one('td.default')
                    if not comment_cell:
                        continue
                    
                    # 获取评论者
                    commenter = comment_cell.select_one('a.hnuser')
                    if not commenter:
                        commenter = comment_cell.select_one('a[href*="user?id="]')
                    commenter_text = commenter.get_text(strip=True) if commenter else "匿名"
                    
                    # 获取缩进级别（评论层级）
                    indent_elem = comment_elem.select_one('td.ind')
                    indent_level = 0
                    if indent_elem:
                        img = indent_elem.select_one('img')
                        if img:
                            width = img.get('width') or img.get('style', '')
                            if width:
                                try:
                                    if isinstance(width, str) and 'width' in width:
                                        # 从style中提取宽度
                                        import re
                                        match = re.search(r'width[:\s]+(\d+)', width)
                                        if match:
                                            indent_level = int(match.group(1)) // 40
                                    else:
                                        indent_level = int(str(width)) // 40
                                except:
                                    indent_level = 0
                    
                    # 允许更深层级的评论（放宽限制）
                    if indent_level > 3:
                        continue
                    
                    # 获取评论内容 - 尝试多种选择器
                    comment_text = comment_cell.select_one('div.commtext.c00')
                    if not comment_text:
                        comment_text = comment_cell.select_one('div.commtext')
                    if not comment_text:
                        comment_text = comment_cell.select_one('span.commtext')
                    if not comment_text:
                        # 尝试直接获取文本内容
                        comment_text = comment_cell
                    
                    if comment_text:
                        comment_content = comment_text.get_text(strip=True)
                        # 过滤掉太短或明显不是评论的内容
                        if comment_content and len(comment_content) > 5:
                            # 移除一些常见的非评论文本
                            if any(skip in comment_content.lower() for skip in ['reply', 'permalink', 'parent', 'root']):
                                if len(comment_content) < 50:
                                    continue
                            
                            # 计算当前评论的长度
                            indent_prefix = "  " * indent_level
                            formatted_comment = f"{indent_prefix}{commenter_text}: {comment_content}"
                            comment_length = len(formatted_comment)
                            
                            # 检查是否超出总长度限制
                            if total_comment_length + comment_length > max_comment_length:
                                if comments:
                                    break
                                else:
                                    max_chars = max_comment_length - total_comment_length - 3
                                    formatted_comment = f"{indent_prefix}{commenter_text}: {comment_content[:max_chars]}..."
                                    comment_length = len(formatted_comment)
                            
                            comments.append(formatted_comment)
                            total_comment_length += comment_length + 2
                            comment_count += 1
                
                # 针对其他评论结构（div.comment等）
                else:
                    commenter = comment_elem.select_one('.commenter, .author, a.hnuser, a[href*="user?id="]')
                    commenter_text = commenter.get_text(strip=True) if commenter else "匿名"
                    
                    comment_text = comment_elem.select_one('.comment-content, .commtext, .comment-text, span.commtext')
                    if not comment_text:
                        comment_text = comment_elem
                    
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
                print(f"处理第{i}条评论时出错: {e}")
                continue
        
        if comments:
            all_content += f"评论 (共找到{total_comments_found}条，显示{comment_count}条):\n\n"
            all_content += "\n\n".join(comments)
        else:
            print(f"警告: 未找到任何评论。HTML长度: {len(html)}, 主贴内容: {main_content_length}")
            # 保存HTML用于调试（仅在开发时）
            if os.environ.get('DEBUG_HTML'):
                debug_file = f"debug_discussion_{int(time.time())}.html"
                with open(debug_file, 'w', encoding='utf-8') as f:
                    f.write(html)
                print(f"调试HTML已保存到: {debug_file}")
        
        print(f"成功获取讨论内容，总长度: {len(all_content)}, 主贴长度: {main_content_length}, 评论长度: {total_comment_length}, 评论数: {comment_count}/{total_comments_found}")
        return all_content
        
    except Exception as e:
        print(f"Error fetching discussion content: {e}")
        traceback.print_exc()
        return ""


def _fetch_discussion_via_selenium(url: str) -> str:
    """使用Selenium获取讨论页面内容（同步函数，用于asyncio.to_thread）"""
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
        # 等待页面加载
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        # 额外等待一下，确保评论加载完成
        time.sleep(2)
        html = driver.page_source
        return html
    except Exception as e:
        print(f"Selenium获取失败: {e}")
        return ""
    finally:
        if driver:
            try:
                driver.quit()
            except:
                pass

# ----------------------------
# Main Processing Function
# ----------------------------
async def process_single_news(news_item, illegal_keywords, fetch_semaphore: asyncio.Semaphore, llm_semaphore: asyncio.Semaphore, db: AsyncDB):
    async with fetch_semaphore:
        news_id, title, news_url, discuss_url, article_content, discussion_content = news_item[:6]

        # 获取文章内容
        if (article_content is None or len(str(article_content).strip()) == 0) and news_url:
            print(f"\n处理文章: {title}")
            print(f"URL: {news_url}")
            article_content, image_urls, image_paths = await get_article_content_async(news_url, title)
            print(f"抓取文章正文完成，长度: {len(article_content or '')}")
            
            # 应用最小正文长度阈值：短于阈值视为“空”，不入库，触发兜底
            content_len = len((article_content or '').strip())
            print(f"抓取正文字数: {content_len}，阈值: {MIN_ARTICLE_CONTENT_CHARS}")
            if article_content and content_len >= MIN_ARTICLE_CONTENT_CHARS:
                await db.execute('UPDATE news SET article_content = ? WHERE id = ?', (article_content.strip(), news_id))
                # 写入后立即回读确认
                latest = await db.fetchone('SELECT article_content FROM news WHERE id = ?', (news_id,))
                if latest and latest[0]:
                    article_content = latest[0]
                print(f"DB回读 article_content 长度: {len(article_content or '')}")
                
                # 保存图片信息
                if image_urls:
                    await db.execute('UPDATE news SET largest_image = ? WHERE id = ?', (image_urls[0], news_id))
                    if len(image_urls) > 1:
                        await db.execute('UPDATE news SET image_2 = ? WHERE id = ?', (image_urls[1], news_id))
                    if len(image_urls) > 2:
                        await db.execute('UPDATE news SET image_3 = ? WHERE id = ?', (image_urls[2], news_id))
                    for i, path in enumerate(image_paths, 1):
                        print(f"第{i}张图片已保存到: {path}")
            else:
                # 过短内容直接视为“空”，后续触发截图兜底
                if content_len > 0:
                    print(f"正文长度低于阈值，丢弃文本并进入兜底流程: {content_len} < {MIN_ARTICLE_CONTENT_CHARS}")
                article_content = ''
            print("文章内容和图片已更新")

        # 获取讨论内容
        if not discussion_content and discuss_url:
            print(f"\n获取讨论内容: {title}")
            discussion_content = await get_discussion_content_async(discuss_url)
            await db.execute('UPDATE news SET discussion_content = ? WHERE id = ?', (discussion_content, news_id))
            print(f"讨论内容已更新: {title}")

        # 从数据库获取最新内容
        result = await db.fetchone('SELECT article_content, discussion_content FROM news WHERE id = ?', (news_id,))
        if result:
            db_article_content, db_discussion_content = result
            if db_article_content:
                article_content = db_article_content
            if db_discussion_content:
                discussion_content = db_discussion_content

        # 生成摘要
        content_summary = ""
        discuss_summary = ""

        if article_content and len(article_content.strip()) > 0:
            print(f"为文章生成摘要: {title}")
            async with llm_semaphore:
                content_summary = await async_generate_summary(article_content.strip(), 'article')
            print(f"文章摘要生成完成: {title}")
        else:
            print(f"文章内容为空，跳过摘要生成: {title}")

        # 截图兜底
        if not content_summary:
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

        # 检查是否需要补充截图（即使已有摘要，但没有保存任何图片）
        if ENABLE_SCREENSHOT and news_url:
            # 检查是否有保存的图片
            result = await db.fetchone('SELECT largest_image, image_2, image_3 FROM news WHERE id = ?', (news_id,))
            if result:
                largest_image, image_2, image_3 = result
                # 如果三个图片字段都为空，则进行截图
                if not largest_image and not image_2 and not image_3:
                    print(f"未保存任何图片，为 '{title}' 生成补充截图（仅用于存档，不生成摘要）")
                    try:
                        fallback_screenshot_path = await asyncio.to_thread(save_page_screenshot, news_url, title)
                        if fallback_screenshot_path:
                            print(f"补充截图已保存到: {fallback_screenshot_path}")
                            await db.execute('UPDATE news SET image_3= ? WHERE id = ?', (fallback_screenshot_path, news_id))
                        else:
                            print(f"补充截图生成失败: '{title}'")
                    except Exception as e:
                        print(f"补充截图过程出错: {e}")

        # 生成讨论摘要
        if discussion_content:
            print(f"为讨论生成摘要: {title}")
            async with llm_semaphore:
                discuss_summary = await async_generate_summary(discussion_content, 'discussion')
            print(f"讨论摘要生成完成: {title}")
        else:
            print(f"讨论内容为空，跳过摘要生成: {title}")

        # 翻译标题 - 使用负载均衡的模型
        result = await db.fetchone('SELECT title_chs FROM news WHERE id = ?', (news_id,))
        if result and not result[0] and content_summary:
            async with llm_semaphore:
                title_chs = await async_translate_title(title, content_summary)
            if title_chs:
                await db.execute('UPDATE news SET title_chs = ? WHERE id = ?', (title_chs, news_id))
                print(f"已翻译标题: {title_chs}")

        # 检查违法关键字
        content_illegal_keywords = db_utils.check_illegal_content(content_summary, illegal_keywords)
        discuss_illegal_keywords = db_utils.check_illegal_content(discuss_summary, illegal_keywords)
        if content_illegal_keywords:
            print(f"\n{colorama.Fore.YELLOW}警告: 文章摘要包含违法关键字:{colorama.Fore.RESET}")
            print(db_utils.highlight_keywords(content_summary, content_illegal_keywords))
        if discuss_illegal_keywords:
            print(f"\n{colorama.Fore.YELLOW}警告: 讨论摘要包含违法关键字:{colorama.Fore.RESET}")
            print(db_utils.highlight_keywords(discuss_summary, discuss_illegal_keywords))

        # 保存摘要
        if content_summary or discuss_summary:
            await db.execute(
                'UPDATE news SET content_summary = ?, discuss_summary = ? WHERE id = ?',
                (content_summary, discuss_summary, news_id)
            )
            print(f"摘要已更新: {title}")

        return f"完成处理: {title}"

# ----------------------------
# Main Function
# ----------------------------
async def process_news_parallel():
    """并行处理新闻的主函数"""
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

    # Gemini 的限流已在 llm_utils.py 中根据模型类型动态处理
    # Flash: 8次/分钟, Pro: 2次/分钟
    # 这里设置并发数为 5，让底层限流器控制实际速率
    if DEFAULT_LLM.lower() == 'gemini':
        max_llm_concurrency = 5
        print(f"检测到使用Gemini，LLM并发设置为 {max_llm_concurrency}，底层限流器将根据模型类型控制速率")

    fetch_semaphore = asyncio.Semaphore(max_fetch_concurrency)
    llm_semaphore = asyncio.Semaphore(max_llm_concurrency)

    tasks = [
        process_single_news(item, illegal_keywords, fetch_semaphore, llm_semaphore, db)
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

async def main_async():
    """主异步函数"""
    if DEFAULT_LLM.lower() == 'grok' and not GROK_API_KEY:
        print("错误: GROK_API_KEY配置变量未设置")
        return
    elif DEFAULT_LLM.lower() == 'gemini' and not GEMINI_API_KEY:
        print("错误: GEMINI_API_KEY配置变量未设置")
        return
    
    db_utils.init_database()
    await process_news_parallel()
    print("所有新闻项目处理完成。")

if __name__ == '__main__':
    asyncio.run(main_async())


