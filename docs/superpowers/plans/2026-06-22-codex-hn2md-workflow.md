# Codex + hn2md Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `publish-hacknews-codex` compose `hn2md` subcommands while keeping Codex as the sole model for manual title, summary, ranking, and tag generation.

**Architecture:** Add a validated manual-plan path to the existing PLANNING stage and carry its artifact through APPLYING and RENDERING receipts. Move deterministic collection and rendering behavior behind reusable hn2md modules, then make CLI stages call reusable cover and WeChat APIs with explicit arguments.

**Tech Stack:** Python 3.10+, Click, SQLite, asyncio, structlog/logging, pytest, unittest.mock

---

## File map

- Create `hn2md/manual_plan.py`: load, validate, normalize, and copy Codex plans.
- Create `hn2md/rendering.py`: render Markdown, HTML, and optional Astro output from an ordered plan.
- Create `hn2md/collection.py`: async context collection and snapshot generation using runtime paths.
- Modify `hn2md/cli.py`: pass declared options into stages and add manual-plan/target-word options.
- Modify `hn2md/stages/{collect,plan,apply,render,cover,publish}.py`: use the reusable APIs and receipt chain.
- Modify `skills/publish-hacknews-codex/SKILL.md`: replace direct project-script entry points with hn2md commands.
- Create focused tests under `tests/hn2md/` for manual plans, rendering, collection, CLI forwarding, cover, and publish.

### Task 1: Forward CLI arguments into stages

**Files:**
- Modify: `hn2md/cli.py`
- Test: `tests/hn2md/test_cli_stage_options.py`

- [ ] **Step 1: Write failing CLI forwarding tests**

Use `CliRunner`, patch `JobStateMachine.load_or_create`, `daily_lock`, and `_load_stage`, then assert calls such as:

```python
result = runner.invoke(main, ["--project-root", str(root), "collect", "--concurrency", "5"])
assert result.exit_code == 0
stage.run.assert_called_once_with(runtime_ctx, machine, concurrency=5)
```

Cover `plan --manual-plan`, `apply PLAN`, `cover MARKDOWN --mode ai --target-word WORD`, and `publish MARKDOWN --cover-image COVER` in the same test module.

- [ ] **Step 2: Run the focused tests and verify failure**

Run: `pytest tests/hn2md/test_cli_stage_options.py -v --tb=short`

Expected: FAIL because CLI currently drops every stage-specific argument.

- [ ] **Step 3: Pass options through and add new Click options**

Implement these calls:

```python
stage.run(rt, machine, concurrency=concurrency)
stage.run(rt, machine, llm=llm, manual_plan_file=manual_plan_file)
stage.run(rt, machine, plan_file=plan_file)
stage.run(rt, machine, markdown_file=markdown_file, mode=mode, target_word=target_word)
stage.run(rt, machine, markdown_file=markdown_file, cover_image=cover_image)
```

Add `@click.option("--manual-plan", "manual_plan_file", type=click.Path(exists=True))` to `plan` and `@click.option("--target-word", default=None)` to `cover`. Add return type annotations to touched public functions.

- [ ] **Step 4: Run focused tests**

Run: `pytest tests/hn2md/test_cli_stage_options.py -v --tb=short`

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add hn2md/cli.py tests/hn2md/test_cli_stage_options.py
git commit -m "fix: forward hn2md stage options"
```

### Task 2: Add validated manual Codex plan import

**Files:**
- Create: `hn2md/manual_plan.py`
- Modify: `hn2md/stages/plan.py`
- Test: `tests/hn2md/test_manual_plan.py`
- Test: `tests/hn2md/test_plan_stage.py`

- [ ] **Step 1: Write plan validation tests**

Test a valid plan and reject missing/duplicate/mismatched data:

```python
valid = {
    "tags": ["AI", "开发", "开源", "安全"],
    "ordered_ids": [2, 1],
    "items": [
        {"id": 1, "title_chs": "标题一", "content_summary": "足够长的正文摘要" * 3, "discuss_summary": "讨论摘要"},
        {"id": 2, "title_chs": "标题二", "content_summary": "足够长的正文摘要" * 3, "discuss_summary": "讨论摘要"},
    ],
}
assert validate_manual_plan(valid)["ordered_ids"] == [2, 1]
```

Assert `ManualPlanError` for duplicate IDs, an `ordered_ids` set mismatch, non-four-tag input, empty required text, and hallucination markers.

- [ ] **Step 2: Run validation tests and verify failure**

Run: `pytest tests/hn2md/test_manual_plan.py -v --tb=short`

Expected: FAIL because `hn2md.manual_plan` does not exist.

- [ ] **Step 3: Implement the manual-plan module**

Define the public API:

```python
class ManualPlanError(ValueError):
    """Raised when a Codex plan cannot enter the publish pipeline."""

def validate_manual_plan(plan: object) -> dict[str, Any]: ...

def import_manual_plan(source: Path, destination_dir: Path) -> Path: ...
```

Validate exact ID correspondence, four non-empty unique tags, and non-empty publish fields. Reuse `contains_hallucination_markers` and `validate_summary_length`; write a normalized UTF-8 JSON copy atomically beneath `destination_dir`.

- [ ] **Step 4: Write PlanStage no-LLM tests**

Patch `src.llm.llm_business.generate_summary`, `translate_title`, evaluator, and tag extractor to raise if called. Execute:

```python
result = PlanStage().execute(ctx, machine, manual_plan_file=str(source))
assert Path(result["plan_file"]).parent == ctx.codex_dir
assert result["manual"] is True
```

- [ ] **Step 5: Implement manual mode before LLM imports**

Change the signature to:

```python
def execute(
    self,
    ctx: RuntimeContext,
    machine: JobStateMachine,
    llm: str | None = None,
    manual_plan_file: str | None = None,
) -> dict[str, Any]:
```

When `manual_plan_file` is present, call `import_manual_plan()` and return its receipt data before importing any `src.llm` module. Preserve automatic mode and route `llm` through the existing provider selection mechanism if supported; otherwise reject unsupported explicit overrides clearly.

- [ ] **Step 6: Run manual and automatic plan tests**

Run: `pytest tests/hn2md/test_manual_plan.py tests/hn2md/test_plan_stage.py -v --tb=short`

Expected: all tests PASS and no mocked LLM is called in manual mode.

- [ ] **Step 7: Commit**

```bash
git add hn2md/manual_plan.py hn2md/stages/plan.py tests/hn2md/test_manual_plan.py tests/hn2md/test_plan_stage.py
git commit -m "feat: import Codex plans through hn2md"
```

### Task 3: Move Codex context collection behind CollectStage

**Files:**
- Create: `hn2md/collection.py`
- Modify: `hn2md/stages/collect.py`
- Test: `tests/hn2md/test_collection.py`

- [ ] **Step 1: Write mocked collection tests**

Create a temporary SQLite `news` table and mock crawler, discussion, screenshot, and image functions. Assert that:

```python
result = asyncio.run(collect_context(ctx, concurrency=2))
assert result["count"] == 1
assert result["concurrency"] == 2
assert Path(result["context_file"]).exists()
```

Also verify the DB stores article/discussion text, screenshot, and three image paths, with no real network calls.

- [ ] **Step 2: Run collection tests and verify failure**

Run: `pytest tests/hn2md/test_collection.py -v --tb=short`

Expected: FAIL because `collect_context` does not exist.

- [ ] **Step 3: Implement reusable async collection**

Expose:

```python
async def collect_context(ctx: RuntimeContext, concurrency: int = 3) -> dict[str, Any]: ...
```

Use `get_db(str(ctx.db_path))`, `asyncio.Semaphore(max(1, concurrency))`, the crawler abstraction, discussion handler, screenshot saver, and article image saver. Query the current local date, commit each completed result through one coordinated connection, and write `hacknews_context_<timestamp>.json` to `ctx.codex_dir`.

- [ ] **Step 4: Make CollectStage call the service**

Use a synchronous stage adapter:

```python
def execute(self, ctx, machine, concurrency: int = 3) -> dict[str, Any]:
    return asyncio.run(collect_context(ctx, concurrency=max(1, concurrency)))
```

Do not retain direct crawler/database logic in the stage.

- [ ] **Step 5: Run tests**

Run: `pytest tests/hn2md/test_collection.py tests/hn2md/test_stages.py -v --tb=short`

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add hn2md/collection.py hn2md/stages/collect.py tests/hn2md/test_collection.py
git commit -m "feat: collect Codex context through hn2md"
```

### Task 4: Carry the plan through ApplyStage

**Files:**
- Modify: `hn2md/stages/apply.py`
- Test: `tests/hn2md/test_apply_stage.py`

- [ ] **Step 1: Write explicit and receipt plan tests**

Build a temporary DB and assert both lookup modes update only parameterized IDs:

```python
result = ApplyStage().execute(ctx, machine, plan_file=str(plan_path))
assert result == {"updated": 2, "plan_file": str(plan_path.resolve())}
```

Also test missing files and malformed plans fail before writes.

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/hn2md/test_apply_stage.py -v --tb=short`

Expected: explicit plan test FAIL because the stage does not accept `plan_file`.

- [ ] **Step 3: Implement plan resolution and validation**

Change the signature to accept `plan_file: str | None = None`, otherwise read PLANNING receipt. Load using the manual-plan validation function, update with `?` placeholders, and return the resolved path for the RENDERING receipt chain.

- [ ] **Step 4: Run tests**

Run: `pytest tests/hn2md/test_apply_stage.py -v --tb=short`

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add hn2md/stages/apply.py tests/hn2md/test_apply_stage.py
git commit -m "feat: apply validated hn2md plans"
```

### Task 5: Render ordered Codex output through hn2md

**Files:**
- Create: `hn2md/rendering.py`
- Modify: `hn2md/stages/render.py`
- Test: `tests/hn2md/test_rendering.py`

- [ ] **Step 1: Write rendering tests**

Seed rows in reverse DB order, supply `ordered_ids=[2, 1]`, and assert the generated Markdown places item 2 first, contains exactly the four plan tags, safely quotes quotes/colon/newlines in frontmatter, creates HTML, and returns `astro_file=None` when Astro is disabled.

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/hn2md/test_rendering.py -v --tb=short`

Expected: FAIL because the rendering service does not exist and the stage ignores the plan.

- [ ] **Step 3: Implement the rendering service**

Expose:

```python
def yaml_quote(value: object) -> str: ...

def render_plan(
    ctx: RuntimeContext,
    plan_file: Path,
    *,
    now: datetime | None = None,
) -> dict[str, str | None]: ...
```

Fetch each ID with parameterized SQL through `get_db`, preserve plan order, generate Markdown and HTML under `ctx.markdown_dir`, and resolve optional Astro output through the existing deployment settings. Return `markdown_file`, `html_file`, `astro_file`, and `plan_file`.

- [ ] **Step 4: Update RenderStage receipt lookup**

Resolve the plan from APPLYING, then PLANNING as a compatibility fallback:

```python
apply_receipt = machine.job.stages.get(Stage.APPLYING.value, {})
plan_file = apply_receipt.get("output_summary", {}).get("plan_file")
if not plan_file:
    raise RuntimeError("No plan file from APPLYING stage")
return render_plan(ctx, Path(plan_file))
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/hn2md/test_rendering.py -v --tb=short`

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add hn2md/rendering.py hn2md/stages/render.py tests/hn2md/test_rendering.py
git commit -m "feat: render ordered Codex plans with hn2md"
```

### Task 6: Fix CoverStage and PublishStage reusable API calls

**Files:**
- Modify: `hn2md/stages/cover.py`
- Modify: `hn2md/stages/publish.py`
- Modify: `tests/hn2md/test_publish_dry_run.py`
- Create: `tests/hn2md/test_cover_stage.py`
- Create: `tests/hn2md/test_publish_stage.py`

- [ ] **Step 1: Write failing API-call tests**

Patch `scripts.generate_wechat_cover_ai.generate_cover_ai`, `scripts.generate_wechat_cover.generate_cover`, and `scripts.publish_wechat.publish_to_wechat`. Assert exact explicit arguments and receipt fallbacks. Assert argparse `main` is never referenced.

- [ ] **Step 2: Run focused tests and verify failure**

Run: `pytest tests/hn2md/test_cover_stage.py tests/hn2md/test_publish_stage.py tests/hn2md/test_publish_dry_run.py -v --tb=short`

Expected: non-dry-run tests FAIL with the current `main()` signature mismatch.

- [ ] **Step 3: Implement CoverStage API selection**

Use:

```python
if mode == "ai":
    from scripts.generate_wechat_cover_ai import generate_cover_ai
    cover_path = generate_cover_ai(md_file, target_word=target_word)
elif mode == "pillow":
    from scripts.generate_wechat_cover import generate_cover
    cover_path = generate_cover(md_file)
else:
    raise ValueError(f"Unsupported cover mode: {mode}")
```

Accept explicit `markdown_file`, otherwise use RENDERING receipt.

- [ ] **Step 4: Implement PublishStage reusable call**

Accept `markdown_file` and `cover_image`, fall back to receipts, preserve safety and dry-run gates, then call:

```python
from scripts.publish_wechat import publish_to_wechat
media_id = publish_to_wechat(md_file, cover_image=cover)
```

- [ ] **Step 5: Run focused tests**

Run: `pytest tests/hn2md/test_cover_stage.py tests/hn2md/test_publish_stage.py tests/hn2md/test_publish_dry_run.py -v --tb=short`

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add hn2md/stages/cover.py hn2md/stages/publish.py tests/hn2md/test_cover_stage.py tests/hn2md/test_publish_stage.py tests/hn2md/test_publish_dry_run.py
git commit -m "fix: call reusable cover and publish APIs"
```

### Task 7: Rewrite publish-hacknews-codex around hn2md

**Files:**
- Modify: `skills/publish-hacknews-codex/SKILL.md`
- Test: `tests/hn2md/test_codex_skill_contract.py`

- [ ] **Step 1: Write the skill contract test**

Read SKILL.md and assert required commands exist while forbidden legacy project entry points do not:

```python
text = skill_path.read_text(encoding="utf-8")
for command in ["hn2md fetch", "hn2md collect", "hn2md plan --manual-plan", "hn2md apply", "hn2md render", "hn2md cover", "hn2md publish"]:
    assert command in text
for legacy in ["src\\core\\fetch_news.py", "apply_news_edits.py", "render_manual_markdown.py", "generate_wechat_cover_ai.py", "publish_wechat.py"]:
    assert legacy not in text
```

- [ ] **Step 2: Run contract test and verify failure**

Run: `pytest tests/hn2md/test_codex_skill_contract.py -v --tb=short`

Expected: FAIL because the skill still invokes standalone scripts.

- [ ] **Step 3: Rewrite the skill workflow**

Document fetch/collect, DB quality gate, Codex context reading and plan generation, `hn2md plan --manual-plan`, apply/render, target-word cover, WeChat publish, optional Astro exact-file commit, and image-directory opening. State explicitly that manual-plan mode must not call Gemini/Grok/Moonshot.

- [ ] **Step 4: Run contract test**

Run: `pytest tests/hn2md/test_codex_skill_contract.py -v --tb=short`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/publish-hacknews-codex/SKILL.md tests/hn2md/test_codex_skill_contract.py
git commit -m "docs: compose Codex publishing with hn2md"
```

### Task 8: End-to-end mocked workflow and full verification

**Files:**
- Create: `tests/hn2md/test_codex_manual_workflow.py`
- Modify: `docs/RUNBOOK.md`

- [ ] **Step 1: Write a mocked stage-chain test**

Run COLLECTING through PUBLISHING with a temporary DB and manual plan while mocking all network, LLM, image generation, and WeChat calls. Assert state receipts carry `context_file -> plan_file -> markdown_file -> cover_image -> wechat_media_id`, and assert every external LLM mock has zero calls.

- [ ] **Step 2: Run the workflow test and fix only integration defects**

Run: `pytest tests/hn2md/test_codex_manual_workflow.py -v --tb=short`

Expected: PASS after resolving any receipt-key or signature mismatch exposed by integration.

- [ ] **Step 3: Update the runbook**

Add the canonical Codex workflow:

```powershell
hn2md fetch
hn2md collect --concurrency 3
hn2md plan --manual-plan <plan.json>
hn2md apply
hn2md render
hn2md cover <markdown.md> --target-word <short-title>
hn2md publish <markdown.md> --cover-image <cover.png>
```

Explain that `hn2md release` without a manual plan uses configured external LLMs and is not the Codex skill path.

- [ ] **Step 4: Run all tests**

Run: `pytest tests/ -v --tb=short`

Expected: all tests PASS; network, LLM, image, and WeChat calls remain mocked.

- [ ] **Step 5: Run static repository checks**

Run: `rg -n "summarize_news[345]|scripts\\publish_wechat.py|scripts\\generate_wechat_cover_ai.py" hn2md skills/publish-hacknews-codex`

Expected: no archived summarizer references; SKILL.md contains no direct script entry points.

- [ ] **Step 6: Commit**

```bash
git add tests/hn2md/test_codex_manual_workflow.py docs/RUNBOOK.md
git commit -m "test: verify Codex manual hn2md workflow"
```

## Self-review

- Spec coverage: every approved requirement maps to Tasks 1-8.
- External-call safety: all collection, LLM, image, Astro, and WeChat interactions are mocked or remain outside automated tests.
- State continuity: PLANNING imports the Codex plan before APPLYING, so no state transition bypass is required.
- Type consistency: `manual_plan_file`, `plan_file`, `markdown_file`, `cover_image`, and `target_word` names remain consistent from CLI through stage APIs and receipts.
- Scope control: no new LLM provider, service, or Astro pipeline stage is introduced.
