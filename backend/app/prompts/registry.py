from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from app.prompts.models import PromptSpec, prompt_content_hash


class PromptRegistryError(RuntimeError):
    pass


# 加载 definitions/ 下的 Prompt 版本文件、做防篡改校验并缓存；唯一对外实例是本文件末尾的 prompt_registry 单例
class PromptRegistry:
    def __init__(self, root: Path | None = None) -> None:
        # root 可覆盖默认目录：测试用它指向临时 fixture 目录构造隔离实例，不会碰真实 definitions/
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
        # 供应用启动时调用：一次性加载所有登记版本，加载失败或内容被篡改要在启动阶段暴露，而不是留到某次线上请求才炸
        specs = [self.get(name, version) for name, version in self._load_active_versions().items()]
        if len({spec.prompt_name for spec in specs}) != len(specs):
            raise PromptRegistryError("Prompt 名称重复")
        self._validate_version_hashes()
        return specs

    def _validate_version_hashes(self) -> None:
        # 版本文件发布后不可原地修改：比对 version_hashes.yaml 里登记的旧 hash 和重新计算出的 content_hash，
        # 对不上说明已发布版本被偷偷改过内容，正确做法是新建版本而不是覆盖旧版本
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
            # 防止复制旧版本文件建新版本时忘记同步改内部字段：文件路径和 YAML 内声明的 name/version 必须一致
            raise PromptRegistryError(f"{prompt_name}@{version} 的文件路径与内部标识不一致")
        # hash 必须基于原始 YAML dict 计算，不能用 spec.model_dump()：pydantic 的类型转换/默认值填充会让 hash 和磁盘内容对不上
        spec.content_hash = prompt_content_hash(raw)
        return spec


# 全局单例，业务代码统一从这里取用（app/prompts/__init__.py 重导出给外部调用方）
prompt_registry = PromptRegistry()
