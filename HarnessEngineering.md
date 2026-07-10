# HarnessEngineering.md — 问津 Agent v2 重构执行拆解

> 这不是 PRD，是把 `docs/backend-prd-v2.md` / `docs/frontend-prd-v2.md` / `docs/frontend-style.md` / `docs/prd-redesign-ai-collaborator.md` / `docs/wenjin-agent-prototype.html` 描述的"AI 全程协作者"重构，拆成 AI coding agent 可以逐个领取、独立执行、独立验收的模块。业务细节一律不复述，只给坐标：目标、涉及文件、依赖、验收标准出处。

## 0. 怎么用这份文档

1. 挑一个状态为 ⬜/🔄 且依赖已全部 ✅ 的模块（见 §4 执行顺序），把该模块整段喂给 agent。
2. 验收标准列的是 PRD 章节号，不是本文重复的文字——做完对照该章节自检，不要凭本文猜测细节。
3. 完成后按 `CLAUDE.md`「文档同步」表更新对应文档，并回来把这份文件里的模块状态改掉（✅/🔄/⬜）。
4. 模块粒度以"一次可独立提交"为准；一个模块内部要不要再拆子任务，由执行的 agent 自己用 TodoWrite/TaskCreate 管理，本文不下沉到函数级别。

状态图例：✅ 已完成并已提交 · 🔄 进行中（有未提交改动）· ⬜ 未开始

## 1. 现状快照（Wave 1 执行完成后更新，供 agent 判断"从哪接手"，不代表长期事实）

Wave 1（B4 收尾、B5、B7、F3）已全部完成并通过验证（后端 113 项 pytest + 手工浏览器验证建档流程；详见各模块状态）：
- B4：`/reports/{id}/refine` 局部重新生成——审查确认原有未提交改动已完整实现（`create_refine_graph`/`run_refine`/接口/patch 构建），补跑测试验证。
- B5：新增用户侧协作 SSE 事件 `agents_parallel_started/merged`、`self_check_round`、`degraded_notice`；同时修复了一个真实缺口——`GET /agent/runs/{id}/events` 之前没有过滤 `debug:` 前缀事件，会把 Admin 调试事件泄漏给普通用户 SSE，现已修复。
- B7：candidate 新增 `matching_confidence_score`/`historical_ranks`，报告新增 `condition_commentary`（含 version=1 基础版走引导性点评的分支）。
- F3：新增 `lib/profileFieldSchema.ts` + `components/profile/{FieldControl,ClarificationBubble,ProfileChatFlow}.tsx`，替换旧的 6 步固定表单向导（`ProfileStepper.tsx` 已删除），`/profile` 页面改为对话式逐字段收集 + 后端 `/profile/field-check` 矛盾检测。浏览器验证时发现并修复了一个字段切换时数字输入框残留旧值的 bug（`FieldControl` 缺少 `key`）。

顺带修复（不在 Wave 1 模块范围内，但阻塞验证/属于文档同步硬性要求）：
- 测试基础设施：`test_rules.py`/`test_scoring.py` 的 SQLite fixture 对全量 `Base.metadata.create_all` 会因 JSONB 列报错，改为只建所需表；删除了整份测试 v1.1 已移除的人工复核（HITL）功能的 `test_human_review.py`，修正 `test_reflection_agent.py` 里 3 个仍断言 `human_review` 路由的过期用例。
- `backend/docs/02_agent_design.md`：整份重写，移除已删除多个版本的 HITL 章节，补充 `refine_graph`、当前真实的并行实现方式（条件边返回多目标，不是 `Send()` API）、新增 SSE 事件的两层设计说明。

已知但未处理（超出 Wave 1 声明范围，供后续排期）：
- `gender`/`has_physical_limits` 只在建档字段依赖图（`_FIELD_ORDER`）里出现，`StudentProfile` 模型和 `ProfileIn` 都没有对应持久化字段——前端填了也会被后端静默丢弃。体检限制是 CLAUDE.md 里明确的高风险约束，建议单独排一个模块补上模型字段 + 迁移。
- `components/report/RiskOverview.tsx` 在 `overallRisk` 不在 `riskConfig` 已枚举的几个值内时会渲染出 `undefined` 组件类型导致 React 报错（浏览器验证 F3 时通过 demo 报告页面触发观察到，与本次改动无关，未修复）。
- `components/chat/*`、`components/ui/Button.tsx` 等共享组件仍是浅色主题，F1"深色设计系统"只落地了 `globals.css` 基础层和 Admin 拓扑图动效，尚未推广到这些既有组件。

未开始：
- B6 ConversationAgent tool-calling 化
- F2/F4/F5/F6/F7/F8（前端 Generative UI 统一页面及其后续能力）

## 2. 分层地图

```
前端 (Next.js App Router)
  ├─ pages 层        app/*             — 路由与页面组合
  ├─ Generative UI 组件层  components/*  — 对话卡片、结构化控件、报告画布
  ├─ 状态层           lib/store.ts (Zustand) + TanStack Query
  └─ BFF             app/api/backend/* — 鉴权转发、SSE 代理

后端 (FastAPI)
  ├─ API 层           app/api/v1/*      — 同步请求处理
  ├─ Agent 层         app/agent/*       — LangGraph 主链路 + ConversationAgent
  ├─ 确定性引擎层      app/engine/*      — rules/scoring/risk_engine/planner
  └─ 数据层           app/models/* + alembic — ORM + 迁移
```

前后端通过 REST + SSE（`sse:{run_id}` Redis Stream）交互，State schema 见 `backend/app/agent/state.py`。

## 3. 模块清单

### 3.1 后端模块

| ID | 模块 | 状态 | 目标 | 涉及文件 | 依赖 | 验收标准 |
| --- | --- | --- | --- | --- | --- | --- |
| B1 | 数据模型基线 | ✅ | 版本血缘、debug摘要等字段迁移 | `models/report.py`, `models/agent_run.py`, alembic | — | backend-prd-v2 §6 |
| B2 | 匿名会话 | ✅ | 匿名建档 + 登录后绑定 | `api/v1/auth.py` | — | backend-prd-v2 §5.1 |
| B3 | 建档字段依赖图 + Profile Agent 追问 | ✅ | `/profile/field-check`，矛盾检测走规则、追问走 Agent | `api/v1/profile.py`, `agent/nodes/profile_agent.py` | B1 | backend-prd-v2 §5.6, §10.1 |
| B4 | 报告局部重新生成 `/refine` | ✅ | 轻量约束只重跑 Recommendation→Risk→Report，复用 checkpoint 证据 | `agent/graph.py`, `worker.py`, `api/v1/reports.py`, `agent/state.py` | B1 | backend-prd-v2 §5.9, §14.1 对应条目 |
| B5 | 用户侧协作 SSE 事件扩展 | ✅ | 新增 `agents_parallel_started/merged`、`self_check_round`、`degraded_notice`，复用已有 Debug 事件做"技术→友好文案"转译；用户侧端点过滤 `debug:` 前缀 | `agent/graph.py`, `agent/nodes/retrieval_agent.py`, `agent/user_events.py`（新增）, `api/v1/agent.py` | B1 | backend-prd-v2 §5.7, §2.3(prd-redesign) |
| B6 | ConversationAgent tool-calling 升级 | ⬜ | 从纯 streaming 升级为 5 个工具（4 UI 操作类 + 1 数据变更类），先做 Kimi k2.6 流式+工具调用的 spike 验证 | `agent/conversation_agent.py`, `api/v1/chat.py` | B4（`regenerate_recommendations` 要调用 `/refine`） | backend-prd-v2 §5.10, §10.9；**建议先起一个独立 spike 任务验证技术可行性，再落地正式实现** |
| B7 | 报告呈现字段升级 | ✅ | 候选项加 `matching_confidence_score`/`historical_ranks`，报告加 `condition_commentary` | `agent/nodes/recommendation_agent.py`, `agent/nodes/report_agent.py`, `engine/scoring.py`, `api/v1/mock_data.py` | B1 | backend-prd-v2 §6.4 |

### 3.2 前端模块

| ID | 模块 | 状态 | 目标 | 涉及文件 | 依赖 | 验收标准 |
| --- | --- | --- | --- | --- | --- | --- |
| F1 | 深色设计系统 | ✅（基础） | 色彩/字体/间距/圆角落地，Admin 保持浅色不迁移 | `app/globals.css`, `components/ui/*` | — | frontend-style.md, frontend-prd-v2 §3 |
| F2 | 建档+报告统一页面骨架 | ⬜ | `/` 改为左右双栏（对话 + 实时报告面板三态），下线 `/assess`/`/profile`/`/reports/generating`/`/volunteer-check` 独立路由 | `app/page.tsx`, 删除对应旧目录, `app/reports/[id]/page.tsx` | F3（控件渲染需要先有） | frontend-prd-v2 §4.3, §6.1, §6.2 |
| F3 | Generative UI 结构化控件渲染器 | ✅ | 字段 schema → 控件类型映射，前端字段依赖图（配置驱动，零 LLM） | `lib/profileFieldSchema.ts`（新增）, `components/profile/*`（替换 `ProfileStepper.tsx`） | B3 | frontend-prd-v2 §6.1「确定性逻辑与 Agent 边界」表 |
| F4 | 对话内生成过程卡片 | ⬜ | `InlineGenerationCard`：并行分组、自我检查分组、降级提示 | `components/chat/*`（新增） | B5 | frontend-prd-v2 §6.1「对话内生成过程卡片」表 |
| F5 | 实时报告面板三态 + 与报告工作台共享组件 | ⬜ | 空/基础版/偏好更新版；`/` 与 `/reports/[id]` 复用同一组件树 | `components/report/*`, `app/reports/[id]/page.tsx` | B4, F2 | frontend-prd-v2 §6.1「实时报告面板」表, §6.2 |
| F6 | ConversationAgent 前端联调 | ⬜ | 处理 `ui_action`/`refine_confirm_required` SSE 事件、版本切换器 `ReportVersionSwitcher` | `components/chat/ChatPanel.tsx`, `components/report/*`（新增版本切换器） | B6, B4 | frontend-prd-v2 §6.2「报告对话意图处理」表 |
| F7 | 方案对比视图 | ⬜ | `PlanCompareView`：手动勾选 + 对话触发共用一套组件 | `components/report/*`（新增） | B6（对话触发需要 `open_compare_view`；手动入口可先行不必等 B6） | frontend-prd-v2 §6.2「方案对比视图」 |
| F8 | 候选卡片/AI 点评呈现优化 | ⬜ | 展示历史位次、匹配置信分、生成后 AI 点评卡片 | `components/report/CandidateCard.tsx` | B7 | frontend-prd-v2 §6.2「推荐卡片」「生成后 AI 点评卡片」 |

## 4. 建议执行顺序（按依赖分波次，波次内可并行）

| 波次 | 模块 | 说明 |
| --- | --- | --- |
| Wave 1 ✅ | B4（收尾）、B5、B7、F3 | 已完成——均无阻塞依赖，可立即并行；F3 依赖已完成的 B3 |
| Wave 2 | F2、F4、F5 | F2 依赖 F3 产出的控件渲染器；F4 依赖 B5 的新事件；F5 依赖 B4 |
| Wave 3 | B6 | 建议单独起一个 spike 任务验证 Kimi 流式+工具调用可行性，再做正式实现；不阻塞 Wave 1/2 |
| Wave 4 | F6、F7、F8 | F6 依赖 B6+B4+F5；F7 依赖 B6（对话触发）但手动入口部分可提前到 Wave 2 做；F8 依赖 B7 |

F2（下线旧路由、合并页面骨架）改动面最大，建议单独一个 PR，不与其他前端模块混在一起提交，避免难以 review。

## 5. 边界提醒（避免 agent 扩大范围）

- 不做：文件上传/OCR、独立 `/compare` 对比中心、支付订单、人工复核——这些是 Phase 2 或明确不做项，见 prd-redesign-ai-collaborator.md §5 和 backend-prd-v2 §10.1「Phase 2 后端方向」。
- 不做：Admin Debug 控制台改造——保留现状，不因本次重构变更（prd-redesign-ai-collaborator.md §4「明确不做」）。
- 完成任一模块后按 `CLAUDE.md`「文档同步」表检查是否需要同步 `docs/backend-prd-v2.md`/`docs/frontend-prd-v2.md`/`CLAUDE.md` 本身。
