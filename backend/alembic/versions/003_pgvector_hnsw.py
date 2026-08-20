"""启用 pgvector，将 chunks.embedding 迁移为 vector(1536) 类型，并新增 HNSW 索引

Revision ID: 003
Revises: 002
Create Date: 2026-07-01
"""
from typing import Sequence, Union

from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. 启用 pgvector 扩展
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # 2. 用真正的 vector 类型替换原来的文本类型 embedding 列
    op.execute("ALTER TABLE chunks DROP COLUMN IF EXISTS embedding")
    op.execute("ALTER TABLE chunks ADD COLUMN embedding vector(1536)")

    # 3. 用于余弦相似度检索的 HNSW 索引（m=16、ef_construction=64，按 PRD §6.2 取值）
    op.execute("""
        CREATE INDEX chunks_embedding_hnsw
        ON chunks USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
    """)

    # 4. (document_id, province) 上的 B-tree 索引，加速元数据过滤查询（PRD §6.2）
    op.execute("""
        CREATE INDEX chunks_doc_province
        ON chunks (document_id, (metadata_json->>'province'))
        WHERE metadata_json IS NOT NULL
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS chunks_doc_province")
    op.execute("DROP INDEX IF EXISTS chunks_embedding_hnsw")
    op.execute("ALTER TABLE chunks DROP COLUMN IF EXISTS embedding")
    op.execute("ALTER TABLE chunks ADD COLUMN embedding TEXT")
    # 不删除 vector 扩展本身——其他表可能仍在使用它
