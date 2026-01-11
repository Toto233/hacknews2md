import sys
import os
# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

import requests
from bs4 import BeautifulSoup
import sqlite3
from datetime import datetime
import urllib.parse
import time
import logging
from contextlib import contextmanager
from typing import List, Dict, Optional, Tuple

# 导入项目模块
from src.core.archive_news import archive_old_news
from src.utils import db_utils

# 配置常量
DB_PATH = 'data/hacknews.db'
HACKERNEWS_URL = 'https://news.ycombinator.com/front'
BASE_URL = 'https://news.ycombinator.com/'
MAX_NEWS_ITEMS = 10
MAX_RETRIES = 3
RETRY_DELAY = 2
REQUEST_TIMEOUT = 10

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


@contextmanager
def get_db_connection():
    """数据库连接上下文管理器"""
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        yield conn
    except sqlite3.Error as e:
        logger.error(f"数据库错误: {e}")
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()


def extract_domain(url: str) -> str:
    """从URL中提取域名"""
    try:
        parsed_url = urllib.parse.urlparse(url)
        domain = parsed_url.netloc
        return domain
    except Exception as e:
        logger.warning(f"解析URL域名失败: {url}, 错误: {e}")
        return ""

def is_domain_filtered(domain: str, cursor: sqlite3.Cursor) -> bool:
    """检查域名是否在过滤列表中"""
    cursor.execute('SELECT id FROM filtered_domains WHERE domain = ?', (domain,))
    return cursor.fetchone() is not None


def is_url_in_history(news_url: str, cursor: sqlite3.Cursor) -> bool:
    """检查URL是否存在于news_history表中"""
    cursor.execute('SELECT id FROM news_history WHERE news_url = ?', (news_url,))
    return cursor.fetchone() is not None


def fetch_news() -> List[Dict[str, str]]:
    """获取HackerNews新闻列表"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Connection': 'keep-alive'
    }
    
    # 获取网页内容
    response = None
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(HACKERNEWS_URL, headers=headers, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            break
        except requests.RequestException as e:
            if attempt == MAX_RETRIES - 1:
                logger.error(f"获取新闻失败: {e}")
                return []
            logger.warning(f"第{attempt + 1}次尝试失败，{RETRY_DELAY}秒后重试...")
            time.sleep(RETRY_DELAY)
    
    # 解析HTML内容
    soup = BeautifulSoup(response.text, 'html.parser')
    titles = soup.find_all('span', class_='titleline')
    subtext = soup.find_all('td', class_='subtext')
    
    news_items = []
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        for title, sub in zip(titles, subtext):
            if len(news_items) >= MAX_NEWS_ITEMS:
                break
                
            title_link = title.find('a')
            if not title_link:
                continue
                
            news_title = title_link.text.strip()
            news_url = title_link['href']
            
            # 补全相对URL
            if not (news_url.startswith("http://") or news_url.startswith("https://")):
                news_url = f"{BASE_URL}{news_url}"
            
            # 检查URL是否在历史记录中
            if is_url_in_history(news_url, cursor):
                logger.info(f"跳过已存在于历史记录中的新闻: {news_title}")
                continue
                
            # 检查域名是否被过滤
            domain = extract_domain(news_url)
            if domain and is_domain_filtered(domain, cursor):
                logger.info(f"跳过被过滤的域名: {domain}, 标题: {news_title}")
                continue
            
            # 获取讨论链接
            discuss_url = ''
            discuss_link = sub.find('a', string=lambda text: text and 'comment' in text.lower())
            if discuss_link:
                try:
                    discuss_id = discuss_link['href'].split('id=')[1]
                    discuss_url = f'{BASE_URL}item?id={discuss_id}'
                except (IndexError, KeyError) as e:
                    logger.warning(f"解析讨论链接失败: {e}")
            
            news_items.append({
                'title': news_title,
                'news_url': news_url,
                'discuss_url': discuss_url
            })
    
    logger.info(f"成功获取 {len(news_items)} 条新闻")
    return news_items

def save_to_database(news_items: List[Dict[str, str]]) -> int:
    """保存新闻到数据库，返回实际保存的条目数"""
    if not news_items:
        logger.warning("没有新闻条目需要保存")
        return 0
    
    saved_count = 0
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        for item in news_items:
            # 跳过"Ask HN:"开头的新闻
            if item['title'].startswith('Ask HN:'):
                logger.info(f"跳过Ask HN类型新闻: {item['title']}")
                continue
                
            # 检查是否已存在相同标题的新闻
            cursor.execute('SELECT id FROM news WHERE title = ?', (item['title'],))
            if cursor.fetchone() is None:
                try:
                    cursor.execute('''
                    INSERT INTO news (title, news_url, discuss_url, created_at)
                    VALUES (?, ?, ?, ?)
                    ''', (item['title'], item['news_url'], item['discuss_url'], datetime.now()))
                    saved_count += 1
                    logger.info(f"保存新闻: {item['title']}")
                except sqlite3.Error as e:
                    logger.error(f"保存新闻失败: {item['title']}, 错误: {e}")
            else:
                logger.info(f"新闻已存在，跳过: {item['title']}")
        
        conn.commit()
    
    logger.info(f"成功保存 {saved_count} 条新闻到数据库")
    return saved_count

def add_filtered_domain(domain: str, reason: str = "") -> bool:
    """添加一个需要过滤的域名"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
            INSERT INTO filtered_domains (domain, reason, created_at)
            VALUES (?, ?, ?)
            ''', (domain, reason, datetime.now()))
            conn.commit()
            logger.info(f"成功添加过滤域名: {domain}")
            return True
    except sqlite3.IntegrityError:
        logger.warning(f"域名 {domain} 已在过滤列表中")
        return False
    except sqlite3.Error as e:
        logger.error(f"添加过滤域名失败: {domain}, 错误: {e}")
        return False

def remove_filtered_domain(domain: str) -> bool:
    """从过滤列表中移除一个域名"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM filtered_domains WHERE domain = ?', (domain,))
            if cursor.rowcount > 0:
                logger.info(f"成功移除过滤域名: {domain}")
                conn.commit()
                return True
            else:
                logger.warning(f"域名 {domain} 不在过滤列表中")
                return False
    except sqlite3.Error as e:
        logger.error(f"移除过滤域名失败: {domain}, 错误: {e}")
        return False

def list_filtered_domains() -> List[Tuple[str, str, str]]:
    """列出所有被过滤的域名"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT domain, reason, created_at FROM filtered_domains ORDER BY created_at DESC')
            domains = cursor.fetchall()
            
            if not domains:
                logger.info("过滤列表为空")
            else:
                logger.info("当前过滤的域名列表:")
                for domain, reason, created_at in domains:
                    logger.info(f"域名: {domain}, 原因: {reason}, 添加时间: {created_at}")
            
            return domains
    except sqlite3.Error as e:
        logger.error(f"获取过滤域名列表失败: {e}")
        return []

def main():
    """主程序入口"""
    try:
        logger.info("开始执行新闻获取流程")
        
        # 统一初始化所有表结构
        db_utils.init_database()
        
        # 先执行归档操作，清理旧数据
        archive_old_news()
        
        # 然后获取新闻
        news_items = fetch_news()
        
        # 保存到数据库
        saved_count = save_to_database(news_items)
        
        logger.info(f'成功获取 {len(news_items)} 条新闻，保存 {saved_count} 条到数据库')
        
    except Exception as e:
        logger.error(f"程序执行失败: {e}")
        raise

if __name__ == '__main__':
    main()