#!/usr/bin/env bash
# 单向数据库同步：线上 jdy_server -> 本地开发环境
#
# 方向是固定的、不可反转的：jdy_server 是真实运行的实例，本地是可随时重建的开发
# 沙盒。每次运行会用线上快照完全覆盖本地库（pg_dump --clean 先 DROP 再重建），
# 本地此前的数据会丢失；线上数据不受任何影响。
#
# 用法：
#   ./scripts/sync_db_from_prod.sh              # 交互确认后执行
#   SYNC_YES=1 ./scripts/sync_db_from_prod.sh    # 跳过确认，供 cron/定时任务使用
#
# 定时执行（本地 macOS crontab 示例，每天凌晨3点同步一次；只在电脑开机、Docker
# Desktop 运行时才会真正执行，笔记本休眠时会跳过这次，不会补跑）：
#   crontab -e
#   0 3 * * * cd /Users/tyson/repo/AI/wenjin && SYNC_YES=1 ./scripts/sync_db_from_prod.sh >> /tmp/wenjin_db_sync.log 2>&1
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

REMOTE_HOST="${DEPLOY_HOST:-root@117.72.127.159}"
REMOTE_DIR="${DEPLOY_DIR:-/opt/wenjin}"
DUMP_FILE="$(mktemp -t wenjin_prod_dump).sql.gz"

cleanup() { rm -f "$DUMP_FILE"; }
trap cleanup EXIT

if [[ "${SYNC_YES:-}" != "1" ]]; then
  echo "即将用线上(${REMOTE_HOST}:${REMOTE_DIR})数据库快照覆盖本地数据库，本地现有数据会丢失。"
  echo -n "确认继续吗？[y/N] "
  read -r confirm
  if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
    echo "已取消"
    exit 1
  fi
fi

echo "==> 1/3 从线上导出数据库快照"
ssh "$REMOTE_HOST" "cd ${REMOTE_DIR} && docker compose exec -T postgres pg_dump -U wenjin -d wenjin --clean --if-exists --no-owner --no-privileges" \
  | gzip > "$DUMP_FILE"

echo "==> 2/3 导入本地数据库（覆盖本地现有数据）"
gunzip -c "$DUMP_FILE" | docker compose exec -T postgres psql -U wenjin -d wenjin -v ON_ERROR_STOP=1 -q

echo "✅ 同步完成：本地数据库已与线上 $(date '+%Y-%m-%d %H:%M:%S') 时刻的快照保持一致"
