# WSL Browser Automation - MCP Server 配置指南

## 🎯 概述

我已经为你创建了一个完整的 **MCP (Model Context Protocol) 服务器**，它可以作为 Claude Code 的能力扩展，提供 WSL 环境下的浏览器自动化和网页抓取功能。

## 📦 已创建的文件

```
/mnt/d/python/hacknews/mcp-server-wsl-browser/
├── package.json                    # 项目配置
├── index.js                        # MCP 服务器主文件
├── README.md                       # 详细文档
├── examples.js                     # 使用示例
├── test-server.js                  # 测试工具
└── claude_mcp_config.json          # Claude 配置示例
```

## 🚀 快速开始

### 1. 安装依赖（已完成）

```bash
cd /mnt/d/python/hacknews/mcp-server-wsl-browser
npm install
npx playwright install chromium
```

### 2. 测试功能

```bash
# 运行示例
node examples.js

# 这将：
# - 抓取 Hacker News 前 5 条新闻
# - 在你的 Windows 浏览器中显示演示页面
# - 截图 GitHub Trending 页面
```

### 3. 配置 Claude Code

有两种配置方式：

#### 方式A: 全局配置（推荐）

创建或编辑 `~/.config/Claude/claude_desktop_config.json`：

```json
{
  "mcpServers": {
    "wsl-browser": {
      "command": "node",
      "args": [
        "/mnt/d/python/hacknews/mcp-server-wsl-browser/index.js"
      ]
    }
  }
}
```

#### 方式B: 项目配置

在你的项目中添加 `.claude/mcp_config.json`：

```json
{
  "mcpServers": {
    "wsl-browser": {
      "command": "node",
      "args": [
        "/mnt/d/python/hacknews/mcp-server-wsl-browser/index.js"
      ]
    }
  }
}
```

### 4. 重启 Claude Code

配置完成后，重启 Claude Code 以加载 MCP 服务器。

## 🛠️ 可用工具

配置完成后，Claude Code 将自动获得以下5个新工具：

### 1. `scrape_webpage`
抓取任何网页的内容

```json
{
  "url": "https://example.com",
  "selector": "h1",          // 可选：提取特定元素
  "screenshot": true         // 可选：是否截图
}
```

### 2. `show_in_browser`
在 Windows 浏览器中显示 HTML 内容

```json
{
  "html": "<h1>Hello World</h1>",
  "title": "My Page"         // 可选：页面标题
}
```

### 3. `screenshot_webpage`
截图网页

```json
{
  "url": "https://example.com",
  "fullPage": true,          // 全页面截图
  "showInBrowser": false     // 是否在浏览器中显示截图
}
```

### 4. `scrape_hacker_news`
快速获取 Hacker News 热门新闻

```json
{
  "limit": 10               // 获取前10条新闻
}
```

### 5. `scrape_github_trending`
获取 GitHub Trending 仓库

```json
{
  "language": "python",      // 编程语言
  "since": "daily",          // daily/weekly/monthly
  "limit": 10               // 数量
}
```

## 💬 使用示例

配置完成后，你可以在 Claude Code 对话中直接使用：

### 示例 1: 抓取网页
```
User: 帮我抓取 python.org 的首页内容
Claude: [自动调用 scrape_webpage 工具]
       好的，我已经抓取了 python.org 的内容...
```

### 示例 2: 显示结果
```
User: 把这个 HTML 在我的浏览器中显示：<h1>测试</h1>
Claude: [自动调用 show_in_browser 工具]
       已经在您的浏览器中打开了！
```

### 示例 3: 截图
```
User: 帮我截图 github.com/trending
Claude: [自动调用 screenshot_webpage 工具]
       截图已保存到 /tmp/screenshot_xxx.png
```

### 示例 4: Hacker News
```
User: 今天 Hacker News 有什么热门内容？
Claude: [自动调用 scrape_hacker_news 工具]
       今天 Hacker News 的热门内容有：
       1. How Did TVs Get So Cheap?
       2. Lights and Shadows
       ...
```

### 示例 5: GitHub Trending
```
User: 最近有哪些热门的 Python 项目？
Claude: [自动调用 scrape_github_trending 工具]
       最近热门的 Python 项目包括：
       1. MiroMindAI/MiroThinker (799 stars today)
       ...
```

## 🔧 进阶用法

### 组合使用工具

```
User: 帮我抓取 Hacker News 前5条新闻，然后生成一个漂亮的 HTML 页面，在浏览器中显示

Claude:
1. [调用 scrape_hacker_news] 获取新闻数据
2. [生成 HTML]
3. [调用 show_in_browser] 在浏览器中显示

好的，已经在您的浏览器中打开了 Hacker News 汇总页面！
```

### 自动化工作流

```
User: 每天帮我做一份技术新闻报告：
     1. Hacker News 前10条
     2. GitHub Python Trending 前5个
     3. 生成 HTML 报告并在浏览器显示

Claude: [依次调用多个工具并生成报告]
```

## 📝 开发自定义工具

你可以在 `index.js` 中添加更多工具：

```javascript
// 在 ListToolsRequestSchema 中添加新工具
{
    name: 'my_custom_tool',
    description: '我的自定义功能',
    inputSchema: {
        type: 'object',
        properties: {
            param1: { type: 'string', description: '参数1' }
        },
        required: ['param1']
    }
}

// 在 CallToolRequestSchema 中实现功能
case 'my_custom_tool': {
    // 实现你的功能
    return {
        content: [{ type: 'text', text: 'result' }]
    };
}
```

## 🎨 Python 版本

如果你更喜欢 Python，可以使用 `browser_manager.py` 和相关脚本：

```python
from browser_manager import BrowserManager

# 在浏览器中显示内容
manager = BrowserManager()
manager.open_html("<h1>Hello</h1>", auto_close=False)
```

## 🔍 调试

### 查看服务器日志

```bash
# 直接运行服务器
node /mnt/d/python/hacknews/mcp-server-wsl-browser/index.js

# 服务器会输出日志到 stderr
```

### 测试单个工具

创建测试脚本：

```javascript
import { chromium } from 'playwright';

async function test() {
    const browser = await chromium.launch({ headless: true });
    const page = await browser.newPage();

    await page.goto('https://news.ycombinator.com/');
    const title = await page.title();

    console.log('Title:', title);
    await browser.close();
}

test();
```

## 📚 相关文档

- **wsl.md** - WSL 环境完整技术文档
- **browser_manager.py** - Python 浏览器管理类
- **demo_practical_scraping.py** - Python 实用示例
- **mcp-server-wsl-browser/README.md** - MCP 服务器详细文档

## 🐛 常见问题

### Q: MCP 服务器没有加载？

A: 检查以下几点：
1. 配置文件路径是否正确
2. `node` 是否在 PATH 中
3. 重启 Claude Code
4. 查看 Claude Code 的日志

### Q: Playwright 浏览器未安装？

A: 运行：
```bash
npx playwright install chromium
```

### Q: 浏览器没有打开？

A: 确保：
1. 在 WSL 环境中运行
2. Windows 浏览器已安装（Chrome/Edge/Firefox）
3. `wslpath` 命令可用

### Q: 权限错误？

A: 在 `.claude/settings.local.json` 中添加权限：
```json
{
  "permissions": {
    "allow": [
      "Bash(node:*)",
      "Bash(npx:*)"
    ]
  }
}
```

## 🎯 下一步

1. ✅ 运行 `node examples.js` 测试功能
2. ✅ 配置 Claude Code MCP 服务器
3. ✅ 在对话中测试工具调用
4. ✅ 根据需要添加自定义工具
5. ✅ 集成到你的 Node.js 项目中

## 🤝 贡献

这个 MCP 服务器是完全可定制的！你可以：

- 添加更多网站的专用抓取器
- 实现数据持久化
- 添加定时任务功能
- 集成其他服务（邮件、通知等）

## 📖 技术栈

- **MCP SDK** - Model Context Protocol
- **Playwright** - 浏览器自动化
- **Node.js** - 运行时
- **WSL** - Windows Subsystem for Linux

---

**祝你使用愉快！🎉**

如有问题，参考 `wsl.md` 或 `mcp-server-wsl-browser/README.md`
