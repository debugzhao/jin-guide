# ============================================================================
# Claude Code Pre-commit Hook 环境配置
# 本文件由 pre-commit 脚本自动加载，修改后无需重新安装 hook
# ============================================================================

# ---------- API 配置（直接调用模式） ----------

# API 基础地址（公司代理地址，不含 /v1/messages 后缀）
#CLAUDE_API_BASE_URL="https://your-proxy.company.com"
CLAUDE_API_BASE_URL="https://llm-gateway-test.pacvue.com"

# API Key
#CLAUDE_API_KEY="your-api-key-here"
CLAUDE_API_KEY="sk-rQfRANLTBghBxhA9HM6JJQ"

# Claude 模型
CLAUDE_MODEL="claude-haiku-4-5-20251001"

# ---------- 工具路径（可选） ----------

# Git Bash 路径（仅 Windows 需要，Git hook 运行依赖 Git Bash）
# 留空 = 自动从 git 安装目录推断；如果自动检测失败请手动指定
# macOS/Linux 无需配置此项
CLAUDE_GIT_BASH_PATH="/usr/bin/git"

# ---------- 审查配置 ----------

# 审查规则配置文件路径（相对于项目根目录）
REVIEW_CONFIG_PATH="claude-pre-commit/.claude-review.yml"

# 是否启用颜色输出（true/false）
COLOR_OUTPUT="true"

# Claude 调用失败时的行为：skip=跳过继续提交 / block=阻断提交
ON_FAILURE="block"
