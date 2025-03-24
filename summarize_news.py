import os
import sqlite3
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import json
import urllib3
import re
import colorama

# 禁用SSL证书验证警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 初始化Grok API配置
# 从配置文件加载API密钥和URL
with open('config.json', 'r', encoding='utf-8') as f:
    config = json.load(f)
    GROK_API_KEY = config.get('GROK_API_KEY')
    GROK_API_URL = config.get('GROK_API_URL', 'https://api.x.ai/v1/chat/completions')

# 初始化colorama以支持控制台彩色输出
colorama.init()

# 禁用SSL证书验证警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 初始化Grok API配置
# 从配置文件加载API密钥和URL
with open('config.json', 'r', encoding='utf-8') as f:
    config = json.load(f)
    GROK_API_KEY = config.get('GROK_API_KEY')
    GROK_API_URL = config.get('GROK_API_URL', 'https://api.x.ai/v1/chat/completions')

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

def get_article_content(url):
    try:
        response = requests.get(url, timeout=10, verify=False)  # 禁用SSL验证
        # 检查响应状态码，如果是错误状态码则直接返回空字符串
        if response.status_code in [403, 404] or response.status_code >= 500:
            print(f"Skipping due to HTTP error {response.status_code} for URL: {url}")
            return ""
        soup = BeautifulSoup(response.text, 'html.parser')
        # 移除脚本和样式元素
        for script in soup(["script", "style"]):
            script.decompose()
        # 获取正文内容
        text = soup.get_text(strip=True)
        # 简单处理文本，限制长度
        return text[:3000]  # 限制文本长度以控制API调用成本
    except Exception as e:
        print(f"Error fetching article content: {e}")
        return ""

def get_discussion_content(url):
    if not url:
        return ""
    try:
        response = requests.get(url, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        comments = soup.find_all('div', class_='comment')
        text = '\n'.join([comment.get_text(strip=True) for comment in comments[:10]])  # 只获取前10条评论
        return text[:3000]  # 限制文本长度
    except Exception as e:
        print(f"Error fetching discussion content: {e}")
        return ""

def generate_summary(text, prompt_type='article'):
    if not text:
        return ""
    try:
        headers = {
            'Authorization': f'Bearer {GROK_API_KEY}',
            'Content-Type': 'application/json'
        }
        
        # 为文章和评论使用不同的提示语
        if prompt_type == 'article':
            prompt = f"请用中文总结以下文章的主要内容（200-250字左右）：\n{text}\n如果你认为这个文章并没有正确读取，请返回空字符串。总结不能生硬的截断，如果字数不够一句话，就调整输出内容。"
        else:  # 评论提示语
            prompt = f"请用中文总结以下讨论中的讨论内容（200-250字左右）：\n{text}\n如果讨论内容不充分或无法理解，请返回空字符串。总结不能生硬的截断，如果字数不够一句话，就调整输出内容。"
        
        system_content = '你是一个专业的文章摘要助手，及一个优秀的科技文章编辑。' if prompt_type == 'article' else '你是一个专业的讨论内容分析助手，及一个优秀的科技文章编辑。'
        
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
            'model': 'grok-2-latest',
            'temperature': 0.7,
            'max_tokens': 200,
            'stream': False
        }
        
        response = requests.post(GROK_API_URL, headers=headers, json=data, verify=True)
        response_json = response.json()
        
        if response.status_code == 200 and 'choices' in response_json:
            summary = response_json['choices'][0]['message']['content'].strip()
            
            # 直接分割句子并返回除最后一句外的所有句子
            sentences = summary.split('。')
            if len(sentences) > 1:
                return '。'.join(sentences[:-1]) + '。'
            return summary
        else:
            print(f"Error from Grok API: {response.text}")
            return ""
    except Exception as e:
        print(f"Error generating summary: {e}")
        return ""

def process_news():
    conn = sqlite3.connect('hacknews.db')
    cursor = conn.cursor()
    
    # 先确保表结构正确
    create_or_update_table()
    
    # 获取所有违法关键字
    illegal_keywords = get_illegal_keywords()
    
    # 获取需要处理的新闻
    cursor.execute('''
    SELECT id, title, news_url, discuss_url, article_content, discussion_content 
    FROM news 
    WHERE title_chs IS NULL OR title_chs = '' 
       OR article_content IS NULL 
       OR discussion_content IS NULL 
       OR content_summary IS NULL OR content_summary = '' 
       OR discuss_summary IS NULL OR discuss_summary = ''
    ''')
    news_items = cursor.fetchall()
    
    for item in news_items:
        news_id, title, news_url, discuss_url, article_content, discussion_content = item
        
        # 如果原始内容为空，则获取
        if not article_content and news_url:
            article_content = get_article_content(news_url)
            cursor.execute('UPDATE news SET article_content = ? WHERE id = ?', (article_content, news_id))
            print(f"获取文章内容: {title}")
        
        if not discussion_content and discuss_url:
            discussion_content = get_discussion_content(discuss_url)
            cursor.execute('UPDATE news SET discussion_content = ? WHERE id = ?', (discussion_content, news_id))
            print(f"获取讨论内容: {title}")
        
        # 提交保存原始内容
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
            try:
                headers = {
                    'Authorization': f'Bearer {GROK_API_KEY}',
                    'Content-Type': 'application/json'
                }
                
                translation_prompt = f"请根据以下信息翻译标题：\n原标题：{title}\n文章摘要：{content_summary}\n请给出最准确、通顺的中文标题翻译,翻译的标题直接返回结果，无需添加任何额外内容，如果文章摘要为空，或者不符合，请直接返回空。"
                
                data = {
                    'messages': [
                        {
                            'role': 'system',
                            'content': '你是一个专业的翻译助手，需要根据文章上下文提供准确的标题翻译。'
                        },
                        {
                            'role': 'user',
                            'content': translation_prompt
                        }
                    ],
                    'model': 'grok-2-latest',
                    'temperature': 0.7,
                    'max_tokens': 200,
                    'stream': False
                }
                
                response = requests.post(GROK_API_URL, headers=headers, json=data, verify=True)
                response_json = response.json()
                
                if response.status_code == 200 and 'choices' in response_json:
                    title_chs = response_json['choices'][0]['message']['content'].strip()
                    cursor.execute('UPDATE news SET title_chs = ? WHERE id = ?', (title_chs, news_id))
                    print(f"Translated title for news {title}")
            except Exception as e:
                print(f"Error translating title: {e}")
        
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
            
            print(f"处理完成: {title}")
    
    conn.commit()
    conn.close()

def main():
    if not GROK_API_KEY:
        print("Error: GROK_API_KEY config variable is not set")
        return
    
    # 确保表结构正确
    create_or_update_table()
    process_news()
    print("Finished processing all news items.")

if __name__ == '__main__':
    main()