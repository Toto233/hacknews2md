# CI Portability Fixes Design

## Goal

Make the crawler and daily-lock behavior consistent across the Windows local
environment and Linux GitHub Actions runners.

## Scrapling Compatibility

The project permits multiple Scrapling versions because Crawl4AI and Scrapling
currently impose conflicting lxml constraints. The crawler must therefore avoid
the optional global `Fetcher.configure(adaptive=True)` call, which older
resolver-selected Scrapling versions reject before the mocked or real fetch can
run. Article fetching continues through the shared `Fetcher.get` API with
stealthy headers and existing SSRF validation.

## Lock Portability

PID values less than or equal to zero are invalid lock owners and are treated
as dead before invoking platform process APIs. This prevents Unix
`os.kill(0, 0)` process-group semantics from making a PID 0 lock appear active,
while preserving the existing Windows and positive-PID behavior.

## Testing

- Keep the reported crawler extraction and dead-PID tests as regression gates.
- Add an explicit negative-PID assertion at the `_pid_alive` boundary.
- Run the complete test suite locally after focused tests pass.
- Commit and push normally to `origin/main`; never force push.

## Scope

No crawler selection changes, dependency upgrades, network calls, or lock file
format changes are included.
