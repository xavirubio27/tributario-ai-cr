"""Privilegios EFECTIVOS de `app_backend`, no solo filas en `information_schema`.

POR QUÉ ESTE ARCHIVO EXISTE (hallazgo de auditoría)

    `REVOKE ... FROM app_backend` no elimina privilegios concedidos a `PUBLIC`.
    Contar filas en `information_schema.role_table_grants` puede dar cero y aun
    así el rol tener acceso por esa vía.

    `has_table_privilege` / `has_schema_privilege` / `has_function_privilege` sí
    responden a la pregunta que importa: qué puede hacer el rol **de verdad**,
    antes de asumir `authenticated`.

AFIRMACIÓN CALIBRADA
    No se afirma "cero acceso ambiental": `USAGE` sobre el schema `public` sigue
    concedido vía `PUBLIC` y no se revoca, porque hacerlo afectaría a otros roles.
    Lo que sí se exige es que las TABLAS de tenancy y las FUNCIONES sensibles
    sean inalcanzables sin el `SET LOCAL ROLE`.
"""

from __future__ import annotations

import pytest

from app.config import BACKEND_DB_ROLE
from app.db import anonymous_transaction

TENANCY_TABLES = ("public.companies", "public.company_memberships")
PRIVILEGES = ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE")


@pytest.mark.parametrize("table", TENANCY_TABLES)
@pytest.mark.parametrize("privilege", PRIVILEGES)
def test_backend_role_has_no_effective_table_privilege(pool, settings, table, privilege):
    """Sin asumir `authenticated`, el rol no puede tocar las tablas de tenancy."""
    with anonymous_transaction(pool, settings) as conn:
        row = conn.execute(
            "select has_table_privilege(%s, %s, %s) as allowed",
            (BACKEND_DB_ROLE, table, privilege),
        ).fetchone()
    assert row["allowed"] is False, (
        f"{BACKEND_DB_ROLE} puede {privilege} sobre {table} sin asumir authenticated"
    )


def test_control_authenticated_does_have_select(pool, settings):
    """CONTROL: `authenticated` sí puede leer.

    Sin este control, los tests anteriores podrían pasar porque el instrumento
    devuelve False para todo.
    """
    with anonymous_transaction(pool, settings) as conn:
        row = conn.execute(
            "select has_table_privilege('authenticated', 'public.companies', 'SELECT') as allowed"
        ).fetchone()
    assert row["allowed"] is True


@pytest.mark.parametrize("schema", ["auth", "private"])
def test_backend_role_cannot_use_sensitive_schemas(pool, settings, schema):
    with anonymous_transaction(pool, settings) as conn:
        row = conn.execute(
            "select has_schema_privilege(%s, %s, 'USAGE') as allowed",
            (BACKEND_DB_ROLE, schema),
        ).fetchone()
    assert row["allowed"] is False


@pytest.mark.parametrize(
    "function",
    [
        "public.create_company(text)",
        "private.create_company_impl(text)",
        "private.is_company_member(uuid)",
    ],
)
def test_backend_role_cannot_execute_sensitive_functions(pool, settings, function):
    with anonymous_transaction(pool, settings) as conn:
        row = conn.execute(
            "select has_function_privilege(%s, %s, 'EXECUTE') as allowed",
            (BACKEND_DB_ROLE, function),
        ).fetchone()
    assert row["allowed"] is False


def test_public_schema_usage_is_documented_not_asserted_away(pool, settings):
    """Deja constancia del `USAGE` que llega vía PUBLIC.

    No se revoca: hacerlo a `PUBLIC` afectaría a otros roles. Se registra para
    que la documentación no afirme más de lo que es cierto.
    """
    with anonymous_transaction(pool, settings) as conn:
        row = conn.execute(
            "select has_schema_privilege(%s, 'public', 'USAGE') as usage_granted",
            (BACKEND_DB_ROLE,),
        ).fetchone()
    assert isinstance(row["usage_granted"], bool)
