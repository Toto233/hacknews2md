# 单仓库架构与安装

本项目使用一个 Git 仓库、一个 Python 发行包和统一版本，提供 Hacker News 日报与 Product Hunt 月报。发行包继续使用 `hn2md` 名称，命令入口按来源区分。使用者下载一次仓库即可安装和发布任一来源，无需另行部署一个 Hacker News 项目才能发布 Product Hunt。

## 模块职责

| 模块 | 拥有的职责 |
| --- | --- |
| `publisher/` | Hacker News 对外编排、命令及阶段集成；Product Hunt 命令转交给其独立流程。 |
| `hn2md/`、`src/` | Hacker News 抓取、内容、编辑、状态及来源专用集成。 |
| `ph2md/` | 月榜抓取、数据库、Top 10 编辑计划、严格审计、渲染、发布状态与回执。 |
| `publisher_shared/wechat/` | Markdown 转换、正文图片与封面上传、草稿创建、远端校验和结构化传输结果。 |
| `skills/` | 两个来源的编辑与恢复规范。 |

依赖方向为 `publisher/hn2md → publisher_shared/wechat` 和 `ph2md → publisher_shared/wechat`。公共发布模块不导入来源的编排或数据库；来源模块决定文章是否可以发布，再交给公共模块传输。源 URL 安全校验、统一 SQLite 连接工厂等现有基础工具仍可复用，不在这次整理中整体搬迁。

共享代码在本仓库维护一次。修改公共传输时同时验证 HN 和 PH 的调用契约；修改 PH 编辑规则时不改变 HN 的来源、截图或摘要要求。微信草稿、订阅者群发和 Astro 推送是不同动作，公共草稿上传成功不会自动增加其他目标。

## 使用者安装

从仓库根目录运行，Python 3.11+：

```powershell
python -m venv .venv
# 只使用 Product Hunt
.\.venv\Scripts\python.exe -m pip install -e ".[producthunt]"
# 使用 Hacker News，或同时使用两者
.\.venv\Scripts\python.exe -m pip install -e ".[hackernews]"
.\.venv\Scripts\python.exe -m pip install -e ".[hackernews,producthunt]"
```

选择其中一条安装命令即可。基础依赖包含公共发布和 PH 抓取/渲染所需组件；`producthunt` 是明确的功能选择入口，HN 的浏览器和应用 LLM 等较重依赖放在 `hackernews` extra。依赖清单以 `pyproject.toml` 为准；运行时不会自动安装包。安装包包含全部业务代码，选择 extra 决定安装哪些可选依赖。

开发者在对应业务依赖之外安装 `dev` extra，例如 `python -m pip install -e ".[hackernews,producthunt,dev]"`。`requirements.txt` 保留与项目声明同步的完整功能依赖，供原有安装方式使用；仅使用 PH 时选择 extra 安装，避免安装 HN 专用依赖。

公众号凭据放在本部署根目录忽略提交的 `config/config.json`，或 `WECHAT_APPID` / `WECHAT_APPSEC` 环境变量。文章、图片、数据库与回执属于运行数据，不放入发行包。两个来源可以共享一个已配置账号，同时保留各自的发布检查与回执。

## 数据隔离与部署根目录

HN 保留既有 `data/`、`output/markdown/`、`output/images/` 和 `output/jobs/` 等位置，以免破坏已有日报与回执引用。PH 默认使用：

```text
data/producthunt/producthunt.db
output/producthunt/
├── codex/       # 草稿及最终编辑计划
├── markdown/    # Markdown 与 HTML
├── images/      # YYYYMM 图片和封面
├── receipts/    # 月度抓取和上传回执
└── backups/     # 重渲染及迁移备份
```

`ph2md --root <部署目录> ...` 将数据库、产物和账号配置定位到该目录；默认根目录是当前工作目录。PowerShell 包装器从仓库根目录运行，可显式传入其他部署目录。不要把命令执行目录误认为源码必须所在的位置。

旧独立月报项目的数据通过显式迁移复制到上述目录，保留原始项目和所有已知 Media ID；迁移不是重新抓取，也不调用微信。详见 [迁移与运行指南](PRODUCTHUNT.md)。

## 版本与演进

当前以同一版本发布，版本唯一来源为 `publisher_shared.__version__`，构建元数据及业务模块复用该值。公共接口变化和两边调用方在同一次修改中完成。没有动态插件发现机制，也没有三个需要分别发布的依赖包。目录边界已经允许未来独立打包，但只有在业务需要独立版本、发布节奏或公共模块被第三个项目复用时，再考虑同仓库多包 workspace；拆包后安装依赖仍由包管理器自动处理。

本次迁移的验收包括：仅安装 PH 所需依赖可以从本地榜单导出计划、审计、渲染和离线预检；模拟微信结果验证草稿回执与重复上传保护；HN 的调用与既有路径保持兼容。测试不会使用真实公众号创建草稿。决策依据见 [2026-10-02 决策](DECISIONS.md)。
