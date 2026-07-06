# 问津 Agent — 执行 Sprint 计划

版本：v1.3  
日期：2026-07-06  

> **v1.3 更新**：新增 Phase 3 Sprint（P3 Day 1-6）——「AI 全程协作者」产品重构，规划来源见 [`docs/prd-redesign-ai-collaborator.md`](./prd-redesign-ai-collaborator.md)（已评审通过，Generative UI 混合形态）。核心变化：生成进度页从静态 checklist 升级为可见的 Agent 协作时间线、建档问诊从固定表单向导改为对话流+结构化控件、ConversationAgent 从纯问答升级为可操作报告画布的 tool-calling agent、新增方案对比能力。新增 Demo 案例 #8 / #9 / #10。  
> **v1.2 更新**：新增 Phase 2 Sprint（P2 Day 1-3），包含两个新功能：① 报告问答 Chat Panel（ConversationAgent）② Admin Debug 控制台（LangGraph 实时拓扑图 + Debug 事件时间线）。新增 Demo 案例 #6 / #7。  
> **v1.1 实现变更**：M3 的 HITL 复核闭环已取消，未实现；鉴权改为邮箱+密码（非手机号）。以下 Day 8-9 已同步移除 HITL 相关任务，仅保留实际交付内容。
目标：**7-10 天完成三个里程碑，部署上线，可作为面试作品集展示**；Phase 3 目标：**把黑盒的 Agent 编排能力和单向的报告交付，改造成用户可感知、可对话调整的协作体验**

> 本文件是**执行索引**，不重复 PRD 内容。技术细节见：
>
> - 后端架构/Agent/RAG/规则：[backend-prd.md](./backend-prd.md)
> - 前端页面/组件/交互：[frontend-prd.md](./frontend-prd.md)
> - 产品定位/MVP 范围：[README.md](../README.md)

---

## 里程碑总览

| 里程碑                    | 时间        | 目标                         | 结束时能展示                                                         |
| ------------------------- | ----------- | ---------------------------- | -------------------------------------------------------------------- |
| **M1：骨架跑通**          | Day 1-3     | 全链路可点击，数据 mock      | 建档 → 进度页 → 报告页完整走通；LiteLLM 网关跑通                     |
| **M2：核心引擎**          | Day 4-7     | 真实业务逻辑，真实数据       | 三套方案用真实算法；RAG 证据检索；LangSmith trace                    |
| **M3：Agent 深化 + 上线** | Day 8-10    | 完整 Agent 编排，部署线上    | Reflection 自检；邮箱鉴权；线上 URL 可访问（**HITL 已移除**）        |
| **Phase 2：增强功能**     | P2 Day 1-3  | Chat Panel + Admin Debug     | 报告问答 AI 助手；LangGraph 实时拓扑图；Debug 事件时间线             |
| **Phase 3：AI 协作者重构** | P3 Day 1-6  | 编排可视化前置 + 多轮交互能力 | 生成过程可见的协作时间线；建档 Generative UI 化；改约束重新生成 + 方案对比 |

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
✅ 匿名会话创建正常，邮箱登录流程可走通
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
| Alembic 补全剩余表：`preferences / reports / chunks` 等           | backend | backend-prd Section 6.1      |
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
| `LoginModal` 组件：邮箱 + 验证码/密码，居中 Modal 弹出                    | frontend | frontend-prd Section 7.4 |
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

**目标**：完整 Agent 编排（含 Reflection 自检），线上部署，demo 准备就绪。

### M3 DoD

```
✅ Reflection Agent：正则禁词层 + LLM Judge 层，最多 3 轮自检；LLM 输出 passed=true 时早退出；3 轮失败后 best-effort 直接交付
✅ ToolResponse 三态：所有工具返回 ToolResponse，PARTIAL 自动写 data_warnings，CircuitBreaker 对 3 个外部调用点生效
✅ ToolFilter：每个 Agent 节点只能看到各自权限范围内的工具（见 backend-prd Section 10.8）
✅ Railway 部署：FastAPI + ARQ Worker + LiteLLM + PostgreSQL + Redis 全部线上
✅ Vercel 部署：Next.js 前端线上，URL 可访问，可分享给面试官
✅ 生产环境 seed data 就位（河南省完整数据集）
✅ 5-10 个 Demo 案例走通（见下方清单）
✅ 面试 demo 演示脚本准备好
```

### Day 8：Reflection Agent 后端

**目标**：LangGraph 完整 Agent 链路跑通，含 Reflection 自检回退。

| 任务                                                                                                                                                                             | 类型    | 参考                           |
| -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------- | ------------------------------ |
| Reflection Agent 节点：`check_compliance`（正则层） + `llm_judge`（语义过度承诺检测）                                                                                            | backend | backend-prd Section 10.1, 12.1 |
| Reflection 循环保护：`reflection_iterations` 计数器，3 轮上限；**实现"无需改进"早退出**（参考 HelloAgents ReflectionAgent，LLM 输出 `passed=true` 时立即 break，不等待剩余轮次） | backend | backend-prd Section 10.6       |
| Profile Agent 节点：档案完整性检查，不足时返回追问列表                                                                                                                           | backend | backend-prd Section 10.1       |

---

### Day 9：可观测性 + 质量

**目标**：可观测性确认，移动端适配验收。

| 任务                                                                                   | 类型     | 参考                     |
| -------------------------------------------------------------------------------------- | -------- | ------------------------ |
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

## Demo 案例清单（M3 + Phase 2 就绪）

| #   | 案例类型               | 输入                                          | 预期输出                                             | 展示技术点                                         |
| --- | ---------------------- | --------------------------------------------- | ---------------------------------------------------- | -------------------------------------------------- |
| 1   | 正常流程               | 省份河南 / 分数 612 / 位次 32680 / 物理化学   | 三套方案，均衡型推荐 8 所，有证据链                  | 完整 Agent 链路、RAG 证据、LangSmith trace         |
| 2   | 高风险方案展示         | 同上但保底只填 2 所                           | 报告生成后风险等级标红，风险总览卡片展示具体原因，不触发复核流程 | Risk Engine 确定性风险体检、RiskOverview 展示      |
| 3   | 选科冲突               | 选历史，但填报了物理类专业                    | 规则过滤命中，报告标红，选科冲突风险项               | Rule Engine 确定性校验                             |
| 4   | 合规拦截               | 在测试用例中注入"保证录取"表述                | Reflection Agent 拦截，report_draft 被修正           | Reflection + 合规自检                              |
| 5   | 体检限制               | 填报临床医学，档案注明色觉异常                | 体检限制高风险标红，提示需重新确认目标专业           | 医学限制规则                                       |
| 6   | 报告问答 Chat *(P2)*   | 报告生成后，用户提问"为什么推荐郑州大学？"    | ConversationAgent 流式回复，引用 2025 年招生数据     | ConversationAgent、RAG-over-report、行内引用标签   |
| 7   | Admin Debug *(P2)*     | 管理员打开 `/admin/debug`，触发一条新 run     | 拓扑图节点实时着色，并行区高亮，时间线实时滚动       | Debug SSE 事件、静态拓扑图、节点着色动画           |
| 8   | 协作时间线 *(P3)*      | 用户正常生成报告，观察生成进度页               | 并行任务分组展示、Reflection 迭代可见、降级安心文案  | 用户侧 SSE 事件转译、Generative UI 生成过程可视化  |
| 9   | 建档 AI 追问 *(P3)*    | 选择物理但再选组合在目标省份无招生计划         | 对话流中立即插入 AI 追问气泡，可选择调整或继续       | 对话流外壳、结构化控件渲染器、确定性字段依赖图     |
| 10  | 改约束+方案对比 *(P3)* | 报告页对话框输入"预算改到8万以内"，再要求对比方案 | Agent 确认后局部重跑生成新版本；对话触发对比视图展示差异 | ConversationAgent tool-calling、局部重跑、Generative UI 画布 |

---

## Phase 2 Sprint（P2 Day 1-3）

**目标**：在 M3 上线后，3 天内交付两个高价值增强功能：报告问答 Chat Panel 和 Admin Debug 控制台。

### Phase 2 DoD

```
✅ POST /api/v1/reports/{id}/chat 可用，流式 SSE 回复正常
✅ ConversationAgent 基于报告上下文回答，禁词正则检测覆盖对话输出
✅ 每用户每日 30 条对话限流生效，超限返回 429
✅ 对话历史写入 Redis（TTL 7天）+ PostgreSQL 双层存储
✅ 前端 Chat Panel：移动端底部 Sheet（70vh）/ 桌面 Drawer（380px）均正确展开
✅ 4 条预设建议问题展示，点击直接发送
✅ AI 回复含行内来源引用标签，点击跳转 /sources/[id]
✅ GET /api/v1/admin/runs 和 /admin/runs/{id} 可用（role=admin 鉴权）
✅ GET /api/v1/admin/runs/{id}/debug-events SSE 支持历史回放（0-0）
✅ LangGraph 节点执行时正确推送 node_completed / tool_called / parallel_fan_out / parallel_fan_in 等 Debug SSE 事件
✅ debug_summary_json 在 run 完成后由 Worker 写入 agent_runs 表
✅ 前端 /admin/debug：三栏布局（Run 列表 + 拓扑图 + 时间线）渲染正确
✅ LangGraph 拓扑图 10 个节点正确布局，节点状态随 Debug SSE 实时着色
✅ 并行区域（retrieval + policy_rule）边流动动画正常，fan_in 后动画消失
✅ Debug 事件时间线正确展示 8 种事件颜色，Auto-scroll 开启时自动滚动到最新
✅ role != admin 访问 /admin/debug 跳转 403，不渲染任何数据
```

---

### P2 Day 1：ConversationAgent 后端 + Debug SSE 基础

**目标**：Chat API 可用，LangGraph 节点开始发出 Debug 事件。

| 任务 | 类型 | 参考 |
| --- | --- | --- |
| Alembic 新增 `report_conversations` 表 + `agent_runs.debug_summary_json` JSONB 列 | backend | backend-prd Section 6.1 |
| `ConversationAgent`：加载报告上下文（plan_json 压缩 + profile），调用 LiteLLM 生成回复 | backend | backend-prd Section 10.9 |
| `ConversationAgent` 工具：`get_report_context`（只读），`vector_search`（scoped 到同省份年份） | backend | backend-prd Section 10.9 |
| `POST /api/v1/reports/{id}/chat`：SSE 端点，生成后合规检测，通过后流式推送 `token` 事件 | backend | backend-prd Section 5.1, 10.9 |
| `GET /api/v1/reports/{id}/chat/history`：从 Redis / PostgreSQL 读取对话历史 | backend | backend-prd Section 5.1 |
| `DELETE /api/v1/reports/{id}/chat`：清空 Redis + PostgreSQL 对话历史 | backend | backend-prd Section 5.1 |
| 对话每日 30 条限流：Redis 计数器，超限返回 `429 rate_limited` | backend | backend-prd Section 10.9 |
| **新建 `backend/app/agent/debug_events.py`**：`emit_debug_event(run_id, event_type, data)` 工具函数，XADD 写入 Redis Stream，try/except 静默 | backend | backend-prd Section 5.8 |
| LangGraph 各节点入口 / 出口注入 `emit_debug_event` 调用，推送 `node_started` / `node_completed` 事件 | agent | backend-prd Section 5.8 |
| `parallel_fan_out` / `parallel_fan_in` 事件：在 `after_data_resolver` 函数和 merge_node 中注入 | agent | backend-prd Section 5.8 |

**P2 Day 1 验收**：`POST /api/v1/reports/{id}/chat` 返回流式回复；执行任意一条 run 后，Redis Stream 中可见 `node_started` + `node_completed` + `parallel_fan_out` + `parallel_fan_in` 事件。

---

### P2 Day 2：Chat Panel 前端 + Admin Debug 后端 API

**目标**：Chat Panel 前端可用；Admin Run 列表和单 Run 元数据 API 可用。

| 任务 | 类型 | 参考 |
| --- | --- | --- |
| `ChatPanel` 组件：桌面 Drawer（380px）/ 移动 Sheet（70vh），含历史列表和输入区 | frontend | frontend-prd Section 8.6, 10 |
| `ChatSuggestedQuestions`：对话为空时展示 4 条预设问题卡片，点击直接发送 | frontend | frontend-prd Section 8.6 |
| `ChatMessageBubble`：用户右对齐 / AI 左对齐，含打字动画 `ChatTypingIndicator` | frontend | frontend-prd Section 8.6, 10 |
| `ChatInput`：多行文本框 200 字上限，Enter 发送 / Shift+Enter 换行 | frontend | frontend-prd Section 10 |
| `CitationInline`：行内来源引用徽章，hover 展示 Tooltip，点击跳转 `/sources/[id]` | frontend | frontend-prd Section 10 |
| 报告页"问一问"悬浮按钮（仅 run completed 时展示），点击打开 ChatPanel | frontend | frontend-prd Section 8.6 |
| Zustand 新增 Chat 状态：`isChatPanelOpen` / `conversation_id` / 消息缓存 / `streamingToken` | frontend | frontend-prd Section 11.1 |
| SSE 订阅 `POST /api/v1/reports/{id}/chat`：逐 token 追加到 `streamingToken`，收到 `done` 后提交为完整消息 | frontend | frontend-prd Section 8.6 |
| `GET /api/v1/admin/runs`：返回最近 50 条 run 的调试摘要（含 province、耗时、cost_usd、degraded_agents） | backend | backend-prd Section 14.5 |
| `GET /api/v1/admin/runs/{id}`：返回 node_timings、tool_call_summary、state_summary、cost_breakdown（从 debug_summary_json 读取） | backend | backend-prd Section 14.5 |
| `GET /api/v1/admin/metrics/summary`：从 Redis 计数器聚合返回指标快照 | backend | backend-prd Section 14.5 |
| FastAPI `require_admin_role` Dependency 注入所有 `/api/v1/admin/*` 路由 | backend | backend-prd Section 14.5 |
| ARQ Worker：run 完成后聚合 Redis Stream debug 事件，写入 `agent_runs.debug_summary_json` | backend | backend-prd Section 14.5 |
| **P2 Day 2 Chat 验收**：Chat Panel 在报告页正确展开，预设问题点击可发送，AI 流式回复正常 | QA | frontend-prd Section 14.1 |

**P2 Day 2 验收**：Chat Panel 端到端可用；`GET /api/v1/admin/runs` 返回带调试摘要的 run 列表。

---

### P2 Day 3：Admin Debug 前端（拓扑图 + 时间线）

**目标**：`/admin/debug` 完整可用，LangGraph 拓扑图实时着色，Debug 事件时间线可回放。

| 任务 | 类型 | 参考 |
| --- | --- | --- |
| `/admin/debug` 路由：`role=admin` 守卫（服务端 + 客户端双重检查），非 admin 跳转 403 | frontend | frontend-prd Section 8.11 |
| `DebugMetricsBar`：顶部指标条，TanStack Query 每 30s 轮询，错误率 > 10% 变红，P95 > 60s 数字标红 | frontend | frontend-prd Section 8.11, 10 |
| `DebugRunList`：左侧 Run 列表，状态/耗时/费用/降级标记，实时跟随开关，三种筛选条件 | frontend | frontend-prd Section 8.11, 10 |
| `GET /api/v1/admin/runs/{id}/debug-events`：Admin Debug SSE 端点，`XREAD 0-0` 历史回放，run 已完成时发送 `stream_end` 关闭连接 | backend | backend-prd Section 5.8, 14.5 |
| `LangGraphTopology`：CSS Grid + 绝对定位 SVG 边线，10 节点固定布局 | frontend | frontend-prd Section 8.11, 10 |
| `TopologyNode`：5 种状态颜色（pending/running/completed/degraded/failed）+ 脉冲动画（running）+ 徽章（degraded/failed） | frontend | frontend-prd Section 8.11, 10 |
| `TopologyEdge`：SVG 线条 3 种样式（主流程/并行/条件）；`parallel_fan_out` 事件触发并行边流动动画，`fan_in` 后动画消失 | frontend | frontend-prd Section 8.11, 10 |
| Reflection 回退循环箭头：`reflection_iteration(passed=false)` 事件时闪烁，节点右侧展示 `N/3` 迭代计数 | frontend | frontend-prd Section 8.11 |
| `NodeDetailPanel`：点击节点后展开，展示该节点工具调用列表（来自 `tool_called` 事件）、降级详情、Reflection 迭代状态 | frontend | frontend-prd Section 8.11, 10 |
| Zustand Debug 状态：`selectedRunId` / `isLiveFollowing` / `nodeStates` Map / `debugEvents` 数组 / `timelineFilter` | frontend | frontend-prd Section 11.1 |
| Debug SSE 订阅：消费 `debug-events` 流，按事件类型更新 `nodeStates`，追加 `debugEvents` | frontend | frontend-prd Section 8.11 |
| `DebugEventTimeline` + `DebugEventRow`：8 种事件颜色编码，筛选条，Auto-scroll，底部固定"在 LangSmith 查看 ↗"按钮 | frontend | frontend-prd Section 8.11, 10 |
| **Demo 案例 #6**：Chat Panel 演示（提问 → 流式回复 → 行内引用标签） | demo | sprint-plan Demo #6 |
| **Demo 案例 #7**：Admin Debug 演示（执行 run，实时观察拓扑图节点着色 → 并行边高亮 → 时间线事件） | demo | sprint-plan Demo #7 |

**P2 Day 3 验收**：Phase 2 DoD 全部打勾；Demo #6 / #7 可现场演示。

---

## Phase 3 Sprint（P3 Day 1-6）：AI 全程协作者重构

**目标**：解决"技术复杂度和产品体验脱节"的问题——LangGraph 并行编排、Reflection 自我修正、熔断降级目前只在 `/admin/debug` 可见，用户侧只有一条静态进度条；报告生成后是一次性交付，不能追问改约束、不能对比方案。完整设计见 [`docs/prd-redesign-ai-collaborator.md`](./prd-redesign-ai-collaborator.md)，产品形态决策为 **Generative UI 混合形态**（chat 是控制层，Tab/卡片/对比视图是呈现层，不做纯聊天式产品）。

**范围对照**：本 Sprint 的 P3 Day 1-6 对应 redesign 文档 §5 的 Phase 2a-2e（该文档编号在合并进本文件时改为 P3 Day，避免与已完成的「Phase 2：增强功能」混淆）。

### Phase 3 DoD

```
✅ 用户侧 SSE 新增 4 个事件（agents_parallel_started / agents_parallel_merged / self_check_round / degraded_notice），
   走既有 sse:{run_id} Stream，不新增事件源
✅ 生成进度页替换为「协作时间线」组件：并行任务显式分组展示、Reflection 轮次可见（类别化原因，不暴露原始违规文本/禁用词）、
   降级转译为安心文案
✅ 推荐卡片新增近两年历史投档位次并列 + 精确概率百分比（数据源复用 admission_scores 表，无需新数据管道）
✅ 报告页新增「AI 是如何得出这份方案的」可折叠回放卡片（只读，复用生成过程数据，不重新调用 Agent）
✅ 报告生成后展示 AI 条件点评（指出用户输入的张力/优化点），复用 report-agent 模型
✅ 建档问诊改为对话流外壳 + Agent 渲染结构化控件，字段排序/跳过为确定性配置驱动（不调用 LLM），
   仅矛盾/歧义项触发 Profile Agent 追问（最多 3 轮，沿用既有约束）
✅ ConversationAgent 升级为 tool-calling 架构：UI 操作类工具（switch_tab/highlight_candidates/open_compare_view/
   expand_risk_detail，纯前端状态变更）+ 数据变更类工具 regenerate_recommendations（触发局部重跑）
✅ POST /api/v1/reports/{id}/refine 可用：轻量约束只重跑 Recommendation→Risk→Report（复用 evidence_list/rule_results），
   重大约束（省份/选科/批次）提示需完整重新生成
✅ reports 表新增 version / parent_report_id 字段，报告页支持版本切换
✅ 方案对比视图：手动勾选或对话触发（open_compare_view），至少展示学校/专业/位次差/学费/风险等级 5 维度差异 + AI 取舍建议
✅ Kimi k2.6 流式 + tool-calling 并存场景完成技术 spike 验证（本 Sprint 唯一高不确定性技术点）
```

### P3 Day 1：用户侧 SSE 事件扩展 + 生成进度页协作时间线

**目标**：把 Debug 专属信号（并行执行、Reflection 迭代、降级）转译成用户可见事件，替换生成进度页的静态 checklist；同时顺手把推荐卡片数据密度提升一起做（复用度最高，边际成本低）。

| 任务 | 类型 | 参考 |
| --- | --- | --- |
| 新增用户侧事件转译逻辑：`agents_parallel_started`/`agents_parallel_merged`（复用 `parallel_fan_out`/`fan_in`，剥离节点技术名） | backend | backend-prd Section 5.7、prd-redesign §2.3 |
| 新增 `self_check_round` 事件：`reflection_iterations`/`compliance_issues` 转类别枚举（`over_promise`/`evidence_gap`/`none`），**不传原始违规文本** | backend | backend-prd Section 5.7、10.6 |
| 新增 `degraded_notice` 事件：维护"技术降级原因 → 用户安心文案"映射表（如 `vector_search→sql_search` → "检索遇到延迟，已切换备用数据源"） | backend | backend-prd Section 5.7 |
| 候选卡片数据扩展：从 `admission_scores` 读取近两年历史投档位次，评分模块补充精确概率百分比字段 | backend | backend-prd Section 8.1、prd-redesign §3.4-2 |
| 生成进度页重构为 `AgentCollaborationTimeline` 组件：并行任务分组框、Reflection 轮次展示、失败/降级文案 | frontend | frontend-prd Section 8.5 |
| 推荐卡片补充双年份历史位次 + 精确概率展示 | frontend | frontend-prd Section 8.6 |

**P3 Day 1 验收**：走一遍生成流程能看到"正在并行处理"分组框同时展示两个子任务、Reflection 至少一次迭代时能看到"第 N 轮：类别化原因"提示；报告卡片展示两年历史位次和百分比概率。

---

### P3 Day 2：报告页「决策过程回放」卡片 + 生成后 AI 点评

**目标**：把 Day 1 产生的过程数据沉淀成报告的一部分，另外加一段低成本的"AI 条件点评"（竞品借鉴，直接复用 report-agent 模型，无新增架构）。

| 任务 | 类型 | 参考 |
| --- | --- | --- |
| Alembic 新增字段：`agent_runs.run_summary_json`（用户可见摘要，区别于已有 `debug_summary_json`） | backend | backend-prd Section 6.1、prd-redesign §2.4 |
| ARQ Worker：run 完成后聚合协作时间线数据（并行任务、Reflection 轮次、是否降级），写入 `run_summary_json` | backend | backend-prd Section 10.9 |
| Report Agent prompt 扩展：生成"条件点评"段落（指出用户输入条件的张力/优化点） | backend | backend-prd Section 10.1、prd-redesign §3.4-1 |
| 报告页新增可折叠「AI 是如何得出这份方案的」卡片：只读回放 `run_summary_json`，不重新调用 Agent | frontend | frontend-prd Section 8.6 |
| 报告页考生概况卡片下方展示 AI 条件点评文案 | frontend | frontend-prd Section 8.6 |

**P3 Day 2 验收**：报告页能看到"决策过程回放"折叠卡片（展开后可见并行/Reflection/降级摘要）和一段 AI 条件点评。

---

### P3 Day 3-4：建档问诊 Generative UI 化

**目标**：把现有「步骤 1/6」硬编码表单向导，改造成对话流外壳 + Agent 渲染结构化控件；字段排序/跳过走确定性配置，只有检测到矛盾才触发 Profile Agent 追问。这是本 Sprint 里前端改动最大的一块，独立于 Day 5-6 的 ConversationAgent 改造，可并行安排。

| 任务 | 类型 | 参考 |
| --- | --- | --- |
| 定义字段依赖图配置（省份/批次/分数/位次/选科/个人信息之间的顺序与跳过规则，如专科批跳过本科限定字段） | backend | backend-prd Section 10.1、prd-redesign §3.1 |
| 轻量前置校验接口：复用 Policy Rule Agent 现有规则工具（`check_subject_req`/`check_batch_eligibility`），命中矛盾时返回 `profile_pending_questions` | backend | backend-prd Section 10.1、10.4 |
| `对话流外壳`组件：聊天容器承载逐条渲染的结构化控件 | frontend | frontend-prd Section 8.4 |
| `结构化控件渲染器`：字段 schema → 控件类型映射（下拉/数字输入/多选 chip） | frontend | frontend-prd Section 8.4 |
| 前端接入字段依赖图，实现跳过逻辑（纯配置驱动，不调用 LLM） | frontend | frontend-prd Section 8.4 |
| 对话式追问卡片组件：命中 `profile_pending_questions` 时插入澄清气泡（"调整选科" / "仍按此继续"按钮） | frontend | frontend-prd Section 8.4 |
| 动态进度百分比组件：替换固定的「步骤 1/6」 | frontend | frontend-prd Section 8.4 |
| **QA**：至少走一遍会触发矛盾追问的建档流程（如选科组合无招生计划），确认追问轮数上限（3 轮）生效 | QA | — |

**P3 Day 3-4 验收**：建档问诊呈现为连续对话流；专科批场景自动跳过本科限定字段（无 LLM 调用）；选科组合冲突时立即插入 AI 追问气泡而非等到最后统一提示。

---

### P3 Day 5-6：ConversationAgent 升级为 Agent 操作画布 + 方案对比

**目标**：ConversationAgent 从纯 streaming completion 升级为 tool-calling agent，让报告页从静态展示变成 Agent 可操作的画布；新增方案对比能力。本阶段工作量和不确定性最大，**Day 5 上午先做技术 spike**，验证 Kimi k2.6 流式回复 + 工具调用同时开启的稳定性，不确定性高于本 Sprint 其他任务。

| 任务 | 类型 | 参考 |
| --- | --- | --- |
| **技术 Spike（半天）**：验证 LiteLLM → Kimi k2.6 流式 + tool-calling 并存的可行性，若不稳定需评估 fallback（如先非流式判断工具调用，再流式吐文字） | backend | backend-prd Section 10.9、prd-redesign §3.2 技术风险 |
| ConversationAgent 升级为 tool-calling 架构（LangGraph 工具调用范式，Retrieval/Policy Rule Agent 已验证可行） | backend | backend-prd Section 10.9 |
| 定义 UI 操作类工具：`switch_tab` / `highlight_candidates` / `open_compare_view` / `expand_risk_detail`（纯前端状态变更，无需确认） | backend | backend-prd Section 10.9 |
| 定义数据变更类工具：`regenerate_recommendations(patch)`，触发前需用户二次确认 | backend | backend-prd Section 10.9 |
| `POST /api/v1/reports/{id}/refine`：轻量约束只重跑 Recommendation→Risk→Report（复用 evidence_list/rule_results）；重大约束（省份/选科/批次）提示需完整重新生成 | backend | backend-prd Section 5、10.9 |
| Alembic 新增 `reports.version` / `reports.parent_report_id` 字段 | backend | backend-prd Section 6.1 |
| 前端：ConversationAgent 工具调用执行器，UI 操作类工具直接执行并联动画布组件，数据变更类工具先展示确认卡片 | frontend | frontend-prd Section 8.6 |
| 前端：报告页版本切换器（v1/v2...），聊天面板展示重新生成后的变化摘要 | frontend | frontend-prd Section 8.6 |
| 方案对比视图组件（Bottom Sheet/Drawer）：学校/专业/位次差/学费/风险等级 5 维度差异高亮 + AI 取舍建议 | frontend | frontend-prd Section 8.6 |
| **QA**：走查"改预算重新生成"和"对话触发对比视图"两条路径 | QA | — |

**P3 Day 5-6 验收**：Phase 3 DoD 全部打勾；Demo #8/#9/#10 可现场演示。

---

## GitHub 项目管理配置

### Milestones 设置

在 GitHub repo → Issues → Milestones 创建：

| Milestone        | Due Date    | 描述                                            |
| ---------------- | ----------- | ----------------------------------------------- |
| M1：骨架跑通     | Day 3       | 全链路联通，mock 数据可 demo                    |
| M2：核心引擎     | Day 7       | 真实业务逻辑，RAG 检索，LangSmith trace         |
| M3：上线         | Day 10      | Reflection 自检、线上部署、demo 就绪            |
| Phase 2：增强功能 | P2 Day 3   | Chat Panel + Admin Debug 控制台交付              |
| Phase 3：AI 协作者重构 | P3 Day 6 | 协作时间线、建档 Generative UI 化、改约束重新生成 + 方案对比交付 |

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

每个 Issue 标题格式：`[M1/M2/M3/P2] 功能描述`，正文包含：

- 具体任务列表（checkbox）
- 参考 PRD 章节链接
- DoD 条件

### 建议 Issue 拆分粒度

每个 Issue 控制在 **半天到一天** 可完成。每完成一个 Issue 立即 close 并移到 Done。

---

## Phase 2 留存项（P2 Day 4+ 或 Phase 3）

> **已移入 Phase 2 Sprint**：报告问答 Chat Panel（P2 Day 1-2）、Admin Debug 控制台（P2 Day 2-3）。

以下功能不影响技术深度展示，暂不在本 Sprint 内实现：

| 功能                           | 原因                                        | 切入点                                  |
| ------------------------------ | ------------------------------------------- | --------------------------------------- |
| 志愿表文件上传 + OCR           | 与核心技术点无关，需额外文件解析服务        | 引入异步文件处理后实现                  |
| 自托管 BGE embedding（需 GPU） | 只改 LiteLLM config 即可切换，无代码变更    | Railway 支持 GPU 实例后迁移             |
| BM25 + RRF 混合检索            | SQL + 向量检索已满足 MVP                    | 向量检索效果验证后引入 BM25             |
| 黄金评测集 30-50 案例          | 5-10 个够 demo，大批量自动化是 CI 工作      | Phase 2 引入 LangSmith Dataset 自动评测 |
| 多省份数据                     | 窄而深比宽而浅更有价值，1 省做透即可        | 验证河南省数据链路稳定后扩展            |
| Chat LLM Judge 合规层          | 正则层先上，LLM Judge 是增量优化            | Chat 稳定后接入，参考 backend-prd 12.1  |

---

## 技术债追踪（M3 后处理）

| 债项                        | 影响                               | 处理方式                              |
| --------------------------- | ---------------------------------- | ------------------------------------- |
| Mock 数据替换               | 非河南省用户体验差                 | Phase 2 多省份数据接入                |
| Redis LRU 驱逐 checkpoint   | 长时间等待用户输入（如 Profile Agent 多轮追问）可能丢失 State | 生产环境加 PostgreSQL checkpoint 双写 |
| 正则禁词列表维护            | 新的违规表达需人工更新             | Phase 2 建立禁词管理后台              |
| LangSmith 离线 Dataset 评测 | 目前只有 runtime trace，无自动回归 | Phase 2 接入 CI 自动运行评测集        |
| ConversationAgent 流式+tool-calling 稳定性未验证 | Kimi k2.6 没有"流式回复+工具调用并存"的先例场景，若不稳定会影响 Phase 3d 的改约束/UI 操作体验 | P3 Day 5 上午先做技术 spike，验证不通过则 fallback 为"先非流式判断工具调用，再流式吐文字"两阶段方案 |
