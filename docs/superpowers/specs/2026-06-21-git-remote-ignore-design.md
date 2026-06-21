# Git Remote and Ignore Design

## Goal

Use the SSH GitHub remote while preventing generated output, private config,
and SQLite runtime files from being committed.

## Remote

The existing `origin` remote will be updated in place to:

```text
git@github.com:Toto233/hacknews2md.git
```

Using `set-url` avoids the failure that `remote add` would produce because
`origin` already exists.

## Ignore Policy

- Ignore all files directly under `config/` unless their filename contains an
  `.example` segment.
- Keep both supported example naming styles tracked:
  `config.json.example` and `deployment.example.json`.
- Ignore all generated files under `output/`.
- Ignore SQLite databases and sidecar files anywhere under `data/`: `.db`,
  `.db-wal`, `.db-shm`, and `.db-journal`.
- Do not stage, overwrite, or revert unrelated working-tree changes.

## Verification

Verify both fetch and push URLs, use `git check-ignore` against representative
private/example/output/database paths, and confirm no forbidden path is tracked
or staged.

## Commit and Remote Integration

- Stage all current project changes that remain eligible after the ignore rules
  are applied.
- Before committing, inspect the staged path list and reject any non-example
  config file, generated output, SQLite database, or SQLite sidecar.
- Commit the allowed project changes without staging ignored local artifacts.
- Rebase the resulting local branch onto `origin/main`. Preserve the current
  project redesign when resolving conflicts, while incorporating remote-only
  changes.
- Run the relevant test suite after the rebase.
- Push `main` normally through the SSH remote. Never use force push or rewrite
  the remote branch.
- If rebase conflicts cannot be resolved safely, abort the rebase and report
  the blocker rather than discarding either side's changes.
