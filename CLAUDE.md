# Metafin — Claude Code Instructions

## Git Workflow

- **Never commit directly to `main`.** Always create a feature branch first:
  ```
  git checkout -b feat/<short-description>
  ```
- Branch names: `feat/`, `fix/`, `chore/` prefixes matching the commit type.
- After pushing a branch, open a PR rather than merging locally.

## Commit Style

- Follow Conventional Commits: `feat:`, `fix:`, `chore:`, `refactor:`, `docs:`.
- Scope in parens when useful: `fix(poster):`, `feat(tagger):`.
- One logical change per commit; don't bundle unrelated fixes.

## Code Conventions

- Run `ruff check` and `black --check` before committing. Fix any violations.
