"""Bloqueo temporal tras varios intentos fallidos de inicio de sesión.

El contador vive en la fila del usuario: sin servicios nuevos y atómico con un solo `UPDATE`.

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("failed_logins", sa.Integer(), server_default="0", nullable=False)
    )
    op.add_column("users", sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "locked_until")
    op.drop_column("users", "failed_logins")
