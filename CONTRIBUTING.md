# Contributing to AI Career Assistant

## Table of Contents

1. [Project structure](#project-structure)
2. [Local development setup](#local-development-setup)
3. [Architecture decisions](#architecture-decisions)
4. [Database — dual-dialect SQL](#database--dual-dialect-sql)
5. [Adding a new API module](#adding-a-new-api-module)
6. [Frontend conventions](#frontend-conventions)
7. [Testing](#testing)
8. [CI/CD pipeline](#cicd-pipeline)
9. [Deploying to production](#deploying-to-production)
10. [GitHub Secrets reference](#github-secrets-reference)
11. [Using Claude Code on this project](#using-claude-code-on-this-project)

---

## Project structure

```
.
├── api/                  # FastAPI backend (Python 3.11, Poetry)
│   ├── app/
│   │   ├── main.py       # FastAPI app + lifespan (scheduler guard)
│   │   ├── modules/      # Feature modules (router + schemas per module)
│   │   │   ├── admin/
│   │   │   ├── agents/
│   │   │   ├── applications/
│   │   │   ├── auth/
│   │   │   ├── notifications/
│   │   │   ├── profile/
│   │   │   ├── scoring/
│   │   │   └── stats/
│   │   ├── pipeline/     # Scheduler + agentic pipeline
│   │   └── shared/       # Cross-cutting helpers (sql_compat, llm, config…)
│   ├── migrations/       # Alembic migrations
│   ├── tests/
│   ├── Dockerfile
│   ├── Makefile
│   └── pyproject.toml
├── ui/                   # React 19 frontend (Vite, TypeScript, Tailwind 4)
│   ├── src/
│   │   ├── api/          # Axios API clients
│   │   ├── components/   # Feature components
│   │   ├── hooks/        # Custom React hooks
│   │   └── pages/        # Top-level page components
│   └── public/           # Static assets (favicons, manifest)
├── nginx/                # Nginx config for production
├── prompts/              # LLM prompt markdown files (read-only at runtime)
├── docker-compose.prod.yml
├── .github/workflows/    # CI/CD pipelines
├── CLAUDE.md             # AI assistant instructions (read by Claude Code)
└── CONTRIBUTING.md       # This file
```

---

## Local development setup

### Prerequisites

- Python 3.11+
- [Poetry](https://python-poetry.org/docs/#installation)
- Node.js 20+
- [Ollama](https://ollama.com) (optional — only needed if you don't have a Gemini API key)

### Backend

```bash
cd api
cp ../.env.example .env        # then edit .env with your values
poetry install
make migrate                   # run all Alembic migrations
make dev                       # starts on http://localhost:8000
```

> **Never** run `uvicorn app.main:app --reload` directly — it watches `.venv/` and crashes
> when packages are installed while it's running. Always use `make dev`.

> **Before `poetry install`**: stop the server first (`pkill -f uvicorn`), install, then
> restart. Installing while the server is running corrupts the venv.

### Frontend

```bash
cd ui
npm install
npm run dev                    # starts on http://localhost:5173
```

The Vite dev server proxies `/api` to `http://localhost:8000` — both must be running.

### LLM setup

The backend picks its LLM automatically from `.env`:

- **Gemini** (recommended): set `GEMINI_API_KEY` in `.env` — uses `gemini-2.5-flash-lite` by default
- **Ollama** (local/offline): leave `GEMINI_API_KEY` empty — install Ollama and pull `deepseek-r1:7b`

The switch is silent — always check `.env` if LLM behaviour seems wrong.

### Login

Dev mode has no real auth. Enter any email address on the login page — the backend
auto-creates a user row on first sight.

---

## Architecture decisions

### Why EC2, not Lambda

The scheduler and agentic pipeline are long-running processes (persistent loops, APScheduler
jobs). Lambda's execution model doesn't support this. EC2 t2.micro gives us always-on
processes within AWS free tier.

### Why Unix socket, not TCP port

In production, Gunicorn binds to `/run/app/app.sock` (a Unix socket shared as a Docker
volume between the `api` and `nginx` containers). This avoids hardcoded port numbers and
port conflicts when multiple services run on the same host.

### Why three containers

| Container | Role |
|-----------|------|
| `api` | Gunicorn + Uvicorn workers, `ENABLE_SCHEDULER=false` |
| `scheduler` | Runs `app.scheduler_worker` — cron jobs + scorer loop, no HTTP |
| `nginx` | SSL termination, HTTP→HTTPS redirect, proxies to `api` via Unix socket |

The scheduler runs in its own container so a crash there doesn't take down the API, and
vice versa. `ENABLE_SCHEDULER` in `app/main.py` prevents double-scheduling.

### Why SQLite in dev, PostgreSQL in prod

SQLite requires zero infrastructure locally. PostgreSQL is used in production (RDS).
All dialect-sensitive SQL goes through `api/app/shared/sql_compat.py` — never write
raw SQLite-specific or PostgreSQL-specific SQL directly in routers or services.

### Frontend on S3 + CloudFront, not EC2

Static assets don't need the EC2 instance. S3 + CloudFront gives global CDN, immutable
cache headers for hashed assets, and free-tier eligible storage. The EC2 instance only
serves the API.

---

## Database — dual-dialect SQL

`api/app/shared/sql_compat.py` is the single source of truth for any SQL that differs
between SQLite and PostgreSQL. Import from it; never write dialect-specific SQL inline.

```python
from app.shared.sql_compat import days_ago, months_ago, month_trunc, nulls_last, get_dialect

_dialect = get_dialect(get_settings().database_url)  # computed once at module load

# Date arithmetic
since = days_ago(30)          # returns ISO date string, works in both dialects

# Column formatting
col = month_trunc("created_at", _dialect)   # strftime vs TO_CHAR

# Ordering
order = nulls_last("score DESC", _dialect)  # IS NULL workaround for SQLite
```

When adding a new query that uses dates, truncation, or NULL ordering — add the helper
to `sql_compat.py` first, then use it everywhere it's needed.

### Running migrations

```bash
# Apply all pending migrations
cd api && make migrate

# Create a new migration after changing a model
cd api && poetry run python -m alembic revision --autogenerate -m "describe the change"
```

Migrations run automatically in CI as a one-shot `migrate` container before `api` starts.

---

## Adding a new API module

1. Create `api/app/modules/<name>/` with `__init__.py`, `router.py`, `schemas.py`
2. Register the router in `api/app/main.py`
3. If the module needs new DB tables, create a migration (`alembic revision --autogenerate`)
4. Add tests under `api/tests/`
5. If any SQL is dialect-sensitive, add helpers to `sql_compat.py` first

---

## Frontend conventions

- **API calls**: all go through `ui/src/api/client.ts` — never use `fetch` directly
- **State**: React Query (`@tanstack/react-query`) for server state, Zustand for local UI state
- **Styling**: Tailwind 4 utility classes — no custom CSS files
- **Components**: feature components live in `ui/src/components/`, page-level in `ui/src/pages/`
- **No logic duplication**: shared helpers go in `ui/src/hooks/` or a shared utility file

---

## Testing

### Backend

```bash
cd api && make test                          # run all tests
cd api && poetry run pytest tests/path.py -v  # run a specific file
```

Tests use SQLite in-memory (`sqlite+aiosqlite:///:memory:`) — no external dependencies needed.
Every PR must include tests for new logic. No exceptions.

### Frontend

```bash
cd ui && npm test                # single pass (Vitest)
cd ui && npm run test:watch      # watch mode
cd ui && npm run test:coverage   # with v8 coverage report
```

---

## CI/CD pipeline

Four workflow files in `.github/workflows/`:

| File | Purpose |
|------|---------|
| `orchestrator.yml` | Entry point — detects changed paths, fans out to the others |
| `api-ci.yml` | Lint → tests → security scan → Docker build → EC2 deploy |
| `ui-ci.yml` | Lint → tests → npm audit → Vite build → S3 deploy |
| `post-deploy-tests.yml` | Smoke tests against live production API + UI |

**When each stage runs:**

| Trigger | API | UI |
|---------|-----|----|
| Push to feature branch | Lint only | Lint only |
| Pull request to main | Lint + tests + security | Lint + tests + audit |
| Merge to main | Deploy to EC2 | Deploy to S3/CloudFront |
| Git tag `v*.*.*` | Full pipeline | Full pipeline |

All secrets are stored in GitHub — never in code. The CI pipeline writes a `.env` file
to the EC2 instance at deploy time via SSH.

---

## Deploying to production

### AWS resources needed (one-time setup)

- **ECR** repository for the Docker image
- **EC2** t2.micro with Docker, Docker Compose, and AWS CLI installed
- **RDS** PostgreSQL (db.t3.micro, free tier)
- **S3** bucket with static website hosting
- **CloudFront** distribution pointing to the S3 bucket (SPA error pages → `index.html`)
- **IAM** user with ECR push, S3 sync, and CloudFront invalidation permissions

### SSL certificates on EC2

```bash
# On the EC2 instance (one-time)
sudo apt install certbot
sudo certbot certonly --standalone -d yourdomain.com
```

Certificates are mounted read-only into the `nginx` container from `/etc/letsencrypt`.

### First deploy

Once GitHub Secrets are configured (see below), push to `main` — the pipeline handles everything:
build → push to ECR → SSH into EC2 → `docker compose pull` → restart → migrate → health check.

---

## GitHub Secrets reference

All of these must be set under **Settings → Secrets and variables → Actions** before
the pipeline can deploy.

| Secret | Description |
|--------|-------------|
| `AWS_ACCESS_KEY_ID` | IAM user access key |
| `AWS_SECRET_ACCESS_KEY` | IAM user secret |
| `AWS_ACCOUNT_ID` | 12-digit AWS account ID |
| `AWS_REGION` | e.g. `ap-southeast-1` |
| `ECR_REPOSITORY` | ECR repo name (not full URI) |
| `EC2_HOST` | Public IP or domain of the EC2 instance |
| `EC2_USER` | SSH user (e.g. `ubuntu`) |
| `EC2_SSH_KEY` | Private SSH key (PEM content) |
| `DATABASE_URL` | `postgresql+asyncpg://user:pass@rds-host:5432/dbname` |
| `JWT_SECRET_KEY` | Random secret, min 32 chars |
| `GEMINI_API_KEY` | From Google AI Studio |
| `HCAPTCHA_SECRET_KEY` | hCaptcha server-side secret |
| `GOOGLE_CLIENT_ID` | Google OAuth2 client ID (Drive integration) |
| `GOOGLE_CLIENT_SECRET` | Google OAuth2 client secret |
| `S3_UI_BUCKET` | S3 bucket name for the frontend |
| `CLOUDFRONT_DISTRIBUTION_ID` | CloudFront distribution ID (optional — skips invalidation if absent) |
| `PROD_API_URL` | Full API base URL, e.g. `https://api.yourdomain.com` |
| `PROD_UI_URL` | Full frontend URL, e.g. `https://yourdomain.com` |
| `VITE_HCAPTCHA_SITE_KEY` | hCaptcha site key (public, safe in build) |

---

## Using Claude Code on this project

This repo includes `.claude/` — Claude Code's memory directory. It stores learned context
about this project (decisions made, patterns to follow, things to avoid) and is shared via
git so all teammates benefit from the same AI context automatically.

Read `CLAUDE.md` for the full set of rules Claude follows on this project.
