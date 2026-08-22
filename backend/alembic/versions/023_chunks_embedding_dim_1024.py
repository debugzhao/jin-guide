"""rag_chunks.embedding 从 vector(1536) 改为 vector(1024)

Embedding 供应商从 Moonshot moonshot-v1-emb-small 切换到 DashScope
qwen3.7-text-embedding（原因：前者返回 403 且官方文档查无此模型，见
backend/docs/04_rag_pipeline.md §9），后者输出向量维度是 1024。

pgvector 的 vector 列宽是类型的一部分，不能原地改宽度。执行本迁移时
rag_chunks.embedding 全部是 NULL（尚未跑过一次成功的 embedding batch），
drop+recreate 列比 ALTER ... USING 更直接安全，做法与 003_pgvector_hnsw
建表时一致。

Revision ID: 023_chunks_embedding_dim_1024
Revises: 022
"""

from typing import Sequence, Union

from alembic import op

revision: str = "023_chunks_embedding_dim_1024"
down_revision: Union[str, None] = "022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS rag_chunks_embedding_hnsw")
    op.execute("ALTER TABLE rag_chunks DROP COLUMN IF EXISTS embedding")
    op.execute("ALTER TABLE rag_chunks ADD COLUMN embedding vector(1024)")
    op.execute("""
        CREATE INDEX rag_chunks_embedding_hnsw
        ON rag_chunks USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS rag_chunks_embedding_hnsw")
    op.execute("ALTER TABLE rag_chunks DROP COLUMN IF EXISTS embedding")
    op.execute("ALTER TABLE rag_chunks ADD COLUMN embedding vector(1536)")
    op.execute("""
        CREATE INDEX rag_chunks_embedding_hnsw
        ON rag_chunks USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
    """)
