# 问津 Agent — 执行 Sprint 计划

版本：v1.1  
日期：2026-07-01  

> **v1.1 实现变更**：M3 的 HITL 复核闭环已取消；鉴权改为邮箱+密码。代码为准，本计划部分 Day 8-9 HITL 条目仅作历史参考。
目标：**7-10 天完成三个里程碑，部署上线，可作为面试作品集展示**

> 本文件是**执行索引**，不重复 PRD 内容。技术细节见：
>
> - 后端架构/Agent/RAG/规则：[backend-prd.md](./backend-prd.md)
> - 前端页面/组件/交互：[frontend-prd.md](./frontend-prd.md)
> - 产品定位/MVP 范围：[README.md](../README.md)

---

## 里程碑总览

| 里程碑                    | 时间     | 目标                      | 结束时能展示                                      |
| ------------------------- | -------- | ------------------------- | ------------------------------------------------- |
| **M1：骨架跑通**          | Day 1-3  | 全链路可点击，数据 mock   | 建档 → 进度页 → 报告页完整走通；LiteLLM 网关跑通  |
| **M2：核心引擎**          | Day 4-7  | 真实业务逻辑，真实数据    | 三套方案用真实算法；RAG 证据检索；LangSmith trace |
| **M3：Agent 深化 + 上线** | Day 8-10 | 完整 Agent 编排，部署线上 | Reflection 自检；邮箱鉴权；线上 URL 可访问（**HITL 已移除**） |

---

## M1：骨架跑通（Day 1-3）

**目标**：全链路技术栈跑通，数据可以 mock，但每层（前端/BFF/FastAPI/LangGraph/LiteLLM/DB）都真实存在且连通。

### M1 DoD（Definition of Done）

```
✅ docker compose up 一键启动所有服务（前端/后端/DB/Redis/LiteLLM/ARQ Worker）
✅ DB schema 建好，alembic migration 可运行
✅ 河南省 seed data 脚本结构就位（即使数据量少）
✅ LiteLLM Proxy 启动，至少一个 Agent 调用 gpt-4o-mini 成功，LangSmith 有 trace 记录
✅ 建档问诊 6 步 Wizard 可完整填写，数据写入数据库
✅ 点击"生成方案" → ARQ Worker 收到任务 → SSE 进度条有响应
✅ 报告页三套方案 Tab 可切换（hardcode 数据即可）
✅ 匿名会话创建正常，手机号登录流程可走通
```

### Day 1：基础设施 + 项目骨架

**目标**：所有服务容器跑起来，互相能通信。

| 任务                                                                                      | 类型     | 参考                     |
| ----------------------------------------------------------------------------------------- | -------- | ------------------------ |
| 初始化 monorepo 结构（`/frontend` + `/backend`）                                          | infra    | —                        |
| `docker-compose.yml`：postgres+pgvector / redis / litellm / fastapi / nextjs / arq-worker | infra    | backend-prd Section 17   |
| `litellm_config.yaml`：配置 5 个虚拟模型名，验证至少一个调用成功                          | infra    | backend-prd Section 16   |
| FastAPI 项目骨架：`/health` 端点，环境变量加载，数据库连接                                | backend  | —                        |
| Alembic 初始化，建第一批核心表：`users / sessions / student_profiles / agent_runs`        | backend  | backend-prd Section 6.1  |
| Next.js App Router 骨架：`/` 路由跑通，Tailwind 配置                                      | frontend | —                        |
| `.env.example` 文件（含所有环境变量，不含真实密钥）                                       | infra    | backend-prd Section 17.4 |

**Day 1 验收**：`docker compose up` 后，`GET /health` 返回 200，`GET /` 前端页面可访问。

---

### Day 2：核心 API + LangGraph Mock + ARQ

**目标**：报告生成的异步链路跑通（即使 Agent 返回 hardcode 数据）。

| 任务                                                                              | 类型    | 参考                         |
| --------------------------------------------------------------------------------- | ------- | ---------------------------- |
| Alembic 补全剩余表：`preferences / reports / human_reviews / chunks` 等           | backend | backend-prd Section 6.1      |
| `POST /api/v1/auth/session`：创建匿名会话                                         | backend | backend-prd Section 5.1      |
| `POST /api/v1/profile`、`GET /api/v1/profile/{id}`：档案 CRUD                     | backend | backend-prd Section 5.1      |
| `POST /api/v1/reports/generate`：创建 agent run，投入 ARQ 队列，返回 run_id       | backend | backend-prd Section 5.1, 5.3 |
| `GET /api/v1/agent/runs/{id}/events`：SSE 端点，从 Redis Stream 读取事件          | backend | backend-prd Section 5.3      |
| LangGraph State Schema 定义（`VolunteerPlanState`）                               | backend | backend-prd Section 10.2     |
| LangGraph Mock 图（5 个节点，全部 sleep + 返回 hardcode 数据，同时推送 SSE 事件） | backend | backend-prd Section 10.3     |
| ARQ Worker 启动脚本，消费队列并运行 LangGraph 图                                  | backend | backend-prd Section 2        |

**Day 2 验收**：`POST /reports/generate` → ARQ Worker 收到任务 → SSE 5 个节点事件依次推送 → run status 变为 completed。

---

### Day 3：前端骨架 + M1 端到端联调

**目标**：用户能从入口页走完完整流程，看到 hardcode 报告。

| 任务                                                                      | 类型     | 参考                     |
| ------------------------------------------------------------------------- | -------- | ------------------------ |
| 入口页（`/`）：三张入口卡片 + 登录入口                                    | frontend | frontend-prd Section 8.1 |
| 快速测算页（`/assess`）：省份/分数/位次/选科表单，提交后展示风险画像卡片  | frontend | frontend-prd Section 8.2 |
| 建档问诊（`/profile`）：6 步 Wizard，自动保存草稿，完整度进度条           | frontend | frontend-prd Section 8.4 |
| 生成进度页（`/reports/generating`）：SSE 连接，纵向时间线节点状态         | frontend | frontend-prd Section 8.5 |
| 报告详情页（`/reports/[id]`）：hardcode 三套方案 Tab + 推荐卡片（可展开） | frontend | frontend-prd Section 8.6 |
| `LoginSheet` 组件：手机号 + 验证码，底部弹出                              | frontend | frontend-prd Section 7.4 |
| Next.js BFF Route Handler：转发 API 请求，注入 session cookie             | frontend | backend-prd Section 2    |
| **M1 端到端冒烟测试**：走一遍完整流程，确认每页都无报错                   | QA       | —                        |

**Day 3 验收**：M1 DoD 全部打勾。

---

## M2：核心引擎（Day 4-7）

**目标**：规则引擎、推荐算法、风险引擎、RAG 全部用真实逻辑，报告数据从数据库来。

### M2 DoD

```
✅ 选科/体检/批次 3 类硬规则过滤正确（单元测试覆盖）
✅ 冲稳保评分算法可测（位次差阈值、4 个子分计算）
✅ 三套方案比例符合 PRD 定义（保守 20/40/40，均衡 35/40/25，进取 50/35/15）
✅ pgvector HNSW 索引建好，text-embedding-3-small 向量检索跑通
✅ Cohere Rerank API 跑通，top-8 证据进入 Context Pack
✅ 报告推荐卡片绑定真实 source_id（来自 SQL 数据）
✅ LangSmith Trace 有完整 5 节点链路记录（含 token 消耗）
✅ 禁词合规检查（正则层）能正确拦截"保证录取"等词
✅ 志愿表手动录入 + 3 类核心风险项（保底/梯度/选科冲突）正确展示
✅ 报告历史页可展示过往报告列表
```

### Day 4：数据 + 规则引擎 + 工具可靠性基础

**目标**：种好真实数据，规则引擎可测试；同步建立工具层可靠性基础（ToolResponse + CircuitBreaker）。

| 任务                                                                                                                                        | 类型     | 参考                          |
| ------------------------------------------------------------------------------------------------------------------------------------------- | -------- | ----------------------------- |
| 河南省 seed data（50+ 所学校，3 年投档线，一分一段表，选科要求）                                                                            | data     | backend-prd Section 7         |
| `GET /api/v1/data/availability`：省份数据可用性检查                                                                                         | backend  | backend-prd Section 5.2       |
| **新建 `backend/app/agent/tool_response.py`**：ToolResponse 三态（SUCCESS/PARTIAL/ERROR），含 `to_dict`/`from_dict`                         | backend  | backend-prd Section 10.8      |
| **新建 `backend/app/agent/circuit_breaker.py`**：CircuitBreaker（failure_threshold=3, recovery_timeout=300s），保护 Cohere/LiteLLM/pgvector | backend  | backend-prd Section 10.8      |
| Rule Engine：`check_subject_req` / `check_medical_restriction` / `check_batch_eligibility` / `check_budget`，**返回值改为 `ToolResponse`**  | backend  | backend-prd Section 8.2, 10.8 |
| Rule Engine 单元测试（至少 10 个 case，覆盖 pass/fail/partial；**新增 PARTIAL 降级 case**）                                                 | test     | backend-prd Section 15.3      |
| `POST /api/v1/risk/preview`：同步风险画像（< 2s）                                                                                           | backend  | backend-prd Section 5.1       |
| 前端快速测算页接入真实 `risk/preview` API，展示真实风险画像                                                                                 | frontend | frontend-prd Section 8.2      |

---

### Day 5：推荐算法 + 风险引擎

**目标**：冲稳保分层、评分排序、志愿体检逻辑跑通。

| 任务                                                                                                | 类型     | 参考                      |
| --------------------------------------------------------------------------------------------------- | -------- | ------------------------- |
| `admission_score` 子分计算（位次差 + 稳定性）                                                       | backend  | backend-prd Section 8.1.1 |
| `major_fit_score` / `city_family_score` / `cost_risk_score` 子分计算                                | backend  | backend-prd Section 8.1.1 |
| 冲稳保分层阈值（`rush/target/safe/high_rush`）                                                      | backend  | backend-prd Section 8.1.2 |
| 三套方案生成器（按比例从候选池组装 conservative/balanced/aggressive）                               | backend  | backend-prd Section 8.1.3 |
| Risk Engine：`check_safety_adequacy` / `check_gradient` / `check_crowding` / `check_rejected_major` | backend  | backend-prd Section 8.3   |
| `POST /api/v1/volunteer/check`：志愿表体检同步接口（< 5s）                                          | backend  | backend-prd Section 5.1   |
| 推荐算法单元测试（10+ case）                                                                        | test     | —                         |
| 志愿表体检页（`/volunteer-check`）：手动录入卡片列表 + 风险摘要悬浮条                               | frontend | frontend-prd Section 8.3  |

---

### Day 6：RAG Pipeline

**目标**：向量检索 + Rerank + 证据打包跑通。

| 任务                                                                       | 类型     | 参考                         |
| -------------------------------------------------------------------------- | -------- | ---------------------------- |
| pgvector HNSW 索引建立（`m=16, ef_construction=64`，维度 1536）            | data     | backend-prd Section 6.2, 9.2 |
| 文档 chunking 脚本（按 PRD chunk 策略切分招生章程/专业介绍/政策文件）      | data     | backend-prd Section 9.2      |
| Embedding pipeline：批量向量化 chunks，写入 pgvector（经 LiteLLM Gateway） | data     | backend-prd Section 9.2      |
| `vector_search` 工具：pgvector cosine similarity，top-20                   | backend  | backend-prd Section 10.4     |
| `search_admission_sql` 工具：按省份/年份/批次/专业组精确检索结构化数据     | backend  | backend-prd Section 10.4     |
| `rerank_evidence` 工具：Cohere Rerank API，top-8 进入 Context Pack         | backend  | backend-prd Section 9.2      |
| `GET /api/v1/sources/{id}`：证据来源详情接口                               | backend  | backend-prd Section 5.1      |
| 数据源详情页（`/sources/[id]`）：展示证据完整信息                          | frontend | frontend-prd Section 8.8     |
| 报告推荐卡片证据入口：点击唤起 `EvidenceDrawer`（Bottom Sheet）            | frontend | frontend-prd Section 8.6     |

---

### Day 7：LangGraph 真实编排 + M2 联调

**目标**：把 Day 2 的 mock 节点替换成真实逻辑，报告从真实数据生成。

| 任务                                                                                                                                                                                          | 类型     | 参考                                 |
| --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- | ------------------------------------ |
| Data Resolver 节点：锁定 dataset_version，校验 published 状态                                                                                                                                 | backend  | backend-prd Section 10.1             |
| Retrieval Agent 节点（LLM）：**参考 HelloAgents ReActAgent tool-calling sub-loop**；query rewrite → vector_search → rerank → evidence pack；工具返回 ToolResponse，PARTIAL 时写 data_warnings | backend  | backend-prd Section 10.1, 10.4, 10.8 |
| **新建 `backend/app/agent/tool_filter.py`**：ToolFilter 按 Section 10.8 工具视野表为每个节点过滤工具 Registry                                                                                 | backend  | backend-prd Section 10.8             |
| Policy Rule Agent 节点（确定性）：调用 Rule Engine 4 个工具，**CircuitBreaker 保护每个工具调用**                                                                                              | backend  | backend-prd Section 10.1             |
| 并行执行：Retrieval Agent + Policy Rule Agent 通过 LangGraph `Send` API 并发                                                                                                                  | backend  | backend-prd Section 10.3, 10.7       |
| Recommendation Agent 节点（确定性）：调用评分/分层/三套方案生成                                                                                                                               | backend  | backend-prd Section 10.1             |
| Report Agent 节点（LLM）：模板渲染 + 证据引用，经 LiteLLM 调用；**CircuitBreaker 保护 LiteLLM 调用**                                                                                          | backend  | backend-prd Section 10.1, 10.4, 10.8 |
| Compliance 正则检查（禁词层，不含 LLM Judge，LLM Judge 是 M3 任务）                                                                                                                           | backend  | backend-prd Section 12.1             |
| 报告详情页接入真实数据（替换 hardcode）                                                                                                                                                       | frontend | frontend-prd Section 8.6             |
| 报告历史页（`/reports`）                                                                                                                                                                      | frontend | frontend-prd Section 8.9             |
| **M2 端到端验证**：输入真实案例（分数 612/位次 32680/河南/物化），确认报告内容真实                                                                                                            | QA       | —                                    |
| LangSmith 检查：确认 5 节点 trace 完整，token 消耗有记录                                                                                                                                      | QA       | backend-prd Section 14.1             |

**Day 7 验收**：M2 DoD 全部打勾。

---

## M3：Agent 深化 + 上线（Day 8-10）

**目标**：完整 Agent 编排（含 Reflection + HITL），线上部署，demo 准备就绪。

### M3 DoD

```
✅ Reflection Agent：正则禁词层 + LLM Judge 层，最多 3 轮自检，3 轮失败强制触发复核；LLM 输出 passed=true 时早退出
✅ ToolResponse 三态：所有工具返回 ToolResponse，PARTIAL 自动写 data_warnings，CircuitBreaker 对 3 个外部调用点生效
✅ ToolFilter：每个 Agent 节点只能看到各自权限范围内的工具（见 backend-prd Section 10.8）
✅ HITL 完整闭环：interrupt() → human_reviews 记录 → 复核员提交 PATCH → resume() → 报告交付
✅ 复核员工作台（/admin/reviews）：待复核队列 + 领取 + 提交结论
✅ 用户侧复核等待页：复核状态展示 + 等待提示
✅ Railway 部署：FastAPI + ARQ Worker + LiteLLM + PostgreSQL + Redis 全部线上
✅ Vercel 部署：Next.js 前端线上，URL 可访问，可分享给面试官
✅ 生产环境 seed data 就位（河南省完整数据集）
✅ 5-10 个 Demo 案例走通（见下方清单）
✅ 面试 demo 演示脚本准备好
```

### Day 8：Reflection Agent + HITL 后端

**目标**：LangGraph 完整 Agent 链路跑通，包含 interrupt/resume。

| 任务                                                                                                                                                                             | 类型    | 参考                           |
| -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------- | ------------------------------ |
| Reflection Agent 节点：`check_compliance`（正则层） + `llm_judge`（语义过度承诺检测）                                                                                            | backend | backend-prd Section 10.1, 12.1 |
| Reflection 循环保护：`reflection_iterations` 计数器，3 轮上限；**实现"无需改进"早退出**（参考 HelloAgents ReflectionAgent，LLM 输出 `passed=true` 时立即 break，不等待剩余轮次） | backend | backend-prd Section 10.6       |
| `human_review_node`：`render_review_draft` 生成底稿，`interrupt()` 暂停图执行                                                                                                    | backend | backend-prd Section 10.1, 11.2 |
| `POST /api/v1/reviews`：创建复核任务                                                                                                                                             | backend | backend-prd Section 5.1        |
| `PATCH /api/v1/reviews/{id}`：提交复核结论（approved/rejected），触发 run resume                                                                                                 | backend | backend-prd Section 5.1, 11.7  |
| `POST /api/v1/agent/runs/{id}/resume`：将复核结论注入 State，恢复图执行                                                                                                          | backend | backend-prd Section 5.1        |
| Profile Agent 节点：档案完整性检查，不足时返回追问列表                                                                                                                           | backend | backend-prd Section 10.1       |
| `human_interrupt` SSE 事件推送到前端                                                                                                                                             | backend | backend-prd Section 5.3        |

---

### Day 9：HITL 前端 + 可观测性 + 质量

**目标**：复核流程前端完整，可观测性确认，移动端适配验收。

| 任务                                                                                   | 类型     | 参考                     |
| -------------------------------------------------------------------------------------- | -------- | ------------------------ |
| 人工复核页（`/reports/[id]/review`）：复核状态条 + AI 底稿折叠卡 + 风险清单 + 结论展示 | frontend | frontend-prd Section 8.7 |
| 复核员工作台（`/admin/reviews`）：待复核队列 + 领取任务 + 提交通过/拒绝                | frontend | frontend-prd Section 6   |
| 报告页 HITL 入口：高风险时展示"建议人工复核"橙色提示条 + 主按钮                        | frontend | frontend-prd Section 8.7 |
| 生成进度页：收到 `human_interrupt` 事件后切换到"复核等待"状态                          | frontend | frontend-prd Section 8.5 |
| 错误状态完善：所有页面的 loading/empty/error 状态（Skeleton、EmptyState、Toast）       | frontend | frontend-prd Section 9   |
| LangSmith Dashboard 确认：成本追踪有记录，P95 延迟可见                                 | QA       | backend-prd Section 14   |
| 结构化日志格式确认（run_id / node / event / latency_ms 字段完整）                      | QA       | backend-prd Section 14.2 |

---

### Day 10：部署 + Demo 准备

**目标**：线上 URL 可访问，demo 案例就绪，面试脚本准备好。

| 任务                                                                 | 类型  | 参考                     |
| -------------------------------------------------------------------- | ----- | ------------------------ |
| Railway 部署：FastAPI Service + ARQ Worker Service + LiteLLM Service | infra | backend-prd Section 17   |
| Railway 数据库：PostgreSQL + pgvector 插件启用                       | infra | backend-prd Section 17.2 |
| Railway Redis：配置 Redis Service                                    | infra | backend-prd Section 17.2 |
| Vercel 部署：Next.js，配置 `NEXT_PUBLIC_API_URL` 环境变量            | infra | backend-prd Section 17.2 |
| 生产环境 seed data 运行：河南省招生数据 + 向量化入库                 | data  | —                        |
| 端到端生产冒烟测试：走一遍报告生成完整流程                           | QA    | —                        |
| **Demo 案例准备**（见下方清单）                                      | QA    | —                        |
| 面试 demo 演示脚本                                                   | docs  | README Section 14        |

---

## Demo 案例清单（M3 必须就绪）

| #   | 案例类型       | 输入                                        | 预期输出                                   | 展示技术点                                 |
| --- | -------------- | ------------------------------------------- | ------------------------------------------ | ------------------------------------------ |
| 1   | 正常流程       | 省份河南 / 分数 612 / 位次 32680 / 物理化学 | 三套方案，均衡型推荐 8 所，有证据链        | 完整 Agent 链路、RAG 证据、LangSmith trace |
| 2   | 高风险触发复核 | 同上但保底只填 2 所                         | 报告生成后触发 HITL，展示复核等待页        | interrupt/resume 机制                      |
| 3   | 选科冲突       | 选历史，但填报了物理类专业                  | 规则过滤命中，报告标红，选科冲突风险项     | Rule Engine 确定性校验                     |
| 4   | 合规拦截       | 在测试用例中注入"保证录取"表述              | Reflection Agent 拦截，report_draft 被修正 | Reflection + 合规自检                      |
| 5   | 体检限制       | 填报临床医学，档案注明色觉异常              | 体检限制高风险标红，建议复核               | 医学限制规则                               |

---

## GitHub 项目管理配置

### Milestones 设置

在 GitHub repo → Issues → Milestones 创建：

| Milestone    | Due Date | 描述                                    |
| ------------ | -------- | --------------------------------------- |
| M1：骨架跑通 | Day 3    | 全链路联通，mock 数据可 demo            |
| M2：核心引擎 | Day 7    | 真实业务逻辑，RAG 检索，LangSmith trace |
| M3：上线     | Day 10   | HITL 闭环，线上部署，demo 就绪          |

### Labels 设置

```
backend     蓝色   后端 API / 服务
frontend    绿色   前端页面 / 组件
agent       紫色   LangGraph / Agent 逻辑
infra       橙色   Docker / 部署 / 配置
data        黄色   Seed data / ETL / 向量化
test        灰色   单元测试 / 集成测试
```

### Issue 模板

每个 Issue 标题格式：`[M1/M2/M3] 功能描述`，正文包含：

- 具体任务列表（checkbox）
- 参考 PRD 章节链接
- DoD 条件

### 建议 Issue 拆分粒度

每个 Issue 控制在 **半天到一天** 可完成。每完成一个 Issue 立即 close 并移到 Done。

---

## 当前版本 Phase 2 留存项

以下功能不影响技术深度展示，不在本 Sprint 内实现：

| 功能                           | 原因                                        | Phase 2 切入点                          |
| ------------------------------ | ------------------------------------------- | --------------------------------------- |
| 志愿表文件上传 + OCR           | 与核心技术点无关，需额外文件解析服务        | 引入异步文件处理后实现                  |
| 自托管 BGE embedding（需 GPU） | 只改 LiteLLM config 即可切换，无代码变更    | Railway 支持 GPU 实例后迁移             |
| BM25 + RRF 混合检索            | SQL + 向量检索已满足 MVP                    | 向量检索效果验证后引入 BM25             |
| HITL `need_more_info` 子流程   | 主干 approved/rejected 已完整，子流程是增量 | 复核员反馈收集后实现                    |
| 黄金评测集 30-50 案例          | 5-10 个够 demo，大批量自动化是 CI 工作      | Phase 2 引入 LangSmith Dataset 自动评测 |
| 多省份数据                     | 窄而深比宽而浅更有价值，1 省做透即可        | 验证河南省数据链路稳定后扩展            |

---

## 技术债追踪（M3 后处理）

| 债项                        | 影响                               | 处理方式                              |
| --------------------------- | ---------------------------------- | ------------------------------------- |
| Mock 数据替换               | 非河南省用户体验差                 | Phase 2 多省份数据接入                |
| Redis LRU 驱逐 checkpoint   | 长 HITL 等待可能丢失 State         | 生产环境加 PostgreSQL checkpoint 双写 |
| 正则禁词列表维护            | 新的违规表达需人工更新             | Phase 2 建立禁词管理后台              |
| LangSmith 离线 Dataset 评测 | 目前只有 runtime trace，无自动回归 | Phase 2 接入 CI 自动运行评测集        |
