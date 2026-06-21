# Changelog

## 0.2.0 (2026-06-20)

### Architecture
- Split `llm_utils.py` god module (973->635 lines) into config/rate_limit/balancer/daily_status
- Archived legacy `summarize_news.py` monolith
- Unified DB connections in hn2md/stages/ (all use `get_db()`)
- Replaced 122 `print()` calls with structured logging
- Wired `setup_logging()` into CLI entry point

### Security
- SSRF protection in all 9 fetch paths
- YAML/HTML injection prevention
- Secret redaction in error logs
- Content safety gate (illegal keywords + hallucination detection)
- Atomic state file writes with backup recovery

### Testing
- 392 tests (from 0)
- Handler pure-function tests (52)
- Provider tests (28)
- State machine tests (17)
- Retry decorator tests (12)
- Dry-run publish tests (2)

### Infrastructure
- pyproject.toml with build-system + 24 deps
- GitHub Actions CI workflow
- Pre-commit hooks (ruff)
- Makefile with test/lint/format targets
- .gitignore production-ready

### New CLI Features
- `hn2md release --dry-run` — preview without publishing
- `hn2md release --backup/--no-backup` — auto-backup before pipeline
- `hn2md doctor --json` — CI-ready health check
- `hn2md backup` — manual database backup

## 0.1.0 (initial)
- Initial release
