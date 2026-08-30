#!/usr/bin/env bash
# 单向数据库同步（反向）：本地开发环境 -> 线上 jdy_server
#
# 警告：这个方向和 sync_db_from_prod.sh 相反，也是本仓库里唯一一个会覆盖线上数据的脚本。
# jdy_server 是真实运行的实例，本地是可随时重建的开发沙盒——正常情况下不应该反过来覆盖线上。
# 只有在明确要用本地数据（例如新导入的招生数据）整体替换线上库时才使用，且执行前请再次确认：
#   - 线上现有的真实用户（auth_users）、报告运行记录（agent_runs）、对话历史（memory_*）、
#     登录会话（auth_sessions）等生产数据会被本地库状态完全覆盖，本地没有的数据会一并丢失
#   - 该操作不可逆，线上无法回滚到执行前的状态（脚本会在覆盖前自动备份线上快照到本地，
#     可用该备份手动恢复，但除此之外没有其他安全网）
#
# 用法：
#   ./scripts/sync_db_to_prod.sh              # 交互确认后执行（需要手动输入确认短语）
#   SYNC_YES=1 ./scripts/sync_db_to_prod.sh    # 跳过交互确认，仅供已知悉风险的自动化场景使用
#
# 执行前自动做的事：
#   1. 从线上导出一份快照，保存到 /tmp（覆盖前的最后备份，用于紧急回滚）
#   2. 从本地导出快照
#   3. 用本地快照覆盖线上库（pg_dump --clean 先 DROP 再重建）
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

REMOTE_HOST="${DEPLOY_HOST:-root@117.72.127.159}"
REMOTE_DIR="${DEPLOY_DIR:-/opt/wenjin}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
PROD_BACKUP_FILE="/tmp/wenjin_prod_backup_before_overwrite_${TIMESTAMP}.sql.gz"
LOCAL_DUMP_FILE="$(mktemp -t wenjin_local_dump).sql.gz"

cleanup() { rm -f "$LOCAL_DUMP_FILE"; }
trap cleanup EXIT

if [[ "${SYNC_YES:-}" != "1" ]]; then
  echo "⚠️  即将用本地数据库状态覆盖线上(${REMOTE_HOST}:${REMOTE_DIR})数据库。"
  echo "⚠️  线上现有的真实用户、报告记录、对话历史、登录会话等生产数据会被清空，本地没有的数据不会保留。"
  echo "⚠️  该操作不可逆。覆盖前会自动备份线上当前快照到 ${PROD_BACKUP_FILE}，但除此之外无法回滚。"
  echo -n "确认继续吗？请输入「OVERWRITE PROD」以确认："
  read -r confirm
  if [[ "$confirm" != "OVERWRITE PROD" ]]; then
    echo "已取消"
    exit 1
  fi
fi

echo "==> 1/4 备份线上当前数据库快照（覆盖前的最后回滚点）"
ssh "$REMOTE_HOST" "cd ${REMOTE_DIR} && docker compose exec -T postgres pg_dump -U wenjin -d wenjin --clean --if-exists --no-owner --no-privileges" \
  | gzip > "$PROD_BACKUP_FILE"
echo "    已保存到 ${PROD_BACKUP_FILE}"

echo "==> 2/4 导出本地数据库快照"
docker compose exec -T postgres pg_dump -U wenjin -d wenjin --clean --if-exists --no-owner --no-privileges \
  | gzip > "$LOCAL_DUMP_FILE"

echo "==> 3/4 导入线上数据库（覆盖线上现有数据）"
gunzip -c "$LOCAL_DUMP_FILE" | ssh "$REMOTE_HOST" "cd ${REMOTE_DIR} && docker compose exec -T postgres psql -U wenjin -d wenjin -v ON_ERROR_STOP=1 -q"

echo "==> 4/4 完成"
echo "✅ 同步完成：线上数据库已与本地 $(date '+%Y-%m-%d %H:%M:%S') 时刻的快照保持一致"
echo "   如需回滚，可用备份文件恢复：gunzip -c ${PROD_BACKUP_FILE} | ssh ${REMOTE_HOST} \"cd ${REMOTE_DIR} && docker compose exec -T postgres psql -U wenjin -d wenjin -v ON_ERROR_STOP=1 -q\""
