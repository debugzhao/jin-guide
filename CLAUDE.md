# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## 项目简介

**问津 Agent** — 面向高考生和家长的 AI 志愿决策助理。核心能力：建档、规则校验、冲稳保方案生成、志愿表风险体检、人工复核（Human-in-the-loop）。PRD 文档在 `docs/` 目录，是理解业务逻辑的首要参考。

---

## 开发命令

### 一键启动（推荐）

```bash
cp .env.example .env          # 填入 OPENAI_API_KEY 等必填值
docker-compose up             # 启动全栈：postgres、redis、litellm、backend、worker、frontend
```

服务端口：前端 3000 · 后端 8000 · LiteLLM 4000 · PostgreSQL 5432 · Redis 6379

### 单独启动各服务

```bash
# 后端
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
                                         LiteLLM Proxy → OpenAI / Anthropic
```

- **BFF 层**：轻量鉴权、SSE 转发、文件预处理，不含业务逻辑
- **API 层**：`backend/app/api/v1/` — 同步 HTTP 处理，Agent run 投入 ARQ 队列后立即返回
- **Worker 层**：`backend/app/worker.py` — ARQ worker，在独立进程运行 LangGraph。**不用 FastAPI BackgroundTasks 做 Agent run**，原因是进程重启会丢失任务
- **Agent 层**：`backend/app/agent/` — LangGraph 编排多 Agent，通过工具调用确定性服务，不直接访问 DB
- **模型网关**：所有 LLM 调用经 LiteLLM Proxy（`:4000`），不直接调用厂商 API

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
- **`agent_runs`** 通过 `thread_id` 与 LangGraph checkpoint 关联，只存业务元数据
- 软删除字段：`documents.deleted_at`、`reports.deleted_at`

---

## 当前实现状态

项目处于 Phase 1 早期。已有脚手架：
- 前端：入口页（`/`）、快速测算（`/assess`）、建档向导（`/profile`）、报告页（`/reports/[id]`）、生成进度页（基础 UI）
- 后端：模型定义（`backend/app/models/`）、API 路由骨架（`backend/app/api/v1/`）、Agent graph 占位（`backend/app/agent/nodes/mock_nodes.py`）
- Agent 节点目前为 mock，真实实现待开发
