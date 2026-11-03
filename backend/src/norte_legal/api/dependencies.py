"""Dependencias de FastAPI compartidas por las rutas."""

import re
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Header, status
from sqlalchemy.orm import Session

from norte_legal.adapters.blob_store import LocalBlobStore
from norte_legal.api.problems import ProblemError
from norte_legal.config import get_settings
from norte_legal.db.session import new_session

DEFAULT_TENANT = "default"
_TENANT_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def get_tenant_id(
    x_tenant_id: Annotated[str, Header(alias="X-Tenant-ID")] = DEFAULT_TENANT,
) -> str:
    """Única fuente del tenant. No es un control de seguridad: en producción saldría de un JWT."""
    if not _TENANT_ID.fullmatch(x_tenant_id):
        raise ProblemError(status.HTTP_400_BAD_REQUEST, "invalid_tenant", "Invalid tenant")
    return x_tenant_id


def get_session() -> Iterator[Session]:
    with new_session() as session:
        yield session


def get_blob_store() -> LocalBlobStore:
    return LocalBlobStore(get_settings().blob_dir)


TenantId = Annotated[str, Depends(get_tenant_id)]
DbSession = Annotated[Session, Depends(get_session)]
BlobStore = Annotated[LocalBlobStore, Depends(get_blob_store)]
