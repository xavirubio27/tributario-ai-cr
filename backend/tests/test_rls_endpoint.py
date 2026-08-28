"""Camino completo HTTP: JWT -> FastAPI -> PostgreSQL -> RLS.

Incluye el CONTROL POSITIVO obligatorio: sin él, los casos de aislamiento
podrían pasar simplemente porque toda la autenticación estuviera rota.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client(settings):  # noqa: ARG001 — fuerza el skip si falta configuración
    with TestClient(app) as c:
        yield c


# ── Autenticación en la frontera HTTP ─────────────────────────────────────────

def test_health_needs_no_authentication(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_request_without_jwt_is_rejected(client):
    response = client.get("/diagnostics/identity")
    assert response.status_code == 401


@pytest.mark.parametrize(
    "header",
    ["", "Bearer", "Bearer ", "Token abc", "abc.def.ghi", "Basic dXNlcjpwYXNz"],
)
def test_malformed_authorization_is_rejected(client, header):
    response = client.get("/diagnostics/identity", headers={"Authorization": header})
    assert response.status_code == 401


def test_invalid_jwt_is_rejected(client):
    response = client.get(
        "/diagnostics/identity",
        headers={"Authorization": "Bearer eyJhbGciOiJFUzI1NiJ9.invalido.firma"},
    )
    assert response.status_code == 401


def test_rejection_does_not_leak_internals(client):
    response = client.get(
        "/diagnostics/identity", headers={"Authorization": "Bearer no-es-un-jwt"}
    )
    assert response.status_code == 401
    body = response.text.lower()
    for leak in ("postgres", "password", "app_backend", "traceback", "psycopg"):
        assert leak not in body


# ── Identidad propagada hasta PostgreSQL ──────────────────────────────────────

def test_user_a_identity_reaches_postgres(client, user_a):
    response = client.get(
        "/diagnostics/identity", headers={"Authorization": f"Bearer {user_a.token}"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_user_id"] == user_a.id
    assert body["db_user_id"] == user_a.id, "RLS no vio la identidad del token"
    assert body["db_role"] == "authenticated"


def test_user_b_identity_reaches_postgres(client, user_b):
    response = client.get(
        "/diagnostics/identity", headers={"Authorization": f"Bearer {user_b.token}"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["db_user_id"] == user_b.id


# ── Aislamiento entre tenants ─────────────────────────────────────────────────

def test_user_a_sees_own_company(client, user_a):
    response = client.get(
        "/diagnostics/identity", headers={"Authorization": f"Bearer {user_a.token}"}
    )
    ids = {c["id"] for c in response.json()["companies"]}
    assert user_a.company_id in ids


def test_user_b_does_not_see_company_of_user_a(client, user_a, user_b):
    response = client.get(
        "/diagnostics/identity", headers={"Authorization": f"Bearer {user_b.token}"}
    )
    ids = {c["id"] for c in response.json()["companies"]}
    assert user_a.company_id not in ids


def test_control_user_b_can_operate_in_own_tenant(client, user_b):
    """CONTROL POSITIVO. Convierte 'B no ve nada' en 'B no ve lo ajeno'."""
    response = client.get(
        "/diagnostics/identity", headers={"Authorization": f"Bearer {user_b.token}"}
    )
    assert response.status_code == 200
    ids = {c["id"] for c in response.json()["companies"]}
    assert user_b.company_id in ids, "B no puede operar en su propio tenant"


def test_same_endpoint_returns_different_data_per_user(client, user_a, user_b):
    """La respuesta depende del token, no del endpoint."""
    a = client.get(
        "/diagnostics/identity", headers={"Authorization": f"Bearer {user_a.token}"}
    ).json()
    b = client.get(
        "/diagnostics/identity", headers={"Authorization": f"Bearer {user_b.token}"}
    ).json()

    ids_a = {c["id"] for c in a["companies"]}
    ids_b = {c["id"] for c in b["companies"]}

    assert a["db_user_id"] != b["db_user_id"]
    assert user_a.company_id in ids_a and user_a.company_id not in ids_b
    assert user_b.company_id in ids_b and user_b.company_id not in ids_a
