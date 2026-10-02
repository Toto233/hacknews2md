# 微信公众号草稿发布

本项目的“发布到微信”是将一篇已审核的 Markdown 上传到公众号**草稿箱**，返回 Media ID；不会向订阅者群发。日报与 Product Hunt 月报各有独立的来源、编辑和状态门禁，低层上传工具不替代这些门禁。

## 配置与入口

在忽略的 `config/config.json` 中配置 `wechat.appid`、`wechat.appsec`，或使用 `WECHAT_APPID`、`WECHAT_APPSEC`。不要将凭据写进文章、日志或提交。

- Hacker News 日报：从 [发布技能](../skills/publish-hacknews-codex/SKILL.md)和 `scripts/publisher.ps1` 进入。完整发布会在微信草稿后尝试 Astro 同步；仅微信重发需要明确的新草稿意图。
- Product Hunt 编辑月报：从独立 `producthunt-monthly` 项目的 `python -m scripts.publish_producthunt_editorial --year YYYY --month MM --cover-image "<已验收封面>"` 进入。该命令使用本仓库的上传脚本和配置，并将 Media ID 写回月报状态；不会推送 Astro。
- `scripts/publish_wechat.py`：低层 Markdown 转换与上传工具。直接运行它不会执行日报截图、来源或月报 Top 10 审计。

## 发布前本地预检

对已准备的 Markdown 和封面，可运行：

```powershell
python .\scripts\publish_wechat.py "<文章.md>" --cover-image "<封面.png>" --preview
```

预检实际转换正文并检查标题、摘要、来源 URL、正文是否非空、本地图片是否存在且可读取、格式及自动上传的 1 MB 限制，还检查指定封面的尺寸、2.35:1 与 1:1 裁剪和缩略图对比度。失败时退出码非零。它不获取微信 token、不上传图片或草稿；未指定封面时，只能提醒而不能验证尚未生成的封面。目视审查文案准确性、排版和封面文字仍是编辑工作。

## 上传与回执

低层工具将本地正文图片上传并替换成微信图片 URL，指定封面作为题图上传，然后创建草稿。图片缺失、格式不支持、超过自动上传限制或上传失败时，严格图片模式会阻止创建草稿，而不是把缺图稿件算作成功。成功输出 Media ID；月报入口还会保存单月回执并把状态记为 `PUBLISHED`。

对于没有明确成功回执的超时或中断，先查本地回执和公众号草稿，再决定是否重试。已经确认 Media ID 的月报入口直接返回原 ID，不再上传；日报的一般 `--rerun` 也不会绕过重复草稿保护。

## IP 白名单失败

微信 `40164 invalid ip` 表示当前出口 IP 不在公众号白名单。单纯重试同一网络不会解决。日报的[一键补发脚本](../scripts/publish_today_wechat.py)会核对上次被拒绝的 IP 与当前出口 IP：未变化则在本地停下；切换网络后可继续。若已把同一 IP 加入白名单，可显式传 `--whitelist-updated`。该脚本只用当天已经验收的文章和封面，不生成内容，也不推送 Astro。

更详细的日常状态与恢复命令见 [运行手册](RUNBOOK.md)，流程取舍见 [决策记录](DECISIONS.md)。
