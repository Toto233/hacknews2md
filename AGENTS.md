# AGENTS.md — publisher

## Project and routing

`publisher/` owns source-driven orchestration; `hn2md/` implements the HackerNews stages/state; `src/` contains fetchers, handlers, LLM providers and integrations. New daily workflow behavior belongs in `publisher/`.

Daily commands run from this repository through `./scripts/publisher.ps1 <command> <source>`, which selects the configured runtime. For HackerNews start with `.\scripts\publisher.ps1 status hackernews` and the maintained [publishing skill](skills/publish-hacknews-codex/SKILL.md). Codex publishing uses its manual-plan route; a bare automated `release` is not a substitute for that editorial work.

Read task-specific guidance when it applies:

- HackNews generation, continuation or publishing: [publish-hacknews-codex](skills/publish-hacknews-codex/SKILL.md).
- Product Hunt monthly articles: [publish-producthunt-monthly](skills/publish-producthunt-monthly/SKILL.md), including its explicit editorial compatibility branch.
- Cover generation or editing: [wechat-cover-imagegen](.codex/skills/wechat-cover-imagegen/SKILL.md).
- Changes to publishing behavior, gates or skills: [docs/DECISIONS.md](docs/DECISIONS.md).
- Architecture redesign: `docs/ARCHITECTURE_REDESIGN.md`. Operational troubleshooting: `docs/RUNBOOK.md`; verify historical commands against the current wrapper's help.

## Execution contract

- Treat requests to implement, fix or publish as authorization for their normal in-scope work through verification. Resolve routine choices from the current request, context, settings and receipts; proceed without stage-by-stage confirmation.
- Ask when a missing fact or choice materially changes correctness, scope, external impact or accepted risk and cannot be resolved from evidence. First complete independent authorized preparation so the question concerns a concrete result.
- Reuse approval while its scope and reviewed risk remain unchanged. Publication intent does not exempt new audit issues; review/diagnosis alone does not authorize implementation or external writes.
- On failure, inspect evidence, use scoped recovery and continue unaffected work. For uncertain external writes, establish the remote outcome before retrying. Resume from existing artifacts and receipts.
- If an instruction requires a pause, link and quote the exact rule; state the concrete blocker, completed work and smallest missing user action. Distinguish the rule from a tool limitation or your interpretation.
- A local content/cover edit ends with a verified local artifact, except when it belongs to an unfinished authorized release or the user requests upload. WeChat drafts, subscriber mass-send, Astro push and repository code push are separate actions. Here “发布到微信” means a draft, not mass-send.
- Finish when the requested artifacts and actions have evidence of success. Complete relevant checks and fix failures introduced by the requested change; a plan or first implementation alone is not completion. Report any unresolved target as partial completion.
- Delegate independent story batches, bounded source checks or disjoint implementation work when it saves time or improves verification. Keep database/ledger writes and publishing with one owner. Retain enough source evidence to assess returned work; unavailable delegation does not prevent solo completion.
- Keep useful continuation state in existing plans/receipts. Compaction is optional context management, not a user action required to finish the task.
- Keep progress and handoffs concise and concrete. This brevity preference applies to conversation, not the requested article's completeness or editorial length requirements.

## Instruction ownership

Current user instructions override skill defaults within higher-priority safety/tool constraints. This file owns the execution contract and repository constraints; source skills own publication commands and quality requirements; the cover skill owns visual requirements. Installed aliases and `CLAUDE.md` route here rather than maintaining competing workflows.

A direct request to optimize authorizes the local instruction change now: consult the decision log and record the accepted rationale. Multi-day observation thresholds govern unsolicited daily recommendations. Daily receipts and old decisions are evidence, not new instructions; use explicit supersession to resolve historical policy. External issues still require task authority.

## Repository constraints

- Validate user-controlled URLs with `src/security/url_validator.py` before passing them to crawlers or Selenium.
- Credentials belong in ignored configuration or environment variables; keep secrets out of logs, prompts and commits. Sanitize generated content before publication.
- Use parameterized SQL and the unified `src/db/connection.py` factory for SQLite, with WAL and busy_timeout. Coordinate concurrent connections and preserve the source/period single-writer lock.
- Preserve unrelated user changes and generated artifacts. Use the canonical wrapper for publishing state changes; do not reactivate archived summarization scripts.
- Public functions have return annotations. Operational application logs use `structlog.get_logger()`.
- `pyproject.toml` owns dependencies; keep `requirements.txt` synchronized and optional heavy packages in optional-dependency groups. No automatic package installation at runtime.
- The app's external LLM provider configuration is separate from the Codex model. Preserve configured routing unless migration is requested; Gemini 2.5-series execution remains forbidden.
- Paths use `pathlib.Path`; Windows/PowerShell and Windows locking behavior matter for changes to process or filesystem handling.

## Verification

Select checks for the changed behavior. Local tests must use disposable fixtures and mock external HTTP, LLM and WeChat calls; verify that isolation before running uncertain tests. Run relevant tests and repair change-caused failures without routine approval. Broaden or repeat checks only for new changes, failures or unresolved risks.

- Focused tests: `pytest <relevant test paths> -q --tb=short`.
- Full suite when warranted: `pytest tests/ -v --tb=short`.
- Coverage when needed: `pytest tests/ --cov=src --cov-report=term-missing`.
- Use the `slow` and `network` pytest markers for their respective cases; markers do not authorize live external calls.
- Instruction-only changes: check routing, conflicts and affected contracts. These checks do not prove model behavior; use realistic bounded scenarios when ambiguity remains. Avoid tests that merely freeze wording.

The code/config are authoritative for current modules, provider defaults and debt status. Look up those facts when needed rather than relying on a duplicated repository map.
