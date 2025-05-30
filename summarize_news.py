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

def generate_summary_from_image(base64_image_data, prompt, llm_type):
    if llm_type.lower() == 'grok':
        print("Image summarization is not currently supported for Grok. Please configure Gemini as the default LLM for this feature.")
        return "" # Consistent "null" / empty handling

    # Assuming Gemini if not Grok
    # Access global config for Gemini settings
    # GEMINI_API_KEY is already global
    # GEMINI_API_URL is already global (for REST fallback)
    
    if not GEMINI_API_KEY:
        print("错误: GEMINI_API_KEY 未设置 (Error: GEMINI_API_KEY not set)")
        return "" 
    if not base64_image_data:
        print("错误: base64_image_data 为空 (Error: base64_image_data is empty)")
        return ""

    gemini_model_name = config.get('GEMINI_MODEL', 'gemini-1.5-flash-latest')
    
    # Attempt with google.generativeai library first
    try:
        from google import generativeai as genai

        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel(gemini_model_name)

        image_part = {
            "mime_type": "image/png", 
            "data": base64_image_data
        }
        
        print(f"Attempting image summarization with google-generativeai library, model: {gemini_model_name}")
        response = model.generate_content([prompt, image_part])

        if hasattr(response, 'text') and response.text:
            summary = response.text.strip()
            if summary.lower() == "null":
                print("Gemini API (google-generativeai) returned null for image.")
                return ""
            return summary
        elif hasattr(response, 'prompt_feedback') and response.prompt_feedback.block_reason:
            print(f"Gemini API (google-generativeai) blocked prompt: {response.prompt_feedback.block_reason}")
            return "" 
        else:
            # Check for parts if text is not directly available (though less common for simple image prompts)
            if hasattr(response, 'parts') and response.parts:
                 summary_parts = [part.text for part in response.parts if hasattr(part, 'text')]
                 if summary_parts:
                     summary = "".join(summary_parts).strip()
                     if summary.lower() == "null":
                         print("Gemini API (google-generativeai) returned null in parts for image.")
                         return ""
                     return summary
            print(f"Gemini API (google-generativeai) returned no usable text. Response: {response}")
            return ""

    except ImportError:
        print("google.generativeai library not found. Falling back to REST API for image summarization.")
    except Exception as e:
        print(f"Error with google.generativeai for image summarization: {e}")
        print("Falling back to REST API due to google-generativeai error.")

    # Fallback to REST API
    print(f"Attempting image summarization with REST API, model: {gemini_model_name}")
    headers = {
        'Content-Type': 'application/json'
    }
    params = {'key': GEMINI_API_KEY}
    
    payload = {
        "contents": [{
            "parts": [
                {"text": prompt},
                {
                    "inline_data": {
                        "mime_type": "image/png", 
                        "data": base64_image_data
                    }
                }
            ]
        }],
        "generationConfig": {
            "temperature": config.get('GEMINI_TEMPERATURE', 0.7),
            "maxOutputTokens": config.get('GEMINI_MAX_TOKENS_IMAGE', config.get('GEMINI_MAX_TOKENS', 250)) # Specific max tokens for image or general
        }
    }

    # Construct the API URL carefully
    base_gemini_api_url = config.get('GEMINI_API_URL_BASE', 'https://generativelanguage.googleapis.com/v1beta/models/')
    if base_gemini_api_url.endswith('/'): # Ensure it ends with a slash if it's just the base
         gemini_api_url_to_use = f"{base_gemini_api_url}{gemini_model_name}:generateContent"
    else: # If user provided full URL template or specific model URL
         # This logic might need adjustment if config.get('GEMINI_API_URL') is expected to be the full URL already
         # For now, assuming GEMINI_API_URL from config might be the full URL directly
         gemini_api_url_from_config = config.get('GEMINI_API_URL')
         if gemini_api_url_from_config and "generateContent" in gemini_api_url_from_config:
             gemini_api_url_to_use = gemini_api_url_from_config # Use it directly if it seems complete
         else: # Fallback to constructing from base and model name
             gemini_api_url_to_use = f"{base_gemini_api_url.rstrip('/')}/{gemini_model_name}:generateContent"


    try:
        print(f"Posting to Gemini REST API: {gemini_api_url_to_use}")
        response = requests.post(gemini_api_url_to_use, headers=headers, params=params, json=payload, timeout=30)
        response.raise_for_status()
        response_json = response.json()

        if 'candidates' in response_json and len(response_json['candidates']) > 0 and \
           'content' in response_json['candidates'][0] and \
           'parts' in response_json['candidates'][0]['content'] and \
           len(response_json['candidates'][0]['content']['parts']) > 0 and \
           'text' in response_json['candidates'][0]['content']['parts'][0]:
            summary = response_json['candidates'][0]['content']['parts'][0]['text'].strip()
            if summary.lower() == "null":
                print("Gemini REST API returned null for image.")
                return ""
            return summary
        elif 'promptFeedback' in response_json and \
             'blockReason' in response_json['promptFeedback']:
            print(f"Gemini REST API blocked prompt: {response_json['promptFeedback']['blockReason']}")
            return ""
        else:
            print(f"Gemini REST API error or unexpected response format: {response.text}")
            return ""
            
    except requests.exceptions.RequestException as e:
        print(f"Gemini REST API request failed: {e}")
        return ""
    except Exception as e:
        print(f"An unexpected error occurred with Gemini REST API for image: {e}")
        return ""
    
    return "" # Default return if all fails

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

        image_prompt = f"这是一个关于网页的截图。请用中文描述其内容，字数在200到250字之间。总结应专业、简洁，并符合中文新闻报道的习惯。如果图片内容无法辨认，或者无法理解，请只返回“null”。不要添加任何其他说明或开场白，直接给出总结。网页标题是：“{title}”。"
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

def create_or_update_table():
    """创建或更新数据库表结构"""
    conn = sqlite3.connect('hacknews.db')
    cursor = conn.cursor()
    
    # 检查是否需要添加新字段
    cursor.execute("PRAGMA table_info(news)")
    columns = [column[1] for column in cursor.fetchall()]
    
    # 添加原始内容字段
    if 'article_content' not in columns:
        cursor.execute('ALTER TABLE news ADD COLUMN article_content TEXT')
    if 'discussion_content' not in columns:
        cursor.execute('ALTER TABLE news ADD COLUMN discussion_content TEXT')
    if 'largest_image' not in columns:
        cursor.execute('ALTER TABLE news ADD COLUMN largest_image TEXT')
    # 添加新的图片字段
    if 'image_2' not in columns:
        cursor.execute('ALTER TABLE news ADD COLUMN image_2 TEXT')
    if 'image_3' not in columns:
        cursor.execute('ALTER TABLE news ADD COLUMN image_3 TEXT')
    
    # 创建违法关键字表
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS illegal_keywords (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        keyword TEXT UNIQUE,
        created_at TIMESTAMP
    )
    ''')
    
    conn.commit()
    conn.close()
    print("数据库表结构已更新")

def get_illegal_keywords():
    """获取所有违法关键字"""
    conn = sqlite3.connect('hacknews.db')
    cursor = conn.cursor()
    cursor.execute('SELECT keyword FROM illegal_keywords')
    keywords = [row[0] for row in cursor.fetchall()]
    conn.close()
    return keywords

def add_illegal_keyword(keyword):
    """添加违法关键字"""
    conn = sqlite3.connect('hacknews.db')
    cursor = conn.cursor()
    try:
        cursor.execute(
            'INSERT INTO illegal_keywords (keyword, created_at) VALUES (?, datetime("now", "localtime"))',
            (keyword,)
        )
        conn.commit()
        print(f"成功添加违法关键字: {keyword}")
    except sqlite3.IntegrityError:
        print(f"关键字 {keyword} 已存在")
    finally:
        conn.close()

def check_illegal_content(text, keywords):
    """检查文本是否包含违法关键字，返回包含的关键字列表"""
    if not text or not keywords:
        return []
    
    found_keywords = []
    for keyword in keywords:
        if keyword in text:
            found_keywords.append(keyword)
    
    return found_keywords

def highlight_keywords(text, keywords):
    """高亮显示文本中的关键字"""
    if not text or not keywords:
        return text
    
    highlighted_text = text
    for keyword in keywords:
        # 使用红色高亮显示关键字
        highlighted_text = highlighted_text.replace(
            keyword, 
            f"{colorama.Fore.RED}{keyword}{colorama.Fore.RESET}"
        )
    
    return highlighted_text

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

def generate_summary(text, prompt_type='article', llm_type=None):
    """
    生成摘要，支持不同的LLM模型
    
    Args:
        text: 需要总结的文本
        prompt_type: 'article'或'discussion'
        llm_type: 使用的LLM类型，None表示使用默认设置
    
    Returns:
        生成的摘要文本
    """
    if not text:
        return ""
    
    # 如果未指定LLM类型，使用默认设置
    if llm_type is None:
        llm_type = DEFAULT_LLM
    
    # 为文章和评论使用不同的提示语
    if prompt_type == 'article':
        prompt = f"将以下用三引号包裹的英文新闻用简洁准确的中文总结，200到250字。专业、简洁，符合中文新闻报道习惯。乐观、生动、对任何新鲜事都感兴趣。目标读者为一群爱好科技和 对有意思生活充满好奇的中文读者。请翻译并总结以下英文新闻的核心内容，突出背景、事件和影响，保留重要细节与数据，避免过多赘述，返回的内容只有正文，不需要包含markdown格式的标题：\n\"\"\"{text}\"\"\"\n如果你认为这个文章并没有正确读取，请只返回null，不要返回任何其他文字。"
        system_content = '你是一名专业的中文新闻编辑，擅长精准流畅地翻译和总结英文新闻。'
    else:  # 评论提示语
        prompt = f"下方用三引号包裹的英文讨论为hacknews论坛的内容，返回文字中以论坛代替\"hacknews论坛\"，将以下英文讨论用简洁准确的中文总结，200到250字。尽量多的介绍不同讨论者的言论，避免对单个评论过多赘述，返回的内容只有正文，不需要包含markdown格式的标题：\"\"\"\n{text}\n\"\"\"如果讨论内容不充分或无法理解，请返回null，不要返回任何其他文字。"
        system_content = '你是一个专业的讨论内容分析助手，擅长中文新闻编辑，擅长精准流畅地翻译和总结英文评论。'
    
    try:
        # 根据LLM类型选择不同的API调用方式
        if llm_type.lower() == 'grok':
            return generate_summary_grok(prompt, system_content)
        elif llm_type.lower() == 'gemini':
            return generate_summary_gemini(prompt, system_content)
        else:
            print(f"不支持的LLM类型: {llm_type}，使用默认的Grok")
            return generate_summary_grok(prompt, system_content)
    except Exception as e:
        print(f"生成摘要时出错: {e}")
        # 如果主要LLM失败，尝试使用备用LLM
        try:
            backup_llm = 'gemini' if llm_type.lower() == 'grok' else 'grok'
            print(f"尝试使用备用LLM: {backup_llm}")
            if backup_llm == 'grok':
                return generate_summary_grok(prompt, system_content)
            else:
                return generate_summary_gemini(prompt, system_content)
        except Exception as e2:
            print(f"备用LLM也失败了: {e2}")
            return ""

def generate_summary_grok(prompt, system_content):
    """使用Grok API生成摘要"""
    if not GROK_API_KEY:
        print("错误: GROK_API_KEY未设置")
        return ""
    
    headers = {
        'Authorization': f'Bearer {GROK_API_KEY}',
        'Content-Type': 'application/json'
    }
    
    data = {
        'messages': [
            {
                'role': 'system',
                'content': system_content
            },
            {
                'role': 'user',
                'content': prompt
            }
        ],
        'model': GROK_MODEL,
        'temperature': GROK_TEMPERATURE,
        'max_tokens': GROK_MAX_TOKENS,
        'stream': False
    }
    
    response = requests.post(GROK_API_URL, headers=headers, json=data, verify=True)
    response_json = response.json()
    
    if response.status_code == 200 and 'choices' in response_json:
        summary = response_json['choices'][0]['message']['content'].strip()
        
        # 检查是否返回了"null"
        if summary.lower() == "null":
            print("Grok API返回null，认为没有有效内容")
            return ""
        
        # 直接分割句子并返回除最后一句外的所有句子
        sentences = summary.split('。')
        if len(sentences) > 1:
            return '。'.join(sentences[:-1]) + '。'
        return summary
    else:
        print(f"Grok API错误: {response.text}")
        return ""

def generate_summary_gemini(prompt, system_content):
    """使用Gemini API生成摘要"""
    if not GEMINI_API_KEY:
        print("错误: GEMINI_API_KEY未设置")
        return ""
    
    gemini_model_name = config.get('GEMINI_MODEL', 'gemini-1.5-flash-latest')
    # Attempt with google.generativeai library first
    try:
        from google import generativeai as genai

        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel(gemini_model_name)
        
        full_prompt = f"{system_content}\n\n{prompt}"
        print(f"Attempting text summarization with google-generativeai library, model: {gemini_model_name}")
        response = model.generate_content(full_prompt)

        if hasattr(response, 'text') and response.text:
            summary = response.text.strip()
            if summary.lower() == "null":
                print("Gemini API (google-generativeai) returned null for text.")
                return ""
            # The sentence splitting logic is preserved for text summaries
            sentences = summary.split('。')
            if len(sentences) > 1:
                return '。'.join(sentences[:-1]) + '。'
            return summary
        elif hasattr(response, 'prompt_feedback') and response.prompt_feedback.block_reason:
            print(f"Gemini API (google-generativeai) blocked prompt for text: {response.prompt_feedback.block_reason}")
            return ""
        else:
            if hasattr(response, 'parts') and response.parts:
                 summary_parts = [part.text for part in response.parts if hasattr(part, 'text')]
                 if summary_parts:
                     summary = "".join(summary_parts).strip()
                     if summary.lower() == "null":
                         print("Gemini API (google-generativeai) returned null in parts for text.")
                         return ""
                     # Sentence splitting for parts as well
                     sentences = summary.split('。')
                     if len(sentences) > 1:
                         return '。'.join(sentences[:-1]) + '。'
                     return summary
            print(f"Gemini API (google-generativeai) returned no usable text. Response: {response}")
            return ""

    except ImportError:
        print("google.generativeai library not found. Falling back to REST API for text summarization.")
    except Exception as e:
        print(f"Error with google.generativeai for text summarization: {e}")
        print("Falling back to REST API due to google-generativeai error.")

    # Fallback to REST API for text summarization
    print(f"Attempting text summarization with REST API, model: {gemini_model_name}")
    headers = {'Content-Type': 'application/json'}
    params = {'key': GEMINI_API_KEY}
    
    payload = {
        "contents": [{"parts": [{"text": f"{system_content}\n\n{prompt}"}]}],
        "generationConfig": {
            "temperature": config.get('GEMINI_TEMPERATURE', 0.7),
            "maxOutputTokens": config.get('GEMINI_MAX_TOKENS', 200) 
        }
    }

    base_gemini_api_url = config.get('GEMINI_API_URL_BASE', 'https://generativelanguage.googleapis.com/v1beta/models/')
    if base_gemini_api_url.endswith('/'):
         gemini_api_url_to_use = f"{base_gemini_api_url}{gemini_model_name}:generateContent"
    else:
         gemini_api_url_from_config = config.get('GEMINI_API_URL') # This is the old single URL config
         if gemini_api_url_from_config and "generateContent" in gemini_api_url_from_config and gemini_model_name in gemini_api_url_from_config:
             # If the old GEMINI_API_URL contains the model name and :generateContent, use it
             gemini_api_url_to_use = gemini_api_url_from_config
         elif gemini_api_url_from_config and "generateContent" in gemini_api_url_from_config:
             # If it has generateContent but not model, try to insert model (less ideal)
             # This case might indicate a misconfiguration if GEMINI_API_URL_BASE is not used.
             # For safety, we'll replace the default model in a generic URL if possible, or stick to a full default.
             # Defaulting to gemini-1.5-flash-latest if GEMINI_MODEL is not in the URL.
             default_model_for_url = 'gemini-1.5-flash-latest' # A known good default
             url_parts = gemini_api_url_from_config.split('/')
             try:
                 model_idx = url_parts.index("models") + 1
                 url_parts[model_idx] = gemini_model_name
                 gemini_api_url_to_use = "/".join(url_parts)
             except ValueError: # "models" not in URL or structure is unexpected
                 gemini_api_url_to_use = f"https://generativelanguage.googleapis.com/v1beta/models/{gemini_model_name}:generateContent"

         else: # Fallback to constructing from base and model name, or full default
             gemini_api_url_to_use = f"{base_gemini_api_url.rstrip('/')}/{gemini_model_name}:generateContent"
    
    try:
        print(f"Posting to Gemini REST API for text: {gemini_api_url_to_use}")
        response = requests.post(gemini_api_url_to_use, headers=headers, params=params, json=payload, timeout=30)
        response.raise_for_status() 
        response_json = response.json()

        if 'candidates' in response_json and len(response_json['candidates']) > 0 and \
           'content' in response_json['candidates'][0] and \
           'parts' in response_json['candidates'][0]['content'] and \
           len(response_json['candidates'][0]['content']['parts']) > 0 and \
           'text' in response_json['candidates'][0]['content']['parts'][0]:
            summary = response_json['candidates'][0]['content']['parts'][0]['text'].strip()
            if summary.lower() == "null":
                print("Gemini REST API returned null for text.")
                return ""
            # Sentence splitting logic
            sentences = summary.split('。')
            if len(sentences) > 1:
                return '。'.join(sentences[:-1]) + '。'
            return summary
        elif 'promptFeedback' in response_json and \
             'blockReason' in response_json['promptFeedback']:
            print(f"Gemini REST API blocked prompt for text: {response_json['promptFeedback']['blockReason']}")
            return ""
        else:
            print(f"Gemini REST API error or unexpected response format for text: {response.text}")
            return ""
            
    except requests.exceptions.RequestException as e:
        print(f"Gemini REST API request failed for text: {e}")
        return ""
    except Exception as e:
        print(f"An unexpected error occurred with Gemini REST API for text: {e}")
        return ""

    return "" # Default return if all fails

# 修改翻译标题的部分，支持不同的LLM
def translate_title(title, content_summary, llm_type=None):
    """
    翻译标题，支持不同的LLM模型
    
    Args:
        title: 原始标题
        content_summary: 文章摘要，提供上下文
        llm_type: 使用的LLM类型，None表示使用默认设置
    
    Returns:
        翻译后的标题
    """
    if not title or not content_summary:
        return ""
    
    # 如果未指定LLM类型，使用默认设置
    if llm_type is None:
        llm_type = DEFAULT_LLM
    
    translation_prompt = f"请根据以下包含在三引号中的英文标题和文章摘要，请给出最有冲击力、最通顺的中文标题翻译,标题可以不直译,翻译的标题直接返回结果，无需添加任何额外内容，如果文章摘要为空，或者不符合，请直接返回空。英文标题：\"\"\"{title}\"\"\"文章摘要：\"\"\"{content_summary}\"\"\""
    system_content = '你是一个专业的新闻编辑，需要根据文章上下文提供有冲击力的标题翻译。'
    
    try:
        # 根据LLM类型选择不同的API调用方式
        if llm_type.lower() == 'grok':
            headers = {
                'Authorization': f'Bearer {GROK_API_KEY}',
                'Content-Type': 'application/json'
            }
            
            data = {
                'messages': [
                    {
                        'role': 'system',
                        'content': system_content
                    },
                    {
                        'role': 'user',
                        'content': translation_prompt
                    }
                ],
                'model': GROK_MODEL,
                'temperature': GROK_TEMPERATURE,
                'max_tokens': GROK_MAX_TOKENS,
                'stream': False
            }
            
            response = requests.post(GROK_API_URL, headers=headers, json=data, verify=True)
            response_json = response.json()
            
            if response.status_code == 200 and 'choices' in response_json:
                translated_title = response_json['choices'][0]['message']['content'].strip()
                # 检查是否返回了"null"
                if translated_title.lower() == "null":
                    print(f"Grok API翻译标题返回null，认为没有有效翻译: {title}")
                    return ""
                return translated_title
        elif llm_type.lower() == 'gemini':
            try:
                from google import generativeai as genai
                
                genai.configure(api_key=GEMINI_API_KEY)
                model = genai.GenerativeModel('gemini-2.0-flash')
                
                # 合并system_content和prompt
                full_prompt = f"{system_content}\n\n{translation_prompt}"
                
                response = model.generate_content(full_prompt)
                
                if hasattr(response, 'text'):
                    translated_title = response.text.strip()
                    # 检查是否返回了"null"
                    if translated_title.lower() == "null":
                        print(f"Gemini API翻译标题返回null，认为没有有效翻译: {title}")
                        return ""
                    return translated_title
            except ImportError:
                # 如果没有安装Google API库，使用REST API
                headers = {
                    'Content-Type': 'application/json'
                }
                
                params = {
                    'key': GEMINI_API_KEY
                }
                
                data = {
                    'contents': [
                        {
                            'parts': [
                                {
                                    'text': f"{system_content}\n\n{translation_prompt}"
                                }
                            ]
                        }
                    ],
                    'generationConfig': {
                        'temperature': 0.7,
                        'maxOutputTokens': 200
                    }
                }
                
                response = requests.post(
                    GEMINI_API_URL, 
                    headers=headers, 
                    params=params,
                    json=data
                )
                
                if response.status_code == 200:
                    response_json = response.json()
                    if 'candidates' in response_json and len(response_json['candidates']) > 0:
                        translated_title = response_json['candidates'][0]['content']['parts'][0]['text'].strip()
                        # 检查是否返回了"null"
                        if translated_title.lower() == "null":
                            print(f"Gemini REST API翻译标题返回null，认为没有有效翻译: {title}")
                            return ""
                        return translated_title
    except Exception as e:
        print(f"翻译标题时出错: {e}")
    
    return ""

# 修改process_news函数，使用新的翻译函数
def process_news():
    conn = sqlite3.connect('hacknews.db')
    cursor = conn.cursor()
    
    # 先确保表结构正确
    create_or_update_table()
    
    # 获取所有违法关键字
    illegal_keywords = get_illegal_keywords()
    
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
                cursor.execute('UPDATE news SET largest_image = ? WHERE id = ?', 
                               (screenshot_image_path, news_id))
                # The main loop already has conn.commit() at the end of each item processing block.
                print(f"Database will be updated with screenshot path for largest_image: {screenshot_image_path}")
                # content_summary remains empty if it was empty before this block, as per requirements.
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
        content_illegal_keywords = check_illegal_content(content_summary, illegal_keywords)
        discuss_illegal_keywords = check_illegal_content(discuss_summary, illegal_keywords)
        
        # 如果包含违法关键字，在控制台输出并高亮显示
        if content_illegal_keywords:
            print(f"\n{colorama.Fore.YELLOW}警告: 文章摘要包含违法关键字:{colorama.Fore.RESET}")
            print(highlight_keywords(content_summary, content_illegal_keywords))
        
        if discuss_illegal_keywords:
            print(f"\n{colorama.Fore.YELLOW}警告: 讨论摘要包含违法关键字:{colorama.Fore.RESET}")
            print(highlight_keywords(discuss_summary, discuss_illegal_keywords))
        
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
    create_or_update_table()
    process_news()
    print("所有新闻项目处理完成。")

if __name__ == '__main__':
    main()