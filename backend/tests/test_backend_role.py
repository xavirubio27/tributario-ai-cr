"""Atributos y privilegios del rol PostgreSQL del backend (ADR-012).

Se comprueban contra la base de datos real, no contra el texto de la migración.
"""

from __future__ import annotations

import pytest

from app.db import anonymous_transaction

ROLE = "app_backend"


@pytest.fixture(scope="module")
def role_row(pool, settings):
    with anonymous_transaction(pool, settings) as conn:
        row = conn.execute(
            """
            select rolname, rolsuper, rolbypassrls, rolcanlogin,
                   rolinherit, rolcreaterole, rolcreatedb, rolreplication
            from pg_roles where rolname = %s
            """,
            (ROLE,),
        ).fetchone()
    if row is None:
        pytest.fail(f"El rol {ROLE} no existe. ¿Se aplicó la migración?")
    return row


def test_role_exists(role_row):
    assert role_row["rolname"] == ROLE


def test_role_has_no_bypassrls(role_row):
    """REQUISITO DE ADR-012. Con BYPASSRLS el aislamiento no existiría."""
    assert role_row["rolbypassrls"] is False


def test_role_is_not_superuser(role_row):
    assert role_row["rolsuper"] is False


def test_role_cannot_create_roles_or_databases(role_row):
    assert role_row["rolcreaterole"] is False
    assert role_row["rolcreatedb"] is False


def test_role_is_noinherit(role_row):
    """Sin herencia no arrastra privilegios de forma ambiental."""
    assert role_row["rolinherit"] is False


def test_role_can_login(role_row):
    assert role_row["rolcanlogin"] is True


def test_role_memberships_are_minimal(pool, settings):
    """Exactamente `authenticated` y `fiscal_backend`, y sin herencia.

    ADR-020 añadió `fiscal_backend` a las pertenencias de `app_backend`. La
    aserción se amplía, pero NO se debilita: además del conjunto exacto se exige
    ahora que ninguna pertenencia se herede automáticamente. Una pertenencia con
    `inherit_option=true` daría a toda conexión del pool los privilegios del rol
    fiscal sin haberlos pedido, que es justo lo que la frontera evita.
    """
    with anonymous_transaction(pool, settings) as conn:
        rows = conn.execute(
            """
            select m.rolname as member_of,
                   am.inherit_option, am.set_option, am.admin_option
            from pg_auth_members am
            join pg_roles r on r.oid = am.member
            join pg_roles m on m.oid = am.roleid
            where r.rolname = %s
            """,
            (ROLE,),
        ).fetchall()
    memberships = {r["member_of"] for r in rows}
    assert memberships == {"authenticated", "fiscal_backend"}
    assert "service_role" not in memberships
    assert "anon" not in memberships

    for row in rows:
        assert row["inherit_option"] is False, f"{row['member_of']} se hereda sin pedirlo."
        assert row["set_option"] is True, f"{row['member_of']} no se puede asumir con SET ROLE."
        assert row["admin_option"] is False, f"{ROLE} puede conceder {row['member_of']} a otros."


def test_role_cannot_reach_service_role(pool, settings):
    """Control explícito: no puede escalar a un rol con BYPASSRLS."""
    with anonymous_transaction(pool, settings) as conn:
        row = conn.execute(
            "select pg_has_role(%s, 'service_role', 'MEMBER') as can_assume", (ROLE,)
        ).fetchone()
    assert row["can_assume"] is False


def test_role_has_no_direct_table_grants(pool, settings):
    """Todo acceso ocurre tras asumir `authenticated`, bajo RLS."""
    with anonymous_transaction(pool, settings) as conn:
        row = conn.execute(
            "select count(*) as n from information_schema.role_table_grants where grantee = %s",
            (ROLE,),
        ).fetchone()
    assert row["n"] == 0


def test_application_connects_as_backend_role_not_privileged(pool, settings):
    """La aplicación se conecta como `app_backend`, no como postgres ni service_role."""
    with pool.connection() as conn:
        row = conn.execute("select session_user::text as who").fetchone()
    assert row["who"] == ROLE
    assert row["who"] not in ("postgres", "service_role", "supabase_admin")


def test_effective_role_inside_transaction_is_authenticated(pool, settings, user_a):
    """Dentro de la transacción de usuario el rol efectivo es `authenticated`."""
    from app.db import user_transaction

    with user_transaction(pool, settings, user_a.identity) as conn:
        row = conn.execute(
            "select current_user::text as effective, session_user::text as login_role"
        ).fetchone()
    assert row["effective"] == "authenticated"
    assert row["login_role"] == ROLE



# ── Verificación en runtime (defensa en profundidad) ──────────────────────────

def test_runtime_verification_passes_against_real_database(pool):
    """`verify_backend_role` no lanza contra la base de datos real."""
    from app.db import verify_backend_role

    verify_backend_role(pool)  # no debe lanzar


def test_runtime_verification_rejects_wrong_session_user(pool, monkeypatch):
    """Si la sesión no fuera `app_backend`, el backend no debe arrancar."""
    from app import db as db_module
    from app.db import RoleVerificationError, verify_backend_role

    monkeypatch.setattr(db_module, "BACKEND_DB_ROLE", "un_rol_que_no_es_el_nuestro")
    with pytest.raises(RoleVerificationError, match="se exige"):
        verify_backend_role(pool)


def test_runtime_verification_rejects_unexpected_memberships(pool, monkeypatch):
    """Una pertenencia extra debe impedir el arranque."""
    from app import db as db_module
    from app.db import RoleVerificationError, verify_backend_role

    # Se estrecha lo permitido para simular "hay una pertenencia que no toca".
    monkeypatch.setattr(db_module, "_ALLOWED_MEMBERSHIPS", frozenset())
    with pytest.raises(RoleVerificationError, match="Pertenencias inesperadas"):
        verify_backend_role(pool)


def test_runtime_verification_checks_required_attributes(pool, monkeypatch):
    """Un atributo distinto del esperado debe impedir el arranque."""
    from app import db as db_module
    from app.db import RoleVerificationError, verify_backend_role

    monkeypatch.setattr(
        db_module,
        "_REQUIRED_ROLE_ATTRIBUTES",
        {**db_module._REQUIRED_ROLE_ATTRIBUTES, "rolbypassrls": True},
    )
    with pytest.raises(RoleVerificationError, match="atributos incorrectos"):
        verify_backend_role(pool)


def test_runtime_verification_detects_reachable_privileged_role(pool, monkeypatch):
    """Si el rol pudiera asumir uno privilegiado, debe detectarse."""
    from app import db as db_module
    from app.db import RoleVerificationError, verify_backend_role

    # `authenticated` SÍ es alcanzable: tratarlo como prohibido debe disparar.
    monkeypatch.setattr(db_module, "_FORBIDDEN_REACHABLE_ROLES", ("authenticated",))
    with pytest.raises(RoleVerificationError, match="puede asumir"):
        verify_backend_role(pool)
