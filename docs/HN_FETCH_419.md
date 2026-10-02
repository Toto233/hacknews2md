# Hacker News `/front` 抓取遇到 HTTP 419

419 不是标准 HTTP 状态码；本项目不能据此断言是登录过期或限流。2026-10-02 的对照请求中，旧的伪 Chrome/120 User-Agent 两次得到 419 和 `Sorry`，改用 `hacknews2md/1.0` 两次得到 200。HN 的内部拒绝规则仍未知。

普通抓取现使用 `hacknews2md/1.0`。再次遇到 419 时，抓取阶段会立即停止，不再对同一请求反复等待重试。先运行 `./scripts/publisher.ps1 status hackernews` 查看回执，确认本次抓取未成功；不要因为浏览器能打开页面就推断程序访问也一定能成功。

如果浏览器可以打开当天实际的 [`/front`](https://news.ycombinator.com/front) 页面，可按页面顺序抄录 story ID，再从仓库根目录执行：

```powershell
.\scripts\publisher.ps1 fetch hackernews --front-ids "<逗号分隔的有序 story ID>"
.\scripts\publisher.ps1 status hackernews
```

需要提供 10–30 个不重复的数字 ID。历史重复、过滤域名、Ask HN 或无效 URL 会被排除，所以应按实际页面顺序提供足够多的候选，确保最终保存 10 条。程序用 HN 官方 item API 核对 ID，沿用原有过滤与 URL 安全检查，回执来源标记为 `browser_front_ids_hn_api`。

不要用 API 的实时 `topstories` 代替当天 `/front` 排名，也不要在页面不可见时猜造 ID。这个入口只恢复选题抓取，正文、讨论、截图、审计和发布门禁照常执行；不应因 419 重复发布已确认成功的草稿。
