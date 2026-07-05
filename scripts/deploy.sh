#!/usr/bin/env bash
# 一键部署脚本：本地仓库 -> jdy_server（rsync 同步代码 + 远程 docker compose 重建）
#
# 用法：
#   ./scripts/deploy.sh                 # 全量部署：同步整个仓库 + 重建全部服务
#   ./scripts/deploy.sh frontend        # 只同步 frontend/ 目录 + 只重建 frontend 服务
#   ./scripts/deploy.sh backend         # 只同步 backend/ 目录 + 只重建 backend 服务
#   ./scripts/deploy.sh backend worker  # backend 和 worker 共用 backend/ 目录，可以一起传
#   ./scripts/deploy.sh --dry-run       # 只预览 rsync 会同步哪些文件，不做任何改动
#   DEPLOY_YES=1 ./scripts/deploy.sh    # 跳过交互确认（供后续接入 CI 使用）
#
# 注意：
#   - 指定服务名时，rsync 只会同步该服务对应的子目录（见下面 service_path），不会碰其他服务的代码，
#     防止“只想部署 A，结果把 B 未提交的改动也带上线”。
#     根目录的共享文件（docker-compose.yml、litellm_config.yaml、.env.example 等）只有在不带参数的
#     全量部署时才会同步，改了这些文件记得跑一次不带参数的全量部署。
#   - backend/frontend 容器都是 “挂载源码目录 + 热重载”（uvicorn --reload / next dev），
#     rsync 落盘的那一刻代码就已经在生效了，docker compose build/up 主要是为了让新依赖生效、
#     以及让新增的路由文件被正确识别，不是代码生效的唯一开关。
#   - rsync 使用 --delete，会让服务器上对应目录与本地仓库状态完全一致（本地删了的文件，服务器也会删）。
#     服务器专属文件（.env、*.log）已加入排除名单，不受影响。
#   - 这个脚本同步的是“本地工作区当前状态”，包含未提交的改动。如果不想把未提交的改动带到生产，
#     请先自行 git status 确认或 git stash。
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

REMOTE_HOST="${DEPLOY_HOST:-root@117.72.127.159}"
REMOTE_DIR="${DEPLOY_DIR:-/opt/wenjin}"

# 服务名 -> 对应的本地源码子目录（bash 3.2 没有关联数组，用函数模拟映射）
service_path() {
  case "$1" in
    frontend) echo "frontend" ;;
    backend|worker) echo "backend" ;;
    *) echo "" ;;
  esac
}

DRY_RUN=""
SERVICES=()
for arg in "$@"; do
  if [[ "$arg" == "--dry-run" ]]; then
    DRY_RUN="--dry-run"
  else
    SERVICES+=("$arg")
  fi
done

# 校验服务名，同时算出需要同步的目录（去重）
SYNC_FRONTEND=0
SYNC_BACKEND=0
for svc in "${SERVICES[@]+"${SERVICES[@]}"}"; do
  path="$(service_path "$svc")"
  if [[ -z "$path" ]]; then
    echo "未知服务：${svc}（deploy.sh 目前认识 frontend / backend / worker；改根目录共享文件请不带参数跑全量部署）" >&2
    exit 1
  fi
  [[ "$path" == "frontend" ]] && SYNC_FRONTEND=1
  [[ "$path" == "backend" ]] && SYNC_BACKEND=1
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

if [[ ${#SERVICES[@]} -eq 0 ]]; then
  echo "==> 1/3 同步代码（全量：整个仓库）"
  rsync -az --delete $DRY_RUN "${EXCLUDES[@]}" ./ "${REMOTE_HOST}:${REMOTE_DIR}/"
else
  echo "==> 1/3 同步代码（按服务范围）"
  if [[ "$SYNC_FRONTEND" == "1" ]]; then
    echo "    - frontend/"
    rsync -az --delete $DRY_RUN "${EXCLUDES[@]}" ./frontend/ "${REMOTE_HOST}:${REMOTE_DIR}/frontend/"
  fi
  if [[ "$SYNC_BACKEND" == "1" ]]; then
    echo "    - backend/"
    rsync -az --delete $DRY_RUN "${EXCLUDES[@]}" ./backend/ "${REMOTE_HOST}:${REMOTE_DIR}/backend/"
  fi
fi

if [[ -n "$DRY_RUN" ]]; then
  echo "==> 预览完成，未执行远程构建/重启"
  exit 0
fi

echo "==> 2/3 远程构建并重启容器：${SERVICES[*]:-(全部服务)}"
ssh "${REMOTE_HOST}" "cd ${REMOTE_DIR} && docker compose build ${SERVICES[*]:-} && docker compose up -d ${SERVICES[*]:-}"

echo "==> 3/3 容器状态"
ssh "${REMOTE_HOST}" "cd ${REMOTE_DIR} && docker compose ps"

echo "✅ 部署完成"
