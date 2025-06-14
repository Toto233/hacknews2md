import requests
from bs4 import BeautifulSoup
import sqlite3
import os
from datetime import datetime
import urllib.parse
import time
# 导入归档模块
from archive_news import archive_old_news
# 新增：导入db_utils
import db_utils

def extract_domain(url):
    """从URL中提取域名"""
    try:
        parsed_url = urllib.parse.urlparse(url)
        domain = parsed_url.netloc
        return domain
    except:
        return ""

def is_domain_filtered(domain, cursor):
    """检查域名是否在过滤列表中"""
    cursor.execute('SELECT id FROM filtered_domains WHERE domain = ?', (domain,))
    return cursor.fetchone() is not None

def fetch_news():
    url = 'https://news.ycombinator.com/front'
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Connection': 'keep-alive'
    }
    
    max_retries = 3
    retry_delay = 2  # 重试间隔秒数
    
    for attempt in range(max_retries):
        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            break
        except (requests.RequestException) as e:
            if attempt == max_retries - 1:
                print(f"获取新闻失败: {e}")
                return []
            print(f"第{attempt + 1}次尝试失败，{retry_delay}秒后重试...")
            time.sleep(retry_delay)
    
    soup = BeautifulSoup(response.text, 'html.parser')
    
    news_items = []
    titles = soup.find_all('span', class_='titleline')
    subtext = soup.find_all('td', class_='subtext')
    
    # 连接数据库获取过滤域名
    conn = sqlite3.connect('hacknews.db')
    cursor = conn.cursor()
    
    for idx, (title, sub) in enumerate(zip(titles, subtext)):
        if idx >= 10:  # 只获取前10条新闻
            break
            
        title_link = title.find('a')
        news_title = title_link.text
        news_url = title_link['href']
        
        # 如果 news_url 不是完整的 URL，则补全为 Hacker News 的标准链接
        if not (news_url.startswith("http://") or news_url.startswith("https://")):
            # 补全为 https://news.ycombinator.com/item?id=xxxx
            news_url = f"https://news.ycombinator.com/{news_url}"
        
        # 提取域名并检查是否被过滤
        domain = extract_domain(news_url)
        if domain and is_domain_filtered(domain, cursor):
            print(f"跳过被过滤的域名: {domain}, 标题: {news_title}")
            continue
        
        # 获取discuss链接
        discuss_link = sub.find('a', string=lambda text: text and 'comment' in text.lower())
        if discuss_link:
            discuss_id = discuss_link['href'].split('id=')[1]
            discuss_url = f'https://news.ycombinator.com/item?id={discuss_id}'
        else:
            discuss_url = ''
        
        news_items.append({
            'title': news_title,
            'news_url': news_url,
            'discuss_url': discuss_url
        })
    
    conn.close()
    return news_items

def save_to_database(news_items):
    conn = sqlite3.connect('hacknews.db')
    cursor = conn.cursor()
    for item in news_items:
        # 跳过"Ask HN:"开头的新闻
        if item['title'].startswith('Ask HN:'):
            continue
            
        # 检查是否已存在相同标题的新闻
        cursor.execute('SELECT id FROM news WHERE title = ?', (item['title'],))
        if cursor.fetchone() is None:
            # 如果不存在相同标题的新闻，则插入
            cursor.execute('''
            INSERT INTO news (title, news_url, discuss_url, created_at)
            VALUES (?, ?, ?, ?)
            ''', (item['title'], item['news_url'], item['discuss_url'], datetime.now()))
    conn.commit()
    conn.close()

def add_filtered_domain(domain, reason=""):
    """添加一个需要过滤的域名"""
    conn = sqlite3.connect('hacknews.db')
    cursor = conn.cursor()
    try:
        cursor.execute('''
        INSERT INTO filtered_domains (domain, reason, created_at)
        VALUES (?, ?, ?)
        ''', (domain, reason, datetime.now()))
        conn.commit()
        print(f"成功添加过滤域名: {domain}")
    except sqlite3.IntegrityError:
        print(f"域名 {domain} 已在过滤列表中")
    finally:
        conn.close()

def remove_filtered_domain(domain):
    """从过滤列表中移除一个域名"""
    conn = sqlite3.connect('hacknews.db')
    cursor = conn.cursor()
    cursor.execute('DELETE FROM filtered_domains WHERE domain = ?', (domain,))
    if cursor.rowcount > 0:
        print(f"成功移除过滤域名: {domain}")
    else:
        print(f"域名 {domain} 不在过滤列表中")
    conn.commit()
    conn.close()

def list_filtered_domains():
    """列出所有被过滤的域名"""
    conn = sqlite3.connect('hacknews.db')
    cursor = conn.cursor()
    cursor.execute('SELECT domain, reason, created_at FROM filtered_domains ORDER BY created_at DESC')
    domains = cursor.fetchall()
    conn.close()
    
    if not domains:
        print("过滤列表为空")
    else:
        print("当前过滤的域名列表:")
        for domain, reason, created_at in domains:
            print(f"域名: {domain}, 原因: {reason}, 添加时间: {created_at}")
    
    return domains

def main():
    # 统一初始化所有表结构
    db_utils.init_database()
    # 先执行归档操作，清理旧数据
    archive_old_news()
    # 然后获取新闻
    news_items = fetch_news()
    save_to_database(news_items)
    print(f'Successfully fetched and saved {len(news_items)} news items.')

if __name__ == '__main__':
    main()