"""Frontera de datos fiscales (ADR-020).

Estos tests demuestran la frontera con una tabla CANARIO EFÍMERA,
`fiscal.boundary_probe`, que se crea al empezar y se destruye al terminar. Se hace
así a propósito: el gate `BLOCKING BEFORE FIRST FISCAL TABLE` sigue abierto y
ninguna tabla fiscal real existe todavía. El canario prueba el mecanismo, no el
modelo de datos.

La tabla se construye con la misma forma que tendrá cualquier tabla fiscal futura
--- `company_id`, RLS activa, política sobre `private.is_company_member`, permisos
solo para `fiscal_backend` --- para que lo que se demuestra aquí sea transferible.
"""

from __future__ import annotations

import httpx
import psycopg
import pytest

from app.db import (
    FISCAL_DB_ROLE,
    TENANCY_DB_ROLE,
    RoleVerificationError,
    _check_fiscal_role_members,
    current_identity,
    fiscal_transaction,
    user_transaction,
    verify_backend_role,
)

PROBE = "fiscal.boundary_probe"


def _fiscal_identity(conn) -> dict:
    """Identidad vista desde una transacción fiscal, sin tocar el schema `auth`.

    `current_identity()` de `app.db` llama a `auth.uid()`, y `fiscal_backend` no
    tiene USAGE sobre el schema `auth` (ver
    `test_fiscal_backend_no_alcanza_el_schema_auth`). Se lee el claim directamente,
    que es exactamente de donde `auth.uid()` lo saca.
    """
    return conn.execute(
        """
        select current_user::text as db_role,
               current_setting('request.jwt.claims', true)::jsonb ->> 'sub' as user_id
        """
    ).fetchone()


@pytest.fixture(scope="module")
def probe_table(admin_sql, user_a, user_b):
    """Crea el canario, siembra una fila por empresa y lo destruye al salir."""
    # El `drop` previo cubre el caso de una ejecución anterior interrumpida: el
    # schema `fiscal` debe quedar vacío pase lo que pase, porque el gate
    # `BLOCKING BEFORE FIRST FISCAL TABLE` sigue abierto y ninguna tabla fiscal
    # debe sobrevivir a esta suite.
    admin_sql(f"drop table if exists {PROBE} cascade")
    try:
        _create_probe(admin_sql, user_a, user_b)
        yield PROBE
    finally:
        admin_sql(f"drop table if exists {PROBE} cascade")
        # Comprobación AUTOMATIZADA del teardown, no un comando manual posterior.
        # Si el drop fallara, esto rompe la suite en lugar de dejar residuo
        # silencioso en un schema fiscal que el gate mantiene vacío.
        residuo = admin_sql(
            """
            select (select count(*) from information_schema.tables
                     where table_schema = 'fiscal')                      as tablas,
                   (select count(*) from pg_proc p
                     join pg_namespace n on n.oid = p.pronamespace
                    where n.nspname = 'fiscal')                          as funciones
            """
        )[0]
        assert residuo["tablas"] == 0, f"Residuo: {residuo['tablas']} tabla(s) en `fiscal`."
        assert residuo["funciones"] == 0, f"Residuo: {residuo['funciones']} función(es) en `fiscal`."


@pytest.fixture
def probe_rows(admin_sql, probe_table):
    """Retira las filas que inserte un test, para que no se contaminen entre sí."""
    yield
    admin_sql(f"delete from {PROBE} where note like 'matriz-%'")


def _insert_probe(pool, settings, user, company_id: str, note: str) -> None:
    with fiscal_transaction(pool, settings, user.identity) as conn:
        conn.execute(
            f"insert into {PROBE} (company_id, note) values (%s, %s)", (company_id, note)
        )


def _create_probe(admin_sql, user_a, user_b) -> None:
    """Tabla con la misma forma que tendrá cualquier tabla fiscal futura."""
    admin_sql(
        f"""
        create table {PROBE} (
            id          uuid primary key default gen_random_uuid(),
            company_id  uuid not null references public.companies(id) on delete restrict,
            note        text not null
        );

        alter table {PROBE} enable row level security;

        revoke all on {PROBE} from public;
        revoke all on {PROBE} from anon;
        revoke all on {PROBE} from authenticated;
        revoke all on {PROBE} from app_backend;
        grant select, insert on {PROBE} to fiscal_backend;

        create policy probe_select on {PROBE}
            for select to fiscal_backend
            using (private.is_company_member(company_id));

        create policy probe_insert on {PROBE}
            for insert to fiscal_backend
            with check (private.is_company_member(company_id));

        insert into {PROBE} (company_id, note) values
            ('{user_a.company_id}', 'canario-A'),
            ('{user_b.company_id}', 'canario-B');
        """
    )


# ─────────────────────────────────────────────────────────────────────────────
# 1. La Data API no expone el schema `fiscal`
# ─────────────────────────────────────────────────────────────────────────────


def test_data_api_no_expone_el_schema_fiscal(settings, publishable_key, user_a, probe_table):
    """PostgREST debe rechazar el schema, no devolver una lista vacía.

    La distinción importa: `200 []` significaría que el schema SÍ está expuesto y
    que lo único que nos separa de los datos es RLS. `PGRST106` significa que
    PostgREST ni siquiera admite el schema como destino. Es la diferencia entre
    una puerta cerrada con llave y una puerta que no existe.
    """
    response = httpx.get(
        f"{settings.supabase_url}/rest/v1/boundary_probe",
        headers={
            "apikey": publishable_key,
            "Authorization": f"Bearer {user_a.token}",
            "Accept-Profile": "fiscal",
        },
        params={"select": "*"},
        timeout=90,
    )

    assert response.status_code != 200, (
        "La Data API respondió 200 sobre el schema `fiscal`: el schema está "
        f"expuesto. Cuerpo: {response.text[:200]}"
    )
    assert response.json().get("code") == "PGRST106", (
        "Se esperaba PGRST106 (schema no expuesto). "
        f"Recibido {response.status_code}: {response.text[:200]}"
    )


def test_data_api_si_expone_el_schema_public(settings, publishable_key, user_a):
    """Contraprueba: el mismo cliente SÍ llega a `public`.

    Sin esto, un fallo de red o un token inválido produciría un PGRST106 falso y
    el test anterior pasaría por la razón equivocada.
    """
    response = httpx.get(
        f"{settings.supabase_url}/rest/v1/companies",
        headers={"apikey": publishable_key, "Authorization": f"Bearer {user_a.token}"},
        params={"select": "id"},
        timeout=90,
    )
    assert response.status_code == 200, response.text[:200]


# ─────────────────────────────────────────────────────────────────────────────
# 2. Privilegios: quién puede siquiera nombrar el schema
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("role", ["public", "anon", "authenticated", "app_backend", "service_role"])
def test_ningun_rol_salvo_fiscal_backend_tiene_usage(admin_sql, role, probe_table):
    row = admin_sql(
        f"select has_schema_privilege('{role}', 'fiscal', 'USAGE') as u"
    )[0]
    assert row["u"] is False, f"{role} tiene USAGE sobre el schema `fiscal`."


def test_fiscal_backend_tiene_usage_pero_no_create(admin_sql, probe_table):
    row = admin_sql(
        "select has_schema_privilege('fiscal_backend','fiscal','USAGE')  as u,"
        "       has_schema_privilege('fiscal_backend','fiscal','CREATE') as c"
    )[0]
    assert row["u"] is True
    assert row["c"] is False, "`fiscal_backend` puede crear objetos en `fiscal`."


def test_fiscal_backend_no_lee_company_memberships_directamente(admin_sql):
    """Alcanza la pertenencia por la función, no por la tabla.

    `private.is_company_member` es SECURITY DEFINER: da la respuesta sin dar la
    tabla. Si `fiscal_backend` tuviera SELECT directo, el helper sobraría y la
    superficie sería mayor de lo necesario.
    """
    row = admin_sql(
        "select has_table_privilege('fiscal_backend','public.company_memberships','SELECT') as t,"
        "       has_function_privilege('fiscal_backend','private.is_company_member(uuid)','EXECUTE') as f"
    )[0]
    assert row["t"] is False, "`fiscal_backend` tiene SELECT sobre company_memberships."
    assert row["f"] is True


def test_authenticated_no_alcanza_el_canario(pool, settings, user_a, probe_table):
    """Una transacción de tenancy no llega a los datos fiscales."""
    with user_transaction(pool, settings, user_a.identity) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege) as exc:
            conn.execute(f"select * from {PROBE}")
    assert exc.value.sqlstate == "42501"


def test_app_backend_sin_set_role_no_alcanza_el_canario(pool, probe_table):
    """`inherit_option=false` en acción.

    `app_backend` ES miembro de `fiscal_backend`, pero sin herencia: los
    privilegios solo aparecen tras un `SET ROLE` explícito. Sin él, el rol de
    login no ve nada, y ese es el estado por defecto de toda conexión del pool.
    """
    with pool.connection() as conn:
        with conn.transaction():
            assert conn.execute("select current_user::text as u").fetchone()["u"] == "app_backend"
            with pytest.raises(psycopg.errors.InsufficientPrivilege) as exc:
                conn.execute(f"select * from {PROBE}")
    assert exc.value.sqlstate == "42501"


# ─────────────────────────────────────────────────────────────────────────────
# 3. RLS dentro de la frontera: `fiscal_backend` no tiene BYPASSRLS
# ─────────────────────────────────────────────────────────────────────────────


def test_fiscal_transaction_asume_el_rol_fiscal(pool, settings, user_a, probe_table):
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        identity = _fiscal_identity(conn)
    assert identity["db_role"] == FISCAL_DB_ROLE
    assert identity["user_id"] == user_a.id, "La identidad del usuario debe sobrevivir al cambio de rol."


def test_usuario_a_solo_ve_su_fila_fiscal(pool, settings, user_a, user_b, probe_table):
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        rows = conn.execute(f"select company_id::text as c, note from {PROBE}").fetchall()
    companies = {r["c"] for r in rows}
    assert companies == {user_a.company_id}, f"A vio empresas ajenas: {companies}"
    assert user_b.company_id not in companies


def test_usuario_b_solo_ve_su_fila_fiscal(pool, settings, user_a, user_b, probe_table):
    with fiscal_transaction(pool, settings, user_b.identity) as conn:
        rows = conn.execute(f"select company_id::text as c, note from {PROBE}").fetchall()
    companies = {r["c"] for r in rows}
    assert companies == {user_b.company_id}, f"B vio empresas ajenas: {companies}"
    assert user_a.company_id not in companies


# ── Matriz INSERT: el rechazo debe venir de RLS, NO de falta de privilegios ──
#
# `permission denied for table X` y `new row violates row-level security policy`
# comparten SQLSTATE 42501 y clase `InsufficientPrivilege` --- verificado
# empíricamente. Asertar solo el sqlstate NO distingue una política RLS de un
# GRANT ausente: un test así pasaría igual con la RLS desactivada. El único
# discriminador fiable es el mensaje.
_RLS_REJECTION = "row-level security policy"

# Cubre tanto `permission denied for table X` como `permission denied for schema
# fiscal`: la denegación por privilegios ocurre en dos niveles y quedarse solo
# con el de tabla dejaría pasar el de schema. Lo descubrió el autotest de abajo.
_GRANT_REJECTION = "permission denied"


def _assert_rejected_by_rls(exc: psycopg.errors.InsufficientPrivilege) -> None:
    message = str(exc)
    assert _GRANT_REJECTION not in message, (
        "El rechazo vino de un privilegio ausente (schema o tabla), no de RLS. "
        "Este test no demuestra aislamiento por políticas. "
        f"Mensaje: {message.splitlines()[0]}"
    )
    assert _RLS_REJECTION in message, (
        f"Se esperaba un rechazo de RLS. Mensaje: {message.splitlines()[0]}"
    )


def test_el_rol_fiscal_posee_insert_sobre_el_canario(admin_sql, probe_table):
    """PREMISA de la matriz: los rechazos que siguen no pueden ser por grants.

    Si `fiscal_backend` no tuviera INSERT, o le faltara USAGE sobre el schema,
    los cuatro casos fallarían por privilegios y la matriz no probaría nada sobre
    RLS. Se comprueba antes de interpretar ningún rechazo.
    """
    row = admin_sql(
        "select has_table_privilege('fiscal_backend', 'fiscal.boundary_probe', 'INSERT') as ins,"
        "       has_table_privilege('fiscal_backend', 'fiscal.boundary_probe', 'SELECT') as sel,"
        "       has_schema_privilege('fiscal_backend', 'fiscal', 'USAGE')                as usg,"
        "       (select relrowsecurity from pg_class where oid = 'fiscal.boundary_probe'::regclass) as rls"
    )[0]
    assert row["ins"] is True, "`fiscal_backend` no tiene INSERT: la matriz sería vacua."
    assert row["sel"] is True
    assert row["usg"] is True
    assert row["rls"] is True, "RLS no está activa sobre el canario."


def test_insert_A_en_empresa_A_permitido(pool, settings, admin_sql, user_a, probe_rows):
    """A → Company A: permitido. Se ejecuta de verdad y se comprueba la fila."""
    _insert_probe(pool, settings, user_a, user_a.company_id, "matriz-AA")

    rows = admin_sql(
        f"select company_id::text as c from {PROBE} where note = 'matriz-AA'"
    )
    assert len(rows) == 1, "El INSERT permitido no creó exactamente una fila."
    assert rows[0]["c"] == user_a.company_id, "La fila quedó en la empresa equivocada."

    # Y su propio autor la ve a través de RLS.
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        visible = conn.execute(
            f"select note from {PROBE} where note = 'matriz-AA'"
        ).fetchall()
    assert len(visible) == 1


def test_insert_B_en_empresa_B_permitido(pool, settings, admin_sql, user_b, probe_rows):
    """B → Company B: permitido."""
    _insert_probe(pool, settings, user_b, user_b.company_id, "matriz-BB")

    rows = admin_sql(
        f"select company_id::text as c from {PROBE} where note = 'matriz-BB'"
    )
    assert len(rows) == 1
    assert rows[0]["c"] == user_b.company_id

    with fiscal_transaction(pool, settings, user_b.identity) as conn:
        visible = conn.execute(
            f"select note from {PROBE} where note = 'matriz-BB'"
        ).fetchall()
    assert len(visible) == 1


def test_insert_A_en_empresa_B_denegado_por_rls(pool, settings, admin_sql, user_a, user_b, probe_rows):
    """A → Company B: denegado por `WITH CHECK`, no por privilegios."""
    with pytest.raises(psycopg.errors.InsufficientPrivilege) as exc:
        _insert_probe(pool, settings, user_a, user_b.company_id, "matriz-AB")

    assert exc.value.sqlstate == "42501"
    _assert_rejected_by_rls(exc.value)
    assert admin_sql(f"select count(*) as n from {PROBE} where note = 'matriz-AB'")[0]["n"] == 0


def test_insert_B_en_empresa_A_denegado_por_rls(pool, settings, admin_sql, user_a, user_b, probe_rows):
    """B → Company A: denegado por `WITH CHECK`, no por privilegios."""
    with pytest.raises(psycopg.errors.InsufficientPrivilege) as exc:
        _insert_probe(pool, settings, user_b, user_a.company_id, "matriz-BA")

    assert exc.value.sqlstate == "42501"
    _assert_rejected_by_rls(exc.value)
    assert admin_sql(f"select count(*) as n from {PROBE} where note = 'matriz-BA'")[0]["n"] == 0


def test_el_oraculo_de_rls_distingue_un_rechazo_por_grants(pool, settings, user_a, probe_table):
    """AUTOTEST del discriminador.

    `authenticated` no tiene privilegios sobre el canario, así que su rechazo es
    por privilegios. Si `_assert_rejected_by_rls` lo aceptara, los cuatro tests
    de la matriz podrían estar midiendo grants en lugar de políticas y nadie se
    enteraría.

    Este autotest ya encontró un fallo real: la primera versión solo reconocía
    `permission denied for table` y habría dado por bueno un rechazo por
    `permission denied for schema`.
    """
    with pytest.raises(psycopg.errors.InsufficientPrivilege) as exc:
        with user_transaction(pool, settings, user_a.identity) as conn:
            conn.execute(f"select * from {PROBE}")

    assert exc.value.sqlstate == "42501"
    with pytest.raises(AssertionError, match="privilegio ausente"):
        _assert_rejected_by_rls(exc.value)

    # Y el rechazo real es, en efecto, por privilegios de schema.
    assert "permission denied for schema fiscal" in str(exc.value)


# ─────────────────────────────────────────────────────────────────────────────
# 4. El rol fiscal no sobrevive a la transacción
# ─────────────────────────────────────────────────────────────────────────────


def test_el_rol_fiscal_se_revierte_en_la_misma_conexion(single_connection_pool, settings, user_a, probe_table):
    """Una sola conexión física, reutilizada: es el escenario del pool.

    Si `SET LOCAL ROLE` no revirtiera, la siguiente petición heredaría acceso
    fiscal sin haberlo pedido. Se comprueba sobre la MISMA conexión, no sobre una
    cualquiera del pool, para que el test no pueda pasar por casualidad.
    """
    pool = single_connection_pool

    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        assert conn.execute("select current_user::text as u").fetchone()["u"] == FISCAL_DB_ROLE

    with pytest.raises(psycopg.errors.InsufficientPrivilege) as exc:
        with pool.connection() as conn:
            assert conn.execute("select current_user::text as u").fetchone()["u"] == "app_backend"
            conn.execute(f"select * from {PROBE}")
    assert exc.value.sqlstate == "42501"


def test_tras_fiscal_una_transaccion_de_tenancy_vuelve_a_authenticated(
    single_connection_pool, settings, user_a, probe_table
):
    """Alternar fiscal → tenancy no arrastra privilegios."""
    pool = single_connection_pool

    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        assert _fiscal_identity(conn)["db_role"] == FISCAL_DB_ROLE

    # En tenancy sí funciona `current_identity`, que es la ruta de producción.
    with pytest.raises(psycopg.errors.InsufficientPrivilege) as exc:
        with user_transaction(pool, settings, user_a.identity) as conn:
            assert current_identity(conn)["db_role"] == TENANCY_DB_ROLE
            assert current_identity(conn)["user_id"] == user_a.id
            conn.execute(f"select * from {PROBE}")
    assert exc.value.sqlstate == "42501"


def test_la_identidad_no_sobrevive_a_la_transaccion_fiscal(single_connection_pool, settings, user_a, probe_table):
    pool = single_connection_pool
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        assert _fiscal_identity(conn)["user_id"] == user_a.id

    with pool.connection() as conn:
        leftover = conn.execute(
            "select current_setting('request.jwt.claims', true) as c"
        ).fetchone()["c"]
    assert not leftover, f"La identidad sobrevivió a la transacción: {leftover!r}"


def test_fiscal_backend_no_alcanza_el_schema_auth(pool, settings, user_a, probe_table):
    """RESTRICCIÓN REGISTRADA, no un defecto pendiente.

    `fiscal_backend` no tiene USAGE sobre `auth`, así que `auth.uid()` no es
    invocable desde una transacción fiscal. El aislamiento no depende de ello: la
    política del canario resuelve la pertenencia con
    `private.is_company_member`, que es SECURITY DEFINER y sí puede consultar la
    identidad. La identidad del usuario está presente --- en
    `request.jwt.claims` --- aunque el atajo `auth.uid()` no lo esté.

    CONSECUENCIA DE DISEÑO: toda política RLS sobre una tabla fiscal debe
    apoyarse en `private.is_company_member(company_id)` y no en `auth.uid()`
    directo. Este test existe para que ese requisito falle en voz alta si alguien
    lo olvida, y para que ampliar el privilegio sea una decisión explícita y no
    un descubrimiento a mitad de una migración.
    """
    with pytest.raises(psycopg.errors.InsufficientPrivilege) as exc:
        with fiscal_transaction(pool, settings, user_a.identity) as conn:
            conn.execute("select auth.uid()")
    assert exc.value.sqlstate == "42501"

    # Pese a ello, la identidad viaja en la transacción.
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        assert _fiscal_identity(conn)["user_id"] == user_a.id


# ─────────────────────────────────────────────────────────────────────────────
# 5. El rol de ejecución no es un parámetro
# ─────────────────────────────────────────────────────────────────────────────


def test_no_existe_una_api_publica_con_rol_parametrizable():
    """La elección del rol ocurre en tiempo de código, no de petición.

    Escribir `fiscal_transaction(...)` es una decisión del programador. Un
    `transaction(..., role=request.role)` la trasladaría al atacante.
    """
    import inspect

    from app import db

    for name in ("user_transaction", "fiscal_transaction", "anonymous_transaction"):
        params = set(inspect.signature(getattr(db, name)).parameters)
        assert not (params & {"role", "db_role", "execution_role"}), (
            f"`{name}` acepta el rol como parámetro: el rol dejaría de ser un invariante."
        )

    assert not hasattr(db, "transaction"), (
        "Existe una `transaction` genérica; la frontera depende de que no la haya."
    )


# ─────────────────────────────────────────────────────────────────────────────
# 6. Relación INVERSA: quién puede asumir `fiscal_backend`
# ─────────────────────────────────────────────────────────────────────────────

# Roles de la Data API presentes en el catálogo de este proyecto. Nombres
# verificados, no supuestos: los cuatro existen en `pg_roles`.
_DATA_API_ROLES = ("anon", "authenticated", "service_role", "authenticator")

_SET_ROLE_CLOSURE_SQL = """
with recursive alcanza(rol) as (
        select mem.rolname
        from pg_auth_members am
        join pg_roles r   on r.oid = am.roleid
        join pg_roles mem on mem.oid = am.member
        where r.rolname = 'fiscal_backend' and am.set_option
    union
        select mem.rolname
        from alcanza a
        join pg_roles rr on rr.rolname = a.rol
        join pg_auth_members am on am.roleid = rr.oid and am.set_option
        join pg_roles mem on mem.oid = am.member
)
select a.rol from alcanza a
join pg_roles r on r.rolname = a.rol
where not r.rolsuper
"""


def test_miembros_exactos_de_fiscal_backend(admin_sql):
    """Estado exacto de la relación inversa, con sus opciones.

    Son dos, no uno. `postgres` figura porque en PostgreSQL 16+ quien crea un rol
    recibe pertenencia automática `WITH ADMIN TRUE, SET FALSE, INHERIT FALSE`. Es
    sistémico --- aparece igual en `anon`, `authenticated`, `service_role` y
    `app_backend` --- y con `set_option=false` no permite asumir el rol.

    Asertar `== {app_backend}` sería asertar algo falso y la suite fallaría por
    una razón inventada. Se aserta el estado real y exacto, que detecta drift
    igual de bien: cualquier tercer miembro rompe este test.
    """
    rows = admin_sql(
        """
        select mem.rolname as member, am.inherit_option, am.set_option, am.admin_option
        from pg_auth_members am
        join pg_roles r   on r.oid = am.roleid
        join pg_roles mem on mem.oid = am.member
        where r.rolname = 'fiscal_backend'
        order by 1
        """
    )
    members = {r["member"] for r in rows}
    assert members == {"app_backend", "postgres"}, f"Miembros inesperados: {sorted(members)}"

    by_name = {r["member"]: r for r in rows}
    assert by_name["app_backend"]["set_option"] is True
    assert by_name["app_backend"]["inherit_option"] is False
    assert by_name["app_backend"]["admin_option"] is False

    # El creador administra el rol, pero no puede asumirlo.
    assert by_name["postgres"]["set_option"] is False
    assert by_name["postgres"]["inherit_option"] is False


def test_solo_app_backend_puede_asumir_el_rol_fiscal(admin_sql):
    """Cierre TRANSITIVO de `SET ROLE`, que es la propiedad que importa.

    `pg_has_role(rol, 'fiscal_backend', 'MEMBER')` no vale como oráculo: devuelve
    cierto para `postgres`, `cli_login_postgres` y `supabase_admin`, y de esos
    solo el superusuario puede realmente asumir el rol. Se recorre la cadena de
    pertenencias exigiendo `set_option` en CADA salto.

    Los superusuarios se excluyen porque alcanzan cualquier rol por definición;
    en este proyecto el único es `supabase_admin`, el dueño de la plataforma.
    """
    closure = {r["rol"] for r in admin_sql(_SET_ROLE_CLOSURE_SQL)}
    assert closure == {"app_backend"}, (
        f"Pueden asumir `fiscal_backend`: {sorted(closure)}. Solo `app_backend` debe poder."
    )

    supers = {r["rolname"] for r in admin_sql("select rolname from pg_roles where rolsuper")}
    assert supers == {"supabase_admin"}, f"Superusuarios inesperados: {sorted(supers)}"


def test_ningun_rol_de_la_data_api_puede_asumir_el_rol_fiscal(admin_sql):
    """El vector que ADR-020 cierra: navegador → Data API → datos fiscales."""
    closure = {r["rol"] for r in admin_sql(_SET_ROLE_CLOSURE_SQL)}
    for role in _DATA_API_ROLES:
        assert role in {
            r["rolname"] for r in admin_sql("select rolname from pg_roles")
        }, f"El rol {role!r} no existe; revisa el nombre antes de asertar sobre él."
        assert role not in closure, f"{role} puede asumir `fiscal_backend`."


def test_postgres_es_miembro_pero_no_puede_asumir_el_rol(admin_sql):
    """Distinción entre pertenencia y capacidad, comprobada ejecutándola.

    Documenta por qué la guarda no usa `pg_has_role(..., 'MEMBER')`.
    """
    row = admin_sql(
        "select pg_has_role('postgres','fiscal_backend','MEMBER') as member_flag,"
        "       pg_has_role('postgres','fiscal_backend','USAGE')  as usage_flag"
    )[0]
    assert row["member_flag"] is True, "Se esperaba que `postgres` figurase como miembro."
    assert row["usage_flag"] is False, "`postgres` heredaría privilegios fiscales."

    # `admin_sql` conecta como `postgres`: que falle aquí ES la prueba.
    with pytest.raises(Exception) as exc:
        admin_sql("set role fiscal_backend")
    assert "42501" in str(exc.value) or "permission denied to set role" in str(exc.value)


# ─────────────────────────────────────────────────────────────────────────────
# 7. Detección de drift: un miembro inesperado debe romper el arranque
# ─────────────────────────────────────────────────────────────────────────────


def test_la_guarda_rechaza_un_miembro_inesperado_sin_tocar_la_base(admin_sql):
    """Propiedad, comprobada sobre la función pura de verificación.

    No basta con constatar que hoy solo está `app_backend`: eso describe el
    estado, no demuestra que la guarda lo vigile. Aquí se le entrega un catálogo
    con un miembro extra y se exige que falle.
    """
    real = admin_sql(
        """
        select mem.rolname as member, am.inherit_option, am.set_option, am.admin_option
        from pg_auth_members am
        join pg_roles r   on r.oid = am.roleid
        join pg_roles mem on mem.oid = am.member
        where r.rolname = 'fiscal_backend'
        """
    )
    closure = {r["rol"] for r in admin_sql(_SET_ROLE_CLOSURE_SQL)}

    # Estado real: pasa.
    _check_fiscal_role_members(real, closure)

    # Miembro inesperado: falla.
    intruso = real + [
        {
            "member": "some_unexpected_role",
            "inherit_option": False,
            "set_option": True,
            "admin_option": False,
        }
    ]
    with pytest.raises(RoleVerificationError, match="some_unexpected_role"):
        _check_fiscal_role_members(intruso, closure | {"some_unexpected_role"})

    # Y un cierre de `SET ROLE` ampliado también falla, aunque los miembros cuadren.
    with pytest.raises(RoleVerificationError, match="SET ROLE"):
        _check_fiscal_role_members(real, closure | {"otro_rol_que_asume"})

    # Opciones alteradas: `app_backend` heredando en lugar de asumir.
    heredando = [
        {**r, "inherit_option": True} if r["member"] == "app_backend" else r for r in real
    ]
    with pytest.raises(RoleVerificationError, match="inherit_option"):
        _check_fiscal_role_members(heredando, closure)


def test_la_guarda_de_arranque_falla_con_un_miembro_real_inesperado(pool, admin_sql):
    """La misma propiedad, extremo a extremo contra la base de datos real.

    Se crea un rol NOLOGIN, se le concede `fiscal_backend`, y se comprueba que
    `verify_backend_role` --- la misma función que corre en el arranque ---
    rechaza el estado. El rol se retira en `finally` pase lo que pase, y después
    se verifica que no quedó rastro.
    """
    drift_role = "d1_drift_probe"
    try:
        admin_sql(
            f"create role {drift_role} nologin noinherit nosuperuser nobypassrls; "
            f"grant fiscal_backend to {drift_role} with inherit false, set true, admin false;"
        )

        with pytest.raises(RoleVerificationError) as exc:
            verify_backend_role(pool)
        assert drift_role in str(exc.value)
    finally:
        admin_sql(f"revoke fiscal_backend from {drift_role}")
        admin_sql(f"drop role if exists {drift_role}")

    # Estado restaurado: la guarda vuelve a pasar y no queda residuo.
    verify_backend_role(pool)
    assert admin_sql(f"select count(*) as n from pg_roles where rolname = '{drift_role}'")[0]["n"] == 0
    assert {r["rol"] for r in admin_sql(_SET_ROLE_CLOSURE_SQL)} == {"app_backend"}


# ─────────────────────────────────────────────────────────────────────────────
# 8. Endurecimiento del rol fiscal
# ─────────────────────────────────────────────────────────────────────────────


def test_atributos_completos_de_fiscal_backend(admin_sql):
    """Invariantes de endurecimiento. Nunca se imprime hash ni contraseña.

    `rolpassword is null` es la propiedad segura: se consulta la ausencia, no el
    valor. `NOLOGIN` ya impide autenticarse, así que esto es endurecimiento y no
    la corrección de una vulnerabilidad abierta.
    """
    row = admin_sql(
        """
        select rolcanlogin, rolsuper, rolbypassrls, rolinherit,
               rolcreaterole, rolcreatedb, rolreplication,
               (rolpassword is null) as sin_password,
               (rolvaliduntil is null) as sin_caducidad
        from pg_authid where rolname = 'fiscal_backend'
        """
    )[0]
    assert row["rolcanlogin"] is False
    assert row["rolsuper"] is False
    assert row["rolbypassrls"] is False
    assert row["rolinherit"] is False
    assert row["rolcreaterole"] is False
    assert row["rolcreatedb"] is False
    assert row["rolreplication"] is False
    assert row["sin_password"] is True, "`fiscal_backend` tiene una contraseña almacenada."
    assert row["sin_caducidad"] is True


# ─────────────────────────────────────────────────────────────────────────────
# 9. Limpieza fiscal sobre la MISMA sesión de cliente
# ─────────────────────────────────────────────────────────────────────────────
#
# En todo lo que sigue la identidad de conexión se establece con una MARCA DE
# SESIÓN: `set_config(..., false)` --- deliberadamente no local, para que
# sobreviva a COMMIT y a ROLLBACK. Si la marca reaparece, es la misma sesión.
#
# NO se usa `pg_backend_pid()`: a través de Supavisor no identifica la sesión de
# cliente de forma fiable, y una prueba basada en él podría pasar sin haber
# demostrado reutilización.


def _session_state(conn) -> dict:
    """Estado observable de la sesión, sin tocar el schema `auth`."""
    return conn.execute(
        """
        select nullif(current_setting('app.fiscal_probe', true), '')     as probe,
               nullif(current_setting('request.jwt.claims', true), '')   as claims,
               current_user::text                                        as role
        """
    ).fetchone()


def test_rollback_fiscal_no_deja_rol_ni_identidad_en_la_sesion(
    single_connection_pool, settings, user_a, probe_table
):
    """Excepción dentro de `fiscal_transaction` → ROLLBACK → misma sesión limpia."""
    pool = single_connection_pool
    marker = "fiscal-rollback-probe"

    class Boom(RuntimeError):
        pass

    with pool.connection() as conn:
        conn.execute("select set_config('app.fiscal_probe', %s, false)", (marker,))

    # ── Transacción fiscal abortada ──
    with pytest.raises(Boom):
        with fiscal_transaction(pool, settings, user_a.identity) as conn:
            state = _session_state(conn)
            assert state["probe"] == marker, "La sesión no se reutilizó; prueba no concluyente"
            assert state["role"] == FISCAL_DB_ROLE
            assert _fiscal_identity(conn)["user_id"] == user_a.id
            # Escritura legítima que el ROLLBACK debe deshacer.
            conn.execute(
                f"insert into {PROBE} (company_id, note) values (%s, %s)",
                (user_a.company_id, "rollback-no-debe-persistir"),
            )
            raise Boom("fallo simulado: fuerza ROLLBACK")

    # ── Misma sesión, después del ROLLBACK ──
    with pool.connection() as conn:
        state = _session_state(conn)

    assert state["probe"] == marker, "La sesión no se reutilizó; prueba no concluyente"
    assert state["role"] == "app_backend", "El rol fiscal SOBREVIVIÓ al ROLLBACK"
    assert state["claims"] is None, "La identidad SOBREVIVIÓ al ROLLBACK"

    # Y sin `SET ROLE` la sesión ya no alcanza el schema fiscal.
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with pool.connection() as conn:
            conn.execute(f"select * from {PROBE}")


def test_el_rollback_fiscal_deshizo_la_escritura(admin_sql, probe_table):
    """El ROLLBACK no solo limpió la sesión: tampoco persistió la fila."""
    rows = admin_sql(
        f"select count(*) as n from {PROBE} where note = 'rollback-no-debe-persistir'"
    )
    assert rows[0]["n"] == 0, "Una transacción fiscal abortada dejó datos escritos."


def test_alternancia_fiscal_A_B_en_la_misma_sesion_sin_fuga(
    single_connection_pool, settings, user_a, user_b, probe_table
):
    """A → B → A → B sobre una sola conexión física.

    Es el escenario real del pool: dos contribuyentes distintos atendidos por la
    misma sesión de PostgreSQL. Entre transacción y transacción se comprueba que
    el rol vuelve a `app_backend` y que las claims desaparecen; dentro de cada
    una, que la identidad es la correcta y que no se ve ni una fila de la otra
    empresa.
    """
    pool = single_connection_pool
    marker = "fiscal-alternancia-probe"

    with pool.connection() as conn:
        conn.execute("select set_config('app.fiscal_probe', %s, false)", (marker,))

    def _turno(user, otro):
        with fiscal_transaction(pool, settings, user.identity) as conn:
            state = _session_state(conn)
            assert state["probe"] == marker, "La sesión no se reutilizó; prueba no concluyente"
            assert state["role"] == FISCAL_DB_ROLE
            assert _fiscal_identity(conn)["user_id"] == user.id

            visible = {
                r["c"]
                for r in conn.execute(f"select company_id::text as c from {PROBE}").fetchall()
            }
        assert visible == {user.company_id}, f"Vio empresas ajenas: {sorted(visible)}"
        assert otro.company_id not in visible, "FUGA: vio la empresa del otro contribuyente."

        # Limpieza entre turnos, sobre la misma sesión.
        with pool.connection() as conn:
            after = _session_state(conn)
        assert after["probe"] == marker, "La sesión no se reutilizó; prueba no concluyente"
        assert after["role"] == "app_backend", "El rol fiscal sobrevivió a la transacción"
        assert after["claims"] is None, "La identidad sobrevivió a la transacción"

    for user, otro in ((user_a, user_b), (user_b, user_a), (user_a, user_b), (user_b, user_a)):
        _turno(user, otro)


def test_una_transaccion_fiscal_no_hereda_la_identidad_de_la_anterior(
    single_connection_pool, settings, user_a, user_b, probe_table
):
    """Comprobación directa del vector: B nunca lee con la identidad de A."""
    pool = single_connection_pool
    marker = "fiscal-herencia-probe"

    with pool.connection() as conn:
        conn.execute("select set_config('app.fiscal_probe', %s, false)", (marker,))

    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        assert _fiscal_identity(conn)["user_id"] == user_a.id

    with fiscal_transaction(pool, settings, user_b.identity) as conn:
        state = _session_state(conn)
        assert state["probe"] == marker, "La sesión no se reutilizó; prueba no concluyente"
        identity = _fiscal_identity(conn)
        assert identity["user_id"] == user_b.id
        assert identity["user_id"] != user_a.id, "B heredó la identidad de A."
