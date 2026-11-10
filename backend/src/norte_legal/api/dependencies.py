"""Dependencias de FastAPI compartidas por las rutas."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Cookie, Depends, status
from opentelemetry import trace
from sqlalchemy.orm import Session

from norte_legal.adapters.blob_store import LocalBlobStore
from norte_legal.api.problems import ProblemError
from norte_legal.config import get_settings
from norte_legal.db.accounts import SessionView
from norte_legal.db.session import new_session
from norte_legal.services import auth

SESSION_COOKIE = "nl_session"


def get_session() -> Iterator[Session]:
    with new_session() as session:
        yield session


DbSession = Annotated[Session, Depends(get_session)]
SessionToken = Annotated[str | None, Cookie(alias=SESSION_COOKIE)]


def get_account(session: DbSession, token: SessionToken = None) -> SessionView:
    """Usuario y organización de la sesión. Sin sesión válida, 401."""
    account = auth.resolve_session(session, token) if token else None
    if account is None:
        raise ProblemError(
            status.HTTP_401_UNAUTHORIZED, "unauthenticated", "Authentication required"
        )
    # Identificadores, nunca el email: la traza enlaza los logs de la petición con el usuario.
    span = trace.get_current_span()
    span.set_attribute("enduser.id", str(account.user_id))
    span.set_attribute("norte_legal.organization_id", account.organization_id)
    return account


Account = Annotated[SessionView, Depends(get_account)]


def get_tenant_id(account: Account) -> str:
    """Única fuente del tenant: la organización activa de la sesión."""
    return account.organization_id


def get_blob_store() -> LocalBlobStore:
    return LocalBlobStore(get_settings().blob_dir)


TenantId = Annotated[str, Depends(get_tenant_id)]
BlobStore = Annotated[LocalBlobStore, Depends(get_blob_store)]
