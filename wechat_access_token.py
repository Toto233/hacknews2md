#!/usr/bin/env python3
"""
WeChat Access Token Tool
Automatically retrieves WeChat access token using app ID and secret.
Stores tokens in SQLite database with expiration management.
"""

import requests
import json
import time
import sqlite3
import os
import re
import hashlib
from datetime import datetime, timedelta
from typing import Dict, Optional

class WeChatAccessToken:
    def __init__(self, appid: str, secret: str, db_path: str = "wechat_tokens.db"):
        self.appid = appid
        self.secret = secret
        self.db_path = db_path
        self.access_token = None
        self.expires_at = None
        self._init_database()
        
    def _init_database(self):
        """Initialize SQLite database and create tables if not exists"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                # Create access_tokens table
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS access_tokens (
                        appid TEXT PRIMARY KEY,
                        access_token TEXT NOT NULL,
                        created_at TIMESTAMP NOT NULL,
                        expires_at TIMESTAMP NOT NULL,
                        expires_in INTEGER NOT NULL
                    )
                ''')
                
                # Create image_uploads table for caching uploaded images
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS image_uploads (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        file_path TEXT NOT NULL,
                        file_name TEXT NOT NULL,
                        file_md5 TEXT NOT NULL,
                        file_size INTEGER NOT NULL,
                        upload_date DATE NOT NULL,
                        upload_type TEXT NOT NULL, -- 'article' or 'thumb'
                        media_id TEXT,
                        media_url TEXT NOT NULL,
                        appid TEXT NOT NULL,
                        created_at TIMESTAMP NOT NULL,
                        UNIQUE(file_md5, upload_date, upload_type, appid)
                    )
                ''')
                
                conn.commit()
                print(f"Database initialized: {self.db_path}")
        except Exception as e:
            print(f"Database initialization error: {e}")
    
    def _save_token_to_db(self, access_token: str, expires_in: int):
        """Save access token to database"""
        try:
            created_at = datetime.now()
            expires_at = created_at + timedelta(seconds=expires_in - 300)  # 5 minute buffer
            
            with sqlite3.connect(self.db_path) as conn:
                conn.execute('''
                    INSERT OR REPLACE INTO access_tokens 
                    (appid, access_token, created_at, expires_at, expires_in)
                    VALUES (?, ?, ?, ?, ?)
                ''', (self.appid, access_token, created_at, expires_at, expires_in))
                conn.commit()
                
            self.access_token = access_token
            self.expires_at = expires_at
            print(f"Token saved to database, expires at: {expires_at}")
            return True
        except Exception as e:
            print(f"Error saving token to database: {e}")
            return False
    
    def _load_token_from_db(self) -> Optional[str]:
        """Load valid access token from database"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute('''
                    SELECT access_token, expires_at, created_at, expires_in
                    FROM access_tokens 
                    WHERE appid = ?
                ''', (self.appid,))
                
                row = cursor.fetchone()
                if not row:
                    print("No token found in database")
                    return None
                
                # Parse datetime string
                expires_at = datetime.fromisoformat(row['expires_at'])
                created_at = datetime.fromisoformat(row['created_at'])
                
                # Check if token is still valid
                if datetime.now() < expires_at:
                    self.access_token = row['access_token']
                    self.expires_at = expires_at
                    remaining = (expires_at - datetime.now()).total_seconds()
                    print(f"Valid token found in database (expires in {int(remaining)} seconds)")
                    return row['access_token']
                else:
                    print("Token in database has expired")
                    # Clean up expired token
                    conn.execute('DELETE FROM access_tokens WHERE appid = ?', (self.appid,))
                    conn.commit()
                    return None
                    
        except Exception as e:
            print(f"Error loading token from database: {e}")
            return None
        
    def get_access_token(self, force_refresh: bool = False, retry_count: int = 2) -> Optional[str]:
        """
        Get WeChat access token. Checks database first, then API if needed.

        Args:
            force_refresh: Force refresh token even if cached one is valid
            retry_count: Number of retries if API request fails (default: 2)

        Returns:
            Access token string or None if failed
        """
        # Check database first unless force refresh is requested
        if not force_refresh:
            db_token = self._load_token_from_db()
            if db_token:
                return db_token

        # Request new token from API with retry logic
        url = "https://api.weixin.qq.com/cgi-bin/token"
        params = {
            'grant_type': 'client_credential',
            'appid': self.appid,
            'secret': self.secret
        }

        for attempt in range(retry_count):
            try:
                if attempt > 0:
                    print(f"Retrying to get access token (attempt {attempt + 1}/{retry_count})...")
                else:
                    print("Requesting new access token from WeChat API...")

                response = requests.get(url, params=params, timeout=10)
                response.raise_for_status()

                data = response.json()

                if 'access_token' in data:
                    access_token = data['access_token']
                    expires_in = data.get('expires_in', 7200)

                    # Save to database
                    if self._save_token_to_db(access_token, expires_in):
                        print(f"New access token retrieved and saved!")
                        print(f"Token: {access_token[:20]}...")
                        return access_token
                    else:
                        print("Warning: Token retrieved but failed to save to database")
                        return access_token
                else:
                    error_code = data.get('errcode', 'unknown')
                    error_msg = data.get('errmsg', 'unknown error')
                    print(f"WeChat API error {error_code}: {error_msg}")

                    # Only retry for certain error codes (e.g., network issues, rate limits)
                    if attempt < retry_count - 1:
                        print(f"Will retry in 2 seconds...")
                        time.sleep(2)
                        continue
                    return None

            except requests.exceptions.RequestException as e:
                print(f"Network error: {e}")
                if attempt < retry_count - 1:
                    print(f"Will retry in 2 seconds...")
                    time.sleep(2)
                    continue
                return None
            except json.JSONDecodeError as e:
                print(f"JSON decode error: {e}")
                if attempt < retry_count - 1:
                    print(f"Will retry in 2 seconds...")
                    time.sleep(2)
                    continue
                return None
            except Exception as e:
                print(f"Unexpected error: {e}")
                if attempt < retry_count - 1:
                    print(f"Will retry in 2 seconds...")
                    time.sleep(2)
                    continue
                return None

        return None
    
    def is_token_valid(self) -> bool:
        """Check if current token is still valid"""
        if not self.access_token or not self.expires_at:
            # Try to load from database
            token = self._load_token_from_db()
            return token is not None
        return datetime.now() < self.expires_at
    
    def get_token_info(self) -> Dict:
        """Get current token information"""
        if not self.access_token:
            # Try to load from database
            self._load_token_from_db()
            
        return {
            'access_token': self.access_token,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'is_valid': self.is_token_valid(),
            'remaining_seconds': (self.expires_at - datetime.now()).total_seconds() if self.expires_at else 0,
            'db_path': self.db_path
        }
    
    def clear_expired_tokens(self):
        """Remove all expired tokens from database"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute('''
                    DELETE FROM access_tokens 
                    WHERE datetime(expires_at) < datetime('now')
                ''')
                deleted_count = cursor.rowcount
                conn.commit()
                print(f"Cleared {deleted_count} expired tokens from database")
                return deleted_count
        except Exception as e:
            print(f"Error clearing expired tokens: {e}")
            return 0
    
    def _calculate_file_md5(self, file_path: str) -> str:
        """Calculate MD5 hash of a file"""
        hash_md5 = hashlib.md5()
        try:
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_md5.update(chunk)
            return hash_md5.hexdigest()
        except Exception as e:
            print(f"Error calculating MD5 for {file_path}: {e}")
            return ""
    
    def _check_image_cache(self, file_path: str, upload_type: str = "article") -> Optional[Dict]:
        """
        Check if image was already uploaded today
        
        Args:
            file_path: Path to the image file
            upload_type: Type of upload ('article' or 'thumb')
            
        Returns:
            Dict with cached upload info or None if not found
        """
        if not os.path.exists(file_path):
            return None
            
        file_md5 = self._calculate_file_md5(file_path)
        if not file_md5:
            return None
        
        today = datetime.now().date().isoformat()
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute('''
                    SELECT * FROM image_uploads 
                    WHERE file_md5 = ? AND upload_date = ? AND upload_type = ? AND appid = ?
                    ORDER BY created_at DESC LIMIT 1
                ''', (file_md5, today, upload_type, self.appid))
                
                row = cursor.fetchone()
                if row:
                    return {
                        'media_id': row['media_id'],
                        'media_url': row['media_url'],
                        'file_name': row['file_name'],
                        'file_size': row['file_size'],
                        'upload_type': row['upload_type'],
                        'cached': True
                    }
                    
        except Exception as e:
            print(f"Error checking image cache: {e}")
            
        return None
    
    def _save_image_upload(self, file_path: str, upload_type: str, media_id: str = None, media_url: str = "") -> bool:
        """
        Save image upload record to database
        
        Args:
            file_path: Path to the uploaded file
            upload_type: Type of upload ('article' or 'thumb')
            media_id: WeChat media ID (for permanent materials)
            media_url: WeChat media URL
            
        Returns:
            True if saved successfully, False otherwise
        """
        if not os.path.exists(file_path):
            return False
            
        file_md5 = self._calculate_file_md5(file_path)
        if not file_md5:
            return False
        
        file_name = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)
        today = datetime.now().date().isoformat()
        created_at = datetime.now()
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute('''
                    INSERT OR REPLACE INTO image_uploads 
                    (file_path, file_name, file_md5, file_size, upload_date, 
                     upload_type, media_id, media_url, appid, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (file_path, file_name, file_md5, file_size, today, 
                     upload_type, media_id, media_url, self.appid, created_at))
                conn.commit()
                print(f"💾 Image upload cached: {file_name} ({upload_type})")
                return True
                
        except Exception as e:
            print(f"Error saving image upload record: {e}")
            return False
    
    def get_all_tokens_info(self) -> list:
        """Get information about all tokens in database"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute('''
                    SELECT appid, access_token, created_at, expires_at, expires_in,
                           datetime(expires_at) > datetime('now') as is_valid
                    FROM access_tokens
                    ORDER BY created_at DESC
                ''')
                
                tokens = []
                for row in cursor.fetchall():
                    tokens.append({
                        'appid': row['appid'],
                        'access_token': row['access_token'][:20] + '...',
                        'created_at': row['created_at'],
                        'expires_at': row['expires_at'],
                        'expires_in': row['expires_in'],
                        'is_valid': bool(row['is_valid'])
                    })
                return tokens
        except Exception as e:
            print(f"Error getting tokens info: {e}")
            return []
    
    def get_draft_list(self, offset: int = 0, count: int = 20, no_content: int = 0) -> Optional[Dict]:
        """
        Get WeChat draft list
        
        Args:
            offset: Start position (0 means from the first draft)
            count: Number of drafts to return (1-20)
            no_content: 1 to not return content field, 0 to return normally (default: 0)
            
        Returns:
            Dict containing draft list or None if failed
        """
        # Validate parameters
        if not (1 <= count <= 20):
            print("Error: count must be between 1 and 20")
            return None
        
        if no_content not in [0, 1]:
            print("Error: no_content must be 0 or 1")
            return None
        
        # Get access token
        access_token = self.get_access_token()
        if not access_token:
            print("Error: Could not get access token")
            return None
        
        # API endpoint
        url = f"https://api.weixin.qq.com/cgi-bin/draft/batchget?access_token={access_token}"
        
        # Request payload
        payload = {
            "offset": offset,
            "count": count,
            "no_content": no_content
        }
        
        try:
            print(f"Requesting draft list (offset={offset}, count={count}, no_content={no_content})...")
            # Use json.dumps with ensure_ascii=False for Chinese support
            payload_json = json.dumps(payload, ensure_ascii=False).encode('utf-8')
            headers = {'Content-Type': 'application/json; charset=utf-8'}
            response = requests.post(url, data=payload_json, headers=headers, timeout=30)
            response.raise_for_status()
            
            # Ensure proper UTF-8 decoding
            response.encoding = 'utf-8'
            data = response.json()
            
            if 'total_count' in data:
                print(f"Successfully retrieved draft list:")
                print(f"  Total drafts: {data.get('total_count', 0)}")
                print(f"  Returned items: {data.get('item_count', 0)}")
                return data
            else:
                error_code = data.get('errcode', 'unknown')
                error_msg = data.get('errmsg', 'unknown error')
                print(f"WeChat API error {error_code}: {error_msg}")
                return None
                
        except requests.exceptions.RequestException as e:
            print(f"Network error: {e}")
            return None
        except json.JSONDecodeError as e:
            print(f"JSON decode error: {e}")
            return None
        except Exception as e:
            print(f"Unexpected error: {e}")
            return None
    
    def add_draft(self, articles: list) -> Optional[str]:
        """
        Add articles to WeChat draft box
        
        Args:
            articles: List of article dictionaries with required fields:
                - title: Article title (required)
                - content: Article content (required)
                - article_type: "news" or "newspic" (optional, defaults to "news")
                - author: Author name (optional)
                - digest: Article summary (optional)
                - content_source_url: Original article URL (optional)
                - thumb_media_id: Cover image media ID (required for news articles)
                - need_open_comment: 0 or 1 (optional, default 0)
                - only_fans_can_comment: 0 or 1 (optional, default 0)
                - pic_crop_235_1: Cover crop coordinates for 2.35:1 ratio (optional)
                - pic_crop_1_1: Cover crop coordinates for 1:1 ratio (optional)
                - image_info: Image information for newspic articles (optional)
                - cover_info: Cover information (optional)
                - product_info: Product information (optional)
        
        Returns:
            Media ID string if successful, None if failed
        """
        # Validate articles
        if not articles or not isinstance(articles, list):
            print("Error: articles must be a non-empty list")
            return None
        
        for i, article in enumerate(articles):
            # Check required fields
            if not article.get('title'):
                print(f"Error: Article {i+1} missing required field 'title'")
                return None
            if not article.get('content'):
                print(f"Error: Article {i+1} missing required field 'content'")
                return None
            
            # Check article type specific requirements
            article_type = article.get('article_type', 'news')
            if article_type == 'news' and not article.get('thumb_media_id'):
                print(f"Error: Article {i+1} of type 'news' requires 'thumb_media_id'")
                return None
            elif article_type == 'newspic' and not article.get('image_info'):
                print(f"Error: Article {i+1} of type 'newspic' requires 'image_info'")
                return None
        
        # Get access token
        access_token = self.get_access_token()
        if not access_token:
            print("Error: Could not get access token")
            return None
        
        # API endpoint
        url = f"https://api.weixin.qq.com/cgi-bin/draft/add?access_token={access_token}"
        
        # Prepare payload
        payload = {"articles": articles}
        
        try:
            print(f"Adding {len(articles)} article(s) to draft box...")
            # Use json.dumps with ensure_ascii=False to preserve Chinese characters
            payload_json = json.dumps({"articles": articles}, ensure_ascii=False).encode('utf-8')
            headers = {'Content-Type': 'application/json; charset=utf-8'}
            response = requests.post(url, data=payload_json, headers=headers, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            
            if 'media_id' in data:
                media_id = data['media_id']
                print(f"Successfully added draft! Media ID: {media_id}")
                return media_id
            else:
                error_code = data.get('errcode', 'unknown')
                error_msg = data.get('errmsg', 'unknown error')
                print(f"WeChat API error {error_code}: {error_msg}")
                return None
                
        except requests.exceptions.RequestException as e:
            print(f"Network error: {e}")
            return None
        except json.JSONDecodeError as e:
            print(f"JSON decode error: {e}")
            return None
        except Exception as e:
            print(f"Unexpected error: {e}")
            return None
    
    def add_draft_smart(self, articles: list, default_thumb_media_id: str = None) -> Optional[str]:
        """
        Intelligently add articles to WeChat draft box with automatic image handling
        
        This method will:
        1. Find local images in article content and upload them using upload_image_for_article
        2. Replace local image paths with uploaded URLs in content
        3. Use the first article's first image as thumb_media_id, or default if no images
        4. Automatically set required fields for draft creation
        
        Args:
            articles: List of article dictionaries with fields:
                - title: Article title (required)
                - content: Article content with possible local image paths (required)
                - author: Author name (optional)
                - digest: Article summary (optional)
                - content_source_url: Original article URL (optional)
                - article_type: "news" or "newspic" (optional, defaults to "news")
                - need_open_comment: 0 or 1 (optional, default 0)
                - only_fans_can_comment: 0 or 1 (optional, default 0)
            default_thumb_media_id: Default thumb media ID if no images found
            
        Returns:
            Media ID string if successful, None if failed
        """
        if not articles or not isinstance(articles, list):
            print("Error: articles must be a non-empty list")
            return None
        
        print(f"Smart draft processing: {len(articles)} article(s)")
        processed_articles = []
        first_thumb_media_id = None
        first_article_has_image = False  # Track if first article has any images

        for i, article in enumerate(articles):
            # Check required fields
            if not article.get('title'):
                print(f"Error: Article {i+1} missing required field 'title'")
                return None
            if not article.get('content'):
                print(f"Error: Article {i+1} missing required field 'content'")
                return None

            print(f"\nProcessing article {i+1}: {article['title']}")

            # Copy article data
            processed_article = article.copy()
            processed_content = processed_article['content']

            # Find local image paths in content
            # Look for common patterns: img src="local_path", ![](local_path), etc.
            image_patterns = [
                r'<img[^>]+src=["\']([^"\']+\.(?:jpg|jpeg|png|gif|webp))["\'][^>]*>',  # HTML img tags
                r'!\[.*?\]\(([^)]+\.(?:jpg|jpeg|png|gif|webp))\)',  # Markdown images
                r'src=["\']([^"\']+\.(?:jpg|jpeg|png|gif|webp))["\']',  # Simple src attributes
            ]

            found_images = set()
            for pattern in image_patterns:
                matches = re.findall(pattern, processed_content, re.IGNORECASE)
                found_images.update(matches)

            # Filter for local files (not URLs)
            local_images = [img for img in found_images if not img.startswith(('http://', 'https://', '//'))]

            if local_images:
                print(f"  Found {len(local_images)} local image(s): {local_images}")

                # Mark if this is the first article with images
                if i == 0:
                    first_article_has_image = True

                # Upload local images and replace paths
                for local_path in local_images:
                    # Check if file exists
                    if os.path.exists(local_path):
                        print(f"  Uploading: {local_path}")
                        uploaded_url = self.upload_image_for_article(local_path)

                        if uploaded_url:
                            # Replace all occurrences of local path with uploaded URL
                            processed_content = processed_content.replace(local_path, uploaded_url)
                            print(f"    ✓ Replaced with: {uploaded_url}")

                            # ONLY use first image of first article as thumb, not from other articles
                            if i == 0 and first_thumb_media_id is None:
                                # Upload as permanent material for thumb
                                print(f"  Using as thumb image: {local_path}")
                                thumb_result = self.upload_permanent_material(local_path, "thumb")
                                if thumb_result:
                                    first_thumb_media_id = thumb_result['media_id']
                                    print(f"    ✓ Thumb media ID: {first_thumb_media_id}")
                        else:
                            print(f"    ✗ Failed to upload: {local_path}")
                    else:
                        print(f"  ✗ Image file not found: {local_path}")
            else:
                print(f"  No local images found in article {i+1}")
                if i == 0:
                    # First article has no images
                    first_article_has_image = False
            
            # Update processed content
            processed_article['content'] = processed_content
            
            # Set default values for required fields
            processed_article.setdefault('article_type', 'news')
            processed_article.setdefault('author', '')
            processed_article.setdefault('digest', '')
            processed_article.setdefault('content_source_url', '')
            processed_article.setdefault('need_open_comment', 0)
            processed_article.setdefault('only_fans_can_comment', 0)
            
            # Set thumb_media_id for news articles
            if processed_article['article_type'] == 'news':
                # CRITICAL: Only use first_thumb_media_id if first article has images
                # If first article has NO images, always use default thumb
                if first_article_has_image and first_thumb_media_id:
                    # First article has images, use its first image as thumb
                    processed_article['thumb_media_id'] = first_thumb_media_id
                    print(f"  Article {i+1} using first article's image as thumb: {first_thumb_media_id}")
                else:
                    # First article has NO images, use default thumb
                    thumb_to_use = default_thumb_media_id or "53QZJEu2zs4etGM_3jLi5wl7KNs2RM1RnV_iiGWQmWnYf7qEq2kvHRIIeBCBnAEb"
                    processed_article['thumb_media_id'] = thumb_to_use
                    if not first_article_has_image:
                        print(f"  Article {i+1} using DEFAULT thumb (first article has no images): {thumb_to_use}")
                    else:
                        print(f"  Article {i+1} using default thumb: {thumb_to_use}")
            
            processed_articles.append(processed_article)
        
        print(f"\nSmart processing complete. Creating draft...")
        # Use the original add_draft method with processed articles
        return self.add_draft(processed_articles)

    def upload_permanent_material(self, file_path: str, media_type: str = "image", title: str = None, introduction: str = None) -> Optional[Dict]:
        """
        Upload permanent material to WeChat (with caching)
        
        Args:
            file_path: Path to the media file
            media_type: Type of media ("image", "voice", "video", "thumb")
            title: Title for video media (required for video type)
            introduction: Introduction for video media (optional)
            
        Returns:
            Dict containing media_id and url if successful, None if failed
        """
        # For image and thumb types, check cache first
        if media_type in ["image", "thumb"]:
            cached_result = self._check_image_cache(file_path, media_type)
            if cached_result:
                print(f"📱 Using cached {media_type}: {cached_result['file_name']} (media_id: {cached_result['media_id']})")
                return {
                    'media_id': cached_result['media_id'],
                    'url': cached_result['media_url'],
                    'type': media_type,
                    'file_path': file_path,
                    'cached': True
                }
        
        # Validate media type
        valid_types = ["image", "voice", "video", "thumb"]
        if media_type not in valid_types:
            print(f"Error: media_type must be one of {valid_types}")
            return None
        
        # Check if file exists
        if not os.path.exists(file_path):
            print(f"Error: File not found: {file_path}")
            return None
        
        # Video type requires title
        if media_type == "video" and not title:
            print("Error: Video media requires title parameter")
            return None
        
        # Get access token
        access_token = self.get_access_token()
        if not access_token:
            print("Error: Could not get access token")
            return None
        
        # API endpoint
        url = f"https://api.weixin.qq.com/cgi-bin/material/add_material?access_token={access_token}&type={media_type}"
        
        try:
            print(f"Uploading permanent {media_type} material: {file_path}")
            
            # Prepare files for upload
            with open(file_path, 'rb') as f:
                files = {'media': (os.path.basename(file_path), f, 'application/octet-stream')}
                
                # Prepare form data
                data = {}
                if media_type == "video" and title:
                    description = {
                        "title": title,
                        "introduction": introduction or ""
                    }
                    data = {'description': json.dumps(description)}
                
                # Make request
                response = requests.post(url, files=files, data=data, timeout=60)
                response.raise_for_status()
            
            result = response.json()
            
            if 'media_id' in result:
                media_id = result['media_id']
                media_url = result.get('url', 'N/A')
                print(f"Successfully uploaded permanent material!")
                print(f"Media ID: {media_id}")
                if media_url != 'N/A':
                    print(f"Media URL: {media_url}")
                
                # Cache the upload result for image and thumb types
                if media_type in ["image", "thumb"]:
                    self._save_image_upload(file_path, media_type, media_id, media_url)
                
                return {
                    'media_id': media_id,
                    'url': media_url,
                    'type': media_type,
                    'file_path': file_path,
                    'cached': False
                }
            else:
                error_code = result.get('errcode', 'unknown')
                error_msg = result.get('errmsg', 'unknown error')
                print(f"WeChat API error {error_code}: {error_msg}")
                return None
                
        except requests.exceptions.RequestException as e:
            print(f"Network error: {e}")
            return None
        except json.JSONDecodeError as e:
            print(f"JSON decode error: {e}")
            return None
        except Exception as e:
            print(f"Unexpected error: {e}")
            return None
    
    def upload_image_for_article(self, file_path: str) -> Optional[str]:
        """
        Upload image for article content (not permanent material, with caching)
        
        Args:
            file_path: Path to the image file (jpg/png, max 1MB)
            
        Returns:
            Image URL if successful, None if failed
        """
        # Check cache first
        cached_result = self._check_image_cache(file_path, "article")
        if cached_result:
            print(f"📱 Using cached article image: {cached_result['file_name']} -> {cached_result['media_url']}")
            return cached_result['media_url']
        
        # Check if file exists
        if not os.path.exists(file_path):
            print(f"Error: File not found: {file_path}")
            return None
        
        # Check file extension
        file_ext = os.path.splitext(file_path)[1].lower()
        if file_ext not in ['.jpg', '.jpeg', '.png', '.webp']:
            print("Error: Only jpg/png/webp formats are supported for article images")
            return None

        # Check file size (1MB limit for jpg/png, 2MB for webp)
        file_size = os.path.getsize(file_path)
        size_limit = 2 * 1024 * 1024 if file_ext == '.webp' else 1024 * 1024
        if file_size > size_limit:
            print(f"Error: File size {file_size} bytes exceeds {size_limit//1024//1024}MB limit")
            return None
        
        # Get access token
        access_token = self.get_access_token()
        if not access_token:
            print("Error: Could not get access token")
            return None
        
        # API endpoint
        url = f"https://api.weixin.qq.com/cgi-bin/media/uploadimg?access_token={access_token}"
        
        try:
            print(f"Uploading article image: {file_path}")
            
            # Prepare files for upload
            with open(file_path, 'rb') as f:
                # Determine MIME type based on file extension
                if file_ext in ['.jpg', '.jpeg']:
                    mime_type = 'image/jpeg'
                elif file_ext == '.png':
                    mime_type = 'image/png'
                elif file_ext == '.webp':
                    mime_type = 'image/webp'
                else:
                    mime_type = 'application/octet-stream'

                files = {'media': (os.path.basename(file_path), f, mime_type)}
                
                # Make request
                response = requests.post(url, files=files, timeout=30)
                response.raise_for_status()
            
            result = response.json()
            
            if 'url' in result and result.get('errcode', 0) == 0:
                image_url = result['url']
                print(f"Successfully uploaded article image!")
                print(f"Image URL: {image_url}")
                
                # Cache the upload result
                self._save_image_upload(file_path, "article", None, image_url)
                
                return image_url
            else:
                error_code = result.get('errcode', 'unknown')
                error_msg = result.get('errmsg', 'unknown error')
                print(f"WeChat API error {error_code}: {error_msg}")
                return None
                
        except requests.exceptions.RequestException as e:
            print(f"Network error: {e}")
            return None
        except json.JSONDecodeError as e:
            print(f"JSON decode error: {e}")
            return None
        except Exception as e:
            print(f"Unexpected error: {e}")
            return None

    def format_draft_list(self, draft_data: Dict, show_content: bool = False) -> str:
        """
        Format draft list data into readable string
        
        Args:
            draft_data: Draft list data from get_draft_list()
            show_content: Whether to show article content (for brief view)
            
        Returns:
            Formatted string representation of draft list
        """
        if not draft_data or 'item' not in draft_data:
            return "No draft data available"
        
        output = []
        output.append(f"=== Draft List Summary ===")
        output.append(f"Total Count: {draft_data.get('total_count', 0)}")
        output.append(f"Returned Count: {draft_data.get('item_count', 0)}")
        output.append("")
        
        for i, item in enumerate(draft_data.get('item', []), 1):
            media_id = item.get('media_id', 'N/A')
            update_time = item.get('update_time', 0)
            
            # Convert timestamp to readable date
            if update_time:
                from datetime import datetime
                update_date = datetime.fromtimestamp(update_time).strftime('%Y-%m-%d %H:%M:%S')
            else:
                update_date = 'N/A'
            
            output.append(f"--- Draft {i} ---")
            output.append(f"Media ID: {media_id}")
            output.append(f"Update Time: {update_date}")
            
            # Process articles in the draft
            content = item.get('content', {})
            news_items = content.get('news_item', [])
            
            if news_items:
                output.append(f"Articles: {len(news_items)}")
                for j, article in enumerate(news_items, 1):
                    article_type = article.get('article_type', 'news')
                    title = article.get('title', 'No title')
                    author = article.get('author', 'Unknown')
                    digest = article.get('digest', '')
                    
                    output.append(f"  Article {j}: [{article_type}] {title}")
                    output.append(f"    Author: {author}")
                    if digest:
                        output.append(f"    Digest: {digest}")
                    
                    if show_content and 'content' in article:
                        content_preview = article['content'][:100] + '...' if len(article['content']) > 100 else article['content']
                        output.append(f"    Content: {content_preview}")
                    
                    if 'url' in article:
                        output.append(f"    Preview URL: {article['url']}")
            else:
                output.append("Articles: 0")
            
            output.append("")
        
        return "\n".join(output)

def main():
    # Your WeChat app credentials
    APPID = "wx910e368754a621bd"
    SECRET = "f2ae6909464b6d0ad166781fb213ddf6"
    
    # Create WeChat client with database storage
    wechat = WeChatAccessToken(APPID, SECRET)
    
    # Display current database status
    print("\n" + "="*50)
    print("WeChat Access Token Tool with SQLite Storage")
    print("="*50)
    
    # Show all tokens in database
    all_tokens = wechat.get_all_tokens_info()
    if all_tokens:
        print(f"\nTokens in database ({len(all_tokens)}):")
        for token in all_tokens:
            status = "✓ Valid" if token['is_valid'] else "✗ Expired"
            print(f"  {token['appid']}: {token['access_token']} - {status}")
        print()
    
    # Clean up expired tokens
    wechat.clear_expired_tokens()
    
    # Get access token (will check database first)
    print("\n" + "-"*30)
    print("Getting access token...")
    token = wechat.get_access_token()
    
    if token:
        print("\n" + "="*50)
        print("SUCCESS: Access token retrieved!")
        print("="*50)
        
        # Display token info
        info = wechat.get_token_info()
        print(f"Access Token: {info['access_token']}")
        print(f"Expires At: {info['expires_at']}")
        print(f"Valid: {info['is_valid']}")
        print(f"Remaining: {int(info['remaining_seconds'])} seconds")
        print(f"Database: {info['db_path']}")
        
        # Test draft list functionality
        print("\n" + "="*50)
        print("Testing Draft List Functionality")
        print("="*50)
        
        # Get draft list without content
        print("\n1. Getting draft list (no content)...")
        draft_data = wechat.get_draft_list(offset=0, count=10, no_content=1)
        if draft_data:
            print("Draft list retrieved successfully!")
            formatted = wechat.format_draft_list(draft_data, show_content=False)
            print(formatted)
        else:
            print("No drafts found or error occurred")
        
        # Get draft list with content (if drafts exist)
        if draft_data and draft_data.get('total_count', 0) > 0:
            print("\n2. Getting draft list (with content)...")
            draft_data_full = wechat.get_draft_list(offset=0, count=3, no_content=0)
            if draft_data_full:
                formatted_full = wechat.format_draft_list(draft_data_full, show_content=True)
                print(formatted_full)
        
        # Test token caching
        print("\n" + "-"*30)
        print("Testing database cache...")
        token2 = wechat.get_access_token()
        print(f"Same token: {token == token2}")
        
    else:
        print("FAILED: Could not retrieve access token")


# Usage examples:
"""
# Basic usage with database storage:
from wechat_access_token import WeChatAccessToken

wechat = WeChatAccessToken("your_appid", "your_secret")
token = wechat.get_access_token()  # Automatically checks database first

# Get draft list:
draft_data = wechat.get_draft_list(offset=0, count=10, no_content=1)
if draft_data:
    formatted_output = wechat.format_draft_list(draft_data)
    print(formatted_output)

# Get draft list with full content:
draft_full = wechat.get_draft_list(offset=0, count=5, no_content=0)

# Custom database path:
wechat = WeChatAccessToken("your_appid", "your_secret", "custom_path.db")

# Check token status:
if wechat.is_token_valid():
    print("Token is valid")

# Get token info:
info = wechat.get_token_info()
print(f"Token expires in {info['remaining_seconds']} seconds")

# Force refresh token (bypass database cache):
new_token = wechat.get_access_token(force_refresh=True)

# Database management:
wechat.clear_expired_tokens()  # Remove expired tokens
all_tokens = wechat.get_all_tokens_info()  # View all tokens
"""

if __name__ == "__main__":
    main()