"""Fixtures compartidas del backend.

CONSUMO DE CUOTA DE AUTH
    El proyecto de DESARROLLO tiene `sign_in_sign_ups = 30` por 5 minutos e IP.
    Los usuarios de prueba se crean UNA sola vez por sesión de pytest (scope
    "session") y se reutilizan en todos los tests. Ver ADR-018.

FALLO RÁPIDO
    Cualquier fallo de preparación aborta con la causa original visible; ningún
    test continúa con identificadores vacíos.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass

import httpx
import pytest

from app.config import ConfigError, get_settings
from app.db import create_pool


class SetupError(RuntimeError):
    """Fallo de preparación. Aborta la suite con la causa visible."""


def _rate_limit_hint(response: httpx.Response) -> str:
    if response.status_code == 429 or "rate limit" in response.text.lower():
        return (
            "\n  >>> LÍMITE DE TASA DE SUPABASE AUTH alcanzado."
            "\n      [auth.rate_limit] sign_in_sign_ups = 30 por 5 minutos e IP."
            "\n      Espera unos minutos antes de reejecutar la suite."
        )
    return ""


@dataclass(frozen=True)
class TestUser:
    id: str
    email: str
    password: str
    token: str
    company_id: str
    company_name: str


@pytest.fixture(scope="session")
def settings():
    try:
        return get_settings()
    except ConfigError as exc:
        pytest.skip(f"Backend sin configurar: {exc}")


@pytest.fixture(scope="session")
def publishable_key() -> str:
    key = os.environ.get("SUPABASE_PUBLISHABLE_KEY", "").strip()
    if not key:
        pytest.skip("Falta SUPABASE_PUBLISHABLE_KEY en backend/.env.local")
    if key.startswith("sb_secret_") or key.startswith("ey"):
        raise SetupError("SUPABASE_PUBLISHABLE_KEY no es una clave publicable.")
    return key


@pytest.fixture(scope="session")
def pool(settings):
    try:
        p = create_pool(settings)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"No se pudo abrir el pool: {exc}")
    yield p
    p.close()


def _create_user(base_url: str, apikey: str, label: str) -> TestUser:
    """Crea un usuario y su empresa. Aborta con causa visible si algo falla."""
    run_id = uuid.uuid4().hex[:10]
    email = f"be-{label}-{run_id}@example.com"
    password = f"PwBe-{run_id}-x9"

    with httpx.Client(base_url=base_url, timeout=30.0) as client:
        signup = client.post(
            "/auth/v1/signup",
            headers={"apikey": apikey, "Content-Type": "application/json"},
            json={"email": email, "password": password},
        )
        if signup.status_code != 200:
            raise SetupError(
                f"signUp de {label} falló: HTTP {signup.status_code} "
                f"{signup.text[:160]}{_rate_limit_hint(signup)}"
            )
        body = signup.json()
        token = body.get("access_token")
        user_id = (body.get("user") or {}).get("id")
        if not token or not user_id:
            raise SetupError(
                f"signUp de {label} no devolvió sesión. "
                "Revisa que enable_confirmations = false en desarrollo (ADR-019)."
            )

        company_name = f"Backend {label} {run_id}"
        created = client.post(
            "/rest/v1/rpc/create_company",
            headers={
                "apikey": apikey,
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={"p_name": company_name},
        )
        if created.status_code != 200:
            raise SetupError(
                f"create_company de {label} falló: HTTP {created.status_code} "
                f"{created.text[:160]}"
            )
        company_id = created.json().get("id")
        if not company_id:
            raise SetupError(f"create_company de {label} no devolvió id.")

    return TestUser(
        id=user_id,
        email=email,
        password=password,
        token=token,
        company_id=company_id,
        company_name=company_name,
    )


@pytest.fixture(scope="session")
def user_a(settings, publishable_key) -> TestUser:
    return _create_user(settings.supabase_url, publishable_key, "a")


@pytest.fixture(scope="session")
def user_b(settings, publishable_key) -> TestUser:
    return _create_user(settings.supabase_url, publishable_key, "b")


@pytest.fixture(scope="session")
def single_connection_pool(settings):
    """Pool de UNA sola conexión: fuerza la reutilización de la misma sesión.

    Es el escenario contra el que ADR-012 exige protección.
    """
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool

    p = ConnectionPool(
        conninfo=settings.database_url,
        min_size=1,
        max_size=1,
        open=True,
        kwargs={"row_factory": dict_row},
    )
    yield p
    p.close()
