.PHONY: dev test migrate

dev:
	poetry run uvicorn app.main:app --reload --port 8000 \
		--reload-exclude '.venv' \
		--reload-exclude '__pycache__' \
		--reload-exclude '*.pyc' \
		--reload-exclude 'aicareercoach.db*'

test:
	poetry run pytest

migrate:
	poetry run python -m alembic upgrade head
