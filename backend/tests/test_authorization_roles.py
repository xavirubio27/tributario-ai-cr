"""Checkpoint C — roles de autorización (ADR-015).

Demuestra que `company_memberships` es la única fuente de verdad de pertenencia y
rol, que existen exactamente los tres roles del MVP, y que un mismo usuario puede
tener roles distintos en empresas distintas.

NO prueba permisos fiscales: no existen tablas fiscales todavía.
"""

from __future__ import annotations

import uuid

import psycopg
import pytest

from app.authorization import (
    CompanyMembership,
    CompanyRole,
    get_company_membership,
    list_company_memberships,
)
from app.db import user_transaction


def _membership_of(pool, settings, user, company_id):
    """Abre la transacción con la identidad verificada y consulta el helper."""
    with user_transaction(pool, settings, user.identity) as conn:
        return get_company_membership(conn, company_id)


def _memberships_of(pool, settings, user):
    with user_transaction(pool, settings, user.identity) as conn:
        return list_company_memberships(conn)


# ── Conjunto de roles ─────────────────────────────────────────────────────────

def test_mvp_roles_are_exactly_three():
    assert {r.value for r in CompanyRole} == {"owner", "editor", "viewer"}


def _role_check_definition(pool, settings) -> str:
    """Lee el CHECK por el pool normal: los catálogos son legibles sin la CLI."""
    from app.db import anonymous_transaction

    with anonymous_transaction(pool, settings) as conn:
        row = conn.execute(
            """
            select pg_get_constraintdef(con.oid) as def
            from pg_constraint con
            join pg_class rel on rel.oid = con.conrelid
            where rel.relname = 'company_memberships'
              and con.conname = 'company_memberships_role_check'
            """
        ).fetchone()
    assert row is not None, "No existe company_memberships_role_check"
    return row["def"]


def _allowed_roles_in_check(pool, settings) -> set[str]:
    """Conjunto EXACTO de literales que el CHECK admite.

    Extrae todos los literales de la expresión normalizada por PostgreSQL, en
    lugar de comprobar que ciertas palabras aparecen. La diferencia importa: un
    CHECK que además aceptara `manager` superaría una prueba de contención, pero
    falla la de igualdad de conjuntos.
    """
    import re

    definition = _role_check_definition(pool, settings)
    return set(re.findall(r"'([^']*)'::text", definition))


def test_check_domain_is_exactly_the_mvp_roles(pool, settings):
    """El dominio permitido es EXACTAMENTE {owner, editor, viewer}."""
    assert _allowed_roles_in_check(pool, settings) == {"owner", "editor", "viewer"}


def test_role_enum_matches_database_constraint(pool, settings):
    """Igualdad de conjuntos entre el enum de Python y el CHECK de PostgreSQL.

    Falla si cualquiera de los dos lados añade o elimina un rol sin actualizar el
    otro.
    """
    assert _allowed_roles_in_check(pool, settings) == {r.value for r in CompanyRole}


@pytest.mark.parametrize("role", ["owner", "editor", "viewer"])
def test_valid_roles_accepted_by_constraint(pool, settings, role):
    """Los tres roles del MVP están en el dominio del CHECK."""
    assert role in _allowed_roles_in_check(pool, settings)


# ── Roles inválidos: se exige la CAUSA concreta ───────────────────────────────

@pytest.mark.parametrize("role", ["manager", "admin", "superuser", "OWNER", "", "root", "editor "])
def test_invalid_roles_rejected_with_check_violation(admin_sql, user_a, role):
    """Rechazo por violación de CHECK, con SQLSTATE 23514 y constraint concreto.

    HALLAZGO CORREGIDO (auditoría, severidad MEDIUM)
        Antes se capturaba `Exception` y se contaba como PASS. Un timeout, un
        fallo de DNS, un error de autenticación o un fallo de la CLI habrían dado
        un falso verde. Ahora se exige el error exacto de PostgreSQL: cualquier
        otra causa hace FALLAR el test.
    """
    from conftest import AdminSqlError

    safe = role.replace("'", "''")
    with pytest.raises(AdminSqlError) as excinfo:
        admin_sql(
            "insert into public.company_memberships (company_id, user_id, role) "
            f"values ('{user_a.company_id}', '{user_a.id}', '{safe}')"
        )

    error = excinfo.value
    assert error.sqlstate == "23514", (
        f"Se esperaba una violación de CHECK (23514) y se obtuvo "
        f"{error.sqlstate!r}: {error}"
    )
    assert error.constraint == "company_memberships_role_check", (
        f"Violado un constraint distinto: {error.constraint!r}"
    )


def test_valid_role_does_not_trigger_check_violation(admin_sql, user_b, seed_role):
    """CONTROL: un rol válido NO produce 23514.

    Sin este control, los tests anteriores podrían pasar porque toda escritura
    fallara por cualquier motivo.
    """
    from conftest import AdminSqlError

    try:
        seed_role(user_b.company_id, user_b.id, "editor")
    except AdminSqlError as exc:  # pragma: no cover
        pytest.fail(f"Un rol válido fue rechazado: {exc.sqlstate} {exc}")
    finally:
        seed_role(user_b.company_id, user_b.id, "owner")


# ── Membresía y rol por usuario ───────────────────────────────────────────────

def test_owner_membership_is_reported(pool, settings, user_a):
    """User A creó su empresa: es `owner`."""
    membership = _membership_of(pool, settings, user_a, user_a.company_id)
    assert membership is not None
    assert membership.role is CompanyRole.OWNER
    assert membership.user_id == user_a.id
    assert membership.company_id == user_a.company_id


def test_editor_membership_is_reported(pool, settings, user_b, seed_role):
    """User B en su empresa, degradado a `editor`."""
    seed_role(user_b.company_id, user_b.id, "editor")
    try:
        membership = _membership_of(pool, settings, user_b, user_b.company_id)
        assert membership is not None
        assert membership.role is CompanyRole.EDITOR
    finally:
        seed_role(user_b.company_id, user_b.id, "owner")


def test_viewer_membership_is_reported(pool, settings, user_b, seed_role):
    """User B en su empresa, degradado a `viewer`."""
    seed_role(user_b.company_id, user_b.id, "viewer")
    try:
        membership = _membership_of(pool, settings, user_b, user_b.company_id)
        assert membership is not None
        assert membership.role is CompanyRole.VIEWER
    finally:
        seed_role(user_b.company_id, user_b.id, "owner")


def test_each_user_gets_only_their_real_role(pool, settings, user_a, user_b, seed_role):
    """A es owner de la suya; B es viewer de la suya. Ninguno hereda el del otro."""
    seed_role(user_b.company_id, user_b.id, "viewer")
    try:
        a = _membership_of(pool, settings, user_a, user_a.company_id)
        b = _membership_of(pool, settings, user_b, user_b.company_id)
        assert a.role is CompanyRole.OWNER
        assert b.role is CompanyRole.VIEWER
    finally:
        seed_role(user_b.company_id, user_b.id, "owner")


# ── Roles distintos en empresas distintas ─────────────────────────────────────

def test_same_user_can_hold_different_roles_in_different_companies(
    pool, settings, user_a, user_b, seed_role, admin_sql
):
    """A: owner en su empresa, viewer en la de B. Sin conflicto (ADR-015)."""
    admin_sql(
        "insert into public.company_memberships (company_id, user_id, role) "
        f"values ('{user_b.company_id}', '{user_a.id}', 'viewer') "
        "on conflict (company_id, user_id) do update set role = 'viewer'"
    )
    try:
        propia = _membership_of(pool, settings, user_a, user_a.company_id)
        ajena = _membership_of(pool, settings, user_a, user_b.company_id)

        assert propia.role is CompanyRole.OWNER
        assert ajena.role is CompanyRole.VIEWER
        assert propia.company_id != ajena.company_id

        todas = _memberships_of(pool, settings, user_a)
        por_empresa = {m.company_id: m.role for m in todas}
        assert por_empresa[user_a.company_id] is CompanyRole.OWNER
        assert por_empresa[user_b.company_id] is CompanyRole.VIEWER
    finally:
        admin_sql(
            "delete from public.company_memberships "
            f"where company_id = '{user_b.company_id}' and user_id = '{user_a.id}'"
        )


# ── Ausencia de membresía ─────────────────────────────────────────────────────

def test_no_membership_yields_none_not_a_default_role(pool, settings, user_b, user_a):
    """Sin fila en `company_memberships` no hay rol: no se inventa `viewer`."""
    membership = _membership_of(pool, settings, user_b, user_a.company_id)
    assert membership is None


def test_nonexistent_company_yields_none(pool, settings, user_a):
    membership = _membership_of(pool, settings, user_a, str(uuid.uuid4()))
    assert membership is None


# ── La autoridad no puede falsificarse ────────────────────────────────────────

def test_application_cannot_write_memberships(pool, settings, user_a):
    """La app no puede crear ni cambiar memberships: la autoridad no se auto-otorga."""
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with user_transaction(pool, settings, user_a.identity) as conn:
            conn.execute(
                "insert into public.company_memberships (company_id, user_id, role) "
                "values (%s, %s, 'owner')",
                (str(uuid.uuid4()), user_a.id),
            )


def test_application_cannot_escalate_own_role(pool, settings, user_b, seed_role):
    """Un viewer no puede convertirse en owner por sí mismo."""
    seed_role(user_b.company_id, user_b.id, "viewer")
    try:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with user_transaction(pool, settings, user_b.identity) as conn:
                conn.execute(
                    "update public.company_memberships set role = 'owner' "
                    "where company_id = %s and user_id = %s",
                    (user_b.company_id, user_b.id),
                )
        # Y sigue siendo viewer.
        membership = _membership_of(pool, settings, user_b, user_b.company_id)
        assert membership.role is CompanyRole.VIEWER
    finally:
        seed_role(user_b.company_id, user_b.id, "owner")


def test_membership_comes_from_database_not_from_arguments(pool, settings, user_b, seed_role):
    """El helper no tiene por dónde recibir un rol ni una identidad.

    Tras la corrección de la auditoría, la firma es `(conn, company_id)`: la
    identidad viaja en la conexión ya contextualizada, no como argumento.
    """
    import inspect

    params = set(inspect.signature(get_company_membership).parameters)
    assert params == {"conn", "company_id"}
    assert "role" not in params
    assert "user_id" not in params

    seed_role(user_b.company_id, user_b.id, "viewer")
    try:
        membership = _membership_of(pool, settings, user_b, user_b.company_id)
        assert membership.role is CompanyRole.VIEWER
    finally:
        seed_role(user_b.company_id, user_b.id, "owner")


def test_membership_is_a_frozen_dataclass():
    """No se puede mutar un rol ya resuelto."""
    m = CompanyMembership(company_id="c", user_id="u", role=CompanyRole.VIEWER)
    with pytest.raises(Exception):
        m.role = CompanyRole.OWNER  # type: ignore[misc]
