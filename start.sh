#!/bin/bash
# 一键启动：后端(8000) + 前端生产托管
# 用法：./start.sh
# 说明：若 frontend/dist 不存在则先执行前端构建；随后由后端托管构建产物，
#       浏览器访问 http://localhost:8000 即可（无需另开前端 dev server）。
set -e

cd "$(dirname "$0")"
ROOT="$(pwd)"

if [ ! -d frontend/dist ]; then
  echo "[start] 未发现 frontend/dist，正在构建前端…"
  if ! command -v npm >/dev/null 2>&1; then
    echo "[start] 未找到 npm。请先安装 Node.js 18+，或手动准备 frontend/dist。" >&2
    exit 1
  fi
  (cd frontend && npm install && npm run build)
fi

if [ ! -x backend/.venv/bin/python ]; then
  echo "[start] 未找到 backend/.venv，正在创建并安装后端依赖…"
  python3 -m venv backend/.venv
  backend/.venv/bin/python -m pip install -r backend/requirements.txt
fi

echo "[start] 启动后端服务： http://localhost:8000"
cd backend
exec .venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8000
