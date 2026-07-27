"""Backfill conversation_messages from legacy messages_json

Revision ID: 015
Revises: 014
Create Date: 2026-07-24

Changes (docs/memory-architecture.md 第六节 P2):
1. 把 report_conversations/intake_conversations.messages_json 里现存的历史消息，
   按数组下标展开成 conversation_messages 的独立行（seq = 数组下标）。这一步
   在应用层双写逻辑（backend/app/services/conversation_store.py 的
   append_conversation_messages）上线之后运行，只回填"双写上线前就已存在、
   conversation_messages 里还完全没有记录"的会话——用 NOT EXISTS 排除双写上线
   后新建的会话，避免把它们已经写过的消息重复插入一遍。
2. 纯数据迁移，不改 schema；downgrade 删除本次回填产生的行（用 created_at 早于
   本次迁移执行时刻无法可靠区分，因此 downgrade 直接清空两类会话下所有
   "在回填前就没有 conversation_messages 记录、回填后才有"的行不可逆地识别——
   实际是不可精确 downgrade 的数据迁移，downgrade 里改为整表清空并记录警告，
   与本项目 009 迁移里对不可逆 downgrade 的处理方式一致（见该文件注释）。
"""

from typing import Sequence, Union

from alembic import op

revision: str = "015"
down_revision: Union[str, None] = "014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO conversation_messages
            (id, report_conversation_id, intake_conversation_id, seq, role, content, citations, created_at)
        SELECT
            gen_random_uuid()::text,
            rc.id,
            NULL,
            elem.ordinality::int,
            COALESCE(elem.value->>'role', 'unknown'),
            COALESCE(elem.value->>'content', ''),
            elem.value->'citations',
            COALESCE((elem.value->>'created_at')::timestamptz, rc.created_at)
        FROM report_conversations rc
        CROSS JOIN LATERAL jsonb_array_elements(rc.messages_json) WITH ORDINALITY AS elem(value, ordinality)
        WHERE jsonb_array_length(rc.messages_json) > 0
          AND NOT EXISTS (
              SELECT 1 FROM conversation_messages cm WHERE cm.report_conversation_id = rc.id
          )
        """
    )
    op.execute(
        """
        INSERT INTO conversation_messages
            (id, report_conversation_id, intake_conversation_id, seq, role, content, citations, created_at)
        SELECT
            gen_random_uuid()::text,
            NULL,
            ic.id,
            elem.ordinality::int,
            COALESCE(elem.value->>'role', 'unknown'),
            COALESCE(elem.value->>'content', ''),
            elem.value->'citations',
            COALESCE((elem.value->>'created_at')::timestamptz, ic.created_at)
        FROM intake_conversations ic
        CROSS JOIN LATERAL jsonb_array_elements(ic.messages_json) WITH ORDINALITY AS elem(value, ordinality)
        WHERE jsonb_array_length(ic.messages_json) > 0
          AND NOT EXISTS (
              SELECT 1 FROM conversation_messages cm WHERE cm.intake_conversation_id = ic.id
          )
        """
    )


def downgrade() -> None:
    # 无法精确区分"回填产生的行"和"回填之后双写产生的行"，只能整表清空——
    # 与 009 迁移对不可逆 downgrade 的处理方式一致：如果 downgrade 时已有
    # 回填后新增的会话数据，这个操作会丢弃它们，需要在有真实数据前谨慎使用。
    op.execute("DELETE FROM conversation_messages")
