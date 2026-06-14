# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AI Career Assistant — an agentic system that automates job searching, ATS scoring, resume creation, and interview prep. FastAPI backend (`api/`) + React frontend (`ui/`).

## Commands

### Backend (`api/`)

```bash
cd api && uvicorn app.main:app --reload --port 8000
cd api && python -m pytest
cd api && alembic upgrade head
cd api && alembic revision --autogenerate -m "description"
cd api && poetry install
```

### Frontend (`ui/`)

```bash
cd ui && npm run dev      # Vite, port 5173
cd ui && npm run build
cd ui && npm run lint
cd ui && npm install
```

### Environment

Copy `.env.example` to `api/.env`. Backend reads config from `api/.env` via `pydantic-settings`.

## Architecture

### LLM backend

Uses **Ollama** (local LLM) at `http://localhost:11434`. `get_claude_client()` in `api/app/shared/api_client.py` returns an `OllamaClient` — name kept for backward compatibility. Models configured as `coordinator_model` / `specialist_model` (default: `llama3.1:8b`).

Agent calls: send prompt → `parse_agent_output()` extracts structured JSON → retries up to `max_self_corrections` via `build_reflexion_prompt()` → records run in `agent_runs` + `budget_records`.

### Authentication

Dev-mode only, no passwords. Frontend stores email in `localStorage`, sends it as `X-User-Email` header. `get_current_user()` auto-creates a user row on first seen email.

### Agent streaming (SSE)

All `POST /api/v1/agents/*` endpoints return `StreamingResponse` (`text/event-stream`). Event types: `status`, `chunk`, `result` (final JSON), `error`, `meta`. Consumed by `ui/src/hooks/useAgentStream.ts`.

### Database

SQLite + WAL at `api/aicareercoach.db`. Alembic migrations in `api/migrations/versions/`. `AuditLog` rows are hash-chained (`prev_hash` + `chain_hash`) for tamper detection.

### Prompts

Agent system prompts live in `prompts/` as markdown files, loaded at runtime.
