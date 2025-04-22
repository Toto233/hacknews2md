import os
import sqlite3
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import json
import urllib3
import re
import colorama
from urllib.parse import urljoin, urlparse
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
    """获取文章内容和最大的图片
    
    Args:
        url: 文章URL
        title: 文章标题
        
    Returns:
        tuple: (文章内容, 图片URL, 图片保存路径)
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Accept-Encoding': 'gzip, deflate',  # 移除 br
        'Connection': 'keep-alive',
        'Cache-Control': 'max-age=0',
        'Upgrade-Insecure-Requests': '1'
    }
    
    try:
        response = requests.get(url, headers=headers, verify=False)
        print("\n调试信息:")
        print(f"状态码: {response.status_code}")
        print(f"原始编码: {response.encoding}")
        print(f"Content-Type: {response.headers.get('Content-Type', 'unknown')}")
        print(f"Content-Encoding: {response.headers.get('Content-Encoding', 'none')}")
        
        if response.status_code == 200:
            # 使用原始内容创建BeautifulSoup对象
            soup = BeautifulSoup(response.content, 'html.parser')
            print(f"页面标题: {soup.title.string if soup.title else 'No title'}")
            
            # 查找最大的图片
            images = []
            for img in soup.find_all('img'):
                print(f"\n找到图片标签: {img}")
                src = img.get('src')
                if not src:
                    continue
                    
                # 处理相对URL
                if not src.startswith(('http://', 'https://')):
                    src = urljoin(url, src)
                print(f"处理后的图片URL: {src}")
                
                # 获取图片尺寸属性
                width = img.get('width', '0')
                height = img.get('height', '0')
                
                # 尝试从style属性获取尺寸
                style = img.get('style', '')
                if style:
                    width_match = re.search(r'width:\s*(\d+)px', style)
                    height_match = re.search(r'height:\s*(\d+)px', style)
                    if width_match and height_match:
                        width = width_match.group(1)
                        height = height_match.group(1)
                
                try:
                    width = int(width)
                    height = int(height)
                except ValueError:
                    width = height = 0
                
                print(f"HTML/CSS尺寸: {width}x{height}")
                
                # 如果没有尺寸信息，尝试下载图片获取实际尺寸
                if width * height == 0:
                    try:
                        print(f"尝试下载图片: {src}")
                        img_response = requests.get(src, headers=headers, verify=False, timeout=5)
                        if img_response.status_code == 200:
                            img_data = BytesIO(img_response.content)
                            with Image.open(img_data) as img_obj:
                                width, height = img_obj.size
                                print(f"实际图片尺寸: {width}x{height}")
                    except Exception as e:
                        print(f"获取图片尺寸失败: {str(e)}")
                        continue
                
                # 只添加有效尺寸的图片
                if width * height > 0:
                    images.append({
                        'url': src,
                        'size': width * height
                    })
                    print(f"添加图片: {src}, 尺寸: {width}x{height}")
            
            # 按尺寸排序并选择最大的图片
            if images:
                largest_image = max(images, key=lambda x: x['size'])
                image_url = largest_image['url']
                print(f"\n选择最大图片: {image_url}, 尺寸: {largest_image['size']}")
                
                # 保存图片
                image_path = save_article_image(image_url, url, title)
                if image_path:
                    print(f"图片已保存到: {image_path}")
            
            # 现在处理文章内容
            # 处理压缩内容
            content = response.content
            if 'Content-Encoding' in response.headers:
                content = handle_compressed_content(content, response.headers['Content-Encoding'])
            
            # 尝试检测编码
            if not response.encoding or response.encoding.lower() == 'utf-8':
                detected = chardet.detect(content)
                if detected and detected['encoding']:
                    response.encoding = detected['encoding']
                    print(f"检测到编码: {detected['encoding']}")
            
            # 重新解析内容以获取文本
            soup = BeautifulSoup(content, 'html.parser')
            
            # 移除不需要的元素
            for tag in soup.find_all(['script', 'style', 'nav', 'footer', 'header']):
                tag.decompose()
            
            # 获取文章内容
            article_content = ''
            article_tag = soup.find('article')
            if article_tag:
                article_content = article_tag.get_text(strip=True)
            else:
                # 尝试从其他常见容器中获取内容
                main_content = soup.find(['main', 'div[role="main"]', '.content', '#content'])
                if main_content:
                    article_content = main_content.get_text(strip=True)
            
            if images:
                return article_content, image_url, image_path
            return article_content, None, None
            
        else:
            print(f"请求失败: {response.status_code} {response.reason}")
            return None, None, None
            
    except Exception as e:
        print(f"处理文章时出错: {str(e)}")
        return None, None, None

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
    
    try:
        # 尝试使用Google官方API
        from google import generativeai as genai
        
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel('gemini-2.0-flash')
        
        # 合并system_content和prompt
        full_prompt = f"{system_content}\n\n{prompt}"
        
        response = model.generate_content(full_prompt)
        
        if hasattr(response, 'text'):
            summary = response.text.strip()
            
            # 检查是否返回了"null"
            if summary.lower() == "null":
                print("Gemini API返回null，认为没有有效内容")
                return ""
            
            # 直接分割句子并返回除最后一句外的所有句子
            sentences = summary.split('。')
            if len(sentences) > 1:
                return '。'.join(sentences[:-1]) + '。'
            return summary
        else:
            print("Gemini API返回格式错误")
            return ""
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
                            'text': f"{system_content}\n\n{prompt}"
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
                summary = response_json['candidates'][0]['content']['parts'][0]['text'].strip()
                
                # 检查是否返回了"null"
                if summary.lower() == "null":
                    print("Gemini REST API返回null，认为没有有效内容")
                    return ""
                
                # 直接分割句子并返回除最后一句外的所有句子
                sentences = summary.split('。')
                if len(sentences) > 1:
                    return '。'.join(sentences[:-1]) + '。'
                return summary
        
        print(f"Gemini API错误: {response.text}")
        return ""

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
    SELECT id, title, news_url, discuss_url, article_content, discussion_content, largest_image 
    FROM news 
    WHERE title_chs IS NULL OR title_chs = '' 
       OR article_content IS NULL 
       OR discussion_content IS NULL 
       OR content_summary IS NULL OR content_summary = '' 
       OR discuss_summary IS NULL OR discuss_summary = ''
    ''')
    news_items = cursor.fetchall()
    
    for item in news_items:
        news_id, title, news_url, discuss_url, article_content, discussion_content, largest_image = item
        
        # 如果原始内容为空，则获取
        if not article_content and news_url:
            print(f"\n处理文章: {title}")
            print(f"URL: {news_url}")
            article_content, image_url, image_path = get_article_content(news_url, title)
            
            if article_content:
                cursor.execute('UPDATE news SET article_content = ? WHERE id = ?', 
                             (article_content, news_id))
                
                if image_url:
                    cursor.execute('UPDATE news SET largest_image = ? WHERE id = ?',
                                 (image_url, news_id))
                    print(f"已保存图片URL: {image_url}")
                    if image_path:
                        print(f"图片已保存到: {image_path}")
            
            conn.commit()
            print(f"文章内容已更新")
        
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