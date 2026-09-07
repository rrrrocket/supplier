.PHONY: dev test migrate revision

dev:
	./start.sh

test:
	./start.sh test

migrate:
	docker compose exec app alembic upgrade head

revision:
	docker compose exec app alembic revision --autogenerate -m "$(m)"
