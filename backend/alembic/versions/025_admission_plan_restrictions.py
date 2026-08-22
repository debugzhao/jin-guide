"""Add restrictions to enrollment_data_admission_plans.

跟 024_admission_plan_adm_type 是同一条问题链上的最后一环：即使加了
admission_type，宁波大学"音乐学（师范）"仍有两条 valid 发布记录撞成一条
（quota 26"器乐主项"和 quota 27"声乐主项"，university/year/province/batch/
subject_type/major_group/major_code/major_name/admission_type 完全相同，
只有备注不同）——补 restrictions 列作为最后一层去重兜底，并把这个字段真正
存下来（此前该字段在 published_data_records 里其实一直有，只是没同步进业务
表，属于沉默丢数据，不是单纯的"字段缺失可接受"）。

Revision ID: 025_admission_plan_restrictions
Revises: 024_admission_plan_adm_type
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "025_admission_plan_restrict"
down_revision: Union[str, None] = "024_admission_plan_adm_type"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "enrollment_data_admission_plans",
        sa.Column("restrictions", sa.String(500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("enrollment_data_admission_plans", "restrictions")
