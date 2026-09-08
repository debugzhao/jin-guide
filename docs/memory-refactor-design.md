# 记忆模块重构设计方案：收敛读写边界 + 长期记忆治理

> 技术/架构视角。本文范围只覆盖两项：**收敛读写边界（Memory Facade）** 与
> **长期记忆治理（激活已存在的治理元数据字段 + 状态机 + 用户查看/修改/删除）**。
> Context Builder（P3）、执行恢复（Checkpoint）、RAG 不在本次范围（其现状见
> `memory-architecture.md`）。
>
> 本文的"现状"部分均基于代码核实（2026-09 检查 `conversation_store.py` /
> `chat.py` / `intake_chat.py` / `models/profile.py` / `api/v1/profile.py` /
> `app/context/*`），不是从旧的架构评审文档推断。

---

## 0. 结论先行

两项任务里，"治理元数据"的**存储面已经完成**（迁移 `017` 已给 `StudentProfile` /
`Preference` 加上全套治理字段），缺口在**读写逻辑没接通、没有状态机流转、没有
查看/修改/删除入口**；"Memory Facade"**已经起步**（`conversation_store.py` 已
收敛身份解析、限流 key、Redis/DB 原子写、摘要原语），但**边界没收干净**——
`chat.py` 自留 `_db_owner_filter`、两个聊天端点各自手抄"查父行→回源→读摘要"
样板、`Preference` 读写完全绕过 Facade。

因此本文的重点是：

1. **激活已有字段**：把一套只有字段的状态机，补成"跑得起来的状态机 + 用户
   可见的治理入口"；
2. **扩展并收紧 Facade**：把 Facade 从"对话域"扩展到"用户记忆域"，同时消掉
   接口层残留的身份/样板重复。

现有基础设施（State、Redis/PostgreSQL、Profile、RAG、`app/context`）全部保留，
这是一次"分层收敛式重构"，不推倒重来。

---

## 1. 现状校准（与 `memory-architecture.md` 的差异）

| 事实 | 真实状态（已核实） | 说明 |
|---|---|---|
| 治理元数据字段 | ✅ 已存在 | 迁移 `017_preference_provenance_fields` 已加 `source_type / confidence / status / last_confirmed_at / source_message_id / superseded_by / superseded_at`，`_ProvenanceMixin` 已声明 |
| Memory Facade | ⚠️ 已有基础 | `conversation_store.py` 已收敛身份解析、限流 key、Redis Lua 原子写、DB 乐观锁、摘要 CAS 原语 |
| 统一 Context Builder | ⚠️ 已部分落地 | `app/context/`（`types.py`/`assembler.py`/`budget.py`/`config.py`/`trimming.py`/`manifest.py`）已运行，非"一行没落地" |
| 状态机 | ❌ 未接通 | 字段在、但唯一写入路径仍是 `POST /profile` 一次性表单；无 proposed/rejected/superseded 流转；无查看/修改/删除接口 |

> 上述"已落地/部分落地"与 `memory-architecture.md` 的旧描述不一致，已同步修正
> 该文档（见本次同批更新）。

---

## 2. 第一部分：收敛读写边界（Memory Facade）

### 2.1 设计边界（红线）

Facade 职责**只做"读写的统一入口 + 横切机制"**，不做业务编排、不做 Context
组装（那是 `app/context` 的职责）、不碰 LLM。保持"四个记忆域独立"原则，Facade
是它们之上的一层**薄入口**，不建大而全的 `MemoryManager`。

```
API 层 (chat / intake_chat / profile)
        │
        ▼
┌──────────────────────────────────────────────┐
│  MemoryFacade（统一入口，薄）                 │
│  · 身份作用域解析（owner/thread/tenant）       │
│  · 会话域委托 conversation_store（Redis+PG）  │
│  · 用户记忆域委托 user_memory_service         │
│  · 横切：限流 / 日志 / 来源上下文             │
└──────────────────────────────────────────────┘
   │              │              │
   ▼              ▼              ▼
Conversation   UserMemory    Knowledge(RAG)
(store 已有)   (profile)      (不在本次范围)
```

### 2.2 现状问题（逐条对应）

| # | 问题 | 位置 | 后果 |
|---|---|---|---|
| 1 | 身份过滤条件两套实现 | `chat.py::_db_owner_filter` 与 `intake_chat.py::_get_owned_conversation` 各写一遍 | 过滤口径可能再次漂移（P0 想根治的病复发风险） |
| 2 | "查父行→回源→读摘要"样板复制两份 | `chat.py` 与 `intake_chat.py` 各写一遍几乎相同的 `select(Report/IntakeConversation) → hydrate_history_from_db → load_summary` | 新增第 3 个会话型 Agent 还得抄第三遍 |
| 3 | Preference 读写绕过 Facade | `api/v1/profile.py` 直接裸操作 `Preference`/`StudentProfile` ORM | 治理字段（status/superseded）无法在统一入口强制约束 |
| 4 | Redis 连接生命周期散落 | `conversation_store.py` 每个函数内部 `aioredis.from_url(...).aclose()` | 简单可靠，但不便于后续加统一审计/连接池 |

### 2.3 设计方案

#### A. 身份作用域收敛为单一契约

建立统一的 `MemoryScope`，把"这段记忆归谁"收敛成三个正交维度，取代字符串拼凑：

| 维度 | 来源 | 语义 |
|---|---|---|
| `owner` | 登录 `user.id` 或 `anon:{anonymous_id}` | 记忆归属的人（**权威隔离边界**） |
| `thread` | 会话/报告 id | 对话连续性的容器 |
| `tenant` | 预留，当前恒为默认 | 未来多租户隔离 |

关键约束（延续 `conversation_store.py` 既有正确判断）：**`thread_id` 只承载执行/
会话维度，绝不允许参与归属判断**；`owner_key` 是唯一隔离依据。

Facade 对外只暴露 `scope_of(identity) -> MemoryScope`。`_db_owner_filter` 和
`_get_owned_conversation` 都改为消费这同一个 scope，两处手写过滤消失。

#### B. 会话快照聚合原语（消灭样板）

把 `chat.py` 里"加载历史 + 加载摘要"的组合流程上提为 Facade 的一个会话快照
原语（概念名 `load_session_snapshot`）：

- 输入：`scope + parent_kind + report/conversation id`；
- 输出：`{history, history_source, summary_json, summary_meta, summary_load_status}`。

`chat.py` 与 `intake_chat.py` 只消费该结果，不再各自拼查询。这是 P0 已经成功过
一次的套路（`hydrate_history_from_db` 把四份回源复制收敛成一份）的继续推进。

#### C. 用户记忆域纳入 Facade

新增 `user_memory_service`（与 `conversation_store` 平级，仍属 Facade 之下），
**持有状态机与 supersede 规则的唯一实现权**：

- `create / confirm / reject / supersede / delete` 记忆条目只经它暴露的口子；
- `status` 合法流转、`superseded_by` 链维护、`last_confirmed_at` 刷新全部在
  service 内收敛，调用方无法写错状态。

### 2.4 验收标准（收敛边界）

| 检查项 | 标准 |
|---|---|
| 身份过滤实现 | 全仓仅 Facade 一处持有 owner 过滤逻辑（`grep _db_owner_filter/_get_owned_conversation` 结果唯一） |
| 会话快照聚合 | `chat.py`/`intake_chat.py` 不再含 `select(ReportConversation)`/`select(IntakeConversation)` 样板 |
| Preference 写入 | `profile.py` 之外无任何裸 `Preference(...)` 构造 |
| 行为回归 | 复用 §7.1 基线（会话隔离/用户隔离/Redis 降级/删除不复活）全绿，无行为变化 |

---

## 3. 第二部分：长期记忆治理（激活已存在的元数据字段）

### 3.1 现状：字段在、流程空

`_ProvenanceMixin` 已声明全套治理字段，但只有两点在真正赋值：

| 字段 | 现状 |
|---|---|
| `source_type` | 默认 `user_explicit`，**尚无 `model_inferred` 写入路径** |
| `status` | 默认 `confirmed`，**无 proposed/rejected/superseded 流转** |
| `last_confirmed_at` | 仅 `create_profile` 赋值 now |
| `source_message_id` | 恒 NULL，无对话来源锚点 |
| `superseded_by/at` | 恒 NULL，无变更链 |

唯一写入路径仍是 `POST /profile` 一次性表单；无 PATCH/PUT、无查看/管理列表、
无删除接口。所以"补治理元数据"本质是：**把只有字段的状态机，补成跑得起来的
状态机 + 用户可见的治理入口**。

### 3.2 状态机设计

```
                 ┌──────────→ confirmed ──────supersede─────→ superseded
                 │             (可用，进规则)                  (历史留档)
proposed ────────┤ 确认(显式/隐式)
 (仅展示候选)     │
   │             └──────────→ rejected（丢弃/留档，不进规则）
   │ 从对话提取
   └─ proposed 绝对不进入规则引擎
```

**核心不变量（硬红线）**：

1. **只有 `confirmed` 态能投影进规则引擎/推荐评分**；`proposed` 只作"待确认"
   卡片，`superseded`/`rejected` 永不影响硬规则。
2. **变更 = supersede，不覆盖**：旧值标 `superseded` + 记 `superseded_by/at`，
   新值成 `confirmed`，形成"预算 5万→8万"的可追溯链。
3. **`model_inferred` 必须经确认才转 `confirmed`**，无"AI 推断即采信"旁路。

### 3.3 治理入口（用户可查看/修改/删除）

补齐当前缺失的三个能力面：

| 能力 | 接口契约（概念） | 要点 |
|---|---|---|
| 查看 | `list_memories(scope)` | 按"当前有效(confirmed) + 历史(superseded/rejected)"分层返回，每一行带来源/置信度/时间/是否推断 |
| 修改 | `update_memory(...)` | 改值走 supersede 生成新 confirmed，不原地改旧行 |
| 删除 | `delete_memory(...)` | 物理删除 + **四路径级联检查**（见 3.5） |

### 3.4 提取与确认（只做"方案 B"，不接 AI 无确认采信）

遵循 `memory-architecture.md` §六 P4 已论证结论：**先做"显式表达 + 显式确认"
最小闭环，暂不接"AI 自由推断直接进规则"**：

```
对话中明确表达("我预算 8 万")
      │ 异步节流提取（复用 P2 摘要的 BackgroundTasks 模式）
      ▼
proposed 候选 ──前端确认卡片──▶ 用户确认 ──▶ confirmed ──投影──▶ Preference(规则可读)
```

- `source_type` 仍标 `user_explicit`（是用户说的），但 `status` 先落 `proposed`，
  确认后才 `confirmed`。
- 提取失败不阻断对话（best-effort，与摘要同可靠性级别）。

### 3.5 验收标准

| 能力 | 标准 |
|---|---|
| proposed 隔离 | 任何路径下 `proposed` 不得进入规则引擎（单测硬门禁） |
| supersede 链 | 预算 5万→8万后能查到完整链"谁/何时/从什么到什么" |
| 删除闭环 | 删除后四路径均不可召回：①可见列表 ②后续 Context 注入 ③规则引擎输入 ④对话摘要回填 |
| 提取准确率 | 先跑人工标注基线再定阈值，不凭空承诺（沿用 §6 P4 口径） |

---

## 4. 实施顺序

```
阶段1（存储面已就绪，跳过建表）
   └→ 激活状态机 + 补查看/修改/删除接口 + user_memory_service 收敛 Preference 写入

阶段2（Facade 收敛，纯重构、无行为变化）
   └→ MemoryScope 统一身份 → 会话快照原语消灭样板 → _db_owner_filter 合并

阶段3（提取闭环，风险最高，放最后）
   └→ 对话→proposed 提取 → 前端确认 → confirmed 投影（先小流量灰度验证确认率）
```

**顺序理由**：治理元数据字段已存在，先让它"跑起来"成本最低、收益最直接
（立刻能验证 supersede/删除闭环）；Facade 收敛是纯重构、无行为变化、可独立
验收；提取闭环依赖前两者稳定，风险最高放最后——与"正确性 → 摘要 → Context →
长期偏好"的总体节奏一致。

---

## 5. 关联说明

- **与 P2 对话摘要不重复**：摘要是"对话层短期上下文压缩"（随会话生命周期），
  这里做的是"跨会话持久化结构化事实"（随账号生命周期），摘要里的
  `confirmed_facts` 可作为提取逻辑的候选来源，两者是上下游关系。
- **与 Context Builder 不重复**：Facade 负责"记忆的读写"，
  `app/context` 负责"记忆的组装进 Prompt"，Facade 是 `app/context` 的上游
  数据提供方，各自职责不变。