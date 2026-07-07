#!/bin/bash
# ============================================================================
# 安装 pre-commit hook（macOS / Linux）
# 用法: bash claude-pre-commit/install.sh
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
HOOK_DIR="$REPO_ROOT/.git/hooks"
SOURCE="$SCRIPT_DIR/pre-commit"

if [ ! -d "$HOOK_DIR" ]; then
  echo "错误: 未找到 .git/hooks 目录，请确认当前在 Git 仓库中运行"
  exit 1
fi

if [ ! -f "$SOURCE" ]; then
  echo "错误: 未找到 pre-commit 文件: $SOURCE"
  exit 1
fi

cp "$SOURCE" "$HOOK_DIR/pre-commit"
chmod +x "$HOOK_DIR/pre-commit"

echo "✓ pre-commit hook 已安装到 $HOOK_DIR/pre-commit"
