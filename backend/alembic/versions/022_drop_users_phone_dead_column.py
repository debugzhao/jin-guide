"""删除 auth_users.phone 死列及其唯一约束

migration 001 建表时预留了 phone 字段（用于二期短信登录），但短信登录方案在
v1.1 已移除（见 CLAUDE.md「已移除（v1.1）」），User 模型早已不再声明这个字段，
代码里也没有任何地方读写它——纯粹是一列从未被使用过的死数据，此次一并清理。

Revision ID: 022
Revises: 021_module_prefix_table_rename
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "022"
down_revision: Union[str, None] = "021_module_prefix_table_rename"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("auth_users_phone_key", "auth_users", type_="unique")
    op.drop_column("auth_users", "phone")


def downgrade() -> None:
    op.add_column("auth_users", sa.Column("phone", sa.String(20), nullable=True))
    op.create_unique_constraint("auth_users_phone_key", "auth_users", ["phone"])
