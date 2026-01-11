import json
import os

class ProxyConfig:
    """代理配置类，用于从配置文件加载和管理代理设置"""
    
    def __init__(self, config_path='config/config.json'):
        self.config_path = config_path
        self.proxies = None
        self.load_config()
    
    def load_config(self):
        """从配置文件加载代理设置"""
        try:
            if not os.path.exists(self.config_path):
                print(f"配置文件 {self.config_path} 不存在")
                return None
                
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                proxy_config = config.get('proxy', {})
                proxy_enabled = proxy_config.get('enabled', False)
                
                # 设置代理
                if proxy_enabled:
                    proxy_type = proxy_config.get('type', 'socks5')
                    proxy_host = proxy_config.get('host', '127.0.0.1')
                    proxy_port = proxy_config.get('port', 18080)
                    proxy_username = proxy_config.get('username', '')
                    proxy_password = proxy_config.get('password', '')
                    
                    # 构建代理URL
                    if proxy_username and proxy_password:
                        proxy_url = f"{proxy_type}://{proxy_username}:{proxy_password}@{proxy_host}:{proxy_port}"
                    else:
                        proxy_url = f"{proxy_type}://{proxy_host}:{proxy_port}"
                    
                    self.proxies = {
                        'http': proxy_url,
                        'https': proxy_url
                    }
                    print(f"使用代理: {proxy_type} {proxy_host}:{proxy_port}")
                else:
                    self.proxies = None
                    print("代理未启用")
        except Exception as e:
            print(f"加载代理配置失败: {e}")
            self.proxies = None
    
    def get_proxies(self):
        """获取代理设置"""
        return self.proxies