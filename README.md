# AI Career Assistant

An agentic system that automates job searching, ATS scoring, resume creation, and interview prep. FastAPI backend + React frontend.

## Prerequisites

- Python 3.11+ with [Poetry](https://python-poetry.org/)
- Node.js 18+
- [Ollama](https://ollama.com/) for local LLM inference

## Setup

### 1. Ollama + Model

Install Ollama from https://ollama.com, then:

```bash
# Start the Ollama server
ollama serve

# Pull the DeepSeek-R1 model (approx 4.7GB download)
ollama pull deepseek-r1:7b
```

### 2. Backend

```bash
cd api
poetry install
cp ../.env.example .env   # then fill in values
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

### 3. Frontend

```bash
cd ui
npm install
npm run dev               # runs on http://localhost:5173
```

## Environment

Key values to set in `api/.env`:

```
specialist_model=deepseek-r1:7b
coordinator_model=deepseek-r1:7b
```

## Usage

Open http://localhost:5173 in your browser. Enter your email to log in (no password required in dev mode).
