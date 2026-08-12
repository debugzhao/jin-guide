from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from app.prompts.models import PromptSpec, prompt_content_hash


class PromptRegistryError(RuntimeError):
    pass


class PromptRegistry:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path(__file__).resolve().parent
        self._active_versions: dict[str, str] | None = None
        self._cache: dict[tuple[str, str], PromptSpec] = {}

    def get(self, prompt_name: str, version: str | None = None) -> PromptSpec:
        active_versions = self._load_active_versions()
        selected_version = version or active_versions.get(prompt_name)
        if selected_version is None:
            raise PromptRegistryError(f"Prompt 未登记启用版本: {prompt_name}")
        key = (prompt_name, selected_version)
        if key not in self._cache:
            self._cache[key] = self._load_spec(prompt_name, selected_version)
        return self._cache[key]

    def validate_all(self) -> list[PromptSpec]:
        specs = [self.get(name, version) for name, version in self._load_active_versions().items()]
        if len({spec.prompt_name for spec in specs}) != len(specs):
            raise PromptRegistryError("Prompt 名称重复")
        self._validate_version_hashes()
        return specs

    def _validate_version_hashes(self) -> None:
        path = self.root / "version_hashes.yaml"
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise PromptRegistryError(f"无法加载 Prompt 哈希清单: {exc}") from exc
        if not isinstance(raw, dict):
            raise PromptRegistryError("Prompt 哈希清单必须是对象")
        for key, expected_hash in raw.items():
            try:
                prompt_name, version = str(key).rsplit("@", 1)
            except ValueError as exc:
                raise PromptRegistryError(f"Prompt 哈希清单键格式非法: {key}") from exc
            spec = self.get(prompt_name, version)
            if expected_hash != spec.content_hash:
                raise PromptRegistryError(
                    f"已登记版本 {key} 内容发生变化；请新建版本而不是覆盖旧版本"
                )

    def _load_active_versions(self) -> dict[str, str]:
        if self._active_versions is not None:
            return self._active_versions
        path = self.root / "active_versions.yaml"
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise PromptRegistryError(f"无法加载 Prompt 版本清单: {exc}") from exc
        if not isinstance(raw, dict) or not raw:
            raise PromptRegistryError("Prompt 版本清单必须是非空对象")
        self._active_versions = {str(name): str(version) for name, version in raw.items()}
        return self._active_versions

    def _load_spec(self, prompt_name: str, version: str) -> PromptSpec:
        path = self.root / "definitions" / prompt_name / f"{version}.yaml"
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise PromptRegistryError(f"无法加载 {prompt_name}@{version}: {exc}") from exc
        if not isinstance(raw, dict):
            raise PromptRegistryError(f"{prompt_name}@{version} 定义必须是对象")
        try:
            spec = PromptSpec.model_validate(raw)
        except ValidationError as exc:
            raise PromptRegistryError(f"{prompt_name}@{version} 校验失败: {exc}") from exc
        if spec.prompt_name != prompt_name or spec.version != version:
            raise PromptRegistryError(f"{prompt_name}@{version} 的文件路径与内部标识不一致")
        spec.content_hash = prompt_content_hash(raw)
        return spec


prompt_registry = PromptRegistry()
