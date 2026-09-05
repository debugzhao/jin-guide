## 提示词工程总结

### 问津Agent 现有架构中提示词工程存在的问题

问津agent系统中有七个agent，提示词分散在不同agent中。 

**存在的问题：**

1. 提示词管理分散，不方便集中治理
2. 模型参数、输出格式、安全规则容易发生漂移（什么是漂移？）
3. 无法追溯当前agent用的是哪个版本的提示词

### 生产级Agent 系统是如何优化提示词工程的？

 真实生产级别的agent把提示词当做需要评测、发布、灰度、回滚的业务配置资产，而不是简单的字符串

成熟的提示词管理体系需要具备一下能力：

1. 资产管理

   每份提示词都需要有稳定的名称、版本号、使用场景、输入契约、输出契约

2. 版本管理

   每次修改提示词都会产生不可变的版本，可以查询某次请求用了哪个版本的提示词

3. 环境管理

   开发、测试、生成明确使用哪个版本的提示词

4. 评测

   提示词、模型、工具定义之后要跑回归集

5. 发布

   支持灰度发布、AB发布、快速回滚

6. 观测

   每次请求记录提示词版本号、调用工具集、耗时、token消耗等等

7. 安全管理

   指令和数据隔离，最小化工具权限

8. 权限管理

### 问津Agent 如何优化提示词工程？

使用git 有限的提示词注册器管理系统提示词，每个agent 都有自己的提示词， 只不过统一通过注册器获取

```  
backend/app/prompts/
├── registry.py
├── schemas.py
├── common/
│   ├── safety.md
│   └── untrusted_context.md
├── intake/
│   └── v1.md
├── conversation/
│   └── v1.md
├── report/
│   └── v1.md
├── reflection/
│   └── v1.md
├── profile_clarification/
│   └── v1.md
├── conversation_summary/
│   └── v1.md
└── conversation_title/
    └── v1.md
```

### 模型参数治理（一）：max_tokens 该设多大

```
max_tokens = reasoning 预算 + 正式输出预算 + 安全余量
```

**这三项都必须来自真实调用数据，不能凭公式空推。** 公式本身只是分账方式，每一项填什么数字要靠实测。

需要特别注意的前提：**kimi-k2.6 默认开启 thinking，而 reasoning 消耗是算在 `max_tokens` 额度里的**。配置时如果只按"我期望模型输出多长"来估，就会漏掉 reasoning 这一大块，导致正式输出还没开始写就被截断。

判断是否踩坑看 `finish_reason`：

| 值 | 含义 | 处理方式 |
|---|---|---|
| `stop` | 模型自然结束 | 正常，内容可信 |
| `length` | **撞到 `max_tokens` 被硬切断** | 内容不完整，必须重试或提预算 |
| `tool_calls` | 模型要调工具 | 走工具分支 |
| `content_filter` | 被内容审核拦截 | 单独处理 |

这组数据说明两件事：

1. reasoning 消耗与任务类型强相关——对话路由（intake_chat）只要几百，结构化抽取（summary/title）动辄上千甚至打满；
2. 一旦 reasoning 吃满额度，表现出来是"模型返回了不合法 JSON"，**极易误判为模型质量问题**，实际是预算配置问题。


#### 配置原则

按任务性质分层，而不是给所有 prompt 配同一个量级：

- **结构化抽取 / 短文本生成**（摘要、标题、澄清）：关闭 thinking，`max_tokens` 按输出估算即可；
- **需要推理的任务**（报告生成、反思审查）：保留 thinking，但要给 reasoning 留足空间；
- **非流式（`stream: false`）调用要格外小心**：reasoning 越长，一次性响应体越大，越容易触发 `httpx.ReadTimeout`。对这类调用，提高 `max_tokens` 反而更危险，应优先关闭 thinking。

### 模型参数治理（二）：模型选型依据

Moonshot 当前在售模型（`kimi-k2`、`kimi-k2.5`、`moonshot-v1` 系列均已下线，调用返回 404）：

| 模型 ID | 上下文 | 价格（输入/输出，每百万 token） | 定位 |
|---|---:|---|---|
| `kimi-k3` | 1M | $3 / $15 | 旗舰，2.8T 参数 |
| **`kimi-k2.6`** | 256K | **$0.95 / $4.00** | 通用，支持 thinking/non-thinking 双模式 |
| `kimi-k2.7-code` | 256K | $0.95 / $4.00 | 编程向，默认强制 thinking |
| `kimi-k2.7-code-highspeed` | 256K | — | 低延迟编程版 |

**结论：继续用 `kimi-k2.6`，不要换。** 依据：

1. **`kimi-k3` 是浪费**：它的卖点是 1M 上下文，但本项目实测输入才 1812 tokens（摘要调用）、823 tokens（intake 首轮），256K 窗口用不到 1%。换过去价格涨 3～3.75 倍，买的是完全用不上的窗口。
2. **`kimi-k2.7-code` 不对症**：编程向调优，且默认强制开 thinking——正是上面 reasoning 吃满额度问题的来源。
3. **`kimi-k2.6` 恰好匹配分层需求**：它是唯一支持 thinking 开关的型号，而现有 10 个 prompt 天然分成两类——摘要/标题/澄清是结构化抽取，不需要推理；报告生成/反思审查需要推理。双模式正是解法。

需要留意的是，当前 `litellm_config.yaml` 里 6 个 alias（profile-agent、retrieval-agent、intake-agent、report-agent、reflection-agent、review-draft-agent）全部指向同一个 `kimi-k2.6`，分 alias 的意义在于独立的观测与成本口径，不是真的在用不同模型。thinking 开关应当配在 prompt 定义层（按任务分层），而不是靠换 alias 实现。

