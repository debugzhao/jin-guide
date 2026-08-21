"""
提示词层的确定性评测（deterministic / rule-based grader）。

对应 backend/docs/Agent评测体系调研.md「三、1. 提示词层」的指标表：模板契约正确性、
结构化输出契约（各 Prompt 定义里的 output_schema）、调用预算（PromptModelConfig 里
的 max_tokens/timeout_seconds/stream）——这三者都是直接写在 Prompt YAML 定义本身
里的契约，因此归在这一层，而不是"工具与行动层"或"知识检索层"。

  1. Prompt 模板变量能否正常渲染          -> TestPromptTemplateRendering
  2. 模型输出是否满足 JSON Schema         -> TestStructuredOutputSchema
  9. 调用次数、token、延迟是否超过限制    -> TestPromptCallBudget

工具参数校验/越权工具调用属于"工具与行动层"，放在
tests/eval/tool_and_action_layer/test_tool_argument_and_authorization.py，
不在本文件重复。
"""
from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.prompts import prompt_registry
from app.prompts.models import _template_variables


# ── 1. Prompt 模板变量能否正常渲染 ───────────────────────────────────────────────

def _all_prompt_template_pairs() -> list[tuple[str, str]]:
    """(prompt_name, template_name) 的全量组合，覆盖当前登记的全部 7 个 Prompt。"""
    specs = prompt_registry.validate_all()
    return [
        (spec.prompt_name, template_name)
        for spec in specs
        for template_name in spec.templates
    ]


class TestPromptTemplateRendering:
    """
    不手写每个 Prompt 该传哪些变量（容易漏改/写错），而是用 models.py 里同一套
    _template_variables() 反查每个模板实际用到的变量，再供给等量的哑值——
    这样测试永远和模板定义保持同步，模板改了变量也不需要同步改测试。
    """

    @pytest.mark.parametrize("prompt_name,template_name", _all_prompt_template_pairs())
    def test_template_renders_successfully_with_exact_required_variables(
        self, prompt_name, template_name
    ):
        spec = prompt_registry.get(prompt_name)
        required = sorted(_template_variables(spec.templates[template_name]))
        dummy_values = {name: f"__{name}_probe__" for name in required}

        rendered = spec.render(template_name, **dummy_values)

        assert rendered.strip() != ""
        for name, value in dummy_values.items():
            assert value in rendered, (
                f"{prompt_name}@{spec.version}::{template_name} 声明了变量 {name}，"
                "但渲染结果里没有出现对应取值——模板里的占位符和变量名可能没有对上"
            )

    @pytest.mark.parametrize("prompt_name,template_name", _all_prompt_template_pairs())
    def test_template_rejects_missing_or_extra_variable(self, prompt_name, template_name):
        spec = prompt_registry.get(prompt_name)
        required = sorted(_template_variables(spec.templates[template_name]))
        dummy_values = {name: "probe" for name in required}

        if required:
            missing = dict(list(dummy_values.items())[:-1])  # 少传最后一个变量
            with pytest.raises(ValueError, match="缺少变量"):
                spec.render(template_name, **missing)

        extra = {**dummy_values, "__undeclared_variable__": "probe"}
        with pytest.raises(ValueError, match="多余变量"):
            spec.render(template_name, **extra)


# ── 2. 模型输出是否满足 JSON Schema ─────────────────────────────────────────────

class TestStructuredOutputSchema:
    """
    reflection_review 和 report_generation 都要求模型返回结构化 JSON，且都在解析前
    做“去 markdown 代码块围栏”的预处理。这里直接测底层 Pydantic 模型 + 解析函数，
    不经过网络，保持纯粹、确定性。
    """

    def test_reflection_review_output_accepts_valid_shape(self):
        from app.agent.nodes.reflection_agent import ReflectionReviewOutput

        result = ReflectionReviewOutput.model_validate_json(
            '{"passed": true, "feedback": "无需改进", "issues": []}'
        )
        assert result.passed is True
        assert result.issues == []

    def test_reflection_review_output_rejects_extra_field(self):
        from app.agent.nodes.reflection_agent import ReflectionReviewOutput

        with pytest.raises(ValidationError):
            ReflectionReviewOutput.model_validate_json(
                '{"passed": true, "feedback": "ok", "issues": [], "confidence": 0.9}'
            )

    def test_reflection_review_output_rejects_passed_true_with_issues(self):
        """passed=true 却带着 issues 是自相矛盾的结构化输出，必须在 Schema 层面就拒绝。"""
        from app.agent.nodes.reflection_agent import ReflectionReviewOutput

        with pytest.raises(ValidationError):
            ReflectionReviewOutput.model_validate_json(
                '{"passed": true, "feedback": "ok", "issues": ["录取概率极高"]}'
            )

    def test_reflection_review_output_rejects_missing_required_field(self):
        from app.agent.nodes.reflection_agent import ReflectionReviewOutput

        with pytest.raises(ValidationError):
            ReflectionReviewOutput.model_validate_json('{"passed": false}')

    @pytest.mark.asyncio
    async def test_llm_judge_strips_markdown_fence_before_validating(self, monkeypatch):
        """模型经常把 JSON 包在 ```json ... ``` 里，_llm_judge 必须先去围栏再校验。"""
        from unittest.mock import AsyncMock
        from app.agent.nodes import reflection_agent as module

        # _llm_judge 内部会经过 track_prompt_invocation 写审计——这里只关心解析行为，
        # 不应该真的打真实数据库，否则这条"确定性"测试就悄悄变成了依赖 DB 的集成测试。
        monkeypatch.setattr(
            "app.database.async_session_maker",
            lambda: (_ for _ in ()).throw(RuntimeError("db not used in this test")),
        )
        fenced_response = {
            "choices": [
                {
                    "message": {
                        "content": '```json\n{"passed": true, "feedback": "无需改进", "issues": []}\n```'
                    }
                }
            ]
        }
        monkeypatch.setattr(
            module, "call_chat_completion", AsyncMock(return_value=fenced_response)
        )

        result = await module._llm_judge({"plans": []}, [])

        assert result == {"passed": True, "feedback": "无需改进", "issues": []}

    @pytest.mark.asyncio
    async def test_llm_judge_fails_closed_on_malformed_json(self, monkeypatch):
        """模型返回的不是合法 JSON（或不满足 Schema）时，必须 fail closed 而不是当作通过。"""
        from unittest.mock import AsyncMock
        from app.agent.nodes import reflection_agent as module

        monkeypatch.setattr(
            "app.database.async_session_maker",
            lambda: (_ for _ in ()).throw(RuntimeError("db not used in this test")),
        )
        broken_response = {
            "choices": [{"message": {"content": "这不是 JSON，是模型跑题了"}}]
        }
        monkeypatch.setattr(
            module, "call_chat_completion", AsyncMock(return_value=broken_response)
        )

        result = await module._llm_judge({"plans": []}, [])

        assert result["passed"] is False
        assert result["issues"] == ["合规审查服务不可用"]

    def test_report_generation_output_parses_valid_shape_with_markdown_fence(self):
        from app.agent.nodes.report_agent import _parse_llm_reasons

        content = (
            '```json\n'
            '{"reasons": {"1": ["历史录取稳定", "省内211", "多余的第四条会被截断"],'
            ' "2": ["综合评分较高"]}, "condition_commentary": "预算和城市偏好存在张力"}\n'
            '```'
        )

        reasons, commentary = _parse_llm_reasons(content, candidate_count=2)

        assert reasons[1] == ["历史录取稳定", "省内211", "多余的第四条会被截断"]
        assert reasons[2] == ["综合评分较高"]
        assert commentary == "预算和城市偏好存在张力"

    def test_report_generation_output_truncates_reasons_to_three(self):
        from app.agent.nodes.report_agent import _parse_llm_reasons

        content = json.dumps(
            {"reasons": {"1": ["r1", "r2", "r3", "r4", "r5"]}, "condition_commentary": ""}
        )

        reasons, _ = _parse_llm_reasons(content, candidate_count=1)

        assert reasons[1] == ["r1", "r2", "r3"]

    def test_report_generation_output_fails_closed_on_invalid_json(self):
        """解析失败时必须返回确定性的空兜底，而不是抛异常打断报告生成主链路。"""
        from app.agent.nodes.report_agent import _parse_llm_reasons

        reasons, commentary = _parse_llm_reasons("完全不是 JSON 的自由文本", candidate_count=3)

        assert reasons == {}
        assert commentary == ""

    def test_report_generation_output_rejects_extra_field_but_fails_closed(self):
        """Schema 是 extra='forbid'，多余字段会让 model_validate_json 抛错，
        但 _parse_llm_reasons 必须把这类异常吞掉、返回空兜底，而不是向上抛。"""
        from app.agent.nodes.report_agent import _parse_llm_reasons

        content = json.dumps(
            {"reasons": {"1": ["ok"]}, "condition_commentary": "", "extra_field": "not allowed"}
        )

        reasons, commentary = _parse_llm_reasons(content, candidate_count=1)

        assert reasons == {}
        assert commentary == ""

    def test_report_generation_output_skips_non_numeric_keys_but_keeps_valid_ones(self):
        """键不是数字的条目要被静默跳过，不影响其余合法条目正常解析。"""
        from app.agent.nodes.report_agent import _parse_llm_reasons

        content = json.dumps(
            {
                "reasons": {
                    "1": ["合法的理由"],
                    "not_a_number": ["应该被跳过"],
                },
                "condition_commentary": "",
            }
        )

        reasons, _ = _parse_llm_reasons(content, candidate_count=2)

        assert reasons == {1: ["合法的理由"]}

    def test_report_generation_output_fails_closed_when_value_is_not_a_list(self):
        """reasons 的 Schema 是 dict[str, list[str]]，某个候选的值不是 list 时
        整个结构在 Pydantic 层就校验不通过（不是进入循环后才逐条跳过），必须整体 fail closed。"""
        from app.agent.nodes.report_agent import _parse_llm_reasons

        content = json.dumps(
            {"reasons": {"1": "不是 list，应该导致整体解析失败"}, "condition_commentary": ""}
        )

        reasons, commentary = _parse_llm_reasons(content, candidate_count=1)

        assert reasons == {}
        assert commentary == ""


# ── 9. 调用次数、token、延迟是否超过限制 ─────────────────────────────────────────

class TestPromptCallBudget:
    """
    每个 Prompt 的 max_tokens/timeout_seconds 是发布时就该审过的预算上限，这里做
    两类检查：数值本身在合理区间内、且 request_options() 产出的请求体真的带上了
    能让 LiteLLM/LangSmith 统计到用量的字段——预算限制的前提是先能测出真实用量。
    """

    @pytest.mark.parametrize("prompt_name", [
        "intake_chat", "report_conversation", "profile_clarification",
        "report_generation", "reflection_review", "conversation_summary",
        "conversation_title",
    ])
    def test_model_budget_fields_are_within_sane_bounds(self, prompt_name):
        spec = prompt_registry.get(prompt_name)

        assert 0 < spec.model.max_tokens <= 8000, (
            f"{prompt_name} 的 max_tokens={spec.model.max_tokens} 超出预期区间，"
            "确认是否为配置失误（例如误填了 80000）"
        )
        # conversation_summary 跑在 BackgroundTasks 里、不在用户等待的关键路径上
        # （见 CLAUDE.md「建档前聊天」一节），240s 的超时是刻意设置，不是失误。
        assert 0 < spec.model.timeout_seconds <= 300, (
            f"{prompt_name} 的 timeout_seconds={spec.model.timeout_seconds} 超出预期区间"
        )

    @pytest.mark.parametrize("prompt_name", [
        "intake_chat", "report_conversation", "profile_clarification",
        "report_generation", "reflection_review", "conversation_summary",
        "conversation_title",
    ])
    def test_streaming_prompts_request_usage_reporting(self, prompt_name):
        """
        stream=true 时 OpenAI 兼容协议默认不在最后一个 chunk 带 usage，必须显式加
        stream_options.include_usage，否则 token 预算根本无法被统计和监控（见
        app/prompts/models.py::PromptSpec.request_options）。
        """
        spec = prompt_registry.get(prompt_name)
        options = spec.request_options()

        if spec.model.stream:
            assert options.get("stream_options") == {"include_usage": True}
        else:
            assert "stream_options" not in options


# ── 审计写入必须 best-effort，不能反过来拖垮主链路 ───────────────────────────────

class TestPromptInvocationAuditIsBestEffort:
    """
    tracing.py 目前没有任何测试覆盖。它的核心承诺是“审计表故障不能影响用户主链路”，
    这条承诺本身就应该被测试锁定，否则未来重构时很容易被悄悄破坏。放在提示词层，
    因为它包装的正是每一次 Prompt 调用本身（prompt_name/version/hash 都来自 PromptSpec）。
    """

    @pytest.mark.asyncio
    async def test_audit_write_failure_does_not_propagate(self, monkeypatch):
        from app.prompts.tracing import track_prompt_invocation

        def _raise_on_call():
            raise RuntimeError("db connection refused")

        monkeypatch.setattr("app.database.async_session_maker", _raise_on_call)

        spec = prompt_registry.get("conversation_title")
        async with track_prompt_invocation(spec) as invocation:
            assert invocation.spec is spec
        # 走到这里说明 with 块正常退出，_persist_trace 内部吞掉了 DB 异常

    @pytest.mark.asyncio
    async def test_real_exception_inside_the_block_still_propagates(self, monkeypatch):
        """审计失败要吞，但业务逻辑自己的异常绝不能被这层 best-effort 顺手吞掉。"""
        from app.prompts.tracing import track_prompt_invocation

        monkeypatch.setattr(
            "app.database.async_session_maker",
            lambda: (_ for _ in ()).throw(RuntimeError("db also down")),
        )

        spec = prompt_registry.get("conversation_title")
        with pytest.raises(ValueError, match="business failure"):
            async with track_prompt_invocation(spec):
                raise ValueError("business failure")
