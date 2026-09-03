# Python 核心语法深度指南：Java 工程师的 AI Agent 视角

> 面向有 Java 经验、主攻 AI Agent 开发的工程师。不讲玩具语法，讲的是你在 LangGraph/LangChain 代码里天天看到、看不懂就卡住的那些东西。

---

## 目录

1. [基础语法要点](#1-基础语法要点)
   - 1.1 list / dict / tuple
   - 1.2 f-string
   - 1.3 try / except
   - 1.4 `if __name__ == "__main__"`
   - 1.5 命名规则与访问控制
   - 1.6 函数参数：`*` 关键字-only 分隔符
2. [Python 类型系统](#2-python-类型系统)
   - 2.1 基础类型标注
   - 2.2 TypedDict
   - 2.3 Annotated 与 LangGraph Reducer
   - 2.4 Protocol（结构子类型 / 鸭子类型）
   - 2.5 Generic 泛型
   - 2.6 dataclass
   - 2.7 注解求值时机：`from __future__ import annotations`
3. [装饰器](#3-装饰器)
   - 3.1 装饰器是什么（从函数对象说起）
   - 3.2 函数装饰器
   - 3.3 带参数的装饰器
   - 3.4 类装饰器
   - 3.5 functools.wraps
4. [生成器与 yield](#4-生成器与-yield)
   - 4.1 迭代器协议
   - 4.2 生成器函数
   - 4.3 yield from
   - 4.4 生成器表达式
   - 4.5 在流式输出中的实际用法
5. [异步编程](#5-异步编程)
   - 5.1 为什么需要异步
   - 5.2 async/await 基础
   - 5.3 asyncio 事件循环与 Task
   - 5.4 并发模式：gather / TaskGroup
   - 5.5 异步生成器与流式
   - 5.6 同步代码调用异步代码
6. [上下文管理器](#6-上下文管理器)
   - 6.1 with 语句的本质
   - 6.2 contextlib 实用工具
7. [闭包与高阶函数](#7-闭包与高阶函数)
   - 7.1 闭包
   - 7.2 高阶函数与 functools.partial
8. [特殊方法（Dunder Methods）](#8-特殊方法dunder-methods)
9. [综合案例：从零理解 LangGraph 状态流](#9-综合案例从零理解-langgraph-状态流)
10. [附录：快速查阅表](#附录快速查阅表)

---

## 1. 基础语法要点

### 1.1 list / dict / tuple

#### list（有序、可变）

**Java 对比**：类似 `ArrayList`，但字面量更轻，支持负数下标和 `+` 拼接。

```python
# 创建
messages = [HumanMessage("hello"), AIMessage("hi")]
tools = [search_tool, calc_tool]

# 下标访问（负数下标是 Python 特有）
messages[0]    # 第一条
messages[-1]   # 最后一条（不用 messages[len-1]）
messages[1:3]  # 切片，取索引 1、2

# 拼接
full = [SystemMessage("system")] + messages  # 返回新列表

# 追加
messages.append(AIMessage("done"))

# 遍历
for msg in messages:
    print(msg.content)

# LangGraph 节点必须把结果包进 list：
return {"messages": [response]}  # 即使只有一条也要放进列表
```

#### dict（键值映射）

**Java 对比**：类似 `Map<K,V>`，但字面量更像 JSON，支持嵌套。

```python
# 创建
state = {"messages": [], "route": None}
config = {"configurable": {"thread_id": "42"}}  # 嵌套字典

# 读取
state["messages"]                    # key 不存在 → KeyError
state.get("missing")                 # key 不存在 → None（安全读取）
config["configurable"]["thread_id"]  # 嵌套读取

# 修改
state["route"] = "knowledge_base"

# 注意：{} 是空 dict，{"a", "b"} 是 set（没有冒号）
```

#### tuple（有序、不可变）

**Java 对比**：类似 `record` 或 `Pair<A, B>`，但更轻——不需要提前定义类。

```python
# 基础用法
point = (10, 20)
point[0]  # 10（只读，不能 point[0] = 5）

# 解构赋值
x, y = point

# LangChain 消息简写：(role, content) 二元组
messages = [
    ("human", "what's the weather?"),  # 等价于 HumanMessage(content="...")
    ("ai", "It's sunny."),             # 等价于 AIMessage(content="...")
]
# LangChain 内部调用 convert_to_messages() 转换

# 常见角色映射：
# "human" / "user"      → HumanMessage
# "ai" / "assistant"    → AIMessage
# "system"              → SystemMessage
```

#### set（无序、唯一、可变）

**Java 对比**：类似 `HashSet<T>`，字面量更简洁。注意：`{}` 是空 dict，空 set 必须用 `set()`。

```python
# 创建
roles = {"human", "ai", "system"}
seen_ids = set()          # 空 set 必须用 set()，{} 是空 dict！

# 最常用场景：去重
tool_names = ["search", "calc", "search", "translate"]
unique = list(set(tool_names))   # 顺序不保证

# 成员检测 O(1)——比 list 的 O(n) 快
if "search" in roles:
    print("has search tool")

# 集合运算——权限校验场景
allowed   = {"read", "write", "search"}
requested = {"write", "delete", "search"}

requested & allowed   # 交集：{'write', 'search'}（有权限的请求）
requested - allowed   # 差集：{'delete'}（无权限的请求，需拦截）
requested | allowed   # 并集：{'read', 'write', 'search', 'delete'}
requested ^ allowed   # 对称差：只在一边的元素

# 增删
roles.add("tool")
roles.discard("unknown")   # 不存在也不报错（安全删除）
roles.remove("human")      # 不存在会 KeyError
```

#### 数据结构选型速查

| 结构 | 有序 | 唯一 | 可变 | 典型场景 |
|------|------|------|------|---------|
| `list` | ✓ | ✗ | ✓ | 消息列表、工具列表 |
| `tuple` | ✓ | ✗ | ✗ | 固定结构、字典键、消息二元组 |
| `dict` | ✓ | key 唯一 | ✓ | state 更新、配置、JSON |
| `set` | ✗ | ✓ | ✓ | 去重、成员检测 O(1)、权限集合 |

*Python 3.7+ dict 保证插入顺序。

#### 迭代方法

##### for / enumerate / zip

```python
messages = ["hello", "hi", "bye"]
tools    = ["search", "calc", "translate"]

# 基础 for
for msg in messages:
    print(msg)

# enumerate：同时拿下标和值（Java: for (int i=0; i<list.size(); i++)）
for i, msg in enumerate(messages):
    print(f"[{i}] {msg}")

enumerate(messages, start=1)   # 下标从 1 开始

# zip：并行遍历两个序列（长度取短的，超出部分丢弃）
for msg, tool in zip(messages, tools):
    print(msg, "→", tool)

# zip + enumerate（同时需要下标）
for i, (msg, tool) in enumerate(zip(messages, tools)):
    print(i, msg, tool)
```

##### dict 遍历

```python
state = {"route": "tools", "risk": "low", "answer": None}

# keys()——只遍历 key（也是 for k in dict 的默认行为）
for key in state:
    print(key)

# values()——只遍历 value
for val in state.values():
    print(val)

# items()——同时拿 key 和 value（最常用）
for key, val in state.items():
    print(f"{key}: {val}")

# 过滤非空字段
filled = {k: v for k, v in state.items() if v is not None}
# {"route": "tools", "risk": "low"}
```

##### 推导式（Comprehension）

**是什么**：一行表达式生成 list / dict / set，比 for 循环更简洁、更 Pythonic。

```python
messages = ["hello", "hi", "bye"]
tools    = [" search ", " calc "]

# 列表推导式：[表达式 for 变量 in 可迭代 if 条件]
contents   = [m.upper() for m in messages]           # ['HELLO', 'HI', 'BYE']
long_msgs  = [m for m in messages if len(m) > 2]     # ['hello', 'bye']
tool_names = [t.strip() for t in tools]              # ['search', 'calc']

# dict 推导式
state = {"route": "tools", "risk": None, "answer": "done"}
filled = {k: v for k, v in state.items() if v is not None}
# {'route': 'tools', 'answer': 'done'}

# set 推导式（自动去重）
roles = {"human", "ai", "human", "system"}
short_roles = {r for r in roles if len(r) <= 2}    # {'ai'}

# 嵌套推导式（展平二维列表）
matrix = [[1, 2], [3, 4], [5, 6]]
flat   = [x for row in matrix for x in row]        # [1, 2, 3, 4, 5, 6]
```

##### reversed / sorted

```python
messages = ["hello", "hi", "bye"]

# reversed：反向遍历，不复制列表（惰性）
for msg in reversed(messages):
    print(msg)   # bye, hi, hello

# sorted：排序后遍历，返回新列表，不修改原列表
for msg in sorted(messages):
    print(msg)   # bye, hello, hi（字母序）

# 自定义排序键
tools = [{"name": "search", "cost": 3}, {"name": "calc", "cost": 1}]
for t in sorted(tools, key=lambda x: x["cost"]):
    print(t["name"])   # calc, search

# reverse=True：降序
sorted(messages, reverse=True)   # ['hi', 'hello', 'bye']
```

##### 解构赋值（Unpacking）

```python
# 基础解构
first, second, third = ["a", "b", "c"]

# * 收集剩余元素
first, *rest = ["a", "b", "c", "d"]   # first="a", rest=["b","c","d"]
*init, last  = ["a", "b", "c", "d"]   # init=["a","b","c"], last="d"

# 循环中解构 tuple
pairs = [("human", "hello"), ("ai", "hi")]
for role, content in pairs:
    print(f"{role}: {content}")

# 嵌套解构
data = [("Alice", (90, 85)), ("Bob", (78, 92))]
for name, (score1, score2) in data:
    print(f"{name}: avg={( score1 + score2) / 2}")
```

---

### 1.2 f-string

**是什么**：在字符串前加 `f`，花括号里可以写任意 Python 表达式。

**Java 对比**：类似 `"hello %s".formatted(name)` 或 `STR."hello \{name}"`，但更简洁且支持表达式。

```python
name = "Alice"
age = 30

# 基础插值
f"Hello, {name}!"                  # Hello, Alice!

# 表达式
f"Next year: {age + 1}"            # Next year: 31

# 函数调用
f"Error: {repr(error)}"            # Error: ValueError('...')

# 格式化
price = 12.3456
f"Price: {price:.2f}"             # Price: 12.35
f"Percent: {0.856:.1%}"           # Percent: 85.6%

# 多行（三引号）
prompt = f"""
You are {name}.
Your goal is to {goal}.
"""

# 注意：不要用 f-string 拼 SQL（注入风险），复杂 JSON 用 json.dumps()
```

---

### 1.3 try / except

**Java 对比**：类似 `try/catch/finally`，但没有 checked exception——Python 不要求函数签名声明 `throws`。

```python
# 基础结构
try:
    result = int(user_input)
except ValueError as error:
    print(f"不是数字: {error}")

# 捕获多种异常
try:
    response = llm.invoke(messages)
except (ConnectionError, TimeoutError) as error:
    return f"网络错误: {error}"

# finally：无论是否异常都执行
try:
    conn = get_connection()
    result = conn.query()
except Exception as error:
    log_error(error)
    raise  # 重新抛出，不吞掉异常
finally:
    conn.close()  # 一定会执行

# 捕获所有异常（谨慎使用）
try:
    result = execute_code(code)
except BaseException as error:
    return f"执行失败: {repr(error)}"  # repr() 包含类型信息

# 主动抛出
def get_weather(city: str):
    if city not in ["nyc", "sf"]:
        raise ValueError(f"Unknown city: {city}")  # raise 不是 throw

# try/except/else：没有异常时执行 else
try:
    value = parse(data)
except ParseError:
    value = default
else:
    process(value)  # 只有 parse 成功时才走这里
```

**关键区别**：Python 异常是运行时概念，函数签名不声明异常，调用方自己决定是否处理。

---

### 1.4 `if __name__ == "__main__"`

**是什么**：Python 的脚本入口守卫——区分"直接运行"和"被 import"两种场景。

**Java 对比**：类似 `public static void main(String[] args)`，但 Python 没有强制入口，解释器从文件顶部一路执行到底，所以需要手动守卫。

```python
# 没有守卫的问题：
# 如果别的模块 import 这个文件，asyncio.run(main()) 会立即执行！
asyncio.run(main())  # 危险：放在顶层会在 import 时触发

# 有守卫的写法：
async def main():
    result = await graph.ainvoke({"messages": [HumanMessage("hello")]})
    print(result)

if __name__ == "__main__":
    asyncio.run(main())   # 只有直接运行这个文件时才执行

# 原理：Python 给每个模块设置 __name__
# 直接运行：__name__ == "__main__"
# 被 import：__name__ == "模块文件名"（如 "my_agent"）

# 常见误解：不是必须叫 main()，只是约定
if __name__ == "__main__":
    run_demo()   # 叫什么都行
```

---

### 1.5 命名规则与访问控制

Python 没有 `public`/`private` 关键字，靠命名约定表达访问意图：

| 风格 | 示例 | 用途 |
|---|---|---|
| `snake_case` | `my_func`, `tool_id` | 函数、变量、模块（Python 主流） |
| `UPPER_SNAKE` | `MAX_RETRY`, `BASE_URL` | 模块级常量 |
| `PascalCase` | `ToolRegistry`, `AgentState` | 类名 |
| `_single` | `_tools`, `_build_config` | 约定私有，模块外不应访问 |
| `__double` | `__secret` | 类内私有，触发名称改写（Name Mangling） |
| `__dunder__` | `__init__`, `__str__` | Python 保留的魔法方法，不要自定义 |

```python
class ToolRegistry:
    def register(self, tool):    # public：外部正常调用
        self._validate(tool)
        self.__storage[tool.name] = tool

    def _validate(self, tool):   # _：约定内部使用（语言不拦截，靠约定）
        ...

    def __cleanup(self):         # __：名称被改写为 _ToolRegistry__cleanup
        ...                      #     外部用 obj.__cleanup() 会报 AttributeError

# Java 对比：
# _x  ≈ protected（能访问，但不该访问）
# __x ≈ private（语言层面阻断，但绕不过去也不是真的访问不到）
```

---

### 1.6 函数参数：`*` 关键字-only 分隔符

**是什么**：`*` 单独出现在函数签名里（后面不带名字）时，是一道"分界线"——它后面的所有参数，调用时只能用 `参数名=值` 的方式传，不能按位置顺序传。

`*` 管的只是 "**必须用 `参数名=值` 的方式传**" 这件事，**不管写的顺序**。

**为什么用**：

- 防止传错顺序：多个同类型参数（比如几个 str、几个 list）按位置传很容易传反，强制写参数名一眼看清
- 可读性：调用处每行都写明"这个值是什么"，读代码的人不用回去翻函数定义
- 给未来留余地：以后想加参数，不用担心中间插一个会打乱所有调用方的位置顺序

**Java 对比**：Java 没有这个机制，参数要么全按位置传，要么用 Builder 模式解决"参数多容易传错"。Python 用 `*` 在语法层面直接强制调用方指名道姓。

```python
def assemble_messages(
    *,                              # ← 分界线：它后面的参数全是"只能用关键字传"
    system_prompt: str,
    dynamic_items: list[ContextItem],
    history: list[dict],
    user_message: str,
) -> list[dict]:
    ...

# ✅ 正确：必须写参数名
assemble_messages(
    system_prompt="你是助手",
    dynamic_items=items,
    history=history_list,
    user_message="帮我写个方案",
)

# ❌ 错误：按位置传 → TypeError（不接受位置参数）
assemble_messages("你是助手", items, history_list, "帮我写个方案")
```

**和 `*args` / `**kwargs` 区分**：

- `*args`：带名字的 `*`，作用是"收集"多余的位置参数成元组
- `**kwargs`：收集多余的关键字参数成字典
- 单独 `*`：不带名字，只当标记，作用是"禁止"位置传参，与收集无关

**典型使用场景**：参数多且类型容易混淆的函数、配置类 / 初始化类、公共 API / 入口函数——凡是"不希望调用方靠猜位置来调"的地方。

### 1.7 *args和 **kwargs区别和使用场景 

**一句话：** `*args` 把"多出来的位置参数"收进一个元组，`**kwargs` 把"多出来的关键字参数"收进一个字典。下面拆开讲，都用你熟悉的场景。

**1. `*args` —— 收集多余的位置参数**

```python
def log(*args):
    print(args)

log("hello")            # ('hello',)        元组，注意只有一个元素也要逗号
log("hello", 1, 2, 3)   # ('hello', 1, 2, 3)
log()                   # ()                一个都不传也行
```

看函数签名：`*args` 里的 `*` 会把**所有按位置传的参数**一股脑收进一个叫 `args` 的**元组**。

`args` 这个名字只是**约定**，不是语法要求，你写成 `*things`、`*rest` 效果一样：

```python
def show(*rest):
    print(rest)

show(1, 2, 3)   # (1, 2, 3)
```

**2. `**kwargs` —— 收集多余的关键字参数**

```python
def log2(**kwargs):
    print(kwargs)

log2(a=1, b=2)             # {'a': 1, 'b': 2}
log2(name="tyson", age=30) # {'name': 'tyson', 'age': 30}
log2()                     # {}
```

两个 `**` 会把所有**用 `名字=值` 传**的参数收进一个叫 `kwargs` 的**字典**，key 是参数名，value 是值。

**3. 两个一起用（最常见的完整写法）**

```python
def flex(*args, **kwargs):
    print("位置参数:", args)
    print("关键字参数:", kwargs)

flex(1, 2, x=3, y=4)
# 位置参数: (1, 2)
# 关键字参数: {'x': 3, 'y': 4}
```

**4. 它们还有"反方向"的用法：调用时拆包**

上面是**定义函数**时收参数；反过来，**调用函数**时用 `*` / `**` 可以把序列/字典"拆开"传进去：

```python
def add(a, b, c):
    return a + b + c

nums = [1, 2, 3]
add(*nums)          # 等价于 add(1, 2, 3)     → 6

d = {"a": 1, "b": 2, "c": 3}
add(**d)            # 等价于 add(a=1, b=2, c=3) → 6
```

**5. 最典型的使用场景：装饰器"透传所有参数"**

你在文档里看过很多 `def wrapper(*args, **kwargs)`，就是这个原因——包装函数**不知道自己会收到什么参数**，用这两个符号"原样接住、原样转交"，一个字都不改：

```python
def log_call(func):
    def wrapper(*args, **kwargs):      # 接住任何形式的参数
        print("调用:", func.__name__)
        return func(*args, **kwargs)   # 原样转交给真正的函数
    return wrapper

@log_call
def greet(name, greeting="Hi"):
    return f"{greeting}, {name}"

greet("Tom")                       # greet 只收一个，wrapper 转发没问题
greet("Tom", greeting="Hello")     # 关键字也照样转发
```

**6. 别和上次讲的单独 `*` 混淆**

| 写法            | 作用                         | 用在哪   |
| --------------- | ---------------------------- | -------- |
| `*args`         | **收集**多余位置参数成元组   | 函数定义 |
| `**kwargs`      | **收集**多余关键字参数成字典 | 函数定义 |
| 单独 `*`        | **禁止**位置传参，强制关键字 | 函数定义 |
| 调用时 `*list`  | **拆开**序列按位置传         | 函数调用 |
| 调用时 `**dict` | **拆开**字典按名字传         | 函数调用 |

**记忆口诀：** 星号 `*` = "打包/拆包"的开关——定义时打包收进来，调用时拆开传出去；一个星号管位置参数，两个星号管带名字的参数。

---

## 2. Python 类型系统

### 2.1 基础类型标注

**是什么**：Python 3.5+ 引入的可选类型提示（hint），运行时不强制，IDE 和 mypy 用来做静态检查。

**Java 对比**：Java 的类型是强制的编译期概念；Python 的类型标注是"文档 + 可选检查"，运行时默认忽略。

```python
# Java: String name = "hello"; int count = 42;
name: str = "hello"
count: int = 42

# 函数签名
def greet(name: str, times: int = 1) -> str:
    return f"Hello, {name}! " * times

# 集合类型（Python 3.9+ 可直接用小写）
numbers: list[int] = [1, 2, 3]
mapping: dict[str, int] = {"a": 1}
pair: tuple[str, int] = ("alice", 30)

# 联合类型（3.10+ 用 | 语法，旧版用 Union）
def parse(value: str | int) -> str:
    return str(value)

# Optional = T | None
def find(key: str) -> str | None:
    return None  # 必须在类型里显式声明 | None 才算"允许为空"

# Literal：限定只能是某几个值（轻量枚举）
from typing import Literal

def route(state) -> Literal["tools", "knowledge_base", "__end__"]:
    ...  # LangGraph 条件边依赖这些字符串做路由

# Any：放弃类型检查（谨慎使用）
from typing import Any
def process(data: Any) -> dict[str, Any]:
    ...
```

---

### 2.2 TypedDict

**是什么**：给普通字典加类型约束，让字典有"结构"——LangGraph 的 State 就是这个。

**为什么用**：LangGraph 的 `AgentState` 需要序列化/反序列化存入 Checkpoint，用 TypedDict 而不是普通 class，是因为字典可以直接 JSON 化，无需额外序列化逻辑。

**Java 对比**：类似 `Map<String, Object>` + 编译期知道每个 key 的类型。比 `Map<String, Object>` 安全，比定义完整 POJO 轻量。

```python
from typing import TypedDict, Annotated
from langgraph.graph.message import add_messages

# 基础用法——就是带类型的字典
class UserProfile(TypedDict):
    name: str
    age: int
    email: str | None

# 使用：和普通字典完全一样
profile: UserProfile = {"name": "Alice", "age": 30, "email": None}
print(profile["name"])      # "Alice"
print(profile.get("age"))   # 30

# TypedDict 不阻止运行时添加额外字段（Python 是动态的）
# 但 mypy/IDE 会报错——这就是它的价值

# --- LangGraph 真实场景 ---
class AgentState(TypedDict):
    messages: Annotated[list, add_messages]  # Annotated 指定 reducer，见下节
    route: str | None
    risk_level: str | None
    final_answer: str | None

# LangGraph 节点函数：接收完整 state，返回部分更新
def classify_intent(state: AgentState) -> dict:
    return {"route": "knowledge_base"}  # 只返回要改的字段
```

---

### 2.3 Annotated 与 LangGraph Reducer

**是什么**：在类型上附加额外元数据。`Annotated[T, metadata]` 仍然表示类型 `T`，但携带了 `metadata`，框架可以读取它改变行为。

**LangGraph 的 reducer 机制**：节点返回字典时，有 reducer 的字段不是覆盖而是合并。

```python
from typing import Annotated
from operator import add
from langgraph.graph.message import add_messages

# 告诉 LangGraph：这个字段用 add 函数合并（列表拼接）
# state.numbers = [1, 2]，节点返回 {"numbers": [3, 4]}
# 结果：[1, 2, 3, 4]，不是 [3, 4]
numbers: Annotated[list[int], add]

# messages 用 add_messages（会按消息 id 去重、处理覆盖）
messages: Annotated[list, add_messages]

# 没有 Annotated 的字段：直接覆盖
route: str | None   # 节点返回 {"route": "tools"} → 直接替换

# --- add_messages vs operator.add 对比 ---
# operator.add：同 id 消息会重复
#   [msg_a, msg_b] + [msg_b_updated]  →  [msg_a, msg_b, msg_b_updated]
#
# add_messages：同 id 消息原地替换（支持消息编辑）
#   [msg_a, msg_b] + [msg_b_updated]  →  [msg_a, msg_b_updated]
#
# 规则：消息列表用 add_messages，普通追加列表用 operator.add

# --- 框架如何读取 metadata（原理） ---
import typing

def get_reducer(field_type):
    if typing.get_origin(field_type) is Annotated:
        args = typing.get_args(field_type)
        return args[1] if len(args) > 1 else None
    return None

FieldType = Annotated[list, add_messages]
print(get_reducer(FieldType))  # <function add_messages at 0x...>
```

**关键理解**：`Annotated[list, add_messages]` 的运行时类型还是 `list`，`add_messages` 只是附加信息，LangGraph 在 `StateGraph` 编译时读取它来决定如何 merge 状态。

---

### 2.4 Protocol（结构子类型 / 鸭子类型）

**是什么**：Python 版的"鸭子类型接口"——不要求继承，只要有相同的方法/属性就算"实现了"这个接口。

**Java 对比**：

| | Java 接口 | Python Protocol |
|---|---|---|
| 实现方式 | 必须 `implements Interface` | 只需有对应方法，无需声明 |
| 编译期检查 | 编译器强制 | mypy/pyright 静态检查 |
| 运行时检查 | `instanceof` | 需加 `@runtime_checkable` |
| 接入第三方 | 必须写 Adapter | 直接传入，零适配 |

```python
from typing import Protocol, runtime_checkable

# 定义协议（接口）
class EnterpriseTool(Protocol):
    def invoke(self, args) -> str: ...
    name: str

# 实现时不需要 implements！只要有相应方法就满足协议
class TicketLookupTool:
    name = "ticket_lookup"
    def invoke(self, args) -> str:
        return "ticket info"

class SlackNotifyTool:         # 第三方库，无法修改继承结构
    name = "slack_notify"
    def invoke(self, args) -> str:
        return "sent"

# 函数接受协议类型——任何有这两个成员的对象都行
def run_tool(tool: EnterpriseTool, args: dict) -> str:
    return tool.invoke(args)

run_tool(TicketLookupTool(), {})   # 合法
run_tool(SlackNotifyTool(), {})    # 合法（无需包装）

# --- runtime_checkable：让 isinstance 支持协议检查 ---
@runtime_checkable
class HasMessages(Protocol):
    messages: list

class MyState:
    def __init__(self):
        self.messages = []

print(isinstance(MyState(), HasMessages))  # True
# 注意：只检查成员是否存在，不验证类型签名

# --- Protocol vs ABC（抽象基类）---
# 用 Protocol：不需要共享实现，接入第三方，插件系统
# 用 ABC：需要共享基类的具体实现逻辑（如公共方法）

# --- LangChain mock 测试场景 ---
class FakeLLM:
    def invoke(self, messages: list) -> str:
        return "fake response"
    
    def ainvoke(self, messages: list):
        import asyncio
        return asyncio.coroutine(lambda: "fake async response")()

# 只要有 invoke/ainvoke，不需要继承任何 LangChain 基类
```

**一句话**：Protocol 是"结构兼容"，Java 接口是"声明兼容"。Protocol 先检查形状，不问出身。

---

### 2.5 Generic 泛型

**是什么**：参数化类型，让类/函数对类型保持通用。

```python
from typing import TypeVar, Generic

T = TypeVar('T')

# 泛型类——Java: class Box<T>
class Box(Generic[T]):
    def __init__(self, value: T) -> None:
        self.value = value
    
    def get(self) -> T:
        return self.value

int_box: Box[int] = Box(42)
str_box: Box[str] = Box("hello")

# 泛型函数
def first(items: list[T]) -> T:
    return items[0]

# --- 实用场景：Result 类型（避免用异常控制正常流程）---
from dataclasses import dataclass

@dataclass
class Ok(Generic[T]):
    value: T

@dataclass
class Err:
    error: str

def safe_call_llm(prompt: str) -> Ok[str] | Err:
    try:
        result = llm.invoke(prompt)
        return Ok(result)
    except Exception as e:
        return Err(str(e))

result = safe_call_llm("hello")
match result:           # Python 3.10+ match 语句
    case Ok(value=v):
        print(f"Response: {v}")
    case Err(error=e):
        print(f"Failed: {e}")
```

---

### 2.6 dataclass

**一句话：** `@dataclass` 是 Python 内置的**数据类装饰器**，作用是根据你在类里写的类型注解，自动帮你生成一堆样板方法（主要是 `__init__`、`__repr__`、`__eq__`），省得手写。

**没有它时你要手写：**

```python
class TokenBudgetAllocator:
    def __init__(self, max_tokens: int, overlap: int, doc_type: str):
        self.max_tokens = max_tokens
        self.overlap = overlap
        self.doc_type = doc_type

    def __repr__(self):
        return f"TokenBudgetAllocator(max_tokens={self.max_tokens!r}, ...)"
```

**加上 `@dataclass` 后：**

```python
from dataclasses import dataclass

@dataclass
class TokenBudgetAllocator:
    max_tokens: int
    overlap: int
    doc_type: str
```

**自动生成的等价内容：**

| 方法       | 作用                                                         |
| ---------- | ------------------------------------------------------------ |
| `__init__` | 按声明顺序把参数赋值给属性（`self.max_tokens = max_tokens` 等） |
| `__repr__` | 调试时打印 `TokenBudgetAllocator(max_tokens=400, overlap=80, doc_type='charter')`，好看好排查 |
| `__eq__`   | 两个实例属性全相等就认为相等，可直接 `==` 比较               |

**几个常用参数：**

- `@dataclass(frozen=True)` —— 实例创建后不可变（类似只读），适合当配置对象
- `@dataclass(order=True)` —— 自动生成 `<` / `>` 排序方法
- `@dataclass(slots=True)` —— 用 `__slots__` 省内存（Python 3.10+）

**跟类型注解的关系：** `@dataclass` 是靠你写的注解 `max_tokens: int` 才知道要生成哪些字段、什么顺序、什么类型的——所以它和 `from __future__ import annotations` 是配合使用的（注解先"存成字符串"不影响 dataclass，因为 dataclass 用的是 `__annotations__` 里的名字和默认值，不是运行时求值）。

**结合你的项目：** 你 `context/` 里那些 `TokenBudgetAllocator`、`SourceType`、`ContextItem` 这类"纯数据载体"的类用 `@dataclass` 最合适——它们不包含复杂逻辑，就是装字段、传数据、打日志，dataclass 让代码量砍掉一大半，且字段增减都集中在一处声明，改起来不容易漏

---

### 2.7 类型注解求值时机

**一句话结论：** `from __future__ import annotations` 这一行就是——"这个文件里所有的类型注解，先别当真算，等要用的时候再算。"下面用你项目里的真实代码讲清楚。

**1. 先认识"类型注解"是什么**

你 `context/types.py` 里这种写法就是类型注解（`冒号后面` / `-> 后面` 的内容）：

```python
drop_reason: str | None = None   # 冒号后面是"注解"
token_cost: int = 0
summary_labels: dict[str, str] = ...
```

它的作用只是**给人和工具看的一张"标签"**：告诉 IDE、mypy、读代码的人"这个字段应该是字符串"。它本来不该影响程序运行。

**2. Python 默认是怎么处理的（坑就在这里）**

Python 有个烦人的默认行为：**在定义函数/类的那一行，它会真的把注解里的类型"算一遍"**，看看这个名字存不存在。比如：

```python
def f(x: FutureClass): ...   # 如果 FutureClass 在后面才定义 → 报 NameError
```

于是会遇到几个经典痛点：

- **前向引用**：类型写在后面，前面用了 → 报错
- **自身引用**：类的方法返回自己这个类 → 报错（类还没定义完）
- **循环导入**：A 模块 import B，B 又用 A 的类型 → 报错
- **低版本兼容**：`str | None` 这种 `|` 写法是 Python 3.10 才支持的，`dict[str, str]` 是 3.9 才支持。你的 `pyproject.toml` 写着支持 `>=3.9`，在 3.9 上这些注解如果被当场求值，直接 `TypeError`

**3. 加上这行之后发生了什么**

```python
from __future__ import annotations
```

加在最顶部后，**所有注解都不再被当场求值，而是被原样"存成一段字符串"**，等真正需要类型的时候（比如 mypy 检查、`get_type_hints()`）才去解析。

带来的效果：

- 上面的坑全没了——前向引用、循环导入随便写，不用把类型包成字符串 `"TreeNode"` 那种丑写法
- 启动更快（少算一大堆类型表达式）
- 运行时永远不会因为"注解里的名字没定义"而崩溃

**4. 代价（很小）**

如果你想**在运行时**拿到真实的类型对象，得显式调 `typing.get_type_hints()` 才会真正去求值；如果类型确实不存在，那一刻才报错。对类型检查工具（mypy / IDE）零影响，它们本来就是静态看的。

**5. 为什么你的 context 目录每个文件都有**

查了你的代码：**backend/app 下 86 个 py 文件里 53 个都带这行**，是项目统一约定，不是 context 特有。而且对 context 这批文件来说它确实有用：

- 全是 `dataclass` + `Enum` + 一堆注解（`SourceType`、`TrustLevel`、`ContextItem`...），注解密度高
- 用了 `str | None`、`dict[str, str]` 这种新语法，但项目要兼容 Python 3.9 → 靠这行兜底
- 文件之间互相 import（`config.py` 引 `trimming.py`），以后想互相引用类型也安全

**一句话总结：** 它是一行"防御性、懒加载"的声明——**让注解只当标签，不当定时炸弹。** 属于现代 Python 项目里几乎可以无脑加的标准模板行。

> **顺带一提：** Python 3.14 起，注解默认就是"延迟求值"了（PEP 649 / 749），那时候这行可以不用写；但为了兼容 3.9 / 3.10，现在保留是合理的。

## 3. 装饰器

### 3.1 装饰器是什么（从函数对象说起）

**核心前提**：Python 里函数是一等对象——可以赋值给变量、作为参数传递、作为返回值。装饰器本质上就是"接受函数、返回函数的函数"。

**Java 对比**：

```text
Java 注解：通常只是声明元数据，框架后续扫描处理（编译期/运行时反射）。
Python 装饰器：函数定义时立即执行一段代码，可以直接包装、替换或注册原函数。
```

所以 Python 装饰器不只是"标记"——`@decorator` 等价于 `func = decorator(func)`，是真正运行的代码。

```python
# 函数是对象，可以赋值和传递
def greet(name: str) -> str:
    return f"Hello, {name}"

say_hello = greet           # 赋值给变量
say_hello("Alice")          # Hello, Alice

def apply(func, value):
    return func(value)

apply(greet, "Bob")         # Hello, Bob

# 作为返回值——这是装饰器的本质
def make_greeter(prefix: str):
    def greeter(name: str) -> str:
        return f"{prefix}, {name}"
    return greeter

hello = make_greeter("Hello")
hi    = make_greeter("Hi")
hello("Alice")  # Hello, Alice
hi("Bob")       # Hi, Bob
```

---

### 3.2 函数装饰器

**`@decorator` 是语法糖，等价于 `func = decorator(func)`。**

```python
import time
import functools

def timer(func):
    @functools.wraps(func)          # 保留原函数元信息（见 3.5）
    def wrapper(*args, **kwargs):   # *args/**kwargs 透传所有参数
        start = time.perf_counter()
        result = func(*args, **kwargs)
        elapsed = time.perf_counter() - start
        print(f"{func.__name__} took {elapsed:.4f}s")
        return result
    return wrapper

# @timer 等价于：call_llm = timer(call_llm)
@timer
def call_llm(prompt: str) -> str:
    time.sleep(0.1)
    return "response"

call_llm("hello")  # call_llm took 0.1003s

# --- 多个装饰器的执行顺序（从下往上应用）---
# 等价于：my_func = log(validate(my_func))
@log
@validate
def my_func():
    print("Running")

# 调用时执行顺序：log → validate → my_func → validate 返回 → log 返回
```

---

### 3.3 带参数的装饰器

**是什么**：返回装饰器的函数——多一层嵌套。`@retry(max_attempts=3)` 先调用 `retry(3)` 返回装饰器，再用装饰器包装函数。

```python
import functools, time

def retry(max_attempts: int = 3, delay: float = 1.0):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    if attempt < max_attempts - 1:
                        time.sleep(delay)
            raise last_error
        return wrapper
    return decorator

@retry(max_attempts=3, delay=0.5)
def unstable_api_call(url: str) -> dict:
    import random
    if random.random() < 0.7:
        raise ConnectionError("Network error")
    return {"status": "ok"}

# --- LangChain 的 @tool 就是这个模式（简化版原理）---
def tool(name=None, description=""):
    def decorator(func):
        func._tool_name = name or func.__name__
        func._description = description or func.__doc__ or ""
        
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)
        
        wrapper._tool_name = func._tool_name
        wrapper._description = func._description
        return wrapper
    
    # 支持 @tool（无括号）和 @tool(name="...")（有括号）两种写法
    if callable(name):      # @tool 无括号时，name 实际上是被装饰的函数
        actual_func = name
        name = None
        return decorator(actual_func)
    
    return decorator

@tool
def search_web(query: str) -> str:
    """Search the web for information."""
    return f"Results for: {query}"

@tool(name="db_query", description="Query the database")
def query_db(sql: str) -> list:
    return []
```

---

### 3.4 类装饰器

**方式一**：用函数装饰类（接受类、返回新的可调用对象）。

```python
def singleton(cls):
    instances = {}
    
    @functools.wraps(cls)
    def get_instance(*args, **kwargs):
        if cls not in instances:
            instances[cls] = cls(*args, **kwargs)
        return instances[cls]
    
    return get_instance

@singleton
class LLMClient:
    def __init__(self):
        print("Initializing...")   # 只打印一次
    
    def invoke(self, prompt: str) -> str:
        return "response"

a = LLMClient()  # Initializing...
b = LLMClient()  # 不打印
print(a is b)    # True
```

**方式二**：用类实现装饰器（有状态的装饰器，通过 `__call__` 变成可调用对象）。

```python
class RateLimit:
    def __init__(self, calls_per_second: int):
        self.min_interval = 1.0 / calls_per_second
        self.last_called = 0.0
    
    def __call__(self, func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            now = time.perf_counter()
            elapsed = now - self.last_called
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)
            self.last_called = time.perf_counter()
            return func(*args, **kwargs)
        return wrapper

@RateLimit(calls_per_second=10)
def api_call(endpoint: str) -> dict:
    return {}
```

---

### 3.5 functools.wraps

**是什么**：保留被包装函数的 `__name__`、`__doc__`、`__module__` 等元信息。

**为什么必须加**：没有 `@wraps`，调试时所有装饰过的函数名都变成 `wrapper`；LangChain 用函数名生成 tool schema 时会直接出错。

```python
def bad_decorator(func):
    def wrapper(*args, **kwargs):  # 没有 @wraps
        return func(*args, **kwargs)
    return wrapper

def good_decorator(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)
    return wrapper

@bad_decorator
def search(query: str) -> str:
    """Search for information."""
    return query

@good_decorator
def better_search(query: str) -> str:
    """Search for information."""
    return query

print(search.__name__)          # wrapper       ← 被覆盖了！
print(search.__doc__)           # None          ← 消失了！
print(better_search.__name__)   # better_search ← 正确
print(better_search.__doc__)    # Search for information. ← 正确
```

---

## 4. 生成器与 yield

### 4.1 迭代器协议

**是什么**：Python 的统一迭代接口——任何实现 `__iter__` 和 `__next__` 的对象都可以被 `for` 循环。

```python
# for 循环的底层展开：
# it = iter(obj)        → 调用 obj.__iter__()
# while True:
#     try: x = next(it) → 调用 it.__next__()
#     except StopIteration: break

class CountUp:
    def __init__(self, limit: int):
        self.limit = limit
        self.current = 0
    
    def __iter__(self):
        return self
    
    def __next__(self):
        if self.current >= self.limit:
            raise StopIteration    # 告诉 for 循环停止
        value = self.current
        self.current += 1
        return value

for x in CountUp(3):
    print(x)   # 0, 1, 2
```

---

### 4.2 生成器函数

**是什么**：包含 `yield` 的函数。调用它**不执行函数体**，而是返回一个生成器对象。每次 `next()` 运行到下一个 `yield` 后挂起，下次从挂起点继续。

**为什么用**：延迟计算（lazy）+ 低内存——不一次性把所有数据放入内存。流式输出就是这个原理。

```python
# 普通函数：一次性返回所有结果（可能占用大量内存）
def get_all_tokens():
    return [f"token_{i}" for i in range(1000000)]

# 生成器：按需计算，内存占用极低
def generate_tokens():
    for i in range(1000000):
        yield f"token_{i}"   # 产出一个，然后挂起

gen = generate_tokens()
print(type(gen))   # <class 'generator'>，不执行函数体

print(next(gen))   # token_0，执行到第一个 yield
print(next(gen))   # token_1，从上次挂起点继续

for token in generate_tokens():
    print(token)
    break  # 随时停止，未计算的不消耗资源

# --- 深入：yield 的暂停/恢复/发送机制 ---
def step_by_step():
    print("Step 1")
    received = yield "first"   # 产出 "first"，挂起，等待 send() 的值
    print(f"Step 2, received={received}")
    yield "second"
    print("Step 3")

gen = step_by_step()

result = next(gen)         # 执行到第一个 yield
# 输出：Step 1
print(f"Got: {result}")   # Got: first

result = gen.send("hello") # 恢复，把 "hello" 赋给 received
# 输出：Step 2, received=hello
print(f"Got: {result}")   # Got: second
```

---

### 4.3 yield from

**是什么**：委托给另一个可迭代对象，简化嵌套生成器。比手动 `for item in sub: yield item` 更简洁，且正确透传 `send()` 和 `throw()`。

```python
# 手动转发
def chain_manual(*iterables):
    for it in iterables:
        for item in it:
            yield item

# yield from：简洁且语义完整
def chain(*iterables):
    for it in iterables:
        yield from it

list(chain([1, 2], [3, 4], [5]))  # [1, 2, 3, 4, 5]

# --- 递归生成器（yield from 的典型场景）---
def flatten(nested):
    """展平任意深度的嵌套列表"""
    for item in nested:
        if isinstance(item, list):
            yield from flatten(item)   # 递归委托
        else:
            yield item

data = [1, [2, [3, 4], 5], [6, 7]]
print(list(flatten(data)))  # [1, 2, 3, 4, 5, 6, 7]

# --- yield from 的完整语义：子生成器的 return 值 ---
def sub_gen():
    yield "from sub"
    return "sub done"    # 生成器的 return 值

def delegating():
    result = yield from sub_gen()   # result 接收子生成器的 return 值
    print(f"sub returned: {result}")
    yield "from outer"
```

---

### 4.4 生成器表达式

**是什么**：和列表推导式语法相似，但用圆括号，返回惰性生成器而不是即时列表。

```python
import sys

# 列表推导式：立即计算，全部存入内存
squares_list = [x**2 for x in range(10000)]
print(sys.getsizeof(squares_list))    # ~85112 bytes

# 生成器表达式：惰性，只存"如何计算"
squares_gen = (x**2 for x in range(10000))
print(sys.getsizeof(squares_gen))     # 104 bytes

# 直接传给函数（外层括号可省略）
total = sum(x**2 for x in range(10))
max_len = max(len(s) for s in ["hello", "world", "!"])

# --- LangGraph 流式处理场景 ---
def extract_text_tokens(stream):
    """从流式输出中过滤并提取文本"""
    return (
        chunk.content
        for chunk in stream
        if hasattr(chunk, 'content') and chunk.content
    )
```

---

### 4.5 在流式输出中的实际用法

```python
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

# graph.stream() 本身就是一个生成器
def run_streaming(graph, query: str, thread_id: str = "demo"):
    config = {"configurable": {"thread_id": thread_id}}
    
    # 每次 yield 是一个节点执行后的完整 state（stream_mode="values"）
    for event in graph.stream(
        {"messages": [HumanMessage(content=query)]},
        config=config,
        stream_mode="values"
    ):
        if "messages" in event:
            last = event["messages"][-1]
            if isinstance(last, AIMessage) and last.content:
                print(f"AI: {last.content}")
            elif isinstance(last, ToolMessage):
                print(f"Tool: {last.content[:80]}...")

# 更细粒度：token 级流式（stream_mode="messages"）
def token_stream(graph, query: str):
    config = {"configurable": {"thread_id": "token-demo"}}
    
    for msg_chunk, metadata in graph.stream(
        {"messages": [HumanMessage(content=query)]},
        config=config,
        stream_mode="messages"
    ):
        if msg_chunk.content:
            yield msg_chunk.content    # 再次 yield，调用方也能流式处理

# 调用方：
for token in token_stream(graph, "hello"):
    print(token, end="", flush=True)
```

---

## 5. 异步编程

### 5.1 为什么需要异步

**核心问题**：LLM API 调用是 I/O 密集型——大部分时间在等待网络响应，CPU 在"空转"。

```
同步（串行）：
[LLM call 1: 2s] [LLM call 2: 2s] [LLM call 3: 2s]  →  总耗时 6s

异步（并发）：
[LLM call 1: 2s]
[LLM call 2: 2s]  ← 同时发起
[LLM call 3: 2s]  ← 同时发起
→  总耗时 ~2s
```

**Java 对比**：Java 的异步是多线程（`CompletableFuture`）。Python 的 `asyncio` 是**单线程事件循环**——协程切换，不是线程切换。

- 适合：I/O 密集（网络请求、数据库、文件）
- 不适合：CPU 密集（用 `ProcessPoolExecutor`）

---

### 5.2 async/await 基础

```python
import asyncio

# async def 定义协程函数——调用它返回协程对象，不执行！
async def fetch_llm(prompt: str) -> str:
    await asyncio.sleep(1)     # 让出控制权，等待期间事件循环可运行其他协程
    return f"Response to: {prompt}"

# 直接调用不执行：
coro = fetch_llm("hello")
print(type(coro))   # <class 'coroutine'>

# 执行协程的方式：
# 1. asyncio.run()——程序入口，启动事件循环
asyncio.run(fetch_llm("hello"))

# 2. await——在另一个 async 函数内等待
async def main():
    result = await fetch_llm("hello")   # 等待完成，让出控制权给其他协程
    print(result)

asyncio.run(main())

# --- 同步 vs 异步调用规则 ---
# 同步函数里调用异步：必须用 asyncio.run()（但如果已在事件循环里会报错）
# 异步函数里调用异步：必须 await
# 异步函数里调用同步：直接调用（但阻塞的同步函数会卡住整个事件循环）
```

---

### 5.3 asyncio 事件循环与 Task

```python
import asyncio

# 直接 await：顺序执行（串行）
async def sequential():
    r1 = await fetch_llm("q1")  # 等 1s
    r2 = await fetch_llm("q2")  # 再等 1s
    # 总共 2s

# create_task：把协程提交给事件循环，立即调度（并发）
async def concurrent():
    task1 = asyncio.create_task(fetch_llm("q1"))  # 立即开始调度
    task2 = asyncio.create_task(fetch_llm("q2"))  # 立即开始调度
    
    r1 = await task1   # 等待完成（可能已经完成了）
    r2 = await task2
    # 总共 ~1s

# 带超时的等待
async def with_timeout():
    try:
        result = await asyncio.wait_for(fetch_llm("slow"), timeout=0.5)
    except asyncio.TimeoutError:
        result = "timeout fallback"
    return result
```

---

### 5.4 并发模式：gather / TaskGroup

```python
import asyncio

# gather：同时运行多个协程，等所有完成，结果顺序与输入一致
async def parallel_llm_calls():
    prompts = ["summarize", "translate", "analyze"]
    results = await asyncio.gather(*[fetch_llm(p) for p in prompts])
    # results = [r1, r2, r3]
    return results

# gather 的错误处理
async def gather_with_errors():
    results = await asyncio.gather(
        fetch_llm("q1"),
        fetch_llm("q2"),
        return_exceptions=True   # 默认 False：任一失败则全部取消
    )
    for r in results:
        if isinstance(r, Exception):
            print(f"Failed: {r}")

# TaskGroup（Python 3.11+，推荐）：任一失败 → 取消其余，重新抛出
async def task_group_example():
    async with asyncio.TaskGroup() as tg:
        tasks = [tg.create_task(fetch_llm(p)) for p in ["q1", "q2", "q3"]]
    # 所有任务完成后才到这里
    return [t.result() for t in tasks]

# --- 实际场景：多 Agent 并行 ---
async def multi_agent(query: str):
    async def ask_expert(role: str) -> dict:
        await asyncio.sleep(0.5)   # 实际是 await llm.ainvoke(...)
        return {"role": role, "answer": f"{role}'s view"}
    
    return await asyncio.gather(*[
        ask_expert(r) for r in ["analyst", "critic", "synthesizer"]
    ])
```

---

### 5.5 异步生成器与流式

**是什么**：`async def` + `yield` = 异步生成器，用 `async for` 消费。LangChain 的 `astream()` 就是这个。

```python
import asyncio

# 异步生成器
async def stream_tokens(prompt: str):
    words = f"Response to {prompt}".split()
    for word in words:
        await asyncio.sleep(0.1)    # 模拟网络延迟
        yield word + " "

# 消费：async for
async def print_stream():
    async for token in stream_tokens("hello"):
        print(token, end="", flush=True)

# LangChain 真实场景
async def langchain_stream(llm, messages: list):
    async for chunk in llm.astream(messages):   # astream() 是异步生成器
        if chunk.content:
            yield chunk.content    # 再次 yield，继续流式传递
```

---

### 5.6 同步代码调用异步代码

这是最常见的痛点，尤其在 LangGraph 节点函数里。

```python
import asyncio

# 场景 1：纯同步环境（没有运行中的事件循环）
def sync_main():
    result = asyncio.run(fetch_llm("prompt"))  # 新建事件循环，运行完关闭
    return result

# 场景 2：已经在事件循环里（Jupyter、某些 web 框架）
# asyncio.run() 会报错："cannot run nested event loop"
# 解决方案：nest_asyncio
import nest_asyncio
nest_asyncio.apply()   # 允许嵌套事件循环，之后可以用 asyncio.run()

# 场景 3：推荐方式——LangGraph 节点直接写成 async
async def async_agent_node(state: dict) -> dict:
    response = await llm.ainvoke(state["messages"])
    return {"messages": [response]}
# LangGraph 支持 async 节点，图的 invoke 也需要改成 ainvoke

# 场景 4：在事件循环里运行阻塞的同步代码
async def call_blocking_sync():
    loop = asyncio.get_event_loop()
    # 把阻塞函数放到线程池执行，不阻塞事件循环
    result = await loop.run_in_executor(None, some_blocking_sync_func, "arg")
    return result
```

---

## 6. 上下文管理器

### 6.1 with 语句的本质

**是什么**：保证资源在使用完毕后一定被清理（即使发生异常），本质是调用 `__enter__` 和 `__exit__`。

**Java 对比**：类似 try-with-resources（`AutoCloseable`），但更灵活——不只是关闭资源，可以做任何"进入/退出"逻辑。

```python
# with 语句等价展开：
# cm = expr
# target = cm.__enter__()
# try:
#     body
# except:
#     if not cm.__exit__(*sys.exc_info()):  # 返回 True 吞异常，False 重新抛出
#         raise
# else:
#     cm.__exit__(None, None, None)

# 文件操作（最常见场景）
with open("graph.png", "wb") as f:
    f.write(graph_png)
# 离开 with 块自动关闭文件，等价于：
# f = open("graph.png", "wb")
# try:    f.write(graph_png)
# finally: f.close()

# 自定义上下文管理器
class Timer:
    def __enter__(self):
        import time
        self.start = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        import time
        print(f"Elapsed: {time.perf_counter() - self.start:.4f}s")
        return False  # 不吞异常

with Timer() as t:
    time.sleep(0.1)
# 即使抛异常，__exit__ 也会被调用
```

---

### 6.2 contextlib 实用工具

```python
from contextlib import contextmanager, asynccontextmanager, suppress
import os

# contextmanager：用生成器实现上下文管理器（比写类简洁）
@contextmanager
def managed_connection(url: str):
    conn = create_connection(url)
    try:
        yield conn          # yield 的值是 as 子句接收的值
    finally:
        conn.close()        # 无论是否异常都执行

with managed_connection("db://localhost") as conn:
    conn.execute("SELECT 1")

# asynccontextmanager：异步版本
@asynccontextmanager
async def async_session():
    session = await create_async_session()
    try:
        yield session
    finally:
        await session.close()

async def query():
    async with async_session() as session:
        return await session.fetch("SELECT 1")

# suppress：静默忽略指定异常（替代 try/except: pass）
with suppress(FileNotFoundError):
    os.remove("maybe_nonexistent.txt")

# --- LangGraph 节点追踪场景 ---
@contextmanager
def trace_node(name: str):
    import time
    print(f"[TRACE] → {name}")
    start = time.perf_counter()
    try:
        yield
        print(f"[TRACE] ✓ {name} ({time.perf_counter()-start:.3f}s)")
    except Exception as e:
        print(f"[TRACE] ✗ {name} FAILED: {e}")
        raise

def my_node(state: dict) -> dict:
    with trace_node("my_node"):
        return {"result": "done"}
```

---

## 7. 闭包与高阶函数

### 7.1 闭包

**是什么**：内层函数"记住"定义时所在作用域的变量，即使外层函数已经返回。

```python
# 闭包：内层函数捕获外层变量
def make_counter(start: int = 0):
    count = start  # 被内层函数捕获
    
    def increment(step: int = 1) -> int:
        nonlocal count   # 声明要修改外层变量（不加 nonlocal 只能读）
        count += step
        return count
    
    return increment

counter = make_counter(10)
counter()    # 11
counter()    # 12
counter(5)   # 17

counter2 = make_counter(0)
counter2()   # 1  ← 独立于 counter，各自有独立的 count

# --- 闭包在 Agent 配置中的典型用法：工厂函数 ---
def make_llm_node(model_name: str, temperature: float = 0.7):
    """返回带特定配置的节点函数，model_name/temperature 被闭包捕获"""
    
    def node(state: dict) -> dict:
        llm = ChatLLM(model=model_name, temperature=temperature)
        response = llm.invoke(state["messages"])
        return {"messages": [response]}
    
    node.__name__ = f"node_{model_name}"
    return node

fast_node  = make_llm_node("kimi-k2.6", temperature=0.0)
smart_node = make_llm_node("kimi-k2.6", temperature=0.7)

graph.add_node("fast",  fast_node)
graph.add_node("smart", smart_node)
```

---

### 7.2 高阶函数与 functools.partial

#### functools.partial：固定部分参数

**是什么**：预先固定函数的部分参数，生成新的可调用对象。

**为什么用**：LangGraph 节点要求签名是 `node(state)`，而通用函数可能有更多参数。`partial` 是比手写 wrapper 更优雅的适配方式。

```python
from functools import partial, reduce

# 原函数：三个参数
def agent_node(state, agent, name: str) -> dict:
    response = agent.invoke(state["messages"])
    return {"messages": [response], "sender": name}

# 固定 agent 和 name，得到只需 state 的节点函数
research_node = partial(agent_node, agent=research_agent, name="Researcher")
chart_node    = partial(agent_node, agent=chart_agent,    name="chart_generator")

# LangGraph 注册时拿到的已经是"适配好签名"的节点函数
graph.add_node("Researcher", research_node)
graph.add_node("chart_generator", chart_node)

# 调用时：research_node(state) 等价于 agent_node(state, research_agent, "Researcher")

# Java 类比：
# Function<AgentState, Map<String, Object>> researchNode =
#     state -> agentNode(state, researchAgent, "Researcher");

# --- partial vs 闭包的选择 ---
# partial：函数已有，只是固定参数——更简洁
# 闭包：需要额外初始化逻辑（如创建 LLM 对象）——更灵活

# --- 其他高阶函数 ---
numbers = [1, 2, 3, 4, 5, 6]

# map / filter——推荐用列表推导式替代，更 Pythonic
squares = [x**2 for x in numbers]          # 而不是 list(map(lambda x: x**2, numbers))
evens   = [x for x in numbers if x % 2 == 0]

# reduce：折叠（累积）
total = reduce(lambda acc, x: acc + x, numbers)  # 21

# 函数组合
def compose(*functions):
    """从右到左：compose(f, g)(x) = f(g(x))"""
    def composed(x):
        for func in reversed(functions):
            x = func(x)
        return x
    return composed

normalize = compose(str.lower, str.strip)
normalize("  Hello World  ")  # "hello world"
```

---

## 8. 特殊方法（Dunder Methods）

**是什么**：Python 协议的实现机制——通过定义 `__xxx__` 方法，让自定义类与内置语法、操作符配合。

**关键洞察**：Python 的语法糖几乎都是协议的具体化：`for` 是迭代器协议，`with` 是上下文管理器协议，`await` 是可等待协议，`+` 是 `__add__` 方法。

```python
from typing import Iterator

class MessageHistory:
    def __init__(self):
        self._messages: list[dict] = []
    
    def __len__(self) -> int:
        return len(self._messages)

    def __getitem__(self, index: int | slice) -> dict | list:
        return self._messages[index]

    def __setitem__(self, index: int, value: dict) -> None:
        self._messages[index] = value

    def __delitem__(self, index: int) -> None:
        del self._messages[index]

    def __iter__(self) -> Iterator[dict]:
        return iter(self._messages)

    def __contains__(self, msg: dict) -> bool:
        return msg in self._messages

    def __repr__(self) -> str:   # repr()——开发者视图，用于调试
        return f"MessageHistory({len(self._messages)} messages)"

    def __str__(self) -> str:    # str() / print()——用户视图
        return "\n".join(f"{m['role']}: {m['content']}" for m in self._messages)

    def __add__(self, other: 'MessageHistory') -> 'MessageHistory':
        new = MessageHistory()
        new._messages = self._messages + other._messages
        return new

    def __bool__(self) -> bool:  # if history:
        return len(self._messages) > 0

    def __call__(self, msg: dict) -> 'MessageHistory':   # history(msg)
        self._messages.append(msg)
        return self   # 链式调用

history = MessageHistory()
history({"role": "user", "content": "hello"})
history({"role": "assistant", "content": "hi"})

len(history)      # 2
history[0]        # {'role': 'user', ...}
bool(history)     # True
repr(history)     # MessageHistory(2 messages)

# --- __getattr__：属性访问钩子（只在属性不存在时调用）---
class LazyConfig:
    """从环境变量惰性加载配置"""
    def __init__(self):
        self._cache = {}
    
    def __getattr__(self, name: str):
        if name.startswith('_'):
            raise AttributeError(name)
        import os
        value = os.getenv(name.upper())
        if value is None:
            raise AttributeError(f"Config '{name}' not set")
        self._cache[name] = value
        return value

config = LazyConfig()
print(config.moonshot_api_key)   # 从 MOONSHOT_API_KEY 环境变量读取
```

---

## 9. 综合案例：从零理解 LangGraph 状态流

把前面所有知识点串起来，完整解析 LangGraph 的核心机制。

```python
"""
本例涵盖：
TypedDict + Annotated（状态定义）
装饰器（工具定义）
闭包（工厂函数）
生成器（流式消费）
async/await（异步节点）
上下文管理器（资源/追踪）
"""

from typing import TypedDict, Annotated, Literal
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from langchain_core.tools import tool

# ============================================================
# 1. 状态定义（TypedDict + Annotated）
# ============================================================
class AgentState(TypedDict):
    # Annotated[list, add_messages]：reducer 是 add_messages（追加并去重）
    messages: Annotated[list, add_messages]
    
    # 无 Annotated 的字段：直接覆盖语义
    intent: str | None
    risk_level: Literal["low", "medium", "high"] | None

# ============================================================
# 2. 工具定义（装饰器 + 闭包）
# ============================================================
def make_search_tool(max_results: int = 5):
    """工厂函数：闭包捕获 max_results"""
    
    @tool
    def search(query: str) -> str:
        """Search the web for information about the query."""
        return f"Top {max_results} results for: {query}"   # 闭包变量
    
    return search

search_tool = make_search_tool(max_results=3)

# ============================================================
# 3. 节点函数（sync 或 async 都支持）
# ============================================================
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(model="gpt-4o-mini")
llm_with_tools = llm.bind_tools([search_tool])

def agent_node(state: AgentState) -> dict:
    """
    节点函数：接收完整 state，返回部分更新
    - messages 字段：add_messages 追加
    - intent 字段：直接覆盖
    """
    response = llm_with_tools.invoke(state["messages"])
    intent = "tool_use" if response.tool_calls else "direct_response"
    
    return {
        "messages": [response],
        "intent": intent,
    }

# 异步版本（生产推荐）
async def async_agent_node(state: AgentState) -> dict:
    response = await llm_with_tools.ainvoke(state["messages"])
    return {"messages": [response]}

# ============================================================
# 4. 路由函数（纯函数，无副作用）
# ============================================================
def route_after_agent(state: AgentState) -> Literal["tools", "__end__"]:
    last = state["messages"][-1]
    if hasattr(last, "tool_calls") and last.tool_calls:
        return "tools"
    return "__end__"

# ============================================================
# 5. 构建图
# ============================================================
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.memory import MemorySaver

def build_graph():
    builder = StateGraph(AgentState)
    
    builder.add_node("agent", agent_node)
    builder.add_node("tools", ToolNode([search_tool]))
    
    builder.set_entry_point("agent")
    builder.add_conditional_edges("agent", route_after_agent, {
        "tools": "tools",
        "__end__": END,
    })
    builder.add_edge("tools", "agent")
    
    return builder.compile(checkpointer=MemorySaver())

graph = build_graph()

# ============================================================
# 6. 流式运行（生成器消费）
# ============================================================
def run_streaming(query: str, thread_id: str = "demo"):
    config = {"configurable": {"thread_id": thread_id}}
    
    # graph.stream() 是生成器——惰性，每次 yield 一个节点执行后的 state
    for event in graph.stream(
        {"messages": [HumanMessage(content=query)]},
        config=config,
        stream_mode="values"
    ):
        if "messages" in event:
            last = event["messages"][-1]
            if isinstance(last, AIMessage) and last.content:
                print(f"AI: {last.content}")
            elif isinstance(last, ToolMessage):
                print(f"Tool: {last.content[:80]}...")

# Token 级流式
def token_stream(query: str):
    config = {"configurable": {"thread_id": "token-demo"}}
    for chunk, metadata in graph.stream(
        {"messages": [HumanMessage(content=query)]},
        config=config,
        stream_mode="messages"
    ):
        if chunk.content:
            yield chunk.content   # 生成器：调用方也能流式处理

# ============================================================
# 7. Human-in-the-loop（暂停/恢复）
# ============================================================
def run_with_approval(query: str):
    config = {"configurable": {"thread_id": "approval"}}
    
    # interrupt_before：在 tools 节点前自动暂停
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.graph import StateGraph
    
    graph_hil = StateGraph(AgentState)
    # ... 和上面一样构建 ...
    graph_hil = graph_hil.compile(
        checkpointer=MemorySaver(),
        interrupt_before=["tools"]
    )
    
    # 第一次运行：在工具调用前暂停
    for event in graph_hil.stream(
        {"messages": [HumanMessage(content=query)]},
        config=config
    ):
        pass  # 消费事件直到暂停
    
    # 检查待执行的工具调用
    state = graph_hil.get_state(config)
    pending = state.values["messages"][-1].tool_calls
    print(f"Pending tool calls: {pending}")
    
    if input("Approve? (y/n): ") == "y":
        # None 表示从断点继续，不修改 state
        for event in graph_hil.stream(None, config):
            pass

# ============================================================
# 入口守卫
# ============================================================
if __name__ == "__main__":
    run_streaming("What's the latest news about LangGraph?")
```

---

## 附录：快速查阅表

### 类型标注

| 写法 | 含义 |
|------|------|
| `x: int` | 整数 |
| `x: str \| None` | 字符串或 None |
| `x: list[str]` | 字符串列表 |
| `x: dict[str, int]` | 字符串键、整数值 |
| `x: tuple[str, int]` | 固定结构元组 |
| `x: Annotated[list, fn]` | 带 reducer 的 list |
| `x: Literal["a", "b"]` | 只能是这几个字面值 |
| `x: TypeVar('T')` | 泛型类型变量 |
| `x: Any` | 放弃类型检查 |

### 装饰器

| 写法 | 何时用 |
|------|--------|
| `@decorator` | 无参数装饰器 |
| `@decorator()` | 带参数装饰器（工厂返回装饰器） |
| `@functools.wraps(func)` | 在 wrapper 内保留元信息，**必写** |
| `@dataclass` | 自动生成 `__init__`/`__repr__`/`__eq__` |
| `@dataclass(frozen=True)` | 不可变 dataclass，可做字典键 |
| `@property` | 方法变属性访问 |
| `@classmethod` | 类方法（第一个参数是类） |
| `@staticmethod` | 静态方法（无 self/cls） |
| `@runtime_checkable` | 让 Protocol 支持 isinstance |

### async/await

| 写法 | 含义 |
|------|------|
| `async def f()` | 定义协程函数 |
| `await coro` | 等待协程（只能在 async 内） |
| `asyncio.run(coro)` | 程序入口，启动事件循环 |
| `asyncio.create_task(coro)` | 创建并发 Task（立即调度） |
| `await asyncio.gather(*coros)` | 并发运行，等全部完成 |
| `await asyncio.wait_for(coro, timeout)` | 带超时的等待 |
| `async for x in aiter` | 遍历异步迭代器 |
| `async with cm` | 异步上下文管理器 |
| `async def f(): yield x` | 异步生成器 |

### 生成器

| 写法 | 含义 |
|------|------|
| `yield x` | 产出值，挂起函数 |
| `x = yield` | 产出 None，接收 send() 的值 |
| `yield from iterable` | 委托给子迭代器 |
| `(x for x in it)` | 生成器表达式（惰性） |
| `next(gen)` | 运行到下一个 yield |
| `gen.send(value)` | 恢复并传入值 |
| `gen.throw(exc)` | 在 yield 处抛出异常 |

### 常用 dunder 方法

| 方法 | 触发时机 |
|------|---------|
| `__init__` | 实例化 |
| `__repr__` | `repr(obj)` / 调试 |
| `__str__` | `str(obj)` / `print()` |
| `__len__` | `len(obj)` |
| `__getitem__` | `obj[key]` |
| `__iter__` | `for x in obj` |
| `__contains__` | `x in obj` |
| `__enter__` / `__exit__` | `with obj` |
| `__call__` | `obj()` |
| `__add__` | `obj + other` |
| `__bool__` | `if obj` |
| `__getattr__` | 访问不存在的属性 |

---

> **核心原则**：Python 的语法糖几乎都是协议（protocol）的具体化——`for` 是迭代器协议，`with` 是上下文管理器协议，`await` 是可等待协议，`+` 是 `__add__` 方法。理解了这一点，遇到陌生语法就能快速推断其底层机制。
