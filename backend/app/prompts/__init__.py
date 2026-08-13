"""Git-first Prompt Registry：统一加载、校验和追踪线上 Prompt。"""

from app.prompts.registry import PromptRegistry, prompt_registry

"""
这个特定文件的价值不是"标记包"（这个作用现在弱化了），而是给 app/prompts
这个包定义了一个干净的对外接口——外部只依赖 prompt_registry，不用关心内部是 registry.py 还是别的文件实现的
"""
__all__ = ["PromptRegistry", "prompt_registry"]