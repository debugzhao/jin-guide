# 问津 Agent 记忆管理重新设计 —— 实施计划

> 目标：把当前「会话级临时消息列表」升级为「分层、可恢复、可复用」的企业级记忆系统。

---

## Changelog

| 版本 | 日期 | 主要变更 |
| ---- | ---------- | -------- |
| v1.0 | 2026-07-22 | 初始化记忆管理重新设计文档 |
| v1.1 | 2026-07-22 | 用 Explore agent 通读代码补充具体文件路径/行号证据；新增企业级调研三方向对比（LangGraph 官方机制、开源记忆框架、大厂消费级产品）；修正方案选项，收敛为"结构化事实用 StudentProfile 覆盖 + 软性偏好用 LangGraph Store"的两级架构 |

---

## 1. 现状诊断（已确认，附代码证据）

### 1.1 对话短期记忆

| 层级 | IntakeAgent（建档前聊天） | ConversationAgent（报告问答） |
|------|---------------------------|-------------------------------|
| Redis 热层 | `intake:history:{owner_key}:{conversation_id}`，TTL 7 天，整段历史序列化为一个 JSON 字符串整体读写（`backend/app/api/v1/intake_chat.py:44,64-65,89-109`） | `chat:history:{report_id}:{user_id}`，TTL 同为 7 天（`backend/app/api/v1/chat.py:35,45-46,71-96`） |
| Postgres 冷层 | `intake_conversations` 表：`id`(会话/thread id)、`owner_key`、`title`、`messages_json`(最多50条)、软删除 `deleted_at`（`backend/app/models/conversation.py:44-77`），多会话模型，`(owner_key, updated_at, id)` 复合索引支撑游标分页 | `report_conversations` 表：`(report_id, user_id)` 唯一一条记录，非多会话模型（`backend/app/models/conversation.py:14-41`） |
| Prompt 截断 | `_MAX_HISTORY_MESSAGES=16`，滑窗截尾，不做摘要（`backend/app/agent/intake_agent.py:32,125-126`） | `_MAX_HISTORY_MESSAGES=10`，同样是滑窗截尾（`backend/app/agent/conversation_agent.py:32`） |
| 存储上限 | 50 条（`_MAX_MESSAGES_STORED=50`，`intake_chat.py:43`） | 50 条（`_MAX_MESSAGES_STORED=50`，`chat.py:34`） |
| 限流 | 30 条/天，按 `owner_key`（`intake_chat.py:42`） | 30 条/天，按 `user_id`（`chat.py:33`） |

**主要问题**：
- **无摘要压缩**，纯"存 50 条、喂 10~16 条"的硬截断，长会话中较早的信息在超出滑窗后对 LLM 完全不可见（哪怕仍在存储范围内）。
- **两套实现完全独立、代码高度重复**：限流函数、Redis 读写函数、DB upsert 函数在 `intake_chat.py` 和 `chat.py` 里几乎逐行相同，却没有抽出共享的 `ConversationStore` 之类的模块——这是重新设计时可以顺手合并的技术债。
- **匿名转登录只改 `owner_key`**（`auth.py::_bind_anonymous_data`），不做任何语义合并；且历史上 `owner_key` 字段一度过窄（36 字符）导致匿名用户（`"anon:" + uuid` = 41 字符）的建档历史写库直接被吞异常，只靠 Redis 7 天 TTL 硬撑，009 号迁移才修复（`backend/alembic/versions/009_intake_conversation_threads.py:14-19` 注释记录了此 bug）。
- 目前"30条/天 + 单条≤200字"的限流客观上掩盖了滑窗截断的问题（单日对话量还撑不爆窗口）；一旦未来放开限流，信息丢失会迅速显性化。

### 1.2 LangGraph 运行状态

- `create_graph()`/`create_refine_graph()` 调用 `graph.compile()` **均未传入 `checkpointer` 参数**（`backend/app/agent/graph.py:252,284`），全仓库搜索 `PostgresSaver|RedisSaver|BaseCheckpointSaver|checkpointer=` 均无匹配——**checkpointer 从未配置过，不是"配置不对"而是完全未启用**。
- `worker.py:304` 传入的 `config={"configurable":{"thread_id": run.thread_id}}` 在无 checkpointer 时是**死参数**，不会触发任何状态查找/恢复。
- `checkpoints`/`checkpoint_blobs`/`checkpoint_writes` 三张表在当前 Postgres schema 中**根本不存在**（alembic 全部迁移文件搜索无相关 `CREATE TABLE`）。
- `/refine` 端点实际复用证据的方式是直接读 **`reports.evidence_json`**（Postgres 落盘字段），不经过任何 checkpoint 查询（`backend/app/api/v1/reports.py`、`worker.py:202-220`）。`reports.py` 里的 `HTTPException(409, "checkpoint_not_found")` 实际只是 `StudentProfile` 判空分支的历史遗留命名，**与"checkpoint 过期"语义完全无关**，容易误导后来者。
- `VolunteerPlanState.messages`（`backend/app/agent/state.py:59`，LangGraph 官方消息累加字段）**没有任何节点真正读写它**，`worker.py` 里恒为 `messages=[]`——是预留但形同虚设的字段。

**主要问题**：Worker/进程重启即丢失运行进度；未来做 HITL、断点续跑没有任何支撑；State 里名义上的"记忆"字段实际未被使用。

### 1.3 用户长期记忆

- `StudentProfile`（`backend/app/models/profile.py:11-41`）+ `Preference` 附属表：字段包括 `province/score/rank/subjects/batch/family_budget/risk_style` 及 `major_prefs/city_prefs/rejected_majors/career_priority`。
- **一次性表单建档，无持续更新通道**：`backend/app/api/v1/profile.py` 只有 `POST`（创建）和 `GET`（读取），**没有 PATCH/PUT 更新端点**。`/refine` 里接收的 `patch`（预算/城市偏好等）只作为一次性传给 Worker 的 run 输入，**从未写回 `student_profiles`/`preferences` 表**——下一次全新建档或新报告仍读取未 patch 的原始行（`backend/app/api/v1/reports.py:275-309,377`）。
- **确认不存在**"聊天中提到的偏好/事实 → 结构化提炼 → 回写长期记忆表"的机制：`intake_agent.py` 工具集只有 3 个只读查询工具 + 1 个纯信号工具（无写入类工具）；`conversation_agent.py` 完全没有 tool-calling；全仓库搜索 `StudentProfile`/`Preference` 写路径，只有表单创建和登录合并两处，无任何从 `messages_json` 抽取信息回写的代码。
- **无跨会话记忆能力**：换一个新 `conversation_id`（IntakeAgent）或新 `report_id`（ConversationAgent），Agent 对用户在其他会话里说过的信息一无所知。侧栏虽能列出历史会话标题，但不会被注入当前会话的 LLM context。

**主要问题**：用户多次来访时 Agent 像"失忆"；ConversationAgent 看不到跨报告的偏好演化；`docs/backend-prd-v2.md` 里描述的"checkpoint 驱动的连续追问/证据复用"设计与代码现状存在明显落差，重新设计时不应把那部分文档当作现状基线。

### 1.4 证据/报告复用

- `/refine` 复用 `parent_report.evidence_json`，只复用证据本身，不复用对话意图、用户否定过的候选、过往约束的解释过程。

---

## 2. 企业级记忆管理参考框架

### 2.1 LangGraph 官方机制（优先参考，因为改造成本最低）

| 组件 | 定位 | 生产实现 | 关键 API |
|---|---|---|---|
| Checkpointer | 单线程(会话)内 state 快照，短期记忆，支撑连续对话/故障恢复/time-travel | `PostgresSaver`/`AsyncPostgresSaver` | 图必须带 `thread_id`：`config={"configurable":{"thread_id":...}}` |
| Store | 跨线程(会话)持久化，长期记忆，自定义 namespace + 可选语义检索 | `PostgresStore`/`AsyncPostgresStore` | `store.put(namespace, key, value)` / `store.search(namespace, query=...)` |

官方生态库 **LangMem** 在 Store 之上提供记忆提取/更新范式，区分：

| 维度 | Profile（单文档覆盖） | Collection（追加式） |
|---|---|---|
| 更新方式 | 更新同一份文档 | 新增/删除/合并独立记录 |
| 适用场景 | 只关心"最新状态"（用户画像） | 需跨多次交互无损追踪知识 |
| 检索 | key 直查，快 | 需语义相似度+重要性加权 |

写入时机分 hot path（同步实时）和 background（异步，会话结束后处理，`ReflectionExecutor` 支持去抖）两条路径，官方倾向复杂反思类记忆走异步——与我们 `IntakeAgent` 现有的"`done` 事件后异步升级标题"模式天然契合。

来源：[LangGraph Persistence](https://docs.langchain.com/oss/python/langgraph/persistence) · [LangChain Memory 概念](https://docs.langchain.com/oss/python/concepts/memory) · [LangMem 概念指南](https://github.com/langchain-ai/langmem/blob/main/docs/docs/concepts/conceptual_guide.md)

### 2.2 开源长期记忆框架对比

| 维度 | Mem0 | Zep (Graphiti) | Letta (MemGPT) |
|---|---|---|---|
| 记忆分类 | User/Session/Agent + Factual/Episodic/Semantic | Episode→Entity/Fact→Community 三层 | Core/Archival/Recall 三层 |
| 提取时机 | 调用时同步过一次 LLM | 提交后异步 pipeline | Agent 推理循环里主动调工具写入 |
| 存储结构 | 向量库(Qdrant/pgvector) | Neo4j/FalkorDB 图数据库 | PostgreSQL + pgvector |
| 集成成本 | **低**：`pip install mem0ai`，可复用现有 pgvector+LiteLLM | **高**：自托管版已弃用(2025-04)，需付费云或自建图数据库 | **中高**：需独立部署 Letta Server |

三者哲学不同：Mem0/Zep 是"外部管道确定性抽取"，Letta 是"Agent 自主决定记什么"。Zep 的独特价值是双时态模型（`valid_at`/`invalid_at`，旧事实不删除只标记失效），对"考生选科/位次随时间调整"这类场景更严谨，但运维成本对我们现有 Postgres+Redis 技术栈是额外负担。

来源：[Mem0 Docs](https://docs.mem0.ai/core-concepts/memory-types) · [Zep 论文](https://arxiv.org/abs/2501.13956) · [MemGPT 论文](https://arxiv.org/abs/2310.08560)

### 2.3 大厂消费级产品记忆设计理念

| 维度 | ChatGPT Memory | Claude Memory |
|---|---|---|
| 机制 | Saved Memories（显式）+ Reference chat history（全历史检索） | 单一 memory summary，按 Project 强隔离 |
| 用户管理 | 设置页查看/单条删除/一键清空；"memory sources"面板显示引用来源 | Settings 查看摘要全文；对话中直接说"忘记/更新"编辑；Pause vs Reset |
| 隐私默认 | Opt-in，Temporary Chat 不建记忆 | Opt-in，Incognito 聊天不写入 |

共识：**记忆可见、可编辑/删除、可临时关闭**三件套信任设计；不主动记录敏感信息（如健康）除非用户明确要求。这对教育决策这种高风险场景（避免记错选科/身体条件导致报告出错）尤其值得借鉴。

来源：[OpenAI Memory FAQ](https://help.openai.com/en/articles/8590148-memory-faq) · [Claude 官方博客](https://claude.com/blog/memory)

---

## 3. 方案选项

### 选项 A：工程韧性优先，分阶段推进（推荐，先做）

先解决「运行丢进度」和「对话上下文失控」两大工程风险：

1. **LangGraph Checkpointer 落地**
   - 引入 `langgraph-checkpoint-postgres`，为 `agent_graph`/`refine_graph` 配置 `PostgresSaver`
   - `thread_id` 真正用于状态恢复；Worker 重启后可继续运行
   - `checkpoints` 相关表由 LangGraph 自动维护（不走 alembic，与 `CLAUDE.md` 现有约定一致）
2. **对话记忆优化**
   - 实现滚动摘要：消息数超过阈值时，把早期消息压缩为 `summary`
   - Prompt 结构改为：`[system] + [summary] + [recent N 条]`
   - `intake_conversations`/`report_conversations` 增加 `summary` 字段；Redis 同步存储
   - 顺手合并 `intake_chat.py`/`chat.py` 里重复的限流/Redis读写/DB upsert 逻辑为共享模块（技术债清理，非新增功能）
3. **运行状态快照 & 可观测性**
   - 关键 state delta 写入 `agent_runs.debug_summary_json`（复用现有字段，不新增列）
   - Admin Debug 的事件回放从「仅事件」升级为「事件 + 状态快照」

### 选项 B：跨会话长期记忆（在 A 基础上扩展）

调研结论收敛为**两级记忆架构**，而非另起一套独立记忆库：

| 记忆类型 | 承载方式 | 更新方式 |
|---|---|---|
| **结构化事实**（有明确字段语义，如省份/分数/选科/预算） | 直接用 `StudentProfile`/`Preference` 表覆盖式更新 | 补充 `PATCH /profile/{id}` 端点，不引入 LLM 冲突判定（唯一值语义，业界共识不需要 Mem0 式 ADD/UPDATE/DELETE 这类重机制） |
| **软性偏好/事实**（无对应字段，如"更看重稳定就业""历史问过的院校"） | 引入 LangGraph `PostgresStore`，namespace `(owner_key, "preferences")` / `(owner_key, "facts")` | Profile 型（覆盖式）用 `store.put`；Collection 型（追加式）用 LangMem 的 `create_memory_store_manager` + trustcall |

1. **不新建独立 `user_memories` 表**：让 `Store` 的持久化落在 Postgres，通过 `owner_key`/`user_id` 与 `StudentProfile` 关联，避免记忆库和业务表割裂成两套系统。
2. **提取时机**：复用 `IntakeAgent` 现有"`done` 事件后 `BackgroundTasks` 异步"模式，会话结束后异步调 LLM 提取候选记忆写入 Store，不拖慢主链路流式响应延迟。
3. **暂不引入 Mem0/Zep/Letta 作为独立组件**：当前场景（结构化程度高、单租户、无需多 Agent 共享记忆）用 LangGraph 原生 Store + LangMem 已够用，改造成本最低。若未来出现"跨学生相似决策路径的多跳推理"需求，再评估 Mem0 的 Graph Memory 变体。
4. **记忆管理入口**：借鉴 ChatGPT/Claude 的信任设计，在建档页/报告页加一个轻量入口，展示当前存的 profile/facts 摘要，允许用户手动纠正或清空。
5. **隐私与合规**：提取时排除 PII（分数、位次、身份证号），仅保留偏好/约束级事实；提供清空/删除接口。

**待确认事项**（信息缺口，若选择引入 Mem0 需单独核实）：Mem0 是否支持任意 OpenAI 兼容 `base_url`（即能否指向现有 LiteLLM Proxy）。

---

## 4. 推荐执行顺序

建议先按 **选项 A** 落地，原因：
- 风险最高（运行丢进度、上下文爆炸）先解决
- 改动范围可控，不引入新的 LLM 调用链和向量提取成本
- 为选项 B 打好基础（有 checkpointer 才能稳定做提取，有摘要才能控制长期记忆 prompt 长度）

选项 B 作为 **Phase 2** 在 A 验收通过后启动，且 B 内部结构化事实（StudentProfile PATCH）改动小、可独立先行，软性偏好（LangGraph Store）改动大，可再拆一个子阶段。

---

## 5. 关键文件清单（预计改动）

| 文件 | 改动内容 |
|------|---------|
| `backend/app/agent/graph.py` | 配置 `PostgresSaver` checkpointer |
| `backend/app/worker.py` | 注入 checkpointer；恢复运行逻辑；状态快照写入 |
| `backend/app/agent/conversation_agent.py` | 接入 summary + recent messages 构建 |
| `backend/app/agent/intake_agent.py` | 同上 |
| `backend/app/api/v1/chat.py` | 摘要生成/更新；summary 落库；Redis 同步；与 intake_chat.py 共享逻辑抽取 |
| `backend/app/api/v1/intake_chat.py` | 同上 |
| `backend/app/models/conversation.py` | 增加 `summary` 字段 |
| `backend/app/api/v1/profile.py` | 新增 `PATCH /profile/{id}` 端点（选项 B） |
| `backend/app/agent/state.py` | 评估 `messages` 字段是否启用或移除（当前形同虚设） |
| `backend/alembic/versions/` | 新增 conversation `summary` 字段迁移 |
| `backend/tests/` | 新增 `test_memory.py`、`test_checkpointer.py` 等 |
| `docs/backend-prd-v2.md`、`CLAUDE.md` | 同步记忆设计变更，修正与代码不符的 checkpoint/tool-calling 描述 |

---

## 6. 验收标准

- [ ] Worker 被 `docker compose restart` 后，未完成的 run 能从 checkpoint 继续并正常交付
- [ ] 长对话（>30 轮）的 token 消耗不再线性增长，回答仍能引用早期约束
- [ ] `/intake/chat/history` 与 `/reports/{id}/chat/history` 返回包含 `summary` 的新结构，前端兼容
- [ ] （选项 B）用户在会话 A 提到的偏好，能在会话 B 里被 Agent 引用
- [ ] 新增测试覆盖 ≥80% 的记忆相关代码路径
- [ ] 文档（PRD / CLAUDE.md）与代码同步更新，且不再残留与现状不符的 checkpoint/tool-calling 描述

---

## 7. 下一步

现状梳理与企业级调研已完成（本文档 §1、§2）。等待你选择：
- **选项 A（推荐）**：先落地 Checkpointer + 对话摘要 + 测试
- **选项 B**：在 A 基础上继续建设结构化事实（StudentProfile PATCH）+ 软性偏好（LangGraph Store）

确认后进入详细实施计划（Plan Mode）与测试用例设计。
