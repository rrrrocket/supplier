from __future__ import annotations

import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from uuid import uuid4

import psycopg
from psycopg import sql
from sqlalchemy.engine import URL, make_url


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def connect(database_url: URL, database_name: str) -> psycopg.Connection:
    return psycopg.connect(
        host=database_url.host,
        port=database_url.port,
        user=database_url.username,
        password=database_url.password,
        dbname=database_name,
        autocommit=True,
    )


@contextmanager
def temporary_postgresql_database(prefix: str) -> Iterator[URL]:
    server_url = make_url(os.environ["DATABASE_URL"])
    database_name = f"{prefix}_{uuid4().hex}_test"
    database_url = server_url.set(database=database_name)

    with connect(server_url, "postgres") as connection:
        connection.execute(
            sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name))
        )

    try:
        yield database_url
    finally:
        with connect(server_url, "postgres") as connection:
            connection.execute(
                "SELECT pg_terminate_backend(pid) "
                "FROM pg_stat_activity WHERE datname = %s",
                (database_name,),
            )
            connection.execute(
                sql.SQL("DROP DATABASE IF EXISTS {}").format(
                    sql.Identifier(database_name)
                )
            )


def run_migrations(database_url: URL, revision: str) -> None:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url.render_as_string(
        hide_password=False
    )
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", revision],
        cwd=PROJECT_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
