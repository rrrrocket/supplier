#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
  echo "未找到 Python 3。请先安装 Python 3.12 或更高版本。"
  read -r -p "按回车退出…"
  exit 1
fi

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi

source .venv/bin/activate
python -m pip install -r requirements-dev.txt

if [ ! -f .env ]; then
  cp .env.example .env
fi

printf '\nMatrix One Supplier Network 已准备启动：\n'
printf '  首页：http://127.0.0.1:8000\n'
printf '  登录：http://127.0.0.1:8000/login\n'
printf '  管理端：http://127.0.0.1:8000/admin\n\n'

(sleep 1.2; open "http://127.0.0.1:8000/login" >/dev/null 2>&1 || true) &
exec uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
