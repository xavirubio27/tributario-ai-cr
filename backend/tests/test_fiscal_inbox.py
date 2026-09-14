"""Bandeja de documentos fiscales (C3-B3) — contra PostgreSQL y C2 reales.

Se usa el camino de ingesta REAL siempre que se puede, de modo que cada caso
prueba a la vez el ciclo de vida que escribe C2 y la lectura que lo interpreta.
Probar la lectura sobre filas fabricadas a mano demostraría que el mapeo
funciona sobre estados que quizá C2 nunca produce.
"""

from __future__ import annotations

import base64
import json
import time
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from lxml import etree

from app.db import fiscal_transaction
from app.fiscal.inbox import (
    PAGINA_MAXIMA,
    InboxCursor,
    InboxQueryError,
    OperationalStatus,
    clasificar,
    decode_cursor,
    read_inbox,
)
from app.fiscal.ingestion import IngestionSource, ingest_fiscal_xml
from app.main import app

FIXTURES = Path(__file__).parent / "fixtures" / "fiscal" / "real" / "v4_4"
FE = "50601082600310161019803900001010004596121100"
TE = "Comprobante_Electronico_50630062600310174582"
NC = "NC-50631082600310181576400100001030000001522"

_TRANSITORIOS = ("unexpected status 401", "unexpected login role status 401",
                 "LegacyDbConfigConnectTempRoleError", "unexpected status 5")


def _admin_resiliente(admin_sql, sql, intentos=3):
    ultimo = None
    for i in range(intentos):
        try:
            return admin_sql(sql)
        except Exception as exc:            # noqa: BLE001
            if not any(t in str(exc) for t in _TRANSITORIOS):
                raise
            ultimo = str(exc)
            time.sleep(1 + i)
    raise AssertionError(f"CLI de Supabase falló por transporte: {ultimo[:160]}")


def _borrado(user_a, user_b) -> str:
    ambas = f"('{user_a.company_id}','{user_b.company_id}')"
    return (f"with s as (delete from fiscal.source_documents "
            f"where company_id in {ambas} returning 1) "
            f"delete from fiscal.electronic_documents where company_id in {ambas}")


def _fixture(prefijo: str) -> Path:
    for sub in ("fe", "te", "nc", "mh"):
        for p in (FIXTURES / sub).glob("*.xml"):
            if p.name.startswith(prefijo):
                return p
    raise AssertionError(prefijo)


def _bytes(prefijo: str) -> bytes:
    return _fixture(prefijo).read_bytes()


def _mh_bytes() -> bytes:
    return sorted((FIXTURES / "mh").glob("*.xml"))[0].read_bytes()


@pytest.fixture(scope="module")
def client(settings):  # noqa: ARG001
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module", autouse=True)
def _limpieza_inicial(admin_sql, user_a, user_b):
    _admin_resiliente(admin_sql, _borrado(user_a, user_b))
    yield


@pytest.fixture
def limpio(admin_sql, user_a, user_b):
    try:
        yield
    finally:
        _admin_resiliente(admin_sql, _borrado(user_a, user_b))


@pytest.fixture
def as_role(admin_sql, user_a):
    original = admin_sql(
        f"select role from public.company_memberships "
        f"where company_id='{user_a.company_id}' and user_id='{user_a.id}'"
    )[0]["role"]

    def _set(role: str) -> None:
        admin_sql(f"update public.company_memberships set role='{role}' "
                  f"where company_id='{user_a.company_id}' and user_id='{user_a.id}'")

    yield _set
    _set(original)


def _ingerir(pool, settings, user, datos):
    """Camino REAL de C2. Devuelve el resultado o la excepción esperada."""
    try:
        return ingest_fiscal_xml(
            pool, settings, user.identity, company_id=user.company_id,
            raw_xml=datos, ingestion_source=IngestionSource.MANUAL_UPLOAD,
        )
    except Exception as exc:              # noqa: BLE001
        return exc


def _leer(pool, settings, user, **kw):
    with fiscal_transaction(pool, settings, user.identity) as conn:
        return read_inbox(conn, company_id=user.company_id, **kw)


def _get(client, user, company_id, **params):
    return client.get(
        f"/companies/{company_id}/fiscal-documents",
        params=params, headers={"Authorization": f"Bearer {user.token}"},
    )


# ═════════════════════════════════════════════════════════════════════════════
# 1 · La regla de derivación
# ═════════════════════════════════════════════════════════════════════════════

#: Todos los estados durables que C2 puede dejar, con su clasificación.
#: `(edoc, parse_status, parse_error, detection_status, detected_type)`
ESTADOS_DE_C2 = [
    (uuid4(), "parsed", None, "detected", "invoice", OperationalStatus.PROCESSED),
    (None, "parsed", None, "detected", "invoice", OperationalStatus.REQUIRES_ATTENTION),
    (None, "pending", None, "pending", None, OperationalStatus.SYSTEM_PENDING),
    (None, "failed", "malformed_xml", "failed", None, OperationalStatus.INVALID_DOCUMENT),
    (None, "failed", "xsd_validation_error", "detected", "invoice",
     OperationalStatus.INVALID_DOCUMENT),
    (None, "failed", "semantic_parse_error", "detected", "invoice",
     OperationalStatus.INVALID_DOCUMENT),
    (None, "failed", "unsupported_document", "unknown", None,
     OperationalStatus.UNRECOGNIZED),
    (None, "failed", "unsupported_document", "unsupported", "debit_note",
     OperationalStatus.NOT_YET_SUPPORTED),
    (None, "failed", "unsupported_document", "unsupported", "hacienda_message",
     OperationalStatus.OUTSIDE_PIPELINE),
]


@pytest.mark.parametrize(
    ("edoc", "ps", "pe", "sds", "dt", "esperado"), ESTADOS_DE_C2,
    ids=[c[5].value for c in ESTADOS_DE_C2],
)
def test_la_regla_clasifica_cada_estado_durable(edoc, ps, pe, sds, dt, esperado):
    assert clasificar(
        electronic_document_id=edoc, parse_status=ps, parse_error=pe,
        schema_detection_status=sds, detected_document_type=dt,
    ) is esperado


def test_un_estado_que_c2_no_produce_falla_cerrando():
    """No se inventa una categoría para un estado imposible."""
    from app.fiscal.errors import PersistenceDatabaseError

    with pytest.raises(PersistenceDatabaseError):
        clasificar(electronic_document_id=None, parse_status="failed",
                   parse_error="codigo_del_futuro",
                   schema_detection_status="detected", detected_document_type=None)


def test_la_regla_no_mira_texto_de_error_ni_xml():
    """`parse_error` guarda CÓDIGOS, no mensajes: es lo que hace posible B3.

    Sobre AST y nunca sobre el texto del fichero. Buscar `".lower()"` como
    subcadena confunde MENCIONAR con HACER —un comentario bastaría para
    romperlo— y es el patrón frágil que este repositorio ya ha corregido
    varias veces.
    """
    import ast

    from app.fiscal import inbox

    arbol = ast.parse(Path(inbox.__file__).read_text(encoding="utf-8"))

    # No se invoca al parser ni a lxml.
    llamadas = {n.func.id for n in ast.walk(arbol)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    for prohibido in ("parse_fiscal_document", "fromstring"):
        assert prohibido not in llamadas, f"la lectura usa {prohibido}"
    assert not any(
        isinstance(n, (ast.Import, ast.ImportFrom))
        and "lxml" in (getattr(n, "module", "") or "")
        for n in ast.walk(arbol)
    ), "la lectura importa lxml"

    # Y no se interroga el TEXTO del error: nada de normalizar ni buscar
    # prefijos sobre él. Se comprueba por métodos invocados, no por cadenas.
    metodos = {n.func.attr for n in ast.walk(arbol)
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    for textual in ("lower", "upper", "startswith", "endswith", "find", "split"):
        assert textual not in metodos, f"la lectura manipula texto con {textual}()"


def test_los_limites_de_tribuu_no_cuentan_como_deuda_del_usuario():
    from app.fiscal.inbox import REQUIEREN_ACCION

    assert OperationalStatus.NOT_YET_SUPPORTED not in REQUIEREN_ACCION
    assert OperationalStatus.OUTSIDE_PIPELINE not in REQUIEREN_ACCION
    assert OperationalStatus.SYSTEM_PENDING not in REQUIEREN_ACCION
    assert REQUIEREN_ACCION == {
        OperationalStatus.REQUIRES_ATTENTION,
        OperationalStatus.INVALID_DOCUMENT,
        OperationalStatus.UNRECOGNIZED,
    }


# ═════════════════════════════════════════════════════════════════════════════
# 2 · Cursor
# ═════════════════════════════════════════════════════════════════════════════

def _cursor_crudo(**cambios) -> str:
    base = {"v": 1, "receivedAt": "2026-09-13T10:00:00+00:00",
            "kind": "receipt", "rowId": str(uuid4())}
    base.update(cambios)
    crudo = json.dumps(base).encode()
    return base64.urlsafe_b64encode(crudo).decode().rstrip("=")


def test_un_cursor_valido_va_y_vuelve():
    from datetime import UTC, datetime

    original = InboxCursor(
        received_at=datetime(2026, 9, 13, 10, 0, tzinfo=UTC),
        kind="document", row_id=uuid4(),
    )
    vuelto = decode_cursor(original.encode())
    assert vuelto == original


@pytest.mark.parametrize(
    ("nombre", "crudo"),
    [
        ("base64 inválido", "no-es-base64-%%%"),
        ("base64 válido con JSON inválido", base64.urlsafe_b64encode(b"{roto").decode()),
        ("no es un objeto", base64.urlsafe_b64encode(b'["a"]').decode()),
        ("versión futura", _cursor_crudo(v=2)),
        ("marca de tiempo inválida", _cursor_crudo(receivedAt="ayer")),
        ("tipo de fila desconocido", _cursor_crudo(kind="factura")),
        ("uuid inválido", _cursor_crudo(rowId="no-es-uuid")),
    ],
)
def test_un_cursor_invalido_se_rechaza(nombre, crudo):
    with pytest.raises(InboxQueryError):
        decode_cursor(crudo)


def test_un_cursor_con_claves_de_mas_o_de_menos_se_rechaza():
    falta = base64.urlsafe_b64encode(
        json.dumps({"v": 1, "kind": "receipt", "rowId": str(uuid4())}).encode()
    ).decode().rstrip("=")
    sobra = _cursor_crudo(orderBy="total desc")
    for crudo in (falta, sobra):
        with pytest.raises(InboxQueryError):
            decode_cursor(crudo)


def test_el_cursor_no_transporta_orden_elegido_por_el_cliente():
    """Es estado de paginación, no un fragmento de ORDER BY."""
    with pytest.raises(InboxQueryError):
        decode_cursor(_cursor_crudo(sort="reported_total_document"))


def test_el_error_de_cursor_no_revela_el_decodificador():
    try:
        decode_cursor("%%%")
    except InboxQueryError as exc:
        texto = f"{exc} {exc.args}"
        for fuga in ("base64", "binascii", "json", "Traceback", "padding"):
            assert fuga.lower() not in texto.lower()


# ═════════════════════════════════════════════════════════════════════════════
# 3 · Matriz de estados por el camino REAL de C2
# ═════════════════════════════════════════════════════════════════════════════

def test_un_comprobante_valido_aparece_procesado(pool, settings, user_a, limpio):
    r = _ingerir(pool, settings, user_a, _bytes(FE))
    assert not isinstance(r, Exception), r

    pagina = _leer(pool, settings, user_a)
    assert len(pagina.items) == 1
    item = pagina.items[0]
    assert item.operational_status is OperationalStatus.PROCESSED
    assert item.kind == "document"
    assert str(item.electronic_document_id) == r.electronic_document_id
    assert item.source_document_id is None, "un documento colapsa recepciones"
    assert item.document_type == "invoice"
    assert item.receipt_count == 1
    assert pagina.counts.needs_attention == 0
    assert pagina.counts.system_pending == 0


def test_el_conflicto_de_clave_requiere_atencion(pool, settings, user_a, limpio):
    """Fija la invariante que NO tiene columna propia.

    `parsed` + sin enlace significa conflicto de clave porque el `except
    ClaveConflict` de C2 es el único camino que comitea T2 sin enlazar. No hay
    campo que lo diga, así que este test es lo que impide que otro desenlace
    «parseado y sin enlazar» se cuele aquí en silencio.
    """
    from app.fiscal.errors import ClaveConflict

    assert not isinstance(_ingerir(pool, settings, user_a, _bytes(FE)), Exception)

    arbol = etree.fromstring(_bytes(FE))
    ns = arbol.tag[1:].split("}")[0]
    nodo = arbol.find(f"{{{ns}}}NumeroConsecutivo")
    nodo.text = nodo.text[:-1] + ("0" if nodo.text[-1] != "0" else "1")
    conflicto = _ingerir(pool, settings, user_a, etree.tostring(arbol))
    assert isinstance(conflicto, ClaveConflict)
    sid = conflicto.contexto["source_document_id"]

    # El estado durable que sostiene la inferencia.
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        fila = conn.execute(
            "select parse_status, electronic_document_id "
            "from fiscal.source_documents where id=%s", (sid,)).fetchone()
    assert fila["parse_status"] == "parsed"
    assert fila["electronic_document_id"] is None

    pagina = _leer(pool, settings, user_a)
    conflictivo = [i for i in pagina.items if str(i.source_document_id) == sid]
    assert len(conflictivo) == 1
    assert conflictivo[0].operational_status is OperationalStatus.REQUIRES_ATTENTION
    assert conflictivo[0].kind == "receipt"
    assert pagina.counts.needs_attention == 1


@pytest.mark.parametrize(
    ("nombre", "carga", "estado", "tipo"),
    [
        ("malformado", b"<FacturaElectronica> sin cerrar",
         OperationalStatus.INVALID_DOCUMENT, None),
        ("doctype", b'<!DOCTYPE r [<!ENTITY e "x">]>\n<r/>',
         OperationalStatus.INVALID_DOCUMENT, None),
        ("desconocido", b'<Cualquiera xmlns="urn:x"><a/></Cualquiera>',
         OperationalStatus.UNRECOGNIZED, None),
    ],
)
def test_documentos_que_no_se_procesan(
    pool, settings, user_a, nombre, carga, estado, tipo, limpio
):
    _ingerir(pool, settings, user_a, carga)
    pagina = _leer(pool, settings, user_a)
    assert len(pagina.items) == 1
    assert pagina.items[0].operational_status is estado
    assert pagina.items[0].document_type == tipo


def test_un_xsd_invalido_es_documento_invalido(pool, settings, user_a, limpio):
    arbol = etree.fromstring(_bytes(FE))
    ns = arbol.tag[1:].split("}")[0]
    arbol.find(f"{{{ns}}}Clave").text = "NO-ES-UNA-CLAVE"
    _ingerir(pool, settings, user_a, etree.tostring(arbol))

    pagina = _leer(pool, settings, user_a)
    assert pagina.items[0].operational_status is OperationalStatus.INVALID_DOCUMENT
    # El tipo SÍ se detectó antes de fallar la validación.
    assert pagina.items[0].document_type == "invoice"
    assert pagina.counts.needs_attention == 1


def test_la_nota_de_debito_es_todavia_no_soportada(pool, settings, user_a, limpio):
    ns = ("https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.4/"
          "notaDebitoElectronica")
    crudo = f'<NotaDebitoElectronica xmlns="{ns}"><Clave/></NotaDebitoElectronica>'.encode()
    _ingerir(pool, settings, user_a, crudo)

    pagina = _leer(pool, settings, user_a)
    assert pagina.items[0].operational_status is OperationalStatus.NOT_YET_SUPPORTED
    assert pagina.items[0].document_type == "debit_note"
    # Es un límite NUESTRO: no cuenta como algo que el usuario deba resolver.
    assert pagina.counts.needs_attention == 0


def test_el_mensaje_hacienda_queda_fuera_del_flujo(pool, settings, user_a, limpio):
    _ingerir(pool, settings, user_a, _mh_bytes())

    pagina = _leer(pool, settings, user_a)
    assert pagina.items[0].operational_status is OperationalStatus.OUTSIDE_PIPELINE
    assert pagina.items[0].document_type == "hacienda_message"
    assert pagina.counts.needs_attention == 0, "no es culpa del usuario"


def test_un_artefacto_capturado_sin_procesar_esta_pendiente(
    pool, settings, user_a, monkeypatch, limpio
):
    """`PersistenceUnavailable` revierte T2: la fila queda en `pending`."""
    from app.fiscal import ingestion
    from app.fiscal.errors import PersistenceUnavailable

    def _caida(*a, **k):
        raise PersistenceUnavailable("no disponible", stage="inyectado")

    monkeypatch.setattr(ingestion, "persist_parsed_fiscal_document", _caida)
    r = _ingerir(pool, settings, user_a, _bytes(FE))
    assert isinstance(r, PersistenceUnavailable)

    pagina = _leer(pool, settings, user_a)
    assert pagina.items[0].operational_status is OperationalStatus.SYSTEM_PENDING
    assert pagina.counts.system_pending == 1
    assert pagina.counts.needs_attention == 0, "es cosa nuestra, no del usuario"


# ═════════════════════════════════════════════════════════════════════════════
# 4 · Duplicados
# ═════════════════════════════════════════════════════════════════════════════

def test_dos_recepciones_del_mismo_xml_son_una_sola_fila(
    pool, settings, user_a, limpio
):
    crudo = _bytes(FE)
    primero = _ingerir(pool, settings, user_a, crudo)
    segundo = _ingerir(pool, settings, user_a, crudo)
    assert primero.status.value == "created"
    assert segundo.status.value == "linked_existing"

    # La evidencia NO se borra: siguen siendo dos artefactos.
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        n = conn.execute(
            "select count(*) as n from fiscal.source_documents where company_id=%s",
            (user_a.company_id,)).fetchone()["n"]
    assert n == 2

    pagina = _leer(pool, settings, user_a)
    assert len(pagina.items) == 1, "la bandeja no se ensucia por una doble subida"
    assert pagina.items[0].receipt_count == 2
    assert pagina.items[0].electronic_document_id is not None
    assert pagina.items[0].source_document_id is None


# ═════════════════════════════════════════════════════════════════════════════
# 5 · Equivalencia REAL entre la regla canónica y el filtro SQL
#
# El filtro por estado existe dos veces: `clasificar()` y `_PREDICADO`. La
# duplicación era necesaria —filtrar en Python tras traer la página devolvía
# páginas ralas— pero dos verdades divergen. Estos tests la vigilan CONTRA LA
# BASE: si una de las dos cambia sola, fallan.
# ═════════════════════════════════════════════════════════════════════════════

#: Los NUEVE desenlaces durables alcanzables de C2, fila a fila:
#: `(parse_status, parse_error, schema_detection_status, detected_document_type)`,
#: si la fila queda enlazada a un documento electrónico, y su clasificación.
#: `invalid_document` agrupa TRES errores distintos; por eso el enum de siete
#: valores no basta como lista de desenlaces.
DESENLACES_DURABLES = {
    "processed": (("parsed", None, "detected", "invoice"), True,
                  OperationalStatus.PROCESSED),
    "clave_conflict": (("parsed", None, "detected", "invoice"), False,
                       OperationalStatus.REQUIRES_ATTENTION),
    "pending": (("pending", None, "pending", None), False,
                OperationalStatus.SYSTEM_PENDING),
    "malformed_xml": (("failed", "malformed_xml", "failed", None), False,
                      OperationalStatus.INVALID_DOCUMENT),
    "xsd_validation_error": (
        ("failed", "xsd_validation_error", "detected", "invoice"), False,
        OperationalStatus.INVALID_DOCUMENT),
    "semantic_parse_error": (
        ("failed", "semantic_parse_error", "detected", "invoice"), False,
        OperationalStatus.INVALID_DOCUMENT),
    "unknown_document": (("failed", "unsupported_document", "unknown", None),
                         False, OperationalStatus.UNRECOGNIZED),
    "debit_note": (("failed", "unsupported_document", "unsupported", "debit_note"),
                   False, OperationalStatus.NOT_YET_SUPPORTED),
    "hacienda_message": (
        ("failed", "unsupported_document", "unsupported", "hacienda_message"),
        False, OperationalStatus.OUTSIDE_PIPELINE),
}


def _semantico_inyectado(pool, settings, user, monkeypatch) -> str:
    """`semantic_parse_error` por la frontera REAL de procesamiento de C2.

    Ningún XML público lo alcanza hoy: sus puntos de partida posteriores al
    XSD los ataja antes el propio esquema (demostrado en la suite de ingesta).
    Fabricar un XML que lo simulara fingiría cobertura, así que se inyecta el
    error del parser en la frontera del módulo —igual que hace la suite de
    ingesta— y C2 hace TODO lo demás: captura T1, mapeo del fallo y estado
    durable.
    """
    from app.fiscal import ingestion
    from app.fiscal.errors import DocumentDetection, SemanticParseError

    deteccion = DocumentDetection(document_type="invoice", schema_version="4.4")

    def _semantico(*a, **k):
        raise SemanticParseError(
            "fallo semántico inyectado", detection=deteccion, campo="Emisor")

    monkeypatch.setattr(ingestion, "parse_fiscal_document", _semantico)
    r = _ingerir(pool, settings, user, _bytes(FE))
    monkeypatch.undo()
    assert isinstance(r, SemanticParseError)
    return r.contexto["source_document_id"]


def _sembrar_todos_los_estados(pool, settings, user, monkeypatch):
    """Crea una fila por cada desenlace durable REAL de C2, salvo `pending`.

    Devuelve `{desenlace: row_id}` con las claves de `DESENLACES_DURABLES`:
    el documento electrónico para `processed`, la recepción para el resto.
    Se usan los caminos de ingesta auténticos, no filas fabricadas: probar
    sobre estados que C2 quizá nunca produce no demostraría nada.
    """
    from app.fiscal.errors import ClaveConflict

    creados: dict[str, str] = {}

    # processed
    ok = _ingerir(pool, settings, user, _bytes(FE))
    creados["processed"] = str(ok.electronic_document_id)

    # clave_conflict — misma clave, bytes distintos
    arbol = etree.fromstring(_bytes(FE))
    ns = arbol.tag[1:].split("}")[0]
    nodo = arbol.find(f"{{{ns}}}NumeroConsecutivo")
    nodo.text = nodo.text[:-1] + ("0" if nodo.text[-1] != "0" else "1")
    conflicto = _ingerir(pool, settings, user, etree.tostring(arbol))
    assert isinstance(conflicto, ClaveConflict)
    creados["clave_conflict"] = conflicto.contexto["source_document_id"]

    # invalid_document — las TRES rutas
    r = _ingerir(pool, settings, user, b"<FacturaElectronica> sin cerrar")
    creados["malformed_xml"] = r.contexto["source_document_id"]
    r = _ingerir(pool, settings, user, _xsd_invalido())
    creados["xsd_validation_error"] = r.contexto["source_document_id"]
    creados["semantic_parse_error"] = _semantico_inyectado(
        pool, settings, user, monkeypatch)

    # unrecognized
    r = _ingerir(pool, settings, user, b'<Otro xmlns="urn:x"><a/></Otro>')
    creados["unknown_document"] = r.contexto["source_document_id"]

    # not_yet_supported — Nota de Débito
    nd_ns = ("https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.4/"
             "notaDebitoElectronica")
    r = _ingerir(pool, settings, user,
                 f'<NotaDebitoElectronica xmlns="{nd_ns}"><Clave/></NotaDebitoElectronica>'.encode())
    creados["debit_note"] = r.contexto["source_document_id"]

    # outside_pipeline — MensajeHacienda
    r = _ingerir(pool, settings, user, _mh_bytes())
    creados["hacienda_message"] = r.contexto["source_document_id"]

    return creados


def _xsd_invalido() -> bytes:
    arbol = etree.fromstring(_bytes(FE))
    ns = arbol.tag[1:].split("}")[0]
    arbol.find(f"{{{ns}}}Clave").text = "NO-ES-UNA-CLAVE"
    return etree.tostring(arbol)


def _pendiente(pool, settings, user, monkeypatch) -> str:
    """Un artefacto capturado cuya T2 revirtió."""
    from app.fiscal import ingestion
    from app.fiscal.errors import PersistenceUnavailable

    def _caida(*a, **k):
        raise PersistenceUnavailable("no disponible", stage="inyectado")

    monkeypatch.setattr(ingestion, "persist_parsed_fiscal_document", _caida)
    r = _ingerir(pool, settings, user, _bytes(TE))
    monkeypatch.undo()
    return r.contexto["source_document_id"]


def test_el_filtro_sql_coincide_con_la_regla_canonica(
    pool, settings, user_a, monkeypatch, limpio
):
    """Para CADA estado: `?status=X` devuelve exactamente las filas que
    `clasificar()` considera X. Ni una más, ni una menos.

    Esto es lo que protege la duplicación: si el predicado SQL y la función
    divergen, la comparación falla en el estado afectado.
    """
    _sembrar_todos_los_estados(pool, settings, user_a, monkeypatch)
    _pendiente(pool, settings, user_a, monkeypatch)

    todos = _leer(pool, settings, user_a, limit=100)
    # La verdad canónica, calculada en Python sobre lo que devolvió la base.
    por_estado_python: dict[OperationalStatus, set[str]] = {}
    for item in todos.items:
        por_estado_python.setdefault(item.operational_status, set()).add(str(item.row_id))

    for estado in OperationalStatus:
        filtrado = _leer(pool, settings, user_a, limit=100, status=estado)
        sql = {str(i.row_id) for i in filtrado.items}
        python = por_estado_python.get(estado, set())
        assert sql == python, (
            f"{estado.value}: SQL devolvió {sorted(sql)} y la regla dice {sorted(python)}"
        )
        # Y todo lo devuelto por el filtro se clasifica efectivamente como X.
        assert all(i.operational_status is estado for i in filtrado.items)


def test_los_nueve_desenlaces_reales_estan_representados(
    pool, settings, user_a, monkeypatch, limpio
):
    """El espacio cubierto es el ALCANZABLE, fila a fila, no una lista inventada.

    Que aparezcan los siete valores del enum no basta: `invalid_document`
    agrupa tres errores distintos. Para CADA uno de los nueve desenlaces se
    comprueba el estado durable exacto que dejó C2 en la base, que la regla
    canónica lo clasifica como se espera, y que el filtro SQL devuelve ESA
    fila concreta.
    """
    sembrados = _sembrar_todos_los_estados(pool, settings, user_a, monkeypatch)
    sembrados["pending"] = _pendiente(pool, settings, user_a, monkeypatch)

    assert set(sembrados) == set(DESENLACES_DURABLES), "los nueve, ni uno menos"

    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        for nombre, (tupla, enlazado, esperado) in DESENLACES_DURABLES.items():
            clave = "electronic_document_id" if nombre == "processed" else "id"
            fila = conn.execute(
                "select electronic_document_id, parse_status, parse_error, "
                "schema_detection_status, detected_document_type "
                f"from fiscal.source_documents where {clave} = %s",
                (sembrados[nombre],)).fetchone()
            assert fila is not None, nombre
            durable = (fila["parse_status"], fila["parse_error"],
                       fila["schema_detection_status"],
                       fila["detected_document_type"])
            assert durable == tupla, f"{nombre}: C2 dejó {durable}"
            assert (fila["electronic_document_id"] is not None) is enlazado, nombre
            assert clasificar(
                electronic_document_id=fila["electronic_document_id"],
                parse_status=fila["parse_status"],
                parse_error=fila["parse_error"],
                schema_detection_status=fila["schema_detection_status"],
                detected_document_type=fila["detected_document_type"],
            ) is esperado, nombre

    # Y el filtro SQL incluye exactamente esa fila bajo su estado.
    for nombre, (_, _, esperado) in DESENLACES_DURABLES.items():
        filtrado = _leer(pool, settings, user_a, limit=100, status=esperado)
        assert str(sembrados[nombre]) in {str(i.row_id) for i in filtrado.items}, nombre


# ═════════════════════════════════════════════════════════════════════════════
# 6 · Paginación por keyset contra la base
#
# El orden declarado es `received_at DESC, kind_rank ASC, row_id DESC`, con
# `kind_rank` ASCENDENTE mientras las otras dos descienden. Una comparación de
# tuplas ahí es INCORRECTA: saltaba filas y repetía otras. Estos tests fijan el
# comparador lexicográfico explícito con instantes REALMENTE iguales, fijados
# en la base, no con esperas ni tiempos aproximados.
# ═════════════════════════════════════════════════════════════════════════════

def _fijar_llegada(admin_sql, company_id: str, momentos: dict[str, str]) -> None:
    """Fija `ingested_at` de artefactos concretos. Control exacto del orden."""
    casos = " ".join(
        f"when id = '{sid}' then timestamptz '{ts}'" for sid, ts in momentos.items()
    )
    ids = ", ".join(f"'{s}'" for s in momentos)
    _admin_resiliente(
        admin_sql,
        f"update fiscal.source_documents set ingested_at = case {casos} end "
        f"where company_id = '{company_id}' and id in ({ids})",
    )


def _sembrar_mezcla(pool, settings, user, admin_sql, instante: str):
    """Un `document` y un `receipt` con EXACTAMENTE el mismo `received_at`."""
    ok = _ingerir(pool, settings, user, _bytes(FE))
    malo = _ingerir(pool, settings, user, b"<FacturaElectronica> sin cerrar")

    with fiscal_transaction(pool, settings, user.identity) as conn:
        sid_doc = conn.execute(
            "select id from fiscal.source_documents where electronic_document_id=%s",
            (ok.electronic_document_id,)).fetchone()["id"]
    sid_rec = malo.contexto["source_document_id"]

    _fijar_llegada(admin_sql, user.company_id,
                   {str(sid_doc): instante, sid_rec: instante})
    return ok.electronic_document_id, sid_rec


def test_con_el_mismo_instante_el_documento_va_antes_que_la_recepcion(
    pool, settings, user_a, admin_sql, limpio
):
    """`kind_rank ASC` desempata: `document` (0) antes que `receipt` (1)."""
    eid, sid = _sembrar_mezcla(pool, settings, user_a, admin_sql,
                               "2026-09-13 10:00:00+00")

    pagina = _leer(pool, settings, user_a, limit=100)
    assert len(pagina.items) == 2
    assert pagina.items[0].kind == "document"
    assert str(pagina.items[0].row_id) == eid
    assert pagina.items[1].kind == "receipt"
    assert str(pagina.items[1].row_id) == sid
    assert pagina.items[0].received_at == pagina.items[1].received_at


def test_el_cursor_entre_clases_con_el_mismo_instante_no_salta_ni_repite(
    pool, settings, user_a, admin_sql, limpio
):
    """El defecto exacto que corrigió R1.

    Con la comparación de tuplas, `(T, 1, receipt) < (T, 0, document)` es FALSA
    y la recepción desaparecía. Esta es la prueba que lo impide.
    """
    eid, sid = _sembrar_mezcla(pool, settings, user_a, admin_sql,
                               "2026-09-13 11:00:00+00")

    primera = _leer(pool, settings, user_a, limit=1)
    assert len(primera.items) == 1
    assert str(primera.items[0].row_id) == eid
    assert primera.next_cursor is not None

    segunda = _leer(pool, settings, user_a, limit=1,
                    cursor=decode_cursor(primera.next_cursor))
    assert len(segunda.items) == 1, "la recepción se perdía con la tupla"
    assert str(segunda.items[0].row_id) == sid
    assert segunda.items[0].kind == "receipt"


def test_dos_filas_de_la_misma_clase_con_el_mismo_instante_desempatan_por_id(
    pool, settings, user_a, admin_sql, limpio
):
    """Mismo `kind_rank`: manda `row_id DESC`, sin repetir ni saltar."""
    a = _ingerir(pool, settings, user_a, b"<A> sin cerrar")
    b = _ingerir(pool, settings, user_a, b"<B> sin cerrar")
    sids = [a.contexto["source_document_id"], b.contexto["source_document_id"]]
    _fijar_llegada(admin_sql, user_a.company_id,
                   {s: "2026-09-13 12:00:00+00" for s in sids})

    completa = [str(i.row_id) for i in _leer(pool, settings, user_a, limit=100).items]
    assert completa == sorted(sids, reverse=True), "debe ordenar por id descendente"

    primera = _leer(pool, settings, user_a, limit=1)
    segunda = _leer(pool, settings, user_a, limit=1,
                    cursor=decode_cursor(primera.next_cursor))
    recorrido = [str(primera.items[0].row_id), str(segunda.items[0].row_id)]
    assert recorrido == completa


def test_recorrer_por_paginas_devuelve_exactamente_lo_mismo_que_una_sola(
    pool, settings, user_a, admin_sql, monkeypatch, limpio
):
    """La prueba de completitud: sin pérdidas y sin duplicados.

    Conjunto fijo con las dos clases de fila e instantes repetidos, recorrido
    de dos formas: una página grande, y página a página con `nextCursor`.
    """
    _sembrar_todos_los_estados(pool, settings, user_a, monkeypatch)
    _pendiente(pool, settings, user_a, monkeypatch)

    # Se colapsan los instantes en tres grupos para forzar empates reales
    # atravesando fronteras de página.
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        todos = [str(f["id"]) for f in conn.execute(
            "select id from fiscal.source_documents where company_id=%s order by id",
            (user_a.company_id,)).fetchall()]
    momentos = {sid: f"2026-09-13 1{i % 3}:00:00+00" for i, sid in enumerate(todos)}
    _fijar_llegada(admin_sql, user_a.company_id, momentos)

    de_una = [str(i.row_id) for i in _leer(pool, settings, user_a, limit=100).items]
    assert len(de_una) >= 9

    por_paginas: list[str] = []
    cursor = None
    for _ in range(50):                    # cota: nunca debe hacer falta tanto
        pagina = _leer(pool, settings, user_a, limit=2,
                       cursor=decode_cursor(cursor) if cursor else None)
        por_paginas.extend(str(i.row_id) for i in pagina.items)
        cursor = pagina.next_cursor
        if cursor is None:
            break
    else:
        raise AssertionError("la paginación no terminó")

    assert por_paginas == de_una, "el recorrido difiere del listado completo"
    assert len(set(por_paginas)) == len(por_paginas), "hay filas duplicadas"


def test_el_filtro_se_aplica_antes_de_dimensionar_la_pagina(
    pool, settings, user_a, admin_sql, monkeypatch, limpio
):
    """Un estado escaso entre muchos no produce páginas ralas."""
    _sembrar_todos_los_estados(pool, settings, user_a, monkeypatch)
    _pendiente(pool, settings, user_a, monkeypatch)
    # Dos inválidos más, para poder recorrer varias páginas filtradas.
    for carga in (b"<C> sin cerrar", b"<D> sin cerrar"):
        _ingerir(pool, settings, user_a, carga)

    esperados = {
        str(i.row_id) for i in _leer(pool, settings, user_a, limit=100).items
        if i.operational_status is OperationalStatus.INVALID_DOCUMENT
    }
    assert len(esperados) >= 3

    pagina = _leer(pool, settings, user_a, limit=2,
                   status=OperationalStatus.INVALID_DOCUMENT)
    assert len(pagina.items) == 2, "la página filtrada debe venir llena"
    assert all(i.operational_status is OperationalStatus.INVALID_DOCUMENT
               for i in pagina.items)

    recogidos = {str(i.row_id) for i in pagina.items}
    cursor = pagina.next_cursor
    while cursor:
        siguiente = _leer(pool, settings, user_a, limit=2,
                          status=OperationalStatus.INVALID_DOCUMENT,
                          cursor=decode_cursor(cursor))
        recogidos |= {str(i.row_id) for i in siguiente.items}
        cursor = siguiente.next_cursor
    assert recogidos == esperados


def test_los_contadores_no_cambian_entre_paginas_ni_con_filtro(
    pool, settings, user_a, monkeypatch, limpio
):
    """Son de TODA la empresa: la pregunta «¿tengo algo pendiente?»."""
    _sembrar_todos_los_estados(pool, settings, user_a, monkeypatch)
    _pendiente(pool, settings, user_a, monkeypatch)

    referencia = _leer(pool, settings, user_a, limit=100).counts
    # requires_attention(1) + invalid_document(3) + unrecognized(1)
    assert referencia.needs_attention == 5
    assert referencia.system_pending == 1

    primera = _leer(pool, settings, user_a, limit=2)
    segunda = _leer(pool, settings, user_a, limit=2,
                    cursor=decode_cursor(primera.next_cursor))
    assert primera.counts == referencia
    assert segunda.counts == referencia

    for estado in (OperationalStatus.PROCESSED, OperationalStatus.OUTSIDE_PIPELINE):
        assert _leer(pool, settings, user_a, limit=100, status=estado).counts == referencia


def test_los_limites_de_tribuu_no_suman_a_needs_attention(
    pool, settings, user_a, limpio
):
    """Una ND y un MH no piden nada al usuario."""
    nd_ns = ("https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.4/"
             "notaDebitoElectronica")
    _ingerir(pool, settings, user_a,
             f'<NotaDebitoElectronica xmlns="{nd_ns}"><Clave/></NotaDebitoElectronica>'.encode())
    _ingerir(pool, settings, user_a, _mh_bytes())

    pagina = _leer(pool, settings, user_a, limit=100)
    assert len(pagina.items) == 2
    assert pagina.counts.needs_attention == 0
    assert pagina.counts.system_pending == 0


def test_el_documento_toma_la_llegada_MAS_RECIENTE_de_sus_recepciones(
    pool, settings, user_a, admin_sql, limpio
):
    crudo = _bytes(FE)
    _ingerir(pool, settings, user_a, crudo)
    _ingerir(pool, settings, user_a, crudo)

    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        sids = [str(f["id"]) for f in conn.execute(
            "select id from fiscal.source_documents where company_id=%s order by ingested_at",
            (user_a.company_id,)).fetchall()]
    assert len(sids) == 2
    _fijar_llegada(admin_sql, user_a.company_id, {
        sids[0]: "2026-09-13 08:00:00+00",
        sids[1]: "2026-09-13 09:30:00+00",
    })

    pagina = _leer(pool, settings, user_a, limit=100)
    assert len(pagina.items) == 1
    assert pagina.items[0].receipt_count == 2
    assert pagina.items[0].received_at.isoformat().startswith("2026-09-13T09:30")


# ═════════════════════════════════════════════════════════════════════════════
# 7 · El endpoint HTTP
# ═════════════════════════════════════════════════════════════════════════════

def test_sin_token_es_401(client, user_a):
    r = client.get(f"/companies/{user_a.company_id}/fiscal-documents")
    assert r.status_code == 401


@pytest.mark.parametrize("cabecera", ["", "Bearer", "Token abc", "abc.def.ghi"])
def test_token_invalido_es_401(client, user_a, cabecera):
    r = client.get(f"/companies/{user_a.company_id}/fiscal-documents",
                   headers={"Authorization": cabecera})
    assert r.status_code == 401


@pytest.mark.parametrize("rol", ["owner", "editor", "viewer"])
def test_las_tres_funciones_leen_la_bandeja(client, user_a, as_role, rol, limpio):
    """La política `SELECT` solo comprueba pertenencia, no el rol.

    Es la diferencia con la escritura, que sí exige permiso: un `viewer` no
    puede subir pero sí ver lo que hay.
    """
    _ingerir_por_http = None  # la ingesta va por C2, no por HTTP
    as_role("owner")
    from app.config import get_settings
    from app.db import create_pool
    ajustes = get_settings()
    pool = create_pool(ajustes)
    try:
        _ingerir(pool, ajustes, user_a, _bytes(FE))
    finally:
        pool.close()

    as_role(rol)
    r = _get(client, user_a, user_a.company_id)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert len(cuerpo["items"]) == 1
    assert cuerpo["items"][0]["operational_status"] == "processed"


# ── no enumerabilidad ────────────────────────────────────────────────────────

_VACIO = {"items": [], "next_cursor": None,
          "counts": {"needs_attention": 0, "system_pending": 0}}


def test_un_no_miembro_recibe_200_vacio_no_403(client, user_a, user_b, limpio):
    """DECISIÓN EXPLÍCITA: la lectura no enumera empresas ajenas.

    Distinguir «no perteneces» de «no hay nada» convertiría el endpoint en un
    oráculo para descubrir qué empresas existen. No es relajar RLS: es RLS
    diciendo que no hay filas, y se devuelve tal cual.
    """
    r = _get(client, user_b, user_a.company_id)
    assert r.status_code == 200
    assert r.json() == _VACIO


def test_una_empresa_ajena_no_filtra_nada(client, user_a, user_b, pool, settings, limpio):
    _ingerir(pool, settings, user_a, _bytes(FE))
    r = _get(client, user_b, user_a.company_id)
    assert r.status_code == 200
    assert r.json() == _VACIO, "no debe verse ni un documento de otra empresa"


def test_la_empresa_propia_vacia_es_INDISTINGUIBLE_de_la_ajena(
    client, user_a, user_b, limpio
):
    """La propiedad que sostiene la no enumerabilidad."""
    propia_vacia = _get(client, user_a, user_a.company_id)
    ajena = _get(client, user_b, user_a.company_id)
    inventada = _get(client, user_a, "00000000-0000-4000-8000-000000000000")

    assert propia_vacia.status_code == ajena.status_code == inventada.status_code == 200
    assert propia_vacia.json() == ajena.json() == inventada.json() == _VACIO


def test_el_get_no_promete_403(client):
    from app.main import app as aplicacion

    get = aplicacion.openapi()["paths"][
        "/companies/{company_id}/fiscal-documents"]["get"]
    assert "403" not in get["responses"], "un 403 que no ocurre es un contrato falso"
    assert sorted(get["responses"]) == ["200", "401", "422", "500", "503"]


def test_el_post_conserva_su_403(client):
    from app.main import app as aplicacion

    post = aplicacion.openapi()["paths"][
        "/companies/{company_id}/fiscal-documents"]["post"]
    assert "403" in post["responses"], "la escritura sí niega, y debe decirlo"


# ── parámetros de consulta ───────────────────────────────────────────────────

def test_un_company_id_que_no_es_uuid_usa_el_contrato_estable(client, user_a):
    r = client.get("/companies/no-es-uuid/fiscal-documents",
                   headers={"Authorization": f"Bearer {user_a.token}"})
    assert r.status_code == 422
    cuerpo = r.json()
    assert "detail" not in cuerpo
    assert cuerpo["code"] == "invalid_request"


@pytest.mark.parametrize("valor", ["1", "25", "100"])
def test_limites_validos(client, user_a, valor, limpio):
    r = _get(client, user_a, user_a.company_id, limit=valor)
    assert r.status_code == 200


@pytest.mark.parametrize(
    "valor", ["abc", "1.5", "0", "-1", "101", "1e2", " 5", "", "٣", "1,5"]
)
def test_un_limite_invalido_usa_el_contrato_estable(client, user_a, valor):
    """Nunca el `{"detail": [...]}` de FastAPI."""
    r = _get(client, user_a, user_a.company_id, limit=valor)
    assert r.status_code == 422, f"{valor!r} devolvió {r.status_code}"
    cuerpo = r.json()
    assert "detail" not in cuerpo, f"{valor!r} cayó en la validación del framework"
    assert cuerpo["code"] == "invalid_query"
    assert cuerpo["category"] == "invalid_request"


def test_un_estado_desconocido_usa_el_contrato_estable(client, user_a):
    r = _get(client, user_a, user_a.company_id, status="del_futuro")
    assert r.status_code == 422
    assert r.json()["code"] == "invalid_query"
    assert "detail" not in r.json()


@pytest.mark.parametrize(
    "cursor", ["%%%", "no-canonico==", "eyJ2IjoxfQ", "  ", "abc def"]
)
def test_un_cursor_invalido_usa_el_contrato_estable(client, user_a, cursor):
    r = _get(client, user_a, user_a.company_id, cursor=cursor)
    assert r.status_code == 422
    assert r.json()["code"] == "invalid_query"


@pytest.mark.parametrize("estado", [e.value for e in OperationalStatus])
def test_todos_los_estados_son_filtros_validos(client, user_a, estado, limpio):
    r = _get(client, user_a, user_a.company_id, status=estado)
    assert r.status_code == 200


# ── serialización exacta ─────────────────────────────────────────────────────

def test_el_importe_llega_como_cadena_exacta(client, user_a, pool, settings, limpio):
    """Un decimal fiscal en coma flotante binaria es un importe distinto."""
    from decimal import Decimal

    _ingerir(pool, settings, user_a, _bytes(FE))
    r = _get(client, user_a, user_a.company_id)
    assert r.status_code == 200
    item = r.json()["items"][0]

    total = item["reported_total_document"]
    assert isinstance(total, str), "un número aquí ya habría perdido precisión"
    # Coincide con el decimal guardado, dígito a dígito.
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        guardado = conn.execute(
            "select reported_total_document from fiscal.electronic_documents "
            "where company_id=%s", (user_a.company_id,)).fetchone()
    assert Decimal(total) == guardado["reported_total_document"]
    assert total == str(guardado["reported_total_document"])
    # Y el texto crudo de la respuesta no lo envuelve en comillas numéricas.
    assert f'"reported_total_document":"{total}"' in r.text.replace(" ", "")


def test_la_fecha_de_emision_conserva_el_reloj_de_pared(
    client, user_a, pool, settings, limpio
):
    """ADR-039: no se reinterpreta en otro huso ni se inventa desplazamiento."""
    _ingerir(pool, settings, user_a, _bytes(FE))
    item = _get(client, user_a, user_a.company_id).json()["items"][0]

    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        fila = conn.execute(
            "select issued_at_local, issued_at_offset_minutes "
            "from fiscal.electronic_documents where company_id=%s",
            (user_a.company_id,)).fetchone()
    assert item["issued_at_local"] == fila["issued_at_local"].isoformat()
    assert item["issued_at_offset_minutes"] == fila["issued_at_offset_minutes"]


# ── privacidad ───────────────────────────────────────────────────────────────

_FUGAS = ("raw_xml", "postgres", "psycopg", "sql", "constraint", "traceback",
          "select ", "base64", "binascii", "lxml", "bearer")


@pytest.mark.parametrize(
    ("nombre", "params"),
    [
        ("límite inválido", {"limit": "abc"}),
        ("estado inválido", {"status": "inventado"}),
        ("cursor inválido", {"cursor": "%%%"}),
    ],
)
def test_ninguna_respuesta_de_error_filtra_diagnostico(
    client, user_a, nombre, params
):
    r = _get(client, user_a, user_a.company_id, **params)
    bajo = r.text.lower()
    for fuga in _FUGAS:
        assert fuga not in bajo, f"{nombre} filtró {fuga!r}"


def test_la_lectura_no_devuelve_el_xml_ni_el_error_tecnico(
    client, user_a, pool, settings, limpio
):
    crudo = _bytes(FE)
    _ingerir(pool, settings, user_a, crudo)
    _ingerir(pool, settings, user_a, _xsd_invalido())

    r = _get(client, user_a, user_a.company_id)
    assert r.status_code == 200
    bajo = r.text.lower()
    for fuga in _FUGAS:
        assert fuga not in bajo, f"la lista filtró {fuga!r}"
    # Ni la Clave del contribuyente, ni el texto del error de parseo.
    assert "parse_error" not in r.text
    assert "xsd_validation_error" not in r.text
