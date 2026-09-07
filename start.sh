#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

ACTION="${1:-start}"
TEST_COMPOSE_FILE="$PROJECT_DIR/docker-compose.test.yml"
TEST_PROJECT_NAME="supplier-tests"

require_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    echo "未找到 Docker。请先安装 Docker Engine 和 Docker Compose 插件。"
    exit 1
  fi
  if ! docker compose version >/dev/null 2>&1; then
    echo "未找到 docker compose。请安装 Docker Compose 插件。"
    exit 1
  fi
  if ! docker info >/dev/null 2>&1; then
    echo "Docker 服务未运行，或当前用户没有 Docker 权限。"
    exit 1
  fi
}

random_secret() {
  od -An -N32 -tx1 /dev/urandom | tr -d ' \n'
}

env_value() {
  sed -n "s/^${1}=//p" .env | tail -n 1 | tr -d '"'
}

set_env_value() {
  local key="$1"
  local value="$2"
  local temp_file
  temp_file="$(mktemp "${TMPDIR:-/tmp}/supplier-env.XXXXXX")"
  awk -v key="$key" -v value="$value" '
    BEGIN { updated = 0 }
    $0 ~ "^" key "=" { print key "=" value; updated = 1; next }
    { print }
    END { if (!updated) print key "=" value }
  ' .env > "$temp_file"
  mv "$temp_file" .env
}

compose_project_name() {
  local configured_name="${COMPOSE_PROJECT_NAME:-}"
  if [ -z "$configured_name" ] && [ -f .env ]; then
    configured_name="$(env_value COMPOSE_PROJECT_NAME)"
  fi
  if [ -z "$configured_name" ]; then
    configured_name="$(basename "$PROJECT_DIR")"
  fi
  printf '%s' "$configured_name" \
    | tr '[:upper:]' '[:lower:]' \
    | sed -E 's/[^a-z0-9_-]+//g; s/^[^a-z0-9]+//'
}

business_volume_name() {
  local project_name
  project_name="$(compose_project_name)"
  docker volume ls --quiet \
    --filter "label=com.docker.compose.project=$project_name" \
    --filter "label=com.docker.compose.volume=supplier_postgres" \
    | head -n 1
}

business_volume_initialized() {
  local volume_name
  local inspect_status
  volume_name="$(business_volume_name)"
  if [ -z "$volume_name" ]; then
    return 1
  fi

  if docker run --rm \
    --volume "$volume_name:/var/lib/postgresql/data:ro" \
    --network none \
    --read-only \
    --entrypoint sh \
    postgres:16-alpine \
    -c 'test -f /var/lib/postgresql/data/PG_VERSION || exit 10'; then
    return 0
  else
    inspect_status=$?
  fi
  if [ "$inspect_status" -eq 10 ]; then
    return 1
  fi
  echo "无法只读检查 PostgreSQL 业务卷初始化状态，启动已停止。"
  exit 1
}

prepare_env() {
  local postgres_password
  local session_secret
  local admin_email
  local admin_password
  postgres_password=""
  if [ -f .env ]; then
    postgres_password="$(env_value POSTGRES_PASSWORD)"
  fi
  if [ -z "$postgres_password" ] || [[ "$postgres_password" == replace-* ]] || [ "$postgres_password" = "change-me" ]; then
    if business_volume_initialized; then
      echo "检测到已初始化的 PostgreSQL 业务卷，但 POSTGRES_PASSWORD 缺失或仍为占位值。"
      echo "请恢复原 .env 或从安全备份恢复原数据库密码后重试；为保护现有数据，启动已停止。"
      exit 1
    fi
  fi

  if [ ! -f .env ]; then
    cp .env.example .env
    echo "已根据 .env.example 创建 .env"
  fi

  postgres_password="$(env_value POSTGRES_PASSWORD)"
  session_secret="$(env_value SESSION_SECRET)"
  admin_email="$(env_value ADMIN_EMAIL)"
  admin_password="$(env_value ADMIN_PASSWORD)"

  if [ -z "$postgres_password" ] || [[ "$postgres_password" == replace-* ]] || [ "$postgres_password" = "change-me" ]; then
    set_env_value POSTGRES_PASSWORD "$(random_secret)"
    echo "已生成 PostgreSQL 随机密码"
  fi
  if [ -z "$session_secret" ] || [[ "$session_secret" == replace-* ]] || [[ "$session_secret" == dev-only-* ]]; then
    set_env_value SESSION_SECRET "$(random_secret)"
    echo "已生成 Session 随机密钥"
  fi
  if [ -z "$admin_email" ]; then
    set_env_value ADMIN_EMAIL "admin@matrix-one.tech"
  fi
  if [ -z "$admin_password" ] || [[ "$admin_password" == replace-* ]]; then
    set_env_value ADMIN_PASSWORD "$(random_secret)"
    echo "已生成管理员密码，请在 .env 的 ADMIN_PASSWORD 中查看"
  fi
  if [ -z "$(env_value ADMIN_NAME)" ]; then
    set_env_value ADMIN_NAME "平台管理员"
  fi

  chmod 600 .env
}

wait_for_app() {
  local container_id
  local health_status
  echo "正在等待应用健康检查..."

  for _ in $(seq 1 60); do
    container_id="$(docker compose ps -q app)"
    if [ -n "$container_id" ]; then
      health_status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container_id" 2>/dev/null || true)"
      if [ "$health_status" = "healthy" ]; then
        return 0
      fi
      if [ "$health_status" = "exited" ] || [ "$health_status" = "dead" ]; then
        break
      fi
    fi
    sleep 2
  done

  echo "应用启动失败，最近日志如下："
  docker compose logs --tail=100 app
  exit 1
}

start_stack() {
  prepare_env
  echo "正在构建并启动 Docker 服务..."
  if [ "$ACTION" = "restart" ]; then
    docker compose up -d --build --force-recreate --remove-orphans
  else
    docker compose up -d --build --remove-orphans
  fi
  wait_for_app

  local published_address
  local app_url
  published_address="$(docker compose port app 6790)"
  app_url="$(env_value APP_URL)"

  printf '\nMatrix One Supplier Network 已启动。\n'
  printf '  本机监听：http://%s\n' "$published_address"
  if [ -n "$app_url" ]; then
    printf '  配置域名：%s\n' "$app_url"
  fi
  printf '  查看状态：./start.sh status\n'
  printf '  查看日志：./start.sh logs\n'
  printf '  停止服务：./start.sh stop\n\n'
}

run_tests() {
  local backend_result=0
  local frontend_result=0
  echo "正在构建 PostgreSQL 测试环境..."
  docker compose -p "$TEST_PROJECT_NAME" -f "$TEST_COMPOSE_FILE" build test
  docker compose -p "$TEST_PROJECT_NAME" -f "$TEST_COMPOSE_FILE" up -d --wait test-db

  if docker compose -p "$TEST_PROJECT_NAME" -f "$TEST_COMPOSE_FILE" \
    run --rm --no-deps test; then
    backend_result=0
  else
    backend_result=$?
  fi

  if docker compose -p "$TEST_PROJECT_NAME" -f "$TEST_COMPOSE_FILE" \
    run --rm --no-deps frontend-test; then
    frontend_result=0
  else
    frontend_result=$?
  fi

  if [ "$backend_result" -ne 0 ]; then
    return "$backend_result"
  fi
  return "$frontend_result"
}

case "$ACTION" in
  start|restart)
    require_docker
    start_stack
    ;;
  test)
    require_docker
    run_tests
    ;;
  stop)
    require_docker
    docker compose down
    ;;
  logs)
    require_docker
    docker compose logs -f --tail=200
    ;;
  status)
    require_docker
    docker compose ps
    ;;
  *)
    echo "用法：./start.sh [start|restart|test|stop|logs|status]"
    exit 1
    ;;
esac
