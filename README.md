# HackNews 中文摘要发布器

从 Hacker News 抓取热门新闻和讨论，由 Codex 生成中文标题、摘要、排序与标签，并发布到微信公众号草稿箱。可选将同一份内容同步到独立 Astro 博客仓库。

## 仓库职责

本仓库是抓取和发布系统的唯一源码仓库，包括 Codex skill：

```text
hacknews/
├─ skills/publish-hacknews-codex/  # Codex 发布 skill
├─ src/                            # 抓取、数据库和内容处理
├─ scripts/                        # 微信发布与题图生成
├─ prompts/                        # AI 题图提示词
├─ config/                         # 配置模板
├─ tests/                          # 部署与安装测试
└─ install.ps1                     # Codex skill 安装器
```

`hacknews_recap` 是独立且可选的 Astro 部署仓库。未配置它时，本地 Markdown、HTML、题图和微信公众号发布仍可正常工作。

## 环境要求

- Windows PowerShell
- Python 3.11 或更高版本
- SQLite CLI
- Codex
- 微信公众号 AppID/AppSecret（仅公众号发布需要）
- `gpt-image-2-skill`（可选；缺失时封面回退到头条原图）

## 安装

```powershell
git clone <repository-url> hacknews
cd hacknews

python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

Copy-Item .\config\config.json.example .\config\config.json
Copy-Item .\config\deployment.example.json .\config\deployment.local.json

powershell -ExecutionPolicy Bypass -File .\install.ps1
```

`install.ps1` 将仓库里的 skill 以 Junction 安装到：

```text
%CODEX_HOME%\skills\publish-hacknews-codex
```

未设置 `CODEX_HOME` 时使用 `~/.codex`。如果目标已有旧 skill，安装器会先创建时间戳备份，不会删除旧版本。如果目录正被 Codex 占用，请关闭或重启 Codex 后重新运行安装器。

## 配置

### 主配置

编辑不纳入 Git 的 `config/config.json`：

```json
{
  "wechat": {
    "appid": "your-appid",
    "appsec": "your-app-secret"
  }
}
```

也可以使用环境变量：

```text
WECHAT_APPID
WECHAT_APPSEC
```

仓库还保留 Grok、Gemini 和 Moonshot 的旧接口配置，但 Codex 发布流程不会调用这些模型生成标题和摘要。

### 部署配置

`config/deployment.local.json` 用于保存本机路径，并已加入 `.gitignore`：

```json
{
  "astro": {
    "enabled": false,
    "repo_path": "../hacknews_recap",
    "blog_subdir": "src/data/blog"
  },
  "image_generator": {
    "wrapper_path": ""
  }
}
```

路径和开关可通过环境变量覆盖：

- `HACKNEWS_ROOT`
- `HACKNEWS_DB_PATH`
- `HACKNEWS_ASTRO_ENABLED`
- `HACKNEWS_ASTRO_REPO`
- `HACKNEWS_IMAGE_WRAPPER`
- `HACKNEWS_DEPLOYMENT_CONFIG`

题图 wrapper 未显式配置时，按顺序检查：

```text
~/.claude/skills/gpt-image-2-skill/scripts/gpt_image_2_skill.cjs
~/.codex/skills/gpt-image-2-skill/scripts/gpt_image_2_skill.cjs
```

## 日常发布

在 Codex 中执行：

```text
Publish HackNews Codex 开始今天的
```

Skill 会完成：

1. 按本地自然日将旧新闻移入数据库 `news_history`。
2. 获取当天 Hacker News 新闻。
3. 抓取正文、讨论、图片和截图。
4. 对空正文、短正文、付费墙和防抓取内容做检查。
5. 由 Codex 生成中文标题、正文摘要、讨论摘要、排序和标签。
6. 生成 Markdown、HTML，以及可选 Astro Markdown。
7. 生成并检查 900×383 微信题图。
8. 发布微信公众号草稿。
9. 可选提交并推送 Astro 文章。
10. 打开当天图片目录。

正文为空或明显过短时，流程会停下来等待人工补充；其他正常发布步骤不会重复要求确认。

## 主要命令

### 抓取新闻

```powershell
python .\src\core\fetch_news.py
python .\skills\publish-hacknews-codex\scripts\collect_news_context.py --concurrency 3
```

### 检查正文和讨论

```powershell
sqlite3 -header -column ".\data\hacknews.db" "select id, length(coalesce(article_content,'')) as article_len, length(coalesce(discussion_content,'')) as discussion_len, title, news_url from news where date(created_at)=date('now','localtime') order by id;"
```

### 补抓空讨论

```powershell
python .\skills\publish-hacknews-codex\scripts\refetch_empty_discussions.py --ids 1234 --attempts 2 --delay 8
```

### 应用 Codex 计划并渲染

```powershell
python .\skills\publish-hacknews-codex\scripts\apply_news_edits.py ".\output\codex\hacknews_plan_YYYYMMDD_HHMMSS.json"
python .\skills\publish-hacknews-codex\scripts\render_manual_markdown.py ".\output\codex\hacknews_plan_YYYYMMDD_HHMMSS.json"
```

### 生成题图

```powershell
python .\scripts\generate_wechat_cover_ai.py `
  ".\output\markdown\hacknews_summary_YYYYMMDD_HHMM.md" `
  --target-word "主体加事件" `
  -o ".\output\images\YYYYMMDD\hacknews_cover_ai_YYYYMMDD.png"
```

题图文字应控制在 10–15 字，保留新闻主体和事件，不能用过度泛化的概念替代原标题。

### 发布公众号草稿

```powershell
python .\scripts\publish_wechat.py `
  ".\output\markdown\hacknews_summary_YYYYMMDD_HHMM.md" `
  --cover-image ".\output\images\YYYYMMDD\hacknews_cover_ai_YYYYMMDD.png"
```

更多说明见 [微信公众号发布指南](docs/WECHAT_PUBLISH.md)。

## 输出与本地数据

以下内容不纳入 Git：

```text
config/config.json
config/deployment.local.json
data/
output/
tmp/
```

主要输出：

```text
data/hacknews.db
output/codex/hacknews_context_*.json
output/codex/hacknews_plan_*.json
output/markdown/hacknews_summary_*.md
output/markdown/hacknews_summary_*.html
output/images/YYYYMMDD/
```

## 测试

```powershell
python -m unittest tests.test_deployment -v
powershell -NoProfile -ExecutionPolicy Bypass -File .\tests\test_install_skill.ps1
python -m py_compile .\src\utils\deployment.py .\scripts\generate_wechat_cover_ai.py
```

## 项目指令

根目录的 `AGENT.md` 是 Codex 自动读取的项目级操作约束，必须留在根目录，不能移动到 `docs`。

## License

MIT
