"""
Token 预算分配器 —— 对应 §10.2.4。

提供分配机制本身，暂不用它在生产路径里真正丢弃可选来源的内容：kimi-k2.6
没有在代码库任何地方登记过真实的模型输入窗口大小，`app/agent/context_budget.py`
此前的注释也明确写着"P3 第一阶段：只统计、不裁剪"——这是问津在没有真实用量数据
支撑之前刻意做出的决定（见 docs/memory-architecture.md 对应章节："先验证问题的
真实程度，再决定投入多少"），不该现在为了推进 §10.2 就编一个没有依据的
model_window 去悄悄丢用户上下文。

这里先把分配逻辑做成可独立测试、随时可以接入的机制；真正在两个 Agent 里打开
硬裁剪，需要先有可信的 model_window/output_budget 数值，留给后续迭代决定。
"""
from __future__ import annotations

from dataclasses import dataclass

from app.context.types import ContextItem


@dataclass
class TokenBudgetAllocator:
    """在给定的可选来源预算内，按调用方传入的优先级顺序逐项分配。"""

    optional_budget: int
    spent: int = 0

    @property
    def remaining(self) -> int:
        return max(self.optional_budget - self.spent, 0)

    def reserve(self, item: ContextItem) -> None:
        """必需来源：全额计入已花费，永不裁剪、永不丢弃（对应 §9.6 必需事实
        缺失应追问而不是静默降级）。"""
        item.included = True
        self.spent += item.token_cost

    def allocate(self, item: ContextItem) -> bool:
        """可选来源：预算够才计入；不够则整体丢弃并记录原因，交给调用方决定
        是否需要提示用户"本轮上下文已降级"。"""
        if item.token_cost <= self.remaining:
            item.included = True
            self.spent += item.token_cost
            return True
        item.included = False
        item.truncated = True
        item.drop_reason = "optional_budget_exhausted"
        return False
