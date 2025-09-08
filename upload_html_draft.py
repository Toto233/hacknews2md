#!/usr/bin/env python3
"""
Upload HTML file to WeChat Draft Box
Converts HTML to WeChat-compatible format and uploads as draft
"""

import os
import re
import platform
from bs4 import BeautifulSoup
from config import Config
from wechat_access_token import WeChatAccessToken

# Default thumbnail media_id (640.png uploaded to WeChat)
DEFAULT_THUMB_MEDIA_ID = "53QZJEu2zs4etGM_3jLi5wl7KNs2RM1RnV_iiGWQmWnYf7qEq2kvHRIIeBCBnAEb"

def is_wsl():
    """
    Check if running in WSL environment
    
    Returns:
        True if running in WSL, False otherwise
    """
    try:
        # Check for WSL specific indicators
        if platform.system() == 'Linux':
            # Check for WSL in /proc/version
            with open('/proc/version', 'r') as f:
                version_info = f.read().lower()
                if 'microsoft' in version_info or 'wsl' in version_info:
                    return True
            
            # Check for WSL mount points
            if os.path.exists('/mnt/c') or os.path.exists('/mnt/d'):
                return True
    except:
        pass
    
    return False

def convert_windows_path_to_wsl(windows_path):
    """
    Convert Windows path to WSL path
    
    Args:
        windows_path: Windows-style path like D:\python\...
        
    Returns:
        WSL-style path like /mnt/d/python/...
    """
    if not windows_path or windows_path.startswith('/'):
        return windows_path  # Already Unix path
    
    # Convert Windows path to WSL path
    if ':\\' in windows_path:
        drive, path = windows_path.split(':\\', 1)
        drive = drive.lower()
        path = path.replace('\\', '/')
        return f'/mnt/{drive}/{path}'
    
    return windows_path

def smart_path_convert(path_str):
    """
    Smart path conversion based on current environment
    
    Args:
        path_str: Original path string from HTML
        
    Returns:
        Converted path suitable for current environment
    """
    if not path_str:
        return path_str
    
    # If running in WSL and path looks like Windows path
    if is_wsl() and (':\\' in path_str or '\\' in path_str):
        wsl_path = convert_windows_path_to_wsl(path_str)
        # Check if converted path exists
        if os.path.exists(wsl_path):
            return wsl_path
        else:
            print(f"Warning: Converted path not found: {path_str} -> {wsl_path}")
    
    # If not WSL or path doesn't need conversion, return original
    return path_str

def extract_html_content(html_file_path):
    """
    Extract title and content from HTML file
    
    Args:
        html_file_path: Path to the HTML file
        
    Returns:
        Dict with title, content, and images found
    """
    if not os.path.exists(html_file_path):
        raise FileNotFoundError(f"HTML file not found: {html_file_path}")
    
    with open(html_file_path, 'r', encoding='utf-8') as f:
        html_content = f.read()
    
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Extract title from <title> tag or h1
    title = ""
    if soup.title:
        title = soup.title.get_text().strip()
    elif soup.h1:
        title = soup.h1.get_text().strip()
    else:
        # Use filename as fallback
        title = os.path.splitext(os.path.basename(html_file_path))[0]
    
    # WeChat title limit is 64 characters, truncate if needed
    if len(title) > 64:
        title = title[:61] + "..."
        print(f"Title truncated to: {title}")
    
    # Extract body content
    if soup.body:
        content_element = soup.body
    else:
        content_element = soup
    
    local_images = []
    
    print(f"Current environment: {'WSL' if is_wsl() else 'Native'}")
    
    # Find all image tags and convert paths
    for img in content_element.find_all('img'):
        src = img.get('src', '')
        if src and not src.startswith(('http://', 'https://', '//', 'data:')):
            # Smart path conversion based on environment
            converted_path = smart_path_convert(src)
            
            # Check if the converted path exists
            if os.path.exists(converted_path):
                img['src'] = converted_path
                local_images.append(converted_path)
                print(f"✓ Image found: {src} -> {converted_path}")
            else:
                print(f"✗ Image not found: {src} -> {converted_path}")
    
    # Get clean HTML content
    content_html = str(content_element)
    
    return {
        'title': title,
        'content': content_html,
        'local_images': local_images
    }

def clean_html_for_wechat(html_content):
    """
    Extract body content for WeChat (CSS already inlined)
    
    Args:
        html_content: Raw HTML content
        
    Returns:
        Body content suitable for WeChat
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Extract body content only
    if soup.body:
        body_content = soup.body
        # Get inner HTML of body tag
        content_html = ''.join(str(child) for child in body_content.children)
    else:
        # If no body tag, use the entire content
        content_html = str(soup)
    
    return content_html

def upload_html_to_draft(html_file_path, author="", digest="", source_url=""):
    """
    Upload HTML file to WeChat draft box
    
    Args:
        html_file_path: Path to the HTML file
        author: Article author (optional)
        digest: Article summary (optional) 
        source_url: Original article URL (optional)
        
    Returns:
        Media ID if successful, None if failed
    """
    try:
        # Load configuration
        config = Config()
        wechat_config = config.get_wechat_config()
        
        if not wechat_config:
            print("Error: WeChat configuration not found")
            return None
        
        # Initialize WeChat client
        wechat = WeChatAccessToken(wechat_config['appid'], wechat_config['appsec'])
        
        # Extract content from HTML
        print(f"Extracting content from: {html_file_path}")
        extracted = extract_html_content(html_file_path)
        
        print(f"Title: {extracted['title']}")
        print(f"Found {len(extracted['local_images'])} local images")
        
        # Clean HTML for WeChat
        cleaned_content = clean_html_for_wechat(extracted['content'])
        
        # Prepare article data
        article = {
            'title': extracted['title'],
            'content': cleaned_content,
            'author': author,
            'digest': digest or extracted['title'][:120],  # Use title as digest if not provided
            'content_source_url': source_url,
            'article_type': 'news',
            'need_open_comment': 0,
            'only_fans_can_comment': 0
        }
        
        # Use smart upload to handle images automatically
        print("\nUploading to WeChat draft box...")
        # Use 640.png as default thumbnail
        media_id = wechat.add_draft_smart([article], DEFAULT_THUMB_MEDIA_ID)
        
        if media_id:
            print(f"\nSuccess! Draft uploaded with Media ID: {media_id}")
            print(f"You can now find this draft in your WeChat Official Account backend.")
            return media_id
        else:
            print("Failed to upload draft")
            return None
            
    except Exception as e:
        print(f"Error uploading HTML to draft: {e}")
        return None

def main():
    """Main function for command line usage"""
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python3 upload_html_draft.py <html_file> [author] [digest] [source_url]")
        print("Example: python3 upload_html_draft.py hacknews_summary_20250907_0935.html 'HackerNews摘要' '今日技术热点汇总'")
        return
    
    html_file = sys.argv[1]
    author = sys.argv[2] if len(sys.argv) > 2 else ""
    digest = sys.argv[3] if len(sys.argv) > 3 else ""
    source_url = sys.argv[4] if len(sys.argv) > 4 else ""
    
    # Upload the HTML file
    result = upload_html_to_draft(html_file, author, digest, source_url)
    
    if result:
        print(f"\nUpload completed successfully!")
    else:
        print(f"\nUpload failed!")

if __name__ == "__main__":
    main()