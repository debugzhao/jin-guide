# 问津 Prompt 模块架构解析

## 一句话结论

问津没有把 Prompt 当成散落的字符串常量，而是当成**需要发布、校验、审计的业务配置资产**：Git 里的 YAML 是唯一权威来源（Git-first），`registry.py` 负责加载 + 防篡改校验 + 缓存，`models.py` 负责严格渲染，`tracing.py` 负责 best-effort 审计。

整套设计的核心哲学是——**Prompt Registry 只管"固定指令怎么发布和追溯"，不管"运行时安全"**；后者永远由代码兜底（工具权限、Schema 校验、引用白名单、合规检测），这条边界在 `backend/docs/prompt-registry.md` 里写得很明确，也是这个模块所有设计决策的出发点。

---

## 一、架构总览

### 1.1 分层职责

```
definitions/<name>/vN.yaml   ← 唯一权威来源：指令原文 + 模型参数 + 输入契约（不可变）
        │
active_versions.yaml          ← 灰度/发布指针：每个 Prompt 当前启用哪个版本
version_hashes.yaml           ← 防篡改指纹：已登记版本的内容 sha256
        │
   registry.py (PromptRegistry)
        │  加载 YAML → 用 models.py 校验 → 缓存 → 启动时全量校验
        ▼
   models.py (PromptSpec)
        │  render(template_name, **vars) 严格变量替换
        │  request_options() 生成 LiteLLM 请求参数 + 可观测元数据
        ▼
   业务 Agent 节点 / API 路由（模块加载时调用一次 prompt_registry.get(...)）
        │
   tracing.py (track_prompt_invocation)
        │  记录 invocation_id / 耗时 / 状态，best-effort 写审计表
        ▼
   LiteLLM Proxy → Moonshot kimi-k2.6（真正的模型调用）
```

四个文件各管一层，互不越界：

| 文件 | 职责 | 不做什么 |
|---|---|---|
| `active_versions.yaml` / `version_hashes.yaml` | 声明式配置：哪个版本上线、上线版本长什么样 | 不含任何渲染逻辑 |
| `registry.py` | 加载、路径一致性校验、防篡改校验、内存缓存 | 不做变量渲染、不发 HTTP 请求 |
| `models.py` | `PromptSpec`/`PromptModelConfig` 两个 Pydantic 模型：变量声明校验、`render()`、`request_options()` | 不管版本从哪来、不管调用后的审计 |
| `tracing.py` | 用 `invocation_id` 串起一次调用的开始/结束，best-effort 落库 | 不管 Prompt 内容本身、不阻断业务失败 |

### 1.2 真实调用链路（以 IntakeAgent 为例）

`intake_agent.py:37-45` 展示了这套机制真正落地的样子：

```python
_PROMPT = prompt_registry.get("intake_chat")          # 模块加载时取一次，进程内复用
_INTAKE_MODEL = _PROMPT.model.alias                    # "intake-agent"（LiteLLM 虚拟模型名）
_SYSTEM_PROMPT = _PROMPT.render("system", forbidden_phrases="、".join(_FORBIDDEN))  # 只渲染一次
```

每次请求时（`intake_agent.py:242`）：

```python
async with track_prompt_invocation(_PROMPT, conversation_id=conversation_id) as invocation:
    payload.update(invocation.request_options())   # model/max_tokens/temperature/stream + metadata
    ... httpx.stream(POST /chat/completions, json=payload) ...
```

关键点：**系统提示词只在模块加载时渲染一次并缓存为模块级变量，请求级的动态内容（报告正文、检索结果、对话历史）完全不进入这个模板**，而是作为独立的 `user`/`tool` 消息追加。这正是 CLAUDE.md 里"报告、摘要、检索结果不再拼入 system，而是作为转义并标记为不可信的独立数据消息"这条规则在 Prompt 层的落地方式——`PromptSpec` 从设计上就不允许把动态数据塞进受信任的固定模板。

七个 Prompt 全部走这个模式（`grep prompt_registry.get` 命中 7 处：`intake_chat`、`report_conversation`、`report_generation`、`reflection_review`、`profile_clarification`、`conversation_title`、`conversation_summary`），职责边界清晰——一个 Agent 只认自己那一份 Prompt，不存在一个"万能大 Prompt"。

### 1.3 启动时的强校验

`app/main.py:25` 和 `app/worker.py:34` 都在模块顶层（不是某个请求处理函数里）调用了 `prompt_registry.validate_all()`——FastAPI 进程和 ARQ Worker 进程各自独立校验一遍全部 7 个 Prompt。这意味着：**如果某个 YAML 文件损坏、变量声明对不上、或者已发布版本被人手滑改动过内容，两个进程都会在启动阶段直接崩溃，而不是等到某次线上请求命中那个 Prompt 才报错**。这是"配置类 bug 尽量往左移"的典型工程实践。

---

## 二、提示词是怎么被管理的

### 2.1 生命周期：新增/修改一个 Prompt 版本

1. 在 `definitions/<prompt_name>/v2.yaml` **新建**文件（不能改 `v1.yaml`，`registry.py:_validate_version_hashes` 会在启动时拦截对已登记版本的原地修改）。
2. 改 `active_versions.yaml` 把该 Prompt 指向 `v2`。
3. 首次针对 `v2` 调用 `validate_all()`（比如本地跑一次 pytest 或重启服务）时，`_load_spec` 会计算 `v2` 的 `content_hash` 并要求手动登记进 `version_hashes.yaml`（否则报"哈希清单键格式非法"或该版本压根没在清单里，取决于是否已经补充；实际流程是改完 YAML 后运行校验、拿到新 hash 再写回 `version_hashes.yaml`）。
4. 回滚只需要把 `active_versions.yaml` 改回 `v1`，`v1.yaml` 本身从未被动过，天然可回滚。

### 2.2 一份 Prompt 定义长什么样

以 `definitions/intake_chat/v1.yaml` 为例：

```yaml
prompt_name: intake_chat
version: v1
owner: agent-platform
description: 建档前高考志愿聊天与工具路由
input_variables: [forbidden_phrases]
model:
  alias: intake-agent      # LiteLLM 虚拟模型名，真正后端是 openai/kimi-k2.6
  temperature: 1
  max_tokens: 2000
  timeout_seconds: 60
  stream: true
templates:
  system: |-
    ...业务规则、工具使用规则、话题边界、硬性约束...
```

一份定义 = **指令原文 + 模型参数 + 输入契约**三者合一，这就是它相比"裸字符串常量"的核心价值：改 `max_tokens` 不用去翻 Python 代码，而且 `temperature`/`timeout_seconds` 这些参数天然和对应的指令版本绑定，不会出现"Prompt 改了但忘记同步改超时时间"的配置漂移。

### 2.3 渲染：`string.Template` 而不是 Jinja2/f-string

`models.py:validate_templates` 做了双向变量校验——模板里用到的变量必须在 `input_variables` 里声明过，声明了但没用到的变量也会报错。`render()` 里传参时同理，多传、少传变量都直接抛异常。这比大多数团队"能跑就行"的字符串拼接严格得多，代价是所有模板只能用 `$variable`/`${variable}` 占位符做纯文本替换，**不支持条件判断、循环、函数调用**——这是刻意的选择，不是能力缺失（详见下一节权衡取舍）。

### 2.4 审计：谁在什么时候用了哪个版本

`tracing.py:track_prompt_invocation` 是个 `@asynccontextmanager`，包住一次 LLM 调用：

- 进入时生成 `invocation_id`（uuid4），记录 `started_at`
- 正常结束记 `status="success"`，抛异常记 `status="failed"` 且不吞异常（`raise` 依然会传给调用方）
- `finally` 块里（不管成功失败都执行）调用 `_persist_trace`，尝试写 PostgreSQL 的 `prompt_invocations` 表；这个写入被包在一层 `try/except Exception` 里，失败只记 `logger.warning`，**绝不向上抛**——审计系统本身故障不能拖垮真正的用户请求。
- 审计表只存 `prompt_name`/`prompt_version`/`prompt_hash`/`model_alias`/`status`/`latency_ms`/`error_type` 和白名单里的业务 id（`agent_run_id`/`report_id`/`conversation_id`/`parent_kind`），**不存 Prompt 正文、不存用户输入**——这是合规红线，`_ALLOWED_CONTEXT_KEYS` 这个白名单就是唯一入口，任何调用方传别的 key 都会被静默过滤掉，不会意外落库。

同一份 `request_options()` 生成的 `metadata` 字典（含 `prompt_name`/`prompt_version`/`prompt_hash`/`invocation_id`）会被塞进发给 LiteLLM 的请求体，LiteLLM 配置了 `success_callback: ["langsmith"]`，所以这份 metadata 同时会被 LangSmith 当作 trace 的标签——一次调用产生两份记录：PostgreSQL 里的结构化审计（低精度、高可靠、best-effort）+ LangSmith 里的完整 trace（高精度、依赖第三方服务可用性）。

---

## 三、设计上的权衡取舍

这些是读代码时能看出"选了 A 而不是 B，付出了什么代价"的地方，是面试里最容易被追问、也最能体现思考深度的部分。

### 1. Git-first vs 数据库 / 远程 Prompt 平台（如 LangSmith Prompt Hub）

**选了**：Prompt 定义就是仓库里的 YAML 文件，和代码一起走 PR review、一起发布、一起回滚。
**放弃了**：产品经理/运营独立改 Prompt 不用等工程发版的能力；也放弃了运行时动态切换、A/B 测试无需重启进程的能力。
**为什么值得**：问津现阶段团队规模小、Prompt 数量少（7 个），Git review 本身就是最省成本的"审批流程"；数据库或远程平台在这个阶段是"过度工程"，还会引入新的运行时依赖（如果 LangSmith 挂了，Prompt 加载不能跟着挂）。**这是一个会随规模变化的决策**——如果未来产品经理需要独立迭代、或者需要不重启做灰度，这一层就要重新评估。

### 2. `string.Template` 而不是 Jinja2 / f-string

**选了**：只支持 `$var` 纯文本替换，且变量声明双向强校验。
**放弃了**：模板里写条件判断、循环、过滤器这些表达能力。
**为什么值得**：Prompt 模板的"图灵完备"能力是攻击面，不是生产力——一旦模板能执行任意表达式，就出现了"谁能改 Prompt 谁就能在渲染时执行代码"的风险；而双向校验把"改了模板忘记加变量声明"“改了变量名忘记同步模板"这类低级错误从运行时报错提前到了**加载时**（进程启动直接崩，而不是某次用户请求时崩），本质是拿"表达力"换"确定性和安全性"。

### 3. 版本号是 `v1`/`v2` 而不是语义化版本（semver）

**选了**：简单递增的 `vN`，`version_hashes.yaml` 里也只是内容指纹，不区分"改动性质"。
**放弃了**：`1.0.1`（措辞微调）vs `1.1.0`（新增规则）vs `2.0.0`（改输出契约）这种能一眼看出变更影响面的语义。
**权衡**：更早的设计方案（`doc/提示词工程优化方案.md`）里实际建议过 semver，但最终实现选了更简单的方案——降低了维护成本（不用纠结"这次改动算 patch 还是 minor"），代价是回滚/升级时无法从版本号本身判断风险等级，只能翻 Git diff 或 owner 口头确认。**这是"团队还小、Prompt 数量少"时的合理简化，不是最优解**。

### 4. `output_schema` 字段目前只是文档占位，没有被代码强制消费

这是全模块里最值得在面试里主动指出的一个"未完成状态"：`models.py:30` 声明了 `output_schema: str | None`，`definitions/reflection_review/v1.yaml` 里也确实填了 `output_schema: ReflectionReviewOutput`，**但全仓库搜索 `output_schema` 只有这一处声明，没有任何地方真正拿这个字符串去反射查找类、做输出校验**。真正的校验发生在 `reflection_agent.py:47` 里手写的 `ReflectionReviewOutput(BaseModel)`，靠人工保证类名和 YAML 里写的字符串一致，这是一个**约定而非强制**的绑定。
**权衡解读**：这说明 Registry 目前解决的是"输入侧"的确定性（变量声明、模型参数），"输出侧"的确定性还留在各 Agent 自己手写 Pydantic 模型解析 JSON——是刻意分阶段推进，还是遗留的技术债，值得在面试时诚实地讨论"如果让我来完善会怎么做"（对应下面面试题 Q9）。

### 5. 审计是 best-effort，不是强一致

**选了**：`_persist_trace` 整个包在 `try/except Exception` 里，DB 写入失败只记 warning。
**放弃了**：审计数据 100% 落库的保证。
**为什么值得**：这是一条明确的优先级声明——**可观测性绝不能反过来成为影响业务可用性的单点故障**。代价是如果审计 DB 长期故障，只能靠日志里的 warning 密度去发现，没有专门的告警链路（这也是一个可以在面试里被追问、值得诚实承认"目前没做"的点）。

### 6. system prompt 模块加载时渲染一次，而不是每次请求渲染

**选了**：`_SYSTEM_PROMPT = _PROMPT.render(...)` 在 import 阶段执行一次，之后所有请求复用同一个字符串。
**放弃了**：运行时动态改变 `forbidden_phrases` 这类模板变量的能力（比如热更新合规禁词列表不用重启进程）。
**为什么值得**：`forbidden_phrases` 来自代码里的常量 `_FORBIDDEN`，本质上是"编译期常量"，没有必要在高并发请求路径上重复做字符串替换——这是一个简单但容易被忽略的性能优化，把渲染开销从"每请求"降到"每进程生命周期一次"。**代价是**如果未来禁词表要支持运营后台动态编辑生效，这里的缓存假设就要被推翻。

### 7. 双向变量校验（未声明 / 未使用都报错）而不是只查"缺变量"

多数团队的模板校验只做"用到的变量必须提供"这一个方向。这里额外校验"声明了但没用到"，本质是把"改错变量名导致某个变量悄悄失效"这类静默 bug 提前暴露——`registry.py`/`models.py` 里这类"宁可更严格、错误尽量提前"的选择反复出现（防篡改 hash、启动时 `validate_all`、双向变量校验），说明这个模块的设计哲学是**一致的**：容忍更高的开发期摩擦，换取更低的线上未知风险。

---

## 四、10 道面试题（附深度答案）

### Q1：为什么不能直接把 Prompt 写成 Python 里的字符串常量，非要设计一个 Prompt Registry？

字符串常量能跑，但解决不了三个生产问题：**可追溯**（出了问题不知道当时用的是哪版指令）、**配置一致性**（模型参数和指令散落在不同地方，容易改了一个忘了另一个）、**发布安全**（改 Prompt 没有版本边界，改错了没法回滚到"上一个已知正常"的状态）。问津的做法是把"指令原文 + 模型参数 + 输入契约"打包成一个不可变的 `PromptSpec`（`models.py`），每次调用记录 `prompt_name/version/hash`（`tracing.py`），本质上是把 Prompt 当成和数据库 migration 一样需要版本化管理的资产。业务价值上：报告生成出问题时，能立刻定位到"是哪一版报告生成 Prompt 导致的"，而不是靠猜。

### Q2：为什么选择 Git-first（本地 YAML）而不是数据库或 LangSmith 这类远程 Prompt 平台？什么情况下应该迁移？

核心权衡是"改动成本 vs 灵活性"。Git-first 让 Prompt 变更天然获得代码审查、CI、版本历史这些免费能力，且没有额外的运行时依赖——如果 LangSmith 服务不可用，Prompt 照样能加载，这对一个高风险决策场景（高考志愿）很重要，不能因为第三方平台抖动导致核心链路不可用。什么时候该迁移：当产品经理需要脱离工程发布节奏独立迭代 Prompt、或者需要不重启进程做 A/B/灰度时，本地 YAML 的"改了必须走 PR 和部署"就成了瓶颈，这时候引入远程平台（但仍建议锁定到不可变版本号，而不是运行时永远拉"最新版"，否则会引入"模型行为漂移但没人知道具体是哪次改动导致的"这类事故）。

### Q3：`validate_templates` 里为什么要做"双向"变量校验——不仅查缺变量，还要查多余的声明变量？

因为"未使用的声明变量"背后往往是一个真实 bug 的信号：可能是模板里的变量名被改了（比如 `$score` 改成了 `$user_score`）但 `input_variables` 里的旧名字忘记同步删除，这时候只做单向校验（只查"用到但没声明"）根本发现不了——因为改名后模板里用的新变量 `$user_score` 如果恰好没声明，会报错；但如果开发者手滑把两个都留着（新旧变量都在 `input_variables` 里），单向校验完全不会报错，代码看起来"能跑"，但调用方传的 `score` 参数实际上已经从没被渲染进最终文本里了——这是一种**静默的语义丢失**，业务上表现为"我以为改了 Prompt 行为，但线上行为没变"，非常难排查。双向校验把这类问题从"运行时不报错但行为不对"变成"启动时直接报错"，是用更严格的加载期检查换取更低的线上诡异 bug 概率。

### Q4：`version_hashes.yaml` 的防篡改机制具体怎么工作？如果我只是想改一个错别字，正确流程应该是什么？

`_load_spec` 加载 YAML 后会用 `prompt_content_hash()` 对原始 dict 做 `sort_keys=True` 的规范化 JSON 序列化再算 sha256，`_validate_version_hashes` 在 `validate_all()` 里把这个新算出来的 hash 和 `version_hashes.yaml` 里登记的旧 hash 比对，对不上就直接报 `PromptRegistryError` 并崩溃。这意味着**已登记版本的文件内容一旦有任何字节级改动（哪怕只是改一个错别字），下次启动校验就会失败**。正确流程不是去改 `v1.yaml`，而是新建 `v2.yaml`（哪怕只改一个字），把 `active_versions.yaml` 指向 `v2`，跑一次校验拿到 `v2` 的新 hash 写进 `version_hashes.yaml`。这么设计的业务原因是：**"已发布的指令内容"本身就是一种审计对象**——如果允许原地改动，那么"哪份报告是用哪版 Prompt 生成的"这个可追溯性承诺就会被破坏，因为 `v1@hash1` 可能在你不知情的时候已经变成了内容不同的 `v1@hash2`。

### Q5：审计写入为什么设计成 best-effort（DB 失败只记 warning，不抛异常）？这样会不会让审计数据不可靠，怎么发现审计本身出了问题？

这是一个明确的优先级排序：**业务主链路的可用性 > 审计数据的完整性**。`_persist_trace` 整个函数体包在 `try/except Exception` 里就是为了保证"哪怕 `prompt_invocations` 表所在的库挂了、连接池耗尽、或者表结构对不上，都不能让一次真实的用户对话请求跟着失败"——审计是锦上添花的可观测性，不该成为影响用户体验的单点故障。代价确实是审计数据可能有缺口，目前的兜底是 `logger.warning`，这一层如果要补强，业务上合理的做法是把这类 warning 接入日志监控（比如按 `"prompt invocation audit write failed"` 关键字设置告警阈值），而不是让审计写入本身变成强一致——因为强一致意味着"报告问答功能可用性依赖审计数据库健康"，这个耦合在高风险决策场景里是不可接受的。

### Q6：`@model_validator(mode="after")` 在 `validate_templates` 里为什么必须用 `after` 模式而不是默认的 `before`？

`model_validator` 是 pydantic v2 用来注册"跨字段"校验逻辑的机制，`before` 模式在字段被解析成模型属性之前运行（拿到的是原始输入 dict），`after` 模式在所有字段各自的 `Field()` 校验都通过、已经变成 `self.templates`/`self.input_variables` 这些真正的模型属性之后才运行。这里的校验逻辑要做的事情是"检查 `templates` 里用到的变量和 `input_variables` 声明的变量是否一致"——这是一个需要同时访问两个已解析字段、做交叉比对的逻辑，`before` 模式下这两个字段可能还没通过各自的格式校验（比如 `templates` 还不确定是不是合法的 `dict[str, str]`），没法安全地做交叉校验；只有等到 `after`，才能保证 `self.templates` 和 `self.input_variables` 都已经是类型正确的属性，可以放心地做集合运算。这个问题的深层考点是"pydantic 的两阶段校验模型"，能答出"字段级校验先跑、模型级校验后跑"这个顺序，就说明理解了为什么很多"多字段一致性"检查都得放在 `after`。

### Q7：`reflection_agent.py` 里 LLM 判断服务不可用时返回 `passed=False`（fail-closed），而不是放行。这个设计决策的业务依据是什么？如果是别的业务场景，这个选择还成立吗？

这是"确定性系统给结论、Agent 给解释"这条项目级原则在异常处理上的延伸：语义合规审查本身就是"兜底防线"，如果它自己不可用了，不能把"审查服务挂了"等价于"内容没问题"，因为这两者完全是两码事——一个是基础设施状态，一个是内容安全状态，把前者偷换成后者会导致**审查形同虚设**（只要把审查服务打挂，任何违规内容都能通过）。在高考志愿这种高风险决策场景，一份包含"保证录取"这类违规表述的报告被错误地标记为"合规通过"交付给用户，造成的伤害远大于"报告晚一点、走有限重试或标记降级"。所以选择 fail-closed，配合上层图的"最多 3 轮重试 + 超过重试次数后走确定性兜底"的机制，把风险控制在可接受范围。这个选择不是普遍真理——如果换成一个低风险场景（比如内容审查的是运营侧的营销文案初稿，而不是直接面向消费者的决策依据），fail-open 可能是更合理的选择，因为可用性优先级更高、误判代价更低。**面试时能主动区分"这是场景驱动的选择，不是放之四海而皆准的最佳实践"，是体现工程判断力的关键。**

### Q8：`_SYSTEM_PROMPT` 在模块加载时就渲染好缓存成一个模块级变量，而不是每次请求都调用 `render()`。这样设计图什么？有什么代价？

`render()` 本身不是特别昂贵的操作（就是 `string.Template.substitute`），但 `forbidden_phrases` 这个变量的值来自代码里的常量列表 `_FORBIDDEN`，在进程运行期间根本不会变化——既然输入不变，输出也不会变，那就没必要在每个并发请求的热路径上重复计算同一个字符串。这是一个典型的"把不变的计算挪到冷路径"的优化，尤其是 `intake_chat` 这种高频、低延迟要求的流式聊天接口，省下的是"每个请求都重新做一次字符串替换"这种量级很小但完全没必要的开销。代价在于：这个优化的前提是"`forbidden_phrases` 是编译期常量"，如果未来产品需求变成"运营后台可以动态调整禁用词表，改完立刻生效"，这个模块级缓存就会变成一个隐藏的"重启才生效"的坑——需要改造成显式的缓存失效机制（比如监听配置变更事件重新渲染），而不能再假设"只渲染一次就够了"。

### Q9：`output_schema` 字段在 Registry 里声明了，但代码里没有任何地方真正拿它去做输出校验，这是不是一个设计缺陷？如果让你来完善，你会怎么做？

严格说这是一个**没有做完的收尾**，而不是一个错误的设计方向——`models.py` 已经预留了这个字段的位置，说明架构上是承认"输出契约也应该像输入契约一样被 Registry 管理"的，只是当前只有 `reflection_review` 这一个 Prompt 填了这个字段，且填的值（`ReflectionReviewOutput`）只是一个字符串，靠 `reflection_agent.py` 里手写的同名 Pydantic 类靠约定对上，没有代码层面的强绑定——如果哪天有人把 YAML 里的字符串改成了别的名字，或者把 `reflection_agent.py` 里的类名改了，两边不会有任何报错提示，只会在运行时因为字段对不上而悄悄出问题。如果让我完善，会分两步走：第一步，把 `Agent` 侧的输出模型类**移动到** `app/prompts` 包内（比如每个 Prompt 一个 `outputs.py` 或者复用 `models.py` 的命名空间），让 `output_schema` 字段存的不是字符串而是一个可以被 `registry.py` 通过模块路径动态 `import_module` 解析出来的**类引用路径**（比如 `"app.prompts.outputs.reflection_review.ReflectionReviewOutput"`），这样 `validate_all()` 在启动时就能顺带校验"这个类是否存在、是否是合法的 BaseModel 子类"，把"约定"升级成"强校验"；第二步，在 `PromptSpec` 上加一个 `parse_output(raw: str) -> BaseModel` 方法，让业务代码不用自己写 `model_validate_json`，而是统一走 Registry 提供的解析入口，这样"渲染输入用 Registry，解析输出也用 Registry"两端对称，架构上更完整。

### Q10：现在每个 Prompt 都是在模块加载时调用一次 `prompt_registry.get(...)` 缓存成模块级变量，如果未来要支持"运行时按用户分桶做 A/B 测试，不重启进程切换版本"，这套架构会在哪里撞墙？需要怎么改？

会在两个地方撞墙：第一，`_PROMPT = prompt_registry.get("intake_chat")` 这种写法是**进程启动时绑死的**，`PromptRegistry._cache` 的 key 是 `(prompt_name, version)`，`get()` 内部又是"没传 version 就取 `active_versions.yaml` 里的当前版本"，一旦模块加载时已经把结果赋值给了 `_PROMPT` 这个模块级变量，后续 `active_versions.yaml` 就算改了、`_load_active_versions` 的缓存就算失效重新读了，`_PROMPT` 这个变量本身也不会跟着变——因为它是一次性求值的结果，不是"每次访问都重新查一次"的懒加载。第二，`request_options()` 和 `render()` 里都没有"实验分桶"的概念，`PromptSpec` 是完全无状态的确定性数据结构，不知道"当前这个用户应该走哪个版本"。要支持 A/B，需要在架构上加一层**决策边界**：把 `_PROMPT = prompt_registry.get(...)` 从模块级常量改成请求级查询——比如 `get_prompt_for_request(prompt_name, experiment_context)`，内部根据用户 id 哈希分桶决定传给 `prompt_registry.get(name, version=...)` 的具体版本号，同时要把 `PromptRegistry.get()` 的内部缓存策略从"进程启动时读一次 `active_versions.yaml` 就不再变"改成支持热刷新（比如加 TTL 或者监听配置变更信号），并且 `tracing.py` 记录的 `prompt_version` 要能反映"这次请求实际用的是 A 桶还是 B 桶"，否则实验数据和审计数据对不上号，没法做实验效果归因。这本质是把当前"进程级单版本"的简化模型，升级成"请求级多版本路由"的模型，是一次不小的架构改造，不是加个参数就能解决的。
