# 问津 Agent 记忆管理重新设计 —— 实施计划

> 目标：把当前「会话级临时消息列表」升级为「分层、可恢复、可复用」的企业级记忆系统。

---

## Changelog

| 版本 | 日期 | 主要变更 |
| ---- | ---------- | -------- |
| v1.0 | 2026-07-22 | 初始化记忆管理重新设计文档 |

---

## 1. 现状诊断（已确认）

| 层级 | 当前实现 | 主要问题 |
|------|---------|---------|
| **对话短期记忆** | `intake_conversations` / `report_conversations`：Redis 热层（7 天 TTL）+ PostgreSQL 冷层，最多存 50 条完整消息；Agent prompt 只取最近 10/16 条 | 无摘要压缩，长会话上下文膨胀；跨会话无法继承；匿名转登录只改 owner_key，不做语义合并 |
| **LangGraph 运行状态** | `graph.compile()` 未配置 checkpointer，state 全在内存；`thread_id` 仅用于 LangSmith trace | Worker 重启/超时即丢失运行进度；未来 HITL、断点续跑无支撑 |
| **用户长期记忆** | 仅 `student_profiles` + `preferences` + 历史 `reports` 表，没有用户级事实/偏好记忆表 | 用户多次来访时 Agent 像“失忆”；ConversationAgent 看不到跨报告的偏好演化 |
| **证据/报告复用** | `/refine` 复用 `parent_report.evidence_json` | 只复用证据，不复用对话意图、用户否定过的候选、过往约束解释 |

---

## 2. 企业级记忆管理参考框架

| 记忆类型 | 典型做法 | 问津对应映射 |
|----------|---------|-------------|
| **工作记忆（Working Memory）** | LangGraph State / 上下文窗口 | `VolunteerPlanState`、`messages` |
| **短期/ episodic 记忆** | 会话历史 + 滚动摘要 + Checkpointer | 对话消息、运行节点快照、版本差异 |
| **长期/语义记忆** | 用户事实/偏好向量库（pgvector）+ 提取-检索机制 | 用户“不接受中外合作”“想留河南”等跨会话事实 |
| **程序性记忆** | 系统提示词、工具定义、合规规则版本化 | `compliance.py`、工具 schema、PRD 规则 |

参考实践：LangGraph PostgresSaver、OpenAI 的 Memory API 分层、mem0/Zep 的 extraction-retrieval 模式。

---

## 3. 方案选项

### 选项 A：工程韧性优先，分阶段推进（推荐）

先解决「运行丢进度」和「对话上下文失控」两大工程风险，再视情况扩展长期记忆。交付节奏与你列的 4 个任务对齐：

1. **确认现状 & 企业调研**（1-2 轮）
   - 输出《问津记忆现状审计表》
   - 输出《企业级 Agent 记忆设计速查》
2. **LangGraph Checkpointer 落地**
   - 引入 `langgraph-checkpoint-postgres`，为 `agent_graph` / `refine_graph` 配置 `PostgresSaver`
   - `thread_id` 真正用于状态恢复；Worker 重启后可继续运行
   - 新增 `checkpoints` 相关表由 LangGraph 自动维护（与 PRD 一致，不走 alembic）
3. **对话记忆优化**
   - 实现滚动摘要：当消息数超过阈值时，把早期消息压缩为 `summary`
   - Prompt 结构改为：`[system] + [summary] + [recent N 条]`
   - 在 `intake_conversations` / `report_conversations` 增加 `summary` 字段；Redis 同步存储
4. **运行状态快照 & 可观测性**
   - 每个节点完成后把关键 state delta 写入 `agent_runs.state_snapshot_json`
   - 支持 Admin Debug 的事件回放从「仅事件」升级为「事件 + 状态快照」
5. **测试**
   - 单元测试：checkpointer 注入、`graph.astream` 中断后恢复、摘要器正确性
   - 集成测试：模拟 Worker 重启后 run 继续、长会话摘要后回答一致性
   - 端到端：通过 `/reports/{id}/chat` 与 `/intake/chat` 验证历史不丢

### 选项 B：完整记忆中台（在 A 基础上扩展）

在选项 A 全部完成后，增加长期语义记忆与跨会话个性化：

1. **用户长期记忆表 `user_memories`**
   - 字段：`id, user_id, category(constraint/preference/fact/goal), content, source_report_id/source_conversation_id, created_at, embedding`
   - 来源：每次 ConversationAgent 对话、每次 `/refine`、每次报告生成后异步提取
2. **记忆提取服务**
   - 轻量 LLM 调用（`profile-agent` 或专用虚拟模型），从消息/约束变更中抽取结构化事实
   - 示例抽取：`{"category":"preference","content":"不接受学费超过 8 万/年的专业","source":"report_123/chat"}`
3. **记忆检索注入**
   - ConversationAgent、IntakeAgent、Profile Agent 在构造 prompt 前，按 `user_id` 做向量检索 Top-K
   - 相关性阈值过滤，避免无关记忆干扰
4. **隐私与合规**
   - 提取时排除 PII（分数、位次、身份证号），仅保留偏好/约束级事实
   - 提供 `DELETE /me/memories/{id}` 与 `DELETE /me/memories` 让用户清空
5. **测试**
   - 抽取准确率评估（准备 20 条样本对话）
   - 检索召回/精确率测试
   - 匿名转登录后记忆归属测试

---

## 4. 推荐执行顺序

建议先按 **选项 A** 落地，原因：
- 风险最高（运行丢进度、上下文爆炸）先解决
- 改动范围可控，不引入新的 LLM 调用链和向量提取成本
- 为选项 B 的语义记忆打好基础（有 checkpointer 才能稳定做提取，有摘要才能控制长期记忆 prompt 长度）

选项 B 作为 **Phase 2** 在 A 验收通过后启动。

---

## 5. 关键文件清单（预计改动）

| 文件 | 改动内容 |
|------|---------|
| `backend/app/agent/graph.py` | 配置 `PostgresSaver` checkpointer |
| `backend/app/worker.py` | 注入 checkpointer；恢复运行逻辑；状态快照写入 |
| `backend/app/agent/conversation_agent.py` | 接入 summary + recent messages 构建 |
| `backend/app/agent/intake_agent.py` | 同上 |
| `backend/app/api/v1/chat.py` | 摘要生成/更新；summary 落库；Redis 同步 |
| `backend/app/api/v1/intake_chat.py` | 同上 |
| `backend/app/models/conversation.py` | 增加 `summary` 字段 |
| `backend/app/models/agent_run.py` | 增加 `state_snapshot_json` 字段 |
| `backend/alembic/versions/` | 新增 conversation/agent_run 字段迁移 |
| `backend/tests/` | 新增 `test_memory.py`、`test_checkpointer.py` 等 |
| `docs/backend-prd-v2.md`、`CLAUDE.md` | 同步记忆设计变更 |

---

## 6. 验收标准

- [ ] Worker 被 `docker compose restart` 后，未完成的 run 能从 checkpoint 继续并正常交付
- [ ] 长对话（>30 轮）的 token 消耗不再线性增长，回答仍能引用早期约束
- [ ] `/intake/chat/history` 与 `/reports/{id}/chat/history` 返回包含 `summary` 的新结构，前端兼容
- [ ] 新增测试覆盖 ≥80% 的记忆相关代码路径
- [ ] 文档（PRD / CLAUDE.md）与代码同步更新

---

## 7. 下一步

等待你选择：
- **选项 A（推荐）**：先落地 Checkpointer + 对话摘要 + 测试
- **选项 B**：在 A 基础上继续建设用户长期语义记忆

确认后即可进入第 1 步「现状审计与企业调研」的详细执行。
