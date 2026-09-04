"""Esquema fiscal: estructura, integridad, aislamiento y autorización (fase E3).

Prueban la migración `20260830132124_create_fiscal_domain_tables`, que crea las
siete tablas del dominio fiscal conforme a ADR-032…ADR-038.

A diferencia de la tabla canario del Checkpoint D, estas tablas son PERMANENTES.
Cada test limpia sus propias filas; ninguna prueba deja datos.
"""

from __future__ import annotations

import hashlib
import uuid

import httpx
import psycopg
import pytest

from app.db import fiscal_transaction, user_transaction

TABLES = (
    "source_documents",
    "electronic_documents",
    "document_parties",
    "document_lines",
    "line_discounts",
    "line_taxes",
    "document_references",
)

# Columnas con `UPDATE` concedido, por tabla (ADR-036 §26.3).
MUTABLE = {
    "source_documents": {
        "parse_status", "parse_error", "parse_attempted_at", "parse_attempt_count",
        "schema_detection_status", "detected_document_type", "detected_schema_version",
        "electronic_document_id", "updated_at",
    },
    "electronic_documents": {
        "ruleset_revision", "ruleset_revision_status", "direction",
        "direction_computed_at", "updated_at",
    },
    "document_references": {"resolved_document_id"},
}


def _clave(seed: int = 0) -> str:
    """50 dígitos. No pretende ser una clave real: prueba la FORMA."""
    return f"506{seed:047d}"


def _consecutive(seed: int = 0) -> str:
    return f"{seed:020d}"


XML = b"<FacturaElectronica>prueba</FacturaElectronica>"
SHA = hashlib.sha256(XML).digest()


# ─────────────────────────────────────────────────────────────────────────────
# Utilidades de inserción — dentro de una transacción fiscal ya abierta
# ─────────────────────────────────────────────────────────────────────────────


def _insert_document(conn, company_id: str, *, seed: int, marker: str) -> str:
    row = conn.execute(
        """
        insert into fiscal.electronic_documents (
            company_id, document_type, clave, consecutive_number,
            issued_at_local, issued_at, issued_at_offset_minutes, issued_at_raw,
            issuer_activity_code, sale_condition_code,
            currency_code, reported_exchange_rate,
            reported_total_sale, reported_total_net_sale, reported_total_document,
            ruleset_revision_status, direction, direction_computed_at
        ) values (
            %s, 'invoice', %s, %s,
            timestamp '2026-08-01 05:24:09', timestamptz '2026-08-01T11:24:09+00:00', -360, %s,
            '620100', '01',
            'CRC', 1,
            100, 100, 113,
            'detected', 'issued', now()
        ) returning id::text as id
        """,
        (company_id, _clave(seed), _consecutive(seed), marker),
    ).fetchone()
    return row["id"]


def _insert_source(conn, company_id: str, *, edoc_id: str | None = None) -> str:
    row = conn.execute(
        """
        insert into fiscal.source_documents
            (company_id, raw_xml, content_sha256, ingestion_source, electronic_document_id)
        values (%s, %s, %s, 'manual_upload', %s)
        returning id::text as id
        """,
        (company_id, XML, SHA, edoc_id),
    ).fetchone()
    return row["id"]


@pytest.fixture(scope="module")
def clean_fiscal(admin_sql, user_a, user_b):
    """Retira SOLO las filas de las empresas creadas por esta ejecución.

    Es de ámbito de MÓDULO a propósito: cada limpieza invoca la CLI de Supabase
    —el único camino con privilegio de DELETE, que `fiscal_backend` no tiene— y
    hacerlo por test multiplicaría el tiempo de la suite. Los tests se aíslan
    entre sí usando claves distintas y acotando sus consultas.

    **Nunca sin predicado.** Un `delete from fiscal.<tabla>` global borraría
    datos de otra ejecución concurrente o de otro desarrollador contra el mismo
    proyecto DEV. El ámbito son los UUID exactos de las dos empresas creadas por
    esta ejecución.
    """
    def _borrar():
        for company_id in (user_a.company_id, user_b.company_id):
            admin_sql(f"delete from fiscal.source_documents where company_id = '{company_id}'")
            admin_sql(f"delete from fiscal.electronic_documents where company_id = '{company_id}'")

    _borrar()
    try:
        yield
    finally:
        _borrar()


# ─────────────────────────────────────────────────────────────────────────────
# 1. Esquema
# ─────────────────────────────────────────────────────────────────────────────


def test_las_siete_tablas_existen(admin_sql):
    rows = admin_sql(
        "select table_name from information_schema.tables where table_schema = 'fiscal'"
    )
    assert {r["table_name"] for r in rows} == set(TABLES)


def test_rls_habilitada_en_las_siete(admin_sql):
    rows = admin_sql(
        """
        select c.relname, c.relrowsecurity as rls
        from pg_class c join pg_namespace n on n.oid = c.relnamespace
        where n.nspname = 'fiscal' and c.relkind = 'r'
        """
    )
    sin_rls = [r["relname"] for r in rows if not r["rls"]]
    assert not sin_rls, f"Tablas sin RLS: {sin_rls}"


def test_politicas_esperadas_y_ninguna_de_delete(admin_sql):
    rows = admin_sql(
        "select tablename, cmd from pg_policies where schemaname = 'fiscal'"
    )
    por_tabla: dict[str, set[str]] = {}
    for r in rows:
        por_tabla.setdefault(r["tablename"], set()).add(r["cmd"])
    assert set(por_tabla) == set(TABLES)
    for t, cmds in por_tabla.items():
        assert cmds == {"SELECT", "INSERT", "UPDATE"}, f"{t}: {cmds}"
    assert not [r for r in rows if r["cmd"] == "DELETE"]


def test_tipos_decimales_exactos(admin_sql):
    """Ningún importe en coma flotante (ADR-033)."""
    rows = admin_sql(
        """
        select table_name, column_name, data_type, numeric_precision, numeric_scale
        from information_schema.columns
        where table_schema = 'fiscal'
          and (column_name like 'reported_%' or column_name like '%amount%')
        """
    )
    assert rows, "No se encontró ninguna columna de importe"
    for r in rows:
        if r["column_name"] in ("reported_number", "reported_reference_date",
                                "reported_reference_date_local",
                                "reported_reference_offset_minutes",
                                "reported_reference_date_raw"):
            continue
        assert r["data_type"] == "numeric", f"{r['table_name']}.{r['column_name']} es {r['data_type']}"

    tipos = {(r["table_name"], r["column_name"]): (r["numeric_precision"], r["numeric_scale"])
             for r in rows}
    assert tipos[("document_lines", "reported_quantity")] == (16, 3)
    assert tipos[("line_taxes", "reported_rate")] == (4, 2)
    assert tipos[("electronic_documents", "reported_total_document")] == (18, 5)


def test_ningun_tipo_de_coma_flotante_en_el_schema(admin_sql):
    rows = admin_sql(
        """
        select table_name, column_name, data_type from information_schema.columns
        where table_schema = 'fiscal'
          and data_type in ('real', 'double precision')
        """
    )
    assert rows == [], f"Columnas en coma flotante: {rows}"


def test_raw_xml_es_bytea(admin_sql):
    row = admin_sql(
        """
        select data_type from information_schema.columns
        where table_schema='fiscal' and table_name='source_documents' and column_name='raw_xml'
        """
    )[0]
    assert row["data_type"] == "bytea", "El artefacto debe guardar bytes, no texto ni xml"


# ─────────────────────────────────────────────────────────────────────────────
# 2. Privilegios y ACL
# ─────────────────────────────────────────────────────────────────────────────


def test_ningun_rol_ajeno_alcanza_las_tablas_fiscales(admin_sql):
    for t in TABLES:
        row = admin_sql(
            f"""
            select has_table_privilege('authenticated','fiscal.{t}','SELECT') as auth,
                   has_table_privilege('anon','fiscal.{t}','SELECT')          as anon,
                   has_table_privilege('service_role','fiscal.{t}','SELECT')  as srv,
                   has_table_privilege('app_backend','fiscal.{t}','SELECT')   as app
            """
        )[0]
        assert not any(row.values()), f"Un rol no autorizado alcanza {t}: {row}"


def test_fiscal_backend_no_tiene_delete(admin_sql):
    for t in TABLES:
        row = admin_sql(f"select has_table_privilege('fiscal_backend','fiscal.{t}','DELETE') as d")[0]
        assert row["d"] is False, f"fiscal_backend tiene DELETE sobre {t}"


def test_no_hay_update_a_nivel_de_tabla(admin_sql):
    """Un `GRANT UPDATE` de tabla autorizaría TODAS las columnas (ADR-036)."""
    rows = admin_sql(
        """
        select table_name from information_schema.table_privileges
        where table_schema='fiscal' and grantee='fiscal_backend' and privilege_type='UPDATE'
        """
    )
    assert rows == [], f"Tablas con UPDATE de tabla: {rows}"


def test_exactamente_quince_columnas_mutables(admin_sql):
    rows = admin_sql(
        """
        select table_name, column_name from information_schema.column_privileges
        where table_schema='fiscal' and grantee='fiscal_backend' and privilege_type='UPDATE'
        """
    )
    real: dict[str, set[str]] = {}
    for r in rows:
        real.setdefault(r["table_name"], set()).add(r["column_name"])
    assert real == MUTABLE, f"Distribución inesperada: {real}"
    assert sum(len(v) for v in real.values()) == 15


def test_helper_de_escritura_cumple_su_contrato(admin_sql):
    row = admin_sql(
        """
        select p.prosecdef as definer, p.provolatile as vol,
               p.proconfig::text as config,
               pg_get_function_result(p.oid) as ret
        from pg_proc p join pg_namespace n on n.oid = p.pronamespace
        where n.nspname='private' and p.proname='can_write_company'
        """
    )[0]
    assert row["definer"] is True
    assert row["vol"] == "s", "Debe ser STABLE"
    # El valor llega con escapes de JSON: `{"search_path=\"\""}`. Se normalizan
    # antes de comparar, en lugar de asertar sobre la representación transportada.
    config = row["config"].replace("\\", "")
    assert 'search_path=""' in config, f"search_path debe estar vacío, es {row['config']}"
    assert row["ret"] == "boolean"


def test_helper_solo_ejecutable_por_fiscal_backend(admin_sql):
    row = admin_sql(
        """
        select has_function_privilege('fiscal_backend','private.can_write_company(uuid)','EXECUTE') as fb,
               has_function_privilege('authenticated','private.can_write_company(uuid)','EXECUTE') as auth,
               has_function_privilege('anon','private.can_write_company(uuid)','EXECUTE')          as anon,
               has_function_privilege('service_role','private.can_write_company(uuid)','EXECUTE')  as srv,
               has_function_privilege('app_backend','private.can_write_company(uuid)','EXECUTE')   as app
        """
    )[0]
    assert row["fb"] is True
    assert not any(v for k, v in row.items() if k != "fb"), f"ACL demasiado amplia: {row}"


def test_la_frontera_de_adr_020_sigue_intacta(admin_sql):
    row = admin_sql(
        """
        select has_schema_privilege('fiscal_backend','auth','USAGE') as auth_usage,
               has_table_privilege('fiscal_backend','public.company_memberships','SELECT') as memberships
        """
    )[0]
    assert row["auth_usage"] is False, "fiscal_backend obtuvo USAGE sobre auth"
    assert row["memberships"] is False, "fiscal_backend obtuvo SELECT sobre company_memberships"


# ─────────────────────────────────────────────────────────────────────────────
# 3. Aislamiento entre empresas
# ─────────────────────────────────────────────────────────────────────────────


def test_cada_empresa_solo_ve_lo_suyo(pool, settings, user_a, user_b, clean_fiscal):
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        _insert_document(conn, user_a.company_id, seed=1, marker="A")
    with fiscal_transaction(pool, settings, user_b.identity) as conn:
        _insert_document(conn, user_b.company_id, seed=2, marker="B")

    claves = (_clave(1), _clave(2))
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        vistos = {(r["c"], r["k"]) for r in conn.execute(
            "select company_id::text as c, clave as k from fiscal.electronic_documents "
            "where clave = any(%s)", (list(claves),)).fetchall()}
    assert vistos == {(user_a.company_id, _clave(1))}, f"A vio de más: {vistos}"

    with fiscal_transaction(pool, settings, user_b.identity) as conn:
        vistos = {(r["c"], r["k"]) for r in conn.execute(
            "select company_id::text as c, clave as k from fiscal.electronic_documents "
            "where clave = any(%s)", (list(claves),)).fetchall()}
    assert vistos == {(user_b.company_id, _clave(2))}, f"B vio de más: {vistos}"


def test_insertar_en_empresa_ajena_es_rechazado_por_rls(pool, settings, user_a, user_b, clean_fiscal):
    with pytest.raises(psycopg.errors.InsufficientPrivilege) as exc:
        with fiscal_transaction(pool, settings, user_a.identity) as conn:
            _insert_document(conn, user_b.company_id, seed=3, marker="intruso")
    assert exc.value.sqlstate == "42501"
    assert "row-level security policy" in str(exc.value), (
        "El rechazo debe venir de RLS, no de un privilegio ausente"
    )


def test_una_linea_no_puede_colgar_de_un_documento_de_otra_empresa(
    pool, settings, admin_sql, user_a, user_b, clean_fiscal
):
    """La FK compuesta lo impide en el motor, no sólo por RLS (ADR-032)."""
    with fiscal_transaction(pool, settings, user_b.identity) as conn:
        edoc_b = _insert_document(conn, user_b.company_id, seed=4, marker="B")

    with pytest.raises(psycopg.errors.ForeignKeyViolation) as exc:
        with fiscal_transaction(pool, settings, user_a.identity) as conn:
            conn.execute(
                """
                insert into fiscal.document_lines
                    (company_id, electronic_document_id, line_number, cabys_code,
                     description, unit_of_measure_code, reported_quantity,
                     reported_unit_price, reported_gross_amount, reported_subtotal,
                     reported_taxable_base, reported_net_tax, reported_line_total)
                values (%s, %s, 1, '1234567890123', 'x', 'Sp', 1, 1, 1, 1, 1, 0, 1)
                """,
                (user_a.company_id, edoc_b),
            )
    assert exc.value.sqlstate == "23503"


def test_company_id_inexistente_es_rechazado(pool, settings, user_a, clean_fiscal):
    with pytest.raises(psycopg.Error) as exc:
        with fiscal_transaction(pool, settings, user_a.identity) as conn:
            _insert_document(conn, str(uuid.uuid4()), seed=5, marker="fantasma")
    assert exc.value.sqlstate in ("23503", "42501")


# ─────────────────────────────────────────────────────────────────────────────
# 4. Roles: owner / editor / viewer
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def as_role(admin_sql, user_a):
    """Cambia el rol de A en su empresa y lo restaura al terminar."""
    original = admin_sql(
        f"select role from public.company_memberships "
        f"where company_id='{user_a.company_id}' and user_id='{user_a.id}'"
    )[0]["role"]

    def _set(role: str) -> None:
        admin_sql(
            f"update public.company_memberships set role='{role}' "
            f"where company_id='{user_a.company_id}' and user_id='{user_a.id}'"
        )

    yield _set
    _set(original)


@pytest.mark.parametrize("role", ["owner", "editor"])
def test_owner_y_editor_pueden_escribir(pool, settings, user_a, as_role, role, clean_fiscal):
    as_role(role)
    seed = 10 if role == "owner" else 15
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        doc = _insert_document(conn, user_a.company_id, seed=seed, marker=role)
    assert doc

    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        n = conn.execute(
            "select count(*) as n from fiscal.electronic_documents where clave = %s",
            (_clave(seed),),
        ).fetchone()["n"]
    assert n == 1


def test_viewer_puede_leer(pool, settings, user_a, as_role, clean_fiscal):
    as_role("owner")
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        _insert_document(conn, user_a.company_id, seed=11, marker="previo")

    as_role("viewer")
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        n = conn.execute(
            "select count(*) as n from fiscal.electronic_documents where clave = %s",
            (_clave(11),),
        ).fetchone()["n"]
    assert n == 1, "Un viewer debe poder leer los datos de su empresa"


def test_viewer_no_puede_insertar(pool, settings, user_a, as_role, clean_fiscal):
    as_role("viewer")
    with pytest.raises(psycopg.errors.InsufficientPrivilege) as exc:
        with fiscal_transaction(pool, settings, user_a.identity) as conn:
            _insert_document(conn, user_a.company_id, seed=12, marker="viewer")
    assert exc.value.sqlstate == "42501"
    assert "row-level security policy" in str(exc.value)


def test_viewer_no_puede_actualizar_metadatos(pool, settings, user_a, as_role, clean_fiscal):
    as_role("owner")
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        doc = _insert_document(conn, user_a.company_id, seed=13, marker="previo")

    as_role("viewer")
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        n = conn.execute(
            "update fiscal.electronic_documents set direction = 'received' where id = %s",
            (doc,),
        ).rowcount
    assert n == 0, "La política USING de UPDATE debe dejar la fila fuera de alcance del viewer"


@pytest.mark.parametrize("role", ["owner", "editor"])
def test_owner_y_editor_actualizan_metadatos_mutables(
    pool, settings, user_a, as_role, role, clean_fiscal
):
    as_role(role)
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        doc = _insert_document(conn, user_a.company_id, seed=(14 if role == "owner" else 16), marker=role)
        n = conn.execute(
            "update fiscal.electronic_documents "
            "set ruleset_revision = '2026-04-22', ruleset_revision_status = 'resolved' "
            "where id = %s",
            (doc,),
        ).rowcount
    assert n == 1


# ─────────────────────────────────────────────────────────────────────────────
# 5. Inmutabilidad de los hechos de origen
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "seed, columna, valor",
    [
        (201, "clave", "'" + _clave(999) + "'"),
        (202, "consecutive_number", "'" + _consecutive(999) + "'"),
        (203, "company_id", "gen_random_uuid()"),
        (204, "reported_total_document", "1"),
        (205, "document_type", "'credit_note'"),
        (206, "issued_at_raw", "'manipulado'"),
    ],
)
def test_ni_owner_puede_reescribir_hechos_de_origen(
    pool, settings, user_a, as_role, seed, columna, valor, clean_fiscal
):
    """El privilegio de columna lo impide, no la política (ADR-036 §26.2)."""
    as_role("owner")
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        doc = _insert_document(conn, user_a.company_id, seed=seed, marker="origen")

    with pytest.raises(psycopg.errors.InsufficientPrivilege) as exc:
        with fiscal_transaction(pool, settings, user_a.identity) as conn:
            conn.execute(
                f"update fiscal.electronic_documents set {columna} = {valor} where id = %s",
                (doc,),
            )
    assert exc.value.sqlstate == "42501"
    assert "permission denied" in str(exc.value), (
        "Debe rechazarlo el privilegio de columna, no RLS"
    )


@pytest.mark.parametrize("columna, valor", [("raw_xml", "'\\x00'::bytea"),
                                            ("content_sha256", "'\\x00'::bytea")])
def test_el_artefacto_de_origen_es_inmutable(
    pool, settings, user_a, as_role, columna, valor, clean_fiscal
):
    as_role("owner")
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        src = _insert_source(conn, user_a.company_id)

    with pytest.raises(psycopg.errors.InsufficientPrivilege) as exc:
        with fiscal_transaction(pool, settings, user_a.identity) as conn:
            conn.execute(
                f"update fiscal.source_documents set {columna} = {valor} where id = %s", (src,)
            )
    assert exc.value.sqlstate == "42501"
    assert "permission denied" in str(exc.value)


def test_los_metadatos_del_artefacto_si_son_mutables(pool, settings, user_a, as_role, clean_fiscal):
    as_role("owner")
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        src = _insert_source(conn, user_a.company_id)
        n = conn.execute(
            "update fiscal.source_documents "
            "set parse_status = 'failed', parse_error = 'x', parse_attempt_count = 1 "
            "where id = %s",
            (src,),
        ).rowcount
    assert n == 1


def test_no_hay_delete_en_el_flujo_normal(pool, settings, user_a, as_role, clean_fiscal):
    as_role("owner")
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        doc = _insert_document(conn, user_a.company_id, seed=21, marker="permanente")

    with pytest.raises(psycopg.errors.InsufficientPrivilege) as exc:
        with fiscal_transaction(pool, settings, user_a.identity) as conn:
            conn.execute("delete from fiscal.electronic_documents where id = %s", (doc,))
    assert exc.value.sqlstate == "42501"
    assert "permission denied" in str(exc.value)


# ─────────────────────────────────────────────────────────────────────────────
# 6. Restricciones de forma y valor
# ─────────────────────────────────────────────────────────────────────────────


def test_la_huella_correcta_se_acepta(pool, settings, user_a, clean_fiscal):
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        assert _insert_source(conn, user_a.company_id)


@pytest.mark.parametrize(
    "sha, motivo",
    [
        (hashlib.sha256(b"otro").digest(), "no corresponde a los bytes"),
        (b"\x00" * 31, "31 bytes"),
        (b"\x00" * 33, "33 bytes"),
    ],
)
def test_la_huella_incorrecta_se_rechaza(pool, settings, user_a, sha, motivo, clean_fiscal):
    with pytest.raises(psycopg.errors.CheckViolation) as exc:
        with fiscal_transaction(pool, settings, user_a.identity) as conn:
            conn.execute(
                "insert into fiscal.source_documents "
                "(company_id, raw_xml, content_sha256, ingestion_source) values (%s,%s,%s,'api')",
                (user_a.company_id, XML, sha),
            )
    assert exc.value.sqlstate == "23514", motivo


def test_un_xml_mal_formado_se_conserva_igual(pool, settings, user_a, clean_fiscal):
    """El artefacto ilegible es justo el que hay que preservar (ADR-037)."""
    basura = b"\x00\x01esto no es XML\xff"
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        row = conn.execute(
            "insert into fiscal.source_documents "
            "(company_id, raw_xml, content_sha256, ingestion_source, schema_detection_status) "
            "values (%s,%s,%s,'email','failed') returning octet_length(raw_xml) as n",
            (user_a.company_id, basura, hashlib.sha256(basura).digest()),
        ).fetchone()
    assert row["n"] == len(basura)


@pytest.mark.parametrize(
    "clave, valido",
    [
        ("5" * 50, True),
        ("5" * 49, False),
        ("5" * 51, False),
        ("5" * 49 + "a", False),
        ("5" * 49 + " ", False),
    ],
)
def test_forma_de_la_clave(pool, settings, user_a, clave, valido, clean_fiscal):
    def _do():
        with fiscal_transaction(pool, settings, user_a.identity) as conn:
            conn.execute(
                """
                insert into fiscal.electronic_documents (
                    company_id, document_type, clave, consecutive_number,
                    issued_at_local, issued_at, issued_at_offset_minutes, issued_at_raw,
                    issuer_activity_code, sale_condition_code, currency_code,
                    reported_exchange_rate, reported_total_sale, reported_total_net_sale,
                    reported_total_document, ruleset_revision_status, direction,
                    direction_computed_at
                ) values (%s,'invoice',%s,%s,timestamp '2026-08-01 05:24:09', timestamptz '2026-08-01T11:24:09+00:00', -360,'x','620100','01','CRC',
                          1,100,100,113,'detected','issued',now())
                """,
                (user_a.company_id, clave, _consecutive(30)),
            )

    if valido:
        _do()
    else:
        with pytest.raises(psycopg.errors.CheckViolation) as exc:
            _do()
        assert exc.value.sqlstate == "23514"


@pytest.mark.parametrize("cons, valido", [("7" * 20, True), ("7" * 19, False),
                                          ("7" * 21, False), ("7" * 19 + "x", False)])
def test_forma_del_consecutivo(pool, settings, user_a, cons, valido, clean_fiscal):
    def _do():
        with fiscal_transaction(pool, settings, user_a.identity) as conn:
            conn.execute(
                """
                insert into fiscal.electronic_documents (
                    company_id, document_type, clave, consecutive_number,
                    issued_at_local, issued_at, issued_at_offset_minutes, issued_at_raw,
                    issuer_activity_code, sale_condition_code, currency_code,
                    reported_exchange_rate, reported_total_sale, reported_total_net_sale,
                    reported_total_document, ruleset_revision_status, direction,
                    direction_computed_at
                ) values (%s,'invoice',%s,%s,timestamp '2026-08-01 05:24:09', timestamptz '2026-08-01T11:24:09+00:00', -360,'x','620100','01','CRC',
                          1,100,100,113,'detected','issued',now())
                """,
                (user_a.company_id, _clave(31), cons),
            )

    if valido:
        _do()
    else:
        with pytest.raises(psycopg.errors.CheckViolation) as exc:
            _do()
        assert exc.value.sqlstate == "23514"


@pytest.mark.parametrize("offset, valido", [(-840, True), (840, True), (0, True),
                                            (-841, False), (841, False), (-1440, False)])
def test_rango_del_desplazamiento_horario(pool, settings, user_a, offset, valido, clean_fiscal):
    # Clave distinta por parametrización: las tres válidas insertan de verdad y
    # colisionarían entre sí con `UNIQUE (company_id, clave)`.
    seed = 320 + (offset % 100)
    """XML Schema limita xs:dateTime a -14:00..+14:00 (ADR-034)."""
    def _do():
        with fiscal_transaction(pool, settings, user_a.identity) as conn:
            conn.execute(
                """
                insert into fiscal.electronic_documents (
                    company_id, document_type, clave, consecutive_number,
                    issued_at_local, issued_at, issued_at_offset_minutes, issued_at_raw,
                    issuer_activity_code, sale_condition_code, currency_code,
                    reported_exchange_rate, reported_total_sale, reported_total_net_sale,
                    reported_total_document, ruleset_revision_status, direction,
                    direction_computed_at
                ) values (
                    %s,'invoice',%s,%s,
                    timestamp '2026-08-01 05:24:09',
                    -- El instante se deriva del desplazamiento PROBADO: la
                    -- restriccion de coherencia exige que ambas
                    -- representaciones concuerden, incluso en los casos que
                    -- el rango debe rechazar.
                    (timestamp '2026-08-01 05:24:09'
                     - make_interval(mins => %s)) at time zone 'UTC',
                    %s,'x','620100','01','CRC',
                    1,100,100,113,'detected','issued',now())
                """,
                (user_a.company_id, _clave(seed), _consecutive(seed),
                 offset, offset),
            )

    if valido:
        _do()
    else:
        with pytest.raises(psycopg.errors.CheckViolation) as exc:
            _do()
        assert exc.value.sqlstate == "23514"


def test_ausente_no_es_cero(pool, settings, admin_sql, user_a, clean_fiscal):
    """Tres estados distinguibles: ausente ≠ presente 0 ≠ presente > 0."""
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        ausente = _insert_document(conn, user_a.company_id, seed=40, marker="ausente")
        conn.execute(
            """
            insert into fiscal.electronic_documents (
                company_id, document_type, clave, consecutive_number,
                issued_at_local, issued_at, issued_at_offset_minutes, issued_at_raw,
                issuer_activity_code, sale_condition_code, currency_code,
                reported_exchange_rate, reported_total_sale, reported_total_net_sale,
                reported_total_document, reported_total_tax,
                ruleset_revision_status, direction, direction_computed_at
            ) values (%s,'invoice',%s,%s,timestamp '2026-08-01 05:24:09', timestamptz '2026-08-01T11:24:09+00:00', -360,'x','620100','01','CRC',
                      1,100,100,113,0,'detected','issued',now())
            """,
            (user_a.company_id, _clave(41), _consecutive(41)),
        )
        rows = conn.execute(
            "select clave, reported_total_tax from fiscal.electronic_documents "
            "where clave = any(%s)", ([_clave(40), _clave(41)],)
        ).fetchall()

    por_clave = {r["clave"]: r["reported_total_tax"] for r in rows}
    assert por_clave[_clave(40)] is None, "El total ausente se convirtió en cero"
    assert por_clave[_clave(41)] == 0, "El cero explícito debe conservarse"


def test_importes_negativos_rechazados(pool, settings, user_a, clean_fiscal):
    with pytest.raises(psycopg.errors.CheckViolation) as exc:
        with fiscal_transaction(pool, settings, user_a.identity) as conn:
            conn.execute(
                """
                insert into fiscal.electronic_documents (
                    company_id, document_type, clave, consecutive_number,
                    issued_at_local, issued_at, issued_at_offset_minutes, issued_at_raw,
                    issuer_activity_code, sale_condition_code, currency_code,
                    reported_exchange_rate, reported_total_sale, reported_total_net_sale,
                    reported_total_document, ruleset_revision_status, direction,
                    direction_computed_at
                ) values (%s,'credit_note',%s,%s,timestamp '2026-08-01 05:24:09', timestamptz '2026-08-01T11:24:09+00:00', -360,'x','620100','01','CRC',
                          1,100,100,-113,'detected','issued',now())
                """,
                (user_a.company_id, _clave(42), _consecutive(42)),
            )
    assert exc.value.sqlstate == "23514"


def test_maximo_un_emisor_y_un_receptor(pool, settings, user_a, clean_fiscal):
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        doc = _insert_document(conn, user_a.company_id, seed=43, marker="partes")
        for role in ("issuer", "receiver"):
            conn.execute(
                "insert into fiscal.document_parties "
                "(company_id, electronic_document_id, role, legal_name, "
                " identification_type_code, identification_number) "
                "values (%s,%s,%s,'Nombre','01','3101123456')",
                (user_a.company_id, doc, role),
            )

    with pytest.raises(psycopg.errors.UniqueViolation) as exc:
        with fiscal_transaction(pool, settings, user_a.identity) as conn:
            conn.execute(
                "insert into fiscal.document_parties "
                "(company_id, electronic_document_id, role, legal_name, "
                " identification_type_code, identification_number) "
                "values (%s,%s,'issuer','Otro','01','3101999999')",
                (user_a.company_id, doc),
            )
    assert exc.value.sqlstate == "23505"


def test_clave_unica_por_empresa_pero_no_global(pool, settings, user_a, user_b, clean_fiscal):
    """Dos empresas pueden tener el MISMO comprobante oficial (ADR-035)."""
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        _insert_document(conn, user_a.company_id, seed=50, marker="A")

    # La misma clave en otra empresa: permitido.
    with fiscal_transaction(pool, settings, user_b.identity) as conn:
        conn.execute(
            """
            insert into fiscal.electronic_documents (
                company_id, document_type, clave, consecutive_number,
                issued_at_local, issued_at, issued_at_offset_minutes, issued_at_raw,
                issuer_activity_code, sale_condition_code, currency_code,
                reported_exchange_rate, reported_total_sale, reported_total_net_sale,
                reported_total_document, ruleset_revision_status, direction,
                direction_computed_at
            ) values (%s,'invoice',%s,%s,timestamp '2026-08-01 05:24:09', timestamptz '2026-08-01T11:24:09+00:00', -360,'B','620100','01','CRC',
                      1,100,100,113,'detected','received',now())
            """,
            (user_b.company_id, _clave(50), _consecutive(51)),
        )

    # La misma clave DOS VECES en la misma empresa: rechazado, sin fusión silenciosa.
    with pytest.raises(psycopg.errors.UniqueViolation) as exc:
        with fiscal_transaction(pool, settings, user_a.identity) as conn:
            conn.execute(
                """
                insert into fiscal.electronic_documents (
                    company_id, document_type, clave, consecutive_number,
                    issued_at_local, issued_at, issued_at_offset_minutes, issued_at_raw,
                    issuer_activity_code, sale_condition_code, currency_code,
                    reported_exchange_rate, reported_total_sale, reported_total_net_sale,
                    reported_total_document, ruleset_revision_status, direction,
                    direction_computed_at
                ) values (%s,'invoice',%s,%s,timestamp '2026-08-01 05:24:09', timestamptz '2026-08-01T11:24:09+00:00', -360,'dup','620100','01','CRC',
                          1,999,999,999,'detected','issued',now())
                """,
                (user_a.company_id, _clave(50), _consecutive(52)),
            )
    assert exc.value.sqlstate == "23505"


# ─────────────────────────────────────────────────────────────────────────────
# 7. Enlaces opcionales y comportamiento de SET NULL
# ─────────────────────────────────────────────────────────────────────────────


def test_artefacto_sin_documento_normalizado(pool, settings, user_a, clean_fiscal):
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        assert _insert_source(conn, user_a.company_id, edoc_id=None)


def test_varios_artefactos_para_un_mismo_documento(pool, settings, user_a, clean_fiscal):
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        doc = _insert_document(conn, user_a.company_id, seed=60, marker="uno")
        _insert_source(conn, user_a.company_id, edoc_id=doc)
        _insert_source(conn, user_a.company_id, edoc_id=doc)
        n = conn.execute(
            "select count(*) as n from fiscal.source_documents where electronic_document_id = %s",
            (doc,),
        ).fetchone()["n"]
    assert n == 2, "Un documento debe poder proceder de varios artefactos"


def test_enlace_a_documento_de_otra_empresa_rechazado(pool, settings, user_a, user_b, clean_fiscal):
    with fiscal_transaction(pool, settings, user_b.identity) as conn:
        edoc_b = _insert_document(conn, user_b.company_id, seed=61, marker="B")

    with pytest.raises(psycopg.errors.ForeignKeyViolation) as exc:
        with fiscal_transaction(pool, settings, user_a.identity) as conn:
            _insert_source(conn, user_a.company_id, edoc_id=edoc_b)
    assert exc.value.sqlstate == "23503"


def test_referencia_resuelta_no_cruza_empresas(pool, settings, user_a, user_b, clean_fiscal):
    with fiscal_transaction(pool, settings, user_b.identity) as conn:
        edoc_b = _insert_document(conn, user_b.company_id, seed=62, marker="B")

    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        doc_a = _insert_document(conn, user_a.company_id, seed=63, marker="A")
        # Sin resolver: permitido.
        conn.execute(
            "insert into fiscal.document_references "
            "(company_id, electronic_document_id, sequence, referenced_document_type_code, "
            " reported_reference_date_local, reported_reference_date, reported_reference_offset_minutes, reported_reference_date_raw) "
            "values (%s,%s,1,'01',timestamp '2026-08-01 05:24:09', timestamptz '2026-08-01T11:24:09+00:00', -360,'x')",
            (user_a.company_id, doc_a),
        )

    with pytest.raises(psycopg.errors.ForeignKeyViolation) as exc:
        with fiscal_transaction(pool, settings, user_a.identity) as conn:
            conn.execute(
                "insert into fiscal.document_references "
                "(company_id, electronic_document_id, sequence, referenced_document_type_code, "
                " reported_reference_date_local, reported_reference_date, "
                " reported_reference_offset_minutes, "
                " reported_reference_date_raw, resolved_document_id) "
                "values (%s,%s,2,'01',timestamp '2026-08-01 05:24:09', timestamptz '2026-08-01T11:24:09+00:00', -360,'x',%s)",
                (user_a.company_id, doc_a, edoc_b),
            )
    assert exc.value.sqlstate == "23503"


def test_set_null_solo_anula_la_columna_opcional(pool, settings, admin_sql, user_a, clean_fiscal):
    """Borrado por vía privilegiada: fiscal_backend no recibe DELETE para esto."""
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        doc = _insert_document(conn, user_a.company_id, seed=70, marker="borrable")
        src = _insert_source(conn, user_a.company_id, edoc_id=doc)

    admin_sql(f"delete from fiscal.electronic_documents where id = '{doc}'")

    row = admin_sql(
        f"""
        select (electronic_document_id is null) as enlace_anulado,
               company_id::text                 as company_id,
               octet_length(raw_xml)            as bytes,
               (content_sha256 is not null)     as huella
        from fiscal.source_documents where id = '{src}'
        """
    )[0]
    assert row["enlace_anulado"] is True, "El enlace debía anularse"
    assert row["company_id"] == user_a.company_id, "company_id NO debe cambiar"
    assert row["bytes"] == len(XML), "raw_xml debe sobrevivir intacto"
    assert row["huella"] is True


# ─────────────────────────────────────────────────────────────────────────────
# 8. Limpieza de identidad en la sesión reutilizada
# ─────────────────────────────────────────────────────────────────────────────


def test_la_identidad_no_se_filtra_entre_usuarios_en_la_misma_sesion(
    single_connection_pool, settings, user_a, user_b, clean_fiscal
):
    """Mismo patrón probado en los Checkpoints B y D, ahora sobre tablas reales."""
    pool = single_connection_pool
    marker = "e3-identidad"

    with pool.connection() as conn:
        conn.execute("select set_config('app.e3_probe', %s, false)", (marker,))

    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        _insert_document(conn, user_a.company_id, seed=80, marker="A")

    with fiscal_transaction(pool, settings, user_b.identity) as conn:
        probe = conn.execute(
            "select nullif(current_setting('app.e3_probe', true), '') as p"
        ).fetchone()["p"]
        assert probe == marker, "La sesión no se reutilizó; prueba no concluyente"
        visto = {r["c"] for r in conn.execute(
            "select company_id::text as c from fiscal.electronic_documents where clave = %s",
            (_clave(80),)).fetchall()}
    assert visto == set(), f"B vio el documento de A: {visto}"

    with pool.connection() as conn:
        estado = conn.execute(
            "select current_user::text as rol, "
            "nullif(current_setting('request.jwt.claims', true), '') as claims"
        ).fetchone()
    assert estado["rol"] == "app_backend", "El rol fiscal sobrevivió a la transacción"
    assert estado["claims"] is None, "La identidad sobrevivió a la transacción"


# ─────────────────────────────────────────────────────────────────────────────
# 9. Frontera de la Data API
# ─────────────────────────────────────────────────────────────────────────────


def test_la_data_api_sigue_sin_exponer_el_schema_fiscal(settings, publishable_key, user_a):
    """Regresión permanente: crear tablas no debe haber abierto la puerta."""
    response = httpx.get(
        f"{settings.supabase_url}/rest/v1/electronic_documents",
        headers={
            "apikey": publishable_key,
            "Authorization": f"Bearer {user_a.token}",
            "Accept-Profile": "fiscal",
        },
        params={"select": "*"},
        timeout=90,
    )
    assert response.status_code != 200, (
        f"La Data API expone el schema fiscal: {response.text[:200]}"
    )
    assert response.json().get("code") == "PGRST106", (
        f"Se esperaba PGRST106. Recibido {response.status_code}: {response.text[:200]}"
    )
