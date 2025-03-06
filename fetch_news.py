import requests
from bs4 import BeautifulSoup
import sqlite3
import os
from datetime import datetime

def create_database():
    conn = sqlite3.connect('hacknews.db')
    cursor = conn.cursor()
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS news (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        title_chs TEXT,
        news_url TEXT,
        discuss_url TEXT,
        content_summary TEXT,
        discuss_summary TEXT,
        created_at TIMESTAMP
    )
    ''')
    conn.commit()
    conn.close()

def fetch_news():
    url = 'https://news.ycombinator.com/front'
    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')
    
    news_items = []
    titles = soup.find_all('span', class_='titleline')
    subtext = soup.find_all('td', class_='subtext')
    
    for idx, (title, sub) in enumerate(zip(titles, subtext)):
        if idx >= 10:  # 只获取前10条新闻
            break
            
        title_link = title.find('a')
        news_title = title_link.text
        news_url = title_link['href']
        
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

def main():
    create_database()
    news_items = fetch_news()
    save_to_database(news_items)
    print(f'Successfully fetched and saved {len(news_items)} news items.')

if __name__ == '__main__':
    main()