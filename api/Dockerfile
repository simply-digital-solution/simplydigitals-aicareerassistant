# ─────────────────────────────────────────────────────────────────────────────
# Stage 1 — install dependencies
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

# Install build tools needed for packages with C extensions (lxml, asyncpg)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Poetry and export dependencies to a plain requirements file
RUN pip install --no-cache-dir poetry==1.8.3

COPY pyproject.toml poetry.lock ./
RUN poetry export --without dev --without-hashes -f requirements.txt -o requirements.txt

# Install into an isolated directory so the runtime stage stays clean
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ─────────────────────────────────────────────────────────────────────────────
# Stage 2 — runtime image
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.11-slim

# Runtime lib needed by asyncpg / psycopg drivers
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy pre-built packages from builder
COPY --from=builder /install /usr/local

# Copy application source
COPY app/ ./app/
COPY alembic.ini ./
COPY migrations/ ./migrations/

# Prompts live at the project root — mounted as a volume at runtime.
# Create the directory so the path always exists even without the mount.
RUN mkdir -p /prompts

ARG APP_VERSION=dev
LABEL org.opencontainers.image.version=${APP_VERSION}

# No EXPOSE — the container binds to a Unix socket, not a TCP port.
# The socket path is passed via the GUNICORN_BIND env var.

CMD ["gunicorn", "app.main:app", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--workers", "2", \
     "--bind", "unix:/run/app/app.sock", \
     "--timeout", "120", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
