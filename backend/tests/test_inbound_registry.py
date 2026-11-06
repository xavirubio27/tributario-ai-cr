"""C4-B1 · Registro de Buzones Tribuu e identidad de maquina (ADR-048).

Contra PostgreSQL REAL: registro, lifecycle monotonico, linaje tenant-safe,
procedencia, contexto de maquina fail-closed, capacidades C2 medidas y
topologia de roles.
"""

from __future__ import annotations

import threading
import time

import pytest
from psycopg import errors as pgerr

from app.db import (
    INBOUND_DB_ROLE,
    InboundContextError,
    fiscal_transaction,
    inbound_transaction,
    user_transaction,
    verify_backend_role,
)
from app.inbound import ALFABETO_TOKEN, LONGITUD_TOKEN, generar_routing_token

DOMINIO = "@inbox.tribuu.ai"


# ─────────────────────────────── infraestructura ─────────────────────────────

# Marcadores de fallo TRANSITORIO del CLI de Supabase (login temporal, 401, 5xx):
# el teardown reintenta ante ellos para no dejar estado residual que rompa el
# siguiente test con company_inboxes_one_active. Patrón calcado de test_fiscal_inbox.
_CLI_TRANSITORIOS = ("unexpected status 401", "unexpected login role status 401",
                     "LegacyDbConfigConnectTempRoleError", "LegacyDbConfigLoginRoleStatusError",
                     "unexpected status 5", "cli_login_postgres")


def _limpiar_inboxes(admin_sql, company_ids, intentos=4):
    ids = ", ".join(f"'{c}'" for c in company_ids)
    sql = f"delete from inbound.company_inboxes where company_id in ({ids})"
    ultimo = None
    for i in range(intentos):
        try:
            admin_sql(sql)
            return
        except Exception as exc:            # noqa: BLE001
            if not any(t in str(exc) for t in _CLI_TRANSITORIOS):
                raise
            ultimo = str(exc)[:120]
            time.sleep(1 + i)
    raise AssertionError(f"cleanup de inboxes falló por transporte del CLI: {ultimo}")


@pytest.fixture(autouse=True)
def limpio(admin_sql, user_a, user_b):
    # Limpieza DETERMINISTA: antes (por si un teardown previo falló) y después,
    # con reintento ante fallos transitorios del CLI. Un test fallido no debe
    # dejar un active inbox que rompa el siguiente con one_active.
    companies = (user_a.company_id, user_b.company_id)
    _limpiar_inboxes(admin_sql, companies)
    yield
    _limpiar_inboxes(admin_sql, companies)


def _crear(conn, company_id, prefijo="empresa", token=None):
    token = token or generar_routing_token()
    return conn.execute(
        "insert into inbound.company_inboxes (company_id, display_prefix, local_token) "
        "values (%s, %s, %s) returning id, address, local_token, created_by, status",
        (company_id, prefijo, token),
    ).fetchone()


def _buzon_activo(pool, settings, user, prefijo="empresa"):
    with fiscal_transaction(pool, settings, user.identity) as conn:
        return _crear(conn, user.company_id, prefijo)


def _rotar(conn, company_id, viejo_id, prefijo="empresa"):
    conn.execute(
        "update inbound.company_inboxes set status='disabled', "
        "disabled_at=now(), disabled_reason='rotated' where id=%s and company_id=%s",
        (viejo_id, company_id),
    )
    return conn.execute(
        "insert into inbound.company_inboxes "
        "(company_id, display_prefix, local_token, rotated_from_id) "
        "values (%s, %s, %s, %s) returning id, address",
        (company_id, prefijo, generar_routing_token(), viejo_id),
    ).fetchone()


# ───────────────────────────────── token CSPRNG ──────────────────────────────

def test_el_token_cumple_alfabeto_y_longitud():
    for _ in range(200):
        t = generar_routing_token()
        assert len(t) == LONGITUD_TOKEN == 20
        assert all(c in ALFABETO_TOKEN for c in t)
    assert set(ALFABETO_TOKEN) == set("abcdefghijklmnopqrstuvwxyz234567")


def test_una_muestra_grande_no_tiene_duplicados():
    muestra = {generar_routing_token() for _ in range(20_000)}
    assert len(muestra) == 20_000


# ─────────────────────────────── registro: humanos ───────────────────────────

def test_owner_crea_y_la_direccion_es_canonica(pool, settings, user_a):
    fila = _buzon_activo(pool, settings, user_a, prefijo="pixdea")
    assert fila["address"] == f"pixdea-{fila['local_token']}{DOMINIO}"
    assert fila["status"] == "active"
    assert str(fila["created_by"]) == user_a.id          # procedencia por DEFAULT


def test_editor_crea_viewer_no(pool, settings, user_b, admin_sql):
    original = admin_sql(
        f"select role from public.company_memberships "
        f"where company_id='{user_b.company_id}' and user_id='{user_b.id}'")[0]["role"]
    try:
        admin_sql(f"update public.company_memberships set role='editor' "
                  f"where company_id='{user_b.company_id}' and user_id='{user_b.id}'")
        fila = _buzon_activo(pool, settings, user_b)
        admin_sql(f"delete from inbound.company_inboxes where id='{fila['id']}'")

        admin_sql(f"update public.company_memberships set role='viewer' "
                  f"where company_id='{user_b.company_id}' and user_id='{user_b.id}'")
        with pytest.raises(pgerr.Error):
            _buzon_activo(pool, settings, user_b)
    finally:
        admin_sql(f"update public.company_memberships set role='{original}' "
                  f"where company_id='{user_b.company_id}' and user_id='{user_b.id}'")


def test_viewer_lee_y_el_no_miembro_no_ve_nada(pool, settings, user_a, user_b, admin_sql):
    _buzon_activo(pool, settings, user_a)
    original = admin_sql(
        f"select role from public.company_memberships "
        f"where company_id='{user_a.company_id}' and user_id='{user_a.id}'")[0]["role"]
    try:
        admin_sql(f"update public.company_memberships set role='viewer' "
                  f"where company_id='{user_a.company_id}' and user_id='{user_a.id}'")
        with fiscal_transaction(pool, settings, user_a.identity) as conn:
            n = conn.execute("select count(*) as n from inbound.company_inboxes "
                             "where company_id=%s", (user_a.company_id,)).fetchone()["n"]
        assert n == 1
    finally:
        admin_sql(f"update public.company_memberships set role='{original}' "
                  f"where company_id='{user_a.company_id}' and user_id='{user_a.id}'")
    # user_b NO es miembro de la empresa A: RLS vacio
    with fiscal_transaction(pool, settings, user_b.identity) as conn:
        n = conn.execute("select count(*) as n from inbound.company_inboxes "
                         "where company_id=%s", (user_a.company_id,)).fetchone()["n"]
    assert n == 0


def test_procedencia_forjada_se_rechaza(pool, settings, user_a, user_b):
    with pytest.raises(pgerr.Error):
        with fiscal_transaction(pool, settings, user_a.identity) as conn:
            conn.execute(
                "insert into inbound.company_inboxes "
                "(company_id, display_prefix, local_token, created_by) "
                "values (%s, 'x', %s, %s)",
                (user_a.company_id, generar_routing_token(), user_b.id),
            )


def test_sin_identidad_autenticada_el_insert_falla(pool, settings, user_a):
    with pytest.raises(pgerr.Error):
        with pool.connection() as conn:
            with conn.transaction():
                conn.execute("SET LOCAL ROLE fiscal_backend")   # sin claims
                conn.execute(
                    "insert into inbound.company_inboxes "
                    "(company_id, display_prefix, local_token) values (%s,'x',%s)",
                    (user_a.company_id, generar_routing_token()),
                )


def test_fiscal_backend_no_toca_auth_directamente(pool, settings, user_a):
    with pool.connection() as conn:
        ok = conn.execute(
            "select has_schema_privilege('fiscal_backend','auth','USAGE') as u"
        ).fetchone()["u"]
    assert ok is False, "fiscal_backend no debe recibir USAGE sobre auth (ADR-048)"


# ─────────────────────────────── unicidad y carreras ─────────────────────────

def test_un_solo_activo_global_por_empresa(pool, settings, user_a):
    _buzon_activo(pool, settings, user_a)
    with pytest.raises(pgerr.UniqueViolation):
        _buzon_activo(pool, settings, user_a, prefijo="otro")


def test_creacion_concurrente_solo_una_gana(pool, settings, user_a):
    listo = threading.Barrier(2)
    resultados: list[str] = []

    def intentar():
        try:
            listo.wait(timeout=10)
            _buzon_activo(pool, settings, user_a)
            resultados.append("ok")
        except pgerr.UniqueViolation:
            resultados.append("unique")
        except Exception as exc:          # noqa: BLE001
            resultados.append(type(exc).__name__)

    hilos = [threading.Thread(target=intentar) for _ in range(2)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(timeout=30)
    assert sorted(resultados) == ["ok", "unique"], resultados


def test_direccion_y_token_son_unicos_globalmente(pool, settings, user_a, user_b):
    fila = _buzon_activo(pool, settings, user_a)
    with pytest.raises(pgerr.UniqueViolation):
        with fiscal_transaction(pool, settings, user_b.identity) as conn:
            _crear(conn, user_b.company_id, "empresa", fila["local_token"])


# ─────────────────────────────── lifecycle y linaje ──────────────────────────

def test_rotacion_atomica_con_linaje(pool, settings, user_a):
    viejo = _buzon_activo(pool, settings, user_a)
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        nuevo = _rotar(conn, user_a.company_id, viejo["id"])
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        filas = conn.execute(
            "select id, status, disabled_reason, rotated_from_id "
            "from inbound.company_inboxes where company_id=%s order by created_at",
            (user_a.company_id,)).fetchall()
    assert filas[0]["status"] == "disabled" and filas[0]["disabled_reason"] == "rotated"
    assert filas[1]["status"] == "active"
    assert filas[1]["rotated_from_id"] == viejo["id"]
    assert nuevo["address"] != viejo["address"]


def test_un_buzon_deshabilitado_esta_congelado(pool, settings, user_a):
    viejo = _buzon_activo(pool, settings, user_a)
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        _rotar(conn, user_a.company_id, viejo["id"])
    for sql in (
        "update inbound.company_inboxes set status='active', disabled_at=null, "
        "  disabled_reason=null where id=%s",                       # reactivar
        "update inbound.company_inboxes set disabled_reason='revoked' where id=%s",
    ):
        with pytest.raises(pgerr.Error):
            with fiscal_transaction(pool, settings, user_a.identity) as conn:
                conn.execute(sql, (viejo["id"],))


def test_la_identidad_es_inmutable_incluso_para_admin(pool, settings, user_a, admin_sql):
    from conftest import AdminSqlError   # noqa: PLC0415
    fila = _buzon_activo(pool, settings, user_a)
    with pytest.raises(AdminSqlError):
        admin_sql("update inbound.company_inboxes "
                  f"set display_prefix='hackeado' where id='{fila['id']}'")


def test_delete_fisico_prohibido(pool, settings, user_a):
    fila = _buzon_activo(pool, settings, user_a)
    with pytest.raises(pgerr.InsufficientPrivilege):
        with fiscal_transaction(pool, settings, user_a.identity) as conn:
            conn.execute("delete from inbound.company_inboxes where id=%s", (fila["id"],))


def test_linaje_cross_tenant_imposible(pool, settings, user_a, user_b):
    viejo = _buzon_activo(pool, settings, user_a)
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        _rotar(conn, user_a.company_id, viejo["id"])
    with pytest.raises(pgerr.Error):   # FK compuesta: predecesor de OTRA empresa
        with fiscal_transaction(pool, settings, user_b.identity) as conn:
            conn.execute(
                "insert into inbound.company_inboxes "
                "(company_id, display_prefix, local_token, rotated_from_id) "
                "values (%s,'x',%s,%s)",
                (user_b.company_id, generar_routing_token(), viejo["id"]),
            )


def test_el_predecesor_debe_estar_rotado(pool, settings, user_a):
    # no se puede 'rotar desde' un buzon que sigue ACTIVO
    activo = _buzon_activo(pool, settings, user_a)
    with pytest.raises(pgerr.Error):
        with fiscal_transaction(pool, settings, user_a.identity) as conn:
            conn.execute(
                "insert into inbound.company_inboxes "
                "(company_id, display_prefix, local_token, rotated_from_id) "
                "values (%s,'x',%s,%s)",
                (user_a.company_id, generar_routing_token(), activo["id"]),
            )


def test_un_solo_sucesor_por_predecesor(pool, settings, user_a):
    viejo = _buzon_activo(pool, settings, user_a)
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        nuevo = _rotar(conn, user_a.company_id, viejo["id"])
    # deshabilitar el nuevo y pretender un SEGUNDO sucesor del MISMO viejo
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        conn.execute("update inbound.company_inboxes set status='disabled', "
                     "disabled_at=now(), disabled_reason='revoked' where id=%s",
                     (nuevo["id"],))
    with pytest.raises(pgerr.UniqueViolation):
        with fiscal_transaction(pool, settings, user_a.identity) as conn:
            conn.execute(
                "insert into inbound.company_inboxes "
                "(company_id, display_prefix, local_token, rotated_from_id) "
                "values (%s,'x',%s,%s)",
                (user_a.company_id, generar_routing_token(), viejo["id"]),
            )


# ─────────────────────────────── direccion canonica ──────────────────────────

def test_no_se_puede_escribir_address_explicita(pool, settings, user_a):
    with pytest.raises(pgerr.Error):   # GENERATED ALWAYS
        with fiscal_transaction(pool, settings, user_a.identity) as conn:
            conn.execute(
                "insert into inbound.company_inboxes "
                "(company_id, display_prefix, local_token, address) "
                "values (%s,'x',%s,'x@inbox.tribuu.ai')",
                (user_a.company_id, generar_routing_token()),
            )


@pytest.mark.parametrize(("prefijo", "token"), [
    ("Mayus",      None),               # prefijo con mayuscula
    ("con-guion",  None),               # separador dentro del prefijo
    ("x" * 31,     None),               # prefijo demasiado largo
    ("x",          "corto2abc"),        # token < 16
    ("x",          "TOKENMAYUSCULA22222222"),   # alfabeto invalido
    ("x",          "abcdefghijklmnop018"),      # '0','1','8' fuera de base32
    ("x" * 30,     "a" * 40),           # local-part > 64
])
def test_formas_invalidas_se_rechazan(pool, settings, user_a, prefijo, token):
    with pytest.raises(pgerr.Error):
        with fiscal_transaction(pool, settings, user_a.identity) as conn:
            _crear(conn, user_a.company_id, prefijo, token or generar_routing_token())


# ─────────────────────────────── contexto de maquina ─────────────────────────

def test_a_resuelve_a_y_b_resuelve_b(pool, settings, user_a, user_b):
    fa = _buzon_activo(pool, settings, user_a)
    fb = _buzon_activo(pool, settings, user_b, prefijo="empresab")
    with inbound_transaction(pool, settings, fa["address"]) as conn:
        assert str(conn.execute("select private.inbound_company_id() as c").fetchone()["c"]) \
            == user_a.company_id
        assert str(conn.execute("select private.inbound_inbox_id() as i").fetchone()["i"]) \
            == str(fa["id"])
    with inbound_transaction(pool, settings, fb["address"]) as conn:
        assert str(conn.execute("select private.inbound_company_id() as c").fetchone()["c"]) \
            == user_b.company_id


def test_desconocida_o_deshabilitada_no_abren_contexto(pool, settings, user_a):
    viejo = _buzon_activo(pool, settings, user_a)
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        _rotar(conn, user_a.company_id, viejo["id"])
    with pytest.raises(InboundContextError):
        with inbound_transaction(pool, settings, f"nadie-{'a'*20}{DOMINIO}"):
            pass
    with pytest.raises(InboundContextError):
        with inbound_transaction(pool, settings, viejo["address"]):   # rotada
            pass


def test_enter_desconocida_limpia_el_contexto_previo(pool, settings, user_a):
    fa = _buzon_activo(pool, settings, user_a)
    with inbound_transaction(pool, settings, fa["address"]) as conn:
        assert conn.execute("select private.inbound_company_id() as c").fetchone()["c"] is not None
        # MISMA transaccion: resolver una desconocida DEBE vaciar el contexto A
        r = conn.execute("select private.enter_inbound_context(%s) as c",
                         (f"nadie-{'b'*20}{DOMINIO}",)).fetchone()["c"]
        assert r is None
        assert conn.execute("select private.inbound_company_id() as c").fetchone()["c"] is None
        assert conn.execute("select private.inbound_inbox_id() as i").fetchone()["i"] is None


def test_guc_malformado_o_forjado_falla_cerrado(pool, settings, user_a, user_b):
    fa = _buzon_activo(pool, settings, user_a)
    with inbound_transaction(pool, settings, fa["address"]) as conn:
        # basura
        conn.execute("select set_config('request.inbound_context','{basura',true)")
        assert conn.execute("select private.inbound_company_id() as c").fetchone()["c"] is None
        # par forjado: inbox de A con company de B -> par inexistente
        conn.execute(
            "select set_config('request.inbound_context', %s, true)",
            ('{"inbox_id": "%s", "company_id": "%s"}' % (fa["id"], user_b.company_id),),
        )
        assert conn.execute("select private.inbound_company_id() as c").fetchone()["c"] is None


def test_el_contexto_muere_con_la_transaccion(single_connection_pool, settings, user_a):
    pool = single_connection_pool
    fa = _buzon_activo(pool, settings, user_a)
    with inbound_transaction(pool, settings, fa["address"]) as conn:
        assert conn.execute("select private.inbound_company_id() as c").fetchone()["c"] is not None
    # misma conexion fisica, transaccion nueva: contexto inexistente
    with pool.connection() as conn:
        with conn.transaction():
            conn.execute(f"SET LOCAL ROLE {INBOUND_DB_ROLE}")
            assert conn.execute("select private.inbound_company_id() as c").fetchone()["c"] is None


def test_usuarios_y_fiscal_no_pueden_entrar_al_contexto(pool, settings, user_a):
    with pytest.raises(pgerr.InsufficientPrivilege):
        with user_transaction(pool, settings, user_a.identity) as conn:
            conn.execute("select private.enter_inbound_context('x@inbox.tribuu.ai')")
    with pytest.raises(pgerr.InsufficientPrivilege):
        with fiscal_transaction(pool, settings, user_a.identity) as conn:
            conn.execute("select private.enter_inbound_context('x@inbox.tribuu.ai')")


def test_recipient_vacio_no_abre_trabajo(pool, settings):
    with pytest.raises(InboundContextError):
        with inbound_transaction(pool, settings, "   "):
            pass


# ─────────────────────────── capacidades C2 de la maquina ────────────────────

def test_la_maquina_captura_y_gestiona_ciclo_en_su_empresa(pool, settings, user_a):
    fa = _buzon_activo(pool, settings, user_a)
    with inbound_transaction(pool, settings, fa["address"]) as conn:
        fila = conn.execute(
            "insert into fiscal.source_documents "
            "(company_id, raw_xml, content_sha256, ingestion_source) "
            "values (%s, %s, sha256(%s), 'email') returning id, content_sha256",
            (user_a.company_id, b"<x/>", b"<x/>"),
        ).fetchone()
        # UPDATE de las 9 columnas del ciclo (en dos sentencias reales de C2)
        conn.execute(
            "update fiscal.source_documents set parse_status='failed', "
            "parse_error='malformed_xml', schema_detection_status='failed', "
            "detected_document_type=null, detected_schema_version=null, "
            "parse_attempt_count=parse_attempt_count+1, parse_attempted_at=now(), "
            "updated_at=now() where id=%s and company_id=%s",
            (fila["id"], user_a.company_id),
        )
        # SELECT de columnas concedidas
        leida = conn.execute(
            "select id, company_id, raw_xml, content_sha256, parse_status, "
            "parse_attempt_count, schema_detection_status, electronic_document_id "
            "from fiscal.source_documents where id=%s and company_id=%s",
            (fila["id"], user_a.company_id),
        ).fetchone()
        assert bytes(leida["raw_xml"]) == b"<x/>"
        assert leida["parse_status"] == "failed"


def test_la_maquina_de_a_no_ve_ni_escribe_en_b(pool, settings, user_a, user_b, admin_sql):
    fa = _buzon_activo(pool, settings, user_a)
    _buzon_activo(pool, settings, user_b, prefijo="empresab")
    admin_sql(
        "insert into fiscal.source_documents (company_id, raw_xml, content_sha256, ingestion_source) "
        f"values ('{user_b.company_id}', 'x'::bytea, sha256('x'::bytea), 'manual_upload')"
    )
    try:
        with inbound_transaction(pool, settings, fa["address"]) as conn:
            n = conn.execute("select count(*) as n from fiscal.source_documents "
                             "where company_id=%s", (user_b.company_id,)).fetchone()["n"]
            assert n == 0, "la maquina de A no puede ver filas de B"
        with pytest.raises(pgerr.Error):   # WITH CHECK: escribir en B desde contexto A
            with inbound_transaction(pool, settings, fa["address"]) as conn:
                conn.execute(
                    "insert into fiscal.source_documents "
                    "(company_id, raw_xml, content_sha256, ingestion_source) "
                    "values (%s, 'y'::bytea, sha256('y'::bytea), 'email')",
                    (user_b.company_id,),
                )
    finally:
        admin_sql("delete from fiscal.source_documents "
                  f"where company_id in ('{user_a.company_id}','{user_b.company_id}')")


def test_privilegios_no_concedidos_fallan(pool, settings, user_a, admin_sql):
    fa = _buzon_activo(pool, settings, user_a)
    with inbound_transaction(pool, settings, fa["address"]) as conn:
        sdoc = conn.execute(
            "insert into fiscal.source_documents "
            "(company_id, raw_xml, content_sha256, ingestion_source) "
            "values (%s, 'z'::bytea, sha256('z'::bytea), 'email') returning id",
            (user_a.company_id,),
        ).fetchone()["id"]
    try:
        casos = [
            # columna NO concedida en UPDATE: evidencia inmutable
            ("update fiscal.source_documents set raw_xml='h'::bytea where id=%s", (sdoc,)),
            ("update fiscal.source_documents set content_sha256=sha256('h'::bytea) where id=%s", (sdoc,)),
            ("update fiscal.source_documents set ingestion_source='api' where id=%s", (sdoc,)),
            # columna NO concedida en SELECT
            ("select parse_error from fiscal.source_documents where id=%s", (sdoc,)),
            # DELETE inexistente
            ("delete from fiscal.source_documents where id=%s", (sdoc,)),
            # tablas de tenancy/identidad: vedadas
            ("select id from public.companies limit 1", ()),
            ("select user_id from public.company_memberships limit 1", ()),
            # helpers de usuario: vedados
            ("select private.can_write_company(%s)", (sdoc,)),
            # auth: vedado
            ("select auth.uid()", ()),
        ]
        for sql, params in casos:
            with pytest.raises(pgerr.Error):
                with inbound_transaction(pool, settings, fa["address"]) as conn:
                    conn.execute(sql, params)
    finally:
        admin_sql(f"delete from fiscal.source_documents where id='{sdoc}'")


def test_grants_de_catalogo_exactos(admin_sql):
    # Los has_*_privilege se consultan como rol privilegiado: `app_backend` no
    # tiene USAGE sobre el schema `fiscal` y no podria ni resolver los nombres.
    # Lo que se verifica es el grant a `inbound_backend`, no quien pregunta.
    def tiene(tabla, priv):
        return admin_sql(
            f"select has_table_privilege('inbound_backend', '{tabla}', '{priv}') as p"
        )[0]["p"]

    def col(tabla, columna, priv):
        return admin_sql(
            f"select has_column_privilege('inbound_backend', '{tabla}', '{columna}', '{priv}') as p"
        )[0]["p"]

    assert tiene("fiscal.document_parties", "INSERT")
    assert tiene("fiscal.document_lines", "INSERT")
    assert tiene("fiscal.line_discounts", "INSERT")
    assert tiene("fiscal.line_taxes", "INSERT")
    assert tiene("fiscal.document_references", "INSERT")
    assert tiene("fiscal.electronic_documents", "INSERT")
    assert not tiene("fiscal.electronic_documents", "UPDATE")
    assert not tiene("fiscal.document_parties", "SELECT")
    assert not tiene("fiscal.line_taxes", "DELETE")
    assert not tiene("inbound.company_inboxes", "SELECT")
    assert not tiene("public.companies", "SELECT")
    # RETURNING id en document_lines (persistence.py:289): SELECT(id) y nada mas
    assert col("fiscal.document_lines", "id", "SELECT")
    assert not col("fiscal.document_lines", "description", "SELECT")


# ─────────────────────────────── topologia de roles ──────────────────────────

def test_topologia_del_rol_inbound(pool):
    with pool.connection() as conn:
        r = conn.execute(
            "select rolcanlogin, rolsuper, rolbypassrls, rolinherit "
            "from pg_roles where rolname = %s", (INBOUND_DB_ROLE,)).fetchone()
    assert r is not None
    assert not r["rolcanlogin"] and not r["rolsuper"]
    assert not r["rolbypassrls"] and not r["rolinherit"]


def test_la_verificacion_de_arranque_pasa_con_la_nueva_topologia(pool):
    verify_backend_role(pool)   # no debe levantar


def test_la_verificacion_detecta_miembros_inesperados():
    from app.db import _check_inbound_role_members
    from app.db import RoleVerificationError
    filas_ok = [
        {"member": "app_backend", "inherit_option": False, "set_option": True, "admin_option": False},
        {"member": "postgres", "inherit_option": False, "set_option": False, "admin_option": True},
    ]
    _check_inbound_role_members(filas_ok, {"app_backend"})
    with pytest.raises(RoleVerificationError):
        _check_inbound_role_members(
            filas_ok + [{"member": "intruso", "inherit_option": False,
                         "set_option": True, "admin_option": False}],
            {"app_backend", "intruso"})


# ═════════════════════════════════════════════════════════════════════════════
# E2E · C2 canónico REAL bajo inbound_backend (cierre del gap L2 de Codex)
#
# Invoca los primitivos PRODUCTIVOS de C2 —capture_source_document y
# process_source_document— dentro de inbound_transaction(), es decir bajo el
# rol de máquina con contexto resuelto por recipient y RLS activa. NO se
# reimplementa C2 ni se tocan grants/políticas.
# ═════════════════════════════════════════════════════════════════════════════

from pathlib import Path   # noqa: E402

from app.fiscal.ingestion import (   # noqa: E402
    IngestionSource,
    ProcessingStatus,
    capture_source_document,
    process_source_document,
)

_FIXTURES = Path(__file__).parent / "fixtures" / "fiscal" / "real" / "v4_4"
_FE = "50601082600310161019803900001010004596121100"


def _fe_bytes() -> bytes:
    for sub in ("fe", "te", "nc", "mh"):
        for p in (_FIXTURES / sub).glob("*.xml"):
            if p.name.startswith(_FE):
                return p.read_bytes()
    raise AssertionError("fixture FE no encontrado")


@pytest.fixture
def limpio_fiscal(admin_sql, user_a, user_b):
    _limpiar_inboxes(admin_sql, (user_a.company_id, user_b.company_id))
    yield
    ambas = f"('{user_a.company_id}','{user_b.company_id}')"
    admin_sql(
        f"with s as (delete from fiscal.source_documents where company_id in {ambas} returning 1) "
        f"delete from fiscal.electronic_documents where company_id in {ambas}"
    )


def test_c2_canonico_corre_bajo_inbound_backend(
    pool, settings, user_a, limpio_fiscal
):
    """recipient activo → contexto máquina → C2 real → SourceDocument +
    ElectronicDocument + hijas, todo bajo inbound_backend y RLS.

    El company_id que reciben los primitivos NO es autoridad: lo toma del
    contexto resuelto por el recipient (private.inbound_company_id()), y la
    RLS de máquina lo revalida en cada escritura.
    """
    fa = _buzon_activo(pool, settings, user_a, prefijo="pixdea")
    raw = _fe_bytes()

    with inbound_transaction(pool, settings, fa["address"]) as conn:
        # company_id DEL CONTEXTO, no inventado por el llamante
        company_id = str(
            conn.execute("select private.inbound_company_id() as c").fetchone()["c"]
        )
        assert company_id == user_a.company_id

        captura = capture_source_document(
            conn, company_id=company_id, raw_xml=raw,
            ingestion_source=IngestionSource.EMAIL,
        )
        assert captura.source_document_id

        veredicto = process_source_document(
            conn, company_id=company_id,
            source_document_id=captura.source_document_id,
        )
        assert veredicto.status is ProcessingStatus.CREATED
        edoc_id = veredicto.electronic_document_id
        assert edoc_id

        # El enlace quedó sobre el tenant correcto. Dentro del contexto de
        # máquina SOLO se leen columnas que C2 tiene concedidas en SELECT
        # (company_id, electronic_document_id): `ingestion_source` NO está
        # concedida —C2 nunca la relee— y leerla aquí daría permission denied,
        # que es justamente la frontera de mínimo privilegio funcionando.
        fila = conn.execute(
            "select company_id, electronic_document_id "
            "from fiscal.source_documents where id=%s",
            (captura.source_document_id,),
        ).fetchone()
        assert str(fila["company_id"]) == user_a.company_id
        assert str(fila["electronic_document_id"]) == edoc_id

    # Evidencia y hechos fiscales se verifican por el camino HUMANO
    # (fiscal_backend lee todas las columnas): persistencia tras COMMIT,
    # ingestion_source='email', y las hijas. document_lines se pobló con
    # INSERT ... RETURNING id bajo inbound_backend (grant SELECT(id)); si ese
    # grant faltara, process_source_document habría fallado antes del COMMIT.
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        persistida = conn.execute(
            "select electronic_document_id, ingestion_source "
            "from fiscal.source_documents where id=%s",
            (captura.source_document_id,),
        ).fetchone()
        assert str(persistida["electronic_document_id"]) == edoc_id
        assert persistida["ingestion_source"] == "email"
        n_lineas = conn.execute(
            "select count(*) as n from fiscal.document_lines "
            "where company_id=%s and electronic_document_id=%s",
            (user_a.company_id, edoc_id),
        ).fetchone()["n"]
        n_partes = conn.execute(
            "select count(*) as n from fiscal.document_parties "
            "where company_id=%s and electronic_document_id=%s",
            (user_a.company_id, edoc_id),
        ).fetchone()["n"]
    assert n_lineas >= 1
    assert n_partes >= 1


def test_c2_bajo_inbound_no_escribe_en_otro_tenant(
    pool, settings, user_a, user_b, limpio_fiscal
):
    """Contexto de A: capturar declarando company_id de B lo rechaza la RLS."""
    fa = _buzon_activo(pool, settings, user_a, prefijo="pixdea")
    with pytest.raises(Exception):  # noqa: B017,PT011 — WITH CHECK de la política de máquina
        with inbound_transaction(pool, settings, fa["address"]) as conn:
            capture_source_document(
                conn, company_id=user_b.company_id, raw_xml=_fe_bytes(),
                ingestion_source=IngestionSource.EMAIL,
            )
    # B no recibió nada
    with fiscal_transaction(pool, settings, user_b.identity) as conn:
        n = conn.execute(
            "select count(*) as n from fiscal.source_documents where company_id=%s",
            (user_b.company_id,),
        ).fetchone()["n"]
    assert n == 0


def test_el_rol_y_el_contexto_no_se_filtran_al_pool(single_connection_pool, settings, user_a):
    """Tras la transacción inbound, la MISMA conexión física no conserva ni el
    rol inbound_backend ni el GUC de contexto."""
    pool = single_connection_pool
    fa = _buzon_activo(pool, settings, user_a, prefijo="pixdea")
    with inbound_transaction(pool, settings, fa["address"]) as conn:
        assert conn.execute("select private.inbound_company_id() as c").fetchone()["c"] is not None
    with pool.connection() as conn:
        rol = conn.execute("select current_user as u").fetchone()["u"]
        assert rol == "app_backend", f"el rol se filtró: {rol}"
        ctx = conn.execute(
            "select current_setting('request.inbound_context', true) as c"
        ).fetchone()["c"]
        assert ctx in (None, ""), "el contexto inbound sobrevivió al pool"



