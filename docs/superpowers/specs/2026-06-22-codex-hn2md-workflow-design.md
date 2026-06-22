# Codex + hn2md 可组合发布流程设计

## 目标

将 `publish-hacknews-codex` 从直接调用仓库脚本迁移到 `hn2md` 统一 CLI，同时保留 Codex 作为标题翻译、摘要、讨论摘要、排序和标签生成模型。`hn2md` 负责抓取、内容采集、plan 导入、数据库更新、渲染、题图和微信公众号发布。

## 非目标

- 不让 Codex skill 改用 Gemini、Grok 或 Moonshot。
- 不要求一次 `hn2md release` 完成包含 Codex 推理的全流程。
- 不新增后台服务或新的 LLM provider。
- 不把 Astro Git 提交合并进 hn2md 状态机；它仍是 skill 的可选收尾动作。

## 用户工作流

基础流程由可组合子命令组成：

```powershell
hn2md fetch
hn2md collect --concurrency 3
# Codex 读取 collect 产出的 context JSON，并生成 plan JSON
hn2md plan --manual-plan ".\output\codex\hacknews_plan_YYYYMMDD_HHMMSS.json"
hn2md apply
hn2md render
hn2md cover ".\output\markdown\hacknews_summary_YYYYMMDD_HHMM.md" --target-word "主体 + 事件"
hn2md publish ".\output\markdown\hacknews_summary_YYYYMMDD_HHMM.md" --cover-image ".\output\images\YYYYMMDD\hacknews_cover_ai_YYYYMMDD.png"
```

导入 plan 后，也可用以下命令继续剩余阶段：

```powershell
hn2md release --from-stage APPLYING
```

Skill 可以根据质量检查结果单独重跑 `collect`、`audit`、`cover` 或 `publish`，不依赖固定的一键脚本。

## 设计边界

### 1. 内容采集

`CollectStage` 接收 `concurrency`，直接调用现有 `collect_news_context.py` 中提取出的可调用函数，保留当前 Codex collector 的行为：

- 采集正文和 HN 讨论；
- 保存前三张图片和页面截图；
- 使用统一数据库连接工厂写回；
- 在 `output/codex` 生成包含全文上下文的 JSON；
- receipt 返回 `context_file`、数量和 concurrency。

CLI 不替 Codex 判定内容是否足够。Skill 在 collect 后继续执行数据库质量门禁、失败域名记录和空讨论补抓。

### 2. 手工 Codex plan

`hn2md plan` 新增互斥选项 `--manual-plan PATH`。校验逻辑放在现有 `PlanStage` 中，不新建功能模块。传入时：

- 读取并验证 JSON 顶层 `items`、`ordered_ids` 和 `tags`；
- 校验 item ID 唯一、排序 ID 与 item ID 集合一致；
- 校验每项包含非空的 `title_chs`、`content_summary` 和 `discuss_summary`；
- 对文本执行现有幻觉标记与摘要长度检查；
- 将规范化副本写入 `output/codex`，并在 PLANNING receipt 中记录路径；
- 不导入或调用任何 LLM provider。

未传 `--manual-plan` 时，保留当前自动 LLM 规划行为和 `--llm` 参数。

### 3. Apply 与 Render

`ApplyStage` 默认读取 PLANNING receipt 中的 plan，也继续支持显式 `plan_file` 参数。它使用参数化 SQL 更新数据库，并在 receipt 中保留 plan 路径。

`RenderStage` 从 APPLYING receipt 获取同一 plan，严格按照 `ordered_ids` 渲染，并使用 plan 中的四个 tags。现有 `render_manual_markdown.py` 提取一个接收显式路径的可调用函数，argparse `main()` 保留为兼容包装。渲染产物包括 Markdown、HTML 和可选 Astro Markdown，路径全部写入 receipt。

### 4. Cover 与 Publish

`CoverStage` 接收显式 Markdown、`mode` 和 `target_word`：

- AI 模式调用 `generate_cover_ai()`；
- Pillow 模式调用 `generate_cover()`；
- 未给 Markdown 时回退到 RENDERING receipt。

`PublishStage` 接收显式 Markdown、题图和 `dry_run`，调用可复用的 `publish_to_wechat()`，不调用 argparse `main()`。未传路径时分别回退到 RENDERING 和 COVERING receipts。现有内容安全门禁保持不变。

### 5. 复用原则

本次不新增功能性 Python 模块。仅修改现有 CLI、stage 和脚本：脚本保留命令行入口，同时暴露薄的可调用函数给 `hn2md` 使用。新增文件仅限隔离外部调用的测试文件。

### 6. CLI 参数传递

所有已声明参数必须传给 stage：

- `collect`: `concurrency`
- `plan`: `llm`、`manual_plan_file`
- `apply`: `plan_file`
- `cover`: `markdown_file`、`mode`、`target_word`
- `publish`: `markdown_file`、`cover_image`

每个公开函数保留返回类型标注，操作日志继续进入 structlog 配置的日志目录。

## 状态机与失败处理

手工 plan 仍经过正常 `COLLECTING -> PLANNING -> APPLYING` 状态转换，不绕过 ledger。Plan 验证失败时记录失败 receipt，且不得修改数据库。题图生成失败时由 skill 决定是否重试；若继续发布，可省略 `--cover-image` 触发公众号发布器的首图回退。

## 测试策略

- CLI 测试验证每个选项确实传给 stage。
- PlanStage 测试验证手工 plan 导入、无外部 LLM 调用和非法 plan 拒绝。
- CollectStage 测试 mock 所有网络、截图和图片下载调用。
- Apply/Render 测试验证排序、tags、YAML 转义和 receipt 链路。
- Cover/Publish 测试验证调用可复用 API，而不是脚本 `main()`。
- 完整测试在 Windows 与 Linux 兼容路径下运行，不进行真实 HTTP、LLM 或微信调用。

## Skill 迁移

`skills/publish-hacknews-codex/SKILL.md` 改为以 `hn2md` 子命令为唯一项目入口。Codex 仍直接完成 plan 内容生成；数据库检查、失败记录、Astro 精确提交和打开图片目录保留为 skill 编排步骤。
