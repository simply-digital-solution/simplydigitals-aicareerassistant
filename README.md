# AI Career Assistant

Your one-stop shop for job hunting — from searching and ATS scoring to tailored resume generation and interview prep. FastAPI backend + React frontend, powered by Anthropic Claude.

## Prerequisites

- Python 3.11+ with [Poetry](https://python-poetry.org/)
- Node.js 18+
- An [Anthropic API key](https://console.anthropic.com)

## Setup

### 1. Backend

```bash
cd api
poetry install
cp ../.env.example .env   # fill in ANTHROPIC_API_KEY and DATABASE_URL
make migrate              # alembic upgrade head
make dev                  # starts uvicorn on port 8000
```

### 2. Frontend

```bash
cd ui
npm install
npm run dev               # runs on http://localhost:5173
```

## Environment

Copy `.env.example` to `api/.env` and set at minimum:

```
ANTHROPIC_API_KEY=your-key-here
DATABASE_URL=sqlite+aiosqlite:////absolute/path/to/api/aicareercoach.db
```

See `.env.example` for all available options.

## Usage

Open http://localhost:5173 in your browser. Enter your email to sign in (no password required in dev mode).

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI, SQLAlchemy, Alembic, Poetry |
| Frontend | React, Vite, TypeScript, Tailwind CSS |
| LLM | Anthropic Claude Haiku (classification, scoring, resumes); legacy Gemini / Ollama fallback for other paths |
| Database | SQLite (dev) / PostgreSQL (production) |
| Infra | Docker, AWS EC2 + ECR, S3 + CloudFront, Nginx |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for architecture decisions, local setup, CI/CD pipeline, and team conventions.
