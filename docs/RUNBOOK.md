# 发布运行手册

本手册处理运行中断与恢复。Hacker News 日报的正常编辑顺序和门禁以 [发布技能](../skills/publish-hacknews-codex/SKILL.md)为准；Product Hunt 编辑月报以 [月报技能](../skills/publish-producthunt-monthly/SKILL.md)和 [操作指南](PRODUCTHUNT.md)为准。命令从本仓库根目录执行，先用 `./scripts/publisher.ps1 <command> --help` 或 `./scripts/ph2md.ps1 <command> --help` 核对当前参数。微信公众号目标是草稿，不是群发。

## 先看状态，再续跑

```powershell
.\scripts\publisher.ps1 status hackernews
.\scripts\publisher.ps1 review-missing hackernews
```

按账本中第一个未完成或失效阶段继续，不因一次局部失败重抓全部文章；不要把 Codex 人工撰写的计划替换成裸 `release` 的自动计划。账本在 `output/jobs/publish_job_YYYYMMDD.json`，阶段回执绑定同一 `run_id`。每个日期保持一个写入者；确认锁已过期才使用 `unlock hackernews`。

Hacker News `/front` 返回 419 时，按 [419 抓取恢复说明](HN_FETCH_419.md)核对浏览器页面和有序 ID；不要用实时 `topstories` 替换当天排名。

## 来源与截图

正文为空、只有网页壳或明显截断时，先查已抓内容和可归属的原文/替代来源。不能从常识补写原文。用户提供正文时，用 `set-content` 标记 `human_supplied` 与精确来源 URL；该操作会在本地刷新计划上下文，不重抓其他网站。

```powershell
.\scripts\publisher.ps1 set-content hackernews <id> --file "<正文.txt>" --source-type human_supplied --source-url "<原文URL>"
.\scripts\publisher.ps1 audit hackernews --phase pre-plan --json
```

图片和截图分别核对。GitHub 页面在采集阶段优先保存 GitHub Open Graph 分享预览图，并只从页面 Markdown 正文取其他图片；截图阶段不再对其启动浏览器。若分享图下载失败，发布前会报出 ID 和 URL；用 `collect hackernews --rerun` 补采图片，不以头像或其他正文图片冒充分享图。其他有来源 URL 的新闻仍须保存截图；失败时可定向重试 `capture-screenshots hackernews --rerun`。只有用户明确同意省略某条失败截图，才能为该日期、故事 ID 和精确 URL 记录一次性豁免。不能用假图或删条目绕过门禁。可见的候选替代来源，应先给用户原文和替代页的直接链接以便核对。

## 计划、审计与渲染

Codex 用 `draft-plan`/`export-context` 导航来源，按[技能中的逐条草稿格式](../skills/publish-hacknews-codex/SKILL.md#2-check-each-story-while-writing)写一条、核对一条，并用 `check-story hackernews --item-file "<story.json>"` 检查。检查回执保存在 `output/codex/story_checks/<日期>/<run_id>/`，绑定正文、讨论和草稿版本；正文或草稿变化只需重检查对应条目。结果只返回长度、问题和待确认句子，不重复输出全文。

全部条目处理完后运行 `story-status hackernews`。只有 `ready: true` 才排序、提取四个标签，用 `assemble-plan hackernews --selection-file "<排序和标签.json>" --output "<计划.json>"` 汇总，再执行 `plan --manual-plan`、`apply`、严格审计和渲染。导入/应用会拒绝未检查、失败、过期或与回执不一致的草稿；渲染、封面和上传前仍检查当前摘要和来源。历史手工计划若需要重新导入或渲染，先拆出条目完成逐条检查，不改变已有已发布稿。

文章摘要最低 280 字、讨论摘要最低 180 字，仍不可豁免。来源忠实度、标题准确性和可读性由编辑逐条实际核对，程序不能凭布尔字段验证事实。关键词可在渲染前通过 `record-keyword-review ... --item-file "<story.json>"` 记录原有上下文判断，确认后重检查该条。源码图片与截图可提前收集；生成封面须等最终内容和图片门禁通过。汇总后的复核只处理一致性、排序、链接、图片与目标文件，局部修改不重抓或重写其他条目。

## 微信草稿与 IP 白名单

发布前先运行低层 Markdown 预检，或使用规范发布命令的 `--dry-run` 路线；预检不创建草稿。真正上传由技能规定的 `publisher publish hackernews` 执行，成功须有 Media ID。

`40164 invalid ip` 是当前出口 IP 未在微信白名单。当天文章和封面已准备好时，可在切换网络后用桌面快捷方式或：

```powershell
python .\scripts\publish_today_wechat.py --check --no-pause
python .\scripts\publish_today_wechat.py --no-pause
```

一键脚本只读取台北时间当天已生成的文章和封面，使用规范的 `publisher.ps1 publish ... --target wechat`，不生成内容或推送 Astro。`--check` 只核对回执、文件和已知白名单失败；真正上传时仍由 publisher 执行发布审计。若出口 IP 仍与上次被拒绝的 IP 相同，它会在本地停止，不继续请求微信。已把同一 IP 加入白名单时可显式加 `--whitelist-updated`；公网 IP 查询不可用时也需由操作者确认后使用该标志。

上传超时或结果不明时，先查回执及公众号草稿，不要立即重传。普通 `--rerun` 不会在已有 Media ID 时再建草稿；只有用户明确要求另一个草稿，才走技能中的 `--new-draft` 恢复分支。旧草稿保留。

## Astro 镜像

Astro 仓库不可用、已有预暂存改动或推送失败，不应阻断已验收的微信草稿。记录 `astro_skip_reason`；先查独立仓库状态，再用 `repair-astro hackernews --date YYYY-MM-DD` 补齐缺失文章，并用 `record-astro` 验证已推送的提交。只暂存本次生成的文章，不清理其他人的 Git 状态。

## Product Hunt 月报

月报全部在本仓库 `ph2md` 内运行：`status → fetch → export-plan → audit → render → preview → publish`。`export-plan` 后由编辑者完成 Top 10 计划；裸自动发布不能代替这一步。旧 `publisher <command> producthunt` 入口转交同一流程，`release`、`cover` 等旧基础阶段会给出迁移提示。

默认数据库为 `data/producthunt/producthunt.db`；编辑计划、文稿、图片与回执在 `output/producthunt/`。刷新已有月份前保留数据；刷新事务式替换产品行，重渲染备份已有同月文章与图片。月报直接使用公共微信模块和本部署账号配置，没有 Astro 目标。上传结果不明时，查 `output/producthunt/receipts/publish_YYYYMM.json` 和远端草稿，先确认结果再恢复；已知 Media ID 的月份不会自动重传。旧独立项目的数据需要显式复制迁移，完整步骤见 [Product Hunt 指南](PRODUCTHUNT.md)。
