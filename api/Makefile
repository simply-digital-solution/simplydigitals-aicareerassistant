.PHONY: dev test migrate db-start db-stop

db-start:
	docker-compose -f ../docker-compose.dev.yml up -d
	@echo "Waiting for Postgres to be ready..."
	@until docker exec aicareer-pg pg_isready -U postgres > /dev/null 2>&1; do sleep 1; done
	@echo "Postgres is ready."

db-stop:
	docker-compose -f ../docker-compose.dev.yml down

dev: db-start
	poetry run uvicorn app.main:app --reload --port 8000 \
		--reload-exclude '.venv' \
		--reload-exclude '__pycache__' \
		--reload-exclude '*.pyc'

test: db-start
	poetry run pytest

migrate: db-start
	poetry run python -m alembic upgrade head
