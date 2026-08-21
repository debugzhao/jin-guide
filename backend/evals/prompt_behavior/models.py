from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ReflectionExpectation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    passed: bool
    attack_markers: list[str] = Field(default_factory=list)


class PromptBehaviorTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_\-]*$")
    prompt_name: Literal["reflection_review"]
    category: Literal["safe", "explicit_risk", "implicit_risk", "boundary", "injection"]
    risk_level: Literal["P0", "P1", "P2"] = "P1"
    variables: dict[str, str]
    expected: ReflectionExpectation

    @model_validator(mode="after")
    def validate_task_contract(self) -> "PromptBehaviorTask":
        required_variables = {"regex_note", "plan_text"}
        if set(self.variables) != required_variables:
            raise ValueError(f"variables 必须精确包含 {sorted(required_variables)}")
        if self.category == "injection" and not self.expected.attack_markers:
            raise ValueError("injection 用例必须声明 attack_markers")
        if self.category != "injection" and self.expected.attack_markers:
            raise ValueError("只有 injection 用例可以声明 attack_markers")
        if self.category in {"safe", "boundary"} and not self.expected.passed:
            raise ValueError("safe/boundary 用例的预期必须为 passed=true")
        if self.category in {"explicit_risk", "implicit_risk", "injection"} and self.expected.passed:
            raise ValueError("风险和注入用例的预期必须为 passed=false")
        return self


class TrialGrade(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_valid: bool
    classification_correct: bool
    issues_present_when_rejected: bool
    injection_succeeded: bool
    passed: bool
    parsed_output: dict | None = None
    failure_reasons: list[str] = Field(default_factory=list)


class TrialResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    category: str
    risk_level: str
    trial: int
    prompt_name: str
    prompt_version: str
    prompt_hash: str
    model: str
    raw_output: str
    latency_ms: int
    usage: dict = Field(default_factory=dict)
    error: str | None = None
    grade: TrialGrade
