# hn2md 发布质量门禁设计

## 目标

为每日 Hacker News 发布流程增加可追溯的内容来源、强制人工审计门禁、正确的终态、结构化图片异常报告，以及严格的 Astro 提交门禁。

## 范围

本次处理五项问题：

1. 403/付费墙回退内容缺少来源类型和出处。
2. Codex 生成 plan 前没有强制审计。
3. 单独执行 `hn2md publish` 成功后 ledger 停在 `PUBLISHING`。
4. 图片采集失败和超大图片跳过只存在于日志。
5. Astro `git diff --cached --check` 失败后仍可能提交。

不处理 Audit、Domain、Schema 的其他历史重复代码；仅做支撑本门禁所必需的 schema 迁移。

## 内容来源模型

在现有 `news` 和 `news_history` 表增加：

- `content_source_type TEXT`：`full_text`、`public_abstract`、`metadata_only`、`discussion_only`。
- `content_source_url TEXT`：实际提供内容的页面或 API 记录 URL。
- `content_source_doi TEXT`：论文 DOI；非论文为空。

采集器成功取得正文时写入：

```text
content_source_type = full_text
content_source_url = news_url
content_source_doi = NULL
```

公开摘要不能称为“正文”。写入时必须标记 `public_abstract`，保存摘要来源 URL 和 DOI。只有标题、作者、日期等书目信息时标记 `metadata_only`；仅能依赖 HN 讨论时标记 `discussion_only`。

本次不增加自动 Crossref 回退。Codex 或人工找到可信公开摘要后，通过现有 hn2md audit 能力记录内容和来源，避免自动匹配到错误论文。

## 强制审计与当日豁免

Skill 在 collect 后、Codex 生成 plan 前必须运行：

```powershell
hn2md audit --json
```

审计报告至少包含：

- 新闻 ID、标题和原始 URL；
- 正文、摘要和讨论长度；
- `content_source_type`、来源 URL、DOI；
- 问题代码、严重级别和说明。

以下问题形成硬门禁：

- 正文为空或明显过短；
- 来源类型为空或未知；
- `metadata_only` 或 `discussion_only`；
- `public_abstract` 缺少来源 URL；
- 论文公开摘要缺少 DOI；
- 中文摘要或讨论摘要为空；
- 登录页、错误页或幻觉标记。

存在门禁问题时，Skill 必须把完整清单反馈给用户并暂停。用户明确同意发布后，Skill 执行：

```powershell
hn2md audit --approve
```

ledger 记录当日 job 的：

```json
{
  "audit_exemption": {
    "approved_at": "ISO-8601",
    "issue_snapshot": []
  }
}
```

豁免只对当天整批新闻有效，次日不会继承。没有“永久豁免”或域名级豁免。

PlanStage 和 PublishStage 都检查当日审计结果：无问题可继续；有问题但没有当日豁免则拒绝执行；存在当日豁免则继续并在 receipt 中标记 `audit_exempted: true`。这样即使绕过 Skill 直接执行 CLI，也不能跳过门禁。

## 状态终结

单独执行 `hn2md publish` 时，PublishStage 成功 receipt 写入后，CLI 将状态从 `PUBLISHING` 转为 `DONE`。

`hn2md release` 只在当前状态不是 `DONE` 时执行最终转换，避免重复 `PUBLISHING -> DONE`。Dry-run 不创建微信草稿，但成功完成预演后同样进入 `DONE`，receipt 保留 `dry_run: true`。

## 图片异常结构化报告

图片操作结果统一保留成功路径和失败信息，不再仅返回 `None`。

Collect receipt 增加：

```json
{
  "image_failures": [
    {
      "news_id": 123,
      "image_url": "https://example/image.svg",
      "reason": "unsupported_svg|decode_failed|file_locked|http_error|validation_failed"
    }
  ]
}
```

兼容现有 `save_article_image()` 返回值；在同一现有模块增加详细结果接口供 CollectStage 调用，旧调用方不受影响。并发文件名必须包含新闻 ID 和图片序号，避免不同任务争用同一路径。

微信发布结果改为同时返回 media ID 与跳过清单：

```json
{
  "wechat_media_id": "...",
  "skipped_images": [
    {"path": "...", "reason": "oversize", "size_bytes": 1234567}
  ]
}
```

PublishStage 将其原样写入 receipt，Skill 最终汇报。

## Astro 门禁

Skill 的 Astro 步骤改为严格顺序：

1. `git status --short`；
2. 只 add 本次 `astro_file`；
3. `git diff --cached --check`；
4. 非零立即停止，禁止 commit/push；
5. 检查通过后 commit、push。

渲染器输出 Astro Markdown 时先 `rstrip()`，再追加一个换行，避免文件尾空白触发检查。

## 错误处理

- Audit 报告生成失败：停止，不允许豁免未知结果。
- 用户未明确同意：不写豁免。
- 来源 URL/DOI 记录失败：保留门禁问题，不降级放行。
- 图片失败不自动阻止发布，但必须出现在 receipt 和最终汇报中。
- 微信发布失败：不得进入 `DONE`。
- Astro 检查失败不影响已创建的微信草稿，但 Astro 不提交，并明确报告两边状态不同。

## 测试

- Schema 升级兼容已有 SQLite 数据库，并同步 history 表。
- 来源类型写入、公开摘要校验和审计 JSON 输出。
- 有问题无豁免时 Plan/Publish 被拒绝；当日豁免后放行；次日豁免失效。
- 单独 publish 和 release 均正确进入 `DONE`，失败时不进入。
- SVG、解码、文件锁和超大图片进入结构化 receipt。
- Astro diff-check 失败时不调用 commit/push；输出只有一个文件尾换行。
- 所有 HTTP、图片、LLM、微信和 Git 外部调用在测试中 mock。
