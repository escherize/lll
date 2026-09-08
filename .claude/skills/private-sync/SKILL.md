---
name: private-sync
description: RETIRED. The project's notes moved onto the lll board (issues, findings, decisions). This skill only says where the archive is.
---

# private-sync (retired 2026-09-08)

`.private/` no longer exists in this checkout. Everything it held was
imported onto the hosted lll board, team `LLL`, by `scripts/import_sidecar.py`:
tasks became issues (each carries `Origin: sidecar TASK-nnn`), wiki pages,
decisions and findings became docs (each carries `Origin: sidecar <path>`).
Worklogs were not imported; they and the full history live in the archived
repo at the url in `.private-remote`, read-only.

Do not clone it back into the checkout, and do not run `backlog`. Use the
`lll` skill: `lll issue list`, `lll finding near PATH`, `lll doc list`.
