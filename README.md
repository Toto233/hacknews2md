# 新闻与月榜发布器

本仓库负责 Hacker News 中文日报的采集、编辑门禁与发布，也提供 Product Hunt 月报的 Codex 编辑规范和微信上传组件。默认“发布到微信”是创建公众号**草稿**，不是群发。

## 项目边界

| 位置 | 职责 |
| --- | --- |
| `publisher/` | 按来源编排阶段、状态和回执；日报从这里进入。 |
| `hn2md/`、`src/` | Hacker News 阶段、抓取、数据库和微信集成。 |
| `skills/publish-hacknews-codex/` | 日报的 Codex 编辑与恢复流程。 |
| `skills/publish-producthunt-monthly/` | 月报的编辑标准，指向独立的 `producthunt-monthly` 兼容项目。 |
| `D:\python\producthunt-monthly` | 月榜抓取、数据、Top 10 计划、审计和渲染；微信发布目前调用本仓库的上传脚本与配置。 |

Astro 博客是独立仓库。Hacker News 完整发布会尝试同步 Astro；Product Hunt 月报默认仅创建微信草稿。两个来源的数据库和发布回执不混用。

## 安装与配置

需要 Windows PowerShell、Python 3.11+ 和 Codex。SQLite 由 Python 使用，不要求单独安装 `sqlite3` 命令行工具。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
Copy-Item .\config\config.json.example .\config\config.json
Copy-Item .\config\deployment.example.json .\config\deployment.local.json
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

`install.ps1` 安装本仓库的 Hacker News skill。把微信公众号 AppID/AppSecret 放在忽略的 `config/config.json`，也可使用 `WECHAT_APPID`、`WECHAT_APPSEC`；本机 Astro 路径等放在 `config/deployment.local.json`。不要提交凭据、`data/` 或 `output/`。

运行命令优先使用 `scripts/publisher.ps1`，它会选择已配置的 Python 环境。`hn2md` 是内部兼容 CLI；新的日报流程以 `publisher` 为准。

## Hacker News 日报

先检查当天状态：

```powershell
.\scripts\publisher.ps1 status hackernews
```

在 Codex 中请求“发布今天新闻”会进入 [日报技能](skills/publish-hacknews-codex/SKILL.md)的人工计划流程：获取新闻与正文、捕获截图、审查来源、编写并导入中文计划、严格审计、渲染、封面、微信草稿、可用时的 Astro 同步，以及发布后复核。`release hackernews` 的自动计划不能替代这条编辑流程。未完成的运行按回执续跑，不重复创建已确认的草稿。

需要恢复某个阶段或排查失败时，先看 [运行手册](docs/RUNBOOK.md)和技能里的条件性恢复指引。每条有源 URL 的新闻在微信上传前须有截图，除非用户对该条明确同意并记录一次性豁免；正文来源和摘要也有独立门禁。

当内容与封面已准备好、但当前网络不在微信 IP 白名单时，可在切换网络后运行桌面快捷方式或：

```powershell
python .\scripts\publish_today_wechat.py --check --no-pause
python .\scripts\publish_today_wechat.py --no-pause
```

这只读取台北时间当天已生成的文章和封面，并通过规范的 `publisher` 路径创建微信草稿，不生成正文或推送 Astro。`--check` 仅检查回执、文件和已知白名单失败；实际上传仍须通过 publisher 的发布审计。若上次被拒绝的出口 IP 未变化，它会在本地停下；同一 IP 已加入白名单时可显式加 `--whitelist-updated`。已有 Media ID 时不会重传。

## Product Hunt 月报

默认月报要求 Top 10 的逐条观察、风险和图片，以及完整榜单和原月榜链接。当前这条编辑流程在独立的 `producthunt-monthly` 项目中实现；本仓库的 `publisher producthunt` 是基础榜单路线，**不等同于已审计的编辑月报**。入口和审核边界见 [月报技能](skills/publish-producthunt-monthly/SKILL.md)。

在月报项目中，先抓榜、导出并补完 Top 10 计划，运行严格审计和渲染；使用以下命令做本地预检或创建草稿：

```powershell
python -m scripts.publish_producthunt_editorial --year YEAR --month MONTH --cover-image "<已验收封面>" --preview
python -m scripts.publish_producthunt_editorial --year YEAR --month MONTH --cover-image "<已验收封面>"
python -m ph2md.cli status --year YEAR --month MONTH
```

上传命令会记录 Media ID 和月报状态；已确认成功或结果不明的上传不会自动重复。月榜数据和渲染文件仍在月报项目内，微信上传脚本及配置目前在本仓库，因此月报的**生成可独立运行，微信发布尚不能单仓库独立运行**。详细命令以月报项目的 README/运行手册为准。

## 微信预检与验证

低层微信工具的 `--preview` 会转换 Markdown，检查正文、本地图片格式及 1 MB 自动上传限制、封面可读性和两种裁剪；它不调用微信接口，也不创建草稿。直接调用此工具不会替代日报/月报各自的来源与编辑门禁。见 [微信发布指南](docs/WECHAT_PUBLISH.md)。

针对改动运行相关测试；例如：

```powershell
pytest tests/test_publish_today_wechat.py tests/test_publish_wechat_preview.py -q --tb=short
```

发布规则的已接受取舍见 [决策记录](docs/DECISIONS.md)。
