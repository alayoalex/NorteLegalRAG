"""Borrado lógico de documentos.

Un documento borrado deja de listarse y sus fragmentos salen de la búsqueda (`is_current = false`),
pero versiones y fragmentos se conservan: las citas ya mostradas siguen resolviéndose.

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("documents", "deleted_at")
