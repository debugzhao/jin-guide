# Agent 评测工具选型调研

> 配套文档：`backend/evals/doc/Agent评测体系调研.md`（讲「为什么分层评、每层评什么」）。
> 本文档是它的姊妹篇，只回答一个问题：**市面有哪些现成的 Agent 评测工具，哪些适合「问津」项目，怎么接进来。**
> 结论落地的代码接入方案见 §4（LangSmith Dataset 离线评测）与 §5（RAGAS 指标）。

---

## 一、结论先行

市面 agent 评测工具按职责分成三类，对应三个不同的问题：

| 类别 | 回答的问题 | 代表工具 |
|---|---|---|
| **观测/追踪平台** | 这次 run 到底发生了什么（trace、成本、延迟、数据回放） | LangSmith、Langfuse、Phoenix |
| **评测库/框架** | 输出好不好（现成指标函数、LLM-as-judge、红队） | RAGAS、DeepEval、promptfoo |
| **一体化 LLMOps 平台** | 想同时包办追踪 + 评测 + 实验 + A/B | Braintrust、Galileo、W&B Weave |

**对「问津」的选型结论只有一句话：**

> **LangSmith 继续当唯一 trace + 离线评测底座（别换）；确定性规则评测靠现有自研 `evals/` + `tests/eval/` 强化（别引入框架）；RAG 检索质量与生成忠实度这两处语义评测，按需从 RAGAS 单点借用指标（可选，非必须）。**

判断依据是这个项目的**特殊性**：它是一个「确定性规则引擎优先 + LLM 只做解释」的高风险决策系统。PRD §14.2 里权重最高、最不能出错的指标——硬规则误判率 <0.5%、合规禁词漏检 0 容忍、高风险漏检 0 容忍——**全部是规则可判定的**，属于自研确定性 graders 的主场，而不是 LLM judge 打语义分、也不是框架全家桶能解决的地方。只有 RAG 层的 faithfulness / context recall 这一类**语义指标**才是成熟评测库真正高 ROI 的场景。

---

## 二、市面主流工具盘点

| 工具 | 类别 | 定位 | 核心能力 | 开源/商用 | 对本项目适配度 |
|---|---|---|---|---|---|
| **LangSmith** | 观测+评测 | LangChain 官方，Agent 全链路 | trace、成本/延迟、离线 Dataset 评测、LLM-as-judge、CI 回归 | 商业（有免费额度） | ★★★★★ 已接入 |
| **Langfuse** | 观测+评测 | 开源版 LangSmith 替代，可自托管 | trace、评分标注、数据集、Prompt 管理、成本 | 开源 + 云 | 与 LangSmith 二选一，已选前者 |
| **Phoenix (Arize)** | 观测+评测 | 开源可观测 + RAG 检索分析 | embedding 漂移、检索可视化、幻觉分析 | 开源 | 作为 RAG 观测补充可选 |
| **RAGAS** | 评测库 | RAG 专用指标 | faithfulness、answer relevancy、context recall/precision | 开源 | ★★★★ RAG 层首选借用 |
| **DeepEval** | 评测库 | "LLM 的 pytest"，指标墙 | 14+ 指标（G-Eval 等）、assert 式单测 | 开源 | ★★★ 与 RAGAS 二选一 |
| **promptfoo** | 评测库+CLI | Prompt/红队/回归 | 声明式配置、red team、CI/CD、多模型对比 | 开源 | ★★★ 红队场景可选 |
| **Braintrust** | LLMOps 平台 | 评测+实验+追踪一体化 | Eval、Experiment、A/B | 商业（代码开源） | ★★ 重，ROI 低 |
| **Galileo / W&B Weave** | LLMOps 平台 | 企业级 RAG/Agent 评测 | 风险分级、幻觉检测、护栏 | 商业 | ★ 商业绑定，ROI 低 |

> 参考：[Awesome-AI-Evaluation-Guide](https://github.com/AGBAJEMUH/Awesome-AI-Evaluation-Guide/blob/main/tools-and-platforms.md)、[LLM Evaluation in Production（分层体系）](https://bigdataboutique.com/blog/llm-evaluation-frameworks-metrics-best-practices)、[Best RAG Evaluation Tools in 2026](https://futureagi.com/blog/best-rag-evaluation-tools-2026/)、[promptfoo](https://github.com/promptfoo/promptfoo)。

### 2.1 三类的本质区别

- **观测平台**（LangSmith/Langfuse）——回答「这次 run 到底发生了什么」。评测是它的**附加能力**，不是核心。它管 trace、成本、数据回放。
- **评测库**（RAGAS/DeepEval/promptfoo）——回答「输出好不好」，提供现成指标函数/judge，但**不管 trace，需要你自己喂数据**。
- **一体化平台**（Braintrust/Galileo）——想同时包办两者，但重、贵、有绑定。

### 2.2 为什么「问津」不引入框架全家桶

项目架构（README §12、backend-prd-v2 §12）把最硬的部分全部划给了确定性系统：

| 能力 | 实现 | 评测性质 |
|---|---|---|
| 省份/位次/选科/体检/学费匹配 | SQL + 规则引擎 | 规则可判定 |
| 冲稳保分层 | 算法 + 可配置阈值 | 规则可判定 |
| 合规禁词 | 规则 + Reflection | 规则可判定 |
| 专业/城市解释 | RAG + Agent | **语义需 judge** |
| 报告生成 | 模板 + Agent | 半规则半语义 |

也就是说，这个项目**最需要保住的生命线指标，恰恰是成熟评测框架帮不上忙的那一半**（框架假设你主要靠 LLM 判断，它给 judge 打分；而这里主要靠规则引擎判断，需要的是对规则命中结果做确定性断言）。引入 RAGAS/DeepEval 做全量评测，反而会「稀释」掉硬规则的 0 容忍要求——它们的语义 judge 对「规则漏检」没有判定力。

---

## 三、推荐组合（逐层对号入座）

| 层级（对应配套方法论文档的八层） | 用什么 | 状态 | 理由 |
|---|---|---|---|
| 观测底座（贯穿所有层） | **LangSmith** | ✅ 已接入 | LangChain 原生、`@traceable` 已铺开、PRD §14.3 已明确用其 Dataset 离线评测 |
| 提示词层 / 输出安全层 / 工具与行动层 | **自研 `evals/` + `tests/eval/`** | ✅ 已有，继续强化 | 硬规则、合规、工具鉴权全部规则可判定，确定性 graders 最可靠、可 CI、无 judge 偏差 |
| 知识检索层 + 生成忠实度 | **RAGAS（借用指标）+ 现有自研 recall/MRR** | ⚪ 可选补充 | 唯一 LLM-as-judge 的语义评测主场；现有 `rag_golden_set.yaml` + recall@20/MRR 已覆盖检索侧，RAGAS 主要补生成侧忠实度 |
| 模型基座层 / 端到端层 | LangSmith 离线回归 + 黄金集 | 🔶 待接入 | 换模型/版本时跑一遍黄金集，见 §4 |

### 3.1 明确不建议引入

- **Braintrust / Galileo / W&B Weave**：重、商业绑定，对「确定性规则主导」的本项目 ROI 极低。
- **再搭 Langfuse 替代 LangSmith**：已有 LangSmith（`app/config.py` 的 `langsmith_project`），切换纯迁移成本，零收益。
- **用 RAGAS/DeepEval 兜底硬规则评测**：judge 对规则对错无判定力，会漏检高风险，违背 0 容忍。

---

## 四、接入方案一：LangSmith Dataset 离线评测（黄金集回归）

### 4.1 为什么这是最优先的接入

PRD §14.3 已经定义了 30–50 case 的黄金评测集（选科不符、体检命中、保底不足、梯度过密、合规违规、Reflection 3 次未过、建档矛盾追问、约束修改触发局部重生成……），并明确要求「基于黄金集构建 Dataset，在每次重要版本更新后自动运行」。项目已经具备全部前置条件：

- `app/config.py` 已有 `langsmith_api_key` / `langsmith_project = "wenjin-agent-dev"`；
- 所有节点、工具、LLM 调用都已用 `@traceable` 装饰（`app/agent/llm_client.py`、`app/engine/retrieval.py`、各 `app/agent/nodes/*.py`）；
- LangGraph 图入口是 `app/agent/graph.py::create_graph`。

因此离线评测**几乎零改造**：要么直接对图做 `evaluate()`，要么对单个节点函数做 `evaluate()`。

### 4.2 方案 A：对整个 LangGraph 图做端到端评测（对应「端到端层」）

```python
# backend/evals/langsmith/graph_eval.py   （新文件）
# 目的：把黄金集里的「输入档案」跑完整图，用确定性 judge 断言硬规则/合规结果。
# 替代此前全靠人工 trace 回看的回归方式，可在 CI 里 triggered。
from langsmith import Client, evaluate
from langsmith.evaluation import LangChainStringEvaluator
from app.agent.graph import create_graph

client = Client()  # 自动读 LANGSMITH_API_KEY / langsmith_project

# 评测对象：编译一个内存图（无 checkpointer），离线跑黄金集
graph = create_graph(checkpointer=None)


def target(inputs: dict) -> dict:
    """LangSmith evaluate 的 target 契约：inputs -> outputs。

    黄金集每条 example 的 inputs 形状与 POST /reports/generate 的 body 对齐：
    包含 profile（省份/批次/分数/位次/选科/体检限制）与可选预算/城市/专业。
    """
    # 图入口 State 字段以实际 VolunteerPlanState 为准，这里按 PRD 语义展开
    result = graph.invoke({
        "profile": inputs.get("profile"),
        "province": inputs.get("province"),
        "batch": inputs.get("batch"),
    })
    # 只回传评测关心的结构化字段，避免把整段语义报告塞进 judge
    return {
        "rule_results": getattr(result, "rule_results", []),
        "hard_blocked_items": getattr(result, "hard_blocked_items", []),
        "compliance_issues": getattr(result, "compliance_issues", []),
        "degraded_agents": getattr(result, "degraded_agents", []),
        "evidence_json": getattr(result, "evidence_json", {}),
    }


def rule_hit_evaluator(run, example) -> dict:
    """确定性 judge：断言规则引擎命中了黄金集标注的预期规则，且无预期外的硬阻断。

    注意：这里是规则判分，不是 LLM judge——因为硬规则对错是确定性的，
    用 LLM 打分反而会引入偏差，违背「0 容忍」。
    """
    expected = example.outputs  # 黄金集里人工标注的期望结果
    actual = run.outputs
    expected_rules = set(expected.get("expected_rules", []))
    actual_rules = set(actual.get("rule_results", []))
    missed = expected_rules - actual_rules  # 该命中没命中 = 漏检（高危）
    extra_hard = set(actual.get("hard_blocked_items", [])) - set(expected.get("hard_blocked_items", []))
    return {
        "key": "rule_hit",
        "score": 1.0 if not missed and not extra_hard else 0.0,
        "comment": f"漏检: {sorted(missed)}; 多余硬阻断: {sorted(extra_hard)}",
    }


# 黄金集以 Dataset 形式存在 LangSmith 里：dataset/examples 的 outputs 存人工标注
results = evaluate(
    target,
    data="wenjin-golden-set",  # LangSmith Dataset 名，见 4.4 如何上传
    evaluators=[rule_hit_evaluator],
    experiment_prefix="graph-regression",
)
```

### 4.3 方案 B：对单个 `@traceable` 节点做评测（对应「分层」评测）

适合只改某层时，单独回归该层（方法论文档里「只改了 A 层，其他层要不要重测」的最小答案）：

```python
# backend/evals/langsmith/retrieval_eval.py   （新文件）
from langsmith import Client, evaluate
from app.engine.retrieval import vector_search, rerank_evidence

client = Client()


def target(inputs: dict) -> dict:
    # 只测检索 + 重排，绕开 Agent 编排和生成（与 tests/eval/rag_layer 同思路）
    import asyncio
    from app.engine.embedding import embed_text

    async def _run():
        qv = await embed_text(inputs["query"])
        # 注意：vector_search 需要 db session，离线评测需连 docker-compose 的 postgres
        from app.database import async_session_maker
        async with async_session_maker() as db:
            vec = await vector_search(query_vector=qv, university_code=inputs.get("university_code"), top_k=20, db=db)
            rerank = await rerank_evidence(query=inputs["query"], chunks=vec.data["chunks"], top_n=3)
        return {
            "retrieved_chunk_ids": [c["chunk_id"] for c in rerank.data["chunks"]],
        }
    return asyncio.run(_run())


def context_recall_evaluator(run, example) -> dict:
    # 确定性计算 Recall@3：黄金集 standard_chunk_ids 有多少出现在重排 top3
    standard = set(example.outputs["standard_chunk_ids"])
    got = set(run.outputs["retrieved_chunk_ids"])
    recall = len(standard & got) / len(standard) if standard else 0.0
    return {"key": "context_recall@3", "score": recall}
```

> 说明：`vector_search` / `rerank_evidence` 都已带 `@traceable`，所以即便手动 `asyncio.run` 调用，跑在 `evaluate()` 的 trace 上下文里也会生成完整子 span。方案 B 与现有 `tests/eval/rag_layer/test_retrieval_quality.py` 是互补的——前者是 pytest 单测（本地快速、可跳过外部依赖），后者是挂在 LangSmith Dataset 上、带 trace 的版本。

### 4.4 黄金集上传到 LangSmith Dataset（一次性）

```python
# backend/evals/langsmith/upload_golden_set.py   （新文件）
# 把本地黄金集（JSONL/YAML）一次性灌进 LangSmith Dataset。
# 黄金集本体建议沿用现有 tests/eval/ 下的 datasets 目录，单一事实源。
import json
from pathlib import Path
from langsmith import Client

client = Client()
dataset_name = "wenjin-golden-set"

# 每个 example：inputs=输入档案，outputs=人工标注的期望结果（expected_rules 等）
examples = []
for line in Path("evals/prompt_behavior/datasets/golden_set.jsonl").read_text().splitlines():
    if not line.strip():
        continue
    row = json.loads(line)
    examples.append({
        "inputs": {k: row[k] for k in ("profile", "province", "batch") if k in row},
        "outputs": {k: row[k] for k in (
            "expected_rules", "expected_hard_blocked_items", "expected_degraded_agents",
            "expected_evidence_source", "expected_rejected") if k in row},
    })

# 幂等：存在则先清理旧版本，避免重复 example 堆积
existing = [d for d in client.list_datasets() if d.name == dataset_name]
if existing:
    client.delete_dataset(dataset_id=existing[0].id)
ds = client.create_dataset(dataset_name=dataset_name, description="问津黄金评测集（PRD §14.3）")
for e in examples:
    client.create_example(inputs=e["inputs"], outputs=e["outputs"], dataset_id=ds.id)
```

### 4.5 CI 回归（发布前强制）

黄金集离线评测落进 CI，作为「发布硬门禁」（对照方法论文档 §8.10 的「硬门禁 + 加权总分」）：

```yaml
# .github/workflows/eval.yml 片段
- name: 黄金集离线回归
  run: |
    poetry run python -m evals.langsmith.graph_eval
  env:
    LANGSMITH_API_KEY: ${{ secrets.LANGSMITH_API_KEY }}
    LANGSMITH_PROJECT: wenjin-agent-dev
```

规则：`rule_hit` 的 score 必须为 1.0（硬规则漏检/多余硬阻断 → 一票否决停止发布），RAG 的 `context_recall@3` 低于当前线上基线则告警但不阻断（除非涉及关键事实）。

---

## 五、接入方案二：RAGAS 指标（生成忠实度，可选）

### 5.1 什么时候用

现有 `tests/eval/rag_layer/` 已经覆盖了**检索侧**指标（Context Recall@20、重排 Top3 命中率、MRR）。RAGAS 的增量价值在**生成侧**：

| RAGAS 指标 | 对应项目关注点 | 现有覆盖 |
|---|---|---|
| `Faithfulness` | 回答是否脱稿编造（PRD: RAG citation 覆盖率 95%+、关键事实忠实度 100%） | ❌ 未覆盖（现有只测检索，不测生成） |
| `AnswerRelevancy` | 回答是否切题 | ❌ 未覆盖 |
| `ContextRecall` / `ContextPrecision` | 检索命中（已自研） | ✅ 已有 recall@20/MRR |

**结论：只有当你要量化「生成侧忠实度」（Agent Explainer 的报告是否基于检索结果而非编造）时才值得引入 RAGAS，且只引 faithfulness 一个指标即可，不必整套搬。**

### 5.2 依赖与懒加载注意

RAGAS 较重（拉 OpenAI/依赖链），**不要进 `requirements.txt` 主依赖**，作为评测期可选依赖懒加载：

```python
# backend/evals/ragas/faithfulness_eval.py   （新文件）
# 目的：量化「报告生成」阶段的生成忠实度——Agent 的解释是否基于检索证据，而非自由发挥。
# RAGAS 只在运行本评测时才 import，避免污染主服务依赖。
def _load_ragas():
    try:
        from ragas.metrics import Faithfulness
        from ragas.llms import LangchainLLMWrapper
        from langchain_openai import ChatOpenAI
        return Faithfulness(), LangchainLLMWrapper
    except ImportError as exc:
        raise RuntimeError(
            "RAGAS 未安装。评测期依赖，主服务不装：pip install ragas"
        ) from exc


async def eval_faithfulness(cases: list[dict]) -> list[dict]:
    """cases: [{question, answer, contexts}] 三元组，来自黄金集 + 真实检索结果。

    answer 取自真实报告里的解释段落（Agent Explainer 输出），contexts 取自
    vector_search + rerank_evidence 返回的 chunks 文本——保证评的是「真实链路」
    的忠实度，而不是喂假上下文。
    """
    from ragas import evaluate as ragas_evaluate
    from ragas.dataset_schema import SingleTurnSample

    faith, _ = _load_ragas()
    samples = [
        SingleTurnSample(user_input=c["question"], response=c["answer"], retrieved_contexts=c["contexts"])
        for c in cases
    ]
    result = ragas_evaluate(samples, metrics=[faith])
    # 结果落到 eval_reports/ragas/faithfulness_<ts>.json，与现有报告目录一致
    return result.to_pandas().to_dict(orient="records")
```

### 5.3 judge 校准（关键约束）

RAGAS 的 faithfulness 本质是 **LLM-as-judge**，方法论文档贯穿性要求「judge 必须先用人工标注案例校准过，准确率/召回率分开测」。落地时：从黄金集抽 20–30 条已知 faithful/unfaithful 的标注样本，先跑 judge 校准其判准，再用于批量。不适合「拿 RAGAS 直接当真理」——它的分数只用于识别候选问题，最终裁决仍回到人工 + 确定性规则。

---

## 六、落地顺序（Roadmap）

| 优先级 | 动作 | 投入 | 产出 |
|---|---|---|---|
| P0 | 黄金集上传 LangSmith Dataset（§4.4）+ graph 端到端评测（§4.2） | 低（复用现有黄金集 + `@traceable`） | 换版本/换模型可一键回归，替代人工 trace 回看 |
| P0 | 继续充实 `evals/` + `tests/eval/` 的确定性规则评测 | 中 | 硬规则/合规/工具鉴权回归，0 容忍兜底 |
| P1 | CI 接入黄金集回归（§4.5） | 低 | 发布硬门禁 |
| P2 | 需要量化生成忠实度时引入 RAGAS faithfulness（§5） | 低 | 报告「脱稿编造」量化指标 |
| 不做 | Langfuse / Braintrust / Galileo / DeepEval 全家桶 | — | — |

**判断往哪层投入的依据和方法论文档一致：只补「后果严重程度高 × 当前覆盖率低」的层。** 当前项目最高风险的是硬规则漏检与合规漏检（0 容忍），而这恰好是自研确定性 graders 已覆盖、应继续强化的地方；成熟框架只补 RAG 生成忠实度这一个语义缺口。

---

## 七、参考资料

- [Awesome-AI-Evaluation-Guide](https://github.com/AGBAJEMUH/Awesome-AI-Evaluation-Guide/blob/main/tools-and-platforms.md)
- [LLM Evaluation in Production: Frameworks, Metrics & Layered System](https://bigdataboutique.com/blog/llm-evaluation-frameworks-metrics-best-practices)
- [Best RAG Evaluation Tools in 2026](https://futureagi.com/blog/best-rag-evaluation-tools-2026/)
- [promptfoo](https://github.com/promptfoo/promptfoo)
- [LangSmith Evaluation（官方）](https://docs.smith.langchain.com/evaluation)
- [RAGAS 官方文档](https://docs.ragas.io/)

（注：本仓库网络环境对 `github.com` 直接访问受限，上述开源仓库链接以官方文档/镜像为准。）