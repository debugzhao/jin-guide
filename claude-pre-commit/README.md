# Claude Code Pre-commit 安全审查 Hook

在 `git commit` 前自动调用 Claude Code AI 审查暂存区代码的安全漏洞，支持自定义规则、分级响应（阻断/警告/通过）。

---

## 工作原理

```
git commit
    │
    ▼
┌─────────────────────────────────┐
│  .git/hooks/pre-commit 触发     │
└─────────────────┬───────────────┘
                  │
                  ▼
┌─────────────────────────────────┐
│  1. 获取暂存区 diff              │
│     git diff --cached           │
└─────────────────┬───────────────┘
                  │
                  ▼
┌─────────────────────────────────┐
│  2. 文件过滤                     │
│     根据 .claude-review.yml     │
│     的 ignore 规则排除测试文件等  │
└─────────────────┬───────────────┘
                  │
                  ▼
┌─────────────────────────────────┐
│  3. 前置检查                     │
│     - diff 为空？→ 跳过          │
│     - 超过 max_diff_lines？→ 跳过│
│     - claude CLI 不存在？→ 跳过  │
└─────────────────┬───────────────┘
                  │
                  ▼
┌─────────────────────────────────┐
│  4. 调用 Claude Code            │
│     diff 通过 stdin 传入         │
│     审查指令通过 -p 参数传入      │
│     claude -p "审查指令"         │
└─────────────────┬───────────────┘
                  │
                  ▼
┌─────────────────────────────────┐
│  5. 解析 Claude 响应             │
│     BLOCK: → 阻断提交 (exit 1)  │
│     WARN:  → 输出警告，继续提交   │
│     PASS   → 通过 (exit 0)      │
└─────────────────┬───────────────┘
                  │
                  ▼
          提交成功 / 被阻止
```

---

## 目录结构

```
claude-pre-commit/
├── pre-commit            # hook 主脚本（mvn initialize 时自动复制到 .git/hooks/）
├── .claude-review.yml    # 审查规则配置
└── README.md             # 本文件
```

---

## 安装方式

### 方式一：通过 Maven 自动安装（推荐）

项目 `pom.xml` 已配置 `maven-antrun-plugin`，执行任意 Maven 命令时自动安装：

```bash
cd kroger-api
mvn initialize
```

Hook 会被自动复制到 `.git/hooks/pre-commit`。

### 方式二：手动安装

```bash
cd kroger-api
cp claude-pre-commit/pre-commit .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
```

---

## 前置条件

1. **Claude Code CLI 已安装**
   ```bash
   # 验证
   claude --version
   ```
   如未安装，参考：https://docs.anthropic.com/en/docs/claude-code

2. **Git Bash（Windows）**
   - Claude Code 在 Windows 上需要 Git Bash
   - 脚本会自动检测并设置 `CLAUDE_CODE_GIT_BASH_PATH`
   - 如果 Git 安装在非默认路径，需修改 `pre-commit` 脚本中的路径：
     ```bash
     export CLAUDE_CODE_GIT_BASH_PATH="C:\\你的路径\\Git\\bin\\bash.exe"
     ```

---

## 使用流程

### 正常提交

```bash
git add src/main/java/MyService.java
git commit -m "feat: add user service"
```

输出示例（通过）：
```
[Claude Review] 正在审查 1 个文件的安全性...
✅ [Claude Review] 安全审查通过
```

输出示例（阻断）：
```
[Claude Review] 正在审查 1 个文件的安全性...
❌ [Claude Review] MyService.java - 硬编码数据库密码 "admin123"
❌ [Claude Review] MyService.java - SQL注入：字符串拼接用户输入构造SQL查询
❌ [Claude Review] 提交已阻止！请修复上述安全问题后重试。
[Claude Review] 跳过检查: git commit --no-verify
```

输出示例（警告但不阻断）：
```
[Claude Review] 正在审查 1 个文件的安全性...
⚠️  [Claude Review] MyService.java - 日志中打印了用户token，建议脱敏
✅ [Claude Review] 审查通过（有警告，请关注上述建议）
```

### 跳过审查

紧急情况下跳过安全审查：

```bash
git commit --no-verify -m "hotfix: urgent fix"
```

---

## 规则配置

编辑 `claude-pre-commit/.claude-review.yml`：

### 基本配置

```yaml
severity: strict        # strict | moderate | relaxed
language: 中文          # 输出语言
max_diff_lines: 500     # 超过此行数跳过审查（避免超时）
timeout: 90             # Claude 调用超时（秒）
```

### 审查规则

每条规则包含：

```yaml
rules:
  - name: SQL注入                    # 规则名称
    enabled: true                    # 是否启用
    block: true                      # true=阻断提交 / false=仅警告
    description: 检查字符串拼接SQL... # 审查描述（Claude 按此判断）
```

### 当前预置规则（17 条）

| # | 规则 | 级别 | 分类 |
|---|------|------|------|
| 1 | SQL注入 | BLOCK | 安全漏洞 |
| 2 | XSS (跨站脚本) | BLOCK | 安全漏洞 |
| 3 | SSRF (服务端请求伪造) | BLOCK | 安全漏洞 |
| 4 | 命令注入 | BLOCK | 安全漏洞 |
| 5 | 路径遍历 | BLOCK | 安全漏洞 |
| 6 | XXE (XML外部实体注入) | BLOCK | 安全漏洞 |
| 7 | 认证缺陷 | BLOCK | 安全漏洞 |
| 8 | 授权缺陷 | BLOCK | 安全漏洞 |
| 9 | 敏感数据泄露 | BLOCK | 安全漏洞 |
| 10 | 竞态条件 | BLOCK | 并发与可靠性 |
| 11 | 死锁 | BLOCK | 并发与可靠性 |
| 12 | 空指针/空引用 | BLOCK | 并发与可靠性 |
| 13 | 资源泄漏 | BLOCK | 并发与可靠性 |
| 14 | 内存泄漏 | BLOCK | 并发与可靠性 |
| 15 | 事务问题 | BLOCK | 并发与可靠性 |
| 16 | API兼容性 | WARN | API与性能 |
| 17 | 性能退化 | WARN | API与性能 |

### 文件过滤

```yaml
ignore:
  - ".*\\.test\\."        # 测试文件
  - ".*\\.spec\\."
  - ".*__tests__.*"
  - "package-lock\\.json"  # 锁文件
  - "dist/.*"             # 构建产物
```

### 忽略的问题类别

```yaml
ignore_categories:
  - Naming      # 不检查命名风格
  - Style       # 不检查代码风格
  - Formatting  # 不检查格式化
```

---

## 自定义规则示例

### 添加新规则

```yaml
rules:
  - name: 禁止使用 System.out
    enabled: true
    block: false
    description: 生产代码不应使用System.out.println，应使用日志框架(slf4j/log4j)
```

### 禁用某条规则

```yaml
  - name: 性能退化
    enabled: false     # 关闭此规则
    block: false
    description: ...
```

### 将警告升级为阻断

```yaml
  - name: API兼容性
    enabled: true
    block: true        # 改为 true，发现 API 破坏性变更时阻断提交
    description: ...
```

---

## 故障排查

| 现象 | 原因 | 解决 |
|------|------|------|
| `claude CLI 未安装` | claude 不在 PATH 中 | 运行 `claude --version` 确认安装 |
| `Claude 调用失败或超时` | 网络问题或 Claude 认证过期 | 运行 `claude -p "hi"` 单独测试 |
| `requires git-bash` | Windows 环境变量未设置 | 修改脚本中 `CLAUDE_CODE_GIT_BASH_PATH` 路径 |
| Diff 超过阈值跳过 | 提交文件过多 | 增大 `max_diff_lines` 或分批提交 |
| Hook 未触发 | 文件无执行权限 | `chmod +x .git/hooks/pre-commit` |
| 所有提交都 PASS | 规则文件路径错误 | 确认 `claude-pre-commit/.claude-review.yml` 存在 |
| mvn initialize 报错 | 路径问题 | 确认 `claude-pre-commit/pre-commit` 文件存在 |

### 手动调试

```bash
# 1. 测试 Claude CLI 是否正常
claude -p "say PASS"

# 2. 模拟 hook 调用
git diff --cached | claude -p "审查这段代码是否有安全漏洞，如果有输出 BLOCK: 描述，没有输出 PASS"

# 3. 查看 hook 脚本是否存在
cat .git/hooks/pre-commit | head -5
```

---

## 卸载

```bash
rm .git/hooks/pre-commit
```

或在 `pom.xml` 中移除 `maven-antrun-plugin` 配置。

---

## 注意事项

- 每次 commit 会消耗 Claude API 额度（按 token 计费）
- 大量文件变更时建议分批 commit，或临时 `--no-verify` 跳过
- Hook 调用失败时**不会阻断提交**（fail-open 策略），确保不影响正常开发流程
- 规则描述使用自然语言，Claude 会基于语义理解进行审查，比正则匹配更智能但也可能有误判
