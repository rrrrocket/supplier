FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY alembic.ini pyproject.toml ./
COPY app ./app
COPY migrations ./migrations

FROM base AS test

COPY requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY docker-compose.yml ./
COPY docker-compose.test.yml start.sh ./
COPY deploy/nginx-supplier.conf ./deploy/nginx-supplier.conf
COPY docs ./docs
COPY tests ./tests

CMD ["sh", "-c", "alembic upgrade head && pytest -q"]

FROM base AS runtime

EXPOSE 6790
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 6790 --proxy-headers --forwarded-allow-ips='*'"]
