# Codex + hn2md Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `publish-hacknews-codex` compose existing `hn2md` subcommands while keeping Codex as the model for titles, summaries, ranking, and tags.

**Architecture:** Reuse the existing collector, manual renderer, cover generator, and WeChat publisher. Existing argparse scripts gain callable functions with explicit paths; existing hn2md stages call those functions and pass artifacts through receipts. No new functional Python module is introduced.

**Tech Stack:** Python, Click, SQLite, asyncio, pytest, unittest.mock

---

## File map

- Modify `hn2md/cli.py`: forward existing options and add `--manual-plan`/`--target-word`.
- Modify `hn2md/stages/plan.py`: validate and import a Codex plan without loading an LLM.
- Modify `hn2md/stages/{collect,apply,render,cover,publish}.py`: call existing capabilities with explicit arguments.
- Modify `skills/publish-hacknews-codex/scripts/collect_news_context.py`: expose existing collection as a callable function.
- Modify `skills/publish-hacknews-codex/scripts/render_manual_markdown.py`: expose existing rendering as a callable function.
- Modify `skills/publish-hacknews-codex/SKILL.md`: use hn2md commands as the project entry point.
- Add only focused test files under `tests/hn2md/`.

### Task 1: Forward CLI arguments

**Files:**
- Modify: `hn2md/cli.py`
- Test: `tests/hn2md/test_cli_stage_options.py`

- [ ] Write failing `CliRunner` tests asserting these calls:

```python
stage.run(rt, machine, concurrency=5)
stage.run(rt, machine, llm=None, manual_plan_file=str(plan))
stage.run(rt, machine, plan_file=str(plan))
stage.run(rt, machine, markdown_file=str(md), mode="ai", target_word="主体事件")
stage.run(rt, machine, markdown_file=str(md), cover_image=str(cover))
```

- [ ] Run `pytest tests/hn2md/test_cli_stage_options.py -v --tb=short`; expect failures because options are currently dropped.
- [ ] Add `plan --manual-plan` and `cover --target-word`, pass all declared options to `stage.run()`, and add return annotations to touched public functions.
- [ ] Re-run the focused test; expect PASS.
- [ ] Commit with `git commit -m "fix: forward hn2md stage options"`.

### Task 2: Import Codex plans through the existing PlanStage

**Files:**
- Modify: `hn2md/stages/plan.py`
- Test: `tests/hn2md/test_plan_stage.py`

- [ ] Write failing tests for a valid four-tag plan and invalid duplicate IDs, mismatched `ordered_ids`, empty publish fields, and hallucination markers.
- [ ] In the valid test, patch all `src.llm` entry points to raise if called and assert:

```python
result = PlanStage().execute(ctx, machine, manual_plan_file=str(plan_path))
assert result["manual"] is True
assert result["story_count"] == 2
assert Path(result["plan_file"]).parent == ctx.codex_dir
```

- [ ] Run `pytest tests/hn2md/test_plan_stage.py -v --tb=short`; expect failure because manual mode is absent.
- [ ] Add private `_validate_manual_plan()` and `_import_manual_plan()` helpers directly to `plan.py`. Validate unique IDs, exact ordered-ID correspondence, four unique tags, required text, summary length, and hallucination markers.
- [ ] Change `execute()` to accept `llm: str | None` and `manual_plan_file: str | None`. Return from manual mode before importing any LLM module; preserve current automatic mode.
- [ ] Re-run the focused test; expect PASS and zero external LLM calls.
- [ ] Commit with `git commit -m "feat: import Codex plans through hn2md"`.

### Task 3: Reuse the existing Codex collector

**Files:**
- Modify: `skills/publish-hacknews-codex/scripts/collect_news_context.py`
- Modify: `hn2md/stages/collect.py`
- Test: `tests/hn2md/test_collection.py`

- [ ] Write a failing test with a temporary DB and mocked crawler, discussion, image, and screenshot helpers. Assert article/discussion/images are stored and a context JSON is produced.
- [ ] Run `pytest tests/hn2md/test_collection.py -v --tb=short`; expect failure because collection is only exposed through argparse `main()`.
- [ ] Extract the existing body into:

```python
async def collect_context(
    ctx: RuntimeContext,
    concurrency: int = 3,
    hours: int = 18,
) -> dict[str, Any]:
    ...
```

Use `ctx.db_path` and `ctx.codex_dir`, the unified DB factory, the current helper functions, and one coordinated writer connection. Keep `main()` as a wrapper that parses arguments and calls `collect_context()`.
- [ ] Replace duplicate logic in `CollectStage.execute()` with `asyncio.run(collect_context(ctx, concurrency))`.
- [ ] Run `pytest tests/hn2md/test_collection.py tests/hn2md/test_stages.py -v --tb=short`; expect PASS.
- [ ] Commit with `git commit -m "refactor: reuse Codex collector from hn2md"`.

### Task 4: Pass the plan through ApplyStage

**Files:**
- Modify: `hn2md/stages/apply.py`
- Test: `tests/hn2md/test_apply_stage.py`

- [ ] Write failing tests for explicit `plan_file` and PLANNING-receipt fallback.
- [ ] Run `pytest tests/hn2md/test_apply_stage.py -v --tb=short`; expect the explicit-path test to fail.
- [ ] Accept `plan_file: str | None`, fall back to the PLANNING receipt, verify the required `items` shape, preserve parameterized SQL, and return the resolved plan path.
- [ ] Re-run the focused test; expect PASS.
- [ ] Commit with `git commit -m "fix: pass plan artifacts through apply stage"`.

### Task 5: Reuse the existing manual renderer

**Files:**
- Modify: `skills/publish-hacknews-codex/scripts/render_manual_markdown.py`
- Modify: `hn2md/stages/render.py`
- Test: `tests/hn2md/test_rendering.py`

- [ ] Write a failing test with DB order `[1, 2]` and plan order `[2, 1]`. Assert item 2 renders first, four tags are preserved, YAML strings are escaped, and Markdown/HTML paths are returned.
- [ ] Run `pytest tests/hn2md/test_rendering.py -v --tb=short`; expect failure because rendering is only exposed through argparse `main()`.
- [ ] Refactor the existing script body into:

```python
def render_manual_markdown(
    ctx: RuntimeContext,
    plan_file: Path,
    *,
    now: datetime | None = None,
) -> dict[str, str | None]:
    ...
```

Use `ctx.db_path`/`ctx.markdown_dir`, parameterized queries, current YAML escaping and HTML conversion, and existing optional Astro settings. Keep `main()` as a compatibility wrapper.
- [ ] Make `RenderStage` obtain `plan_file` from APPLYING receipt and call `render_manual_markdown()`.
- [ ] Re-run the focused test; expect PASS.
- [ ] Commit with `git commit -m "refactor: reuse manual renderer from hn2md"`.

### Task 6: Use existing cover and publish APIs correctly

**Files:**
- Modify: `hn2md/stages/cover.py`
- Modify: `hn2md/stages/publish.py`
- Test: `tests/hn2md/test_cover_stage.py`
- Test: `tests/hn2md/test_publish_stage.py`
- Modify: `tests/hn2md/test_publish_dry_run.py`

- [ ] Write failing tests patching `generate_cover_ai`, `generate_cover`, and `publish_to_wechat`; assert argparse `main()` is not called.
- [ ] Run the focused tests; expect current function-signature failures.
- [ ] In CoverStage, resolve explicit Markdown or receipt fallback and call:

```python
generate_cover_ai(md_file, target_word=target_word)  # ai
generate_cover(md_file)                              # pillow
```

- [ ] In PublishStage, resolve explicit paths or receipts, retain safety/dry-run gates, then call `publish_to_wechat(md_file, cover_image=cover)`.
- [ ] Run `pytest tests/hn2md/test_cover_stage.py tests/hn2md/test_publish_stage.py tests/hn2md/test_publish_dry_run.py -v --tb=short`; expect PASS.
- [ ] Commit with `git commit -m "fix: reuse cover and publish APIs"`.

### Task 7: Rewrite the skill around hn2md subcommands

**Files:**
- Modify: `skills/publish-hacknews-codex/SKILL.md`
- Test: `tests/hn2md/test_codex_skill_contract.py`

- [ ] Write a contract test requiring `hn2md fetch`, `collect`, `plan --manual-plan`, `apply`, `render`, `cover`, and `publish`, and rejecting direct project-script commands.
- [ ] Run the test; expect failure against the current skill.
- [ ] Rewrite the skill while retaining DB quality gates, Codex plan generation, failed-domain handling, optional Astro exact-file commit, and image-directory opening. State that manual-plan mode never calls Gemini/Grok/Moonshot.
- [ ] Re-run the contract test; expect PASS.
- [ ] Commit with `git commit -m "docs: compose Codex publishing with hn2md"`.

### Task 8: Integration verification

**Files:**
- Test: `tests/hn2md/test_codex_manual_workflow.py`
- Modify: `docs/RUNBOOK.md`

- [ ] Add a mocked stage-chain test verifying receipt flow `context_file -> plan_file -> markdown_file -> cover_image -> wechat_media_id` and zero external LLM calls.
- [ ] Run `pytest tests/hn2md/test_codex_manual_workflow.py -v --tb=short`; fix only integration mismatches until PASS.
- [ ] Document the canonical composable workflow in RUNBOOK.
- [ ] Run `pytest tests/ -v --tb=short`; expect all tests PASS with no real HTTP, LLM, image, or WeChat calls.
- [ ] Run `rg -n "summarize_news[345]" hn2md skills/publish-hacknews-codex`; expect no archived summarizer references.
- [ ] Commit with `git commit -m "test: verify Codex manual hn2md workflow"`.

## Self-review

- All approved behavior is covered without adding functional Python modules.
- Existing scripts retain their CLI wrappers, so compatibility is preserved.
- Manual PLANNING preserves state transitions and prevents external LLM use.
- Every external call is mocked in tests.
