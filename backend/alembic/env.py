import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# 导入所有模型，让 Alembic 能通过 Base.metadata 探测到它们
from app.models import Base  # noqa: F401 —— 仅为副作用导入，用于注册所有模型
from app.models.base import Base as ModelBase
from app.config import settings

# 这是 Alembic 的 Config 对象，用于访问当前使用的 .ini 配置文件里的取值
config = context.config

# 用 app 配置里的值覆盖 sqlalchemy.url（读取 DATABASE_URL 环境变量）
config.set_main_option("sqlalchemy.url", settings.database_url)

# 解析配置文件用于 Python 日志配置。
# 这一行本质上就是初始化各个 logger。
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 在这里注册模型的 MetaData 对象，供 'autogenerate' 使用
target_metadata = ModelBase.metadata


def run_migrations_offline() -> None:
    """
    以 'offline' 模式运行迁移。
    此模式下只配置一个 URL，不创建 Engine。
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """使用异步引擎运行迁移。"""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """以 'online' 模式运行迁移。"""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
