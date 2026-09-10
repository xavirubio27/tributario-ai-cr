"""Persistencia fiscal transaccional (C1-B) — contra PostgreSQL real.

Estos tests ejercitan la función de PRODUCCIÓN `persist_parsed_fiscal_document`
sobre el proyecto DEV, con RLS activa y sin `service_role`. La autorización la
decide PostgreSQL; aquí solo se comprueba qué decide.

Cada test es dueño de sus filas y las limpia por UUID exacto de empresa. Nunca
un `DELETE` sin predicado: `fiscal_backend` no tiene `DELETE`, así que la
limpieza pasa por la vía administrativa, igual que en `test_fiscal_schema`.
"""

from __future__ import annotations

import hashlib
import threading
import time
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest
from lxml import etree

from app.db import fiscal_transaction
from app.fiscal.errors import (
    ClaveConflict,
    FiscalPersistenceError,
    FiscalWriteForbidden,
    PersistenceMappingError,
    SourceDocumentNotFound,
    SourceDocumentStateConflict,
)
from app.fiscal.parser import parse_fiscal_document
from app.fiscal.persistence import (
    PersistenceResult,
    PersistenceStatus,
    persist_parsed_fiscal_document,
)

FIXTURES = Path(__file__).parent / "fixtures" / "fiscal" / "real" / "v4_4"

#: Prefijos de los comprobantes representativos, y lo que B2 dejó revisado.
FE_7_LINEAS = "50601082600310161019803900001010004596121100"
TE_1_LINEA = "Comprobante_Electronico_50630062600310174582"
NC_CON_REFERENCIA = "NC-50631082600310181576400100001030000001522"

#: Expectativas ESTÁTICAS, tomadas de la matriz revisada en B2. No se derivan
#: del propio parser ni de la persistencia dentro de la aserción.
ESPERADO = {
    FE_7_LINEAS:      {"tipo": "invoice",     "lineas": 7, "desc": 1, "imp": 7, "refs": 0},
    TE_1_LINEA:       {"tipo": "ticket",      "lineas": 1, "desc": 0, "imp": 1, "refs": 0},
    NC_CON_REFERENCIA:{"tipo": "credit_note", "lineas": 1, "desc": 0, "imp": 1, "refs": 1},
}


# ─────────────────────────────────────────────────────────────────────────────
# Utilidades
# ─────────────────────────────────────────────────────────────────────────────

def _fixture(prefijo: str) -> Path:
    candidatos = [
        p for sub in ("fe", "te", "nc")
        for p in (FIXTURES / sub).glob("*.xml")
        if p.name.startswith(prefijo)
    ]
    assert len(candidatos) == 1, f"{prefijo!r} identifica {len(candidatos)} comprobantes"
    return candidatos[0]


def _bytes(prefijo: str) -> bytes:
    return _fixture(prefijo).read_bytes()


def _crear_source(conn, company_id: str, crudo: bytes) -> str:
    """Alta del artefacto. En producción esto es de la ingesta (C2), no de C1;
    aquí es preparación de test."""
    fila = conn.execute(
        "insert into fiscal.source_documents "
        "(company_id, raw_xml, content_sha256, ingestion_source) "
        "values (%s, %s, %s, 'api') returning id",
        (company_id, crudo, hashlib.sha256(crudo).digest()),
    ).fetchone()
    return str(fila["id"])


def _contar(conn, company_id: str) -> dict[str, int]:
    """Recuento por empresa, leído de la base — no del objeto parseado."""
    fila = conn.execute(
        """
        select
          (select count(*) from fiscal.electronic_documents where company_id=%(c)s) as edoc,
          (select count(*) from fiscal.document_parties     where company_id=%(c)s) as partes,
          (select count(*) from fiscal.document_lines       where company_id=%(c)s) as lineas,
          (select count(*) from fiscal.line_discounts       where company_id=%(c)s) as desc_,
          (select count(*) from fiscal.line_taxes           where company_id=%(c)s) as imp,
          (select count(*) from fiscal.document_references  where company_id=%(c)s) as refs,
          (select count(*) from fiscal.source_documents     where company_id=%(c)s) as fuentes
        """,
        {"c": company_id},
    ).fetchone()
    return dict(fila)


VACIO = {"edoc": 0, "partes": 0, "lineas": 0, "desc_": 0, "imp": 0, "refs": 0}


def _sin_filas_normalizadas(conteo: dict) -> bool:
    return all(conteo[k] == 0 for k in VACIO)


@pytest.fixture
def as_role(admin_sql, user_a):
    """Cambia el rol de A en su empresa y lo restaura. Mismo patrón que
    `test_fiscal_schema`: los roles viven en `public.company_memberships`."""
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


#: Fallos de TRANSPORTE de la CLI de Supabase — no de SQL. Se han observado
#: `401 Unauthorized` intermitentes al inicializar el rol de login cuando la
#: suite invoca la CLI muchas veces seguidas. Reintentar SOLO estos es
#: resiliencia frente a una herramienta externa; un error de SQL nunca se
#: reintenta, porque eso sí escondería un defecto del producto.
_TRANSITORIOS_CLI = (
    "unexpected status 401",
    "unexpected login role status 401",
    "LegacyDbConfigConnectTempRoleError",
    "unexpected status 5",
)


def _admin_sql_resiliente(admin_sql, sql: str, intentos: int = 3):
    ultimo = None
    for intento in range(intentos):
        try:
            return admin_sql(sql)
        except Exception as exc:            # noqa: BLE001 - se filtra abajo
            texto = str(exc)
            if not any(t in texto for t in _TRANSITORIOS_CLI):
                raise                        # error de SQL: se propaga tal cual
            ultimo = texto
            time.sleep(1 + intento)
    raise AssertionError(
        f"la CLI de Supabase falló {intentos} veces por transporte: {ultimo[:200]}"
    )


@pytest.fixture(scope="module", autouse=True)
def _limpieza_inicial(admin_sql, user_a, user_b):
    """Una sola limpieza al abrir el módulo. A partir de ahí cada test deja el
    terreno limpio para el siguiente, así que no hace falta limpiar dos veces
    por test: son invocaciones de la CLI, que es el coste dominante aquí."""
    _admin_sql_resiliente(admin_sql, _borrado_de(user_a, user_b))
    yield


def _borrado_de(user_a, user_b) -> str:
    ambas = f"('{user_a.company_id}','{user_b.company_id}')"
    # `source_documents` primero, porque su FK apunta al documento.
    return (
        f"with s as (delete from fiscal.source_documents "
        f"           where company_id in {ambas} returning 1) "
        f"delete from fiscal.electronic_documents where company_id in {ambas}"
    )


@pytest.fixture
def limpio(admin_sql, user_a, user_b):
    """Retira SOLO las filas de las dos empresas de esta ejecución, al terminar.

    Limpiar *después* y no antes es deliberado: cada test hereda el terreno que
    dejó el anterior, y `_limpieza_inicial` garantiza el estado del primero. Si
    un test falla a mitad, su `finally` limpia igual.
    """
    try:
        yield
    finally:
        _admin_sql_resiliente(admin_sql, _borrado_de(user_a, user_b))


def _persistir(pool, settings, user, company_id, source_id, parsed):
    """Una transacción fiscal autenticada completa, como en producción."""
    with fiscal_transaction(pool, settings, user.identity) as conn:
        return persist_parsed_fiscal_document(
            conn,
            company_id=company_id,
            source_document_id=source_id,
            parsed=parsed,
        )


# ═════════════════════════════════════════════════════════════════════════════
# 1 · Puerta de autorización en dos lecturas (C1-B-R1)
#
# Medido contra PostgreSQL 17.6: `SELECT ... FOR UPDATE` aplica, además de la
# política SELECT, la cláusula USING de la política UPDATE, y **filtra en
# silencio** lo que no la pasa —sin excepción y sin SQLSTATE—. Por eso el
# `viewer` y el no-miembro devolvían ambos cero filas y eran indistinguibles.
#
# La puerta aprobada observa DOS capacidades que RLS ya decide:
#   paso A · SELECT simple      → visibilidad
#   paso B · SELECT FOR UPDATE  → intención de escritura, y bloqueo
#
# Ninguna de las dos consulta `company_memberships`.
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("rol", ["owner", "editor"])
def test_owner_y_editor_pueden_persistir(pool, settings, user_a, as_role, rol, limpio):
    as_role(rol)
    crudo = _bytes(FE_7_LINEAS)
    parsed = parse_fiscal_document(crudo)

    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        source_id = _crear_source(conn, user_a.company_id, crudo)

    resultado = _persistir(pool, settings, user_a, user_a.company_id, source_id, parsed)

    assert isinstance(resultado, PersistenceResult)
    assert resultado.status is PersistenceStatus.CREATED
    assert resultado.source_document_id == source_id


def test_viewer_recibe_denegacion_de_escritura(pool, settings, user_a, as_role, limpio):
    """El caso que motivó la refinación: el `viewer` VE el artefacto pero no
    puede bloquearlo para escribir."""
    crudo = _bytes(FE_7_LINEAS)
    parsed = parse_fiscal_document(crudo)

    as_role("owner")
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        source_id = _crear_source(conn, user_a.company_id, crudo)

    as_role("viewer")
    with pytest.raises(FiscalWriteForbidden) as exc:
        _persistir(pool, settings, user_a, user_a.company_id, source_id, parsed)
    assert exc.value.code == "fiscal_write_forbidden"

    # Y no escribió nada.
    as_role("owner")
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        conteo = _contar(conn, user_a.company_id)
    assert _sin_filas_normalizadas(conteo)
    assert conteo["fuentes"] == 1


def test_un_no_miembro_no_puede_enumerar(pool, settings, user_a, user_b, limpio):
    """`user_b` no es miembro de la empresa de A: para él el artefacto no
    existe. No se revela que sí exista."""
    crudo = _bytes(FE_7_LINEAS)
    parsed = parse_fiscal_document(crudo)

    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        source_id = _crear_source(conn, user_a.company_id, crudo)

    with pytest.raises(SourceDocumentNotFound) as exc:
        _persistir(pool, settings, user_b, user_a.company_id, source_id, parsed)
    assert exc.value.code == "source_document_not_found"


def test_una_empresa_no_puede_usar_el_artefacto_de_otra(
    pool, settings, user_a, user_b, limpio
):
    """B tiene su propio artefacto; A no puede persistirlo bajo su empresa."""
    crudo = _bytes(FE_7_LINEAS)
    parsed = parse_fiscal_document(crudo)

    with fiscal_transaction(pool, settings, user_b.identity) as conn:
        source_de_b = _crear_source(conn, user_b.company_id, crudo)

    # A, con su propio company_id, apuntando al artefacto de B.
    with pytest.raises(SourceDocumentNotFound):
        _persistir(pool, settings, user_a, user_a.company_id, source_de_b, parsed)

    # Y tampoco declarando la empresa de B: RLS no le da visibilidad.
    with pytest.raises(SourceDocumentNotFound):
        _persistir(pool, settings, user_a, user_b.company_id, source_de_b, parsed)


def test_un_artefacto_inexistente_no_se_distingue_de_uno_ajeno(
    pool, settings, user_a, limpio
):
    import uuid
    parsed = parse_fiscal_document(_bytes(FE_7_LINEAS))
    with pytest.raises(SourceDocumentNotFound) as exc:
        _persistir(
            pool, settings, user_a, user_a.company_id, str(uuid.uuid4()), parsed
        )
    # El mensaje no dice cuál de los tres casos fue.
    publico = str(exc.value).lower()
    for revelador in ("miembro", "empresa ajena", "otro tenant", "permiso"):
        assert revelador not in publico


def test_el_viewer_es_rechazado_incluso_si_ya_estaba_persistido(
    pool, settings, user_a, as_role, limpio
):
    """Regresión obligatoria: la puerta de escritura va ANTES de la
    idempotencia. Un `viewer` no puede recibir `already_persisted`, aunque ese
    reintento concreto no fuera a mutar nada — C1 es un caso de uso de
    escritura, y la autorización no depende de la suerte del camino."""
    crudo = _bytes(FE_7_LINEAS)
    parsed = parse_fiscal_document(crudo)

    as_role("owner")
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        source_id = _crear_source(conn, user_a.company_id, crudo)
    primero = _persistir(pool, settings, user_a, user_a.company_id, source_id, parsed)
    assert primero.status is PersistenceStatus.CREATED

    as_role("viewer")
    with pytest.raises(FiscalWriteForbidden):
        _persistir(pool, settings, user_a, user_a.company_id, source_id, parsed)


def _sql_del_modulo(modulo) -> list[str]:
    """Todas las sentencias SQL del módulo, extraídas del AST.

    Se mira el SQL y no el fichero entero a propósito: los comentarios y las
    docstrings mencionan `company_memberships` justamente para explicar que NO
    se consulta, y una comprobación sobre el texto plano fallaría por eso.
    """
    import ast

    arbol = ast.parse(Path(modulo.__file__).read_text(encoding="utf-8"))
    docstrings = {
        n.body[0].value
        for n in ast.walk(arbol)
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef))
        and n.body and isinstance(n.body[0], ast.Expr)
        and isinstance(n.body[0].value, ast.Constant)
        and isinstance(n.body[0].value.value, str)
    }
    return [
        n.value for n in ast.walk(arbol)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
        and n not in docstrings
        and any(v in n.value.lower() for v in ("select ", "insert ", "update ", "delete "))
    ]


def test_la_persistencia_no_consulta_company_memberships():
    """La autorización sigue siendo de RLS. Si este módulo consultara
    pertenencias, estaría reimplementando en Python lo que PostgreSQL decide."""
    from app.fiscal import persistence

    sentencias = _sql_del_modulo(persistence)
    assert sentencias, "no se encontró SQL: la extracción por AST falló"
    for sql in sentencias:
        bajo = sql.lower()
        for prohibido in ("company_memberships", "is_company_member",
                          "can_write_company", "service_role", "auth."):
            assert prohibido not in bajo, f"la persistencia consulta {prohibido}"

    # Y las tablas que sí toca son exactamente las fiscales esperadas.
    tocadas = {
        t for sql in sentencias for t in
        ("source_documents", "electronic_documents", "document_parties",
         "document_lines", "line_discounts", "line_taxes", "document_references")
        if t in sql
    }
    assert tocadas == {
        "source_documents", "electronic_documents", "document_parties",
        "document_lines", "line_discounts", "line_taxes", "document_references",
    }


# ═════════════════════════════════════════════════════════════════════════════
# 2 · Camino CREATED con comprobantes reales
# ═════════════════════════════════════════════════════════════════════════════

def _persistir_fixture(pool, settings, user, prefijo):
    crudo = _bytes(prefijo)
    parsed = parse_fiscal_document(crudo)
    with fiscal_transaction(pool, settings, user.identity) as conn:
        source_id = _crear_source(conn, user.company_id, crudo)
    resultado = _persistir(
        pool, settings, user, user.company_id, source_id, parsed
    )
    return source_id, parsed, resultado


@pytest.mark.parametrize("prefijo", list(ESPERADO), ids=lambda p: p[:24])
def test_los_comprobantes_reales_persisten_completos(
    pool, settings, user_a, prefijo, limpio
):
    """Contra la matriz ESTÁTICA revisada en B2, no contra el objeto parseado."""
    esperado = ESPERADO[prefijo]
    source_id, _parsed, resultado = _persistir_fixture(
        pool, settings, user_a, prefijo
    )
    assert resultado.status is PersistenceStatus.CREATED

    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        conteo = _contar(conn, user_a.company_id)
        doc = conn.execute(
            "select id, document_type, clave, direction, ruleset_revision, "
            "       ruleset_revision_status, direction_computed_at "
            "from fiscal.electronic_documents where company_id=%s",
            (user_a.company_id,),
        ).fetchone()
        enlace = conn.execute(
            "select electronic_document_id, parse_status "
            "from fiscal.source_documents where id=%s",
            (source_id,),
        ).fetchone()

    assert conteo["edoc"] == 1
    assert conteo["lineas"] == esperado["lineas"]
    assert conteo["desc_"] == esperado["desc"]
    assert conteo["imp"] == esperado["imp"]
    assert conteo["refs"] == esperado["refs"]
    assert doc["document_type"] == esperado["tipo"]
    assert str(enlace["electronic_document_id"]) == str(doc["id"])


def test_valores_exactos_de_la_factura_de_siete_lineas(
    pool, settings, user_a, limpio
):
    """Valores concretos, contrastados con los literales que B2 dejó revisados."""
    _source_id, _parsed, resultado = _persistir_fixture(
        pool, settings, user_a, FE_7_LINEAS
    )
    assert resultado.status is PersistenceStatus.CREATED

    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        doc = conn.execute(
            "select * from fiscal.electronic_documents where company_id=%s",
            (user_a.company_id,),
        ).fetchone()
        partes = conn.execute(
            "select role, legal_name, identification_type_code, identification_number "
            "from fiscal.document_parties where electronic_document_id=%s "
            "order by role",
            (doc["id"],),
        ).fetchall()
        linea6 = conn.execute(
            "select * from fiscal.document_lines "
            "where electronic_document_id=%s and line_number=6",
            (doc["id"],),
        ).fetchone()
        descuento = conn.execute(
            "select sequence, reported_amount, discount_code "
            "from fiscal.line_discounts where document_line_id=%s",
            (linea6["id"],),
        ).fetchone()
        impuesto = conn.execute(
            "select sequence, tax_code, vat_rate_code, reported_rate, reported_amount "
            "from fiscal.line_taxes where document_line_id=%s",
            (linea6["id"],),
        ).fetchone()

    assert doc["document_type"] == "invoice"
    assert doc["clave"] == FE_7_LINEAS + "000000"[: 50 - len(FE_7_LINEAS)]
    assert doc["currency_code"] == "CRC"
    assert doc["issuer_activity_code"] == "6110.0"     # seis CARACTERES, no dígitos
    assert len(partes) == 2 and {p["role"] for p in partes} == {"issuer", "receiver"}

    # Línea 6 — la única del corpus con descuento.
    assert linea6["cabys_code"] == "8422200000000"
    assert linea6["description"] == "500MBPS/500MBPS_FTTH_LY_2025_FMC"
    assert linea6["unit_of_measure_code"] == "Os"
    assert linea6["reported_unit_price"] == Decimal("58210.99")
    assert linea6["reported_subtotal"] == Decimal("19110.90")
    assert linea6["reported_taxable_base"] == Decimal("19110.90")
    assert linea6["reported_net_tax"] == Decimal("2484.42")
    assert linea6["reported_line_total"] == Decimal("21595.32")

    assert (descuento["sequence"], descuento["discount_code"]) == (1, "07")
    assert descuento["reported_amount"] == Decimal("39100.09")
    assert (impuesto["sequence"], impuesto["tax_code"]) == (1, "01")
    assert impuesto["vat_rate_code"] == "08"
    assert impuesto["reported_rate"] == Decimal("13")
    assert impuesto["reported_amount"] == Decimal("2484.42")


def test_el_tiquete_persiste_como_ticket(pool, settings, user_a, limpio):
    _source_id, _parsed, resultado = _persistir_fixture(
        pool, settings, user_a, TE_1_LINEA
    )
    assert resultado.status is PersistenceStatus.CREATED
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        doc = conn.execute(
            "select document_type from fiscal.electronic_documents where company_id=%s",
            (user_a.company_id,),
        ).fetchone()
        conteo = _contar(conn, user_a.company_id)
    assert doc["document_type"] == "ticket"
    assert (conteo["lineas"], conteo["imp"], conteo["refs"]) == (1, 1, 0)


def test_la_nota_de_credito_persiste_con_referencia_colgante(
    pool, settings, user_a, limpio
):
    """La NC real apunta a una FE que **no está en el corpus**. Debe persistir:
    C1 no resuelve referencias y no exige que el referido exista (ADR-028)."""
    _source_id, _parsed, resultado = _persistir_fixture(
        pool, settings, user_a, NC_CON_REFERENCIA
    )
    assert resultado.status is PersistenceStatus.CREATED

    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        ref = conn.execute(
            "select r.* from fiscal.document_references r "
            "join fiscal.electronic_documents e on e.id = r.electronic_document_id "
            "where e.company_id = %s",
            (user_a.company_id,),
        ).fetchone()
        edocs = conn.execute(
            "select count(*) as n from fiscal.electronic_documents where company_id=%s",
            (user_a.company_id,),
        ).fetchone()

    assert ref["sequence"] == 1
    assert ref["referenced_document_type_code"] == "01"
    assert ref["reported_number"] == (
        "50630082600310181576400100001010000022472103888064"
    )
    assert ref["reference_code"] == "01"
    assert ref["reason"] == "Factura erronea"
    assert ref["resolved_document_id"] is None, "C1 no resuelve referencias"
    # El documento referido no existe, y aun así hay exactamente uno guardado.
    assert edocs["n"] == 1


# ═════════════════════════════════════════════════════════════════════════════
# 3 · Fidelidad de la fuente
# ═════════════════════════════════════════════════════════════════════════════

def test_fecha_con_desplazamiento_conserva_las_cuatro_representaciones(
    pool, settings, user_a, limpio
):
    _s, parsed, _r = _persistir_fixture(pool, settings, user_a, FE_7_LINEAS)
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        doc = conn.execute(
            "select issued_at_local, issued_at, issued_at_offset_minutes, issued_at_raw "
            "from fiscal.electronic_documents where company_id=%s",
            (user_a.company_id,),
        ).fetchone()

    fecha = parsed.document.fecha
    assert doc["issued_at_raw"] == fecha.raw
    assert doc["issued_at_local"] == fecha.local
    assert doc["issued_at_local"].tzinfo is None, (
        "el reloj de pared se guardó con huso: psycopg lo adaptó a timestamptz"
    )
    assert doc["issued_at"] == fecha.instante
    assert doc["issued_at_offset_minutes"] == fecha.offset_minutos


def test_fecha_sin_desplazamiento_no_inventa_zona_horaria(
    pool, settings, user_a, limpio
):
    """ADR-039 sobre un comprobante REAL sin desplazamiento. Nunca −06:00."""
    prefijo = "50619062600310111260300100008010000004706367"
    _s, parsed, _r = _persistir_fixture(pool, settings, user_a, prefijo)
    assert parsed.document.fecha.offset_minutos is None, "el fixture cambió"

    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        doc = conn.execute(
            "select issued_at_local, issued_at, issued_at_offset_minutes, issued_at_raw "
            "from fiscal.electronic_documents where company_id=%s",
            (user_a.company_id,),
        ).fetchone()

    assert doc["issued_at_local"] == parsed.document.fecha.local
    assert doc["issued_at_local"].tzinfo is None
    assert doc["issued_at"] is None
    assert doc["issued_at_offset_minutes"] is None
    assert doc["issued_at_raw"] == parsed.document.fecha.raw


def test_direccion_y_ruleset_del_documento_nuevo(pool, settings, user_a, limpio):
    """C1 no determina dirección ni revisión: lo declara, no lo finge."""
    _persistir_fixture(pool, settings, user_a, FE_7_LINEAS)
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        doc = conn.execute(
            "select direction, direction_computed_at, ruleset_revision, "
            "       ruleset_revision_status, "
            "       (direction_computed_at between now() - interval '10 minutes' "
            "        and now() + interval '10 minutes') as marca_razonable "
            "from fiscal.electronic_documents where company_id=%s",
            (user_a.company_id,),
        ).fetchone()

    assert doc["direction"] == "unknown"
    assert doc["direction_computed_at"] is not None
    assert doc["marca_razonable"] is True
    assert doc["ruleset_revision"] is None
    assert doc["ruleset_revision_status"] == "ambiguous"


def test_la_persistencia_no_toca_parse_status(pool, settings, user_a, limpio):
    """Corrección de C1-A2: `parse_status` es de la ingesta, que ejecuta el
    parser. C1 solo escribe el enlace."""
    crudo = _bytes(FE_7_LINEAS)
    parsed = parse_fiscal_document(crudo)
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        source_id = _crear_source(conn, user_a.company_id, crudo)
        antes = conn.execute(
            "select parse_status, parse_attempt_count, schema_detection_status "
            "from fiscal.source_documents where id=%s", (source_id,)
        ).fetchone()
    assert antes["parse_status"] == "pending"

    _persistir(pool, settings, user_a, user_a.company_id, source_id, parsed)

    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        despues = conn.execute(
            "select parse_status, parse_attempt_count, schema_detection_status, "
            "       electronic_document_id "
            "from fiscal.source_documents where id=%s", (source_id,)
        ).fetchone()

    assert despues["parse_status"] == "pending", "C1 no debe tocar parse_status"
    assert despues["parse_attempt_count"] == antes["parse_attempt_count"]
    assert despues["schema_detection_status"] == antes["schema_detection_status"]
    assert despues["electronic_document_id"] is not None


# ═════════════════════════════════════════════════════════════════════════════
# 4 · Estados NULL / vacío, sobre datos derivados del parser
#
# Cobertura de contrato: el corpus real no trae estos estados. Se preparan
# mutando en memoria, y cada mutación se parsea con el parser de producción —
# que ya validó contra el XSD oficial — sin tocar un solo byte versionado.
# ═════════════════════════════════════════════════════════════════════════════

def _nc_con(campo: str, valor: str | None) -> bytes:
    arbol = etree.fromstring(_bytes(NC_CON_REFERENCIA))
    ns = arbol.tag[1:].split("}")[0]
    ref = arbol.find(f".//{{{ns}}}InformacionReferencia")
    nodo = ref.find(f"{{{ns}}}{campo}")
    if valor is None:
        ref.remove(nodo)
    else:
        nodo.text = valor or None
    return etree.tostring(arbol)


@pytest.mark.parametrize(
    ("caso", "numero", "razon", "esp_num", "esp_razon"),
    [
        ("ausentes", None, None, None, None),
        ("vacios", "", "", "", ""),
    ],
    ids=lambda v: v if isinstance(v, str) and v in ("ausentes", "vacios") else "",
)
def test_la_referencia_conserva_nulo_frente_a_vacio(
    caso, numero, razon, esp_num, esp_razon, pool, settings, user_a, limpio
):
    arbol = etree.fromstring(_bytes(NC_CON_REFERENCIA))
    ns = arbol.tag[1:].split("}")[0]
    ref = arbol.find(f".//{{{ns}}}InformacionReferencia")
    for campo, valor in (("Numero", numero), ("Razon", razon)):
        nodo = ref.find(f"{{{ns}}}{campo}")
        if valor is None:
            ref.remove(nodo)
        else:
            nodo.text = valor or None
    crudo = etree.tostring(arbol)

    parsed = parse_fiscal_document(crudo)           # pasa el XSD oficial
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        source_id = _crear_source(conn, user_a.company_id, crudo)
    _persistir(pool, settings, user_a, user_a.company_id, source_id, parsed)

    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        fila = conn.execute(
            "select r.reported_number, r.reason, "
            "       (r.reported_number is null) as num_nulo, "
            "       (r.reason is null) as razon_nula "
            "from fiscal.document_references r "
            "join fiscal.electronic_documents e on e.id=r.electronic_document_id "
            "where e.company_id=%s",
            (user_a.company_id,),
        ).fetchone()

    assert fila["reported_number"] == esp_num
    assert fila["reason"] == esp_razon
    assert fila["num_nulo"] is (esp_num is None)
    assert fila["razon_nula"] is (esp_razon is None)


def test_la_identificacion_conserva_vacio_y_ausencia(pool, settings, user_a, limpio):
    """`Numero=""` es un estado legal del XSD (sin `minLength`) y se guarda como
    cadena vacía, distinta de la ausencia del nodo."""
    arbol = etree.fromstring(_bytes(FE_7_LINEAS))
    ns = arbol.tag[1:].split("}")[0]
    arbol.find(
        f".//{{{ns}}}Emisor/{{{ns}}}Identificacion/{{{ns}}}Numero"
    ).text = None
    crudo = etree.tostring(arbol)

    parsed = parse_fiscal_document(crudo)
    assert parsed.issuer.identificacion.numero == ""

    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        source_id = _crear_source(conn, user_a.company_id, crudo)
    _persistir(pool, settings, user_a, user_a.company_id, source_id, parsed)

    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        emisor = conn.execute(
            "select p.identification_type_code as tipo, p.identification_number as num, "
            "       (p.identification_number is null) as es_nulo "
            "from fiscal.document_parties p "
            "join fiscal.electronic_documents e on e.id=p.electronic_document_id "
            "where e.company_id=%s and p.role='issuer'",
            (user_a.company_id,),
        ).fetchone()

    assert emisor["tipo"] is not None
    assert emisor["num"] == ""
    assert emisor["es_nulo"] is False, "'' no puede confundirse con ausencia"


def test_el_receptor_sin_identificacion_guarda_ambas_columnas_nulas(
    pool, settings, user_a, limpio
):
    """Estado legal en TE/NC/ND —`Identificacion` es 0..1 para el receptor—.

    Se usa la Nota de Crédito real, que sí trae `Receptor` con
    `Identificacion`: el Tiquete del corpus no trae `Receptor` en absoluto, que
    es un tercer estado distinto (no hay parte, no hay fila).
    """
    arbol = etree.fromstring(_bytes(NC_CON_REFERENCIA))
    ns = arbol.tag[1:].split("}")[0]
    receptor = arbol.find(f".//{{{ns}}}Receptor")
    ident = receptor.find(f"{{{ns}}}Identificacion")
    receptor.remove(ident)
    crudo = etree.tostring(arbol)

    parsed = parse_fiscal_document(crudo)
    assert parsed.receiver.identificacion is None

    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        source_id = _crear_source(conn, user_a.company_id, crudo)
    _persistir(pool, settings, user_a, user_a.company_id, source_id, parsed)

    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        rec = conn.execute(
            "select p.identification_type_code as tipo, p.identification_number as num "
            "from fiscal.document_parties p "
            "join fiscal.electronic_documents e on e.id=p.electronic_document_id "
            "where e.company_id=%s and p.role='receiver'",
            (user_a.company_id,),
        ).fetchone()

    assert rec["tipo"] is None and rec["num"] is None


def test_un_comprobante_sin_receptor_no_crea_la_parte(pool, settings, user_a, limpio):
    """Tercer estado, distinto de los dos anteriores: el Tiquete real no trae
    `Receptor`. No hay parte que guardar — y no se inventa una."""
    crudo = _bytes(TE_1_LINEA)
    parsed = parse_fiscal_document(crudo)
    assert parsed.receiver is None

    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        source_id = _crear_source(conn, user_a.company_id, crudo)
    _persistir(pool, settings, user_a, user_a.company_id, source_id, parsed)

    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        roles = [r["role"] for r in conn.execute(
            "select p.role from fiscal.document_parties p "
            "join fiscal.electronic_documents e on e.id=p.electronic_document_id "
            "where e.company_id=%s", (user_a.company_id,)).fetchall()]
    assert roles == ["issuer"]


def test_las_secuencias_de_hijos_se_enumeran_desde_uno(
    pool, settings, user_a, limpio
):
    """`line_number` sale del `NumeroLinea` reportado; `sequence` de descuentos,
    impuestos y referencias es enumeración del orden de la fuente. Se duplican
    en memoria los hijos para ver 1, 2 sin fabricar un comprobante falso."""
    arbol = etree.fromstring(_bytes(FE_7_LINEAS))
    ns = arbol.tag[1:].split("}")[0]
    import copy as _copy
    linea = arbol.findall(f".//{{{ns}}}LineaDetalle")[5]
    for etiqueta in ("Descuento", "Impuesto"):
        nodo = linea.find(f"{{{ns}}}{etiqueta}")
        linea.insert(list(linea).index(nodo) + 1, _copy.deepcopy(nodo))
    crudo = etree.tostring(arbol)

    parsed = parse_fiscal_document(crudo)
    assert len(parsed.lines[5].discounts) == 2 and len(parsed.lines[5].taxes) == 2

    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        source_id = _crear_source(conn, user_a.company_id, crudo)
    _persistir(pool, settings, user_a, user_a.company_id, source_id, parsed)

    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        l6 = conn.execute(
            "select l.id, l.line_number from fiscal.document_lines l "
            "join fiscal.electronic_documents e on e.id=l.electronic_document_id "
            "where e.company_id=%s and l.line_number=6", (user_a.company_id,)
        ).fetchone()
        seq_d = [r["sequence"] for r in conn.execute(
            "select sequence from fiscal.line_discounts where document_line_id=%s "
            "order by sequence", (l6["id"],)).fetchall()]
        seq_t = [r["sequence"] for r in conn.execute(
            "select sequence from fiscal.line_taxes where document_line_id=%s "
            "order by sequence", (l6["id"],)).fetchall()]
        numeros = [r["line_number"] for r in conn.execute(
            "select line_number from fiscal.document_lines l "
            "join fiscal.electronic_documents e on e.id=l.electronic_document_id "
            "where e.company_id=%s order by line_number", (user_a.company_id,)).fetchall()]

    assert seq_d == [1, 2] and seq_t == [1, 2]
    assert numeros == [1, 2, 3, 4, 5, 6, 7], "line_number viene de NumeroLinea"


# ═════════════════════════════════════════════════════════════════════════════
# 5 · Idempotencia y deduplicación (ADR-042)
# ═════════════════════════════════════════════════════════════════════════════

def test_reintentar_el_mismo_artefacto_no_escribe_nada(
    pool, settings, user_a, limpio
):
    source_id, parsed, primero = _persistir_fixture(
        pool, settings, user_a, FE_7_LINEAS
    )
    assert primero.status is PersistenceStatus.CREATED

    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        antes = _contar(conn, user_a.company_id)
        marca_antes = conn.execute(
            "select updated_at from fiscal.source_documents where id=%s", (source_id,)
        ).fetchone()["updated_at"]

    segundo = _persistir(
        pool, settings, user_a, user_a.company_id, source_id, parsed
    )
    assert segundo.status is PersistenceStatus.ALREADY_PERSISTED
    assert segundo.electronic_document_id == primero.electronic_document_id

    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        despues = _contar(conn, user_a.company_id)
        marca_despues = conn.execute(
            "select updated_at, electronic_document_id "
            "from fiscal.source_documents where id=%s", (source_id,)
        ).fetchone()

    assert despues == antes, "el reintento no debe crear ni borrar filas"
    assert marca_despues["updated_at"] == marca_antes, "ni siquiera updated_at"
    assert str(marca_despues["electronic_document_id"]) == primero.electronic_document_id


def test_un_artefacto_enlazado_a_otra_clave_es_conflicto_de_estado(
    pool, settings, user_a, limpio
):
    """Nunca se reenlaza: el enlace es la traza de cómo llegó esa copia."""
    source_id, _parsed, _r = _persistir_fixture(pool, settings, user_a, FE_7_LINEAS)
    otro = parse_fiscal_document(_bytes(TE_1_LINEA))   # otra clave

    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        antes = _contar(conn, user_a.company_id)

    with pytest.raises(SourceDocumentStateConflict) as exc:
        _persistir(pool, settings, user_a, user_a.company_id, source_id, otro)
    assert exc.value.code == "source_document_state_conflict"

    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        despues = _contar(conn, user_a.company_id)
    assert despues == antes


def test_segundo_artefacto_con_la_misma_huella_se_enlaza_al_existente(
    pool, settings, user_a, limpio
):
    """ADR-042 · misma empresa, misma clave, misma huella → un solo documento
    lógico y dos artefactos, conservando cómo llegó cada copia."""
    crudo = _bytes(FE_7_LINEAS)
    parsed = parse_fiscal_document(crudo)

    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        source_1 = _crear_source(conn, user_a.company_id, crudo)
    primero = _persistir(pool, settings, user_a, user_a.company_id, source_1, parsed)
    assert primero.status is PersistenceStatus.CREATED

    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        antes = _contar(conn, user_a.company_id)
        source_2 = _crear_source(conn, user_a.company_id, crudo)   # bytes idénticos

    segundo = _persistir(pool, settings, user_a, user_a.company_id, source_2, parsed)
    assert segundo.status is PersistenceStatus.LINKED_EXISTING
    assert segundo.electronic_document_id == primero.electronic_document_id

    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        despues = _contar(conn, user_a.company_id)
        enlaces = conn.execute(
            "select electronic_document_id from fiscal.source_documents "
            "where company_id=%s order by id", (user_a.company_id,)
        ).fetchall()

    # Ni una fila normalizada de más: no se duplica el agregado.
    for clave in ("edoc", "partes", "lineas", "desc_", "imp", "refs"):
        assert despues[clave] == antes[clave], clave
    assert despues["fuentes"] == 2
    assert {str(e["electronic_document_id"]) for e in enlaces} == {
        primero.electronic_document_id
    }


def test_misma_clave_con_huella_distinta_es_conflicto(
    pool, settings, user_a, limpio
):
    """ADR-042 · una huella distinta NO prueba que el contenido fiscal difiera;
    prueba que el MVP no puede establecer la equivalencia automáticamente.

    La variante es una serialización inocua —un comentario XML tras la raíz—:
    mismo comprobante, mismos campos normalizados, bytes distintos. Ni siquiera
    así se fusiona.
    """
    crudo = _bytes(FE_7_LINEAS)
    variante = crudo + b"\n<!-- otra serializacion del mismo comprobante -->"
    parsed = parse_fiscal_document(crudo)
    parsed_variante = parse_fiscal_document(variante)
    assert parsed_variante.document.clave == parsed.document.clave

    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        source_1 = _crear_source(conn, user_a.company_id, crudo)
    primero = _persistir(pool, settings, user_a, user_a.company_id, source_1, parsed)

    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        antes = _contar(conn, user_a.company_id)
        source_2 = _crear_source(conn, user_a.company_id, variante)

    with pytest.raises(ClaveConflict) as exc:
        _persistir(
            pool, settings, user_a, user_a.company_id, source_2, parsed_variante
        )
    assert exc.value.code == "clave_conflict"

    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        despues = _contar(conn, user_a.company_id)
        segundo = conn.execute(
            "select electronic_document_id from fiscal.source_documents where id=%s",
            (source_2,),
        ).fetchone()

    for clave in ("edoc", "partes", "lineas", "desc_", "imp", "refs"):
        assert despues[clave] == antes[clave], clave
    assert segundo["electronic_document_id"] is None, "el perdedor queda sin enlazar"
    assert primero.status is PersistenceStatus.CREATED


# ═════════════════════════════════════════════════════════════════════════════
# 6 · Concurrencia — dos transacciones REALES, dos conexiones
#
# El árbitro de la carrera es la restricción `(company_id, clave)`, no una
# consulta previa. Consultar-y-luego-insertar ES la carrera.
#
# Con READ COMMITTED, el segundo INSERT se BLOQUEA mientras el primero sigue
# abierto y solo recibe 23505 cuando el otro comitea. Para entonces la fila ya
# está comiteada y una sentencia nueva la ve: no hay ventana.
# ═════════════════════════════════════════════════════════════════════════════

LIMITE_CONCURRENCIA = 90        # segundos: ningún caso sano se acerca


def _correr_en_paralelo(pool, settings, user, company_id, trabajos, monkeypatch):
    """Fuerza la carrera REAL sobre el `INSERT` del documento electrónico.

    Una barrera al entrar a la transacción no probaba nada: permitía que el
    hilo A completara su transacción entera antes de que B llegara al `INSERT`,
    y los estados finales salían igual. El camino de bloqueo del índice único y
    la recuperación por `SAVEPOINT` quedaban sin ejercitar.

    Aquí la barrera está **inmediatamente antes del `INSERT`**, envolviendo
    `_insertar_documento`, que ya es la frontera natural del módulo: ambos
    workers han pasado visibilidad, `FOR UPDATE` y comprobación de enlace, y
    tienen su `SAVEPOINT` abierto. Solo entonces se sueltan los dos a la vez.

    Sin `sleep`. Sin temporizaciones. La barrera es la sincronización.
    """
    from app.fiscal import persistence as modulo

    n = len(trabajos)
    barrera = threading.Barrier(n, timeout=LIMITE_CONCURRENCIA)
    salidas: list = [None] * n
    #: Evidencia de que la carrera ocurrió: quién llegó a la puerta del INSERT.
    llegadas: list[int] = []
    candado = threading.Lock()
    original = modulo._insertar_documento
    hilo_a_indice: dict[int, int] = {}

    def _con_barrera(conn, cid, parsed):
        indice = hilo_a_indice.get(threading.get_ident())
        with candado:
            llegadas.append(indice)
        barrera.wait()                     # ← ambos aquí antes de insertar
        return original(conn, cid, parsed)

    monkeypatch.setattr(modulo, "_insertar_documento", _con_barrera)

    def _worker(indice, source_id, parsed):
        hilo_a_indice[threading.get_ident()] = indice
        try:
            with fiscal_transaction(pool, settings, user.identity) as conn:
                salidas[indice] = persist_parsed_fiscal_document(
                    conn, company_id=company_id,
                    source_document_id=source_id, parsed=parsed,
                )
        except BaseException as exc:        # noqa: BLE001 - se reporta, no se traga
            salidas[indice] = exc

    hilos = [
        threading.Thread(target=_worker, args=(i, s, p), daemon=True)
        for i, (s, p) in enumerate(trabajos)
    ]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(timeout=LIMITE_CONCURRENCIA)
        assert not h.is_alive(), "la transacción concurrente se quedó colgada"

    # La carrera es un hecho comprobado, no una inferencia de los estados.
    assert sorted(llegadas) == list(range(n)), (
        f"no todos los workers llegaron a la puerta del INSERT: {llegadas}"
    )
    return salidas


def test_concurrencia_misma_clave_misma_huella(
    pool, settings, user_a, monkeypatch, limpio
):
    """Uno crea, el otro enlaza. Exactamente un `ElectronicDocument`."""
    crudo = _bytes(FE_7_LINEAS)
    parsed = parse_fiscal_document(crudo)

    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        s1 = _crear_source(conn, user_a.company_id, crudo)
        s2 = _crear_source(conn, user_a.company_id, crudo)

    salidas = _correr_en_paralelo(
        pool, settings, user_a, user_a.company_id,
        [(s1, parsed), (s2, parsed)], monkeypatch,
    )
    for s in salidas:
        assert not isinstance(s, BaseException), f"excepción inesperada: {s!r}"

    estados = sorted(s.status.value for s in salidas)
    assert estados == ["created", "linked_existing"]
    # El resultado no depende de qué hilo ganó.
    assert len({s.electronic_document_id for s in salidas}) == 1

    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        conteo = _contar(conn, user_a.company_id)
        enlaces = conn.execute(
            "select electronic_document_id from fiscal.source_documents "
            "where company_id=%s", (user_a.company_id,)
        ).fetchall()

    assert conteo["edoc"] == 1, "se creó más de un documento para la misma clave"
    assert conteo["lineas"] == ESPERADO[FE_7_LINEAS]["lineas"]
    assert conteo["imp"] == ESPERADO[FE_7_LINEAS]["imp"]
    assert all(e["electronic_document_id"] is not None for e in enlaces)
    assert len({str(e["electronic_document_id"]) for e in enlaces}) == 1


def test_concurrencia_misma_clave_huella_distinta(
    pool, settings, user_a, monkeypatch, limpio
):
    """Uno crea, el otro recibe conflicto. El perdedor queda sin enlazar."""
    crudo = _bytes(FE_7_LINEAS)
    variante = crudo + b"\n<!-- otra serializacion -->"
    p1 = parse_fiscal_document(crudo)
    p2 = parse_fiscal_document(variante)

    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        s1 = _crear_source(conn, user_a.company_id, crudo)
        s2 = _crear_source(conn, user_a.company_id, variante)

    salidas = _correr_en_paralelo(
        pool, settings, user_a, user_a.company_id,
        [(s1, p1), (s2, p2)], monkeypatch,
    )

    exitos = [s for s in salidas if isinstance(s, PersistenceResult)]
    conflictos = [s for s in salidas if isinstance(s, ClaveConflict)]
    otros = [s for s in salidas if s not in exitos and s not in conflictos]
    assert not otros, f"salida inesperada: {otros!r}"
    assert len(exitos) == 1 and len(conflictos) == 1
    assert exitos[0].status is PersistenceStatus.CREATED

    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        conteo = _contar(conn, user_a.company_id)
        enlazados = conn.execute(
            "select count(*) as n from fiscal.source_documents "
            "where company_id=%s and electronic_document_id is not null",
            (user_a.company_id,),
        ).fetchone()["n"]

    assert conteo["edoc"] == 1
    assert conteo["lineas"] == ESPERADO[FE_7_LINEAS]["lineas"]
    assert enlazados == 1, "solo el ganador queda enlazado"


# ═════════════════════════════════════════════════════════════════════════════
# 7 · Atomicidad — la transacción externa revierte el agregado entero
#
# Los fallos se inyectan parcheando ayudantes internos de la persistencia. La
# producción no tiene banderas de test: las escrituras previas al fallo son
# escrituras reales, y lo que se comprueba es que la transacción externa las
# deshace todas.
# ═════════════════════════════════════════════════════════════════════════════

class _FalloInyectado(RuntimeError):
    """Excepción deliberada del test. No pertenece a la taxonomía fiscal."""


@pytest.mark.parametrize(
    "etapa",
    ["_insertar_partes", "_insertar_lineas", "_insertar_referencias", "_enlazar"],
)
def test_un_fallo_en_cualquier_etapa_no_deja_filas(
    etapa, pool, settings, user_a, monkeypatch, limpio
):
    from app.fiscal import persistence as modulo

    crudo = _bytes(NC_CON_REFERENCIA)      # trae líneas, impuestos y referencia
    parsed = parse_fiscal_document(crudo)
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        source_id = _crear_source(conn, user_a.company_id, crudo)

    original = getattr(modulo, etapa)

    def _revienta(*args, **kwargs):
        original(*args, **kwargs)          # escribe de verdad…
        raise _FalloInyectado(etapa)       # …y luego falla

    monkeypatch.setattr(modulo, etapa, _revienta)

    with pytest.raises(_FalloInyectado):
        _persistir(pool, settings, user_a, user_a.company_id, source_id, parsed)

    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        conteo = _contar(conn, user_a.company_id)
        fuente = conn.execute(
            "select electronic_document_id from fiscal.source_documents where id=%s",
            (source_id,),
        ).fetchone()

    # Cero filas normalizadas del intento. El artefacto PREEXISTENTE sobrevive
    # —lo creó otra transacción, ya comiteada— pero sin enlazar.
    assert _sin_filas_normalizadas(conteo), f"quedaron filas tras fallar en {etapa}"
    assert conteo["fuentes"] == 1
    assert fuente is not None, "el artefacto preexistente no debe desaparecer"
    assert fuente["electronic_document_id"] is None


def test_un_fallo_a_mitad_de_las_lineas_no_deja_lineas_sueltas(
    pool, settings, user_a, monkeypatch, limpio
):
    """Fallo DENTRO del bucle de líneas, con líneas ya insertadas."""
    from app.fiscal import persistence as modulo

    crudo = _bytes(FE_7_LINEAS)
    parsed = parse_fiscal_document(crudo)
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        source_id = _crear_source(conn, user_a.company_id, crudo)

    original = modulo._ejecutar
    estado = {"lineas": 0}

    def _contando(conn_, sql, params, etapa_):
        if etapa_ == "document_line":
            estado["lineas"] += 1
            if estado["lineas"] == 4:      # a mitad de las siete
                raise _FalloInyectado("linea 4")
        return original(conn_, sql, params, etapa_)

    monkeypatch.setattr(modulo, "_ejecutar", _contando)

    with pytest.raises(_FalloInyectado):
        _persistir(pool, settings, user_a, user_a.company_id, source_id, parsed)

    assert estado["lineas"] == 4, "el fallo no se disparó donde se pretendía"
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        conteo = _contar(conn, user_a.company_id)
    assert _sin_filas_normalizadas(conteo)


def test_una_violacion_real_de_constraint_revierte_y_es_defecto_nuestro(
    pool, settings, user_a, limpio
):
    """Fallo REAL de la base tras haber insertado documento y partes.

    Se construye a mano una línea con un CABYS de 13 caracteres **no
    numéricos**: es válida para el modelo de dominio —el XSD solo exige 13
    caracteres, hueco H-3 ya documentado— y la rechaza el CHECK físico
    `^[0-9]{13}$`. Es exactamente la frontera que `PersistenceMappingError`
    existe para nombrar: el documento pasó XSD y parser, así que quien se
    equivocó fue nuestro mapeo, no el contribuyente.
    """
    import dataclasses

    from app.fiscal.models import ParsedDocumentLine

    crudo = _bytes(FE_7_LINEAS)
    parsed = parse_fiscal_document(crudo)
    rota = dataclasses.replace(parsed.lines[0], cabys_code="ABCDEFGHIJKLM")
    assert isinstance(rota, ParsedDocumentLine)     # el dominio la acepta
    parsed_roto = dataclasses.replace(parsed, lines=(rota,) + parsed.lines[1:])

    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        source_id = _crear_source(conn, user_a.company_id, crudo)

    with pytest.raises(PersistenceMappingError) as exc:
        _persistir(pool, settings, user_a, user_a.company_id, source_id, parsed_roto)

    assert exc.value.code == "persistence_mapping_error"
    assert exc.value.contexto.get("stage") == "document_line"

    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        conteo = _contar(conn, user_a.company_id)
        fuente = conn.execute(
            "select electronic_document_id from fiscal.source_documents where id=%s",
            (source_id,),
        ).fetchone()

    assert _sin_filas_normalizadas(conteo), "el documento y las partes no revirtieron"
    assert fuente["electronic_document_id"] is None


# ═════════════════════════════════════════════════════════════════════════════
# 8 · Privacidad de los errores y fronteras del módulo
# ═════════════════════════════════════════════════════════════════════════════

#: Centinelas colocados en campos del contribuyente. Si aparecen en el error
#: público, es que el dato viajó con él.
CENTINELAS = ("SENSITIVE-NAME", "SENSITIVE-CABYS", "SENSITIVE-DESC")


def _superficie(exc: FiscalPersistenceError) -> str:
    return " ".join([str(exc), repr(exc), exc.message, repr(sorted(exc.contexto.items()))])


def test_el_conflicto_de_clave_no_expone_datos_del_contribuyente(
    pool, settings, user_a, limpio
):
    crudo = _bytes(FE_7_LINEAS)
    variante = crudo + b"\n<!-- variante -->"
    p1, p2 = parse_fiscal_document(crudo), parse_fiscal_document(variante)

    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        s1 = _crear_source(conn, user_a.company_id, crudo)
        s2 = _crear_source(conn, user_a.company_id, variante)
    _persistir(pool, settings, user_a, user_a.company_id, s1, p1)

    with pytest.raises(ClaveConflict) as exc:
        _persistir(pool, settings, user_a, user_a.company_id, s2, p2)

    publico = _superficie(exc.value)
    # Ni la clave, ni el nombre, ni la identificación, ni el XML.
    assert p1.document.clave not in publico, "la Clave es identidad fiscal"
    assert p1.issuer.legal_name not in publico
    assert p1.issuer.identificacion.numero not in publico
    assert p1.lines[0].description not in publico
    assert "<" not in publico and "select" not in publico.lower()


def test_el_defecto_de_mapeo_no_copia_el_diagnostico_de_postgresql(
    pool, settings, user_a, limpio
):
    """Solo metadatos estructurales: etapa y nombre de restricción. Ni el valor
    infractor, ni el texto legible del motor, ni SQL."""
    import dataclasses

    crudo = _bytes(FE_7_LINEAS)
    parsed = parse_fiscal_document(crudo)
    linea = dataclasses.replace(
        parsed.lines[0],
        cabys_code="ABCDEFGHIJKLM",
        description="SENSITIVE-DESC " + parsed.lines[0].description,
    )
    roto = dataclasses.replace(parsed, lines=(linea,) + parsed.lines[1:])

    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        source_id = _crear_source(conn, user_a.company_id, crudo)

    with pytest.raises(PersistenceMappingError) as exc:
        _persistir(pool, settings, user_a, user_a.company_id, source_id, roto)

    publico = _superficie(exc.value)
    for centinela in CENTINELAS:
        assert centinela not in publico
    assert "ABCDEFGHIJKLM" not in publico, "el valor infractor no debe salir"
    for filtracion in ("insert into", "check constraint", "DETAIL", "LINE 1"):
        assert filtracion.lower() not in publico.lower()
    # Contexto seguro: etapa y restricción, que son estructurales.
    assert exc.value.contexto["stage"] == "document_line"


def test_el_no_encontrado_y_el_prohibido_no_revelan_estado(
    pool, settings, user_a, as_role, limpio
):
    import uuid

    parsed = parse_fiscal_document(_bytes(FE_7_LINEAS))
    crudo = _bytes(FE_7_LINEAS)

    as_role("owner")
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        source_id = _crear_source(conn, user_a.company_id, crudo)

    with pytest.raises(SourceDocumentNotFound) as no_existe:
        _persistir(pool, settings, user_a, user_a.company_id, str(uuid.uuid4()), parsed)

    as_role("viewer")
    with pytest.raises(FiscalWriteForbidden) as prohibido:
        _persistir(pool, settings, user_a, user_a.company_id, source_id, parsed)

    for exc in (no_existe.value, prohibido.value):
        publico = _superficie(exc)
        assert parsed.document.clave not in publico
        assert parsed.issuer.legal_name not in publico
        assert "row-level security" not in publico.lower()
        assert "42501" not in publico


def test_la_persistencia_no_lee_el_xml_ni_vuelve_a_parsear():
    """C1 trabaja con `source_document_id` y el agregado ya construido.

    Releer `raw_xml` o volver a llamar al parser duplicaría una frontera que
    ya está cerrada, y reabriría la pregunta de qué versión de la evidencia es
    la buena.
    """
    from app.fiscal import persistence

    sentencias = _sql_del_modulo(persistence)
    for sql in sentencias:
        assert "raw_xml" not in sql.lower(), "la persistencia lee el XML crudo"

    fuente = Path(persistence.__file__).read_text(encoding="utf-8")
    for prohibido in ("parse_fiscal_document", "etree", "XMLSchema", "validate("):
        assert prohibido not in fuente, f"la persistencia usa {prohibido}"


def test_la_persistencia_no_calcula_nada():
    """Persistencia ≠ Tax Engine. Ni recálculo, ni catálogos, ni IA."""
    from app.fiscal import persistence

    import ast
    import re

    arbol = ast.parse(Path(persistence.__file__).read_text(encoding="utf-8"))

    # Se miran IDENTIFICADORES e IMPORTS, no la prosa: las docstrings de este
    # módulo nombran «deducibilidad» y «acreditabilidad» precisamente para
    # decir que NO las calcula, y comprobarlo sobre el texto plano fallaría
    # por eso — el mismo error que ya se corrigió en B2-R2.
    identificadores = (
        {n.id for n in ast.walk(arbol) if isinstance(n, ast.Name)}
        | {n.attr for n in ast.walk(arbol) if isinstance(n, ast.Attribute)}
        | {n.name for n in ast.walk(arbol)
           if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
        | {a.name for n in ast.walk(arbol)
           if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names}
        | {n.module for n in ast.walk(arbol)
           if isinstance(n, ast.ImportFrom) and n.module}
    )
    for prohibido in ("deducib", "acredit", "catalog", "llm", "openai",
                      "anthropic", "embedding"):
        colisiones = [x for x in identificadores if prohibido in x.lower()]
        assert not colisiones, f"aparece {prohibido}: {colisiones}"

    # Ninguna columna `computed_*` (ADR-023). El límite de palabra excluye
    # `direction_computed_at`, que es marca de tiempo de metadato y no una
    # cifra fiscal derivada — la distinción que ADR-023 protege.
    for sql in _sql_del_modulo(persistence):
        assert not re.search(r"\bcomputed_", sql.lower()), (
            f"la persistencia escribe una columna computed_*: {sql[:60]}"
        )

    # Ni aritmética sobre importes reportados.
    operaciones = [n for n in ast.walk(arbol)
                   if isinstance(n, ast.BinOp)
                   and isinstance(n.op, (ast.Mult, ast.Div, ast.Sub))]
    assert not operaciones, "hay aritmética en la capa de persistencia"


def test_la_persistencia_no_abre_conexion_ni_comitea():
    """El dueño de la transacción es la capa de caso de uso."""
    from app.fiscal import persistence

    fuente = Path(persistence.__file__).read_text(encoding="utf-8")
    for prohibido in ("ConnectionPool", "pool.connection", "psycopg.connect",
                      "SET LOCAL ROLE", "set_config", "request.jwt"):
        assert prohibido not in fuente, f"la persistencia hace {prohibido}"
    # `conn.transaction()` sí: es el SAVEPOINT anidado de la colisión de clave.
    assert "conn.transaction()" in fuente
    assert ".commit()" not in fuente and ".rollback()" not in fuente


def test_la_persistencia_no_actualiza_filas_normalizadas():
    """Los hechos reportados son inmutables para C1: el único `UPDATE` es el
    enlace del artefacto. Los grants ya lo impiden, pero conviene que el
    código lo diga también."""
    from app.fiscal import persistence

    updates = [
        sql for sql in _sql_del_modulo(persistence)
        if sql.strip().lower().startswith("update")
        or "\nupdate " in sql.lower()
    ]
    assert len(updates) == 1, f"se esperaba un solo UPDATE, hay {len(updates)}"
    assert "fiscal.source_documents" in updates[0]
    assert "electronic_document_id" in updates[0]
    assert "parse_status" not in updates[0]


# ═════════════════════════════════════════════════════════════════════════════
# 9 · R2 · Privacidad de la CADENA de excepciones
#
# La superficie textual no basta. `raise Safe(...) from exc` deja el original
# en `__cause__`, y `from None` lo deja en `__context__` — medido, no supuesto.
# La única forma de que ambos queden en `None` es lanzar FUERA del `except`.
# ═════════════════════════════════════════════════════════════════════════════

def _cadena_completa(exc: BaseException) -> list[BaseException]:
    """Todo lo alcanzable por `__cause__` y `__context__`, recursivamente."""
    vistos: dict[int, BaseException] = {}
    pila = [exc]
    while pila:
        e = pila.pop()
        if e is None or id(e) in vistos:
            continue
        vistos[id(e)] = e
        pila.append(getattr(e, "__cause__", None))
        pila.append(getattr(e, "__context__", None))
    return list(vistos.values())


def _assert_cadena_limpia(exc: FiscalPersistenceError, *sentinelas: str) -> None:
    assert exc.__cause__ is None, f"__cause__ expone {type(exc.__cause__).__name__}"
    assert exc.__context__ is None, (
        f"__context__ expone {type(exc.__context__).__name__}"
    )
    alcanzables = _cadena_completa(exc)
    assert alcanzables == [exc], (
        f"la cadena alcanza {[type(e).__name__ for e in alcanzables]}"
    )
    for e in alcanzables:
        assert not isinstance(e, psycopg.Error), "psycopg alcanzable desde la cadena"
        texto = f"{e!r} {e!s}"
        for centinela in sentinelas:
            assert centinela not in texto
        for filtracion in ("DETAIL", "insert into", "update fiscal",
                           "violates", "LINE 1", "constraint \""):
            assert filtracion.lower() not in texto.lower(), filtracion


def test_from_none_no_bastaria(pool, settings, user_a, limpio):
    """Deja constancia del motivo del diseño: `from None` limpia `__cause__`
    pero NO `__context__`. Si alguien 'simplifica' el traductor a ese patrón,
    este test explica por qué no vale."""
    from psycopg import errors as pgerr

    try:
        try:
            raise pgerr.CheckViolation("violates check constraint SECRETO")
        except pgerr.Error:
            raise PersistenceMappingError("seguro") from None
    except PersistenceMappingError as publico:
        assert publico.__cause__ is None
        assert publico.__context__ is not None, (
            "si esto cambia en una versión futura de Python, revisar el diseño"
        )
        assert isinstance(publico.__context__, psycopg.Error)


def test_el_defecto_de_mapeo_no_deja_psycopg_alcanzable(
    pool, settings, user_a, limpio
):
    """Violación REAL de restricción contra PostgreSQL. Este test falla contra
    la implementación previa a R2."""
    import dataclasses

    crudo = _bytes(FE_7_LINEAS)
    parsed = parse_fiscal_document(crudo)
    linea = dataclasses.replace(
        parsed.lines[0],
        cabys_code="ABCDEFGHIJKLM",
        description="SENSITIVE-DESC",
    )
    roto = dataclasses.replace(parsed, lines=(linea,) + parsed.lines[1:])

    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        source_id = _crear_source(conn, user_a.company_id, crudo)

    with pytest.raises(PersistenceMappingError) as exc:
        _persistir(pool, settings, user_a, user_a.company_id, source_id, roto)

    _assert_cadena_limpia(
        exc.value, "SENSITIVE-DESC", "ABCDEFGHIJKLM",
        parsed.document.clave, parsed.issuer.legal_name,
    )
    assert exc.value.contexto["stage"] == "document_line"


def test_la_denegacion_de_escritura_no_deja_psycopg_alcanzable(
    pool, settings, user_a, as_role, limpio
):
    crudo = _bytes(FE_7_LINEAS)
    parsed = parse_fiscal_document(crudo)
    as_role("owner")
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        source_id = _crear_source(conn, user_a.company_id, crudo)

    as_role("viewer")
    with pytest.raises(FiscalWriteForbidden) as exc:
        _persistir(pool, settings, user_a, user_a.company_id, source_id, parsed)
    _assert_cadena_limpia(exc.value, parsed.document.clave, parsed.issuer.legal_name)


def test_un_error_inesperado_de_bd_no_es_defecto_de_mapeo(
    pool, settings, user_a, limpio
):
    """SQL con una columna inexistente es un bug NUESTRO, no un documento que
    no encaja. Se ataca al ayudante interno para no corromper el SQL real."""
    from app.fiscal import persistence as modulo
    from app.fiscal.errors import PersistenceDatabaseError

    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        with pytest.raises(PersistenceDatabaseError) as exc:
            modulo._ejecutar(
                conn,
                "select columna_que_no_existe from fiscal.source_documents",
                (), "prueba_interna",
            )
    assert exc.value.code == "persistence_database_error"
    assert not isinstance(exc.value, PersistenceMappingError)
    _assert_cadena_limpia(exc.value, "columna_que_no_existe")


@pytest.mark.parametrize(
    "sql",
    [
        "select * from fiscal.tabla_que_no_existe",
        "selct 1",                                    # sintaxis inválida
        "select fiscal.funcion_inexistente()",
    ],
    ids=["tabla", "sintaxis", "funcion"],
)
def test_los_errores_de_programacion_son_internos_y_seguros(
    sql, pool, settings, user_a, limpio
):
    from app.fiscal import persistence as modulo
    from app.fiscal.errors import PersistenceDatabaseError

    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        with pytest.raises(PersistenceDatabaseError) as exc:
            modulo._ejecutar(conn, sql, (), "prueba_interna")
    _assert_cadena_limpia(exc.value)


def test_la_persistencia_no_registra_la_excepcion_cruda():
    """No hay logging en este módulo, y es deliberado: `logger.exception` o
    `exc_info=` volcarían la traza de psycopg con su DETAIL."""
    from app.fiscal import persistence

    import ast

    arbol = ast.parse(Path(persistence.__file__).read_text(encoding="utf-8"))

    # Por AST, no por texto: el comentario del módulo dice «no hay logging, y
    # es deliberado», y comprobarlo sobre el fichero plano fallaría por esa
    # misma frase. Es el tercer sitio donde este patrón muerde — conviene que
    # quede escrito.
    importados = (
        {a.name.split(".")[0] for n in ast.walk(arbol)
         if isinstance(n, ast.Import) for a in n.names}
        | {n.module.split(".")[0] for n in ast.walk(arbol)
           if isinstance(n, ast.ImportFrom) and n.module}
    )
    assert "logging" not in importados, "la persistencia importa logging"
    assert "traceback" not in importados

    llamadas = {
        n.func.attr for n in ast.walk(arbol)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
    } | {
        n.func.id for n in ast.walk(arbol)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    for prohibido in ("exception", "error", "warning", "print", "debug", "info"):
        assert prohibido not in llamadas, f"la persistencia llama a {prohibido}()"

    palabras_clave = {
        kw.arg for n in ast.walk(arbol) if isinstance(n, ast.Call)
        for kw in n.keywords if kw.arg
    }
    assert "exc_info" not in palabras_clave


def test_el_traductor_no_devuelve_ni_guarda_la_excepcion():
    """Guardia estructural: `_clasificar` devuelve dos cadenas, no la
    excepción, y el `raise` va fuera del bloque `except`."""
    import ast
    import inspect

    from app.fiscal import persistence as modulo

    for nombre in ("_ejecutar", "_ejecutar_muchos"):
        arbol = ast.parse(inspect.getsource(getattr(modulo, nombre)).lstrip())
        manejadores = [n for n in ast.walk(arbol) if isinstance(n, ast.ExceptHandler)]
        assert manejadores, nombre
        for h in manejadores:
            raises = [n for n in ast.walk(h) if isinstance(n, ast.Raise)]
            assert not raises, (
                f"{nombre} lanza DENTRO del except: la cadena arrastraría psycopg"
            )
    # `_clasificar` devuelve una tupla de datos, nunca la excepción.
    firma = inspect.signature(modulo._clasificar)
    assert str(firma.return_annotation).replace(" ", "") == "tuple[str,str|None]"


# ═════════════════════════════════════════════════════════════════════════════
# 10 · R2 · El enlace final exige exactamente una fila
#
# Una política `UPDATE` de RLS no lanza error: **filtra**. Si la capacidad de
# escritura cambia entre la puerta y el enlace, el `UPDATE` afecta a cero filas
# y, sin comprobarlo, devolveríamos `created` con el agregado guardado y el
# artefacto SIN enlazar — un documento huérfano de su evidencia.
# ═════════════════════════════════════════════════════════════════════════════

def test_si_el_enlace_final_no_afecta_a_ninguna_fila_se_deniega_y_revierte(
    pool, settings, user_a, as_role, monkeypatch, limpio
):
    """Carrera real: el rol cambia a `viewer` justo antes del enlace.

    El agregado normalizado YA está insertado cuando ocurre. Se comprueba que
    el enlace lo detecta, que el error público es `FiscalWriteForbidden`, y que
    la transacción externa revierte hasta la última fila.
    """
    from app.fiscal import persistence as modulo

    as_role("owner")
    crudo = _bytes(NC_CON_REFERENCIA)      # líneas, impuestos y referencia
    parsed = parse_fiscal_document(crudo)
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        source_id = _crear_source(conn, user_a.company_id, crudo)

    original = modulo._insertar_referencias
    ocurrio = {"cambio": False}

    def _y_luego_pierde_permiso(conn_, cid, edoc_id, parsed_):
        original(conn_, cid, edoc_id, parsed_)   # el agregado queda escrito
        as_role("viewer")                        # otra conexión, ya comiteada
        ocurrio["cambio"] = True

    monkeypatch.setattr(modulo, "_insertar_referencias", _y_luego_pierde_permiso)

    with pytest.raises(FiscalWriteForbidden) as exc:
        _persistir(pool, settings, user_a, user_a.company_id, source_id, parsed)

    assert ocurrio["cambio"], "el cambio de rol no llegó a ejecutarse"
    assert exc.value.contexto.get("stage") == "source_link"
    _assert_cadena_limpia(exc.value)

    as_role("owner")
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        conteo = _contar(conn, user_a.company_id)
        fuente = conn.execute(
            "select electronic_document_id from fiscal.source_documents where id=%s",
            (source_id,),
        ).fetchone()

    # §26 · la reversión externa se lleva TODO el agregado.
    assert _sin_filas_normalizadas(conteo), (
        f"quedaron filas tras la denegación en el enlace: {conteo}"
    )
    assert conteo["fuentes"] == 1
    assert fuente["electronic_document_id"] is None


def test_el_enlace_comprueba_el_numero_de_filas_afectadas():
    """Guardia estructural del invariante: `_enlazar` no puede devolver sin
    haber mirado `rowcount`."""
    import ast
    import inspect

    from app.fiscal import persistence as modulo

    fuente = inspect.getsource(modulo._enlazar)
    arbol = ast.parse(fuente.lstrip())
    atributos = {
        n.attr for n in ast.walk(arbol) if isinstance(n, ast.Attribute)
    }
    assert "rowcount" in atributos, "_enlazar no comprueba rowcount"
    # Y el predicado defiende contra el reenlace.
    assert "electronic_document_id is null" in fuente


def test_mas_de_una_fila_afectada_seria_un_fallo_interno():
    """Imposible bajo un predicado de clave primaria; si ocurriera, es estado
    inesperado de la base y no un problema del contribuyente."""
    import inspect

    from app.fiscal import persistence as modulo

    fuente = inspect.getsource(modulo._enlazar)
    assert "PersistenceDatabaseError" in fuente
    # El caso de cero filas es denegación, no error interno.
    assert "FiscalWriteForbidden" in fuente


# ═════════════════════════════════════════════════════════════════════════════
# 11 · R2 · La reversión restaura `updated_at` EXACTAMENTE
# ═════════════════════════════════════════════════════════════════════════════

def test_un_fallo_despues_del_enlace_restaura_updated_at_exacto(
    pool, settings, user_a, monkeypatch, limpio
):
    """El fallo se inyecta DESPUÉS de que `_enlazar` haya ejecutado su `UPDATE`
    real y con éxito. Se comprueba que la reversión devuelve el valor exacto,
    no «aproximadamente anterior»."""
    from app.fiscal import persistence as modulo

    crudo = _bytes(NC_CON_REFERENCIA)
    parsed = parse_fiscal_document(crudo)
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        source_id = _crear_source(conn, user_a.company_id, crudo)

    # Valor exacto ANTES, desde una transacción independiente ya comiteada.
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        antes = conn.execute(
            "select updated_at, electronic_document_id "
            "from fiscal.source_documents where id=%s", (source_id,)
        ).fetchone()

    original = modulo._enlazar
    testigo = {"enlazo": False}

    def _enlaza_y_revienta(conn_, cid, sid, edoc_id):
        original(conn_, cid, sid, edoc_id)     # el UPDATE se ejecuta de verdad
        testigo["enlazo"] = True
        raise _FalloInyectado("después del enlace")

    monkeypatch.setattr(modulo, "_enlazar", _enlaza_y_revienta)

    with pytest.raises(_FalloInyectado):
        _persistir(pool, settings, user_a, user_a.company_id, source_id, parsed)

    assert testigo["enlazo"], "el enlace real no llegó a ejecutarse"

    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        despues = conn.execute(
            "select updated_at, electronic_document_id "
            "from fiscal.source_documents where id=%s", (source_id,)
        ).fetchone()
        conteo = _contar(conn, user_a.company_id)

    assert despues["electronic_document_id"] is None
    assert despues["electronic_document_id"] == antes["electronic_document_id"]
    assert despues["updated_at"] == antes["updated_at"], (
        "la reversión debe devolver el valor EXACTO, no uno parecido"
    )
    assert _sin_filas_normalizadas(conteo)


def test_el_enlace_dentro_de_la_transaccion_si_cambia_updated_at(
    pool, settings, user_a, limpio
):
    """Contraprueba del test anterior: sin el fallo, `updated_at` SÍ avanza.

    Sin esto, el test de reversión pasaría igual aunque el `UPDATE` nunca
    hubiera tocado la columna.
    """
    crudo = _bytes(FE_7_LINEAS)
    parsed = parse_fiscal_document(crudo)
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        source_id = _crear_source(conn, user_a.company_id, crudo)
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        antes = conn.execute(
            "select updated_at from fiscal.source_documents where id=%s",
            (source_id,)).fetchone()["updated_at"]

    _persistir(pool, settings, user_a, user_a.company_id, source_id, parsed)

    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        despues = conn.execute(
            "select updated_at from fiscal.source_documents where id=%s",
            (source_id,)).fetchone()["updated_at"]
    assert despues > antes, "el enlace debería haber avanzado updated_at"


# ═════════════════════════════════════════════════════════════════════════════
# 12 · R2 · Prueba del ramal SAVEPOINT
# ═════════════════════════════════════════════════════════════════════════════

def test_el_savepoint_deja_la_transaccion_externa_utilizable(
    pool, settings, user_a, limpio
):
    """Tras el `23505` del perdedor: el `SAVEPOINT` revierte, la transacción
    externa sigue viva, el documento del ganador es visible bajo READ COMMITTED
    y la comparación de huella decide el desenlace.

    Se ejecuta en serie a propósito —el ganador ya comiteó— para aislar el
    ramal de recuperación del resto de la mecánica de concurrencia.
    """
    crudo = _bytes(FE_7_LINEAS)
    parsed = parse_fiscal_document(crudo)

    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        s1 = _crear_source(conn, user_a.company_id, crudo)
    ganador = _persistir(pool, settings, user_a, user_a.company_id, s1, parsed)

    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        s2 = _crear_source(conn, user_a.company_id, crudo)

    # Una sola transacción: colisiona, recupera por SAVEPOINT y sigue
    # trabajando —lee el documento existente, compara huella y enlaza—.
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        resultado = persist_parsed_fiscal_document(
            conn, company_id=user_a.company_id,
            source_document_id=s2, parsed=parsed,
        )
        # La transacción externa sigue utilizable tras el rollback al savepoint.
        vivo = conn.execute("select 1 as ok").fetchone()["ok"]

    assert vivo == 1, "la transacción externa quedó abortada tras el 23505"
    assert resultado.status is PersistenceStatus.LINKED_EXISTING
    assert resultado.electronic_document_id == ganador.electronic_document_id
