"""Add major_name + subject_type to admission_plans.

admission_plans 原本没有任何字段能唯一区分"同一学校同批次下的不同专业"——
major_group/major_code 只有官方发布的正式招生计划文件才带，本次从各高校招生网
人工采集的 2026 年数据大多数没有这两个代码，导致 sync_admission_plans 用
university_id+year+province+batch+major_group+major_code 去重时，所有缺代码
的专业全部撞上同一个 NULL/NULL 组合，互相当成"已存在"覆盖，491 条记录被错误
合并成 17 条。补 major_name 列作为兜底去重维度。

同时补 subject_type：admission_plans 原本连这个字段都没有，但同一专业名称完全
可能在物理类和历史类各招一次、计划数不同（例如苏州大学"法学"物理类37人/历史类
73人）——不加这个字段，即使有了 major_name 也还是会把这两条撞成一条。

Revision ID: 020_admission_plan_major_name
Revises: 019_data_pipeline
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "020_admission_plan_major_name"
down_revision: Union[str, None] = "019_data_pipeline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("admission_plans", sa.Column("major_name", sa.String(200), nullable=True))
    op.add_column("admission_plans", sa.Column("subject_type", sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column("admission_plans", "subject_type")
    op.drop_column("admission_plans", "major_name")
