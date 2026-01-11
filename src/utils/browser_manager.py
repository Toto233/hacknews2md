#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
浏览器管理模块
提供HTML文件在浏览器中显示和管理的功能
"""

import webbrowser
import tempfile
import os
import time
import subprocess
import platform
from typing import Optional


class BrowserManager:
    """浏览器管理器"""
    
    def __init__(self):
        """初始化浏览器管理器"""
        self.system = platform.system().lower()
        self.temp_file_path: Optional[str] = None
        self.browser_process: Optional[subprocess.Popen] = None
        self.is_wsl = self._detect_wsl()

    def _detect_wsl(self) -> bool:
        """检测是否在 WSL 环境中运行"""
        try:
            with open('/proc/version', 'r') as f:
                return 'microsoft' in f.read().lower() or 'wsl' in f.read().lower()
        except:
            return False

    def _find_windows_browser(self) -> Optional[str]:
        """在 WSL 环境中查找 Windows 浏览器"""
        browsers = [
            '/mnt/c/Program Files/Google/Chrome/Application/chrome.exe',
            '/mnt/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
            '/mnt/c/Program Files/Mozilla Firefox/firefox.exe',
        ]
        for browser in browsers:
            if os.path.exists(browser):
                return browser
        return None

    def _convert_to_windows_path(self, wsl_path: str) -> str:
        """将 WSL 路径转换为 Windows 路径（浏览器可访问格式）"""
        try:
            result = subprocess.run(['wslpath', '-w', wsl_path],
                                  capture_output=True, text=True, check=True)
            windows_path = result.stdout.strip()
            # 将反斜杠转换为正斜杠，浏览器更容易处理
            windows_path = windows_path.replace('\\', '/')
            return windows_path
        except:
            return wsl_path

    def open_html_in_browser(self, html_content: str, auto_close: bool = True, close_delay: int = 10) -> str:
        """
        在浏览器中打开HTML内容
        
        Args:
            html_content: HTML内容
            auto_close: 是否自动关闭浏览器
            close_delay: 自动关闭延迟（秒）
            
        Returns:
            临时文件路径
        """
        # 创建临时HTML文件
        with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False, encoding='utf-8') as f:
            f.write(html_content)
            self.temp_file_path = f.name
        
        try:
            # 在浏览器中打开HTML文件
            print(f"正在浏览器中打开HTML文件...")

            # WSL 环境特殊处理
            if self.is_wsl:
                browser_path = self._find_windows_browser()
                if browser_path:
                    windows_path = self._convert_to_windows_path(self.temp_file_path)
                    print(f"检测到 WSL 环境，使用 Windows 浏览器")
                    # 直接使用 file:// 协议和转换后的路径
                    self.browser_process = subprocess.Popen(
                        [browser_path, f'file:///{windows_path}'],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL
                    )
                else:
                    print(f"未找到 Windows 浏览器，尝试使用默认方式...")
                    webbrowser.open(f'file://{self.temp_file_path}')
            else:
                webbrowser.open(f'file://{self.temp_file_path}')

            if auto_close:
                print(f"HTML已在浏览器中打开，{close_delay}秒后自动关闭...")
                time.sleep(close_delay)
                self.close_browser()
            else:
                print("HTML已在浏览器中打开，请复制内容后手动关闭浏览器")
                print("提示：复制HTML内容后，可以调用 close_browser() 方法关闭浏览器")
                
        except Exception as e:
            print(f"打开浏览器时出错: {e}")
            self.cleanup()
            
        return self.temp_file_path
    
    def close_browser(self):
        """关闭浏览器"""
        # WSL 环境下，调用 Windows 命令关闭浏览器
        if self.is_wsl:
            self._close_browser_wsl()
        elif self.system == "windows":
            self._close_browser_windows()
        elif self.system == "darwin":  # macOS
            self._close_browser_macos()
        else:  # Linux
            self._close_browser_linux()

        self.cleanup()

    def _close_browser_wsl(self):
        """在 WSL 环境下关闭 Windows 浏览器"""
        try:
            # 使用 Windows taskkill 命令
            browsers = ['chrome.exe', 'msedge.exe', 'firefox.exe']
            for browser in browsers:
                try:
                    subprocess.run(['/mnt/c/Windows/System32/taskkill.exe', '/f', '/im', browser],
                                 capture_output=True, check=False)
                except:
                    pass
            print("已尝试关闭浏览器进程")
        except Exception as e:
            print(f"关闭浏览器时出错: {e}")

    def _close_browser_windows(self):
        """在Windows上关闭浏览器"""
        try:
            # 尝试关闭常见的浏览器进程
            browsers = ['chrome.exe', 'msedge.exe', 'firefox.exe', 'iexplore.exe']
            for browser in browsers:
                try:
                    subprocess.run(['taskkill', '/f', '/im', browser], 
                                 capture_output=True, check=False)
                except:
                    pass
            print("已尝试关闭浏览器进程")
        except Exception as e:
            print(f"关闭浏览器时出错: {e}")
    
    def _close_browser_macos(self):
        """在macOS上关闭浏览器"""
        try:
            # 尝试关闭常见的浏览器应用
            browsers = ['Google Chrome', 'Safari', 'Firefox']
            for browser in browsers:
                try:
                    subprocess.run(['pkill', '-f', browser], 
                                 capture_output=True, check=False)
                except:
                    pass
            print("已尝试关闭浏览器进程")
        except Exception as e:
            print(f"关闭浏览器时出错: {e}")
    
    def _close_browser_linux(self):
        """在Linux上关闭浏览器"""
        try:
            # 尝试关闭常见的浏览器进程
            browsers = ['chrome', 'firefox', 'chromium']
            for browser in browsers:
                try:
                    subprocess.run(['pkill', '-f', browser], 
                                 capture_output=True, check=False)
                except:
                    pass
            print("已尝试关闭浏览器进程")
        except Exception as e:
            print(f"关闭浏览器时出错: {e}")
    
    def cleanup(self):
        """清理临时文件"""
        if self.temp_file_path and os.path.exists(self.temp_file_path):
            try:
                os.unlink(self.temp_file_path)
                self.temp_file_path = None
                print("临时文件已清理")
            except Exception as e:
                print(f"清理临时文件时出错: {e}")
    
    def __del__(self):
        """析构函数，确保清理资源"""
        self.cleanup()


def display_html_in_browser(html_content: str, auto_close: bool = True, close_delay: int = 10):
    """
    便捷函数：在浏览器中显示HTML内容
    
    Args:
        html_content: HTML内容
        auto_close: 是否自动关闭浏览器
        close_delay: 自动关闭延迟（秒）
    """
    manager = BrowserManager()
    manager.open_html_in_browser(html_content, auto_close, close_delay)
    
    if not auto_close:
        return manager  # 返回管理器实例，用户可以手动调用 close_browser()
    
    return None


if __name__ == "__main__":
    # 测试代码
    test_html = """<!DOCTYPE html>
<html>
<head>
    <title>测试页面</title>
    <style>
        body { font-family: Arial, sans-serif; padding: 20px; }
        h1 { color: #e74c3c; }
    </style>
</head>
<body>
    <h1>测试HTML页面</h1>
    <p>这是一个测试页面，用于验证浏览器管理功能。</p>
    <p>如果看到这个页面，说明浏览器管理功能正常工作。</p>
</body>
</html>"""
    
    print("测试浏览器管理功能...")
    manager = display_html_in_browser(test_html, auto_close=False, close_delay=5)
    
    if manager:
        input("按回车键关闭浏览器...")
        manager.close_browser()
