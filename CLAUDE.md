# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## 项目简介

**问津 Agent** — 面向高考生和家长的 AI 志愿决策助理。核心能力：建档、规则校验、冲稳保方案生成、志愿表风险体检。PRD 文档在 `docs/` 目录，是理解业务逻辑的首要参考。

### 鉴权（当前实现）

- **邮箱 + 密码**登录/注册，验证码经 **Resend** 发送（`RESEND_API_KEY`、`EMAIL_FROM=onboarding@resend.dev`）
- API：`POST /auth/send-code`、`/auth/register`、`/auth/login`、`/auth/logout`、`GET /auth/me`
- Session 存 `sessions` 表，ORM 类名 **`AuthSession`**（勿与 SQLAlchemy `Session` 混淆）
- 验证码存 Redis（`auth:code:{email}`，TTL 10 分钟）

### 已移除（v1.1）

- 人工复核（HITL）：无 `human_review_node`、无 `/api/v1/reviews`、无 `/admin/reviews` 与 `/reports/[id]/review`
- 手机号 + 短信验证码登录

---

## 开发命令

### 一键启动（推荐）

```bash
cp .env.example .env          # 填入 MOONSHOT_API_KEY 等必填值（见下方「架构概览 - 模型网关」说明，.env.example 中的 OPENAI_API_KEY 已过时）
docker-compose up             # 启动全栈：postgres、redis、litellm、backend、worker、frontend
```

服务端口：前端 3000 · 后端 8000 · LiteLLM 4000 · PostgreSQL 5432 · Redis 6379

本地开发环境通常长期用 `docker-compose up -d` 跑着（backend/frontend 均挂载源码 + 热重载：`uvicorn --reload` / `next dev`），改代码后落盘即生效，不需要每次重启容器。改依赖（`requirements.txt`/`package.json`）或新增路由文件才需要 `docker compose build`。

### 单独启动各服务

```bash
# 后端（不用 docker 时）
cd backend
uvicorn app.main:app --reload --port 8000

# ARQ Worker（报告生成异步任务）
arq app.worker.WorkerSettings

# 数据库迁移
alembic upgrade head
alembic revision --autogenerate -m "描述"

# 前端
cd frontend
npm install
npm run dev       # 开发服务器
npm run build     # 生产构建
npm run lint      # ESLint 检查
```

### 在已运行的容器里执行命令

```bash
docker compose exec backend alembic upgrade head
docker compose exec backend python -m pytest -q      # 见下方「测试」说明
docker compose logs -f backend worker
```

### 测试

`backend/tests/` 下有 pytest 用例（规则引擎、评分、风险引擎、compliance、graph 结构、tool_filter），但 **`pytest`/`pytest-asyncio` 未写入 `backend/requirements.txt`，backend 容器默认不包含**，直接 `docker compose exec backend python -m pytest` 会报 `No module named pytest`。跑测试前先在容器或本地虚拟环境里补装：

```bash
docker compose exec backend pip install pytest pytest-asyncio
docker compose exec backend python -m pytest -q
```

前端没有单测配置，只有 `npm run lint`（ESLint）。

### 部署

`scripts/deploy.sh` 一键部署到远程 jdy_server（rsync 同步 + 远程 `docker compose build/up`）：

```bash
./scripts/deploy.sh                 # 全量：整仓库 + 重建全部服务
./scripts/deploy.sh frontend        # 只同步 frontend/ + 只重建 frontend 服务
./scripts/deploy.sh backend worker  # backend 和 worker 共用 backend/ 目录
./scripts/deploy.sh --dry-run       # 预览 rsync 差异，不落地改动
```

指定服务名时只同步该服务对应子目录，避免把另一服务未提交的改动带上线；根目录共享文件（`docker-compose.yml`、`litellm_config.yaml` 等）只有不带参数的全量部署才会同步。默认 `rsync --delete` 会让服务器目录与本地工作区（含未提交改动）完全一致，部署前确认 `git status`。远程主机/目录默认为 `root@117.72.127.159:/opt/wenjin`（可用 `DEPLOY_HOST`/`DEPLOY_DIR` 覆盖），详见脚本头部注释。

---

## 架构概览

### 分层结构

```
前端 (Next.js) → BFF (Next.js Route Handler) → FastAPI API 层
                                                    ↓
                                         ARQ Worker (Redis 队列)
                                                    ↓
                                         LangGraph Agent Orchestrator
                                                    ↓
                                         LiteLLM Proxy → Moonshot Kimi (kimi-k2.6)
```

- **BFF 层**：轻量鉴权、SSE 转发、文件预处理，不含业务逻辑
- **API 层**：`backend/app/api/v1/` — 同步 HTTP 处理，Agent run 投入 ARQ 队列后立即返回
- **Worker 层**：`backend/app/worker.py` — ARQ worker，在独立进程运行 LangGraph。**不用 FastAPI BackgroundTasks 做 Agent run**，原因是进程重启会丢失任务
- **Agent 层**：`backend/app/agent/` — LangGraph 编排多 Agent，通过工具调用确定性服务，不直接访问 DB
- **模型网关**：所有 LLM 调用经 LiteLLM Proxy（`:4000`）。**实际后端是 Moonshot Kimi（`kimi-k2.6`），不是 OpenAI/Anthropic** —— `litellm_config.yaml` 里的虚拟模型名（`profile-agent`/`retrieval-agent`/`report-agent`/`reflection-agent`/`review-draft-agent`/`text-embedding-3-small`）全部路由到 `openai/kimi-k2.6`（OpenAI 兼容协议），`.env.example` 里的 `OPENAI_API_KEY` 字段名是历史遗留，真正生效的是 `MOONSHOT_API_KEY`/`MOONSHOT_BASE_URL`（在 `docker-compose.yml` 的 `litellm` 服务里读取）。改模型/加 provider 要改 `litellm_config.yaml` 而不是代码里硬编码模型名。

### 报告问答（ConversationAgent）

`backend/app/agent/conversation_agent.py` + `backend/app/api/v1/chat.py`（路由挂在 `/reports/{report_id}/chat`）。这是独立于主 LangGraph 流程的**同步 SSE 流式问答**，不经过 ARQ 队列：请求进来直接调 LiteLLM `report-agent` 模型 streaming，逐 token 转发。历史记录 Redis 热层（`chat:history:{report_id}:{user_id}`，7 天 TTL）+ PostgreSQL `report_conversations` 表冷层兜底；限流 30 条/用户/天（`chat:daily:{user_id}:{date}`）。回复末尾做一次全量合规检测（复用 `nodes/compliance.py` 的正则），命中禁词会做同义替换后再落库，不重新生成。

### 建档前聊天（IntakeAgent）

`backend/app/agent/intake_agent.py` + `backend/app/api/v1/intake_chat.py`（路由挂在 `/intake/chat`）。首页 Chat-first 首屏用的真正多轮聊天，不是"先分类再二选一"：每轮先发一次带 `tools` 的流式请求（`intake-agent` 模型），模型可以直接流式输出文本，也可以在同一轮里调用 function calling 工具——`lookup_university_score`/`lookup_subject_requirement`/`compare_universities` 三个纯 SQL 工具（`backend/app/engine/school_lookup.py`，不经过 LLM）负责查分数/位次/选科要求/多校对比，执行完把结果塞回 messages 再发起第二轮流式请求产出自然语言；`start_profile_capture` 是不返回数据的信号工具，命中后端直接发 SSE `trigger_profile_capture` 事件，前端收到即内联渲染建档表单。系统提示词把话题严格限定在高考志愿相关范围，硬性要求事实性数字必须过工具查询、禁止凭模型记忆回答。多会话模型：`intake_conversations.id` 即会话/thread id，一个 `owner_key`（`user_id` 或匿名会话 `anon:{anonymous_id}`）可以有多条会话，侧栏 `GET /intake/conversations`（游标分页）展示历史列表，点击某条继续对话。`POST /intake/chat` 不传 `conversation_id` 时懒创建新会话（首条消息 `done` 事件前才建行），传了则校验属于当前 `owner_key`（否则 404）。历史持久化与 ConversationAgent 同构：Redis 热层（`intake:history:{owner_key}:{conversation_id}`）+ PostgreSQL `intake_conversations` 冷层，建档前还没有 `report_id` 可挂靠，需要先有 `session_token` Cookie，前端在聊天前会调 `POST /auth/anonymous-session` 兜底建立。前端首屏默认全新空白对话（`currentIntakeConversationId` 不持久化），历史通过侧栏显式点选恢复。

### 可观测性 / Admin Debug Console

`backend/app/api/v1/admin.py` 提供 `/admin/runs`、`/admin/runs/{id}`、`/admin/runs/{id}/debug-events`（SSE）、`/admin/metrics/summary`，**无鉴权、对所有访客开放**（数据本身不含 PII）。前端 `components/admin/debug/` 渲染 LangGraph 拓扑图和节点耗时时间线。调试事件由 `backend/app/agent/debug_events.py` 的 `emit_debug_event` 写入 **与用户 SSE 共用的同一条 Redis Stream**（`sse:{run_id}`），事件类型加 `debug:` 前缀区分，用户侧 SSE 生成器按前缀过滤掉，Admin SSE 端点则回放全部历史（`XREAD` 从 `0-0` 开始）再续接实时流。

### 工具层弹性设计

`backend/app/agent/` 下三个协作的弹性组件（参考 HelloAgents 设计）：
- **`tool_response.py`**：`ToolResponse` 三态协议（`SUCCESS`/`PARTIAL`/`ERROR`），所有工具函数返回它而不是裸 dict，Agent 节点统一按 `is_usable`/`is_error` 判断
- **`circuit_breaker.py`**：全局单例 `CircuitBreaker`，保护 Cohere Rerank / LiteLLM Proxy / pgvector 三个外部调用点。连续 3 次 `ERROR` → `OPEN`（熔断冷却 300s）→ `HALF_OPEN`（试探）→成功则 `CLOSED`。单进程协程内存态，若未来多进程部署需迁移到 Redis
- **`tool_filter.py`**：按 Agent 名限制可见工具（`_TOOL_REGISTRY`），防止 LLM 在 prompt 里看到并误调用其他 Agent 的工具

### 前端状态分工

- **Zustand** (`frontend/lib/store.ts`)：纯客户端状态（表单草稿、Wizard 步骤、Sheet 展开状态）
- **TanStack Query**：服务端状态（档案、报告、run 状态）；SSE 补充 run 实时进度，不用轮询

### Agent 通信机制

所有节点之间**唯一通信介质是 LangGraph State**，不进行直接 API 调用。State schema 在 `backend/app/agent/state.py`（`VolunteerPlanState`）。并行字段（`evidence_list`、`rule_results`、`hard_blocked_items`）必须加 `Annotated[list, operator.add]` reducer，否则后写节点会覆盖前写节点结果。

---

## 关键设计约束（违反会引发 bug 或产品风险）

### 确定性系统与 LLM 边界

高考志愿是高风险决策。**规则引擎给结论，Agent 给解释**：
- 省份/批次/位次匹配、选科/体检/单科/学费校验 → SQL + Rule Engine，不经过 LLM
- 专业/城市解释、报告文案 → RAG + Agent

### SSE 鉴权

`EventSource` 不支持自定义请求头，**禁止将 Bearer Token 放入 query string**（会被日志记录）。方案：
1. 首选：BFF 种 `HttpOnly` Cookie，SSE 自动携带
2. 备选：`POST /api/v1/agent/runs/{id}/stream-token` 获取 60s 一次性 OTP token

### Embedding 模型一致性

BM25（`chunks` 表）和 pgvector 向量**不能混用两种 embedding 模型**。MVP 用 `text-embedding-3-small`（1536 维）。切换到 BGE（1024 维）时必须全库重建，`chunks.embedding_model` 字段记录模型标识用于迁移过滤。

### BM25 实现

PostgreSQL 原生 `tsvector` 不是 BM25。需要 **`pg_bm25`** 扩展（ParadeDB）：
```sql
CREATE EXTENSION pg_bm25;
CREATE INDEX chunks_bm25 ON chunks USING bm25 (content);
```

### 分页规范

所有列表接口用**游标分页**（cursor-based），不用 offset 分页：
```
GET /api/v1/reports?cursor=<opaque>&limit=20
```

### 志愿数上限

前端志愿表最大条数从后端 `GET /api/v1/data/availability` 的 `max_volunteers` 字段读取（省份动态上限，默认 96）。**不能硬编码 30**。

### 合规禁词

报告文案和前端文字中禁止出现：保证录取、必中、精准录取、包过、保上、内部数据、代替填报。Reflection Agent 第一层用正则检测，第二层用 LLM judge 检测语义过承诺。

---

## 数据模型要点

- **`admission_scores`**：必须有 `batch` 字段区分本科批/专科批
- **`province_thresholds`**：省份级冲稳保位次阈值配置表，替代代码内硬编码
- **LangGraph checkpoint 表**（`checkpoints`/`checkpoint_blobs`/`checkpoint_writes`）：由 LangGraph 自动管理，不是业务表，不在 `alembic` 迁移中维护
- **`agent_runs`** 通过 `thread_id` 与 LangGraph checkpoint 关联，只存业务元数据；同时承载 Admin Debug Console 所需的 `debug_summary_json`（node_timings、tool_call_summary、cost_breakdown 等，无 PII）
- **`report_conversations`**（ORM 类 `ReportConversation`）：报告问答历史冷层，`report_id` + `user_id` 唯一，`messages_json` 只保留最近 50 条；Redis 才是真正的热层，DB 写入是 best-effort（失败不影响主流程）
- **`users`**：`email`（unique）、`password_hash`、`email_verified`、`openid`（预留）、`role`
- **`sessions`**：ORM 模型类名为 `AuthSession`，表名 `sessions`

---

## 当前实现状态

项目处于 Phase 1。已有：
- 前端：Chat-first 首屏（`/`，纯聊天入口 `IntakeChat` → 命中建档意图后内联渲染建档表单 → 生成过程 → 报告问答，同一对话流）、报告工作台（`/reports/[id]`）、响应式三栏工作台壳（`SidebarNav` + `WorkspaceShell`，`<lg` 抽屉/BottomSheet，`≥lg` 三栏常驻）、Admin Debug 抽屉（`components/admin/debug/`）；Web 端居中 Modal 登录/注册
- 后端：邮箱鉴权、LangGraph Agent 编排（Reflection 合规自检，无 HITL）、Resend 邮件验证码、报告问答 ConversationAgent（独立 SSE，不走 ARQ）、Chat-first 建档前聊天 IntakeAgent（`POST /intake/chat`，function calling 查学校/分数/选科/对比 + `start_profile_capture` 触发建档表单，独立 SSE）、Admin Debug Console（运行时指标 + LangGraph 拓扑回放）
- Agent 节点：data_resolver → 并行 retrieval/policy_rule → recommendation → risk → report → reflection（最多 3 轮重试后直接交付）
- 工具层弹性设计：ToolResponse 三态协议、CircuitBreaker 熔断、ToolFilter 按 Agent 限制工具可见性

---

## 文档同步（.cursor/rules 已强制）

修改后端 API / 鉴权 / 数据模型 / Agent 图 / 前端路由时，**必须在同一任务内同步更新对应文档**，不要只改代码留文档过时：

| 变更类型 | 需同步的文件 |
| -------- | ------------ |
| 后端 API / 鉴权 | `docs/backend-prd.md`、`CLAUDE.md` |
| 数据模型 / 迁移 | `docs/backend-prd.md`、`backend/docs/03_data_model.md` |
| Agent 图 / State | `docs/backend-prd.md`、`backend/docs/02_agent_design.md` |
| 前端页面 / 路由 | `docs/frontend-prd.md` |
| 产品定位 / MVP 范围 | `README.md`、`docs/sprint-plan.md` |

删除或废弃的功能：从接口表中移除，或在章节顶部标注「已移除（vX.X）」，不要留可能误导的实现说明（本文件的「已移除（v1.1）」就是这个约定的例子）。完成前自检：`grep` 文档中是否仍残留已删除模块的关键词。
