# 核心业务流程设计

> **v1.1**：已移除人工复核等待流程；鉴权改为 `POST /auth/send-code` + `/auth/register` + `/auth/login`（邮箱+密码，Resend 验证码）。

---

## 1. 核心业务全景

问津 Agent 的主流程是一个**高风险决策辅助系统**，核心约束是：

> 不能给出"保证录取"的结论，只能给出"基于数据的辅助决策"，并在 UI 明确展示高风险说明。

这个约束贯穿所有业务流程设计。

---

## 2. 主流程：从建档到报告交付

### 2.1 整体业务流程

```mermaid
flowchart TD
    START(["用户访问问津 Agent"])
    --> LOGIN["注册/登录\nPOST /auth/send-code + /register\n或 POST /auth/login"]
    LOGIN --> CHECK_DATA["用户填写省份后\n立即调 GET /data/availability\n检查该省份数据是否就绪"]
    CHECK_DATA -- "数据未就绪" --> WARN["提示'当前省份数据尚未就绪'\n用户可继续填档案，生成时会再次校验"]
    CHECK_DATA -- "就绪" --> PROFILE_WIZARD

    WARN --> PROFILE_WIZARD

    PROFILE_WIZARD["建档向导 6 步\n① 省份/批次/分数/位次\n② 选科\n③ 专业偏好 + 禁忌\n④ 城市偏好\n⑤ 家庭预算\n⑥ 风险偏好\nPOST /profile + 自动保存草稿"]

    PROFILE_WIZARD --> RISK_PREVIEW["快速测算\nPOST /risk/preview\n同步 < 2s\n返回风险画像卡片\n（初步判断，不需要完整建档）"]

    RISK_PREVIEW --> GENERATE["点击'生成完整方案'\nPOST /reports/generate\n→ 立即返回 run_id"]

    GENERATE --> SSE["前端建立 SSE 连接\nGET /agent/runs/{id}/events\n实时展示进度"]

    SSE --> AGENT_RUNNING["Agent 执行中\n各节点依次推送 SSE 事件\nnode_started / rule_checked / candidates_ready"]

    AGENT_RUNNING --> REPORT_READY(["报告就绪\nSSE completed 事件\n前端跳转报告详情页"])
```
> v1.1 已移除 HITL 分支（原 `human_interrupt` / 复核等待 / `resume`）。

### 2.2 建档完整度与追问策略

```mermaid
flowchart LR
    PROFILE_INPUT["用户提交档案"]
    --> COMPLETENESS["计算 completeness_score\n必填字段（分 + 省份）= 30%\n位次 = 20%\n选科 = 20%\n偏好信息 = 30%"]

    COMPLETENESS --> SCORE{"completeness_score"}
    SCORE -- "< 60%\n必填缺失" --> BLOCK["阻断\n必须补充分数和省份\n才能继续生成"]
    SCORE -- "60-80%\n缺位次或偏好" --> PROFILE_AGENT["Profile Agent 追问\n最多 3 轮\n超出后以当前档案继续\n缺失字段写入 data_warnings"]
    SCORE -- "> 80%" --> PROCEED["直接进入 Data Resolver"]

    PROFILE_AGENT --> PROCEED
    BLOCK -.->|"用户补充后重试"| PROFILE_INPUT
```

**为什么位次比分数更重要**：

不同省份的录取是按位次而不是分数（新高考省份尤其如此）。分数相同在河南可能是 3 万名，在宁夏可能是 1 千名，录取结果完全不同。

但很多用户只知道分数，不知道位次。这时 Profile Agent 会追问，并且在 `province_thresholds` 表里用"每 10 分 ≈ 1000 位次"的估算规则提供粗略换算，在报告中标注"位次估算，仅供参考"。

**追问轮次上限的设计**：无限追问会让用户感到烦躁（想象一个不停问问题的客服），设 3 轮上限强制继续，缺失字段以 `data_warnings` 标注，在报告中显示"以下推荐基于不完整信息"。

---

## 3. 报告生成流程（Agent 内部）

### 3.1 候选生成与冲稳保分层

```mermaid
flowchart TD
    INPUT["输入\n位次 rank=32680\n省份=河南 批次=本科批\n选科=[物理,化学]"]

    INPUT --> QUERY_PLANS["查询招生计划\nSELECT * FROM admission_plans\nWHERE province='河南' AND year=2026\nAND batch='本科批'\nAND subjects ⊇ ['物理','化学']"]

    QUERY_PLANS --> RULE_FILTER["Rule Engine 硬过滤\n体检限制命中 → 移除\n单科要求不满足 → 移除\n禁忌专业命中 → 标红\n学费超预算 → 降权"]

    RULE_FILTER --> SCORE_CALC["4 维评分算法\n① 录取安全性 40%\n   rank_gap = min_rank_avg - student_rank\n   stability = 1 - stddev/mean (近3年)\n② 专业适配 25%\n   偏好命中 + 选科满足度 + 禁忌惩罚\n③ 城市家庭 20%\n   城市偏好 + 学费预算适配\n④ 成本风险 15%\n   high风险-20 / medium-10 / low-5"]

    SCORE_CALC --> TIER["冲稳保分层\n位次差 > 5000 → high_rush（高冲）\n位次差 1000-5000 → rush（冲）\n位次差 ±1000 → target（稳）\n位次差 < -2000 → safe（保）\n（阈值来自 province_thresholds 表）"]

    TIER --> THREE_PLANS["生成三套方案\n保守型: 0/20/40/40 (high_rush/rush/target/safe)\n均衡型: 5/30/40/25\n进取型: 15/35/35/15"]

    THREE_PLANS --> SAFE_CHECK{"保底 safe 档 ≥ 10 所？"}
    SAFE_CHECK -- "否" --> HARD_BLOCK(["硬阻断\n报告无法生成\nSSE error 事件\n提示'保底不足，请检查分数或放宽偏好'"])
    SAFE_CHECK -- "是" --> DELIVER["候选集写入 State\n进入 Risk Agent"]
```

**保底硬下限 10 所的设计依据**：

河南省最多填 96 个志愿，保守估计一套方案里 safe 档应该占 40%（约 38 所）。但考虑到用户可能偏好集中、省份数据部分缺失等情况，10 所是能保证"不因为没有保底学校而全军覆没"的最低阈值。

低于这个数字说明用户的条件（选科、偏好、预算）过于限制，推荐系统无法生成有意义的保底方案，与其生成一个名义上"有保底"实则风险极高的报告，不如直接阻断让用户调整条件。

### 3.2 志愿表风险体检

```mermaid
flowchart LR
    VOL_TABLE["用户提交志愿表\n手动录入或从报告导入"]
    --> RISK_ENGINE["Risk Engine 5 类检查（全部确定性，不经 LLM）"]

    subgraph CHECKS["风险体检项"]
        R1["① 保底充足性\nsafe 档数量 ≥ 10\n总数中 safe 占比 ≥ 15%"]
        R2["② 梯度合理性\n相邻志愿位次差是否过小\n差距 < 500 名 → 扎堆风险"]
        R3["③ 热门专业扎堆\n计算机/临床医学/法学\n占比 > 60% 提示竞争风险"]
        R4["④ 禁忌专业命中\n专业组内含用户填写的禁忌专业\n高风险，强烈建议复核"]
        R5["⑤ 选科冲突\n用户选科不满足专业要求\n必须标红，逻辑上无法录取"]
    end

    RISK_ENGINE --> CHECKS
    CHECKS --> RISK_SUMMARY["汇总风险项\n{risk_type, severity, message, targets}"]
    RISK_SUMMARY --> OVERALL{"overall_risk_level"}
    OVERALL -- "high" --> RECOMMEND_REVIEW["强烈建议人工复核\n展示橙色提示条"]
    OVERALL -- "medium" --> SHOW_RISKS["展示风险列表\n用户自行判断"]
    OVERALL -- "low" --> CLEAR(["通过体检\n志愿表风险较低"])
```

---

## 4. 数据管道（ETL）流程

```mermaid
flowchart TD
    SRC["数据来源\n省考试院官网 PDF\nExcel 招生计划\n各大学招生章程"]

    SRC --> FETCH["数据采集\n① 爬虫：定时抓取官网更新\n② 人工上传：运营团队上传文件\n③ 写 documents 表 status=raw"]

    FETCH --> PARSE["异步解析（后台任务）\nPDF → OCR → 结构化表格\n招生计划 → admission_plans\n投档线 → admission_scores（含 batch 字段）\n一分一段 → rank_segments\n章程 → rule_requirements"]

    PARSE --> CHUNK["向量化\n非结构化文本 → 按类型切分 chunk\n招生章程: 400 token / 80 重叠\n专业介绍: 300 token / 60 重叠\n就业报告: 500 token / 100 重叠\nbatch embed → pgvector"]

    CHUNK --> SAMPLE["抽样校验\n随机抽取 5% 行\n与原始文件对比关键字段\n录入 dataset_version"]

    SAMPLE --> HUMAN_VERIFY["数据运营人工确认\n关键字段：投档线、计划数\n签字确认无误"]

    HUMAN_VERIFY --> PUBLISH["发布\ndocuments.status = published\ndataset_version 绑定\nDataService 缓存失效\n/data/availability 返回 available=true"]

    PUBLISH --> DEPRECATE["旧年度数据\ndeprecated\n现有报告保留引用\n新报告不允许使用"]

    style HUMAN_VERIFY fill:#fff3e0,stroke:#FF9800
    style PUBLISH fill:#e8f5e9,stroke:#4CAF50
```

**关键设计：为什么数据发布要人工确认**

系统的核心信任度建立在数据准确性上。如果招生计划的学校代码抄错了，或者投档线的行数据偏移了，系统会推荐完全错误的学校——而用户可能就此填报了。

自动化解析（尤其是 PDF OCR）有约 0.5-2% 的字段错误率。人工抽样校验 5% 行，可以发现系统性错误（比如某列全部偏移）。发现错误时整批数据回退到 `parsed` 状态，修复后重新校验发布。

---

## 5. 错误处理与降级策略

### 5.1 错误分层

```
                      ┌── 硬阻断 ──────────────────────────┐
                      │  数据未发布                          │
                      │  Rule Engine 不可用                 │
                      │  候选生成为空                        │
                      │  保底 < 10 所                       │
                      │  后果：立即终止 run，SSE error 事件   │
                      └─────────────────────────────────────┘

                      ┌── 可降级 ───────────────────────────┐
                      │  向量检索失败 → SQL 检索接管          │
                      │  Cohere Rerank 不可用 → 跳过精排     │
                      │  后果：继续执行，报告中标注"数据受限"  │
                      └─────────────────────────────────────┘

                      ┌── 可重试（瞬时故障）────────────────┐
                      │  LLM API 429 / 网络超时              │
                      │  重试策略：3次，1s→2s→4s 指数退避    │
                      │  超限后：阻断，run 标记 failed        │
                      └─────────────────────────────────────┘

                      ┌── 静默记录 ──────────────────────────┐
                      │  非关键 metadata 缺失                 │
                      │  次要字段解析失败                     │
                      │  后果：写 warning 日志，不传播给用户   │
                      └─────────────────────────────────────┘
```

**硬阻断的设计原则**：

高风险场景宁可明确失败，不能静默降级。想象如果 Rule Engine 故障了，系统"降级"为跳过规则校验，那选科不满足的学校也会被推荐出来。用户不知道规则没检查，报告看起来正常，但填报了不满足选科要求的专业就直接被退档。

所以 Rule Engine、数据发布状态、保底数量——这些是"底线约束"，失败只能阻断，不能降级。

### 5.2 降级的 State 传播

```python
# Retrieval Agent 降级后
if retrieval_failed:
    state["degraded_agents"].append("retrieval_agent")
    state["data_warnings"].append("向量检索不可用，已降级到结构化数据检索")

# Report Agent 生成报告时检查降级状态
if "retrieval_agent" in state["degraded_agents"]:
    report_template.add_disclaimer(
        "由于检索服务临时不可用，本报告中部分非结构化内容（专业介绍、就业解读）"
        "基于有限数据，仅供参考。"
    )
```

降级信息必须透传到报告，让用户知道"这部分内容的数据是降级的"，而不是看起来完整实则基于不完整数据的报告。

---

## 6. 可观测性设计

### 6.1 结构化日志

每条日志包含完整的追踪字段：

```json
{
  "timestamp": "2026-06-30T10:00:00+08:00",
  "level": "INFO",
  "service": "agent",
  "run_id": "run_abc123",
  "thread_id": "thread_xyz",
  "user_id": "user_001",
  "node": "retrieval_agent",
  "event": "vector_search_degraded",
  "message": "向量检索超时（3200ms），降级到 SQL 检索",
  "latency_ms": 3200,
  "error_code": "vector_search_timeout"
}
```

**敏感字段处理**：日志里不出现 `score`、`rank` 等成绩数据，只记录 `profile_id` 引用。原因：日志往往集中存储、多人可访问，成绩是个人隐私数据，不需要出现在日志里。

### 6.2 LangSmith Trace 追踪

每个 Agent run 对应一条 LangSmith Trace，`trace_url` 存在 `agent_runs.trace_url` 里，可以从管理后台一键跳转。

Trace 覆盖的关键信息：

| 字段 | 用途 |
|------|------|
| `node_name` | 知道是哪个节点出了问题 |
| `input_tokens / output_tokens` | 成本归因，识别哪个节点最贵 |
| `latency_ms` | 延迟瓶颈分析 |
| `tool_calls` | 工具调用入参/出参/耗时/成功率 |
| `model_name` | 模型切换后的对比分析 |
| `degraded` | 降级执行标记 |

### 6.3 关键监控指标

| 指标 | 告警阈值 | 含义 |
|------|---------|------|
| `agent_run_error_rate` | 5min > 10% | 系统性故障 |
| `report_p95_latency_ms` | > 60s | 超出用户等待上限 |
| `llm_cost_usd_per_run` | 单次 > $0.50 | prompt 可能有问题 |
| `reflection_max_iter_rate` | 5min > 5% | Report Agent 质量下降 |
| `human_review_pending_count` | > 20 条 | 复核员能力不足，需加人 |
| `vector_search_fallback_rate` | 5min > 20% | pgvector 或 Cohere 服务故障 |

---

## 7. 成本控制

```mermaid
flowchart LR
    subgraph "单次 run Token 预算 (150K 上限)"
        PA2["Profile Agent\n~2K tokens\n1-3 轮追问"]
        RA2["Retrieval Agent\n~5K tokens\nQuery Rewrite + 证据分析"]
        REPORT2["Report Agent\n~15K tokens\n报告生成（输出 3K）"]
        REFLECT2["Reflection Agent\n~8K tokens\n最多 3 轮 × 2.7K"]
        DRAFT2["Review Draft\n~10K tokens\n（仅高风险时触发）"]
    end
```

**成本与质量的权衡**：

Reflection Agent 最多跑 3 轮，每轮约 2.7K tokens（Judge 是最贵的 LLM 节点之一）。3 轮上限一方面防止死循环，另一方面控制成本——3 轮约 8K tokens，如果放到 10 轮就是 27K，每次合规检测的成本翻 3 倍。

3 轮的依据：实际测试中，报告质量问题通常在第 1-2 轮就能修正，第 3 轮几乎不出现"第 3 轮通过但前 2 轮都没通过"的情况。如果 3 轮都没通过，大概率是 Report Agent 的 prompt 有问题，需要人工介入。
