"""Acceso a PostgreSQL bajo la identidad del usuario, con alcance transaccional.

ESTE MÓDULO IMPLEMENTA EL REQUISITO CRÍTICO DE ADR-012.

    BEGIN
      SET LOCAL ROLE authenticated
      set_config('request.jwt.claims', '{"sub": ..., "role": ...}', is_local => true)
      ... operaciones bajo RLS ...
    COMMIT   -->  la identidad DESAPARECE

POR QUÉ `SET LOCAL` Y `is_local => true`
    Ambas formas revierten al terminar la transacción. Su alternativa persistente
    (`SET ROLE`, `set_config(..., false)`) sobreviviría al COMMIT y quedaría en la
    conexión física. Con un pool, esa conexión se reutiliza para otro usuario, y
    la fuga no falla: devuelve datos del contribuyente equivocado, en silencio.

    Verificado empíricamente contra esta misma base de datos: tras el COMMIT,
    `current_setting('request.jwt.claims', true)` queda vacío y `auth.uid()`
    devuelve NULL en la conexión reutilizada.

POR QUÉ FUNCIONA CON LAS POLÍTICAS DEL DÍA 2 SIN TOCARLAS
    `auth.uid()` está definida en esta base de datos como

        current_setting('request.jwt.claim.sub', true)
        ó (current_setting('request.jwt.claims', true)::jsonb ->> 'sub')

    de modo que fijar `request.jwt.claims` es exactamente lo que las políticas ya
    consumen. Y las políticas son `TO authenticated`, por lo que el rol efectivo
    debe ser ese: de ahí el `SET LOCAL ROLE`.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.auth import AuthenticatedUser
from app.config import BACKEND_DB_ROLE, Settings

# `SET LOCAL ROLE` no admite parámetros, así que el nombre del rol se valida
# contra una lista blanca en lugar de interpolarse a ciegas.
_ALLOWED_DB_ROLES = frozenset({"authenticated"})


class DatabaseError(RuntimeError):
    pass


class RoleVerificationError(DatabaseError):
    """La sesión real de PostgreSQL no cumple lo que ADR-012 exige."""


# Atributos que el rol de conexión debe cumplir. Se comprueban contra la base de
# datos, no contra la migración: lo que importa es la realidad, no la intención.
_REQUIRED_ROLE_ATTRIBUTES = {
    "rolcanlogin": True,
    "rolsuper": False,
    "rolbypassrls": False,
    "rolinherit": False,
    "rolcreaterole": False,
    "rolcreatedb": False,
}

# Única pertenencia deliberada. Cualquier otra es un hallazgo.
_ALLOWED_MEMBERSHIPS = frozenset({"authenticated"})

# Roles que el backend jamás debe poder asumir.
_FORBIDDEN_REACHABLE_ROLES = ("service_role", "postgres", "supabase_admin")


def verify_backend_role(pool: ConnectionPool) -> None:
    """Comprueba contra PostgreSQL que la sesión cumple ADR-012. Fail fast.

    DEFENSA EN PROFUNDIDAD
        `config.py` valida lo que dice la cadena de conexión. Esto valida lo que
        la base de datos responde de verdad. Si alguien renombrara un rol, o
        `app_backend` recibiera una pertenencia nueva, la configuración seguiría
        pareciendo correcta y solo esta comprobación lo detectaría.

    No registra ni expone la cadena de conexión ni credencial alguna.
    """
    with pool.connection() as conn:
        session_user = conn.execute("select session_user::text as u").fetchone()["u"]
        if session_user != BACKEND_DB_ROLE:
            raise RoleVerificationError(
                f"La sesión se abrió como {session_user!r}; se exige {BACKEND_DB_ROLE!r} (ADR-012)."
            )

        attrs = conn.execute(
            """
            select rolcanlogin, rolsuper, rolbypassrls,
                   rolinherit, rolcreaterole, rolcreatedb
            from pg_roles where rolname = %s
            """,
            (BACKEND_DB_ROLE,),
        ).fetchone()
        if attrs is None:
            raise RoleVerificationError(f"El rol {BACKEND_DB_ROLE!r} no existe.")

        wrong = {k: attrs[k] for k, expected in _REQUIRED_ROLE_ATTRIBUTES.items() if attrs[k] is not expected}
        if wrong:
            detalle = ", ".join(f"{k}={v}" for k, v in sorted(wrong.items()))
            raise RoleVerificationError(
                f"El rol {BACKEND_DB_ROLE!r} tiene atributos incorrectos: {detalle}."
            )

        memberships = {
            row["member_of"]
            for row in conn.execute(
                """
                select m.rolname as member_of
                from pg_auth_members am
                join pg_roles r on r.oid = am.member
                join pg_roles m on m.oid = am.roleid
                where r.rolname = %s
                """,
                (BACKEND_DB_ROLE,),
            ).fetchall()
        }
        if memberships != set(_ALLOWED_MEMBERSHIPS):
            raise RoleVerificationError(
                f"Pertenencias inesperadas en {BACKEND_DB_ROLE!r}: "
                f"{sorted(memberships)}; se esperaba {sorted(_ALLOWED_MEMBERSHIPS)}."
            )

        for role in _FORBIDDEN_REACHABLE_ROLES:
            reachable = conn.execute(
                "select pg_has_role(%s, %s, 'MEMBER') as can", (BACKEND_DB_ROLE, role)
            ).fetchone()["can"]
            if reachable:
                raise RoleVerificationError(
                    f"{BACKEND_DB_ROLE!r} puede asumir {role!r}: violación de ADR-012."
                )


def create_pool(settings: Settings) -> ConnectionPool:
    """Pool de conexiones del rol backend.

    El pool reutiliza conexiones físicas a propósito: es justamente el escenario
    frente al que la identidad transaccional debe protegernos.
    """
    pool = ConnectionPool(
        conninfo=settings.database_url,
        min_size=1,
        max_size=5,
        open=True,
        kwargs={"row_factory": dict_row},
    )
    try:
        verify_backend_role(pool)
    except Exception:
        pool.close()
        raise
    return pool


@contextmanager
def user_transaction(
    pool: ConnectionPool, settings: Settings, user: AuthenticatedUser
) -> Iterator[Connection]:
    """Abre una transacción bajo la identidad de un usuario YA VERIFICADO.

    CONTRATO — solo identidades verificadas

        Acepta `AuthenticatedUser`, no un `str`. Un UUID llegado por query string,
        cabecera o cuerpo de la petición NO satisface este contrato, y una
        `AuthenticatedUser` solo puede emitirla `JwtVerifier.verify()`.

        Antes aceptaba un `str`: bastaba con que un llamante pasara el UUID de
        otro usuario para que `auth.uid()` pasara a ser ese otro. La corrección no
        depende de que nadie se equivoque, sino de que el tipo no lo permita.

        La identidad se establece UNA sola vez, en la frontera autenticada del
        request. Los repositorios y helpers reciben la conexión ya contextualizada
        y no pueden redefinirla.

    Al salir del bloque la transacción termina y la identidad deja de existir.
    """
    # 1. El tipo: un str, un UUID, un dict o None no satisfacen el contrato.
    if not isinstance(user, AuthenticatedUser):
        raise DatabaseError(
            "user_transaction exige una AuthenticatedUser verificada, "
            f"no {type(user).__name__}."
        )

    # 2. La evidencia: debe corresponder EXACTAMENTE a este `id`.
    #
    #    Comprobación redundante por diseño. El constructor ya la exige, pero si
    #    alguien alterase el `id` por una vía ajena a la API normal, aquí se
    #    detecta ANTES de ejecutar SQL con esa identidad. Falla cerrada.
    if not user.has_valid_binding():
        raise DatabaseError(
            "La evidencia de identidad no corresponde al identificador. "
            "No se establece contexto de usuario."
        )
    if settings.db_role not in _ALLOWED_DB_ROLES:
        raise DatabaseError(f"Rol de base de datos no permitido: {settings.db_role!r}")

    claims = json.dumps({"sub": user.id, "role": settings.db_role})

    with pool.connection() as conn:
        with conn.transaction():
            # 1. Asumir el rol al que apuntan las políticas. LOCAL -> revierte.
            conn.execute(f"SET LOCAL ROLE {settings.db_role}")
            # 2. Publicar la identidad que `auth.uid()` leerá. is_local=true -> revierte.
            conn.execute("SELECT set_config('request.jwt.claims', %s, true)", (claims,))
            yield conn
        # Al salir de `conn.transaction()` se emite COMMIT (o ROLLBACK si hubo
        # excepción). En ambos casos rol e identidad quedan descartados.


@contextmanager
def anonymous_transaction(pool: ConnectionPool, settings: Settings) -> Iterator[Connection]:
    """Transacción sin identidad de usuario. Solo para diagnóstico y tests.

    Sirve para comprobar que una conexión reutilizada NO conserva la identidad de
    una transacción anterior.
    """
    with pool.connection() as conn:
        with conn.transaction():
            conn.execute(f"SET LOCAL ROLE {settings.db_role}")
            yield conn


def current_identity(conn: Connection) -> dict[str, str | None]:
    """Identidad que PostgreSQL ve en este momento, tal y como la evalúa RLS."""
    row = conn.execute(
        """
        select
            current_user::text                              as db_role,
            auth.uid()::text                                as user_id,
            nullif(current_setting('request.jwt.claims', true), '') as raw_claims
        """
    ).fetchone()
    if row is None:  # pragma: no cover — una consulta escalar siempre devuelve fila
        raise DatabaseError("No se pudo leer la identidad actual.")
    return row
