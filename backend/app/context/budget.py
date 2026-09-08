"""
Token 预算分配器 —— 对应 §10.2.4。

提供分配机制本身，暂不用它在生产路径里真正丢弃可选来源的内容：kimi-k2.6
没有在代码库任何地方登记过真实的模型输入窗口大小，`app/agent/context_budget.py`
此前的注释也明确写着"P3 第一阶段：只统计、不裁剪"——这是问津在没有真实用量数据
支撑之前刻意做出的决定（见 docs/memory-architecture.md 对应章节："先验证问题的
真实程度，再决定投入多少"），不该现在为了推进 §10.2 就编一个没有依据的
model_window 去悄悄丢用户上下文。

自 P0-2 起，`app/config.py` 已登记 `kimi_k2_6_model_window`（保守假设 32768，
OpenRouter 口径），本模块新增 `input_budget_profile()` 把该窗口切分成「可选来源
实际可用的输入预算」，并新增 `estimate_exceeds_window()` 做「估算超窗」判定。
这两者都只做**观测/告警**，不据此静默丢弃用户上下文；真正把 `TokenBudgetAllocator`
接入生产硬裁剪，仍需先完成一次真实 token 用量回放校准（见 §10.2 第 6 步）。
"""
from __future__ import annotations

from dataclasses import dataclass

from app.config import settings
from app.context.types import ContextItem


@dataclass
class InputBudgetProfile:
    """把一个模型输入窗口切分成固定/动态/输出/余量四块（对应 §3.3）。"""

    model_window: int
    output_budget: int
    safety_margin: int
    # 固定指令（system + 真实工具 schema）已占用、不可裁的部分
    fixed_spent: int

    @property
    def optional_input_budget(self) -> int:
        """可选来源（历史/摘要/报告/RAG）实际能分到的输入预算。"""
        return max(self.model_window - self.output_budget - self.safety_margin - self.fixed_spent, 0)


def input_budget_profile(
    *,
    output_budget: int,
    fixed_spent: int = 0,
    model_window: int | None = None,
    safety_margin: int | None = None,
) -> InputBudgetProfile:
    """按 §3.3 分区公式计算可选来源的输入预算。

    `fixed_spent` 是 system prompt 与工具 schema 的 token 估算——它们按业务定义
    不能裁剪（对应 §9.3 默认保留顺序前两项），必须先从窗口里扣掉。
    """
    return InputBudgetProfile(
        model_window=model_window or settings.kimi_k2_6_model_window,
        output_budget=output_budget,
        safety_margin=safety_margin if safety_margin is not None else settings.context_window_safety_margin,
        fixed_spent=max(fixed_spent, 0),
    )


def estimate_exceeds_window(
    *,
    input_tokens: int | None,
    output_budget: int,
    safety_margin: int | None = None,
    model_window: int | None = None,
) -> bool:
    """输入的「估算」token 是否已触犯窗口（含输出预留与安全余量）。

    只用估算值做 True/False 告警；真实是否超窗以服务端 usage 为准。估算失败
    （input_tokens=None）时返回 False，不误报。
    """
    if input_tokens is None:
        return False
    window = model_window or settings.kimi_k2_6_model_window
    margin = safety_margin if safety_margin is not None else settings.context_window_safety_margin
    return input_tokens + output_budget + margin > window


@dataclass
class TokenBudgetAllocator:
    """在给定的可选来源预算内，按调用方传入的优先级顺序逐项分配。

    接入硬裁剪时，调用方应先用 `input_budget_profile()` 算出 `optional_input_budget`
    再交给本对象；分配顺序应由业务优先级（§9.3）决定，而不是列表位置。
    """

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