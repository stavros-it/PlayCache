# AGENTS.md

> Instructions for AI assistants (and human contributors) working on PlayCache.

## Workflow rules

When making any change to the codebase — bug fix, feature, refactor, docs —
**always** do the following before considering the task complete:

1. **Update `PROJECT_CONTEXT.md`** to reflect the new state:
   - File tree (add new files, update LOC counts)
   - Workflow / architecture diagrams if they changed
   - Conventions (new patterns introduced)
   - Known limitations (new gotchas)
   - Test counts and LOC totals

2. **Update `ROADMAP.md`**:
   - Mark relevant items as ✅ done (move from "planned" to "current state")
   - Add a decision log entry at the top of the decision log section explaining
     *what* changed, *why*, and any trade-offs considered

3. **Run quality checks** before committing:
   ```powershell
   python -m pytest tests/ -q
   ruff check playcache/ tests/ run.py run.pyw scripts/
   ```
   Both must pass. Fix any issues before proceeding.

4. **Commit and push** to the GitHub repo:
   ```powershell
   git add -A
   git commit -m "<concise message matching repo style>"
   git push
   ```
   The remote is `https://github.com/stavros-it/PlayCache.git` (already
   configured as `origin` on the `main` branch).

## Pre-push safety check

Before every commit/push, verify that **no secrets or user data** are staged:

```powershell
git ls-files          # tracked files (must NOT include config.ini, *.db, *.xlsx, *.log)
git diff --cached --name-only
```

- `config.ini` (contains API keys) — gitignored, local-only
- `game_library.db` (your catalog) — gitignored, local-only
- `covers/` (cached cover images) — gitignored, local-only
- `*.xlsx`, `*.json.gz`, `*.log` — gitignored

If any of these appear in `git ls-files`, **do not push** — fix `.gitignore`
first and `git rm --cached` the file.

## Commit message style

- Imperative mood: "Add backup feature", not "Added backup feature"
- First line ≤ 72 chars, optionally followed by a blank line and body
- Reference the feature/bug in the first line; details go in the body
- Examples from this repo's history:
  - `Initial commit: PlayCache v1.0.0`
  - `Add app icon + CI badge to README header`

## Code conventions

- **No comments** in code unless explicitly requested
- **Type hints** everywhere; `from __future__ import annotations` at module top
- **Dark theme colors** centralized in `playcache/gui/theme.py` — never hardcode hex
- **No emojis** in source, docs, or UI strings unless explicitly requested
- **Mocked APIs in tests** — no network calls; use canned JSON fixtures

## Repo details

- **Remote**: `origin` → `https://github.com/stavros-it/PlayCache.git`
- **Default branch**: `main`
- **License**: Proprietary (© 2026 Stavros Antoniou, all rights reserved)
- **CI**: GitHub Actions runs ruff + pytest on every push (`.github/workflows/ci.yml`)
