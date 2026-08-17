"""add rubric_chunks (pgvector)

Revision ID: a1b2c3d4e5f6
Revises: 083c2c6e433d
Create Date: 2026-08-16 12:00:00.000000

Scoring-reference RAG storage: enables the pgvector extension and creates the
``rubric_chunks`` table (CEFR/TCF descriptors + their embeddings). The embedding
dimension (1536) is fixed here to match ``text-embedding-3-small`` /
``settings.embedding_dimensions`` — changing the embedding model needs a new
migration + re-seed. No ANN index: the corpus is ~12 rows, so an exact ``<->``
scan is fine; add an ivfflat/hnsw index if the corpus grows large.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '083c2c6e433d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The exam_section / difficulty_level enum types already exist (first migration),
# so reference them with create_type=False — do not re-CREATE TYPE.
_EXAM_SECTION = postgresql.ENUM(
    'writing', 'speaking', 'listening', 'reading',
    name='exam_section', create_type=False,
)
_DIFFICULTY = postgresql.ENUM(
    'A1', 'A2', 'B1', 'B2', 'C1', 'C2',
    name='difficulty_level', create_type=False,
)

EMBEDDING_DIM = 1536


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        'rubric_chunks',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('exam_section', _EXAM_SECTION, nullable=False),
        sa.Column('cefr_level', _DIFFICULTY, nullable=False),
        sa.Column('dimension', sa.Text(), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('source', sa.Text(), nullable=False),
        sa.Column('embedding', Vector(EMBEDDING_DIM), nullable=False),
        sa.Column(
            'created_at',
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'exam_section', 'dimension', 'cefr_level', 'source',
            name='uq_rubric_chunk_key',
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('rubric_chunks')
    # The exam_section / difficulty_level enums are shared with other tables, so
    # they are NOT dropped here. The `vector` extension is left installed too
    # (dropping it would fail if anything else used it and is unnecessary for a
    # clean round-trip).
