import os
import sqlite3
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import json
import urllib3

# 禁用SSL证书验证警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 初始化Grok API配置
# 从配置文件加载API密钥和URL
with open('config.json', 'r', encoding='utf-8') as f:
    config = json.load(f)
    GROK_API_KEY = config.get('GROK_API_KEY')
    GROK_API_URL = config.get('GROK_API_URL', 'https://api.x.ai/v1/chat/completions')

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
        text = '\n'.join([comment.get_text(strip=True) for comment in comments[:5]])  # 只获取前5条评论
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
        
        prompt = f"请用中文总结以下{'文章' if prompt_type == 'article' else '讨论'}的主要内容（130字左右）：\n{text},如果你认为这个文章并没有正确读取，请返回空字符串。"
        '''你是一个专业的文章摘要助手。请用中文总结以下文章的主要内容（130字左右）并且根据文章翻译标题为中文'''
        #如果文章摘要为空，或者不符合，使用上述promote粘贴文章内容到grok中，让grok帮你翻译标题，然后再生成文章摘要。
        data = {
            'messages': [
                {
                    'role': 'system',
                    'content': '你是一个专业的文章摘要助手。'
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
            return response_json['choices'][0]['message']['content'].strip()
        else:
            print(f"Error from Grok API: {response.text}")
            return ""
    except Exception as e:
        print(f"Error generating summary: {e}")
        return ""

def process_news():
    conn = sqlite3.connect('hacknews.db')
    cursor = conn.cursor()
    
    # 获取所有需要处理的新闻（包括需要翻译标题和生成摘要的）
    cursor.execute('''
    SELECT id, title, news_url, discuss_url 
    FROM news 
    WHERE title_chs IS NULL OR title_chs = '' OR content_summary IS NULL OR discuss_summary IS NULL OR content_summary = '' OR discuss_summary = ''
    ''')
    news_items = cursor.fetchall()
    
    for item in news_items:
        news_id, title, news_url, discuss_url = item
        
        # 先获取并生成文章摘要
        article_content = get_article_content(news_url)
        content_summary = generate_summary(article_content, 'article')
        
        # 获取并生成讨论摘要
        discussion_content = get_discussion_content(discuss_url)
        discuss_summary = generate_summary(discussion_content, 'discussion')
        
        # 检查并翻译标题，结合文章摘要提供上下文
        cursor.execute('SELECT title_chs FROM news WHERE id = ?', (news_id,))
        result = cursor.fetchone()
        if not result[0]:
            try:
                headers = {
                    'Authorization': f'Bearer {GROK_API_KEY}',
                    'Content-Type': 'application/json'
                }
                
                # 将原标题和文章摘要一起提供给翻译模型
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
        
        # 更新数据库
        cursor.execute('''
        UPDATE news 
        SET content_summary = ?, discuss_summary = ? 
        WHERE id = ?
        ''', (content_summary, discuss_summary, news_id))
        
        print(f"Processed news: {title}")
    
    conn.commit()
    conn.close()

def main():
    if not GROK_API_KEY:
        print("Error: GROK_API_KEY config variable is not set")
        return
    
    process_news()
    print("Finished processing all news items.")

if __name__ == '__main__':
    main()