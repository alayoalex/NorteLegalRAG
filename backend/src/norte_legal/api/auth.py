"""Rutas de cuentas: registro, sesión y miembros de la organización activa."""

import uuid

from fastapi import APIRouter, Response, status

from norte_legal.api.dependencies import SESSION_COOKIE, Account, DbSession, SessionToken
from norte_legal.api.schemas import (
    AddMemberIn,
    LoginIn,
    MemberListOut,
    MemberOut,
    MeOut,
    RegisterIn,
    SwitchOrganizationIn,
)
from norte_legal.config import get_settings
from norte_legal.services import auth
from norte_legal.services.auth import IssuedSession

router = APIRouter(prefix="/api/v1", tags=["auth"])

# La cookie solo viaja a la API, no a los archivos estáticos.
_COOKIE_PATH = "/api"


@router.post("/auth/register", response_model=MeOut, status_code=status.HTTP_201_CREATED)
def register(body: RegisterIn, response: Response, session: DbSession) -> MeOut:
    """Crea la cuenta y una organización propia, y abre la sesión."""
    issued = auth.register(
        session,
        email=body.email,
        password=body.password,
        organization_name=body.organization_name,
    )
    return _start(response, session, issued)


@router.post("/auth/login", response_model=MeOut)
def login(body: LoginIn, response: Response, session: DbSession) -> MeOut:
    issued = auth.login(session, email=body.email, password=body.password)
    return _start(response, session, issued)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response, session: DbSession, token: SessionToken = None) -> None:
    """Sin sesión también responde 204: el resultado es el mismo."""
    if token:
        auth.logout(session, token)
    response.delete_cookie(SESSION_COOKIE, path=_COOKIE_PATH)


@router.get("/auth/me", response_model=MeOut)
def me(account: Account, session: DbSession) -> MeOut:
    return MeOut.build(account, auth.organizations_of(session, account))


@router.post("/auth/organization", response_model=MeOut)
def switch_organization(
    body: SwitchOrganizationIn,
    account: Account,
    response: Response,
    session: DbSession,
) -> MeOut:
    """Cambia la organización activa. Emite un token nuevo y anula el anterior."""
    issued = auth.switch_organization(session, account, body.organization_id)
    return _start(response, session, issued)


@router.get("/organization/members", response_model=MemberListOut)
def list_members(account: Account, session: DbSession) -> MemberListOut:
    return MemberListOut(items=[MemberOut.build(m) for m in auth.list_members(session, account)])


@router.post("/organization/members", response_model=MemberOut, status_code=status.HTTP_201_CREATED)
def add_member(body: AddMemberIn, account: Account, session: DbSession) -> MemberOut:
    """Añade a un usuario ya registrado. Solo para `owner`."""
    return MemberOut.build(auth.add_member(session, account, body.email))


@router.delete("/organization/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(user_id: uuid.UUID, account: Account, session: DbSession) -> None:
    """Expulsa a un `member` y cierra sus sesiones en la organización. Solo para `owner`."""
    auth.remove_member(session, account, user_id)


def _start(response: Response, session: DbSession, issued: IssuedSession) -> MeOut:
    settings = get_settings()
    response.set_cookie(
        SESSION_COOKIE,
        issued.token,
        max_age=settings.session_ttl_hours * 3600,
        path=_COOKIE_PATH,
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="lax",
    )
    return MeOut.build(issued.account, auth.organizations_of(session, issued.account))
