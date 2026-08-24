"""Add table/column comments to conversation memory tables.

给 memory_intake_conversations / memory_report_conversations /
memory_conversation_messages / memory_conversation_summaries 四张表补齐
DB 级注释（DDL COMMENT ON），方便直接用 psql/建模工具查表结构时也能看懂
会话壳表、消息明细表、摘要缓存表三者的分工。只加注释，不改字段/约束/索引，
属于纯文档性变更。

Revision ID: 027_conversation_comments
Revises: 026_university_comments
"""

from typing import Sequence, Union

from alembic import op

revision: str = "027_conversation_comments"
down_revision: Union[str, None] = "026_university_comments"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE_COMMENTS = {
    "memory_intake_conversations": (
        "建档前聊天(IntakeAgent)会话身份壳表，仅存会话元信息，不存消息内容"
    ),
    "memory_report_conversations": (
        "报告问答(ConversationAgent)会话身份壳表，仅存会话元信息，不存消息内容"
    ),
    "memory_conversation_messages": (
        "intake/report两种会话共用的消息明细表，追加式存储，一行一条消息"
    ),
    "memory_conversation_summaries": (
        "超出Agent原文历史窗口(MAX_HISTORY_MESSAGES)的消息的结构化摘要缓存，"
        "每个会话最多一行"
    ),
}

_COLUMN_COMMENTS = {
    "memory_intake_conversations": {
        "id": "会话/thread id，与LangGraph checkpoint及消息表关联",
        "owner_key": "会话归属标识：登录用户为user_id，匿名用户为anon:{anonymous_id}",
        "created_at": "会话创建时间",
        "updated_at": "会话最后更新时间",
        "title": (
            "会话标题，初始为截断文本，done后由profile-agent异步升级为自然语言"
            "摘要（已手动重命名则不覆盖）"
        ),
        "deleted_at": "软删除时间，非空表示已删除，删除后再发消息会404",
        "version": "乐观锁版本号",
    },
    "memory_report_conversations": {
        "id": "会话id",
        "report_id": "关联的报告id",
        "user_id": "登录用户id，匿名场景可空",
        "created_at": "会话创建时间",
        "updated_at": "会话最后更新时间",
        "anonymous_id": "匿名用户标识，登录用户场景可空",
        "version": "乐观锁版本号",
    },
    "memory_conversation_messages": {
        "id": "消息主键id",
        "report_conversation_id": (
            "关联的报告问答会话id，与intake_conversation_id恰好二选一(CHECK约束)"
        ),
        "intake_conversation_id": (
            "关联的建档前聊天会话id，与report_conversation_id恰好二选一(CHECK约束)"
        ),
        "seq": "会话内消息序号，从1递增，同一会话内唯一",
        "role": "消息角色：user或assistant",
        "content": "消息正文",
        "citations": "引用来源(jsonb)，报告问答场景用于标注检索证据",
        "created_at": "消息创建时间",
    },
    "memory_conversation_summaries": {
        "id": "摘要主键id",
        "report_conversation_id": (
            "关联的报告问答会话id，与intake_conversation_id恰好二选一(CHECK约束)"
        ),
        "intake_conversation_id": (
            "关联的建档前聊天会话id，与report_conversation_id恰好二选一(CHECK约束)"
        ),
        "summary_json": (
            "结构化摘要内容：confirmed_facts/preferences/rejected_options/"
            "previous_decisions/open_questions"
        ),
        "covered_through_seq": "摘要已覆盖到的消息seq水位线，之前的消息无需再拼入上下文",
        "summary_version": "摘要结构版本号",
        "source_model": "生成本摘要所用的模型标识",
        "prompt_version": "生成本摘要所用的prompt版本",
        "tokens_before": "摘要生成前原始历史的token数",
        "tokens_after": "摘要生成后的token数",
        "status": "摘要生成状态，如ready",
        "created_at": "摘要首次创建时间",
        "updated_at": "摘要最后更新时间（增量重新生成时刷新）",
    },
}


def upgrade() -> None:
    for table, comment in _TABLE_COMMENTS.items():
        op.execute(f"COMMENT ON TABLE {table} IS '{comment}'")
    for table, columns in _COLUMN_COMMENTS.items():
        for column, comment in columns.items():
            op.execute(f"COMMENT ON COLUMN {table}.{column} IS '{comment}'")


def downgrade() -> None:
    for table in _TABLE_COMMENTS:
        op.execute(f"COMMENT ON TABLE {table} IS NULL")
    for table, columns in _COLUMN_COMMENTS.items():
        for column in columns:
            op.execute(f"COMMENT ON COLUMN {table}.{column} IS NULL")
