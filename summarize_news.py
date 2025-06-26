import os
import sqlite3
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import json
import urllib3
import re
import colorama
from urllib.parse import urljoin, urlparse, parse_qs
import time
import brotli  # 添加brotli支持
from PIL import Image
import io
import mimetypes
import hashlib
import chardet
import gzip
import zlib
from io import BytesIO
from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled
import traceback

from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By # If using WebDriverWait
from selenium.webdriver.support.ui import WebDriverWait # If using WebDriverWait
from selenium.webdriver.support import expected_conditions as EC # If using WebDriverWait
import base64
# os and time are already imported

# 新增：导入db_utils
import db_utils

# 新增：导入llm_business
from llm_business import generate_summary, generate_summary_from_image, translate_title

# 禁用SSL证书验证警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 初始化LLM API配置
# 从配置文件加载API密钥和URL
with open('config.json', 'r', encoding='utf-8') as f:
    config = json.load(f)
    # GROK配置
    GROK_API_KEY = config.get('GROK_API_KEY')
    GROK_API_URL = config.get('GROK_API_URL', 'https://api.x.ai/v1/chat/completions')
    GROK_MODEL = config.get('GROK_MODEL', 'grok-3-beta')
    GROK_TEMPERATURE = config.get('GROK_TEMPERATURE', 0.7)
    GROK_MAX_TOKENS = config.get('GROK_MAX_TOKENS', 200)
    
    # GEMINI配置
    GEMINI_API_KEY = config.get('GEMINI_API_KEY')
    GEMINI_API_URL = config.get('GEMINI_API_URL', 'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent')
    
    # 默认LLM设置
    DEFAULT_LLM = config.get('DEFAULT_LLM', 'grok')  # 默认使用grok，可选值: grok, gemini

# 初始化colorama以支持控制台彩色输出
colorama.init()

# 删除重复的代码
# 禁用SSL证书验证警告
# urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 删除重复的配置加载
# with open('config.json', 'r', encoding='utf-8') as f:
#     config = json.load(f)
#     GROK_API_KEY = config.get('GROK_API_KEY')
#     GROK_API_URL = config.get('GROK_API_URL', 'https://api.x.ai/v1/chat/completions')

def get_summary_from_screenshot(news_url, title, llm_type):
    # Create date-specific directory for images
    today = datetime.now()
    date_dir = os.path.join('images', f"{today.year:04d}{today.month:02d}{today.day:02d}")
    if not os.path.exists(date_dir):
        os.makedirs(date_dir)

    # Clean title for filename
    clean_title = re.sub(r'[<>:"/\\|?*]', '', title)
    clean_title = clean_title.replace(' ', '_')
    clean_title = re.sub(r'_{2,}', '_', clean_title)
    clean_title = clean_title[:50]  # Limit title length
    ext = ".png"

    # Handle filename conflicts
    index = 1
    base_filename = clean_title
    while True:
        if index == 1:
            filename = f"{base_filename}{ext}"
        else:
            filename = f"{base_filename}_{index}{ext}"
        
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
    saved_screenshot_path = None  # Initialize path to None

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

        # The rest of the logic for image summarization can proceed
        # but the function's return regarding the path is now prioritized
        with open(image_save_path, "rb") as image_file:
            base64_image_data = base64.b64encode(image_file.read()).decode('utf-8')
        
        if not base64_image_data:
            raise ValueError("Failed to load or encode screenshot.")

        image_prompt = (
            '这是一个关于网页的截图。请用中文描述其内容，字数在200到250字之间。总结应专业、简洁，并符合中文新闻报道的习惯。'
            '如果图片内容无法辨认，或者无法理解，请只返回"null"。不要添加任何其他说明或开场白，直接给出总结。网页标题是："{}"。'.format(title)
        )
        # The summary generation itself is kept, but its result doesn't affect the path return value
        summary = generate_summary_from_image(base64_image_data, image_prompt, llm_type)
        print(f"summary (from screenshot): {summary}") # For logging

    except Exception as e:
        print(f"Error in get_summary_from_screenshot for {news_url}: {e}")
        # Ensure path is None if any error occurs before or during saving, or selenium error
        saved_screenshot_path = None 
    finally:
        if driver:
            print(f"Quitting WebDriver for {news_url}")
            driver.quit()
        # Deletion of the image is removed as per requirements

    # Return the absolute path if screenshot was saved, otherwise None
    return saved_screenshot_path

def handle_compressed_content(content, encoding):
    """处理压缩的内容
    
    Args:
        content: 压缩的内容
        encoding: 压缩类型 (gzip, deflate等)
        
    Returns:
        解压后的内容
    """
    try:
        if encoding == 'gzip':
            return gzip.decompress(content)
        elif encoding == 'deflate':
            import zlib
            return zlib.decompress(content)
        return content
    except Exception as e:
        print(f"解压内容失败: {str(e)}")
        return content

def get_article_content(url, title):
    """获取文章内容和图片(优先处理YouTube链接)

    Args:
        url: 文章URL
        title: 文章标题

    Returns:
        tuple: (内容文本, [图片URL列表], [图片保存路径列表])
    """
    parsed_url = urlparse(url)
    video_id = None
    is_youtube = False

    # 检查是否是YouTube链接并提取视频ID
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

        # 尝试获取文字稿
        try:
            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
            # 优先获取中文或英文文字稿
            transcript = transcript_list.find_generated_transcript(['zh-Hans', 'zh-Hant', 'en'])
            transcript_data = transcript.fetch()
            article_content = " ".join([item.text for item in transcript_data])
            print("成功获取YouTube文字稿")
        except (NoTranscriptFound, TranscriptsDisabled):
            print(f"视频 {video_id} 没有找到可用的文字稿或文字稿已禁用")
            article_content = f"无法获取视频 {title} 的文字稿。" # 提供一个回退内容
        except Exception as e:
            print(f"获取YouTube文字稿时出错: {str(e)}")
            article_content = f"获取视频 {title} 文字稿时出错。" # 提供一个回退内容

        # 获取并保存缩略图
        thumbnail_url = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
        print(f"YouTube缩略图URL: {thumbnail_url}")
        # 使用标题和序号1命名图片
        thumbnail_path = save_article_image(thumbnail_url, url, f"{title}_1")
        if thumbnail_path:
            print(f"YouTube缩略图已保存到: {thumbnail_path}")
            image_urls.append(thumbnail_url)
            image_paths.append(thumbnail_path)
        else:
            print("保存YouTube缩略图失败")

        return article_content, image_urls, image_paths

    # ----- 如果不是YouTube链接，执行原有逻辑 -----
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
        response = requests.get(url, headers=headers, verify=False, timeout=20) # 增加超时到20秒
        print("\n调试信息:")
        print(f"状态码: {response.status_code}")
        print(f"原始编码: {response.encoding}") # requests猜测的编码
        print(f"Apparent Encoding: {response.apparent_encoding}") # chardet检测的编码
        print(f"Content-Type: {response.headers.get('Content-Type', 'unknown')}")
        print(f"Content-Encoding: {response.headers.get('Content-Encoding', 'none')}")

        response.raise_for_status() # 如果状态码不是200-299，则抛出HTTPError

        # requests会自动解压gzip, deflate, br, 无需手动处理
        content = response.content

        # 确定最终编码用于BeautifulSoup解析
        # 优先使用响应头中的charset，其次是requests的apparent_encoding，最后是utf-8
        final_encoding = response.encoding if response.encoding else response.apparent_encoding or 'utf-8'
        print(f"最终用于解析的编码: {final_encoding}")

        try:
            # 使用 LXML 解析器通常更快更健壮，如果安装了的话
            # 需要 pip install lxml
            soup = BeautifulSoup(content, 'lxml', from_encoding=final_encoding)
        except Exception as e_lxml:
             print(f"使用lxml解析失败 (编码: {final_encoding}): {e_lxml}，尝试html.parser...")
             try:
                 soup = BeautifulSoup(content, 'html.parser', from_encoding=final_encoding)
             except Exception as e_parser:
                 print(f"使用html.parser解析也失败 (编码: {final_encoding}): {e_parser}")
                 # 如果有内容但无法解析，尝试直接返回文本内容
                 try:
                     raw_text = content.decode(final_encoding, errors='ignore')
                     print("解析HTML失败，尝试返回原始文本内容")
                     # 简单的清理
                     cleaned_text = re.sub(r'<script.*?</script>', '', raw_text, flags=re.DOTALL | re.IGNORECASE)
                     cleaned_text = re.sub(r'<style.*?</style>', '', cleaned_text, flags=re.DOTALL | re.IGNORECASE)
                     cleaned_text = re.sub(r'<.*?>', ' ', cleaned_text) # 移除所有HTML标签
                     cleaned_text = re.sub(r'\s+', ' ', cleaned_text).strip()
                     return cleaned_text, [], []
                 except Exception as decode_err:
                      print(f"解码原始文本也失败: {decode_err}")
                      return "", [], []
                 # 如果清理后的文本太短，也视作失败
                 if len(cleaned_text) < 50:
                     print("解析后文本内容过短，视作失败")
                     return "", [], []
                 return cleaned_text, [], []

        print(f"页面标题: {soup.title.string.strip() if soup.title and soup.title.string else 'No title found'}")

        # --- 图片处理逻辑 ---
        images = []
        seen_srcs = set()
        min_dimension = 50 # 最小像素尺寸阈值

        for img in soup.find_all('img'):
            src = img.get('src') or img.get('data-src') # 也尝试获取 data-src
            if not src:
                continue

            try:
                # 处理相对URL和 // 开头的URL
                parsed_src = urlparse(src)
                if not parsed_src.scheme and not parsed_src.netloc:
                     if src.startswith('//'):
                         src = urlparse(url).scheme + ':' + src
                     else:
                         src = urljoin(url, src)
                elif not parsed_src.scheme: # 例如 "example.com/image.jpg" -> "http://example.com/image.jpg"
                     src = urlparse(url).scheme + '://' + src

                # 再次检查处理后的URL是否有效
                if not urlparse(src).scheme in ('http', 'https'):
                     print(f"处理后得到无效的图片协议: {src}")
                     continue

            except ValueError as e:
                print(f"处理图片URL时出错 (urljoin/parse): {src}, 错误: {e}")
                continue

            # 跳过无效、SVG或Base64图片
            if not src or src.lower().endswith(('.svg', '.gif')) or src.startswith('data:image'): # 也跳过gif
                continue

            if src in seen_srcs:
                continue
            seen_srcs.add(src)

            width, height = 0, 0
            # 尝试从属性获取尺寸
            width_attr = img.get('width', '0').strip('px% ')
            height_attr = img.get('height', '0').strip('px% ')
            try:
                if width_attr.isdigit(): width = int(width_attr)
                if height_attr.isdigit(): height = int(height_attr)
            except ValueError: pass

            # 尝试从style获取尺寸
            style = img.get('style', '')
            if style:
                width_match = re.search(r'width:\s*(\d+)', style)
                height_match = re.search(r'height:\s*(\d+)', style)
                if width_match and width == 0:
                    try: width = int(width_match.group(1))
                    except ValueError: pass
                if height_match and height == 0:
                    try: height = int(height_match.group(1))
                    except ValueError: pass

            # 如果HTML/CSS尺寸有效且足够大，则直接使用
            if width >= min_dimension and height >= min_dimension:
                images.append({'url': src, 'size': width * height, 'width': width, 'height': height})
                # print(f"使用HTML/CSS尺寸添加图片: {src}, {width}x{height}")
                continue # 直接进入下一张图片

            # 如果尺寸不足或未知，尝试下载获取实际尺寸
            actual_width, actual_height = 0, 0
            img_response = None # 初始化确保finally中可用
            try:
                # print(f"尝试下载图片获取尺寸: {src}")
                img_headers = {**headers, 'Accept': 'image/*,*/*'} # 更明确的Accept头
                img_response = requests.get(src, headers=img_headers, verify=False, timeout=5, stream=True)
                if img_response.status_code == 200:
                    # 检查Content-Type是否为图片
                     content_type = img_response.headers.get('Content-Type', '').lower()
                     if not content_type.startswith('image/'):
                         print(f"下载的内容非图片类型 ({content_type}): {src}")
                         img_response.close() # 关闭流
                         continue

                    # 限制读取大小，避免下载大文件 (确保 BytesIO, Image 已导入)
                img_data_stream = BytesIO()
                read_bytes = 0
                max_read_bytes = 5 * 1024 * 1024 # 最多读取 5MB
                for chunk in img_response.iter_content(chunk_size=8192):
                    img_data_stream.write(chunk)
                    read_bytes += len(chunk)
                    if read_bytes > max_read_bytes:
                        print(f"图片文件过大 (>5MB)，停止下载: {src}")
                        break # 停止读取

                img_response.close() # 关闭流

                if read_bytes <= max_read_bytes: # 只有在文件大小合适时才处理
                    img_data_stream.seek(0) # 重置流指针
                    try:
                        with Image.open(img_data_stream) as img_obj:
                            actual_width, actual_height = img_obj.size
                            # print(f"实际图片尺寸: {actual_width}x{actual_height}")
                    except Exception as img_err:
                        print(f"无法用Pillow打开图片流: {src}, 错误: {img_err}")
                else:
                        print(f"下载图片失败 ({img_response.status_code}): {src}")
                        img_response.close() # 关闭流

            except Exception as e:
                print(f"处理图片尺寸时出错: {src}, 错误: {str(e)}")
            finally:
                 if img_response:
                     img_response.close() # 确保关闭流

            # 使用实际获取的尺寸（如果大于阈值）
            if actual_width >= min_dimension and actual_height >= min_dimension:
                width, height = actual_width, actual_height
            else:
                 # 如果尝试下载后尺寸仍不合格，跳过这张图
                 # print(f"图片尺寸不足 ({width}x{height} 或 {actual_width}x{actual_height})，跳过: {src}")
                 continue


            # 添加最终确定尺寸足够大的图片
            images.append({'url': src, 'size': width * height, 'width': width, 'height': height})
            # print(f"添加有效图片: {src}, 尺寸: {width}x{height}")


        # 按尺寸排序并选择最大的3张图片
        image_urls = []
        image_paths = []
        if images:
            images.sort(key=lambda x: x['size'], reverse=True)
            for i, img in enumerate(images[:3], 1):
                image_url = img['url']
                # print(f"\n处理第{i}大图片: {image_url}, 尺寸: {img['size']}")
                # 假设 save_article_image 函数存在
                image_path = save_article_image(image_url, url, f"{title}_{i}")
                if image_path:
                    # print(f"第{i}张图片已保存到: {image_path}")
                    image_urls.append(image_url)
                    image_paths.append(image_path)


        # --- 文章内容提取逻辑 ---
        # 移除常见的不需要内容块
        selectors_to_remove = [
            'script', 'style', 'nav', 'footer', 'header', 'aside', 'form', 'button', 'input',
            '.sidebar', '#sidebar', '.comments', '#comments', '.related-posts', '.author-bio',
            '.cookie-consent', '.modal', '[role="dialog"]', '[aria-hidden="true"]'
        ]
        for selector in selectors_to_remove:
            for tag in soup.select(selector):
                tag.decompose()

        article_content = ''
        # 优先查找语义化标签或常见内容容器
        potential_containers = [
            'article', 'main', 'div[role="main"]',
            '.entry-content', '.post-content', '.article-body', '.article-content',
            '.content', '#content', '#main-content', '#main', '.post', '.article'
         ]
        for selector in potential_containers:
            main_content = soup.select_one(selector)
            if main_content:
                # 获取文本，尝试保留段落间的换行
                paragraphs = main_content.find_all(['p', 'div', 'section']) # 查找可能的文本块
                if paragraphs:
                     text_blocks = [p.get_text(strip=True) for p in paragraphs]
                     # 过滤掉很短的文本块 (可能是按钮、标签等)
                     article_content = "\n\n".join(block for block in text_blocks if len(block.split()) > 5) # 至少包含5个单词
                else:
                     # 如果找不到段落，直接获取所有文本
                     article_content = main_content.get_text(separator=' ', strip=True)

                if len(article_content.split()) > 50: # 如果提取的内容比较丰富，就采用
                     print(f"使用选择器 '{selector}' 提取内容")
                     break # 找到一个合适的就停止
                else:
                     article_content = '' # 内容太少，可能不是主体，继续尝试


        # 如果语义化查找失败，作为最后手段，清理body文本
        if not article_content or len(article_content.split()) < 50:
            print("语义化提取失败或内容过少，尝试清理body内容...")
            body_tag = soup.find('body')
            if body_tag:
                # 获取文本，尝试保留段落间的换行
                paragraphs = body_tag.find_all(['p', 'div', 'section'])
                if paragraphs:
                     text_blocks = [p.get_text(strip=True) for p in paragraphs]
                     article_content = "\n\n".join(block for block in text_blocks if len(block.split()) > 5)
                else:
                     article_content = body_tag.get_text(separator=' ', strip=True)
            else:
                # 极端情况，连body都没有，直接用整个soup的文本
                print("未找到body标签，使用整个文档文本")
                article_content = soup.get_text(separator=' ', strip=True)


        # 最终清理
        article_content = re.sub(r'\s{2,}', ' ', article_content) # 多个空白变一个空格
        article_content = re.sub(r'(\n\s*){2,}', '\n\n', article_content) # 多个空行变一个

        return article_content.strip(), image_urls, image_paths

    except requests.exceptions.HTTPError as e: # 处理 HTTP 错误 (4xx, 5xx)
        print(f"请求失败 (HTTP Error): {url}, 状态码: {e.response.status_code}, 原因: {e.response.reason}")
        return "", [], []
    except requests.exceptions.Timeout as e:
        print(f"处理文章时请求超时: {url}, 错误: {str(e)}")
        return "", [], []
    except requests.exceptions.RequestException as e: # 处理其他网络请求错误
        print(f"处理文章时网络请求出错: {url}, 错误: {str(e)}")
        return "", [], []
    except Exception as e:
        print(f"处理文章时发生未知错误: {url}\n{traceback.format_exc()}")
        return "", [], []

def save_article_image(image_url, referer_url, title=None):
    """保存文章图片
    
    Args:
        image_url: 图片URL
        referer_url: 来源页面URL
        title: 文章标题，用于生成文件名
        
    Returns:
        str: 保存的图片路径，如果保存失败则返回None
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
        'Accept-Encoding': 'gzip, deflate, br',
        'Referer': referer_url
    }
    
    try:
        response = requests.get(image_url, headers=headers, verify=False, stream=True)
        if response.status_code == 200:
            # 检查Content-Type
            content_type = response.headers.get('Content-Type', '').lower()
            if not content_type.startswith('image/'):
                print(f"不是有效的图片类型: {content_type}")
                return None
            
            # 根据Content-Type获取扩展名
            ext = get_extension_from_content_type(content_type)
            if not ext:
                print(f"无法确定图片扩展名: {content_type}")
                return None
            
            # 创建日期目录 (yyyymmdd格式)
            today = datetime.now()
            date_dir = os.path.join('images', f"{today.year:04d}{today.month:02d}{today.day:02d}")
            if not os.path.exists(date_dir):
                os.makedirs(date_dir)
            
            # 生成文件名
            if title:
                # 清理标题，移除不合法的文件名字符，替换空格为下划线
                clean_title = re.sub(r'[<>:"/\\|?*]', '', title)
                clean_title = clean_title.replace(' ', '_')
                clean_title = re.sub(r'_{2,}', '_', clean_title)  # 将多个连续下划线替换为单个
                clean_title = clean_title[:50]  # 限制标题长度
                
                # 检查是否已存在同名文件
                index = 1
                while True:
                    if index == 1:
                        filename = f"{clean_title}{ext}"
                    else:
                        filename = f"{clean_title}_{index}{ext}"
                    
                    full_path = os.path.join(date_dir, filename)
                    if not os.path.exists(full_path):
                        break
                    index += 1
            else:
                # 如果没有标题，使用URL的MD5作为文件名
                filename = hashlib.md5(image_url.encode()).hexdigest() + ext
                full_path = os.path.join(date_dir, filename)
            
            # 保存图片
            with open(full_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            
            # 验证图片
            try:
                with Image.open(full_path) as img:
                    width, height = img.size
                    if width < 100 or height < 100:
                        print(f"图片太小: {width}x{height}")
                        os.remove(full_path)
                        return None
                    return full_path
            except Exception as e:
                print(f"验证图片时出错: {str(e)}")
                if os.path.exists(full_path):
                    os.remove(full_path)
                return None
                
        return None
    except Exception as e:
        print(f"下载图片时出错: {str(e)}")
        return None

def get_extension_from_content_type(content_type):
    """根据Content-Type获取文件扩展名
    
    Args:
        content_type: HTTP Content-Type
        
    Returns:
        str: 文件扩展名（包含点号）
    """
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

def get_discussion_content(url):
    if not url:
        return ""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 13_2_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/13.0.3 Mobile/15E148 Safari/604.1'
        }
        response = requests.get(url, timeout=10, headers=headers)
        soup = BeautifulSoup(response.text, 'html.parser')
        comments = soup.find_all('div', class_='comment')
        text = '\n'.join([comment.get_text(strip=True) for comment in comments[:10]])  # 只获取前10条评论
        return text[:3000]  # 限制文本长度
    except Exception as e:
        print(f"Error fetching discussion content: {e}")
        return ""

def process_news():
    conn = sqlite3.connect('hacknews.db')
    cursor = conn.cursor()
    
    # 先确保表结构正确
    db_utils.init_database()
    
    # 获取所有违法关键字
    illegal_keywords = db_utils.get_illegal_keywords()
    
    # 获取需要处理的新闻
    cursor.execute('''
    SELECT id, title, news_url, discuss_url, article_content, discussion_content, largest_image, image_2, image_3 
    FROM news 
    WHERE title_chs IS NULL OR title_chs = '' 
       OR article_content IS NULL 
       OR discussion_content IS NULL 
       OR content_summary IS NULL OR content_summary = '' 
       OR discuss_summary IS NULL OR discuss_summary = ''
    ''')
    news_items = cursor.fetchall()
    
    for item in news_items:
        news_id, title, news_url, discuss_url, article_content, discussion_content = item[:6]
        
        # 如果原始内容为空，则获取
        if not article_content and news_url:
            print(f"\n处理文章: {title}")
            print(f"URL: {news_url}")
            article_content, image_urls, image_paths = get_article_content(news_url, title)
            
            if article_content:
                cursor.execute('UPDATE news SET article_content = ? WHERE id = ?', 
                             (article_content, news_id))
                
                # 保存最多3张图片的URL
                if image_urls:
                    # 更新第一张图片（largest_image）
                    cursor.execute('UPDATE news SET largest_image = ? WHERE id = ?',
                                 (image_urls[0], news_id))
                    print(f"已保存第1张图片URL: {image_urls[0]}")
                    
                    # 更新第二张图片
                    if len(image_urls) > 1:
                        cursor.execute('UPDATE news SET image_2 = ? WHERE id = ?',
                                     (image_urls[1], news_id))
                        print(f"已保存第2张图片URL: {image_urls[1]}")
                    
                    # 更新第三张图片
                    if len(image_urls) > 2:
                        cursor.execute('UPDATE news SET image_3 = ? WHERE id = ?',
                                     (image_urls[2], news_id))
                        print(f"已保存第3张图片URL: {image_urls[2]}")
                    
                    # 打印保存的图片路径
                    for i, path in enumerate(image_paths, 1):
                        print(f"第{i}张图片已保存到: {path}")
            
            conn.commit()
            print(f"文章内容和图片已更新")
        
        if not discussion_content and discuss_url:
            print(f"\n获取讨论内容: {title}")
            discussion_content = get_discussion_content(discuss_url)
            cursor.execute('UPDATE news SET discussion_content = ? WHERE id = ?', 
                         (discussion_content, news_id))
            conn.commit()
        
        # 生成摘要，只处理非空内容
        content_summary = ""
        discuss_summary = ""
        
        if article_content:
            content_summary = generate_summary(article_content, 'article')
        
        if not content_summary: # If text summarization failed or article_content was empty
            print(f"Text summarization failed for '{title}' or article content was empty, attempting screenshot processing.")
            
            screenshot_image_path = get_summary_from_screenshot(news_url, title, DEFAULT_LLM) 
            
            if screenshot_image_path: # Check if a path was returned (i.e., screenshot saved)
                print(f"Screenshot successfully saved to: {screenshot_image_path}")
                # Update the database with the path to the screenshot for largest_image
                cursor.execute('UPDATE news SET image_3= ? WHERE id = ?', 
                               (screenshot_image_path, news_id))
                print(f"Database will be updated with screenshot path for largest_image: {screenshot_image_path}")
                
                # 新增：用截图生成摘要，并保存到 content_summary
                try:
                    with open(screenshot_image_path, "rb") as image_file:
                        base64_image_data = base64.b64encode(image_file.read()).decode('utf-8')
                    image_prompt = (
                        '这是一个关于网页的截图。请用中文描述其内容，字数在200到250字之间。总结应专业、简洁，并符合中文新闻报道的习惯。'
                        '如果图片内容无法辨认，或者无法理解，请只返回"null"。不要添加任何其他说明或开场白，直接给出总结。网页标题是："{}"。'.format(title)
                    )
                    # 调用图片摘要生成
                    content_summary = generate_summary_from_image(base64_image_data, image_prompt, DEFAULT_LLM)
                    print(f"图片摘要（content_summary）: {content_summary}")
                    # 保存图片摘要到数据库
                    if content_summary:
                        cursor.execute('UPDATE news SET content_summary = ? WHERE id = ?', (content_summary, news_id))
                        print(f"已将图片摘要保存到 content_summary 字段。")
                except Exception as e:
                    print(f"图片摘要生成或保存失败: {e}")
            else:
                print(f"Screenshot processing (capture or save) failed for '{title}'. No image path to save for largest_image.")

        if discussion_content:
            discuss_summary = generate_summary(discussion_content, 'discussion')
        
        # 检查并翻译标题，结合文章摘要提供上下文
        cursor.execute('SELECT title_chs FROM news WHERE id = ?', (news_id,))
        result = cursor.fetchone()
        if not result[0] and content_summary:
            title_chs = translate_title(title, content_summary)
            if title_chs:
                cursor.execute('UPDATE news SET title_chs = ? WHERE id = ?', 
                             (title_chs, news_id))
                print(f"已翻译标题: {title_chs}")
        
        # 检查摘要中是否包含违法关键字
        content_illegal_keywords = db_utils.check_illegal_content(content_summary, illegal_keywords)
        discuss_illegal_keywords = db_utils.check_illegal_content(discuss_summary, illegal_keywords)
        
        # 如果包含违法关键字，在控制台输出并高亮显示
        if content_illegal_keywords:
            print(f"\n{colorama.Fore.YELLOW}警告: 文章摘要包含违法关键字:{colorama.Fore.RESET}")
            print(db_utils.highlight_keywords(content_summary, content_illegal_keywords))
        
        if discuss_illegal_keywords:
            print(f"\n{colorama.Fore.YELLOW}警告: 讨论摘要包含违法关键字:{colorama.Fore.RESET}")
            print(db_utils.highlight_keywords(discuss_summary, discuss_illegal_keywords))
        
        # 更新摘要
        if content_summary or discuss_summary:
            cursor.execute('''
            UPDATE news 
            SET content_summary = ?, discuss_summary = ? 
            WHERE id = ?
            ''', (content_summary, discuss_summary, news_id))
            
            print(f"摘要已更新: {title}")
            
        conn.commit()
    
    conn.close()
    print("\n所有新闻处理完成")

def main():
    # 检查API密钥是否设置
    if DEFAULT_LLM.lower() == 'grok' and not GROK_API_KEY:
        print("错误: GROK_API_KEY配置变量未设置")
        return
    elif DEFAULT_LLM.lower() == 'gemini' and not GEMINI_API_KEY:
        print("错误: GEMINI_API_KEY配置变量未设置")
        return
    
    # 确保表结构正确
    db_utils.init_database()
    process_news()
    print("所有新闻项目处理完成。")

if __name__ == '__main__':
    main()