# 新闻与月榜发布器

本仓库提供 Hacker News 中文日报和 Product Hunt 中文月报的采集、编辑门禁与发布。两个业务模块共享一份微信发布实现，使用一个 Python 安装包和统一版本。默认“发布到微信”是创建公众号**草稿**，不是群发。

## 项目边界

| 位置 | 职责 |
| --- | --- |
| `publisher/` | 日报编排入口；Product Hunt 命令转交给 `ph2md`。 |
| `hn2md/`、`src/` | Hacker News 阶段、抓取、数据库和来源集成。 |
| `ph2md/` | 月榜抓取、Top 10 编辑审计、渲染、月度状态与发布回执。 |
| `publisher_shared/wechat/` | 公共 Markdown 转换、图片上传、公众号草稿创建与校验。 |
| `skills/publish-hacknews-codex/` | 日报的 Codex 编辑与恢复流程。 |
| `skills/publish-producthunt-monthly/` | 本仓库月报的编辑与发布流程。 |

Astro 博客是独立仓库。Hacker News 完整发布会尝试同步 Astro；Product Hunt 月报默认仅创建微信草稿。两个来源的数据库和发布回执不混用。组织方式与依赖边界见 [Monorepo 架构](docs/MONOREPO.md)。

## 安装与配置

需要 Python 3.11+；Windows 示例使用 PowerShell，Codex 用于人工计划和封面工作流。SQLite 由 Python 使用，不要求单独安装 `sqlite3` 命令行工具。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[hackernews,producthunt]"
Copy-Item .\config\config.json.example .\config\config.json
Copy-Item .\config\deployment.example.json .\config\deployment.local.json
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

仅使用 Product Hunt 可将安装参数改为 `".[producthunt]"`；仅使用 Hacker News 用 `".[hackernews]"`。只下载这一个仓库即可，公共发布模块会一并安装。`requirements.txt` 保留完整依赖供旧安装方式使用。依赖详情以 `pyproject.toml` 为准。

`install.ps1` 安装本仓库的 Hacker News skill，是 Codex 工作流的可选步骤。把微信公众号 AppID/AppSecret 放在忽略的 `config/config.json`，也可使用 `WECHAT_APPID`、`WECHAT_APPSEC`；本机 Astro 路径等放在 `config/deployment.local.json`。PH 使用相同的本部署配置，无需部署另一个项目。不要提交凭据、`data/` 或 `output/`。

日报优先使用 `scripts/publisher.ps1`，月报优先使用 `scripts/ph2md.ps1`，包装器选择已配置的 Python 环境。安装后也可使用 `publisher`、`ph2md` 命令；跨平台月报入口是 `python -m ph2md.cli`。`hn2md` 是内部兼容 CLI；新的日报流程以 `publisher` 为准。

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

月报流程已纳入本仓库 `ph2md/`，要求 Top 10 的逐条观察、风险和图片，以及完整榜单和原月榜链接。使用 `scripts/ph2md.ps1` 运行完整编辑流程，旧基础榜单实现已由这条流程替代。详细步骤、迁移及恢复见 [Product Hunt 指南](docs/PRODUCTHUNT.md)，编辑标准见 [月报技能](skills/publish-producthunt-monthly/SKILL.md)。

以下以最近一个完整自然月 2026 年 9 月为例，已有该月数据时先复用，再按需要抓取：

```powershell
.\scripts\ph2md.ps1 status --year 2026 --month 9
.\scripts\ph2md.ps1 fetch --year 2026 --month 9 --limit 25
.\scripts\ph2md.ps1 export-plan --year 2026 --month 9
```

补完 `output/producthunt/codex/producthunt_plan_202609.json` 的产品观察与风险后：

```powershell
.\scripts\ph2md.ps1 audit --year 2026 --month 9
.\scripts\ph2md.ps1 render --year 2026 --month 9
.\scripts\ph2md.ps1 preview --year 2026 --month 9
# 需要创建微信草稿时执行
.\scripts\ph2md.ps1 publish --year 2026 --month 9
```

预检不调用微信 API。上传会记录 Media ID 和月报状态，已确认成功或结果不明的上传不会自动重复。PH 数据库为 `data/producthunt/producthunt.db`，产物和回执在 `output/producthunt/`；无需另行安装 HN 专用依赖。旧独立项目的数据先按指南显式迁移，保留原件和既有草稿 Media ID。

## 微信预检与验证

低层微信工具的 `--preview` 会转换 Markdown，检查正文、本地图片格式及 1 MB 自动上传限制、封面可读性和两种裁剪；它不调用微信接口，也不创建草稿。直接调用此工具不会替代日报/月报各自的来源与编辑门禁。见 [微信发布指南](docs/WECHAT_PUBLISH.md)。

针对改动运行相关测试；例如：

```powershell
pytest tests/test_publish_today_wechat.py tests/test_publish_wechat_preview.py -q --tb=short
```

发布规则的已接受取舍见 [决策记录](docs/DECISIONS.md)。
