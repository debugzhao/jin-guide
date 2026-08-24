"""Add column comments to enrollment_data_universities.

给 enrollment_data_universities 表补齐业务字段的 DB 级注释（DDL COMMENT ON），
方便直接用 psql/建模工具查表结构时也能看懂每个字段的业务含义，不用回翻 ORM
模型或文档。只加注释，不改字段/约束/索引，属于纯文档性变更。

Revision ID: 026_university_comments
Revises: 025_admission_plan_restrict
"""

from typing import Sequence, Union

from alembic import op

revision: str = "026_university_comments"
down_revision: Union[str, None] = "025_admission_plan_restrict"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_COLUMN_COMMENTS = {
    "id": "主键，院校记录 UUID",
    "name": "院校标准名称",
    "code": "教育部院校代码",
    "city": "院校所在城市",
    "province": "院校所在省份",
    "school_type": "办学类型：综合/理工/师范/医科/财经/农业/军事等",
    "is_985": "是否 985 高校",
    "is_211": "是否 211 高校",
    "is_shuangyiliu": "是否双一流高校",
    "has_medical_program": "是否开设医学类专业",
    "annual_tuition_min": "年学费下限，单位：元/年",
    "annual_tuition_max": "年学费上限，单位：元/年",
}

_TABLE_COMMENT = (
    "院校主数据表：院校基础信息与标签（985/211/双一流/医学类等），"
    "供推荐引擎按条件筛选院校"
)


def upgrade() -> None:
    op.execute(f"COMMENT ON TABLE enrollment_data_universities IS '{_TABLE_COMMENT}'")
    for column, comment in _COLUMN_COMMENTS.items():
        op.execute(
            f"COMMENT ON COLUMN enrollment_data_universities.{column} IS '{comment}'"
        )


def downgrade() -> None:
    op.execute("COMMENT ON TABLE enrollment_data_universities IS NULL")
    for column in _COLUMN_COMMENTS:
        op.execute(
            f"COMMENT ON COLUMN enrollment_data_universities.{column} IS NULL"
        )
