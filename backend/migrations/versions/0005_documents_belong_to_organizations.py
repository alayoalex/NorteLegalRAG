"""Cada documento pertenece a una organización existente.

El tenant ya sale de la sesión, así que no aparecen tenants nuevos sin organización. Antes de la
clave foránea se registran los que se hayan creado por la cabecera `X-Tenant-ID` desde la 0004.
Sin `ON DELETE`: borrar una organización con documentos debe ser una decisión explícita.

Revision ID: 0005
Revises: 0004
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "INSERT INTO organizations (id, name) SELECT DISTINCT tenant_id, tenant_id FROM documents"
        " ON CONFLICT (id) DO NOTHING"
    )
    op.create_foreign_key(
        "fk_documents_organization", "documents", "organizations", ["tenant_id"], ["id"]
    )


def downgrade() -> None:
    op.drop_constraint("fk_documents_organization", "documents", type_="foreignkey")
