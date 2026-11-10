"""Organizaciones, usuarios, pertenencias y sesiones.

Una organización es el tenant: su `id` es el `tenant_id` que ya llevan documentos, versiones y
fragmentos, así que el filtrado existente no cambia. Un usuario pertenece a una o varias
organizaciones (`memberships`) y cada sesión fija la organización activa. La clave foránea
compuesta hacia `memberships` hace que, al expulsar a un miembro, sus sesiones en esa organización
desaparezcan con él.

Los tenants que ya tienen documentos (`default`, `eval-*`) se registran como organizaciones para
no perder sus datos. La clave foránea de `documents.tenant_id` hacia `organizations` llega en una
migración posterior, cuando el tenant deje de salir de la cabecera `X-Tenant-ID`.

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        # El mismo formato que valida la API para el tenant.
        sa.CheckConstraint("id ~ '^[a-z0-9][a-z0-9_-]{0,63}$'", name="ck_organizations_id_format"),
    )

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        # La aplicación normaliza a minúsculas; la restricción impide duplicados por mayúsculas.
        sa.CheckConstraint("email = lower(email)", name="ck_users_email_lowercase"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )

    op.create_table(
        "memberships",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "organization_id",
            sa.Text(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("role IN ('owner', 'member')", name="ck_memberships_role"),
    )
    # La clave primaria empieza por `user_id`: este índice sirve para listar los miembros.
    op.create_index("ix_memberships_organization", "memberships", ["organization_id"])

    op.create_table(
        "sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        # Solo el hash: una copia de la base de datos no sirve para suplantar a nadie.
        sa.Column("token_sha256", sa.String(64), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("token_sha256", name="uq_sessions_token_sha256"),
        sa.ForeignKeyConstraint(
            ["user_id", "organization_id"],
            ["memberships.user_id", "memberships.organization_id"],
            name="fk_sessions_membership",
            ondelete="CASCADE",
        ),
    )
    # PostgreSQL no indexa las claves foráneas: sin esto, el borrado en cascada recorre la tabla.
    op.create_index("ix_sessions_membership", "sessions", ["user_id", "organization_id"])

    op.execute(
        "INSERT INTO organizations (id, name) SELECT DISTINCT tenant_id, tenant_id FROM documents"
    )


def downgrade() -> None:
    op.drop_table("sessions")
    op.drop_table("memberships")
    op.drop_table("users")
    op.drop_table("organizations")
