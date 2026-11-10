"""Cuentas, sesiones y organizaciones compartidas."""

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from clients import PASSWORD, anonymous_client, new_email, signed_in_client
from norte_legal.api.dependencies import SESSION_COOKIE
from norte_legal.db.session import new_session
from norte_legal.services.auth import LOGIN_MAX_FAILURES

pytestmark = pytest.mark.integration

PUBLIC_ROUTES = {
    "/api/v1/auth/register",
    "/api/v1/auth/login",
    "/api/v1/auth/logout",
    "/api/v1/system/ping",
}


@pytest.fixture(scope="module")
def app(migrated_settings: None) -> FastAPI:
    from norte_legal.api.main import create_app

    return create_app()


@pytest.fixture(autouse=True)
def _no_broker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("norte_legal.api.documents.enqueue_ingestion", lambda _: True)


def test_every_tenant_route_requires_a_session(app: FastAPI) -> None:
    """Recorre las rutas publicadas: una ruta nueva no puede olvidarse de exigir sesión."""
    client = anonymous_client(app)
    checked = []
    for route, operations in app.openapi()["paths"].items():
        if not route.startswith("/api/v1/") or route in PUBLIC_ROUTES:
            continue
        path = route
        for parameter in ("{document_id}", "{chunk_id}", "{user_id}"):
            path = path.replace(parameter, str(uuid.uuid4()))
        for method in operations:
            response = client.request(method, path)
            assert (response.status_code, response.json()["code"]) == (401, "unauthenticated"), (
                method,
                route,
            )
            checked.append((method, route))
    assert ("post", "/api/v1/documents") in checked
    assert ("post", "/api/v1/query") in checked


def test_the_session_cookie_is_not_readable_by_scripts(app: FastAPI) -> None:
    response = anonymous_client(app).post(
        "/api/v1/auth/register",
        json={"email": new_email(), "password": PASSWORD, "organization_name": "Despacho"},
    )
    cookie = response.headers["set-cookie"].lower()
    assert all(flag in cookie for flag in ("httponly", "secure", "samesite=lax", "path=/api"))


def test_register_opens_a_session_in_a_new_organization(app: FastAPI) -> None:
    email = new_email()
    client = signed_in_client(app, email=email.upper(), organization="  Bufete Norte  ")

    me = client.get("/api/v1/auth/me").json()

    assert me["email"] == email
    assert me["organization"]["name"] == "Bufete Norte"
    assert me["organization"]["role"] == "owner"
    assert me["organizations"] == [me["organization"]]


@pytest.mark.parametrize(
    ("email", "password", "code"),
    [("no-es-un-email", PASSWORD, "invalid_email"), (None, "corta", "weak_password")],
)
def test_invalid_registrations_are_rejected(
    app: FastAPI, email: str | None, password: str, code: str
) -> None:
    response = anonymous_client(app).post(
        "/api/v1/auth/register",
        json={"email": email or new_email(), "password": password, "organization_name": "X"},
    )
    assert (response.status_code, response.json()["code"]) == (422, code)


def test_an_email_can_only_register_once_whatever_its_case(app: FastAPI) -> None:
    email = new_email()
    signed_in_client(app, email=email)
    response = anonymous_client(app).post(
        "/api/v1/auth/register",
        json={"email": email.upper(), "password": PASSWORD, "organization_name": "X"},
    )
    assert (response.status_code, response.json()["code"]) == (409, "email_taken")


def test_login_does_not_reveal_which_part_was_wrong(app: FastAPI) -> None:
    email = new_email()
    signed_in_client(app, email=email)
    client = anonymous_client(app)

    wrong_password = client.post("/api/v1/auth/login", json={"email": email, "password": "x" * 12})
    unknown_user = client.post(
        "/api/v1/auth/login", json={"email": new_email(), "password": PASSWORD}
    )
    valid = client.post("/api/v1/auth/login", json={"email": email.upper(), "password": PASSWORD})

    assert wrong_password.json()["code"] == unknown_user.json()["code"] == "invalid_credentials"
    assert valid.status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 200


def test_logout_revokes_the_token(app: FastAPI) -> None:
    client = signed_in_client(app)
    token = client.cookies[SESSION_COOKIE]

    assert client.post("/api/v1/auth/logout").status_code == 204

    stolen = anonymous_client(app)
    stolen.cookies.set(SESSION_COOKIE, token)
    assert stolen.get("/api/v1/auth/me").status_code == 401


def test_expired_sessions_and_disabled_users_are_rejected(app: FastAPI) -> None:
    expired, disabled = signed_in_client(app), signed_in_client(app)
    disabled_id = disabled.get("/api/v1/auth/me").json()["user_id"]
    with new_session() as session, session.begin():
        session.execute(
            text("UPDATE sessions SET expires_at = now() - interval '1 second' WHERE user_id = :u"),
            {"u": expired.get("/api/v1/auth/me").json()["user_id"]},
        )
        session.execute(
            text("UPDATE users SET disabled_at = now() WHERE id = :u"), {"u": disabled_id}
        )

    assert expired.get("/api/v1/auth/me").status_code == 401
    assert disabled.get("/api/v1/auth/me").status_code == 401


def test_cross_origin_writes_are_rejected(app: FastAPI) -> None:
    client = signed_in_client(app)

    foreign = client.post("/api/v1/auth/logout", headers={"Origin": "https://otra.mizpa.io"})
    same = client.get("/api/v1/auth/me", headers={"Origin": "https://evil.example"})

    assert (foreign.status_code, foreign.json()["code"]) == (403, "cross_origin_request")
    # Las lecturas no cambian estado: la política de mismo origen ya impide leer la respuesta.
    assert same.status_code == 200
    assert (
        client.post("/api/v1/auth/logout", headers={"Origin": "https://testserver"}).status_code
        == 204
    )


def _organization(client: TestClient) -> str:
    return str(client.get("/api/v1/auth/me").json()["organization"]["id"])


def _document_names(client: TestClient) -> set[str]:
    return {d["name"] for d in client.get("/api/v1/documents").json()["items"]}


def test_members_share_the_documents_of_their_organization(app: FastAPI) -> None:
    owner, member_email = signed_in_client(app), new_email()
    member = signed_in_client(app, email=member_email)
    owner.post("/api/v1/documents", files={"file": ("compartido.txt", b"Clausula primera.")})
    member.post("/api/v1/documents", files={"file": ("personal.txt", b"Nota propia.")})

    added = owner.post("/api/v1/organization/members", json={"email": member_email})
    switched = member.post(
        "/api/v1/auth/organization", json={"organization_id": _organization(owner)}
    )

    assert (added.status_code, added.json()["role"]) == (201, "member")
    assert switched.json()["organization"]["role"] == "member"
    assert len(switched.json()["organizations"]) == 2
    assert _document_names(member) == {"compartido.txt"}
    assert _document_names(owner) == {"compartido.txt"}
    assert {m["email"] for m in member.get("/api/v1/organization/members").json()["items"]} == {
        owner.get("/api/v1/auth/me").json()["email"],
        member_email,
    }


def test_only_owners_manage_members(app: FastAPI) -> None:
    owner, member_email = signed_in_client(app), new_email()
    member = signed_in_client(app, email=member_email)
    owner.post("/api/v1/organization/members", json={"email": member_email})
    member.post("/api/v1/auth/organization", json={"organization_id": _organization(owner)})
    owner_id = owner.get("/api/v1/auth/me").json()["user_id"]

    by_member = member.post("/api/v1/organization/members", json={"email": new_email()})
    remove_owner = owner.delete(f"/api/v1/organization/members/{owner_id}")
    duplicate = owner.post("/api/v1/organization/members", json={"email": member_email})
    unknown = owner.post("/api/v1/organization/members", json={"email": new_email()})

    assert (by_member.status_code, by_member.json()["code"]) == (403, "owner_required")
    assert (remove_owner.status_code, remove_owner.json()["code"]) == (409, "cannot_remove_owner")
    assert (duplicate.status_code, duplicate.json()["code"]) == (409, "already_member")
    assert (unknown.status_code, unknown.json()["code"]) == (404, "user_not_found")


def test_removing_a_member_ends_their_access_immediately(app: FastAPI) -> None:
    owner, member_email = signed_in_client(app), new_email()
    member = signed_in_client(app, email=member_email)
    member_id = owner.post("/api/v1/organization/members", json={"email": member_email}).json()[
        "user_id"
    ]
    member.post("/api/v1/auth/organization", json={"organization_id": _organization(owner)})

    assert owner.delete(f"/api/v1/organization/members/{member_id}").status_code == 204
    assert member.get("/api/v1/documents").status_code == 401


def test_cannot_switch_to_an_organization_one_does_not_belong_to(app: FastAPI) -> None:
    stranger, other = signed_in_client(app), signed_in_client(app)

    response = stranger.post(
        "/api/v1/auth/organization", json={"organization_id": _organization(other)}
    )

    assert (response.status_code, response.json()["code"]) == (404, "organization_not_found")
    assert stranger.get("/api/v1/auth/me").status_code == 200


def test_the_admin_command_gives_an_owner_to_an_existing_organization(app: FastAPI) -> None:
    from norte_legal.cli import main

    email, legacy = new_email(), signed_in_client(app)
    user = signed_in_client(app, email=email)

    exit_code = main(
        ["add-member", "--organization", _organization(legacy), "--email", email, "--role", "owner"]
    )

    switched = user.post(
        "/api/v1/auth/organization", json={"organization_id": _organization(legacy)}
    )
    assert exit_code == 0
    assert switched.json()["organization"]["role"] == "owner"
    assert main(["add-member", "--organization", "no-existe", "--email", email]) == 1


def test_repeated_failures_lock_the_account_for_a_while(app: FastAPI) -> None:
    email = new_email()
    signed_in_client(app, email=email)
    client = anonymous_client(app)

    def attempt(password: str) -> str:
        response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
        return "ok" if response.status_code == 200 else str(response.json()["code"])

    failures = [attempt("contraseña equivocada") for _ in range(LOGIN_MAX_FAILURES)]
    locked = attempt(PASSWORD)
    with new_session() as session, session.begin():
        session.execute(
            text("UPDATE users SET locked_until = now() - interval '1 second' WHERE email = :e"),
            {"e": email},
        )

    assert failures == ["invalid_credentials"] * LOGIN_MAX_FAILURES
    assert locked == "login_locked"
    assert attempt(PASSWORD) == "ok"


def test_a_successful_login_resets_the_failure_count(app: FastAPI) -> None:
    email = new_email()
    signed_in_client(app, email=email)
    client = anonymous_client(app)
    wrong = {"email": email, "password": "contraseña equivocada"}
    right = {"email": email, "password": PASSWORD}

    for _ in range(LOGIN_MAX_FAILURES - 1):
        client.post("/api/v1/auth/login", json=wrong)
    client.post("/api/v1/auth/login", json=right)
    # Sin el reinicio, el primero de estos fallos completaría el tope y bloquearía la cuenta.
    for _ in range(LOGIN_MAX_FAILURES - 1):
        client.post("/api/v1/auth/login", json=wrong)

    assert client.post("/api/v1/auth/login", json=right).status_code == 200
