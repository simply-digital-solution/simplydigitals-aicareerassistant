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

`get_llm_client()` returns `GeminiClient` if `GEMINI_API_KEY` is set in `.env`, otherwise `OllamaClient`. This means the active LLM switches silently based on the env var — always check `.env` before assuming which backend is in use.

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
- **Every task ends with a commit. No exceptions.** The mandatory sequence is: implement → run tests → commit → only then report completion. A task is NOT done until `git commit` has run and the commit SHA appears in the response. Never say "done", "complete", or ask "what's next?" before the commit is made.
