.PHONY: install dev test reset migrate revision

install:
	python3 -m venv .venv
	. .venv/bin/activate && pip install -r requirements-dev.txt

dev:
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

test:
	pytest

reset:
	python scripts/reset_demo.py

migrate:
	alembic upgrade head

revision:
	alembic revision --autogenerate -m "$(m)"
