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

# ── Roles de ejecución — INVARIANTES DE CÓDIGO (ADR-020) ──────────────────────
#
# No son configuración ni parámetros. No hay variable de entorno que los cambie ni
# forma de que lleguen desde una petición: elegir el rol de ejecución es elegir qué
# función se escribe, algo que solo ocurre en tiempo de código.
#
# `SET LOCAL ROLE` no admite parámetros, así que además se validan contra lista
# blanca antes de interpolarse.
TENANCY_DB_ROLE = "authenticated"    # public.companies, public.company_memberships
FISCAL_DB_ROLE = "fiscal_backend"    # schema fiscal, no expuesto por la Data API

_ALLOWED_DB_ROLES = frozenset({TENANCY_DB_ROLE, FISCAL_DB_ROLE})

# Valor del claim `role` dentro de `request.jwt.claims`. Representa lo que dice el
# JWT del usuario, no el rol de ejecución de PostgreSQL: son cosas distintas y
# confundirlas haría que `auth.role()` mintiera.
_JWT_ROLE_CLAIM = "authenticated"


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

# Pertenencias exactas de `app_backend`, con las opciones que cada una debe tener
# (ADR-020 §5.4). Ni una de más ni una de menos.
#
#   inherit_option=False -> los privilegios NO se adquieren de forma automática;
#                           hay que pedirlos explícitamente con SET ROLE.
#   set_option=True      -> `SET ROLE` está permitido (es como se piden).
#   admin_option=False   -> `app_backend` no puede regalar estas pertenencias.
#
# `inherit_option=False` es lo que hace que `app_backend` no vea el schema
# `fiscal` por defecto: solo lo alcanza dentro de `fiscal_transaction`, que hace
# `SET LOCAL ROLE fiscal_backend` y lo revierte al terminar la transacción.
_REQUIRED_MEMBERSHIP_OPTIONS = {"inherit_option": False, "set_option": True, "admin_option": False}
_ALLOWED_MEMBERSHIPS = frozenset({TENANCY_DB_ROLE, FISCAL_DB_ROLE})

# ── Relación INVERSA: quién puede asumir `fiscal_backend` ─────────────────────
#
# La pertenencia directa no basta. Hay que mirar también en el otro sentido: si
# apareciera un segundo miembro de `fiscal_backend`, la frontera tendría una
# puerta que nadie declaró.
#
# Estado real verificado contra el catálogo (no supuesto):
#
#   app_backend  set_option=true   -> nuestra vía deliberada
#   postgres     set_option=FALSE  -> artefacto de PostgreSQL 16+
#
# `postgres` aparece porque en PostgreSQL 16+ quien CREA un rol recibe
# automáticamente pertenencia sobre él `WITH ADMIN TRUE, SET FALSE, INHERIT
# FALSE`. Es sistémico, no específico de `fiscal_backend`: `postgres` figura
# igual en `anon`, `authenticated`, `service_role` y `app_backend`. Y con
# `set_option=false` NO puede asumir el rol --- comprobado ejecutándolo: la
# propia CLI, conectada como `postgres`, recibe `42501: permission denied to set
# role` al intentar `SET ROLE fiscal_backend`.
#
# Quitar esa pertenencia dejaría el rol sin administrador. No se toca.
_FISCAL_ROLE_EXPECTED_MEMBERS: dict[str, dict[str, bool]] = {
    BACKEND_DB_ROLE: {"inherit_option": False, "set_option": True, "admin_option": False},
    "postgres": {"inherit_option": False, "set_option": False, "admin_option": True},
}

# Roles que REALMENTE pueden ejecutar `SET ROLE fiscal_backend`, siguiendo la
# cadena de pertenencias con `set_option` en cada salto.
#
# `pg_has_role(rol, 'fiscal_backend', 'MEMBER')` NO sirve como oráculo: devuelve
# cierto para `postgres`, que no puede asumir el rol. Confundir pertenencia con
# capacidad de asumir daría un falso positivo y haría fallar la guarda por una
# razón inventada.
#
# Los superusuarios quedan fuera de esta propiedad por definición --- alcanzan
# cualquier rol --- y son el dueño de la plataforma, no un actor del modelo de
# amenazas de ADR-012.
_FISCAL_ROLE_SET_ROLE_CLOSURE = frozenset({BACKEND_DB_ROLE})


def _check_fiscal_role_members(rows: list[dict], closure: set[str]) -> None:
    """Valida la relación inversa de `fiscal_backend`. Pura, para poder probarla.

    Se separa de la consulta a propósito: así un test puede alimentarla con un
    miembro inesperado y comprobar que la verificación falla, sin necesidad de
    crear roles reales en la base de datos.
    """
    members = {row["member"] for row in rows}
    expected = set(_FISCAL_ROLE_EXPECTED_MEMBERS)
    if members != expected:
        extra = sorted(members - expected)
        missing = sorted(expected - members)
        raise RoleVerificationError(
            f"Miembros inesperados de {FISCAL_DB_ROLE!r}: sobran {extra}, faltan {missing}. "
            "Alguien puede asumir el rol fiscal sin haberlo declarado (ADR-020)."
        )

    for row in rows:
        expected_opts = _FISCAL_ROLE_EXPECTED_MEMBERS[row["member"]]
        wrong = {k: row[k] for k, v in expected_opts.items() if row[k] is not v}
        if wrong:
            detalle = ", ".join(f"{k}={v}" for k, v in sorted(wrong.items()))
            raise RoleVerificationError(
                f"La pertenencia {row['member']!r} -> {FISCAL_DB_ROLE!r} tiene "
                f"opciones incorrectas: {detalle} (ADR-020)."
            )

    if closure != set(_FISCAL_ROLE_SET_ROLE_CLOSURE):
        raise RoleVerificationError(
            f"Roles capaces de `SET ROLE {FISCAL_DB_ROLE}`: {sorted(closure)}; "
            f"se esperaba {sorted(_FISCAL_ROLE_SET_ROLE_CLOSURE)} (ADR-020)."
        )


# Cierre transitivo de `SET ROLE` sobre `fiscal_backend`, excluyendo superusuarios.
_FISCAL_SET_ROLE_CLOSURE_SQL = """
with recursive alcanza(rol) as (
        select mem.rolname
        from pg_auth_members am
        join pg_roles r   on r.oid = am.roleid
        join pg_roles mem on mem.oid = am.member
        where r.rolname = %(fiscal)s and am.set_option
    union
        select mem.rolname
        from alcanza a
        join pg_roles rr on rr.rolname = a.rol
        join pg_auth_members am on am.roleid = rr.oid and am.set_option
        join pg_roles mem on mem.oid = am.member
)
select a.rol
from alcanza a
join pg_roles r on r.rolname = a.rol
where not r.rolsuper
"""

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

        membership_rows = conn.execute(
            """
            select m.rolname as member_of,
                   am.inherit_option, am.set_option, am.admin_option
            from pg_auth_members am
            join pg_roles r on r.oid = am.member
            join pg_roles m on m.oid = am.roleid
            where r.rolname = %s
            """,
            (BACKEND_DB_ROLE,),
        ).fetchall()

        memberships = {row["member_of"] for row in membership_rows}
        if memberships != set(_ALLOWED_MEMBERSHIPS):
            raise RoleVerificationError(
                f"Pertenencias inesperadas en {BACKEND_DB_ROLE!r}: "
                f"{sorted(memberships)}; se esperaba {sorted(_ALLOWED_MEMBERSHIPS)}."
            )

        # Tener la pertenencia no basta: las opciones deciden si el privilegio se
        # adquiere solo (inherit) o solo bajo petición explícita (set).
        for row in membership_rows:
            wrong_opts = {
                option: row[option]
                for option, expected in _REQUIRED_MEMBERSHIP_OPTIONS.items()
                if row[option] is not expected
            }
            if wrong_opts:
                detalle = ", ".join(f"{k}={v}" for k, v in sorted(wrong_opts.items()))
                raise RoleVerificationError(
                    f"La pertenencia {BACKEND_DB_ROLE!r} -> {row['member_of']!r} tiene "
                    f"opciones incorrectas: {detalle} (ADR-020)."
                )

        # `fiscal_backend` debe existir con los mismos límites duros que `app_backend`:
        # si alguien le concediera BYPASSRLS, el aislamiento fiscal desaparecería sin
        # que ninguna otra comprobación lo notara.
        fiscal_attrs = conn.execute(
            """
            select rolcanlogin, rolsuper, rolbypassrls,
                   rolinherit, rolcreaterole, rolcreatedb, rolreplication
            from pg_roles where rolname = %s
            """,
            (FISCAL_DB_ROLE,),
        ).fetchone()
        if fiscal_attrs is None:
            raise RoleVerificationError(f"El rol {FISCAL_DB_ROLE!r} no existe (ADR-020).")

        fiscal_wrong = {
            k: fiscal_attrs[k]
            for k, expected in _REQUIRED_ROLE_ATTRIBUTES.items()
            if k != "rolcanlogin" and fiscal_attrs[k] is not expected
        }
        if fiscal_attrs["rolcanlogin"]:
            fiscal_wrong["rolcanlogin"] = True  # `fiscal_backend` NO inicia sesión
        if fiscal_attrs["rolreplication"]:
            fiscal_wrong["rolreplication"] = True
        if fiscal_wrong:
            detalle = ", ".join(f"{k}={v}" for k, v in sorted(fiscal_wrong.items()))
            raise RoleVerificationError(
                f"El rol {FISCAL_DB_ROLE!r} tiene atributos incorrectos: {detalle}."
            )

        # ── Relación inversa: nadie más puede asumir el rol fiscal ──
        fiscal_member_rows = conn.execute(
            """
            select mem.rolname as member,
                   am.inherit_option, am.set_option, am.admin_option
            from pg_auth_members am
            join pg_roles r   on r.oid = am.roleid
            join pg_roles mem on mem.oid = am.member
            where r.rolname = %s
            """,
            (FISCAL_DB_ROLE,),
        ).fetchall()
        closure = {
            row["rol"]
            for row in conn.execute(
                _FISCAL_SET_ROLE_CLOSURE_SQL, {"fiscal": FISCAL_DB_ROLE}
            ).fetchall()
        }
        _check_fiscal_role_members([dict(r) for r in fiscal_member_rows], closure)

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
def _identified_transaction(
    pool: ConnectionPool, user: AuthenticatedUser, db_role: str
) -> Iterator[Connection]:
    """Transacción bajo la identidad de un usuario YA VERIFICADO, con `db_role`.

    PRIVADA A PROPÓSITO
        `db_role` es un parámetro aquí porque la lógica es común, pero esta función
        no forma parte de la API pública. Los llamantes usan `user_transaction` o
        `fiscal_transaction`, que fijan el rol de forma estática. Exponer un
        parámetro de rol reintroduciría por otra vía el problema de identidad que
        ADR-012 cerró: un valor puede venir de la petición; el nombre de una
        función, no.

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
    # 3. El rol de ejecución debe ser uno de los invariantes conocidos.
    if db_role not in _ALLOWED_DB_ROLES:
        raise DatabaseError(f"Rol de base de datos no permitido: {db_role!r}")

    claims = json.dumps({"sub": user.id, "role": _JWT_ROLE_CLAIM})

    with pool.connection() as conn:
        with conn.transaction():
            # 1. Asumir el rol al que apuntan las políticas. LOCAL -> revierte.
            conn.execute(f"SET LOCAL ROLE {db_role}")
            # 2. Publicar la identidad que `auth.uid()` leerá. is_local=true -> revierte.
            conn.execute("SELECT set_config('request.jwt.claims', %s, true)", (claims,))
            yield conn
        # Al salir de `conn.transaction()` se emite COMMIT (o ROLLBACK si hubo
        # excepción). En ambos casos rol e identidad quedan descartados.


@contextmanager
def user_transaction(
    pool: ConnectionPool, settings: Settings, user: AuthenticatedUser
) -> Iterator[Connection]:
    """Transacción de TENANCY: opera como `authenticated`.

    Para `public.companies` y `public.company_memberships` — datos de identidad y
    tenancy (ADR-017). No da acceso al schema `fiscal`.
    """
    del settings  # el rol es un invariante de código, no configuración
    with _identified_transaction(pool, user, TENANCY_DB_ROLE) as conn:
        yield conn


@contextmanager
def fiscal_transaction(
    pool: ConnectionPool, settings: Settings, user: AuthenticatedUser
) -> Iterator[Connection]:
    """Transacción FISCAL: opera como `fiscal_backend` (ADR-020).

    Para el schema `fiscal`, que la Data API no expone. `fiscal_backend` no tiene
    `BYPASSRLS`: las políticas de las tablas fiscales siguen decidiendo qué filas
    existen para este usuario.

    Es una función distinta, no una bandera: así el rol de ejecución no puede
    proceder de la petición.
    """
    del settings
    with _identified_transaction(pool, user, FISCAL_DB_ROLE) as conn:
        yield conn


@contextmanager
def anonymous_transaction(pool: ConnectionPool, settings: Settings) -> Iterator[Connection]:
    """Transacción sin identidad de usuario. Solo para diagnóstico y tests.

    Sirve para comprobar que una conexión reutilizada NO conserva la identidad de
    una transacción anterior.
    """
    with pool.connection() as conn:
        with conn.transaction():
            conn.execute(f"SET LOCAL ROLE {TENANCY_DB_ROLE}")
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
