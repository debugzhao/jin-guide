#!/usr/bin/env bash
# 一键部署脚本：本地仓库 -> jdy_server（rsync 同步代码 + 远程 docker compose 重建）
#
# 用法：
#   ./scripts/deploy.sh                 # 部署全部服务（frontend/backend/worker）
#   ./scripts/deploy.sh frontend        # 只重建/重启指定服务，可传多个：./scripts/deploy.sh frontend backend
#   ./scripts/deploy.sh --dry-run       # 只预览 rsync 会同步哪些文件，不做任何改动
#   DEPLOY_YES=1 ./scripts/deploy.sh    # 跳过交互确认（供后续接入 CI 使用）
#
# 注意：
#   - rsync 使用 --delete，会让服务器上的代码目录与本地仓库状态完全一致（本地删了的文件，服务器也会删）。
#     服务器专属文件（.env、*.log）已加入排除名单，不受影响。
#   - 这个脚本同步的是“本地工作区当前状态”，包含未提交的改动。如果不想把未提交的改动带到生产，
#     请先自行 git status 确认或 git stash。
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

REMOTE_HOST="${DEPLOY_HOST:-root@117.72.127.159}"
REMOTE_DIR="${DEPLOY_DIR:-/opt/wenjin}"

DRY_RUN=""
SERVICES=()
for arg in "$@"; do
  if [[ "$arg" == "--dry-run" ]]; then
    DRY_RUN="--dry-run"
  else
    SERVICES+=("$arg")
  fi
done

EXCLUDES=(
  --exclude=.git
  --exclude=.env
  --exclude=".env.*"
  --exclude=node_modules
  --exclude=.next
  --exclude=__pycache__
  --exclude=.venv
  --exclude=venv
  --exclude=.pytest_cache
  --exclude=.mypy_cache
  --exclude=.ruff_cache
  --exclude=.DS_Store
  --exclude=memory
  --exclude=.claude
  --exclude=.cursor
  --exclude="*.log"
)

echo "==> 目标：${REMOTE_HOST}:${REMOTE_DIR}"
if [[ -n "$DRY_RUN" ]]; then
  echo "==> 预览模式（--dry-run），不会修改任何文件"
fi

if [[ -z "$DRY_RUN" && "${DEPLOY_YES:-}" != "1" ]]; then
  echo -n "确认要同步代码并重建容器吗？未提交的本地改动也会被同步上去 [y/N] "
  read -r confirm
  if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
    echo "已取消"
    exit 1
  fi
fi

echo "==> 1/3 同步代码"
rsync -az --delete $DRY_RUN "${EXCLUDES[@]}" ./ "${REMOTE_HOST}:${REMOTE_DIR}/"

if [[ -n "$DRY_RUN" ]]; then
  echo "==> 预览完成，未执行远程构建/重启"
  exit 0
fi

echo "==> 2/3 远程构建并重启容器：${SERVICES[*]:-(全部服务)}"
ssh "${REMOTE_HOST}" "cd ${REMOTE_DIR} && docker compose build ${SERVICES[*]:-} && docker compose up -d ${SERVICES[*]:-}"

echo "==> 3/3 容器状态"
ssh "${REMOTE_HOST}" "cd ${REMOTE_DIR} && docker compose ps"

echo "✅ 部署完成"
