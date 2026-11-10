"""Clientes HTTP de prueba con una sesión iniciada."""

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

PASSWORD = "correct horse battery"


def new_email() -> str:
    return f"u-{uuid.uuid4().hex[:12]}@example.com"


def anonymous_client(app: FastAPI, **kwargs: bool) -> TestClient:
    # HTTPS: la cookie de sesión es `Secure` y httpx no la envía por HTTP.
    return TestClient(app, base_url="https://testserver", **kwargs)


def signed_in_client(
    app: FastAPI, email: str | None = None, organization: str = "Despacho", **kwargs: bool
) -> TestClient:
    """Registra un usuario nuevo, con su propia organización (su tenant)."""
    client = anonymous_client(app, **kwargs)
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": email or new_email(),
            "password": PASSWORD,
            "organization_name": organization,
        },
    )
    assert response.status_code == 201, response.text
    return client
