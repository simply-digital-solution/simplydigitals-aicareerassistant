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
cd ui && npm test         # vitest run (single pass)
cd ui && npm run test:watch  # vitest watch mode
```

### Environment

Copy `.env.example` to `api/.env`. Backend reads config from `api/.env` via `pydantic-settings`.

## Architecture

### LLM backend

Uses **Ollama** (local) or **Gemini** (cloud). The factory function `get_llm_client()` in `api/app/shared/api_client.py` returns a `GeminiClient` if `GEMINI_API_KEY` is set in `.env`, otherwise falls back to `OllamaClient`.

- Ollama: `http://localhost:11434`, models configured via `coordinator_model` / `specialist_model` (default: `llama3.1:8b`)
- Gemini: `gemini-2.5-flash-lite` by default, configured via `gemini_model` setting

Agent calls: send prompt → `parse_agent_output()` extracts structured JSON → retries up to `max_self_corrections` via `build_reflexion_prompt()` (both in `api/app/shared/parser.py`) → records run in `agent_runs` + `budget_records` tables.

### Authentication

Dev-mode only, no passwords. Frontend stores email in `localStorage`, sends it as `X-User-Email` header. `get_current_user()` in `api/app/modules/auth/router.py` auto-creates a `User` row (with empty `hashed_password`) on first seen email.

### Agent streaming (SSE)

`POST /api/v1/agents/{research,resume,application,interview,run}` endpoints return `StreamingResponse` (`text/event-stream`). Event types: `status`, `chunk`, `result` (final JSON), `error`, `meta`. Consumed by `ui/src/hooks/useAgentStream.ts`.

### Database

SQLite + WAL at `api/aicareercoach.db`. Alembic migrations in `api/migrations/versions/`. `AuditLog` rows are hash-chained (`prev_hash` + `chain_hash`) for tamper detection.

### Prompts

Agent system prompts live in `prompts/` (project root, not inside `api/`) as markdown files, loaded at runtime. Current prompts: `research.md`, `resume.md`, `resume_generate.md`, `application.md`, `interview.md`, `role_fit.md`, `industry_classifier.md`, `negotiation.md`, `outreach.md`.

### Backend module structure

`api/app/modules/` contains: `agents/`, `admin/`, `applications/`, `auth/`, `notifications/`, `profile/`, `scoring/`, `stats/`.

## Shell working directory

The project root is `/Users/vasu/Documents/Projects/simplydigitals-aicareerassistant`.
- All backend commands (`poetry`, `pytest`, `alembic`, `uvicorn`) **must** be run from `/Users/vasu/Documents/Projects/simplydigitals-aicareerassistant/api` — always use the absolute path prefix: `cd /Users/vasu/Documents/Projects/simplydigitals-aicareerassistant/api &&`
- All frontend commands (`npm`, `vitest`) **must** be run from `/Users/vasu/Documents/Projects/simplydigitals-aicareerassistant/ui` — always use the absolute path prefix: `cd /Users/vasu/Documents/Projects/simplydigitals-aicareerassistant/ui &&`
- Never rely on the shell's current working directory being correct between commands.

## Behaviour Rules

- **Never make assumptions.** If something is unclear, ask before proceeding.
- **Never hallucinate.** Do not invent facts, file paths, function names, or behaviours that have not been verified by reading the actual code or data.
- **Always show a written plan and wait for explicit approval before touching any files**, running DB patches, or making commits.
- **Always include unit tests** for every change. Commit only after all tests pass.
- **Every task ends with a commit. No exceptions.** The mandatory sequence is: implement → run tests → commit → only then report completion. A task is NOT done until `git commit` has run and the commit SHA appears in the response. Never say "done", "complete", or ask "what's next?" before the commit is made.
