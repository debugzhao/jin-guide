"""Enable pgvector, migrate chunks.embedding to vector(1536), add HNSW index

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
    # 1. Enable pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # 2. Replace text embedding column with proper vector type
    op.execute("ALTER TABLE chunks DROP COLUMN IF EXISTS embedding")
    op.execute("ALTER TABLE chunks ADD COLUMN embedding vector(1536)")

    # 3. HNSW index for cosine similarity search (m=16, ef_construction=64 per PRD §6.2)
    op.execute("""
        CREATE INDEX chunks_embedding_hnsw
        ON chunks USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
    """)

    # 4. B-tree index on (document_id, province) for metadata filter acceleration (PRD §6.2)
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
    # Do not drop vector extension — may be used by other tables
