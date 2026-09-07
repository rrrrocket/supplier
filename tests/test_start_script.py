from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


ENV_EXAMPLE = """APP_ENV=development
POSTGRES_PASSWORD=replace-with-random-database-password
SESSION_SECRET=replace-with-random-session-secret-at-least-32-characters
ADMIN_EMAIL=admin@example.com
ADMIN_PASSWORD=replace-with-a-strong-admin-password
ADMIN_NAME=平台管理员
APP_URL=http://127.0.0.1:6790
"""


DOCKER_FAKE = """#!/usr/bin/env bash
set -eu

case "$1 ${2:-} ${3:-} ${4:-}" in
  "compose version  ")
    exit 0
    ;;
  "info   ")
    exit 0
    ;;
  "volume ls --quiet --filter")
    if [ "$*" != "volume ls --quiet --filter label=com.docker.compose.project=supplier --filter label=com.docker.compose.volume=supplier_postgres" ]; then
      printf 'wrong volume lookup: %s\n' "$*" >&2
      exit 98
    fi
    if [ "${MOCK_BUSINESS_VOLUME:-absent}" != "absent" ]; then
      printf '%s\\n' "${MOCK_BUSINESS_VOLUME}"
    fi
    exit 0
    ;;
  "run --rm --volume "*)
    case "$*" in
      *":/var/lib/postgresql/data:ro --network none --read-only --entrypoint sh postgres:16-alpine"*) ;;
      *) printf 'volume inspection was not read-only: %s\n' "$*" >&2; exit 97 ;;
    esac
    if [ "${MOCK_VOLUME_INITIALIZED:-0}" = "1" ]; then
      exit 0
    fi
    exit 10
    ;;
  "compose up -d --build"|"compose up -d --wait")
    exit 0
    ;;
  "compose ps -q app")
    printf '%s\\n' app-container
    exit 0
    ;;
  "inspect --format {{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}} app-container")
    printf '%s\\n' healthy
    exit 0
    ;;
  "compose port app 6790")
    printf '%s\\n' 127.0.0.1:6790
    exit 0
    ;;
esac

printf 'unexpected docker call: %s\\n' "$*" >&2
exit 99
"""


def run_start_script(
    tmp_path: Path,
    *,
    volume: str = "absent",
    initialized: bool = False,
    env_contents: str | None = None,
) -> tuple[subprocess.CompletedProcess[str], Path]:
    project = tmp_path / "supplier"
    project.mkdir()
    shutil.copy2(PROJECT_ROOT / "start.sh", project / "start.sh")
    (project / ".env.example").write_text(ENV_EXAMPLE)
    if env_contents is not None:
        (project / ".env").write_text(env_contents)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker = fake_bin / "docker"
    docker.write_text(DOCKER_FAKE)
    docker.chmod(0o755)

    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{fake_bin}:{environment['PATH']}",
            "MOCK_BUSINESS_VOLUME": volume,
            "MOCK_VOLUME_INITIALIZED": "1" if initialized else "0",
        }
    )
    result = subprocess.run(
        ["bash", "start.sh"],
        cwd=project,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    return result, project


@pytest.mark.parametrize("env_contents", [None, "POSTGRES_PASSWORD=replace-me\n"])
def test_start_rejects_missing_database_password_for_initialized_volume(
    tmp_path: Path,
    env_contents: str | None,
) -> None:
    result, project = run_start_script(
        tmp_path,
        volume="supplier_supplier_postgres",
        initialized=True,
        env_contents=env_contents,
    )

    assert result.returncode != 0
    assert "检测到已初始化的 PostgreSQL 业务卷" in result.stdout
    assert "恢复原 .env" in result.stdout
    assert "删除" not in result.stdout
    if env_contents is None:
        assert not (project / ".env").exists()
    else:
        assert (project / ".env").read_text() == env_contents


@pytest.mark.parametrize(
    ("volume", "initialized"),
    [("absent", False), ("supplier_supplier_postgres", False)],
)
def test_start_generates_database_password_only_for_new_database(
    tmp_path: Path,
    volume: str,
    initialized: bool,
) -> None:
    result, project = run_start_script(
        tmp_path,
        volume=volume,
        initialized=initialized,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    generated_env = (project / ".env").read_text()
    assert "POSTGRES_PASSWORD=replace-" not in generated_env
    assert "POSTGRES_PASSWORD=change-me" not in generated_env
    assert "已生成 PostgreSQL 随机密码" in result.stdout
