"""Cuentas: registro, sesiones y miembros de una organización.

Una organización es el tenant: sus miembros comparten documentos y consultas. La sesión fija la
organización activa y de ella sale el `tenant_id` de cada petición (DECISIONS.md §2).

El token de sesión es aleatorio y opaco. En la base de datos solo se guarda su SHA-256: un token
de 256 bits no se puede adivinar por fuerza bruta, así que no necesita un hash lento.
"""

import hashlib
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy.orm import Session

from norte_legal.config import get_settings
from norte_legal.db.accounts import AccountRepository, MemberView, OrganizationView, SessionView
from norte_legal.db.models import User

logger = structlog.get_logger(__name__)

PASSWORD_MIN_LENGTH = 12
# Tope para que nadie haga trabajar a Argon2 con un cuerpo de varios megas.
PASSWORD_MAX_LENGTH = 128
EMAIL_MAX_LENGTH = 254
# Frena la fuerza bruta contra una cuenta concreta sin servicios nuevos. Ver DECISIONS.md §2.
LOGIN_MAX_FAILURES = 5
LOGIN_LOCKOUT = timedelta(minutes=15)
# Solo descarta lo que no puede ser un email. Comprobarlo de verdad exigiría enviar un correo.
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Argon2id con los parámetros por defecto de argon2-cffi (perfil de RFC 9106 para poca memoria).
_hasher = PasswordHasher()
# Si el email no existe se verifica contra este hash: la respuesta tarda lo mismo y no revela
# qué emails están registrados.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


class AccountError(Exception):
    """Error esperado de un caso de uso de cuentas. `code` es estable y lo entiende el frontend."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class IssuedSession:
    token: str
    expires_at: datetime
    account: SessionView


def register(
    session: Session, *, email: str, password: str, organization_name: str
) -> IssuedSession:
    """Crea el usuario y una organización propia de la que es `owner`."""
    email = _normalize_email(email)
    _check_password(password)
    password_hash = _hasher.hash(password)
    organization_id = f"o-{secrets.token_hex(6)}"
    with session.begin():
        accounts = AccountRepository(session)
        user_id = accounts.create_user(email, password_hash)
        if user_id is None:
            raise AccountError("email_taken")
        accounts.create_organization(organization_id, organization_name)
        accounts.add_membership(user_id, organization_id, "owner")
        issued = _issue(accounts, user_id, organization_id)
    logger.info("user_registered", user_id=str(user_id), organization_id=organization_id)
    return issued


def login(session: Session, *, email: str, password: str) -> IssuedSession:
    """Abre la sesión en la organización más antigua del usuario.

    Tras `LOGIN_MAX_FAILURES` contraseñas erróneas seguidas, la cuenta no admite inicios de sesión
    durante `LOGIN_LOCKOUT`, aunque la contraseña sea correcta. El fallo se guarda antes de
    responder: si se lanzara la excepción dentro de la transacción, el contador se revertiría.
    """
    now = _now()
    with session.begin():
        accounts = AccountRepository(session)
        user = accounts.active_user_by_email(email.strip().lower())
        if user is not None and user.locked_until is not None and user.locked_until > now:
            outcome: IssuedSession | str = "login_locked"
        elif not _password_matches(user.password_hash if user else _DUMMY_HASH, password):
            outcome = "invalid_credentials"
            if user is not None:
                accounts.record_failed_login(user.id, LOGIN_MAX_FAILURES, now + LOGIN_LOCKOUT)
        else:
            outcome = _open_session(accounts, user, password, now)
    if isinstance(outcome, str):
        logger.info("login_failed", reason=outcome)
        raise AccountError(outcome)
    logger.info("login_succeeded", user_id=str(outcome.account.user_id))
    return outcome


def _open_session(
    accounts: AccountRepository, user: User | None, password: str, now: datetime
) -> IssuedSession | str:
    if user is None:  # Inalcanzable: el hash ficticio no coincide con ninguna contraseña.
        return "invalid_credentials"
    accounts.reset_failed_logins(user.id)
    if _hasher.check_needs_rehash(user.password_hash):
        accounts.set_password_hash(user.id, _hasher.hash(password))
    organizations = accounts.organizations_of(user.id)
    if not organizations:
        return "no_organization"
    accounts.delete_expired_sessions(user.id, now)
    return _issue(accounts, user.id, organizations[0].id)


def resolve_session(session: Session, token: str) -> SessionView | None:
    with session.begin():
        return AccountRepository(session).find_session(_token_hash(token), _now())


def logout(session: Session, token: str) -> None:
    with session.begin():
        AccountRepository(session).delete_session(_token_hash(token))


def switch_organization(
    session: Session, account: SessionView, organization_id: str
) -> IssuedSession:
    """Sustituye la sesión por otra en la organización pedida. El token cambia."""
    with session.begin():
        accounts = AccountRepository(session)
        if accounts.membership_role(account.user_id, organization_id) is None:
            raise AccountError("organization_not_found")
        accounts.delete_session_by_id(account.session_id)
        return _issue(accounts, account.user_id, organization_id)


def organizations_of(session: Session, account: SessionView) -> list[OrganizationView]:
    with session.begin():
        return AccountRepository(session).organizations_of(account.user_id)


def list_members(session: Session, account: SessionView) -> list[MemberView]:
    with session.begin():
        return AccountRepository(session).members_of(account.organization_id)


def add_member(session: Session, account: SessionView, email: str) -> MemberView:
    """Añade como `member` a un usuario ya registrado. Solo un `owner` puede hacerlo."""
    _require_owner(account)
    with session.begin():
        accounts = AccountRepository(session)
        user = accounts.active_user_by_email(email.strip().lower())
        if user is None:
            raise AccountError("user_not_found")
        if not accounts.add_membership(user.id, account.organization_id, "member"):
            raise AccountError("already_member")
        member = next(
            m for m in accounts.members_of(account.organization_id) if m.user_id == user.id
        )
    logger.info("member_added", user_id=str(user.id), organization_id=account.organization_id)
    return member


def remove_member(session: Session, account: SessionView, user_id: uuid.UUID) -> None:
    """Expulsa a un `member`. Un `owner` no se puede expulsar: la organización se quedaría sin
    nadie que la administre."""
    _require_owner(account)
    with session.begin():
        accounts = AccountRepository(session)
        role = accounts.membership_role(user_id, account.organization_id)
        if role is None:
            raise AccountError("member_not_found")
        if role == "owner":
            raise AccountError("cannot_remove_owner")
        accounts.remove_membership(user_id, account.organization_id)
    logger.info("member_removed", user_id=str(user_id), organization_id=account.organization_id)


def _issue(accounts: AccountRepository, user_id: uuid.UUID, organization_id: str) -> IssuedSession:
    token = secrets.token_urlsafe(32)
    expires_at = _now() + timedelta(hours=get_settings().session_ttl_hours)
    accounts.create_session(user_id, organization_id, _token_hash(token), expires_at)
    account = accounts.find_session(_token_hash(token), _now())
    if account is None:  # Creada en esta misma transacción: sería un error de programación.
        raise RuntimeError("new session is not visible")
    return IssuedSession(token=token, expires_at=expires_at, account=account)


def _password_matches(password_hash: str, password: str) -> bool:
    if len(password) > PASSWORD_MAX_LENGTH:
        return False
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def _normalize_email(email: str) -> str:
    email = email.strip().lower()
    if len(email) > EMAIL_MAX_LENGTH or not _EMAIL.fullmatch(email):
        raise AccountError("invalid_email")
    return email


def _check_password(password: str) -> None:
    if not PASSWORD_MIN_LENGTH <= len(password) <= PASSWORD_MAX_LENGTH:
        raise AccountError("weak_password")


def _require_owner(account: SessionView) -> None:
    if account.role != "owner":
        raise AccountError("owner_required")


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(UTC)
