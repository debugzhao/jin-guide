from __future__ import annotations

from hashlib import sha256
from string import Template
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PromptModelConfig(BaseModel):
    # 禁止多余字段，避免 YAML 里的拼写错误被静默忽略
    model_config = ConfigDict(extra="forbid")

    alias: str = Field(min_length=1)
    temperature: float = Field(ge=0, le=2)
    max_tokens: int = Field(gt=0)
    timeout_seconds: float = Field(gt=0)
    stream: bool = False


# definitions/ 下一份已加载并通过校验的 Prompt 版本定义，prompt_registry.get() 对外返回的唯一类型
class PromptSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt_name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    version: str = Field(pattern=r"^v[1-9][0-9]*$")
    owner: str = Field(min_length=1)
    description: str = Field(min_length=1)
    input_variables: list[str] = Field(default_factory=list)
    templates: dict[str, str]
    model: PromptModelConfig
    output_schema: str | None = None
    # 加载时留空，由 prompt_content_hash() 基于原始定义算出后回填，不能在 YAML 里手写
    content_hash: str = ""

    # @model_validator 是 pydantic 用来注册"跨字段"校验函数的装饰器，在各字段自己的 Field() 校验都通过后才执行，
    # 用于表达单个字段管不到的整体一致性规则
    # mode="after"而非默认的"before"：要交叉核对 self.templates 和 self.input_variables，
    # 必须等字段都解析成模型属性后才能跑，before 模式拿到的还是原始 dict，没有 self 可用
    @model_validator(mode="after")
    # 加引号是因为它在类还没定义完的时候就被引用了（自引用类型注解）
    def validate_templates(self) -> "PromptSpec":
        if not self.templates:
            raise ValueError("templates 不能为空")
        if len(self.input_variables) != len(set(self.input_variables)):
            raise ValueError("input_variables 不能重复")

        declared = set(self.input_variables)
        used: set[str] = set()
        for template_name, content in self.templates.items():
            if not template_name or not content.strip():
                raise ValueError("模板名称和内容不能为空")
            try:
                used.update(_template_variables(content))
                # 用空字符串填充做一次试渲染，只为触发 Template 的占位符语法校验，结果不使用
                Template(content).substitute({name: "" for name in declared})
            except (KeyError, ValueError) as exc:
                raise ValueError(f"模板 {template_name} 包含非法变量: {exc}") from exc

        # 双向校验而非只查未声明：declared 多余同样要拒绝，否则线上改错变量名会被悄悄忽略而不报错
        undeclared = used - declared
        unused = declared - used
        if undeclared:
            raise ValueError(f"存在未声明变量: {sorted(undeclared)}")
        if unused:
            raise ValueError(f"存在未使用变量: {sorted(unused)}")
        return self

    def render(self, template_name: str, **variables: Any) -> str:
        if template_name not in self.templates:
            raise KeyError(f"Prompt {self.prompt_name}@{self.version} 不存在模板 {template_name}")
        required = _template_variables(self.templates[template_name])
        provided = set(variables)
        if missing := required - provided:
            raise ValueError(f"模板 {template_name} 缺少变量: {sorted(missing)}")
        if extra := provided - required:
            # 多余变量同样报错：调用方传参和模板已经对不上，说明调用点或模板改动漏了同步
            raise ValueError(f"模板 {template_name} 收到多余变量: {sorted(extra)}")
        return Template(self.templates[template_name]).substitute(
            {key: str(value) for key, value in variables.items()}
        )

    def request_metadata(self, **context: str | None) -> dict[str, str]:
        metadata = {
            "prompt_name": self.prompt_name,
            "prompt_version": self.version,
            "prompt_hash": self.content_hash,
        }
        metadata.update({key: str(value) for key, value in context.items() if value})
        return metadata

    def request_options(self, **context: str | None) -> dict[str, Any]:
        """生成所有调用点共用的模型参数和可观测元数据。"""
        return {
            "model": self.model.alias,
            "max_tokens": self.model.max_tokens,
            "temperature": self.model.temperature,
            "stream": self.model.stream,
            "metadata": self.request_metadata(**context),
        }


def _template_variables(content: str) -> set[str]:
    variables: set[str] = set()
    for match in Template.pattern.finditer(content):
        if match.group("invalid") is not None:
            raise ValueError(f"非法占位符，位置 {match.start()}")
        name = match.group("named") or match.group("braced")
        if name:
            variables.add(name)
    return variables


def prompt_content_hash(raw_definition: dict) -> str:
    # 这个 hash 是 version_hashes.yaml 比对的依据：已发布版本内容被原地改过会在启动校验时被拦下
    import json

    # sort_keys + 紧凑分隔符保证同一份内容无论 YAML 里字段顺序如何都算出相同 hash
    canonical = json.dumps(raw_definition, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + sha256(canonical.encode("utf-8")).hexdigest()
