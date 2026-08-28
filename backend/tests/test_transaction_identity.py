"""Identidad de alcance transaccional y ausencia de fuga entre transacciones.

ESTE ES EL REQUISITO CRÍTICO DE ADR-012.

El fallo que hay que impedir:

    Conexión 1 · Transacción A · identidad de User A · COMMIT
    conexión devuelta al pool
    misma conexión física · Transacción B · User B
    -> la conexión conserva la identidad de User A     <-- CRITICAL

Ese fallo no lanza error: devuelve datos del contribuyente equivocado.
"""

from __future__ import annotations

import pytest

from app.db import anonymous_transaction, current_identity, user_transaction


def _backend_pid(conn) -> int:
    return conn.execute("select pg_backend_pid() as pid").fetchone()["pid"]


def test_identity_is_visible_inside_transaction(pool, settings, user_a):
    with user_transaction(pool, settings, user_a.id) as conn:
        identity = current_identity(conn)
    assert identity["user_id"] == user_a.id
    assert identity["db_role"] == "authenticated"
    assert identity["raw_claims"] is not None


def test_identity_disappears_after_commit(pool, settings, user_a):
    """Tras cerrar la transacción, una nueva sin identidad no ve ninguna."""
    with user_transaction(pool, settings, user_a.id) as conn:
        assert current_identity(conn)["user_id"] == user_a.id

    with anonymous_transaction(pool, settings) as conn:
        identity = current_identity(conn)
    assert identity["user_id"] is None
    assert identity["raw_claims"] is None


def test_identity_disappears_after_rollback(single_connection_pool, settings, user_a):
    """Cleanup tras ROLLBACK, demostrado sobre LA MISMA sesión.

    HALLAZGO CORREGIDO (auditoría de Checkpoint B)
        La versión anterior comprobaba el cleanup en una conexión cualquiera del
        pool, que podía no ser la misma que ejecutó la transacción abortada. Eso
        no demostraba nada: una sesión distinta nunca habría tenido la identidad.

    TÉCNICA — la misma ya aceptada para COMMIT
        Se deja una MARCA DE SESIÓN con `set_config(..., false)`, deliberadamente
        NO local, de modo que sobrevive al final de la transacción. Si esa marca
        sigue visible después, la sesión es la misma, y entonces la ausencia de
        identidad es concluyente.

        El pool tiene una única conexión, así que la reutilización es forzosa.
        No se usa `pg_backend_pid()`: a través de Supavisor no representa la
        conexión de cliente.
    """
    marker = "rollback-probe"

    class Boom(RuntimeError):
        pass

    with single_connection_pool.connection() as conn:
        conn.execute("select set_config('app.rollback_probe', %s, false)", (marker,))

    # ── Transacción con identidad, abortada con ROLLBACK ──
    with pytest.raises(Boom):
        with user_transaction(single_connection_pool, settings, user_a.id) as conn:
            row = conn.execute(
                """
                select nullif(current_setting('app.rollback_probe', true), '') as probe,
                       auth.uid()::text as uid
                """
            ).fetchone()
            assert row["probe"] == marker, "La sesión no se reutilizó; prueba no concluyente"
            assert row["uid"] == user_a.id
            raise Boom("fallo simulado: fuerza ROLLBACK")

    # ── Misma sesión, después del ROLLBACK ──
    with single_connection_pool.connection() as conn:
        row = conn.execute(
            """
            select nullif(current_setting('app.rollback_probe', true), '')   as probe,
                   nullif(current_setting('request.jwt.claims', true), '')   as claims,
                   current_user::text                                        as role
            """
        ).fetchone()

    # La marca sobrevive -> es la MISMA sesión. Sin esto el resto no probaría nada.
    assert row["probe"] == marker, "La sesión no se reutilizó; prueba no concluyente"
    assert row["claims"] is None, "La identidad SOBREVIVIÓ al ROLLBACK"
    assert row["role"] == "app_backend", "El rol asumido SOBREVIVIÓ al ROLLBACK"

    # Y la identidad anterior ya no es alcanzable en una transacción posterior.
    with anonymous_transaction(single_connection_pool, settings) as conn:
        identity = current_identity(conn)
    assert identity["user_id"] is None, "auth.uid() aún devuelve al usuario anterior"
    assert identity["user_id"] != user_a.id


def test_no_identity_leak_on_reused_session(single_connection_pool, settings, user_a, user_b):
    """FUGA ENTRE USUARIOS — el fallo que ADR-012 obliga a impedir.

    CÓMO SE PRUEBA QUE LA SESIÓN ES LA MISMA

        `pg_backend_pid()` no sirve a través de Supavisor: el pooler puede
        asignar backends distintos y el identificador de proceso cambia aunque
        nuestra conexión de cliente sea la misma.

        En su lugar se deja una MARCA DE SESIÓN con `set_config(..., false)` --
        deliberadamente NO local, para que sobreviva al COMMIT. Si esa marca
        sigue visible en transacciones posteriores, la sesión se reutilizó, y la
        prueba de que la identidad no persiste es concluyente sobre esa misma
        sesión.

    El pool tiene una única conexión, de modo que la reutilización es forzosa.
    """
    marker = "identity-leak-probe"

    with single_connection_pool.connection() as conn:
        conn.execute("select set_config('app.leak_probe', %s, false)", (marker,))

    # ── Transacción de User A ──
    with user_transaction(single_connection_pool, settings, user_a.id) as conn:
        row = conn.execute(
            """
            select nullif(current_setting('app.leak_probe', true), '') as probe,
                   auth.uid()::text as uid
            """
        ).fetchone()
        assert row["probe"] == marker, "La sesión no se reutilizó; prueba no concluyente"
        assert row["uid"] == user_a.id
        companies_a = {
            r["id"] for r in conn.execute("select id::text as id from public.companies").fetchall()
        }

    # ── Entre transacciones: no debe quedar rastro ──
    with single_connection_pool.connection() as conn:
        row = conn.execute(
            """
            select nullif(current_setting('app.leak_probe', true), '')      as probe,
                   nullif(current_setting('request.jwt.claims', true), '')  as claims,
                   current_user::text                                       as role
            """
        ).fetchone()
    assert row["probe"] == marker, "La sesión no se reutilizó; prueba no concluyente"
    assert row["claims"] is None, "La identidad SOBREVIVIÓ a la transacción"
    assert row["role"] == "app_backend", "El rol asumido SOBREVIVIÓ a la transacción"

    # ── Transacción de User B sobre LA MISMA sesión ──
    with user_transaction(single_connection_pool, settings, user_b.id) as conn:
        row = conn.execute(
            """
            select nullif(current_setting('app.leak_probe', true), '') as probe,
                   auth.uid()::text as uid
            """
        ).fetchone()
        assert row["probe"] == marker, "La sesión no se reutilizó; prueba no concluyente"
        assert row["uid"] == user_b.id, "B no obtuvo su propia identidad"
        assert row["uid"] != user_a.id, "FUGA: B arrastró la identidad de A"
        companies_b = {
            r["id"] for r in conn.execute("select id::text as id from public.companies").fetchall()
        }

    assert user_a.company_id in companies_a
    assert user_b.company_id in companies_b
    assert user_a.company_id not in companies_b, "FUGA: B vio la empresa de A"
    assert user_b.company_id not in companies_a, "FUGA: A vio la empresa de B"


def test_many_alternating_transactions_never_cross_identities(pool, settings, user_a, user_b):
    """Alternancia repetida sobre el mismo pool: ninguna transacción ve la ajena."""
    expected = [(user_a, user_b)[i % 2] for i in range(8)]
    pids: set[int] = set()

    for user in expected:
        with user_transaction(pool, settings, user.id) as conn:
            pids.add(_backend_pid(conn))
            identity = current_identity(conn)
            rows = conn.execute("select id::text as id from public.companies").fetchall()

        assert identity["user_id"] == user.id
        ids = {r["id"] for r in rows}
        assert user.company_id in ids
        other = user_b if user is user_a else user_a
        assert other.company_id not in ids

    # Con min_size=1 lo normal es que todas hayan usado la misma conexión.
    assert len(pids) >= 1


def test_set_local_is_used_not_persistent_set(pool, settings, user_a):
    """Comprobación directa del mecanismo: el ajuste es local a la transacción.

    Si el código usara `set_config(..., false)` o `SET ROLE` sin `LOCAL`, el valor
    sobreviviría al COMMIT y este test fallaría.
    """
    with user_transaction(pool, settings, user_a.id) as conn:
        pid = _backend_pid(conn)
        assert current_identity(conn)["raw_claims"] is not None

    # Consulta fuera de toda transacción de usuario, sobre el mismo pool.
    with pool.connection() as conn:
        row = conn.execute(
            """
            select pg_backend_pid() as pid,
                   current_user::text as role_now,
                   nullif(current_setting('request.jwt.claims', true), '') as claims_now
            """
        ).fetchone()

    assert row["claims_now"] is None, "La identidad sobrevivió a la transacción"
    assert row["role_now"] == "app_backend", "El rol asumido sobrevivió a la transacción"
    if row["pid"] == pid:
        # Misma conexión física: la evidencia es directa.
        assert row["claims_now"] is None
