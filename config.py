#!/usr/bin/env python3
"""
Configuration loader for WeChat tools
Supports both JSON config files and environment variables
"""

import json
import os
from typing import Dict, Optional

class Config:
    def __init__(self, config_path: str = "config.json"):
        self.config_path = config_path
        self._config_data = {}
        self.load_config()
    
    def load_config(self):
        """Load configuration from JSON file"""
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    self._config_data = json.load(f)
                print(f"Configuration loaded from {self.config_path}")
            else:
                print(f"Configuration file {self.config_path} not found")
        except Exception as e:
            print(f"Error loading configuration: {e}")
    
    def get_wechat_config(self) -> Dict[str, str]:
        """Get WeChat configuration (appid and appsec)"""
        # First try to get from JSON config
        wechat_config = self._config_data.get('wechat', {})
        
        # Override with environment variables if they exist
        appid = os.getenv('WECHAT_APPID', wechat_config.get('appid'))
        appsec = os.getenv('WECHAT_APPSEC', wechat_config.get('appsec'))
        
        if not appid or not appsec:
            raise ValueError("WeChat appid and appsec must be configured")
        
        return {
            'appid': appid,
            'appsec': appsec
        }
    
    def get(self, key: str, default=None):
        """Get configuration value by key"""
        keys = key.split('.')
        data = self._config_data
        
        for k in keys:
            if isinstance(data, dict) and k in data:
                data = data[k]
            else:
                return default
        
        return data

# Example usage
if __name__ == "__main__":
    config = Config()
    
    try:
        wechat_config = config.get_wechat_config()
        print(f"AppID: {wechat_config['appid']}")
        print(f"AppSec: {'*' * len(wechat_config['appsec'])}")  # Hide secret
    except ValueError as e:
        print(f"Configuration error: {e}")