"""
结构化日志配置（structlog）。

FastAPI 进程（app/main.py）和 ARQ worker 进程（app/worker.py）都会在启动时
各自调用一次 configure_logging()，这样 API 路由和 Agent 节点里所有的
logger.info/warning 调用都经过同一套 processor 渲染——保证输出统一带有
timestamp、level、event 这套基础字段，外加调用点自己绑定的结构化 kwargs
（例如 app/worker.py 里逐节点执行日志用到的 run_id、node、latency_ms）。
"""
import logging

import structlog

from app.config import settings


def configure_logging() -> None:
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    # 生产环境输出 JSON（日志采集系统期望每行一个 JSON 对象）；
    # 其他环境输出人类可读的控制台格式。
    renderer = (
        structlog.processors.JSONRenderer()
        if settings.env == "production"
        else structlog.dev.ConsoleRenderer()
    )

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
