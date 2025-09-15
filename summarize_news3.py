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
async def async_generate_summary(text: str, prompt_type: str) -> str:
    return await asyncio.to_thread(generate_summary, text, prompt_type)

async def async_translate_title(title: str, content_summary: str) -> str:
    return await asyncio.to_thread(translate_title, title, content_summary)

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
    image_urls = [thumbnail_url] if thumbnail_path else []
    image_paths = [thumbnail_path] if thumbnail_path else []
    
    return article_content, image_urls, image_paths

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
    elif 'svg' in content_type:
        return '.svg'
    return None

# ----------------------------
# Screenshot Handler
# ----------------------------
def get_summary_from_screenshot(news_url: str, title: str, llm_type: str) -> Optional[str]:
    """通过截图获取摘要"""
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

# ----------------------------
# Main Content Extraction
# ----------------------------
async def get_article_content_async(url: str, title: str) -> Tuple[str, List[str], List[str]]:
    """获取文章内容的主函数"""
    parsed_url = urlparse(url)
    
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
            image_urls = []
            image_paths = []
            for i, img_url in enumerate(images[:3], 1):
                saved = save_article_image(img_url, url, f"{title}_{i}")
                if saved:
                    image_urls.append(img_url)
                    image_paths.append(saved)
            return text, image_urls, image_paths
    
    # 使用 Crawl4AI 获取普通网页内容
    print("使用 Crawl4AI 获取网页内容...")
    crawler = NewsCrawler()
    content, image_urls = await crawler.crawl_article(url)
    
    # 保存图片
    image_paths = []
    for i, img_url in enumerate(image_urls[:3], 1):
        saved = save_article_image(img_url, url, f"{title}_{i}")
        if saved:
            image_paths.append(saved)
    
    return content, image_urls[:3], image_paths

# ----------------------------
# Discussion Content
# ----------------------------
async def get_discussion_content_async(url: str) -> str:
    """获取讨论内容，包括主贴和限制字数的评论"""
    if not url:
        return ""
    
    try:
        print(f"开始获取讨论内容: {url}")
        
        # 直接使用BeautifulSoup解析Hacker News页面
        import aiohttp
        from bs4 import BeautifulSoup
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    html = await response.text()
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    all_content = ""
                    
                    # 提取主贴内容
                    main_post = soup.select_one('tr.athing')
                    if main_post:
                        title_elem = main_post.select_one('span.titleline > a')
                        if title_elem:
                            title = title_elem.get_text(strip=True)
                            all_content += f"标题: {title}\n\n"
                            
                            # 获取外部链接URL
                            link_url = title_elem.get('href', '')
                            if link_url and link_url.startswith('http'):
                                all_content += f"链接: {link_url}\n\n"
                    
                    # 提取主贴文本（如果有）
                    main_text = soup.select_one('div.toptext')
                    if main_text:
                        text = main_text.get_text(strip=True)
                        if text:
                            all_content += f"正文: {text}\n\n"
                    
                    # 计算主贴内容长度
                    main_content_length = len(all_content)
                    
                    # 提取评论，限制评论总字数在1000左右
                    comments = []
                    comment_count = 0
                    total_comment_length = 0
                    max_comment_length = 1000  # 评论部分最大字数限制
                    
                    for comment_row in soup.select('tr.comtr'):
                        # 跳过折叠的评论
                        if 'coll' in comment_row.get('class', []):
                            continue
                            
                        comment_cell = comment_row.select_one('td.default')
                        if not comment_cell:
                            continue
                        
                        # 获取评论者
                        commenter = comment_cell.select_one('a.hnuser')
                        commenter_text = commenter.get_text(strip=True) if commenter else "匿名"
                        
                        # 获取缩进级别（评论层级）
                        indent_elem = comment_row.select_one('td.ind')
                        indent_level = 0
                        if indent_elem:
                            img = indent_elem.select_one('img')
                            if img and img.get('width'):
                                try:
                                    indent_level = int(img.get('width', '0')) // 40
                                except:
                                    indent_level = 0
                        
                        # 只获取顶层评论（缩进级别为0）以减少评论数量
                        if indent_level > 1:  # 跳过嵌套层级较深的评论
                            continue
                        
                        # 获取评论内容
                        comment_text = comment_cell.select_one('div.commtext.c00')
                        if not comment_text:
                            comment_text = comment_cell.select_one('div.commtext')
                        
                        if comment_text:
                            comment_content = comment_text.get_text(strip=True)
                            if comment_content:  # 只添加非空评论
                                # 计算当前评论的长度
                                indent_prefix = "  " * indent_level  # 用空格表示层级
                                formatted_comment = f"{indent_prefix}{commenter_text}: {comment_content}"
                                comment_length = len(formatted_comment)
                                
                                # 检查是否超出总长度限制
                                if total_comment_length + comment_length > max_comment_length:
                                    # 如果已经有评论，就不再添加
                                    if comments:
                                        break
                                    # 如果还没有评论，则截断当前评论
                                    else:
                                        max_chars = max_comment_length - total_comment_length - 3  # 为省略号留出空间
                                        formatted_comment = f"{indent_prefix}{commenter_text}: {comment_content[:max_chars]}..."
                                        comment_length = len(formatted_comment)
                                
                                comments.append(formatted_comment)
                                total_comment_length += comment_length + 6  # 加上分隔符的长度 "\n\n---\n\n"
                                comment_count += 1
                                
                                # 如果已经达到字数限制，停止添加更多评论
                                if total_comment_length >= max_comment_length:
                                    break
                    
                    if comments:
                        all_content += f"评论 (共{comment_count}条):\n\n"
                        all_content += "\n\n---\n\n".join(comments)
                    
                    print(f"成功获取讨论内容，总长度: {len(all_content)}, 主贴长度: {main_content_length}, 评论长度: {total_comment_length}, 评论数: {comment_count}")
                    return all_content
        
        return ""
        
    except Exception as e:
        print(f"Error fetching discussion content: {e}")
        return ""

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

        # 生成讨论摘要
        if discussion_content:
            print(f"为讨论生成摘要: {title}")
            async with llm_semaphore:
                discuss_summary = await async_generate_summary(discussion_content, 'discussion')
            print(f"讨论摘要生成完成: {title}")
        else:
            print(f"讨论内容为空，跳过摘要生成: {title}")

        # 翻译标题
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


