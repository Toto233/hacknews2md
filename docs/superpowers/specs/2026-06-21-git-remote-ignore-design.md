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
