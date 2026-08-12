from pathlib import Path

import pytest

from app.prompts import PromptRegistry, prompt_registry
from app.prompts.registry import PromptRegistryError


def test_all_active_prompts_load_and_have_trace_metadata():
    specs = prompt_registry.validate_all()

    assert len(specs) == 7
    assert {spec.prompt_name for spec in specs} == {
        "intake_chat",
        "report_conversation",
        "profile_clarification",
        "report_generation",
        "reflection_review",
        "conversation_summary",
        "conversation_title",
    }
    assert all(spec.content_hash.startswith("sha256:") for spec in specs)
    assert all(spec.model.alias and spec.model.max_tokens > 0 for spec in specs)


def test_strict_renderer_rejects_missing_and_extra_variables():
    prompt = prompt_registry.get("conversation_title")

    with pytest.raises(ValueError, match="缺少变量"):
        prompt.render("user", user_message="测试")
    with pytest.raises(ValueError, match="多余变量"):
        prompt.render(
            "user", user_message="测试", assistant_response="答复", unexpected="不可接受"
        )


def test_request_options_contain_prompt_version_hash_and_model_params():
    prompt = prompt_registry.get("report_generation")
    options = prompt.request_options(agent_run_id="run-1")

    assert options["model"] == "report-agent"
    assert options["max_tokens"] == 2000
    assert options["metadata"]["prompt_name"] == "report_generation"
    assert options["metadata"]["prompt_version"] == "v1"
    assert options["metadata"]["agent_run_id"] == "run-1"


def test_registry_rejects_path_and_internal_identity_mismatch(tmp_path: Path):
    (tmp_path / "definitions" / "expected").mkdir(parents=True)
    (tmp_path / "active_versions.yaml").write_text("expected: v1\n", encoding="utf-8")
    (tmp_path / "version_hashes.yaml").write_text("{}\n", encoding="utf-8")
    (tmp_path / "definitions" / "expected" / "v1.yaml").write_text(
        """prompt_name: another
version: v1
owner: test
description: mismatch
input_variables: []
model:
  alias: test-model
  temperature: 1
  max_tokens: 10
  timeout_seconds: 1
templates:
  system: test
""",
        encoding="utf-8",
    )

    with pytest.raises(PromptRegistryError, match="文件路径与内部标识不一致"):
        PromptRegistry(tmp_path).validate_all()


def test_registered_versions_are_immutable(tmp_path: Path):
    source_root = Path(__file__).resolve().parents[1] / "app" / "prompts"
    definitions = tmp_path / "definitions" / "conversation_title"
    definitions.mkdir(parents=True)
    source = source_root / "definitions" / "conversation_title" / "v1.yaml"
    definitions.joinpath("v1.yaml").write_text(
        source.read_text(encoding="utf-8").replace(
            "为 Intake 首轮对话生成短标题", "被静默修改的标题 Prompt"
        ),
        encoding="utf-8",
    )
    (tmp_path / "active_versions.yaml").write_text("conversation_title: v1\n", encoding="utf-8")
    baseline_hash = next(
        line for line in (source_root / "version_hashes.yaml").read_text(encoding="utf-8").splitlines()
        if line.startswith("conversation_title@v1:")
    )
    (tmp_path / "version_hashes.yaml").write_text(baseline_hash + "\n", encoding="utf-8")

    with pytest.raises(PromptRegistryError, match="内容发生变化"):
        PromptRegistry(tmp_path).validate_all()
