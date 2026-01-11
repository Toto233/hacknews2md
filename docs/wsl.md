# WSL 环境下的浏览器控制与网页抓取指南

> 本文档总结了在 WSL (Windows Subsystem for Linux) 环境下控制浏览器、抓取网页内容的完整知识和实践经验，可用于 Node.js 项目移植参考。

## 目录

- [环境检测](#环境检测)
- [浏览器控制方案](#浏览器控制方案)
- [路径转换](#路径转换)
- [Python 实现](#python-实现)
- [Node.js 移植指南](#nodejs-移植指南)
- [常见问题与解决方案](#常见问题与解决方案)

---

## 环境检测

### 检测是否在 WSL 环境中

**Python 实现：**
```python
def _detect_wsl() -> bool:
    """检测是否在 WSL 环境中运行"""
    try:
        with open('/proc/version', 'r') as f:
            content = f.read().lower()
            return 'microsoft' in content or 'wsl' in content
    except:
        return False
```

**Node.js 实现：**
```javascript
const fs = require('fs');

function detectWSL() {
    try {
        const procVersion = fs.readFileSync('/proc/version', 'utf8').toLowerCase();
        return procVersion.includes('microsoft') || procVersion.includes('wsl');
    } catch {
        return false;
    }
}
```

**Shell 命令：**
```bash
# 方法 1: 检查 /proc/version
cat /proc/version | grep -i microsoft

# 方法 2: 检查 WSL 环境变量
echo $WSL_DISTRO_NAME

# 方法 3: 使用 uname
uname -r | grep -i microsoft
```

---

## 浏览器控制方案

### 方案对比

| 方案 | 优点 | 缺点 | 用途 | WSL 支持 |
|------|------|------|------|----------|
| **直接调用 Windows 浏览器** | 简单、用户可见 | 功能有限、不能读取内容 | 展示 HTML 内容 | ✅ 完美 |
| **Playwright (无头)** | 快速、功能强大 | 用户看不到 | 自动化抓取 | ✅ 完美 |
| **Playwright (有头)** | 可见、可调试 | 需要 X Server | 调试测试 | ⚠️ 需配置 |
| **Selenium** | 成熟、兼容性好 | 较慢 | 自动化测试 | ✅ 支持 |
| **Puppeteer** | 轻量、Node.js 原生 | 仅支持 Chrome | Node.js 项目 | ✅ 完美 |

### 1. 直接调用 Windows 浏览器

**适用场景：** 在用户的 Windows 浏览器中显示 HTML 内容

**Python 实现：**
```python
import subprocess
import os

def find_windows_browser():
    """查找 Windows 浏览器路径"""
    browsers = [
        '/mnt/c/Program Files/Google/Chrome/Application/chrome.exe',
        '/mnt/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
        '/mnt/c/Program Files/Mozilla Firefox/firefox.exe',
    ]
    for browser in browsers:
        if os.path.exists(browser):
            return browser
    return None

def open_in_windows_browser(html_file_path):
    """在 Windows 浏览器中打开 HTML 文件"""
    browser = find_windows_browser()
    if browser:
        # 转换路径
        windows_path = convert_to_windows_path(html_file_path)
        # 启动浏览器
        subprocess.Popen(
            [browser, f'file:///{windows_path}'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
```

**Node.js 实现：**
```javascript
const { spawn } = require('child_process');
const fs = require('fs');
const { execSync } = require('child_process');

function findWindowsBrowser() {
    const browsers = [
        '/mnt/c/Program Files/Google/Chrome/Application/chrome.exe',
        '/mnt/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
        '/mnt/c/Program Files/Mozilla Firefox/firefox.exe',
    ];

    for (const browser of browsers) {
        if (fs.existsSync(browser)) {
            return browser;
        }
    }
    return null;
}

function openInWindowsBrowser(htmlFilePath) {
    const browser = findWindowsBrowser();
    if (!browser) {
        throw new Error('No Windows browser found');
    }

    // 转换路径
    const windowsPath = convertToWindowsPath(htmlFilePath);

    // 启动浏览器
    spawn(browser, [`file:///${windowsPath}`], {
        detached: true,
        stdio: 'ignore'
    }).unref();
}
```

### 2. Playwright (推荐用于自动化)

**安装：**
```bash
# Python
pip install playwright
python -m playwright install chromium

# Node.js
npm install playwright
npx playwright install chromium
```

**Python 示例：**
```python
from playwright.async_api import async_playwright

async def scrape_website(url):
    async with async_playwright() as p:
        # 启动浏览器（无头模式）
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        # 访问页面
        await page.goto(url)

        # 获取内容
        title = await page.title()
        content = await page.content()

        # 截图
        await page.screenshot(path='screenshot.png')

        # 提取特定元素
        headlines = await page.locator('h1').all_text_contents()

        await browser.close()

        return {
            'title': title,
            'content': content,
            'headlines': headlines
        }
```

**Node.js 示例：**
```javascript
const { chromium } = require('playwright');

async function scrapeWebsite(url) {
    // 启动浏览器
    const browser = await chromium.launch({ headless: true });
    const page = await browser.newPage();

    // 访问页面
    await page.goto(url);

    // 获取内容
    const title = await page.title();
    const content = await page.content();

    // 截图
    await page.screenshot({ path: 'screenshot.png' });

    // 提取特定元素
    const headlines = await page.locator('h1').allTextContents();

    await browser.close();

    return {
        title,
        content,
        headlines
    };
}
```

### 3. Puppeteer (Node.js 原生)

**安装：**
```bash
npm install puppeteer
```

**Node.js 示例：**
```javascript
const puppeteer = require('puppeteer');

async function scrapeWithPuppeteer(url) {
    const browser = await puppeteer.launch({
        headless: true,
        args: ['--no-sandbox', '--disable-setuid-sandbox'] // WSL 需要
    });

    const page = await browser.newPage();
    await page.goto(url, { waitUntil: 'networkidle2' });

    // 获取内容
    const title = await page.title();

    // 执行 JavaScript
    const data = await page.evaluate(() => {
        const headlines = Array.from(document.querySelectorAll('h1'))
            .map(h => h.textContent);
        return { headlines };
    });

    // 截图
    await page.screenshot({ path: 'screenshot.png', fullPage: true });

    await browser.close();

    return { title, ...data };
}
```

---

## 路径转换

### WSL 路径与 Windows 路径转换

**关键概念：**
- WSL 路径：`/tmp/test.html`
- Windows 路径：`\\wsl.localhost\Ubuntu-22.04\tmp\test.html`
- Windows 路径（正斜杠）：`//wsl.localhost/Ubuntu-22.04/tmp/test.html`

### 使用 wslpath 工具

**Python 实现：**
```python
import subprocess

def convert_to_windows_path(wsl_path):
    """将 WSL 路径转换为 Windows 路径"""
    try:
        result = subprocess.run(
            ['wslpath', '-w', wsl_path],
            capture_output=True,
            text=True,
            check=True
        )
        windows_path = result.stdout.strip()
        # 转换为正斜杠（浏览器友好）
        windows_path = windows_path.replace('\\', '/')
        return windows_path
    except:
        return wsl_path

def convert_to_wsl_path(windows_path):
    """将 Windows 路径转换为 WSL 路径"""
    try:
        result = subprocess.run(
            ['wslpath', '-u', windows_path],
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip()
    except:
        return windows_path
```

**Node.js 实现：**
```javascript
const { execSync } = require('child_process');

function convertToWindowsPath(wslPath) {
    try {
        const windowsPath = execSync(`wslpath -w "${wslPath}"`)
            .toString()
            .trim()
            .replace(/\\/g, '/'); // 转换为正斜杠
        return windowsPath;
    } catch {
        return wslPath;
    }
}

function convertToWSLPath(windowsPath) {
    try {
        return execSync(`wslpath -u "${windowsPath}"`)
            .toString()
            .trim();
    } catch {
        return windowsPath;
    }
}
```

**手动转换规则：**
```javascript
function manualConvertToWindowsPath(wslPath) {
    // /mnt/c/... -> C:/...
    if (wslPath.startsWith('/mnt/')) {
        const drive = wslPath.charAt(5).toUpperCase();
        const rest = wslPath.substring(7);
        return `${drive}:/${rest}`;
    }

    // /tmp/... -> //wsl.localhost/{distro}/tmp/...
    // 需要知道发行版名称
    const distro = process.env.WSL_DISTRO_NAME || 'Ubuntu-22.04';
    return `//wsl.localhost/${distro}${wslPath}`;
}
```

---

## Python 实现

### 完整的浏览器管理类

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""浏览器管理器 - 支持 WSL"""

import webbrowser
import tempfile
import os
import subprocess
import platform
from typing import Optional

class BrowserManager:
    """浏览器管理器"""

    def __init__(self):
        self.system = platform.system().lower()
        self.is_wsl = self._detect_wsl()
        self.temp_file_path = None

    def _detect_wsl(self) -> bool:
        """检测是否在 WSL 环境中"""
        try:
            with open('/proc/version', 'r') as f:
                return 'microsoft' in f.read().lower()
        except:
            return False

    def _find_windows_browser(self) -> Optional[str]:
        """查找 Windows 浏览器"""
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
        """转换路径"""
        try:
            result = subprocess.run(['wslpath', '-w', wsl_path],
                                  capture_output=True, text=True, check=True)
            return result.stdout.strip().replace('\\', '/')
        except:
            return wsl_path

    def open_html(self, html_content: str, auto_close: bool = False,
                  close_delay: int = 10) -> str:
        """在浏览器中打开 HTML 内容"""
        # 创建临时文件
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.html', delete=False, encoding='utf-8'
        ) as f:
            f.write(html_content)
            self.temp_file_path = f.name

        # 打开浏览器
        if self.is_wsl:
            browser_path = self._find_windows_browser()
            if browser_path:
                windows_path = self._convert_to_windows_path(self.temp_file_path)
                subprocess.Popen(
                    [browser_path, f'file:///{windows_path}'],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            else:
                webbrowser.open(f'file://{self.temp_file_path}')
        else:
            webbrowser.open(f'file://{self.temp_file_path}')

        if auto_close:
            import time
            time.sleep(close_delay)
            self.cleanup()

        return self.temp_file_path

    def cleanup(self):
        """清理临时文件"""
        if self.temp_file_path and os.path.exists(self.temp_file_path):
            try:
                os.unlink(self.temp_file_path)
                self.temp_file_path = None
            except:
                pass
```

### 网页抓取示例

```python
from playwright.async_api import async_playwright
import asyncio

async def scrape_hacker_news():
    """抓取 Hacker News"""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        await page.goto('https://news.ycombinator.com/')

        # 获取新闻列表
        news_items = await page.locator('.athing').all()

        results = []
        for item in news_items[:10]:
            title_elem = item.locator('.titleline > a')
            title = await title_elem.text_content()
            link = await title_elem.get_attribute('href')

            results.append({
                'title': title,
                'link': link
            })

        await browser.close()
        return results

# 运行
results = asyncio.run(scrape_hacker_news())
for i, item in enumerate(results, 1):
    print(f"{i}. {item['title']}")
    print(f"   {item['link']}\n")
```

---

## Node.js 移植指南

### 1. 项目设置

**package.json：**
```json
{
  "name": "wsl-browser-automation",
  "version": "1.0.0",
  "dependencies": {
    "playwright": "^1.40.0",
    "puppeteer": "^21.0.0"
  }
}
```

**安装：**
```bash
npm install
npx playwright install chromium
```

### 2. 浏览器管理类 (Node.js)

```javascript
const fs = require('fs');
const path = require('path');
const os = require('os');
const { spawn, execSync } = require('child_process');

class BrowserManager {
    constructor() {
        this.system = os.platform();
        this.isWSL = this.detectWSL();
        this.tempFilePath = null;
    }

    detectWSL() {
        try {
            const procVersion = fs.readFileSync('/proc/version', 'utf8').toLowerCase();
            return procVersion.includes('microsoft') || procVersion.includes('wsl');
        } catch {
            return false;
        }
    }

    findWindowsBrowser() {
        const browsers = [
            '/mnt/c/Program Files/Google/Chrome/Application/chrome.exe',
            '/mnt/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
            '/mnt/c/Program Files/Mozilla Firefox/firefox.exe',
        ];

        for (const browser of browsers) {
            if (fs.existsSync(browser)) {
                return browser;
            }
        }
        return null;
    }

    convertToWindowsPath(wslPath) {
        try {
            const windowsPath = execSync(`wslpath -w "${wslPath}"`)
                .toString()
                .trim()
                .replace(/\\/g, '/');
            return windowsPath;
        } catch {
            return wslPath;
        }
    }

    openHTML(htmlContent, options = {}) {
        const { autoClose = false, closeDelay = 10 } = options;

        // 创建临时文件
        this.tempFilePath = path.join(os.tmpdir(), `browser_${Date.now()}.html`);
        fs.writeFileSync(this.tempFilePath, htmlContent, 'utf8');

        // 打开浏览器
        if (this.isWSL) {
            const browserPath = this.findWindowsBrowser();
            if (browserPath) {
                const windowsPath = this.convertToWindowsPath(this.tempFilePath);
                spawn(browserPath, [`file:///${windowsPath}`], {
                    detached: true,
                    stdio: 'ignore'
                }).unref();
            }
        } else {
            // 非 WSL 环境
            const open = require('open');
            open(this.tempFilePath);
        }

        if (autoClose) {
            setTimeout(() => {
                this.cleanup();
            }, closeDelay * 1000);
        }

        return this.tempFilePath;
    }

    cleanup() {
        if (this.tempFilePath && fs.existsSync(this.tempFilePath)) {
            try {
                fs.unlinkSync(this.tempFilePath);
                this.tempFilePath = null;
            } catch {}
        }
    }
}

module.exports = BrowserManager;
```

### 3. 网页抓取 (Node.js + Playwright)

```javascript
const { chromium } = require('playwright');

async function scrapeHackerNews() {
    const browser = await chromium.launch({ headless: true });
    const page = await browser.newPage();

    await page.goto('https://news.ycombinator.com/');

    // 获取新闻列表
    const newsItems = await page.locator('.athing').all();

    const results = [];
    for (const item of newsItems.slice(0, 10)) {
        const titleElem = item.locator('.titleline > a');
        const title = await titleElem.textContent();
        const link = await titleElem.getAttribute('href');

        results.push({ title, link });
    }

    await browser.close();
    return results;
}

// 使用
(async () => {
    const results = await scrapeHackerNews();
    results.forEach((item, i) => {
        console.log(`${i + 1}. ${item.title}`);
        console.log(`   ${item.link}\n`);
    });
})();
```

### 4. 使用 Puppeteer (替代方案)

```javascript
const puppeteer = require('puppeteer');

async function scrapeWithPuppeteer(url) {
    const browser = await puppeteer.launch({
        headless: true,
        args: ['--no-sandbox', '--disable-setuid-sandbox'] // WSL 必需
    });

    const page = await browser.newPage();
    await page.goto(url, { waitUntil: 'networkidle2' });

    // 提取数据
    const data = await page.evaluate(() => {
        const items = Array.from(document.querySelectorAll('.athing'));
        return items.slice(0, 10).map(item => {
            const titleElem = item.querySelector('.titleline > a');
            return {
                title: titleElem?.textContent || '',
                link: titleElem?.href || ''
            };
        });
    });

    await browser.close();
    return data;
}
```

---

## 常见问题与解决方案

### 1. Playwright 无法启动浏览器

**问题：**
```
BrowserType.launch: Executable doesn't exist
```

**解决方案：**
```bash
# 安装浏览器
python -m playwright install chromium
# 或
npx playwright install chromium

# 安装依赖
python -m playwright install-deps
```

### 2. WSL 中 Playwright 无法显示窗口

**问题：** 无头模式正常，有头模式报错

**解决方案：**
```javascript
// 使用无头模式
const browser = await chromium.launch({ headless: true });

// 或者安装 X Server (如 VcXsrv)
// 然后设置 DISPLAY 环境变量
process.env.DISPLAY = ':0';
```

### 3. 路径转换失败

**问题：** `wslpath` 命令不存在或转换错误

**解决方案：**
```javascript
// 手动转换
function convertPath(wslPath) {
    if (wslPath.startsWith('/mnt/')) {
        // /mnt/c/... -> C:/...
        const drive = wslPath.charAt(5).toUpperCase();
        const rest = wslPath.substring(7);
        return `${drive}:/${rest}`;
    }

    // 其他路径使用 wslpath
    try {
        return execSync(`wslpath -w "${wslPath}"`).toString().trim();
    } catch {
        return wslPath;
    }
}
```

### 4. 浏览器进程无法关闭

**问题：** 打开的浏览器无法通过脚本关闭

**解决方案：**

**Linux/WSL:**
```bash
# 通过进程名关闭
pkill chrome
pkill firefox

# Python
subprocess.run(['pkill', 'chrome'], check=False)

# Node.js
execSync('pkill chrome');
```

**Windows (从 WSL 调用):**
```bash
# 使用 Windows taskkill
/mnt/c/Windows/System32/taskkill.exe /F /IM chrome.exe

# Python
subprocess.run(['/mnt/c/Windows/System32/taskkill.exe', '/F', '/IM', 'chrome.exe'])

# Node.js
execSync('/mnt/c/Windows/System32/taskkill.exe /F /IM chrome.exe');
```

### 5. 权限问题

**问题：** `EACCES: permission denied`

**解决方案：**
```bash
# 给文件添加执行权限
chmod +x /path/to/file

# Puppeteer 需要的参数
const browser = await puppeteer.launch({
    args: ['--no-sandbox', '--disable-setuid-sandbox']
});
```

### 6. 截图中文乱码

**问题：** 截图中的中文显示为方块

**解决方案：**
```bash
# 安装中文字体
sudo apt-get install fonts-wqy-zenhei fonts-wqy-microhei

# 或在 Playwright 中指定字体
await page.addStyleTag({
    content: `* { font-family: "Microsoft YaHei", sans-serif !important; }`
});
```

---

## 实用代码片段

### 1. 完整的 Node.js 示例

**index.js:**
```javascript
const BrowserManager = require('./browser-manager');
const { chromium } = require('playwright');

async function main() {
    // 1. 后台抓取数据
    console.log('抓取 Hacker News...');
    const browser = await chromium.launch({ headless: true });
    const page = await browser.newPage();
    await page.goto('https://news.ycombinator.com/');

    const newsItems = await page.locator('.athing').all();
    const news = [];

    for (const item of newsItems.slice(0, 5)) {
        const titleElem = item.locator('.titleline > a');
        const title = await titleElem.textContent();
        const link = await titleElem.getAttribute('href');
        news.push({ title, link });
    }

    await browser.close();

    // 2. 生成 HTML 展示结果
    const html = `
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>Hacker News</title>
        <style>
            body { font-family: Arial; padding: 40px; }
            h1 { color: #ff6600; }
            .item { margin: 20px 0; }
            a { color: #000; text-decoration: none; }
            a:hover { text-decoration: underline; }
        </style>
    </head>
    <body>
        <h1>Hacker News Top 5</h1>
        ${news.map((item, i) => `
            <div class="item">
                <strong>${i + 1}.</strong>
                <a href="${item.link}" target="_blank">${item.title}</a>
            </div>
        `).join('')}
    </body>
    </html>
    `;

    // 3. 在 Windows 浏览器中显示
    const manager = new BrowserManager();
    manager.openHTML(html, { autoClose: false });

    console.log('结果已在浏览器中打开！');
}

main().catch(console.error);
```

### 2. 截图并保存

```javascript
const { chromium } = require('playwright');
const BrowserManager = require('./browser-manager');

async function screenshotAndShow(url) {
    // 访问并截图
    const browser = await chromium.launch({ headless: true });
    const page = await browser.newPage();
    await page.goto(url);

    const screenshotPath = '/tmp/screenshot.png';
    await page.screenshot({
        path: screenshotPath,
        fullPage: true
    });

    await browser.close();

    // 在浏览器中显示截图
    const html = `
    <!DOCTYPE html>
    <html>
    <head><title>Screenshot</title></head>
    <body style="margin:0; padding:20px;">
        <h1>Screenshot of ${url}</h1>
        <img src="file://${screenshotPath}" style="max-width:100%;">
    </body>
    </html>
    `;

    const manager = new BrowserManager();
    manager.openHTML(html);
}
```

### 3. 批量抓取并生成报告

```javascript
const { chromium } = require('playwright');

async function batchScrape(urls) {
    const browser = await chromium.launch({ headless: true });
    const results = [];

    for (const url of urls) {
        const page = await browser.newPage();
        try {
            await page.goto(url, { timeout: 30000 });

            const title = await page.title();
            const description = await page.locator('meta[name="description"]')
                .getAttribute('content')
                .catch(() => 'No description');

            results.push({ url, title, description });
        } catch (error) {
            results.push({ url, error: error.message });
        }
        await page.close();
    }

    await browser.close();
    return results;
}

// 使用
const urls = [
    'https://news.ycombinator.com/',
    'https://github.com/trending',
    'https://www.producthunt.com/'
];

batchScrape(urls).then(results => {
    console.log(JSON.stringify(results, null, 2));
});
```

---

## 性能优化建议

### 1. 复用浏览器实例

```javascript
class ScraperPool {
    constructor(poolSize = 3) {
        this.poolSize = poolSize;
        this.browsers = [];
    }

    async init() {
        for (let i = 0; i < this.poolSize; i++) {
            const browser = await chromium.launch({ headless: true });
            this.browsers.push(browser);
        }
    }

    async scrape(url) {
        const browser = this.browsers.shift();
        const page = await browser.newPage();

        try {
            await page.goto(url);
            const data = await page.content();
            return data;
        } finally {
            await page.close();
            this.browsers.push(browser);
        }
    }

    async close() {
        await Promise.all(this.browsers.map(b => b.close()));
    }
}
```

### 2. 并发抓取

```javascript
const pLimit = require('p-limit');

async function concurrentScrape(urls, concurrency = 3) {
    const limit = pLimit(concurrency);
    const browser = await chromium.launch({ headless: true });

    const tasks = urls.map(url => limit(async () => {
        const page = await browser.newPage();
        try {
            await page.goto(url);
            return await page.content();
        } finally {
            await page.close();
        }
    }));

    const results = await Promise.all(tasks);
    await browser.close();

    return results;
}
```

---

## 总结

### 关键要点

1. **环境检测是必需的** - 始终检测是否在 WSL 环境中
2. **路径转换很重要** - 使用 `wslpath` 或手动转换
3. **无头模式更稳定** - WSL 中推荐使用无头浏览器
4. **权限问题常见** - Puppeteer 需要添加 `--no-sandbox` 参数
5. **浏览器选择**：
   - Playwright - 功能最强，跨浏览器支持
   - Puppeteer - Node.js 最佳，仅 Chrome
   - 直接调用 - 展示用，功能有限

### 推荐架构

```
Node.js 项目
├── browser-manager.js      # 浏览器管理（展示用）
├── scraper.js              # 网页抓取（Playwright/Puppeteer）
├── utils/
│   ├── wsl-detect.js       # WSL 检测
│   ├── path-convert.js     # 路径转换
│   └── browser-pool.js     # 浏览器池（性能优化）
└── examples/
    ├── scrape-and-show.js  # 抓取并展示
    ├── screenshot.js       # 截图功能
    └── batch-scrape.js     # 批量抓取
```

---

## 参考资源

- [Playwright 官方文档](https://playwright.dev/)
- [Puppeteer 官方文档](https://pptr.dev/)
- [WSL 文档](https://docs.microsoft.com/en-us/windows/wsl/)
- [wslpath 命令手册](https://manpages.ubuntu.com/manpages/focal/man1/wslpath.1.html)

---

*本文档基于实践经验总结，适用于 WSL2 + Ubuntu 22.04 环境*
*最后更新: 2026-01-08*
