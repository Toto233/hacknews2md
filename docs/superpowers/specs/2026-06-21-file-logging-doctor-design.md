# File Logging and Doctor Output Design

## Goal

Persist hn2md operational logs while keeping machine-readable command output
clean and fixing the three failing doctor tests before the first GitHub push.

## Logging Architecture

- Write UTF-8 logs to `output/logs/hn2md-YYYYMMDD.log`.
- Create the log directory automatically.
- Normal CLI commands use two handlers: a daily file handler and a human
  console handler writing to stderr.
- Human command results continue to use stdout through `_print`.
- `doctor --json` reconfigures logging as file-only before running checks, so
  stdout contains exactly one JSON document.
- Repeated setup replaces and closes existing handlers to avoid duplicate log
  lines and leaked file handles.

## Doctor Robustness

- `_print` accepts an empty message for intentional blank lines.
- `run_doctor` normalizes context paths with `pathlib.Path`, allowing both
  production `RuntimeContext` values and string-backed test contexts.
- The doctor checks continue to report failures as data rather than raising
  unhandled exceptions.

## Testing

- Preserve the three currently failing tests as regression gates.
- Add logging tests that verify daily file creation, UTF-8 content, stderr
  console routing, file-only mode, and idempotent setup.
- Verify `doctor --json` parses directly without stripping log prefixes.
- Run the complete test suite before committing and pushing.

## Scope

No changes to fetch, summarize, publish, credentials, or generated content.
The existing Git ignore and staged-path security policy remain unchanged.
