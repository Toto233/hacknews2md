# AGENTS.md — hn2md Project Instructions

## Project Overview

**publisher** is the source-driven publishing application. Its HackerNews source scrapes HN front page stories, generates Chinese titles/summaries/rankings/tags via LLM, publishes WeChat drafts, and optionally syncs to Astro.

## Architecture

```
publisher/ (daily CLI orchestration) → hn2md/ + src/ (source implementation) → external services
```

- **`publisher/`**: Canonical source-driven CLI and stage orchestration
- **`hn2md/`**: HackerNews state machine and stages, used internally by `publisher`
- **`src/`**: Core library — fetchers, crawlers, handlers, LLM layer, integrations, utils
- **`scripts/`**: Cover generators + WeChat publisher (used by hn2md stages)
- **`skills/`**: Codex skill definition (legacy, being evaluated for archival)
- **`tests/`**: pytest test suite

**Canonical daily entry point**: `./scripts/publisher.ps1 <command> hackernews`.
`hn2md` is a compatibility/internal CLI; do not add new daily workflow features to it.

## Key Commands

```bash
.\scripts\publisher.ps1 release hackernews              # Full pipeline
.\scripts\publisher.ps1 release hackernews --from-stage COLLECTING  # Resume from a stage
.\scripts\publisher.ps1 release hackernews --dry-run    # Preview without WeChat publish
.\scripts\publisher.ps1 status hackernews               # Current job state and run ledger
.\scripts\publisher.ps1 collect hackernews              # Scrape article content and discussions
.\scripts\publisher.ps1 capture-screenshots hackernews  # Mandatory visual fallback pass
.\scripts\publisher.ps1 audit hackernews                # Content quality gate
.\scripts\publisher.ps1 review-run hackernews           # Post-publish process review
```

## Development Rules

### Security
- **NEVER** pass user-controlled URLs directly to Selenium/crawlers — validate with `src/security/url_validator.py` first
- **NEVER** hardcode API keys, tokens, or secrets — use `config/config.json` or environment variables
- **ALWAYS** use parameterized SQL queries (never f-string interpolation for SQL)
- **ALWAYS** sanitize LLM output before publishing (check for hallucination markers, illegal content)

### Database
- **Use unified connection factory** `src/db/connection.py` for all SQLite access
- **ALWAYS** enable WAL mode and busy_timeout on connections
- **NEVER** open multiple concurrent connections without coordination

### Code Quality
- **No dead code**: `summarize_news3/4/5.py` are archived — do not import or reference
- **Single daily entry point**: Use the `publisher` PowerShell wrapper, not standalone scripts or `hn2md`
- **Type hints**: All public functions must have return type annotations
- **Structured logging**: Use `structlog.get_logger()`, never bare `print()` for operational output

### Testing
- Run tests: `pytest tests/ -v --tb=short`
- Coverage: `pytest tests/ --cov=src --cov-report=term-missing`
- Mark slow tests: `@pytest.mark.slow`
- Mark network tests: `@pytest.mark.network`
- **Mock all external calls** in tests — no real HTTP, no real LLM, no real WeChat API

### Dependencies
- **Single source of truth**: `pyproject.toml` dependencies (sync with `requirements.txt`)
- **Never auto-install packages at runtime** (the `pyperclip` pattern is anti-pattern)
- Pin optional heavy deps in `[project.optional-dependencies]` groups

## File Layout Quick Reference

| Path | Purpose |
|------|---------|
| `hn2md/cli.py` | Click CLI entry point |
| `hn2md/state.py` | Pipeline state machine (JSON ledger) |
| `hn2md/stages/` | Pipeline stage implementations |
| `src/core/fetch_news.py` | HN front page scraping |
| `src/core/crawlers/` | Pluggable content crawlers (Scrapling, Crawl4AI) |
| `src/core/handlers/` | Specialized handlers (Twitter, YouTube, PDF, etc.) |
| `src/llm/llm_utils.py` | LLM routing with failover (Grok → Gemini → Moonshot) |
| `src/llm/providers/` | LLM provider implementations (Gemini, Grok, Moonshot) |
| `src/llm/retry.py` | Unified retry decorator for LLM calls |
| `src/integrations/wechat/` | WeChat module (API client, publisher, access token) |
| `src/integrations/wechat_access_token.py` | WeChat API client (legacy, migrating to wechat/) |
| `src/db/connection.py` | Unified database factory (WAL mode, backup, integrity) |
| `src/security/` | Security module (URL validator, content sanitizer) |
| `src/utils/config.py` | Configuration cascade (env → JSON → defaults) |
| `src/utils/db_utils.py` | Database initialization and utilities |
| `src/utils/logging_setup.py` | Structured logging configuration (structlog) |
| `config/config.json` | API keys and credentials (gitignored) |
| `config/deployment.local.json` | Local paths (gitignored) |

## Known Technical Debt (Tracked)

See `docs/ARCHITECTURE_REDESIGN.md` for the full redesign plan.

**Completed:**
1. ~~SSRF risk~~: URL validator in `src/security/url_validator.py`, integrated into fetch paths
2. ~~State file fragility~~: Atomic write-to-temp + `os.replace()` in `hn2md/state.py`
3. ~~No backup command~~: `hn2md backup` with integrity check and rotation
4. ~~Dead code~~: `summarize_news3/4/5.py` archived, no longer imported
5. ~~Database connections~~: Unified factory in `src/db/connection.py` (WAL + busy_timeout)
6. ~~Retry logic~~: Unified retry decorator in `src/llm/retry.py`
7. ~~Structured logging~~: `structlog` integrated via `src/utils/logging_setup.py`

**Remaining:**
1. **No CI pipeline**: Tests exist but not yet wired to GitHub Actions
2. **Test gaps**: Integration/async/e2e test coverage still thin
3. **WeChat module split**: Migration from `wechat_access_token.py` to `src/integrations/wechat/` in progress
4. **LLM output validation**: Parsers module planned but not yet gating publish

## LLM Provider Notes

- Default provider: `gemini` (configured in `config/config.json`)
- Gemini has model load balancing with circuit breaker (daily disable/enable on quota exhaustion)
- Forbidden Gemini models: 2.5 series (blocked by policy)
- Rate limiting is only enforced for Gemini — Grok and Moonshot have commented-out rate limiters

## Windows-Specific Notes

- Project assumes Windows (PowerShell, ctypes.windll in lock.py)
- WSL detection exists for browser preview (`browser_manager.py`)
- Path handling uses `pathlib.Path` throughout for cross-platform compatibility
