"""Acceso a usuarios, organizaciones, pertenencias y sesiones.

Estas tablas son la identidad, no datos de un tenant: no se filtran por `tenant_id`. Cada consulta
que toca una organización recibe su `organization_id` de forma explícita.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import case, delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from norte_legal.db.models import AuthSession, Membership, Organization, User


@dataclass(frozen=True)
class SessionView:
    session_id: uuid.UUID
    user_id: uuid.UUID
    email: str
    organization_id: str
    organization_name: str
    role: str


@dataclass(frozen=True)
class OrganizationView:
    id: str
    name: str
    role: str


@dataclass(frozen=True)
class MemberView:
    user_id: uuid.UUID
    email: str
    role: str
    joined_at: datetime


class AccountRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create_user(self, email: str, password_hash: str) -> uuid.UUID | None:
        """`None` si el email ya está registrado."""
        statement = (
            insert(User)
            .values(id=uuid.uuid4(), email=email, password_hash=password_hash)
            .on_conflict_do_nothing(constraint="uq_users_email")
            .returning(User.id)
        )
        return self._session.execute(statement).scalar_one_or_none()

    def active_user_by_email(self, email: str) -> User | None:
        return self._session.scalars(
            select(User).where(User.email == email, User.disabled_at.is_(None))
        ).one_or_none()

    def set_password_hash(self, user_id: uuid.UUID, password_hash: str) -> None:
        self._session.execute(
            update(User).where(User.id == user_id).values(password_hash=password_hash)
        )

    def record_failed_login(
        self, user_id: uuid.UUID, max_failures: int, locked_until: datetime
    ) -> None:
        """Un solo `UPDATE`: dos intentos simultáneos no pueden leer el mismo contador. Al llegar
        al tope se bloquea y el contador vuelve a cero para la siguiente ronda."""
        reaches_limit = User.failed_logins + 1 >= max_failures
        self._session.execute(
            update(User)
            .where(User.id == user_id)
            .values(
                failed_logins=case((reaches_limit, 0), else_=User.failed_logins + 1),
                locked_until=case((reaches_limit, locked_until), else_=User.locked_until),
            )
        )

    def reset_failed_logins(self, user_id: uuid.UUID) -> None:
        self._session.execute(
            update(User).where(User.id == user_id).values(failed_logins=0, locked_until=None)
        )

    def create_organization(self, organization_id: str, name: str) -> None:
        self._session.add(Organization(id=organization_id, name=name))

    def add_membership(self, user_id: uuid.UUID, organization_id: str, role: str) -> bool:
        """`False` si el usuario ya pertenecía a la organización."""
        statement = (
            insert(Membership)
            .values(user_id=user_id, organization_id=organization_id, role=role)
            .on_conflict_do_nothing()
            .returning(Membership.user_id)
        )
        return self._session.execute(statement).scalar_one_or_none() is not None

    def membership_role(self, user_id: uuid.UUID, organization_id: str) -> str | None:
        return self._session.scalar(
            select(Membership.role).where(
                Membership.user_id == user_id, Membership.organization_id == organization_id
            )
        )

    def remove_membership(self, user_id: uuid.UUID, organization_id: str) -> None:
        """Las sesiones del usuario en esa organización se borran en cascada."""
        self._session.execute(
            delete(Membership).where(
                Membership.user_id == user_id, Membership.organization_id == organization_id
            )
        )

    def organizations_of(self, user_id: uuid.UUID) -> list[OrganizationView]:
        """Por antigüedad de la pertenencia: la primera es la que se abre al iniciar sesión."""
        rows = self._session.execute(
            select(Organization.id, Organization.name, Membership.role)
            .join(Membership, Membership.organization_id == Organization.id)
            .where(Membership.user_id == user_id)
            .order_by(Membership.created_at, Organization.id)
        )
        return [OrganizationView(id=row.id, name=row.name, role=row.role) for row in rows]

    def members_of(self, organization_id: str) -> list[MemberView]:
        rows = self._session.execute(
            select(User.id, User.email, Membership.role, Membership.created_at)
            .join(Membership, Membership.user_id == User.id)
            .where(Membership.organization_id == organization_id)
            .order_by(Membership.created_at, User.email)
        )
        return [
            MemberView(user_id=row.id, email=row.email, role=row.role, joined_at=row.created_at)
            for row in rows
        ]

    def create_session(
        self, user_id: uuid.UUID, organization_id: str, token_sha256: str, expires_at: datetime
    ) -> uuid.UUID:
        session_id = uuid.uuid4()
        self._session.add(
            AuthSession(
                id=session_id,
                token_sha256=token_sha256,
                user_id=user_id,
                organization_id=organization_id,
                expires_at=expires_at,
            )
        )
        return session_id

    def find_session(self, token_sha256: str, now: datetime) -> SessionView | None:
        """Solo sesiones vigentes de usuarios activos que siguen siendo miembros."""
        row = self._session.execute(
            select(
                AuthSession.id,
                User.id.label("user_id"),
                User.email,
                Organization.id.label("organization_id"),
                Organization.name,
                Membership.role,
            )
            .join(User, User.id == AuthSession.user_id)
            .join(
                Membership,
                (Membership.user_id == AuthSession.user_id)
                & (Membership.organization_id == AuthSession.organization_id),
            )
            .join(Organization, Organization.id == AuthSession.organization_id)
            .where(
                AuthSession.token_sha256 == token_sha256,
                AuthSession.expires_at > now,
                User.disabled_at.is_(None),
            )
        ).one_or_none()
        if row is None:
            return None
        return SessionView(
            session_id=row.id,
            user_id=row.user_id,
            email=row.email,
            organization_id=row.organization_id,
            organization_name=row.name,
            role=row.role,
        )

    def delete_session(self, token_sha256: str) -> None:
        self._session.execute(delete(AuthSession).where(AuthSession.token_sha256 == token_sha256))

    def delete_session_by_id(self, session_id: uuid.UUID) -> None:
        self._session.execute(delete(AuthSession).where(AuthSession.id == session_id))

    def delete_expired_sessions(self, user_id: uuid.UUID, now: datetime) -> None:
        self._session.execute(
            delete(AuthSession).where(AuthSession.user_id == user_id, AuthSession.expires_at <= now)
        )
