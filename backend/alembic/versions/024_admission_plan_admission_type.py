"""Add admission_type to enrollment_data_admission_plans.

跟 020_admission_plan_major_name 是同一类问题在更深一层重现：那次修的是
"缺 major_group/major_code 时靠 major_name+subject_type 兜底去重"，但浙江
这批单校自采数据 subject_type 恒为 "unified"（不分文理），同一专业名称完全
可能在"普通类"平行志愿和"三位一体"综合评价两条不同录取机制下各出现一次、
计划数不同（如宁波大学"水产养殖学（拔尖人才创新班）"），这时 university_id+
year+province+batch+subject_type+major_group+major_code+major_name 这组
去重键还是会把两条撞成一条——sync_admission_plans 实测把193条发布记录合并
丢成了174条。补 admission_type 列（复用 data_pipeline records.py 里
AdmissionScoreRecord/AdmissionPlanRecord 早就有的同名字段）作为再下一层的
去重兜底维度。

Revision ID: 024_admission_plan_adm_type
Revises: 023_chunks_embedding_dim_1024
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "024_admission_plan_adm_type"
down_revision: Union[str, None] = "023_chunks_embedding_dim_1024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 200 而不是常见的50：兜底值有时是整段类别说明文字（如宁波大学"普通类提前
    # 三位一体 0238 只招已参加我校'三位一体'综合评价招生考试并获得入围资格的
    # 考生。具体规则详见我校招生章程。"），已用真实数据撞过 varchar(50) 截断错误。
    op.add_column(
        "enrollment_data_admission_plans",
        sa.Column("admission_type", sa.String(200), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("enrollment_data_admission_plans", "admission_type")
