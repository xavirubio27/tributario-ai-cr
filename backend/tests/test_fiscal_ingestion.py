"""Ingesta fiscal (C2-B) — contra PostgreSQL real.

Dos invariantes gobiernan todo lo de aquí:

1. **La evidencia sobrevive.** Una vez comiteada la captura, ningún fallo
   posterior puede borrarla.
2. **La autorización es de PostgreSQL.** Nada consulta `company_memberships`
   ni reproduce roles en Python.
"""

from __future__ import annotations

import hashlib
import threading
import time
from pathlib import Path

import psycopg
import pytest
from lxml import etree

from app.db import fiscal_transaction
from app.fiscal.errors import (
    ClaveConflict,
    DocumentDetection,
    EmptySourceDocument,
    FiscalWriteForbidden,
    MalformedXML,
    PersistenceDatabaseError,
    PersistenceMappingError,
    PersistenceUnavailable,
    SemanticParseError,
    SourceDocumentNotFound,
    SourceDocumentTooLarge,
    UnsupportedDocument,
    UnsupportedDocumentReason,
    ValidatorConfigurationError,
    XSDValidationError,
)
from app.fiscal.ingestion import (
    MAX_SOURCE_XML_BYTES,
    IngestionResult,
    IngestionSource,
    ProcessingFailureKind,
    ProcessingStatus,
    capture_source_document,
    ingest_fiscal_xml,
    process_source_document,
)

FIXTURES = Path(__file__).parent / "fixtures" / "fiscal" / "real" / "v4_4"

FE = "50601082600310161019803900001010004596121100"
TE = "Comprobante_Electronico_50630062600310174582"
NC = "NC-50631082600310181576400100001030000001522"


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


def _capturar(pool, settings, user, company_id, datos,
              fuente=IngestionSource.API):
    with fiscal_transaction(pool, settings, user.identity) as conn:
        return capture_source_document(
            conn, company_id=company_id, raw_xml=datos, ingestion_source=fuente
        )


def _procesar(pool, settings, user, company_id, source_id):
    with fiscal_transaction(pool, settings, user.identity) as conn:
        return process_source_document(
            conn, company_id=company_id, source_document_id=source_id
        )


def _leer(pool, settings, user, source_id):
    with fiscal_transaction(pool, settings, user.identity) as conn:
        return conn.execute(
            "select * from fiscal.source_documents where id=%s", (source_id,)
        ).fetchone()


# ═════════════════════════════════════════════════════════════════════════════
# 1 · Autorización de la captura — puerta dura verificada contra RLS real
#
# Medido: la política `INSERT` usa `WITH CHECK`, que **sí lanza** `42501` en
# vez de filtrar en silencio. Por eso la captura puede distinguir «no puedes»
# sin consultar pertenencias en Python.
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("rol", ["owner", "editor"])
def test_owner_y_editor_capturan(pool, settings, user_a, as_role, rol, limpio):
    as_role(rol)
    r = _capturar(pool, settings, user_a, user_a.company_id, _bytes(FE))
    assert r.source_document_id
    assert r.content_sha256 == hashlib.sha256(_bytes(FE)).hexdigest()


def test_el_viewer_no_puede_capturar(pool, settings, user_a, as_role, limpio):
    as_role("viewer")
    with pytest.raises(FiscalWriteForbidden) as exc:
        _capturar(pool, settings, user_a, user_a.company_id, _bytes(FE))
    assert exc.value.code == "fiscal_write_forbidden"
    assert exc.value.__cause__ is None and exc.value.__context__ is None


def test_un_no_miembro_no_puede_capturar(pool, settings, user_a, user_b, limpio):
    with pytest.raises(FiscalWriteForbidden):
        _capturar(pool, settings, user_b, user_a.company_id, _bytes(FE))


def test_no_se_puede_capturar_en_empresa_ajena(pool, settings, user_a, user_b, limpio):
    with pytest.raises(FiscalWriteForbidden):
        _capturar(pool, settings, user_a, user_b.company_id, _bytes(FE))


def _sqlstate_de_insert_directo(pool, settings, user, company_id, datos):
    """SQLSTATE que devuelve PostgreSQL al INSERT crudo, sin la traducción de
    la ingesta. Es la puerta dura observada en su propio nivel."""
    huella = hashlib.sha256(datos).digest()
    try:
        with fiscal_transaction(pool, settings, user.identity) as conn:
            conn.execute(
                "insert into fiscal.source_documents "
                "(company_id, raw_xml, content_sha256, ingestion_source) "
                "values (%s, %s, %s, %s)",
                (company_id, datos, huella, "api"),
            )
    except psycopg.Error as exc:
        return exc.sqlstate
    return None


def test_sqlstate_real_de_la_puerta_de_captura(
    pool, settings, user_a, user_b, as_role, limpio
):
    """La política `INSERT` usa `WITH CHECK`: LANZA, no filtra.

    Es la diferencia que hace innecesario duplicar la autorización en Python.
    Se comprueba en el nivel de SQL para que el dato quede medido y no
    heredado de un comentario.
    """
    crudo = _bytes(FE)

    as_role("owner")
    assert _sqlstate_de_insert_directo(
        pool, settings, user_a, user_a.company_id, crudo) is None

    as_role("viewer")
    assert _sqlstate_de_insert_directo(
        pool, settings, user_a, user_a.company_id, crudo) == "42501"

    as_role("owner")
    # No miembro: `user_b` contra la empresa de `user_a`.
    assert _sqlstate_de_insert_directo(
        pool, settings, user_b, user_a.company_id, crudo) == "42501"
    # Cruce de empresas: `user_a` contra la empresa de `user_b`.
    assert _sqlstate_de_insert_directo(
        pool, settings, user_a, user_b.company_id, crudo) == "42501"


def test_la_ingesta_no_consulta_pertenencias():
    """La autorización sigue siendo de RLS."""
    import ast
    from app.fiscal import ingestion

    arbol = ast.parse(Path(ingestion.__file__).read_text(encoding="utf-8"))
    docstrings = {
        n.body[0].value for n in ast.walk(arbol)
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef))
        and n.body and isinstance(n.body[0], ast.Expr)
        and isinstance(n.body[0].value, ast.Constant)
    }
    sql = [n.value for n in ast.walk(arbol)
           if isinstance(n, ast.Constant) and isinstance(n.value, str)
           and n not in docstrings
           and any(v in n.value.lower() for v in ("select ", "insert ", "update "))]
    assert sql
    for s in sql:
        for prohibido in ("company_memberships", "is_company_member",
                          "can_write_company", "service_role"):
            assert prohibido not in s.lower()


# ═════════════════════════════════════════════════════════════════════════════
# 2 · Fidelidad de la evidencia
# ═════════════════════════════════════════════════════════════════════════════

def test_los_bytes_se_guardan_exactos(pool, settings, user_a, limpio):
    crudo = _bytes(FE)
    r = _capturar(pool, settings, user_a, user_a.company_id, crudo,
                  IngestionSource.MANUAL_UPLOAD)
    fila = _leer(pool, settings, user_a, r.source_document_id)

    assert bytes(fila["raw_xml"]) == crudo, "los bytes se alteraron"
    assert bytes(fila["content_sha256"]) == hashlib.sha256(crudo).digest()
    assert fila["ingestion_source"] == "manual_upload"
    # Defaults de la base, no escritos por la captura.
    assert fila["parse_status"] == "pending"
    assert fila["schema_detection_status"] == "pending"
    assert fila["parse_attempt_count"] == 0
    assert fila["parse_error"] is None
    assert fila["electronic_document_id"] is None


def test_la_misma_evidencia_se_puede_capturar_dos_veces(
    pool, settings, user_a, limpio
):
    """Dos recepciones son dos hechos. Deduplicar es de C1 (ADR-031)."""
    crudo = _bytes(FE)
    a = _capturar(pool, settings, user_a, user_a.company_id, crudo)
    b = _capturar(pool, settings, user_a, user_a.company_id, crudo)

    assert a.source_document_id != b.source_document_id
    assert a.content_sha256 == b.content_sha256
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        n = conn.execute(
            "select count(*) as n from fiscal.source_documents where company_id=%s",
            (user_a.company_id,)).fetchone()["n"]
    assert n == 2


# ═════════════════════════════════════════════════════════════════════════════
# 3 · Límites de la frontera de dominio
# ═════════════════════════════════════════════════════════════════════════════

def test_la_evidencia_vacia_se_rechaza(pool, settings, user_a, limpio):
    with pytest.raises(EmptySourceDocument) as exc:
        _capturar(pool, settings, user_a, user_a.company_id, b"")
    assert exc.value.code == "empty_source_document"
    assert exc.value.__cause__ is None and exc.value.__context__ is None
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        assert conn.execute(
            "select count(*) as n from fiscal.source_documents where company_id=%s",
            (user_a.company_id,)).fetchone()["n"] == 0


def test_un_artefacto_demasiado_grande_se_rechaza(pool, settings, user_a, limpio):
    with pytest.raises(SourceDocumentTooLarge) as exc:
        _capturar(pool, settings, user_a, user_a.company_id,
                  b"x" * (MAX_SOURCE_XML_BYTES + 1))
    assert exc.value.code == "source_document_too_large"
    assert exc.value.__cause__ is None and exc.value.__context__ is None
    # Ninguna fila: se rechaza ANTES de tocar la base.
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        assert conn.execute(
            "select count(*) as n from fiscal.source_documents where company_id=%s",
            (user_a.company_id,)).fetchone()["n"] == 0


def test_el_tamano_justo_en_el_limite_se_acepta(pool, settings, user_a, limpio):
    """El límite es inclusivo: se rechaza a partir de MAX+1."""
    from app.fiscal.ingestion import _validar_entrada

    _validar_entrada(b"x" * MAX_SOURCE_XML_BYTES)     # no lanza
    with pytest.raises(SourceDocumentTooLarge):
        _validar_entrada(b"x" * (MAX_SOURCE_XML_BYTES + 1))


# ═════════════════════════════════════════════════════════════════════════════
# 4 · Autorización del procesamiento — antes de cualquier parseo
# ═════════════════════════════════════════════════════════════════════════════

def test_el_viewer_no_provoca_parseo(pool, settings, user_a, as_role,
                                     monkeypatch, limpio):
    """La puerta va antes de leer el XML: un `viewer` no puede hacernos gastar
    trabajo de parseo."""
    from app.fiscal import ingestion

    as_role("owner")
    r = _capturar(pool, settings, user_a, user_a.company_id, _bytes(FE))

    llamadas = {"n": 0}
    original = ingestion.parse_fiscal_document

    def _contando(datos):
        llamadas["n"] += 1
        return original(datos)

    monkeypatch.setattr(ingestion, "parse_fiscal_document", _contando)

    as_role("viewer")
    with pytest.raises(FiscalWriteForbidden):
        _procesar(pool, settings, user_a, user_a.company_id, r.source_document_id)
    assert llamadas["n"] == 0, "el viewer provocó trabajo de parseo"


def test_un_no_miembro_no_enumera_al_procesar(pool, settings, user_a, user_b, limpio):
    r = _capturar(pool, settings, user_a, user_a.company_id, _bytes(FE))
    with pytest.raises(SourceDocumentNotFound):
        _procesar(pool, settings, user_b, user_a.company_id, r.source_document_id)


def test_el_viewer_es_rechazado_aunque_ya_estuviera_enlazado(
    pool, settings, user_a, as_role, limpio
):
    as_role("owner")
    resultado = ingest_fiscal_xml(
        pool, settings, user_a.identity, company_id=user_a.company_id,
        raw_xml=_bytes(FE), ingestion_source=IngestionSource.API,
    )
    as_role("viewer")
    with pytest.raises(FiscalWriteForbidden):
        _procesar(pool, settings, user_a, user_a.company_id,
                  resultado.source_document_id)


# ═════════════════════════════════════════════════════════════════════════════
# 5 · Comprobantes reales de extremo a extremo
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize(
    ("prefijo", "tipo", "refs"),
    [(FE, "invoice", 0), (TE, "ticket", 0), (NC, "credit_note", 1)],
    ids=["FE", "TE", "NC"],
)
def test_ingesta_completa_de_un_comprobante_real(
    prefijo, tipo, refs, pool, settings, user_a, limpio
):
    crudo = _bytes(prefijo)
    resultado = ingest_fiscal_xml(
        pool, settings, user_a.identity, company_id=user_a.company_id,
        raw_xml=crudo, ingestion_source=IngestionSource.MANUAL_UPLOAD,
    )

    assert isinstance(resultado, IngestionResult)
    assert resultado.status is ProcessingStatus.CREATED

    fila = _leer(pool, settings, user_a, resultado.source_document_id)
    assert bytes(fila["raw_xml"]) == crudo
    assert fila["parse_status"] == "parsed"
    assert fila["parse_error"] is None
    assert fila["schema_detection_status"] == "detected"
    assert fila["detected_document_type"] == tipo
    assert fila["detected_schema_version"] == "4.4"
    assert fila["parse_attempt_count"] == 1
    assert fila["parse_attempted_at"] is not None
    assert str(fila["electronic_document_id"]) == resultado.electronic_document_id

    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        doc = conn.execute(
            "select document_type from fiscal.electronic_documents where id=%s",
            (resultado.electronic_document_id,)).fetchone()
        n_refs = conn.execute(
            "select count(*) as n from fiscal.document_references "
            "where electronic_document_id=%s",
            (resultado.electronic_document_id,)).fetchone()["n"]
        sin_resolver = conn.execute(
            "select count(*) as n from fiscal.document_references "
            "where electronic_document_id=%s and resolved_document_id is null",
            (resultado.electronic_document_id,)).fetchone()["n"]
    assert doc["document_type"] == tipo
    assert n_refs == refs
    assert sin_resolver == refs, "C2 no debe resolver referencias"


# ═════════════════════════════════════════════════════════════════════════════
# 6 · Enrutado: lo que no se procesa, y por qué
# ═════════════════════════════════════════════════════════════════════════════

def _estado_tras_fallo(pool, settings, user_a, crudo, excepcion):
    r = _capturar(pool, settings, user_a, user_a.company_id, crudo)
    with pytest.raises(excepcion) as exc:
        veredicto = _procesar(pool, settings, user_a, user_a.company_id,
                              r.source_document_id)
        # el primitivo devuelve veredicto; el orquestador es quien lanza
        from app.fiscal.ingestion import _excepcion_de
        if veredicto.failure:
            raise _excepcion_de(veredicto.failure, veredicto.source_document_id)
    return r.source_document_id, exc.value, _leer(
        pool, settings, user_a, r.source_document_id)


def test_xml_mal_formado(pool, settings, user_a, limpio):
    sid, err, fila = _estado_tras_fallo(
        pool, settings, user_a, b"<FacturaElectronica> sin cerrar", MalformedXML)
    assert fila["parse_status"] == "failed"
    assert fila["schema_detection_status"] == "failed"
    assert fila["parse_error"] == "malformed_xml"
    assert fila["detected_document_type"] is None
    assert fila["detected_schema_version"] is None
    assert fila["parse_attempt_count"] == 1
    assert fila["electronic_document_id"] is None
    assert bytes(fila["raw_xml"]) == b"<FacturaElectronica> sin cerrar"
    assert err.__cause__ is None and err.__context__ is None


def test_doctype(pool, settings, user_a, limpio):
    crudo = b'<!DOCTYPE r [<!ENTITY e "x">]>\n<r/>'
    _sid, _err, fila = _estado_tras_fallo(
        pool, settings, user_a, crudo, MalformedXML)
    assert fila["parse_status"] == "failed"
    assert fila["parse_error"] == "malformed_xml"
    assert bytes(fila["raw_xml"]) == crudo, "la evidencia sobrevive"


def test_raiz_desconocida(pool, settings, user_a, limpio):
    _sid, err, fila = _estado_tras_fallo(
        pool, settings, user_a,
        b'<Cualquiera xmlns="urn:ejemplo:desconocido"><a/></Cualquiera>',
        UnsupportedDocument)
    assert err.reason is UnsupportedDocumentReason.UNKNOWN_DOCUMENT
    assert fila["schema_detection_status"] == "unknown"
    assert fila["parse_error"] == "unsupported_document"
    assert fila["detected_document_type"] is None
    assert fila["detected_schema_version"] is None
    assert err.__cause__ is None and err.__context__ is None


def test_mensaje_hacienda_queda_fuera_del_pipeline(pool, settings, user_a, limpio):
    """El MH real del corpus: se identifica, no se normaliza."""
    _sid, err, fila = _estado_tras_fallo(
        pool, settings, user_a, _mh_bytes(), UnsupportedDocument)
    assert err.reason is UnsupportedDocumentReason.OUTSIDE_PIPELINE
    assert fila["parse_status"] == "failed"
    assert fila["schema_detection_status"] == "unsupported"
    assert fila["detected_document_type"] == "hacienda_message"
    assert fila["detected_schema_version"] == "4.4"
    assert err.__cause__ is None and err.__context__ is None
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        assert conn.execute(
            "select count(*) as n from fiscal.electronic_documents where company_id=%s",
            (user_a.company_id,)).fetchone()["n"] == 0


def test_nota_de_debito_reconocida_sin_soporte(pool, settings, user_a, limpio):
    """Se construye en memoria a partir del esquema oficial: el corpus no trae
    una ND real, y fabricar un comprobante de aspecto auténtico sería fingir
    cobertura. Basta la raíz correcta para llegar a la ruta de enrutado."""
    ns = ("https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.4/"
          "notaDebitoElectronica")
    crudo = f'<NotaDebitoElectronica xmlns="{ns}"><Clave/></NotaDebitoElectronica>'.encode()
    _sid, err, fila = _estado_tras_fallo(
        pool, settings, user_a, crudo, UnsupportedDocument)
    assert err.reason is UnsupportedDocumentReason.UNSUPPORTED_TYPE
    assert fila["schema_detection_status"] == "unsupported"
    assert fila["detected_document_type"] == "debit_note"
    assert fila["detected_schema_version"] == "4.4"
    assert err.__cause__ is None and err.__context__ is None


def test_xml_invalido_contra_el_xsd(pool, settings, user_a, limpio):
    """El esquema SÍ se detecta; la instancia no es conforme."""
    arbol = etree.fromstring(_bytes(FE))
    ns = arbol.tag[1:].split("}")[0]
    arbol.find(f"{{{ns}}}Clave").text = "NO-ES-UNA-CLAVE"
    _sid, err, fila = _estado_tras_fallo(
        pool, settings, user_a, etree.tostring(arbol), XSDValidationError)
    assert fila["parse_status"] == "failed"
    assert fila["schema_detection_status"] == "detected"
    assert fila["parse_error"] == "xsd_validation_error"
    assert fila["detected_document_type"] == "invoice"
    assert fila["detected_schema_version"] == "4.4"
    publico = f"{err!s} {err!r}"
    assert "NO-ES-UNA-CLAVE" not in publico
    assert err.__cause__ is None and err.__context__ is None


def test_el_fallo_semantico_se_mapea_por_inyeccion(
    pool, settings, user_a, monkeypatch, limpio
):
    """`SemanticParseError` NO es alcanzable hoy por la vía pública.

    Sus dos puntos de partida posteriores al XSD —`Emisor` y `ResumenFactura`
    ausentes— los ataja antes el propio esquema: quitando cualquiera de los
    dos de un FE real, el parser devuelve `XSDValidationError`. Son ramas
    defensivas, no un desenlace que un comprobante pueda provocar.

    Fabricar un XML que simulara ese fallo sería fingir cobertura. Lo que sí
    tiene que estar probado es que la INGESTA lo mapea bien si algún día el
    parser lo levanta, así que se inyecta en la frontera del módulo — igual
    que se hace con los fallos de infraestructura.
    """
    from app.fiscal import ingestion

    r = _capturar(pool, settings, user_a, user_a.company_id, _bytes(FE))
    deteccion = DocumentDetection(document_type="invoice", schema_version="4.4")

    def _semantico(*a, **k):
        raise SemanticParseError(
            "fallo semántico inyectado", detection=deteccion, campo="Emisor"
        )

    monkeypatch.setattr(ingestion, "parse_fiscal_document", _semantico)

    veredicto = _procesar(pool, settings, user_a, user_a.company_id,
                          r.source_document_id)
    assert veredicto.status is None
    assert veredicto.failure is not None
    assert veredicto.failure.kind is ProcessingFailureKind.SEMANTIC_PARSE
    assert not isinstance(veredicto.failure, BaseException), (
        "el veredicto no puede transportar una excepción con traza")

    # El estado durable corresponde al mapeo aprobado: el esquema SÍ se
    # detectó, lo que falló fue interpretarlo.
    fila = _leer(pool, settings, user_a, r.source_document_id)
    assert fila["parse_status"] == "failed"
    assert fila["schema_detection_status"] == "detected"
    assert fila["parse_error"] == "semantic_parse_error"
    assert fila["detected_document_type"] == "invoice"
    assert fila["detected_schema_version"] == "4.4"
    assert fila["parse_attempt_count"] == 1
    assert fila["electronic_document_id"] is None
    assert bytes(fila["raw_xml"]) == _bytes(FE), "la evidencia intacta"

    # El error que sale del orquestador nace después del commit: sin cadena y
    # sin el `campo` del diagnóstico interno.
    err = ingestion._excepcion_de(veredicto.failure, veredicto.source_document_id)
    assert isinstance(err, SemanticParseError)
    assert err.__cause__ is None and err.__context__ is None
    assert "Emisor" not in f"{err!s} {err!r}"



# ═════════════════════════════════════════════════════════════════════════════
# 7 · Duplicados y conflicto de clave, extremo a extremo
# ═════════════════════════════════════════════════════════════════════════════

def test_el_mismo_xml_ingerido_dos_veces(pool, settings, user_a, limpio):
    crudo = _bytes(FE)
    kw = dict(company_id=user_a.company_id, raw_xml=crudo,
              ingestion_source=IngestionSource.API)
    primero = ingest_fiscal_xml(pool, settings, user_a.identity, **kw)
    segundo = ingest_fiscal_xml(pool, settings, user_a.identity, **kw)

    assert primero.status is ProcessingStatus.CREATED
    assert segundo.status is ProcessingStatus.LINKED_EXISTING
    assert primero.electronic_document_id == segundo.electronic_document_id
    assert primero.source_document_id != segundo.source_document_id

    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        n_doc = conn.execute(
            "select count(*) as n from fiscal.electronic_documents where company_id=%s",
            (user_a.company_id,)).fetchone()["n"]
        fuentes = conn.execute(
            "select parse_status, electronic_document_id "
            "from fiscal.source_documents where company_id=%s",
            (user_a.company_id,)).fetchall()
    assert n_doc == 1, "no debe duplicarse el documento normalizado"
    assert len(fuentes) == 2, "ambas evidencias se conservan"
    assert all(f["parse_status"] == "parsed" for f in fuentes)
    assert all(f["electronic_document_id"] is not None for f in fuentes)


def test_misma_clave_huella_distinta_conserva_el_estado_de_parseo(
    pool, settings, user_a, limpio
):
    """CIERRE CRÍTICO. El parseo funcionó; la persistencia no pudo establecer
    equivalencia. Esa verdad debe quedar comiteada ANTES de que el llamante
    reciba el conflicto, y se comprueba desde otra transacción."""
    crudo = _bytes(FE)
    variante = crudo + b"\n<!-- otra serializacion del mismo comprobante -->"

    primero = ingest_fiscal_xml(
        pool, settings, user_a.identity, company_id=user_a.company_id,
        raw_xml=crudo, ingestion_source=IngestionSource.API)
    assert primero.status is ProcessingStatus.CREATED

    with pytest.raises(ClaveConflict) as exc:
        ingest_fiscal_xml(
            pool, settings, user_a.identity, company_id=user_a.company_id,
            raw_xml=variante, ingestion_source=IngestionSource.API)

    assert exc.value.contexto.get("source_document_id"), (
        "el llamante debe poder identificar la evidencia conservada"
    )
    segundo_id = exc.value.contexto["source_document_id"]
    assert exc.value.__cause__ is None and exc.value.__context__ is None

    # Estado leído desde OTRA transacción: prueba de durabilidad real.
    fila = _leer(pool, settings, user_a, segundo_id)
    assert fila is not None, "la evidencia debe sobrevivir al conflicto"
    assert bytes(fila["raw_xml"]) == variante
    assert fila["parse_status"] == "parsed", "el parseo SÍ funcionó"
    assert fila["parse_error"] is None, "un conflicto no es un error de parseo"
    assert fila["schema_detection_status"] == "detected"
    assert fila["detected_document_type"] == "invoice"
    assert fila["parse_attempt_count"] == 1
    assert fila["electronic_document_id"] is None

    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        assert conn.execute(
            "select count(*) as n from fiscal.electronic_documents where company_id=%s",
            (user_a.company_id,)).fetchone()["n"] == 1


def test_reprocesar_el_mismo_artefacto_no_reparsea(
    pool, settings, user_a, monkeypatch, limpio
):
    from app.fiscal import ingestion

    resultado = ingest_fiscal_xml(
        pool, settings, user_a.identity, company_id=user_a.company_id,
        raw_xml=_bytes(FE), ingestion_source=IngestionSource.API)
    antes = _leer(pool, settings, user_a, resultado.source_document_id)

    llamadas = {"n": 0}
    original = ingestion.parse_fiscal_document
    monkeypatch.setattr(
        ingestion, "parse_fiscal_document",
        lambda d: (llamadas.__setitem__("n", llamadas["n"] + 1), original(d))[1])

    veredicto = _procesar(pool, settings, user_a, user_a.company_id,
                          resultado.source_document_id)

    assert veredicto.status is ProcessingStatus.ALREADY_PERSISTED
    assert llamadas["n"] == 0, "no debe reparsear un artefacto ya normalizado"
    despues = _leer(pool, settings, user_a, resultado.source_document_id)
    assert despues["parse_attempt_count"] == antes["parse_attempt_count"]
    assert despues["parse_attempted_at"] == antes["parse_attempted_at"]
    assert despues["parse_status"] == antes["parse_status"]


def test_el_contador_de_intentos_avanza_solo_en_intentos_durables(
    pool, settings, user_a, limpio
):
    r = _capturar(pool, settings, user_a, user_a.company_id, b"<roto")
    for esperado in (1, 2):
        veredicto = _procesar(pool, settings, user_a, user_a.company_id,
                              r.source_document_id)
        assert veredicto.failure is not None
        fila = _leer(pool, settings, user_a, r.source_document_id)
        assert fila["parse_attempt_count"] == esperado


# ═════════════════════════════════════════════════════════════════════════════
# 8 · Fallos que NO son del documento: T2 revierte
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize(
    ("objetivo", "excepcion"),
    [
        ("parse_fiscal_document", ValidatorConfigurationError),
        ("persist_parsed_fiscal_document", PersistenceUnavailable),
    ],
    ids=["validador_mal_configurado", "persistencia_no_disponible"],
)
def test_un_fallo_nuestro_no_marca_el_documento_como_fallido(
    objetivo, excepcion, pool, settings, user_a, monkeypatch, limpio
):
    """Ni el paquete de esquemas roto ni la base caída son culpa del
    contribuyente: T2 revierte y el artefacto conserva su estado previo."""
    from app.fiscal import ingestion

    r = _capturar(pool, settings, user_a, user_a.company_id, _bytes(FE))
    antes = _leer(pool, settings, user_a, r.source_document_id)

    def _revienta(*a, **k):
        raise excepcion("fallo inyectado")

    monkeypatch.setattr(ingestion, objetivo, _revienta)

    with pytest.raises(excepcion):
        _procesar(pool, settings, user_a, user_a.company_id, r.source_document_id)

    despues = _leer(pool, settings, user_a, r.source_document_id)
    assert despues is not None, "la evidencia de T1 debe sobrevivir"
    assert despues["parse_status"] == antes["parse_status"] == "pending"
    assert despues["parse_error"] is None
    assert despues["parse_attempt_count"] == 0, "sin incremento durable"
    assert despues["electronic_document_id"] is None


def test_un_defecto_de_programacion_no_culpa_al_documento(
    pool, settings, user_a, monkeypatch, limpio
):
    from app.fiscal import ingestion

    r = _capturar(pool, settings, user_a, user_a.company_id, _bytes(FE))

    def _bug(*a, **k):
        raise RuntimeError("defecto de programación simulado")

    monkeypatch.setattr(ingestion, "parse_fiscal_document", _bug)

    with pytest.raises(RuntimeError):
        _procesar(pool, settings, user_a, user_a.company_id, r.source_document_id)

    fila = _leer(pool, settings, user_a, r.source_document_id)
    assert fila["parse_status"] == "pending", "no se marca fallido por un bug nuestro"
    assert fila["parse_error"] is None
    assert fila["parse_attempt_count"] == 0


# ═════════════════════════════════════════════════════════════════════════════
# 9 · Concurrencia sobre el mismo artefacto
# ═════════════════════════════════════════════════════════════════════════════

def test_la_contencion_real_serializa_el_parseo_del_mismo_artefacto(
    pool, settings, user_a, monkeypatch, limpio
):
    """El segundo proceso ESPERA al lock de fila del primero. Probado por
    PostgreSQL, no inferido del desenlace.

    La versión anterior sincronizaba solo el ARRANQUE de los dos hilos con una
    barrera, así que una planificación serie —A entero y luego B— producía el
    mismo resultado final sin que hubiera habido contención. `CREATED` +
    `ALREADY_PERSISTED` y un solo parseo son necesarios, pero no demuestran que
    B se bloqueara.

    Aquí se retiene a A **dentro** de su transacción y se le pide a PostgreSQL
    que confirme el bloqueo: `pg_blocking_pids(B)` debe contener el PID de A.

    El punto de retención es el parser, y eso es exacto porque el orden de
    producción es `SELECT` → `SELECT ... FOR UPDATE` → atajo de enlace →
    parser: llegar al parser implica que el `FOR UPDATE` YA se concedió y que
    la transacción sigue abierta.
    """
    from app.fiscal import ingestion

    PLAZO = 60          # todo bloqueo del arnés está acotado
    r = _capturar(pool, settings, user_a, user_a.company_id, _bytes(FE))

    parser_real = ingestion.parse_fiscal_document
    llamadas: list[str] = []
    candado = threading.Lock()
    a_tiene_el_lock = threading.Event()
    soltar_a = threading.Event()

    def _parser_coordinado(datos):
        with candado:
            llamadas.append(threading.current_thread().name)
            primera = len(llamadas) == 1
        if primera:
            # Solo el PRIMER hilo que llega retiene: B no debería llegar nunca,
            # y si llegara no debe quedarse colgado aquí -- lo delata el conteo.
            a_tiene_el_lock.set()
            assert soltar_a.wait(timeout=PLAZO), "el arnés no liberó a A a tiempo"
        return parser_real(datos)          # semántica real, no un resultado falso

    monkeypatch.setattr(ingestion, "parse_fiscal_document", _parser_coordinado)

    pids: dict[str, int] = {}
    salidas: dict[str, object] = {}

    def _worker(nombre: str):
        try:
            with fiscal_transaction(pool, settings, user_a.identity) as conn:
                pids[nombre] = conn.execute(
                    "select pg_backend_pid() as pid").fetchone()["pid"]
                salidas[nombre] = process_source_document(
                    conn, company_id=user_a.company_id,
                    source_document_id=r.source_document_id)
        except BaseException as exc:        # noqa: BLE001
            salidas[nombre] = exc

    hilo_a = threading.Thread(target=_worker, args=("A",), name="A", daemon=True)
    hilo_a.start()
    assert a_tiene_el_lock.wait(timeout=PLAZO), (
        "A no alcanzó el parser: sin eso no hay prueba de que tenga el lock")

    # A está retenido DENTRO de su transacción, con la fila bloqueada.
    hilo_b = threading.Thread(target=_worker, args=("B",), name="B", daemon=True)
    hilo_b.start()

    limite = time.monotonic() + PLAZO
    while "B" not in pids and time.monotonic() < limite:
        time.sleep(0.05)
    assert "B" in pids, "B no llegó a abrir su transacción"
    assert pids["A"] != pids["B"], "los dos trabajadores comparten backend"

    # ── LA PRUEBA: que lo diga PostgreSQL ──
    bloqueadores: list[int] = []
    with fiscal_transaction(pool, settings, user_a.identity) as observador:
        limite = time.monotonic() + PLAZO
        while time.monotonic() < limite:
            bloqueadores = observador.execute(
                "select pg_blocking_pids(%s) as pids", (pids["B"],)
            ).fetchone()["pids"]
            if pids["A"] in bloqueadores:
                break
            time.sleep(0.1)
    # El plazo agotado NO es éxito: la aserción es la relación, no el tiempo.
    assert pids["A"] in bloqueadores, (
        f"PostgreSQL no confirmó que A ({pids['A']}) bloquee a B ({pids['B']}); "
        f"bloqueadores observados: {bloqueadores}")

    soltar_a.set()
    for hilo in (hilo_a, hilo_b):
        hilo.join(timeout=PLAZO)
        assert not hilo.is_alive(), f"el trabajador {hilo.name} se quedó colgado"

    for nombre, s in salidas.items():
        assert not isinstance(s, BaseException), f"{nombre} lanzó: {s!r}"
    assert salidas["A"].status is ProcessingStatus.CREATED
    assert salidas["B"].status is ProcessingStatus.ALREADY_PERSISTED
    assert llamadas == ["A"], f"el parser se ejecutó en {llamadas}"

    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        assert conn.execute(
            "select count(*) as n from fiscal.electronic_documents where company_id=%s",
            (user_a.company_id,)).fetchone()["n"] == 1
        fila = conn.execute(
            "select electronic_document_id from fiscal.source_documents where id=%s",
            (r.source_document_id,)).fetchone()
    assert str(fila["electronic_document_id"]) == salidas["A"].electronic_document_id
    assert salidas["B"].electronic_document_id == salidas["A"].electronic_document_id


# ═════════════════════════════════════════════════════════════════════════════
# 10 · Fronteras del módulo
# ═════════════════════════════════════════════════════════════════════════════

def test_la_ingesta_nunca_muta_la_evidencia():
    """Los grants ya lo impiden; el código debe decirlo también."""
    import ast
    from app.fiscal import ingestion

    arbol = ast.parse(Path(ingestion.__file__).read_text(encoding="utf-8"))
    sql = [n.value for n in ast.walk(arbol)
           if isinstance(n, ast.Constant) and isinstance(n.value, str)
           and "update fiscal." in n.value.lower()]
    assert sql, "no se encontró el UPDATE del ciclo de vida"
    for s in sql:
        bajo = s.lower()
        assert "source_documents" in bajo
        for inmutable in ("raw_xml", "content_sha256", "company_id =",
                          "ingested_at", "ingestion_source",
                          "electronic_document_id ="):
            assert f"set {inmutable}" not in bajo
            assert f", {inmutable}" not in bajo.split("where")[0] or inmutable == "company_id ="


def test_la_ingesta_no_duplica_la_logica_del_parser():
    import ast
    from app.fiscal import ingestion

    fuente = Path(ingestion.__file__).read_text(encoding="utf-8")
    for prohibido in ("etree", "XMLSchema", "fromstring", "validate(",
                      "namespace ==", "xml-schemas"):
        assert prohibido not in fuente, f"la ingesta hace {prohibido}"
    # Y el parser se invoca exactamente en un sitio.
    arbol = ast.parse(fuente)
    llamadas = [n for n in ast.walk(arbol)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id == "parse_fiscal_document"]
    assert len(llamadas) == 1, f"el parser se llama en {len(llamadas)} sitios"


def test_la_ingesta_no_calcula_nada_fiscal():
    import ast
    from app.fiscal import ingestion

    arbol = ast.parse(Path(ingestion.__file__).read_text(encoding="utf-8"))
    nombres = ({n.id for n in ast.walk(arbol) if isinstance(n, ast.Name)}
               | {n.attr for n in ast.walk(arbol) if isinstance(n, ast.Attribute)})
    for prohibido in ("deducib", "acredit", "cabys", "ruleset", "llm",
                      "openai", "anthropic", "embedding"):
        assert not [x for x in nombres if prohibido in x.lower()], prohibido


# ═════════════════════════════════════════════════════════════════════════════
# 11 · Frontera con el registro de esquemas verificado (C2-B-R2)
#
# La ingesta necesita la versión estructural del paquete APROBADO, y durante un
# tiempo la sacó de `registro._por_clave` — un interno del registro. Aquí se
# fija el contrato público que la sustituye, para que no vuelva.
# ═════════════════════════════════════════════════════════════════════════════

def test_el_registro_expone_sus_entradas_verificadas():
    """`entradas()` devuelve los esquemas con raíz, en solo lectura."""
    from app.fiscal.xsd.bundle import SchemaEntry
    from app.fiscal.xsd.registry import get_verified_schema_registry

    entradas = get_verified_schema_registry().entradas()

    assert isinstance(entradas, tuple), "debe ser inmutable, no el mapa interno"
    assert entradas, "el paquete verificado no puede quedar vacío"
    assert all(isinstance(e, SchemaEntry) for e in entradas)
    # `frozen`: lo devuelto no permite mutar el catálogo.
    with pytest.raises(Exception):
        entradas[0].version = "9.9"

    # Solo documentos raíz: las dependencias no se enrutan y no salen.
    assert all(e.root is not None for e in entradas)
    raices = {e.root for e in entradas}
    assert "FacturaElectronica" in raices
    assert "MensajeHacienda" in raices
    assert all(e.version == "4.4" for e in entradas), "el paquete vigente es 4.4"


def test_la_version_detectada_sale_del_registro_verificado():
    """El mapa que consume la ingesta coincide con el paquete aprobado."""
    from app.fiscal.ingestion import _version_por_tipo
    from app.fiscal.models import TIPO_DETECTADO_POR_RAIZ
    from app.fiscal.xsd.registry import get_verified_schema_registry

    esperado = {
        TIPO_DETECTADO_POR_RAIZ[e.root]: e.version
        for e in get_verified_schema_registry().entradas()
    }
    _version_por_tipo.cache_clear()
    assert _version_por_tipo() == esperado
    assert esperado["invoice"] == "4.4"
    assert esperado["hacienda_message"] == "4.4"


def test_una_clave_de_enrutado_desconocida_no_encuentra_esquema():
    """La ausencia se comunica con `None`, no con excepción.

    Es el contrato del que depende `parse_fiscal_document` para distinguir
    `UNKNOWN_DOCUMENT` del resto.
    """
    from app.fiscal.xsd.registry import get_verified_schema_registry

    registro = get_verified_schema_registry()
    assert registro.para("NoExiste", "urn:ejemplo:inventado") is None
    # Raíz real con el namespace de otra versión: tampoco.
    assert registro.para("FacturaElectronica", "urn:ejemplo:v9") is None
    # Y la que sí existe, sigue existiendo.
    ns = ("https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.4/"
          "facturaElectronica")
    assert registro.para("FacturaElectronica", ns) is not None


def test_la_ingesta_no_toca_internos_del_registro():
    """Protección estática COMPLEMENTARIA a las tres pruebas de arriba."""
    import ast
    from app.fiscal import ingestion

    arbol = ast.parse(Path(ingestion.__file__).read_text(encoding="utf-8"))
    privados = sorted({
        n.attr for n in ast.walk(arbol)
        if isinstance(n, ast.Attribute) and n.attr.startswith("_")
        and not (n.attr.startswith("__") and n.attr.endswith("__"))
    })
    assert privados == [], f"la ingesta alcanza internos ajenos: {privados}"


# ═════════════════════════════════════════════════════════════════════════════
# 12 · Identidad del artefacto en fallos posteriores a la captura (C3-A2)
#
# ADR-044 hace que el llamante pueda recibir un error CUANDO LA EVIDENCIA YA
# EXISTE. Si ese error no dice cuál es el artefacto, la única salida del
# usuario es volver a subir el fichero -- y nace una segunda evidencia por un
# fallo transitorio nuestro. Aquí se fija que no se pierda esa identidad.
# ═════════════════════════════════════════════════════════════════════════════

_INFRAESTRUCTURA = [
    (PersistenceUnavailable, "persist_parsed_fiscal_document"),
    (PersistenceDatabaseError, "persist_parsed_fiscal_document"),
    (PersistenceMappingError, "persist_parsed_fiscal_document"),
    (ValidatorConfigurationError, "parse_fiscal_document"),
]


@pytest.mark.parametrize(
    ("clase", "objetivo"), _INFRAESTRUCTURA,
    ids=[c.__name__ for c, _ in _INFRAESTRUCTURA],
)
def test_un_fallo_posterior_a_t1_conserva_la_identidad_del_artefacto(
    clase, objetivo, pool, settings, user_a, monkeypatch, limpio
):
    from app.fiscal import ingestion

    def _revienta(*a, **k):
        raise clase("fallo inyectado", stage="inyectado")

    monkeypatch.setattr(ingestion, objetivo, _revienta)

    with pytest.raises(clase) as exc:
        ingest_fiscal_xml(pool, settings, user_a.identity,
                          company_id=user_a.company_id, raw_xml=_bytes(FE),
                          ingestion_source=IngestionSource.API)

    sid = exc.value.contexto.get("source_document_id")
    assert sid, f"{clase.__name__} perdió la identidad de la evidencia"

    # Es el artefacto REAL, no un valor cualquiera: existe y sigue intacto.
    fila = _leer(pool, settings, user_a, sid)
    assert fila is not None, "la evidencia de T1 debe sobrevivir"
    assert fila["parse_status"] == "pending", "T2 revirtió"
    assert fila["parse_error"] is None
    assert fila["parse_attempt_count"] == 0, "sin incremento durable"
    assert fila["electronic_document_id"] is None

    # No quedó ningún documento normalizado.
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        assert conn.execute(
            "select count(*) as n from fiscal.electronic_documents where company_id=%s",
            (user_a.company_id,)).fetchone()["n"] == 0

    # La cadena sigue limpia: se levantó una excepción NUEVA fuera del `except`.
    assert exc.value.__cause__ is None and exc.value.__context__ is None
    publico = f"{exc.value!s} {exc.value!r}"
    for fuga in ("psycopg", "postgres", "Traceback", "lxml"):
        assert fuga not in publico


def test_un_defecto_de_programacion_no_se_enriquece_ni_se_convierte(
    pool, settings, user_a, monkeypatch, limpio
):
    """Lo inesperado sigue siendo inesperado.

    Enriquecer capturando `Exception` habría convertido cualquier defecto
    nuestro en un error de dominio con aspecto de cosa prevista.
    """
    from app.fiscal import ingestion

    def _bug(*a, **k):
        raise RuntimeError("defecto de programación simulado")

    monkeypatch.setattr(ingestion, "persist_parsed_fiscal_document", _bug)

    with pytest.raises(RuntimeError) as exc:
        ingest_fiscal_xml(pool, settings, user_a.identity,
                          company_id=user_a.company_id, raw_xml=_bytes(FE),
                          ingestion_source=IngestionSource.API)
    assert not isinstance(exc.value, (FiscalWriteForbidden, PersistenceUnavailable))
    assert not hasattr(exc.value, "contexto"), "no se le adjuntó contexto de dominio"


def test_el_conjunto_enriquecido_es_cerrado_y_explicito():
    """Ni `Exception` ni `BaseException`: un conjunto nombrado."""
    from app.fiscal.ingestion import _SEGUROS_TRAS_CAPTURA

    assert Exception not in _SEGUROS_TRAS_CAPTURA
    assert BaseException not in _SEGUROS_TRAS_CAPTURA
    assert set(_SEGUROS_TRAS_CAPTURA) == {
        FiscalWriteForbidden, PersistenceUnavailable, PersistenceDatabaseError,
        PersistenceMappingError, ValidatorConfigurationError,
    }


def test_la_etapa_distingue_captura_de_ciclo_de_vida(
    pool, settings, user_a, monkeypatch, limpio
):
    """`_error_de_captura` sirve a T1 y a T2; la etapa debe decir a cuál.

    Antes fijaba `source_capture` literalmente, así que un fallo al escribir el
    estado del intento se etiquetaba como si hubiera ocurrido al recibir la
    evidencia.
    """
    from app.fiscal import ingestion

    r = _capturar(pool, settings, user_a, user_a.company_id, _bytes(FE))

    # Un fallo de base en la ESCRITURA DEL CICLO DE VIDA, dentro de T2.
    original = ingestion._ACTUALIZAR_CICLO
    monkeypatch.setattr(ingestion, "_ACTUALIZAR_CICLO",
                        original.replace("fiscal.source_documents",
                                         "fiscal.no_existe_esta_tabla"))
    with pytest.raises(PersistenceDatabaseError) as exc:
        _procesar(pool, settings, user_a, user_a.company_id, r.source_document_id)

    assert exc.value.contexto.get("stage") == "source_lifecycle", (
        f"etapa incorrecta: {exc.value.contexto.get('stage')!r}")

    # El identificador NO se añade aquí, y es correcto: el primitivo puede
    # llamarse sobre un artefacto que el llamante ya conoce. Enriquecer es
    # tarea del orquestador, que es quien sabe que T1 acaba de comitear --
    # probado en `test_un_fallo_posterior_a_t1_conserva_la_identidad...`.
    assert "source_document_id" not in exc.value.contexto


def test_una_excepcion_ya_enriquecida_llega_con_la_cadena_limpia(
    pool, settings, user_a, monkeypatch, limpio
):
    """El caso que el `raise` a secas dejaba escapar.

    Si un error seguro NACE dentro de otro `except`, Python le cuelga la
    excepción interna en `__context__`. Relanzarlo tal cual —porque ya traía
    su identificador— habría arrastrado esa excepción hasta la frontera
    pública, que es justo lo que C1-B-R2 prohíbe. Por eso se reconstruyen
    todas, tengan identificador o no.
    """
    from app.fiscal import ingestion

    visto: dict[str, str] = {}

    def _contaminado(*a, **k):
        visto["sid"] = k["source_document_id"]
        try:
            raise ValueError("DETALLE-INTERNO-QUE-NO-DEBE-SALIR")
        except ValueError:
            # Nace enriquecida Y dentro de un `except`: las dos condiciones.
            raise PersistenceUnavailable(
                "La persistencia no está disponible",
                stage="electronic_document",
                source_document_id=k["source_document_id"],
            )

    monkeypatch.setattr(ingestion, "persist_parsed_fiscal_document", _contaminado)

    with pytest.raises(PersistenceUnavailable) as exc:
        ingest_fiscal_xml(pool, settings, user_a.identity,
                          company_id=user_a.company_id, raw_xml=_bytes(FE),
                          ingestion_source=IngestionSource.API)

    err = exc.value
    assert err.contexto.get("stage") == "electronic_document", "contexto preservado"
    assert err.contexto.get("source_document_id") == visto["sid"], (
        "se respetó el identificador que el error ya traía")

    # La propiedad que se estaba perdiendo.
    assert err.__cause__ is None
    assert err.__context__ is None
    publico = f"{err!s} {err!r}"
    assert "DETALLE-INTERNO-QUE-NO-DEBE-SALIR" not in publico
    assert "ValueError" not in publico

    # Y la evidencia sigue ahí, con T2 revertida.
    fila = _leer(pool, settings, user_a, visto["sid"])
    assert fila is not None and fila["electronic_document_id"] is None
