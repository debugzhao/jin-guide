"""Report run_id unique constraint

Revision ID: 013
Revises: 012
Create Date: 2026-07-24

Changes:
1. reports.run_id 加唯一约束——report_agent 节点在 reflection 重试循环里可能
   被同一个 run_id 多次执行，之前每次都 uuid4() 插入新行，导致同一 run 产生
   多份孤儿报告。DB 层加约束兜底应用层的 upsert-by-run_id 逻辑
   （backend/app/agent/nodes/report_agent.py），防止并发/漏改导致重复插入。
"""

from typing import Sequence, Union

from alembic import op

revision: str = "013"
down_revision: Union[str, None] = "012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint("uq_reports_run_id", "reports", ["run_id"])


def downgrade() -> None:
    op.drop_constraint("uq_reports_run_id", "reports", type_="unique")
