# Review

## 2026-10-25 — Uncommitted changes since 14550e1

Backend checks: `uv run --extra dev pytest` 74 passed; `ruff check app tests` clean.

### Code

- **`backend/app/market/stream.py`** — Moving `router` inside `create_stream_router` fixes a real bug: the module-level router collected a duplicate `/prices` route every time the factory was called. The new `tests/market/test_stream.py` covers it. Nit: only one blank line now separates `logger = ...` from `def create_stream_router` (PEP 8 wants two; ruff's default rules don't flag it).
- **`backend/pyproject.toml`** — Adds `litellm` and `python-dotenv` for the upcoming LLM work, and moves `rich` to the `dev` extra, since only the demo uses it. `backend/CLAUDE.md` and `backend/README.md` now say `--extra dev` to match. OK.

### Docs

- **`README.md`** — Rewritten for Groq + OpenRouter. Fixed during review: the Development section said `uv run pytest`, but pytest is in the `dev` extra, so it now says `uv run --extra dev pytest`. The Quick Start needs a `Dockerfile`, which doesn't exist yet. The status note covers this.
- **`planning/PLAN.md`** — Large rewrite. It's consistent with `.env.example` and the new README (Groq primary, OpenRouter free fallback, no Cerebras). Deleting `.claude/skills/cerebras` matches this.
- **`.env.example`, `.gitignore` (`db/*.db`), `db/.gitkeep`** — Match PLAN Section 4/5. `.env` is ignored.

### Tooling / config

- **`.claude/settings.json`** — Drops `frontend-design`, `context7` and `playwright` from the project's enabled plugins and enables only `independent-reviewer@siva-tools`. If other agents or clones rely on those plugins being enabled at project scope, they lose them. The file also lost its trailing newline.
- **`independent-reviewer/hooks/hooks.json`** — An `agent` Stop hook *checks whether a condition is met*. It does not do the work itself. So the hook blocked the session instead of writing the review, and it may block again on stops where no review was written. Consider making the prompt a condition ("planning/REVIEW.md has an entry covering the current changes") or delegating to the `change-reviewer` agent.
- **`.claude-plugin/marketplace.json`** — `"$schema": "https://anthropic.com"` is not a schema URL. Remove it or point it at a real one.
- **`.claude/agents/change-reviewer.md`** — Typo "compehensive" and a stray trailing `"` in the body.
- **`.vscode/settings.json`** — Untracked editor config. Decide whether to commit it or ignore it.
