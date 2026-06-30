# 面试速查：设计要点与常见问题

本文件是面试前的快速回顾，每个问题都有一个核心答案和延伸点。

---

## 架构层面

### Q: 为什么用 ARQ 而不是 FastAPI BackgroundTasks？

**核心**：BackgroundTasks 在进程内跑，进程重启任务丢失。报告生成 45s+，进程可能因为部署或 OOM 重启，任务必须能恢复。

**延伸**：ARQ 任务序列化到 Redis，结合 LangGraph Checkpoint，进程重启后 Worker 重新消费任务，LangGraph 从上次完成的节点继续，已完成节点不重跑。

---

### Q: 为什么用 LangGraph，不用 LangChain AgentExecutor / CrewAI？

**核心**：三个核心需求只有 LangGraph 能同时满足：
1. `interrupt()` + Checkpoint 支持跨进程 HITL 等待（最长 4h，期间进程可以重启）
2. `Send` API 支持并行执行（Retrieval + Rule 并发，节省 8s 延迟）
3. 节点可以是普通 Python 函数，不强制 LLM（确定性引擎直接复用）

---

### Q: BFF 层的职责边界怎么划？

**核心**：BFF 只做三件事——鉴权、协议转换（SSE 转发）、Cookie 注入。任何业务判断都不进 BFF。

**为什么**：BFF 混入业务逻辑后，替换前端框架时逻辑散在两处；而且 BFF 是前端代码，后端团队测试困难。

---

### Q: SSE 鉴权方案是什么，为什么不用 Bearer Token？

**核心**：EventSource 不支持自定义请求头，Bearer Token 放 query string 会被日志记录（安全风险）。

**方案**：BFF 种 `HttpOnly; SameSite=Strict` Cookie，SSE 请求自动携带，BFF 校验后转发。备选：60s 一次性 OTP token（使用后立即失效）。

---

### Q: 游标分页 vs offset 分页，为什么要用游标？

**核心**：数据持续写入时，offset=20 的第 21 条可能因为新报告插入而变成上次的第 20 条，导致重复或跳过。游标锚定到记录 ID，不受新数据插入影响。

---

## 数据模型层面

### Q: admission_scores 为什么必须有 batch 字段？

**核心**：同一所大学本科批和专科批的最低位次差距可能超过 2 万名，混用数据会导致严重的推荐错误。

**历史教训**：早期没有 batch 字段，高位次用户被推荐了只在专科批录取的学校，造成误导。

---

### Q: chunks 表为什么有 embedding_model 字段？

**核心**：OpenAI text-embedding-3-small（1536维）和 BGE（1024维）向量空间不兼容，切换模型时需要识别旧向量并批量重建。没有这个字段就只能全库删除重建。

---

### Q: 为什么 evidence 嵌在 reports.evidence_json 而不是单独建表？

**核心**：MVP 阶段每报告 20-50 条证据，查询 pattern 是"按 report_id 取全部"，JSON 数组够用。单独建表增加 JOIN 复杂度而无性能收益。

**延伸**：数据规模增大后再考虑拆表，现在不过度设计。

---

## Agent 设计层面

### Q: 为什么规则引擎不走 LLM，边界怎么划？

**核心**：高考志愿是一次性高风险决策，LLM 有幻觉，规则结论必须 100% 可测试、可追溯。

**边界**：省份/批次/位次匹配、选科/体检/单科校验、保底充足性 → 规则引擎。专业解释、报告文案 → LLM + RAG。

**面试加分点**：规则引擎每次执行都有可审计的输入输出日志，LLM 判断无法在用户投诉时提供证据链。

---

### Q: LangGraph State 并行字段为什么要加 Annotated Reducer？

**核心**：Retrieval Agent 和 Policy Rule Agent 并行执行，都往 `evidence_list` 写数据。默认合并策略是"后写覆盖"，先完成的节点数据丢失。

`Annotated[list[dict], operator.add]` 告诉 LangGraph 做列表拼接而不是覆盖。这是最容易忽略的并发 Bug。

---

### Q: Reflection Agent 为什么分两层，而不是直接让 LLM 检查所有问题？

**核心**：正则检查（禁词）速度快、零成本、零误判，命中直接阻断；LLM Judge 处理正则覆盖不了的语义风险（"这个志愿基本稳了"这种隐晦过度承诺）。先跑正则，过了才跑 LLM，降低约 60% 合规检测成本。

---

### Q: HITL 中断等待 4h，进程重启怎么恢复？

**核心**：`interrupt()` 调用时 LangGraph 自动把 State 快照存到 Checkpoint（Redis 热层 + PostgreSQL 冷层）。进程重启后，`resume()` 从 Checkpoint 恢复 State，图从 interrupt 点之后继续执行，之前完成的节点不重跑。

---

## RAG 层面

### Q: 为什么 MVP 不做 BM25 + RRF 混合检索？

**核心**：代码类精确查询（院校代码、专业组代码）已由 SQL 覆盖，SQL 准确率 100%，BM25 无增量价值；语义查询由向量检索覆盖。BM25 只增加运维复杂度（额外倒排索引、RRF 调参）而无明显收益。已预留 `pg_bm25` 索引结构，Phase 2 可以直接启用。

---

### Q: 为什么向量检索 top-20 再 Rerank 到 top-8，而不是直接 top-8？

**核心**：向量检索（Bi-Encoder）擅长大规模语义召回，但精度不够；Reranker（Cross-Encoder）精度高但计算量大，不适合全量排序。两阶段：向量检索保证召回率，Reranker 保证精准率。这是工业界标准做法。

---

### Q: Context Pack 为什么限制 6K tokens？

**核心**：Report Agent 的 system prompt + 指令约 2K，plan_json 骨架约 2K，给 RAG 证据留 6K，总 prompt 约 10K。加上输出 3K，单次调用 13K tokens。整个 run 6 个 LLM 节点约 30K，远低于 150K 预算上限，有足够余量。

---

## 工程质量层面

### Q: 保底硬下限 10 所是怎么来的？

**核心**：河南 96 个志愿，保守方案 safe 档应占 40%（约 38 所）。10 所是"能保证不因保底不足全军覆没"的绝对最低值。低于 10 说明用户条件过于限制，推荐系统无法生成有意义的保底方案，与其生成虚假安全感的报告，不如明确阻断让用户调整。

---

### Q: 数据发布为什么要人工确认？

**核心**：PDF OCR 有 0.5-2% 字段错误率，自动解析可能有系统性偏移（整列数据错位）。招生计划数据错了会推荐错误学校，用户填报后直接被退档。人工抽样校验 5% 行，发现系统性错误。风险不对称：人工校验的成本远低于数据错误造成的损失。

---

## 可观测性

### Q: 为什么日志里不记录用户分数和位次？

**核心**：日志集中存储、多人可访问（运维、开发都能看）。成绩是个人隐私数据，不需要在日志里出现，通过 `profile_id` 关联查询即可。这是 GDPR 和国内个人信息保护法的基本合规要求。

---

## 关键数字速记

| 指标 | 数值 |
|------|------|
| 风险画像接口 P95 | < 2s |
| 志愿体检接口 P95 | < 5s |
| 报告生成 P95 | < 45s |
| 单次 run token 上限 | 150K |
| 每用户每日报告次数 | 10 次 |
| Reflection 最大轮次 | 3 轮 |
| 人工复核 SLA | 4h |
| 保底志愿硬下限 | 10 所 |
| Context Pack token 预算 | 6K |
| Reranker 候选数 → 精排数 | top-20 → top-8 |
| Embedding 维度 (MVP) | 1536（text-embedding-3-small）|
| Checkpoint TTL | 7 天 |
| 幂等键有效期 | 24h |
| 文件上传大小限制 | 10MB |
| 复核员领取 SLA | 4h（超时自动 close）|
