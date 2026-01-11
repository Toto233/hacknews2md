# HackNews 中文摘要生成器

这是一个自动抓取 Hacker News 热门新闻并生成中文摘要的工具。该工具会自动获取新闻内容和相关讨论，使用多个 AI 大模型进行翻译和摘要生成，最终输出易于阅读的中文摘要报告。

## 🌟 主要特性

- **多 LLM 供应商支持**: 集成 Grok、Gemini、Moonshot 三个 AI 供应商
- **智能负载均衡**: Gemini 模型间自动轮换，分摊配额限制
- **自动容错降级**: API 失败时自动切换到备用 LLM
- **智能限流保护**: 每个 API 独立限流，避免触发限制
- **完整内容抓取**: 支持 YouTube、Twitter/X、PDF 等多种内容源
- **图片处理**: 自动下载、转换和优化图片
- **微信公众号集成**: 一键上传到微信公众号草稿箱

## 主要功能模块

### 1. 新闻抓取模块 (fetch_news.py)
- 自动抓取 Hacker News 首页热门新闻
- 获取新闻标题、链接和讨论页面链接
- 将新闻数据保存到 SQLite 数据库中
- 自动过滤重复新闻和特定类型的新闻（如 Ask HN）

### 2. 内容摘要模块 (summarize_news3.py)
- 抓取新闻原文内容和相关讨论
- **多 LLM 支持**：支持 Grok、Gemini、Moonshot 三种 AI 模型
- **智能模型选择**：
  - Gemini 负载均衡：在 `gemini-2.5-flash` 和 `gemini-2.5-flash-lite` 间轮换
  - 自动降级策略：主 LLM 失败时自动切换到备用 LLM
  - 配额保护：自动检测并处理 API 配额超限
- 支持新闻标题翻译、正文摘要和讨论内容摘要
- 智能处理各种网页格式和错误情况
- **多层次内容抓取策略**：
  - 优先使用 Crawl4AI 异步爬虫进行高效抓取
  - 自动回退方案：当 Crawl4AI 失败时，自动使用 requests + BeautifulSoup 重试
  - 二进制内容过滤：自动检测和过滤非文本内容，确保数据库存储纯文本
  - Content-Type 检测：智能识别HTML/文本内容，跳过PDF、图片等非文本资源
- **特殊内容源支持**：
  - YouTube: 自动提取视频字幕
  - Twitter/X: 支持多种 API 获取推文内容
  - PDF: 自动提取文本并生成截图
- **图片处理功能**：
  - 支持多种图片格式：JPEG、PNG、GIF、WebP、AVIF、SVG
  - 自动格式转换：WebP、AVIF、SVG 格式自动转换为 PNG 格式存储
  - 智能图片过滤：自动过滤尺寸小于 100x100 的图片
  - 本地存储：所有图片下载到本地并按日期分类保存

### 3. Markdown 生成模块 (generate_markdown.py)
- 将处理后的新闻数据生成美观的 Markdown 文档
- 包含新闻标题、原文链接、内容摘要和讨论摘要
- 自动添加时间戳和格式化处理
- **新增：集成微信草稿箱上传功能**
  - 支持自动将生成的HTML文件上传到微信公众号草稿箱
  - 智能路径转换，支持WSL环境下的路径处理
  - 可配置作者、摘要等文章元信息

### 4. Markdown 转微信公众号 HTML 模块 (markdown_to_html_converter.py)
- 将带 YAML Front Matter 的 Markdown 转为微信公众号友好 HTML
- 支持标题、图片、链接行、分隔线、行内代码；内置响应式样式

### 5. 浏览器管理模块 (browser_manager.py)
- 在浏览器中预览 HTML，支持自动/手动关闭，便于复制到公众号

## 🤖 AI 模型配置

本项目支持三个主流 LLM 供应商，具备完整的容错和负载均衡能力：

### 支持的 LLM 供应商

| 供应商 | 模型 | 限流 | 特性 |
|--------|------|------|------|
| **Grok** (X.AI) | grok-3-mini | 50次/分钟 | 快速响应，支持长文本 |
| **Gemini** (Google) | gemini-2.5-flash<br>gemini-2.5-flash-lite | 8次/分钟<br>(每个模型) | 支持图片输入<br>负载均衡 |
| **Moonshot** (月之暗面) | moonshot-v1-8k<br>moonshot-v1-32k<br>moonshot-v1-128k | 3次/分钟 | 超长上下文 |

### LLM 核心功能

#### 1. **负载均衡** (Gemini)
```python
# Gemini 在两个模型间自动轮换
gemini-2.5-flash → gemini-2.5-flash-lite → gemini-2.5-flash ...
```
- 每个模型独立配额: 20次/天
- 总配额翻倍: 40次/天
- 自动轮换，无需手动干预

#### 2. **自动降级策略**
当主 LLM 失败时，自动按优先级切换：
```
Grok 失败 → Gemini → Moonshot
Gemini 失败 → Grok → Moonshot
Moonshot 失败 → Gemini → Grok
```

#### 3. **智能限流保护**
- 每个 API 独立限流计数
- 自动等待和重试机制
- 配额超限自动切换模型

#### 4. **配额智能检测**
- 自动识别配额超限 (`quota exceeded + limit: 0`)
- 提取 API 返回的重试延迟 (`retryDelay`)
- 区分限流 (429) 和配额耗尽

### 配置示例

在 `config/config.json` 中配置：

```json
{
  "GROK_API_KEY": "your-grok-api-key",
  "GROK_MODEL": "grok-3-mini",

  "GEMINI_API_KEY": "your-gemini-api-key",
  "GEMINI_MODEL": "gemini-2.5-flash",

  "MOONSHOT_API_KEY": "your-moonshot-api-key",
  "MOONSHOT_MODEL": "moonshot-v1-8k",

  "DEFAULT_LLM": "gemini"
}
```

### 使用方法

```python
from src.llm.llm_utils import call_llm

# 使用默认 LLM
result = call_llm(prompt="翻译这段文字...")

# 指定使用 Moonshot
result = call_llm(
    prompt="总结这篇文章...",
    llm_type='moonshot',
    system_content="你是技术专家"
)

# Gemini 支持图片
result = call_llm(
    prompt="描述这张图片",
    llm_type='gemini',
    image_data=base64_image
)
```

详细文档请参考 [docs/MOONSHOT_INTEGRATION.md](docs/MOONSHOT_INTEGRATION.md)

## 环境要求
- Python 3.6+
- 必要的 Python 包：requests, beautifulsoup4, sqlite3, crawl4ai（用于网页抓取）
- Pillow 及 pillow-avif-plugin（用于图片处理和格式转换）
- **至少一个 LLM API 密钥**（需要在 config.json 中配置）：
  - Grok API 密钥（推荐）
  - Gemini API 密钥（支持图片）
  - Moonshot API 密钥（超长上下文）
- **微信公众号配置**：如需使用草稿箱上传功能，需在 config.json 中配置微信公众号的 appid 和 appsec
- （HTML 转换模块使用标准库，无需额外第三方依赖）

## 使用方法
1. 克隆项目并安装依赖：
```bash
pip install -r requirements.txt
```

2. 配置 API 和微信公众号：
- 复制 config/config.json.example 为 config/config.json
- **配置至少一个 LLM API 密钥**：
  ```json
  {
    "GROK_API_KEY": "your-grok-api-key",
    "GEMINI_API_KEY": "your-gemini-api-key",
    "MOONSHOT_API_KEY": "your-moonshot-api-key",
    "DEFAULT_LLM": "gemini"
  }
  ```
- **（可选）配置微信公众号信息**：
  ```json
  {
    "wechat": {
        "appid": "your_wechat_appid",
        "appsec": "your_wechat_appsec"
    }
  }
  ```

3. 运行程序：
```bash
# 抓取最新新闻
python src/core/fetch_news.py

# 生成新闻摘要
python src/core/summarize_news3.py

# 生成 Markdown 报告
python src/core/generate_markdown.py
```

- 运行 `python src/core/generate_markdown.py` 将生成并打开两份文件：`hacknews_summary_YYYYMMDD_HHMM.md` 与 `hacknews_summary_YYYYMMDD_HHMM.html`；HTML 会在浏览器中打开，便于复制到微信公众号编辑器，按回车后关闭浏览器。
- **新增：微信草稿箱上传**：完成HTML预览后，系统会询问是否自动上传到微信公众号草稿箱（输入 y 或 yes 确认上传）
- 生成逻辑要点：
  - 选取最近约 12 小时内且已生成内容与讨论摘要的新闻
  - 使用大模型对标题吸引力打分排序（失败则按时间）
  - 抽取标签并生成 YAML 头部（`title/author/description/pubDatetime/tags`）
  - 每条新闻支持最多 3 张图片、原文与讨论链接、摘要内容

### 可选：单独转换/预览

- 以函数方式转换 Markdown 为 HTML：

```python
from src.integrations.markdown_to_html_converter import convert_markdown_to_html

with open('your.md', 'r', encoding='utf-8') as f:
    md = f.read()

html = convert_markdown_to_html(md)

with open('out.html', 'w', encoding='utf-8') as f:
    f.write(html)
```

- 命令行转换现有 Markdown：

```bash
python src/integrations/markdown_to_html_converter.py input.md -o output.html --no-open
# 自动打开并在 10 秒后关闭
python src/integrations/markdown_to_html_converter.py input.md -o output.html --auto-close 10
```

- 浏览器预览：

```python
from src.utils.browser_manager import display_html_in_browser

display_html_in_browser(html, auto_close=True, close_delay=10)
```

## Markdown → 公众号 HTML 转换规则（精要）

- 标题：`## 1. 标题` → 公众号风格 `h2`（序号与配色）
- 图片：`![alt](src)` → 居中、圆角阴影、带说明
- 链接行：包含中文冒号“：”且含 `http` 的整行 → 高亮链接段落
- 分隔线：`---` → 渐变分隔线
- 行内代码：`` `code` `` → 灰底红字内联代码
- YAML 头部：`title/author/description/pubDatetime/tags` 将用于 `<title>` 与元信息

## 微信草稿箱上传功能

### 功能特性
- **自动上传**：将生成的HTML文件直接上传到微信公众号草稿箱
- **智能路径处理**：自动检测WSL环境并进行路径转换
- **图片处理**：自动处理HTML中的本地图片路径
- **内容清理**：自动清理HTML内容以适配微信公众号格式

### 使用方法
1. 在 config/config.json 中配置微信公众号信息：
```json
{
  "wechat": {
    "appid": "your_wechat_appid",
    "appsec": "your_wechat_appsec"
  }
}
```

2. 运行 generate_markdown.py，在HTML预览完成后选择上传：
```bash
python src/core/generate_markdown.py
# 按回车关闭浏览器后，输入 y 或 yes 确认上传
```

### 支持环境
- **Windows**: 原生Windows环境
- **WSL**: Windows Subsystem for Linux，自动处理路径转换
- **Linux**: 原生Linux环境

### 注意事项
- 确保微信公众号具有素材管理权限
- 上传的HTML会自动使用默认缩略图
- 文章标题会自动截断至64字符以符合微信限制

## 注意事项
- 请确保 config.json 中至少配置了一个 LLM API 密钥
- 推荐配置多个 LLM 以提高可用性和配额
- 建议定时运行脚本以获取最新内容
- 注意控制 API 调用频率，避免超出限制
- 注意，由于某些网站会屏蔽抓取，导致生成的摘要为空
- 微信草稿箱上传功能需要有效的微信公众号配置
- **LLM 配额管理**：
  - Gemini 自动在两个模型间轮换，有效翻倍配额
  - 配额超限时会自动切换到备用 LLM
  - 建议配置多个 API 密钥以提高可用性

## 📚 相关文档

- [docs/MOONSHOT_INTEGRATION.md](docs/MOONSHOT_INTEGRATION.md) - Moonshot AI 集成详细文档
- [WORKFLOW.md](WORKFLOW.md) - 日常使用工作流程指南
- [MIGRATION_GUIDE.md](MIGRATION_GUIDE.md) - 项目重组迁移指南

## 🏗️ 项目架构

```
hacknews/
├── src/                          # 源代码
│   ├── core/                     # 核心功能模块
│   │   ├── fetch_news.py         # 新闻抓取
│   │   ├── summarize_news3.py    # 摘要生成
│   │   ├── generate_markdown.py  # Markdown 生成
│   │   └── archive_news.py       # 归档功能
│   ├── llm/                      # LLM 相关模块
│   │   ├── llm_utils.py          # LLM 统一接口 + 负载均衡
│   │   ├── llm_business.py       # 业务层抽象
│   │   ├── llm_evaluator.py      # 新闻评分
│   │   ├── llm_tag_extractor.py  # 标签提取
│   │   └── prompts.py            # 提示词库
│   ├── integrations/             # 第三方集成
│   │   ├── wechat_access_token.py        # 微信API
│   │   └── markdown_to_html_converter.py # Markdown转HTML
│   └── utils/                    # 工具类
│       ├── db_utils.py           # 数据库工具
│       ├── config.py             # 配置加载器
│       ├── proxy_config.py       # 代理配置
│       └── browser_manager.py    # 浏览器管理
├── scripts/                      # 可执行脚本
│   └── auto_process.py           # 自动化处理
├── config/                       # 配置文件
│   ├── config.json               # 主配置
│   └── config.json.example       # 配置模板
├── data/                         # 数据文件
│   └── hacknews.db               # SQLite 数据库
├── output/                       # 输出文件
│   ├── markdown/                 # 生成的 Markdown/HTML
│   └── images/                   # 下载的图片
└── docs/                         # 文档
```

## 🔍 故障排除

### LLM API 相关

**问题**: API 调用失败
```
解决方案：
1. 检查 API Key 是否正确
2. 查看是否触发限流（会自动重试）
3. 确认配额是否充足
4. 系统会自动切换到备用 LLM
```

**问题**: Gemini 配额耗尽
```
解决方案：
1. 系统会自动在 flash 和 flash-lite 间轮换
2. 配额耗尽时自动切换到 Grok 或 Moonshot
3. 检查 gemini-2.5-pro 是否被拦截（系统已自动处理）
```

**问题**: 图片摘要失败
```
解决方案：
1. 确保使用 Gemini（只有 Gemini 支持图片）
2. 检查 image_data 是否正确 base64 编码
3. 查看是否是配额问题
```

### 管理违禁关键字

```bash
# 添加关键字
python manage_keywords.py add 敏感词1

# 列出所有关键字
python manage_keywords.py list

# 删除关键字
python manage_keywords.py remove 敏感词1
```


## 贡献指南
欢迎提交 Issue 和 Pull Request 来帮助改进项目。在提交代码前，请确保：
- 代码符合 PEP 8 规范
- 添加必要的注释和文档
- 测试代码功能正常

## 许可证
MIT License
