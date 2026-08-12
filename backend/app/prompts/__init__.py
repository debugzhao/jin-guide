"""Git-first Prompt Registry：统一加载、校验和追踪线上 Prompt。"""

from app.prompts.registry import PromptRegistry, prompt_registry

__all__ = ["PromptRegistry", "prompt_registry"]
