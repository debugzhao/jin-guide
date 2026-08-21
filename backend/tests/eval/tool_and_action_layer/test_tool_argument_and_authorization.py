"""
工具与行动层的确定性评测（deterministic / rule-based grader）。

对应 backend/docs/Agent评测体系调研.md「三、5. 工具与行动层」的指标表：参数正确率、
权限遵从/越权行为率。这两类原本和提示词层的测试混在同一个文件里，现在按层拆开——
这里只测 intake_chat 暴露给模型的三个查询工具 + 一个信号工具，本身的参数校验和
授权边界，不涉及 Prompt 模板渲染或结构化输出契约。

  3. 工具名称和参数是否正确  -> TestToolArgumentCorrectness
  4. 是否发生越权工具调用    -> TestToolAuthorizationBoundary

这些工具背后真正查询数据库、返回结果是否符合预期的部分，在同目录下的
test_school_lookup_db_state.py 里单独验证，这里只测参数层。
"""
from __future__ import annotations

import json

import pytest


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
