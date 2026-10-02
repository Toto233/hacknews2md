# Product Hunt 月报操作与迁移

完整编辑月报位于本仓库 `ph2md/`。它拥有月榜数据库、Top 10 计划、严格审计和回执，直接调用公共微信模块创建草稿。只安装 `".[producthunt]"` 即可使用，无需部署旧项目或安装 HN 专用依赖；配置方法见 [README](../README.md)。

以下从仓库根目录运行，示例为 2026 年 9 月。包装器可替换为安装后的 `ph2md` 或 `python -m ph2md.cli`；年月必须与文件名中的 `202609` 一致。

## 根目录与文件

`--root` 是全局选项，放在子命令前；默认当前工作目录，也可设置 `PH2MD_ROOT`：

```powershell
python -m ph2md.cli --root "D:\publisher-workspace" status --year 2026 --month 9
```

| 内容 | 默认路径 |
| --- | --- |
| 数据库 | `data/producthunt/producthunt.db` |
| Top 10 计划 | `output/producthunt/codex/producthunt_plan_202609.json` |
| 微信 Markdown / HTML | `output/producthunt/markdown/producthunt_monthly_202609_wechat.md` / `.html` |
| 封面 | `output/producthunt/images/202609/producthunt_cover_202609.png` |
| Top 10 图片 | `output/producthunt/images/202609/logos/` |
| 抓取、渲染、发布回执 | `output/producthunt/receipts/` |
| 备份、诊断 HTML | `output/producthunt/backups/`、`output/producthunt/debug/` |

账号使用部署根目录的 `config/config.json` 或 `WECHAT_APPID` / `WECHAT_APPSEC`；`preview` / `publish` 可显式指定 `--config <文件>`。纯环境变量部署可以不创建配置文件。`doctor` 检查路径和 SQLite schema，不证明网络或微信账号可用。来源写锁串行化 PH 数据和回执修改；写入命令应顺序执行。`status` 使用只读快照，不初始化数据库，可在写入期间查询；尚无数据库时返回 `NOT_STARTED`。

## 1. 检查与抓取

```powershell
.\scripts\ph2md.ps1 doctor
.\scripts\ph2md.ps1 status --year 2026 --month 9
.\scripts\ph2md.ps1 fetch --year 2026 --month 9 --limit 25
```

已有该月数据时先复用。默认最多抓取 25 条，`--limit` 支持 10–100；正式月报至少需要十条。核对官方排名、Top 10 名称及 launch 链接。已有编号的榜单会排除无编号推广卡；同一产品主页可以对应不同 launch，不能仅按 URL 去重。

刷新在事务中替换该月产品行，校验连续唯一名次及源/库数量一致；失败保留旧产品行。必要刷新前用 SQLite backup API 保存数据库和编辑产物，避免直接复制正在使用的 WAL 数据库。刷新后核对计划并重新渲染，既有微信草稿不会随本地刷新而变化。

`fetch --html-file <本地榜单HTML>` 可离线解析，但也写入数据库。诊断时用 `--root <临时目录>` 隔离数据。

## 2. 导出并编辑计划

```powershell
.\scripts\ph2md.ps1 export-plan --year 2026 --month 9
```

导出规范计划 `producthunt_plan_202609.json`，Top 10 的 `observation` 和 `risk` 为空；已有计划时拒绝覆盖。保留年月、排名、名称和 URL 与榜单一致。逐条查阅产品页面及必要的原始材料，写具体观察和未解风险。票数/评论只表示注意力，不证明采用率、收入或效果。

计划检查长度、重复和套话，阈值以 `ph2md/insights.py` 为准。核对全部十条的推理是否各自具体，换几个词不能替代产品相关的分析。

## 3. 审计、渲染与封面

```powershell
.\scripts\ph2md.ps1 audit --year 2026 --month 9
.\scripts\ph2md.ps1 render --year 2026 --month 9
```

审计须成功退出并显示通过。遗漏 Top 10、身份不匹配、短字段、重复或套话必须修复；自动检查不能代替事实核对。`audit` / `render` 可用 `--insights-file <计划>`；渲染时将通过审计的外部计划保存到规范路径并备份原版本。

重渲染备份同月 Markdown、HTML 和完整图片目录；默认封面和 logo 可以更新，自定义封面保留。检查十条图片、观察/风险、完整榜单和原月榜链接。`--skip-logos` 用于离线诊断；预检/上传必须有与渲染回执哈希一致的全部十张产品图片。

默认封面由 Pillow 生成。渲染器寻找本机中文字体；部署环境缺少字体时可用 `PH2MD_FONT` / `PH2MD_FONT_BOLD` 指向常规/粗体字体文件，检查字体回退警告和实际封面文字。用户要求 ImageGen 时按 [封面技能](../.codex/skills/wechat-cover-imagegen/SKILL.md)生成、检查完整图及方形裁剪，将接受的文件同时传给预检和上传的 `--cover-image`。

渲染回执绑定榜单、计划、Markdown 和产品图片的 SHA-256。渲染后修改任一项会阻止预检/上传；更新计划并重新渲染，确保传输的是已审计版本。显式更换封面无需重写文章。

## 4. 预检与公众号草稿

```powershell
.\scripts\ph2md.ps1 preview --year 2026 --month 9
.\scripts\ph2md.ps1 publish --year 2026 --month 9
.\scripts\ph2md.ps1 status --year 2026 --month 9
```

预检重新检查榜单、计划和渲染回执，实际转换 Markdown 并检查图片与封面；不获取 token、不调用微信 API、不创建草稿。生成/预览请求在本地产物和检查验收后完成。

上传作者为 `PH月榜`，严格上传正文图片及封面，创建草稿后读回核对。成功需要 Media ID、远端验证成功、发布回执和 `PUBLISHED` 状态。该状态只指草稿；PH 没有群发或 Astro 目标。

同月已有确认 Media ID 时复用结果。`attempting` 或 `uncertain` 回执需要先查远端草稿；已知 Media ID 但校验未完成的状态为 `PUBLISH_UNVERIFIED`，后续调用不会再上传，也不能把它报告成全部完成。保留回执和草稿，确认实际结果后恢复；入口不提供强制新草稿选项。

## 从旧独立项目迁移

先关闭旧项目的写入进程，并保持目标 PH 数据库未初始化；不要先执行 `doctor` 创建空目标库：

```powershell
.\scripts\ph2md.ps1 migrate-legacy --from-root "D:\python\producthunt-monthly"
.\scripts\ph2md.ps1 status --year 2026 --month 9
```

源可为任意旧部署位置。迁移检查编辑项目 schema，通过 SQLite backup API 保存一致快照，复制数据库、计划、文稿、图片、回执及备份，并重定位工作副本的本地路径。原项目及数据库快照保留；目标数据库或文件有冲突时拒绝覆盖。迁移报告保存在新 receipts 目录，不抓榜、不调用微信、不复制密钥。

已知草稿 Media ID 随数据保留，迁移后先查状态/回执，不重新上传。旧渲染没有新指纹回执，需预检或修改文章时重新审计、渲染并核对备份；这不会改动既有远端草稿。旧主仓库基础版 `data/producthunt.db` 不属于编辑项目 schema，不能当作本命令的迁移源；原文件保留，必要时另行核对恢复。

## 故障与旧入口

| 现象 | 下一步 |
| --- | --- |
| 抓取为零或排名不符 | 查 fetch receipt/debug HTML，对照官方编号，用隔离目录的 fixture 验证修复。 |
| 审计失败 | 修正身份、字段、重复问题，再审计与渲染。 |
| 图片/预检失败 | 检查本地文件、Markdown 引用、格式和封面，修复后预检。 |
| 渲染后版本变化 | 更新计划并重渲染，核对正文和备份。 |
| 微信白名单错误 | 配置当前出口 IP 后继续；先看回执判断草稿结果。 |
| 上传不明或远端校验失败 | 查 publish receipt 和草稿箱，保留 Media ID，确认结果后处理。 |

旧 `scripts/publisher.ps1 <command> producthunt ...` 转交同一流程，支持 `doctor`、`status`、`fetch`、`export-plan`、`audit`、`render`、`preview`、`publish`、`migrate-legacy`；`publish --dry-run` 转为预检。旧基础 `release`、`cover` 等阶段停止并提示编辑流程。PH 不使用 HN 日状态机或日报账本。

代码改动按范围运行离线测试；日常月报无需重复测试未改动的实现。共享接口见 [微信指南](WECHAT_PUBLISH.md)，安装/架构见 [Monorepo 说明](MONOREPO.md)。
