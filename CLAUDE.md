# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AI Career Assistant — an agentic system that automates job searching, ATS scoring, resume creation, and interview prep. FastAPI backend (`api/`) + React frontend (`ui/`).

## Commands

### Backend (`api/`)

```bash
cd api && make dev        # start dev server (excludes .venv from reload watcher)
cd api && make test       # run pytest
cd api && make migrate    # alembic upgrade head
cd api && poetry run python -m alembic revision --autogenerate -m "description"
cd api && poetry install
```

> Never use `uvicorn app.main:app --reload` directly — it watches `.venv/` and crashes if packages are installed while the server is running. Always use `make dev`.
> **Before running `poetry install`**: always stop the server first (`pkill -f uvicorn`), then install, then restart with `make dev`. Installing while the server is running corrupts the venv.

### Frontend (`ui/`)

```bash
cd ui && npm run dev      # Vite, port 5173
cd ui && npm run build
cd ui && npm run lint
cd ui && npm install
cd ui && npm test                # vitest run (single pass)
cd ui && npm run test:watch      # vitest watch mode
cd ui && npm run typecheck       # tsc type check — must pass before every commit
```

> **Before committing any frontend change**: always run `npm test` AND `npm run typecheck`. Both must pass. `npm test` (vitest) does not catch TypeScript type errors — only `typecheck` does.

### Environment

Copy `.env.example` to `api/.env`. Backend reads config from `api/.env` via `pydantic-settings`.

**Database**: PostgreSQL is required for both local dev and production — SQLite is no longer supported.
`make dev` starts Postgres automatically via `docker-compose.dev.yml` (named volume `aicareer-pgdata` persists data across restarts).
Set `DATABASE_URL=postgresql+asyncpg://postgres:dev@localhost:5432/aicareer-db` in `api/.env`.

## Architecture

### LLM backend

**Anthropic (Claude Haiku) is the primary LLM** for the per-task pipelines, via `api/app/shared/api_client.py`:
- `get_classifier_client()` — industry classification (`industry_backfill`)
- `get_scorer_client()` — job-fit scoring (`research_agent`, `request_type == "scoring"`)
- `get_resume_client()` — resume generation (`resume_generate_agent`)

Each returns an `AnthropicClient` on `ANTHROPIC_HAIKU_MODEL` when `ANTHROPIC_API_KEY` is set, and falls back to `get_llm_client()` only if it is empty.

`get_llm_client()` is the legacy global client: `GeminiClient` if `GEMINI_API_KEY` is set, else `OllamaClient` in development (raises `RuntimeError` in production if the Gemini key is missing). It is still used by the non-scoring research path and `industry_refinement`.

**Never infer the active LLM from `.env` key presence or from this file alone** — `.env` can hold stale keys (e.g. an old `GEMINI_API_KEY`). Read `api_client.py` and the call site before stating which provider a task uses.

### Authentication

Dev-mode only — no real auth. Frontend sends email as `X-User-Email` header; the backend auto-creates a user row on first sight. `hashed_password` exists on the `User` model but is always stored empty — it is a placeholder, not a bug.


## Shell working directory

- All backend commands (`poetry`, `pytest`, `alembic`, `uvicorn`) **must** be run from the `api/` directory.
- All frontend commands (`npm`, `vitest`) **must** be run from the `ui/` directory.
- Never assume the shell's current working directory is correct between commands — always `cd` explicitly before each command.

## Behaviour Rules

- **Never make assumptions.** If something is unclear, ask before proceeding.
- **Never hallucinate.** Do not invent facts, file paths, function names, or behaviours that have not been verified by reading the actual code or data.
- **Always show a written plan and wait for explicit approval before touching any files**, running DB patches, or making commits.
- **Always include unit tests** for every change. Commit only after all tests pass.
- **No duplication.** If the same logic is needed in more than one place, extract it into a shared helper first. Never copy-paste logic across files — a single function in a shared module is always preferred.
- **Every task ends with a commit. No exceptions.** The mandatory sequence is: implement → run tests → commit → only then report completion. A task is NOT done until `git commit` has run and the commit SHA appears in the response. Never say "done", "complete", or ask "what's next?" before the commit is made.
