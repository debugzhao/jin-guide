"""
提示词层的确定性评测（deterministic / rule-based grader）。

对应 backend/docs/Agent评测体系调研.md「三、1. 提示词层」的指标表，覆盖大厂做 Agent
评测时常说的这几类 rule-based grader：

  1. Prompt 模板变量能否正常渲染          -> TestPromptTemplateRendering
  2. 模型输出是否满足 JSON Schema         -> TestStructuredOutputSchema
  3. 工具名称和参数是否正确               -> TestToolArgumentCorrectness
  4. 是否发生越权工具调用                 -> TestToolAuthorizationBoundary
  9. 调用次数、token、延迟是否超过限制    -> TestPromptCallBudget

不在本文件覆盖、原因写在对应位置：
  - 「引用 ID 是否真实存在」已经在 test_prompt_security.py 里用
    sanitize_citations/StreamingOutputGuard 覆盖，不重复。
  - 「RAG 是否检索到标准文档」「模拟超时后是否正确降级」放在 test_resilience_graders.py，
    因为它们测的是 CircuitBreaker/rerank 这类弹性组件，和提示词本身无关。
  - 「数据库最终状态是否符合预期」放在 test_school_lookup_db_state.py，需要独立的
    sqlite fixture，不适合和纯 Prompt 断言混在一起。
  - 「Agent 修改的代码能否通过测试」不适用：问津不是代码生成/自动修复类 Agent。
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


# ── 3. 工具名称和参数是否正确 ────────────────────────────────────────────────────

class TestToolArgumentCorrectness:
    """
    intake_chat 的三个查询工具全部要走 Pydantic 白名单校验（extra='forbid' +
    字段级 Field 范围约束），这里补齐此前只覆盖了 lookup_university_score/
    compare_universities 负例、却没覆盖 lookup_subject_requirement 正例的空白，
    并额外验证“默认值/None 字段被正确剔除”这条容易被忽略的行为。
    """

    def test_lookup_university_score_accepts_valid_arguments_and_fills_default_batch(self):
        from app.agent.intake_agent import _validate_tool_arguments

        args, error = _validate_tool_arguments(
            "lookup_university_score",
            json.dumps({"university_name": "郑州大学", "province": "河南"}),
        )

        assert error is None
        assert args == {"university_name": "郑州大学", "province": "河南", "batch": "本科批"}

    def test_lookup_subject_requirement_accepts_valid_arguments_without_major(self):
        """此前只测过这个工具的“未知工具”负例，从未测过它自己的正常参数路径。"""
        from app.agent.intake_agent import _validate_tool_arguments

        args, error = _validate_tool_arguments(
            "lookup_subject_requirement",
            json.dumps({"university_name": "浙江大学"}),
        )

        assert error is None
        assert args == {"university_name": "浙江大学"}

    def test_lookup_subject_requirement_accepts_optional_major_name(self):
        from app.agent.intake_agent import _validate_tool_arguments

        args, error = _validate_tool_arguments(
            "lookup_subject_requirement",
            json.dumps({"university_name": "浙江大学", "major_name": "计算机科学与技术"}),
        )

        assert error is None
        assert args == {"university_name": "浙江大学", "major_name": "计算机科学与技术"}

    def test_compare_universities_accepts_valid_two_way_comparison(self):
        from app.agent.intake_agent import _validate_tool_arguments

        args, error = _validate_tool_arguments(
            "compare_universities",
            json.dumps({"university_names": ["郑州大学", "河南大学"], "province": "河南"}),
        )

        assert error is None
        assert args["university_names"] == ["郑州大学", "河南大学"]
        assert args["batch"] == "本科批"

    def test_lookup_university_score_rejects_empty_university_name(self):
        from app.agent.intake_agent import _validate_tool_arguments

        args, error = _validate_tool_arguments(
            "lookup_university_score",
            json.dumps({"university_name": "", "province": "河南"}),
        )

        assert args is None
        assert error == "工具参数不合法或超出允许范围"

    def test_lookup_subject_requirement_rejects_unknown_field(self):
        from app.agent.intake_agent import _validate_tool_arguments

        args, error = _validate_tool_arguments(
            "lookup_subject_requirement",
            json.dumps({"university_name": "浙江大学", "unexpected_field": True}),
        )

        assert args is None
        assert error == "工具参数不合法或超出允许范围"

    def test_tool_arguments_reject_malformed_json(self):
        from app.agent.intake_agent import _validate_tool_arguments

        args, error = _validate_tool_arguments("lookup_university_score", "{不是合法 JSON")

        assert args is None
        assert error == "工具参数解析失败"

    def test_tool_arguments_reject_non_object_json(self):
        from app.agent.intake_agent import _validate_tool_arguments

        args, error = _validate_tool_arguments("lookup_university_score", "[1, 2, 3]")

        assert args is None
        assert error == "工具参数必须是 JSON 对象"


# ── 4. 是否发生越权工具调用 ──────────────────────────────────────────────────────

class TestToolAuthorizationBoundary:
    """
    intake_agent 暴露给模型的工具集合必须和代码里实际能执行的工具集合完全一致——
    多一个（泄露了未实现的能力）或少一个（校验模型和实现模型不同步）都是缺陷。
    """

    def test_exposed_tool_names_match_intended_surface_exactly(self):
        from app.agent.intake_agent import _TOOL_NAMES

        assert _TOOL_NAMES == {
            "lookup_university_score",
            "lookup_subject_requirement",
            "compare_universities",
            "start_profile_capture",
        }

    def test_every_exposed_tool_has_a_json_schema_with_required_fields(self):
        """暴露给模型的每个工具定义都要有 parameters.required，防止漏写导致模型乱填参数。"""
        from app.agent.intake_agent import _TOOLS

        for tool in _TOOLS:
            fn = tool["function"]
            assert fn["name"], "工具必须有名称"
            assert "parameters" in fn
            # start_profile_capture 是无参信号工具，其余三个都必须声明 required
            if fn["name"] != "start_profile_capture":
                assert fn["parameters"].get("required"), (
                    f"{fn['name']} 缺少 required 声明，模型可能会在必填信息缺失时仍然调用"
                )

    @pytest.mark.asyncio
    async def test_signal_only_tool_cannot_be_executed_as_a_query_tool(self):
        """start_profile_capture 只是触发前端表单的信号，不能被当作数据查询工具真正执行。"""
        from app.agent.intake_agent import _execute_tool_call

        result = await _execute_tool_call("start_profile_capture", "{}")

        assert result["status"] == "ERROR"

    @pytest.mark.asyncio
    async def test_unknown_tool_name_is_rejected_before_execution(self):
        from app.agent.intake_agent import _execute_tool_call

        result = await _execute_tool_call("drop_all_tables", "{}")

        assert result["status"] == "ERROR"
        assert "未知工具" in result["text"]


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
    这条承诺本身就应该被测试锁定，否则未来重构时很容易被悄悄破坏。
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
