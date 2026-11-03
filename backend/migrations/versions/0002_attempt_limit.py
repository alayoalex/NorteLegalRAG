"""Tope de intentos por versión.

`attempt` es el token de exclusión y nunca retrocede. Para que un reintento manual vuelva a tener
presupuesto se sube el tope en lugar de reiniciar el contador.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "document_versions",
        sa.Column("attempt_limit", sa.Integer(), server_default="5", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("document_versions", "attempt_limit")
