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

import json
import os
import re
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest

from app.auth import AuthenticatedUser, JwtVerifier
from app.config import ConfigError, get_settings
from app.db import create_pool


class SetupError(RuntimeError):
    """Fallo de preparación. Aborta la suite con la causa visible."""


class AdminSqlError(RuntimeError):
    """Error devuelto por PostgreSQL al ejecutar SQL de preparación.

    Expone el SQLSTATE y el constraint implicado para que un test pueda afirmar
    la CAUSA concreta. Sin esto, un `except Exception` contaría como PASS un
    timeout, un fallo de DNS o un error de la CLI.
    """

    def __init__(self, message: str, sqlstate: str | None, constraint: str | None) -> None:
        super().__init__(message)
        self.sqlstate = sqlstate
        self.constraint = constraint


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
    # Identidad verificada, obtenida del token real a través del verificador.
    # Los tests NO fabrican identidades: pasan por el mismo camino que producción.
    identity: "AuthenticatedUser"


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
    """Pool del backend.

    SOLO se omite la suite si el entorno no está configurado. Cualquier otro
    fallo —credenciales inválidas, verificación de rol fallida, red— es un
    problema real y debe FALLAR, no convertirse en un skip que parezca inocuo.
    """
    try:
        p = create_pool(settings)
    except ConfigError as exc:
        pytest.skip(f"Backend sin configurar: {exc}")
    yield p
    p.close()


def _create_user(base_url: str, apikey: str, label: str, settings=None) -> TestUser:
    """Crea un usuario y su empresa. Aborta con causa visible si algo falla."""
    run_id = uuid.uuid4().hex[:10]
    email = f"be-{label}-{run_id}@example.com"
    password = f"PwBe-{run_id}-x9"

    # Timeout de RED para la preparación, no un límite de seguridad. El proyecto
    # Supabase de desarrollo responde a veces en decenas de segundos y con 30 s la
    # creación del usuario expiraba antes de terminar, marcando ERROR en fixture
    # todos los tests que dependen de una identidad real.
    with httpx.Client(base_url=base_url, timeout=120.0) as client:
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

    # La identidad se obtiene verificando el token real: mismo camino que producción.
    identity = JwtVerifier(settings).verify(token) if settings else None

    return TestUser(
        id=user_id,
        email=email,
        password=password,
        token=token,
        company_id=company_id,
        company_name=company_name,
        identity=identity,
    )


# Tablas fiscales que llevan `company_id` y de las que se borra directamente.
# Las hijas del agregado (`document_parties`, `document_lines`, `line_discounts`,
# `line_taxes`, `document_references`) desaparecen por CASCADE al borrar el
# documento, asi que no se enumeran: hacerlo duplicaria el borrado sin anadir
# garantia.
#
# `source_documents` va PRIMERO: su enlace al documento normalizado es
# ON DELETE SET NULL, de modo que borrar el documento antes solo dejaria el
# artefacto huerfano en lugar de retirarlo.
_FISCAL_ROOTS = ("source_documents", "electronic_documents")


def _cleanup_user(user: "TestUser") -> None:
    """Retira EXCLUSIVAMENTE lo que creo esta ejecucion, por UUID exacto.

    Nunca se borra por prefijo de nombre ni sin predicado: un `delete` sin
    ambito podria arrasar datos de otra ejecucion concurrente, de otro test o
    de un desarrollador trabajando contra el mismo proyecto DEV.

    El orden lo imponen las claves foraneas reales, no la intuicion:

        filas fiscales de esa empresa   companies.id <- fiscal.* es RESTRICT
                 |
        la empresa                      la membership cae por CASCADE
                 |
        el usuario de Auth              companies.created_by es RESTRICT

    Invertir cualquiera de los dos pasos hace fallar el borrado.
    """
    if user is None:
        return
    sentencias = [
        f"delete from fiscal.{t} where company_id = '{user.company_id}'"
        for t in _FISCAL_ROOTS
    ]
    # La membership cae por CASCADE al borrar la empresa; se deja explicito
    # por si alguna vez se anadiera una membership adicional a mano.
    sentencias += [
        f"delete from public.company_memberships where company_id = '{user.company_id}'",
        f"delete from public.companies where id = '{user.company_id}'",
        f"delete from auth.users where id = '{user.id}'",
    ]
    for sql in sentencias:
        try:
            _admin_sql(sql)
        except Exception as exc:  # noqa: BLE001 - el teardown nunca debe enmascarar el fallo del test
            print(f"[teardown] no se pudo ejecutar {sql!r}: {exc}")


@pytest.fixture(scope="session")
def user_a(settings, publishable_key) -> TestUser:
    user = _create_user(settings.supabase_url, publishable_key, "a", settings)
    try:
        yield user
    finally:
        # `finally` y no codigo tras el `yield` a secas: el teardown debe
        # ejecutarse tambien cuando un test falla o lanza.
        _cleanup_user(user)


@pytest.fixture(scope="session")
def user_b(settings, publishable_key) -> TestUser:
    user = _create_user(settings.supabase_url, publishable_key, "b", settings)
    try:
        yield user
    finally:
        _cleanup_user(user)


@pytest.fixture(scope="session")
def cleanup_user():
    """Expone el borrador acotado para tests que crean su propio usuario."""
    return _cleanup_user


@pytest.fixture(scope="session")
def single_connection_pool(settings):
    """Pool de UNA sola conexión: fuerza la reutilización de la misma sesión.

    Es el escenario contra el que ADR-012 exige protección.
    """
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool

    # `timeout` generoso a propósito: durante la suite conviven varios pools
    # -- el de sesión, este, y el que abre cada `TestClient(app)` por su lifespan --
    # compitiendo por el pooler. Con 30 s por defecto, la adquisición podía agotar
    # el plazo y hacer fallar tests cuyas propiedades sí se cumplen (verificado:
    # pasan 6/6 en aislamiento). Es holgura del arnés, no una aserción relajada.
    p = ConnectionPool(
        conninfo=settings.database_url,
        min_size=1,
        max_size=1,
        timeout=120,
        open=True,
        kwargs={"row_factory": dict_row},
    )
    yield p
    p.close()


# ── Sembrado de roles para fixtures ───────────────────────────────────────────
#
# La APLICACIÓN no puede crear ni modificar memberships: `authenticated` no tiene
# INSERT/UPDATE sobre `company_memberships` y no existe política que lo permita.
# Esa es una propiedad de seguridad deliberada, y hay un test que la comprueba.
#
# Pero los tests necesitan membresías `editor` y `viewer` para demostrar los tres
# roles. Se siembran por FUERA de la aplicación, con la CLI de Supabase, igual que
# se sembraría cualquier dato de prueba.
#
# La CLI es LENTA (segundos por invocación) y ocasionalmente agota el tiempo, así
# que se reserva para las ESCRITURAS. Toda lectura -- catálogos incluidos -- se
# hace con el pool normal, que además ejercita el camino real de la aplicación.
#
# Esto NO es la aplicación usando privilegios elevados: la aplicación jamás
# ejecuta esta ruta. Cuando exista administración de miembros -- checkpoint
# futuro -- necesitará su propio camino controlado y auditable.

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SUPABASE_CLI = _REPO_ROOT / "node_modules" / ".bin" / "supabase"


def _admin_sql(sql: str) -> list[dict]:
    """Ejecuta SQL de preparación fuera de la aplicación. Solo para fixtures."""
    if not _SUPABASE_CLI.exists():
        pytest.skip("CLI de Supabase no disponible para sembrar fixtures")

    result = subprocess.run(
        [str(_SUPABASE_CLI), "db", "query", "--linked", sql],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
        timeout=180,
    )
    combined = result.stdout + result.stderr

    # La CLI devuelve exit 0 incluso con error SQL; hay que mirar el cuerpo.
    if result.returncode != 0 or '"_tag":"Error"' in combined or '"_tag": "Error"' in combined:
        sqlstate = None
        constraint = None
        m = re.search(r"ERROR:\s+(\d{5}):", combined)
        if m:
            sqlstate = m.group(1)
        m = re.search(r'violates check constraint \\+"([^"\\]+)', combined)
        if m:
            constraint = m.group(1)
        raise AdminSqlError(combined[:400], sqlstate, constraint)

    start = result.stdout.find("{")
    if start < 0:
        return []
    return json.loads(result.stdout[start:]).get("rows", [])


@pytest.fixture(scope="session")
def seed_role():
    """Asigna un rol concreto a una membership existente. Solo preparación."""

    def _seed(company_id: str, user_id: str, role: str) -> None:
        _admin_sql(
            "update public.company_memberships "
            f"set role = '{role}' "
            f"where company_id = '{company_id}' and user_id = '{user_id}'"
        )

    return _seed


@pytest.fixture(scope="session")
def admin_sql():
    """SQL de preparación sin pasar por la aplicación. Solo para fixtures."""
    return _admin_sql
