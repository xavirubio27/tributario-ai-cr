"""Frontera HTTP de subida fiscal (C3-B1) — contra PostgreSQL y C2 reales.

Tres propiedades gobiernan este fichero:

1. **El transporte no interpreta.** El endpoint no parsea XML, no valida XSD y
   no decide nada fiscal: solo acota, autentica y traduce.
2. **La autorización sigue siendo de PostgreSQL.** Ninguna prueba simula roles.
3. **Ninguna respuesta de error filtra diagnóstico**, ni del motor ni del
   contribuyente.

Se usa C2 REAL salvo donde provocar un fallo de infraestructura exige inyectar
en la frontera del módulo -- y entonces se inyecta lo mínimo, no la tubería.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from lxml import etree

from app.fiscal.ingestion import MAX_SOURCE_XML_BYTES
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
def client(settings):  # noqa: ARG001 — fuerza el skip si falta configuración
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


def _ruta(company_id: str) -> str:
    return f"/companies/{company_id}/fiscal-documents"


def _subir(client, user, company_id, datos, *, tipo="application/xml", cabeceras=None):
    h = {"Authorization": f"Bearer {user.token}"}
    if tipo is not None:
        h["Content-Type"] = tipo
    h.update(cabeceras or {})
    return client.post(_ruta(company_id), content=datos, headers=h)


# ═════════════════════════════════════════════════════════════════════════════
# 1 · Autenticación e identidad
# ═════════════════════════════════════════════════════════════════════════════

def test_sin_token_es_401(client, user_a):
    r = client.post(_ruta(user_a.company_id), content=_bytes(FE))
    assert r.status_code == 401


@pytest.mark.parametrize(
    "cabecera", ["", "Bearer", "Bearer ", "Token abc", "abc.def.ghi"]
)
def test_token_malformado_es_401(client, user_a, cabecera):
    r = client.post(_ruta(user_a.company_id), content=_bytes(FE),
                    headers={"Authorization": cabecera})
    assert r.status_code == 401


def test_token_invalido_es_401(client, user_a):
    r = client.post(_ruta(user_a.company_id), content=_bytes(FE),
                    headers={"Authorization": "Bearer eyJhbGciOiJFUzI1NiJ9.no.vale"})
    assert r.status_code == 401


# ═════════════════════════════════════════════════════════════════════════════
# 2 · Autorización — decide RLS, no el endpoint
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("rol", ["owner", "editor"])
def test_owner_y_editor_suben(client, user_a, as_role, rol, limpio):
    as_role(rol)
    r = _subir(client, user_a, user_a.company_id, _bytes(FE))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "created"


def test_el_viewer_recibe_403(client, user_a, as_role, limpio):
    as_role("viewer")
    r = _subir(client, user_a, user_a.company_id, _bytes(FE))
    assert r.status_code == 403
    cuerpo = r.json()
    assert cuerpo["code"] == "fiscal_write_forbidden"
    assert cuerpo["category"] == "forbidden"
    # No hay artefacto: la captura falló, no hay identidad que devolver.
    assert cuerpo["source_document_id"] is None


def test_un_no_miembro_recibe_403(client, user_a, user_b, limpio):
    r = _subir(client, user_b, user_a.company_id, _bytes(FE))
    assert r.status_code == 403


def test_no_se_puede_subir_a_empresa_ajena(client, user_a, user_b, limpio):
    r = _subir(client, user_a, user_b.company_id, _bytes(FE))
    assert r.status_code == 403


def test_viewer_y_no_miembro_son_indistinguibles(client, user_a, user_b, as_role, limpio):
    """No enumerabilidad: la misma señal, sin preflight de empresa."""
    as_role("viewer")
    propio = _subir(client, user_a, user_a.company_id, _bytes(FE))
    as_role("owner")
    ajeno = _subir(client, user_b, user_a.company_id, _bytes(FE))
    assert propio.status_code == ajeno.status_code == 403
    assert propio.json() == ajeno.json()


def test_el_endpoint_no_consulta_pertenencias():
    import ast
    from app.api import fiscal_documents

    arbol = ast.parse(Path(fiscal_documents.__file__).read_text(encoding="utf-8"))
    nombres = ({n.id for n in ast.walk(arbol) if isinstance(n, ast.Name)}
               | {n.attr for n in ast.walk(arbol) if isinstance(n, ast.Attribute)}
               | {n.value for n in ast.walk(arbol)
                  if isinstance(n, ast.Constant) and isinstance(n.value, str)})
    for prohibido in ("company_memberships", "is_company_member",
                      "can_write_company", "service_role"):
        assert not any(prohibido in str(x) for x in nombres), prohibido


# ═════════════════════════════════════════════════════════════════════════════
# 3 · Lector acotado — la propiedad de seguridad del transporte
# ═════════════════════════════════════════════════════════════════════════════

def _n_artefactos(admin_sql, company_id) -> int:
    return int(_admin_resiliente(
        admin_sql,
        f"select count(*) as n from fiscal.source_documents "
        f"where company_id='{company_id}'")[0]["n"])


def test_content_length_sobre_el_maximo_es_413(client, user_a, admin_sql, limpio):
    r = _subir(client, user_a, user_a.company_id, b"x" * (MAX_SOURCE_XML_BYTES + 1))
    assert r.status_code == 413
    cuerpo = r.json()
    assert cuerpo["code"] == "source_document_too_large"
    assert cuerpo["category"] == "rejected_before_capture"
    assert cuerpo["source_document_id"] is None
    assert _n_artefactos(admin_sql, user_a.company_id) == 0, "no debe crearse evidencia"


def test_sin_content_length_y_flujo_sobre_el_maximo_es_413(
    client, user_a, admin_sql, limpio
):
    """El cliente no declara longitud: el tope debe salir del acumulado."""
    trozo = b"x" * (256 * 1024)
    veces = (MAX_SOURCE_XML_BYTES // len(trozo)) + 2

    def generador():
        for _ in range(veces):
            yield trozo

    r = client.post(
        _ruta(user_a.company_id), content=generador(),
        headers={"Authorization": f"Bearer {user_a.token}",
                 "Content-Type": "application/xml"},
    )
    assert r.status_code == 413
    assert r.json()["code"] == "source_document_too_large"
    assert _n_artefactos(admin_sql, user_a.company_id) == 0


def test_content_length_mentiroso_no_protege_pero_el_acumulado_si(
    client, user_a, admin_sql, limpio
):
    """Content-Length declara poco y el cuerpo real excede: manda el acumulado."""
    trozo = b"x" * (256 * 1024)
    veces = (MAX_SOURCE_XML_BYTES // len(trozo)) + 2

    def generador():
        for _ in range(veces):
            yield trozo

    r = client.post(
        _ruta(user_a.company_id), content=generador(),
        headers={"Authorization": f"Bearer {user_a.token}",
                 "Content-Type": "application/xml",
                 "Content-Length": "10"},
    )
    assert r.status_code == 413
    assert _n_artefactos(admin_sql, user_a.company_id) == 0


def test_el_maximo_exacto_pasa_el_transporte(client, user_a, limpio):
    """Propiedad del TRANSPORTE: acepta y entrega a C2.

    El documento no es XML, así que C2 lo rechaza después -- y eso es
    justamente lo que demuestra que el transporte no lo atajó por tamaño.
    """
    r = _subir(client, user_a, user_a.company_id, b"x" * MAX_SOURCE_XML_BYTES)
    assert r.status_code == 422, "el transporte aceptó; falló el parseo"
    assert r.json()["code"] == "malformed_xml"


def test_un_byte_de_mas_es_413(client, user_a, limpio):
    r = _subir(client, user_a, user_a.company_id, b"x" * (MAX_SOURCE_XML_BYTES + 1))
    assert r.status_code == 413


def test_el_limite_no_se_redefine_en_el_transporte():
    """Una sola autoridad: la constante se IMPORTA de C2.

    Sobre AST y no sobre el texto del fichero: una aserción textual confunde
    MENCIONAR algo con HACERLO, y aquí el propio comentario que explica por qué
    no se usa `request.body()` bastaba para romperla. Es el patrón frágil que
    este repositorio ya corrigió varias veces.
    """
    import ast
    from app.api import fiscal_documents

    arbol = ast.parse(Path(fiscal_documents.__file__).read_text(encoding="utf-8"))

    importa = [n for n in ast.walk(arbol) if isinstance(n, ast.ImportFrom)
               and n.module == "app.fiscal.ingestion"
               and any(a.name == "MAX_SOURCE_XML_BYTES" for a in n.names)]
    assert importa, "MAX_SOURCE_XML_BYTES debe importarse de C2"

    # Ningún valor del módulo puede EVALUAR a 8 MiB: ni literal ni calculado.
    for nodo in ast.walk(arbol):
        if isinstance(nodo, (ast.Constant, ast.BinOp)):
            try:
                valor = ast.literal_eval(nodo)
            except (ValueError, TypeError, SyntaxError, MemoryError):
                continue
            assert valor != 8 * 1024 * 1024, "el transporte redefine el límite"

    # `request.body()` no se LLAMA (mencionarlo en un comentario es legítimo).
    llamadas_sin_cota = [
        n for n in ast.walk(arbol)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and n.func.attr == "body"
        and isinstance(n.func.value, ast.Name) and n.func.value.id == "request"
    ]
    assert not llamadas_sin_cota, "request.body() acumula sin tope"

    # Y el lector SÍ consume el flujo.
    usa_stream = [
        n for n in ast.walk(arbol)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and n.func.attr == "stream"
    ]
    assert usa_stream, "el cuerpo debe leerse por flujo acotado"


# ═════════════════════════════════════════════════════════════════════════════
# 4 · Fidelidad de los bytes
# ═════════════════════════════════════════════════════════════════════════════

def test_los_bytes_llegan_identicos_a_c2(client, user_a, pool, settings, limpio):
    from app.db import fiscal_transaction

    crudo = _bytes(FE)
    r = _subir(client, user_a, user_a.company_id, crudo)
    assert r.status_code == 200
    sid = r.json()["source_document_id"]
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        fila = conn.execute(
            "select raw_xml from fiscal.source_documents where id=%s", (sid,)
        ).fetchone()
    assert bytes(fila["raw_xml"]) == crudo, "los bytes se alteraron por el camino"


@pytest.mark.parametrize(
    "tipo", ["application/xml", "text/xml", "application/octet-stream",
             "text/plain", None],
)
def test_el_content_type_no_decide(client, user_a, tipo, limpio):
    """El parser es la autoridad, no la cabecera."""
    r = _subir(client, user_a, user_a.company_id, _bytes(FE), tipo=tipo)
    assert r.status_code == 200, f"{tipo} fue rechazado indebidamente"


# ═════════════════════════════════════════════════════════════════════════════
# 5 · Comprobantes reales
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize(("prefijo",), [(FE,), (TE,), (NC,)], ids=["FE", "TE", "NC"])
def test_comprobantes_validos(client, user_a, prefijo, limpio):
    r = _subir(client, user_a, user_a.company_id, _bytes(prefijo))
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["status"] == "created"
    assert cuerpo["source_document_id"] and cuerpo["electronic_document_id"]
    # Contrato mínimo: nada de emisor, total ni Clave.
    assert set(cuerpo) == {"status", "source_document_id", "electronic_document_id"}


# ═════════════════════════════════════════════════════════════════════════════
# 6 · Documentos que no se procesan
# ═════════════════════════════════════════════════════════════════════════════

def test_xml_mal_formado(client, user_a, limpio):
    r = _subir(client, user_a, user_a.company_id, b"<FacturaElectronica> sin cerrar")
    assert r.status_code == 422
    cuerpo = r.json()
    assert cuerpo["code"] == "malformed_xml"
    assert cuerpo["category"] == "invalid_document"
    assert cuerpo["source_document_id"], "la evidencia se guardó: hay que devolverla"


def test_doctype(client, user_a, limpio):
    r = _subir(client, user_a, user_a.company_id,
               b'<!DOCTYPE r [<!ENTITY e "x">]>\n<r/>')
    assert r.status_code == 422
    assert r.json()["code"] == "malformed_xml"


def test_cuerpo_vacio(client, user_a, admin_sql, limpio):
    r = _subir(client, user_a, user_a.company_id, b"")
    assert r.status_code == 422
    cuerpo = r.json()
    assert cuerpo["code"] == "empty_source_document"
    assert cuerpo["category"] == "rejected_before_capture"
    assert cuerpo["source_document_id"] is None
    assert _n_artefactos(admin_sql, user_a.company_id) == 0


def test_raiz_desconocida(client, user_a, limpio):
    r = _subir(client, user_a, user_a.company_id,
               b'<Cualquiera xmlns="urn:ejemplo:x"><a/></Cualquiera>')
    assert r.status_code == 422
    cuerpo = r.json()
    assert cuerpo["code"] == "unsupported_document"
    assert cuerpo["category"] == "unrecognized"
    assert cuerpo["reason"] == "unknown_document"
    assert cuerpo["source_document_id"]


def test_mensaje_hacienda(client, user_a, limpio):
    r = _subir(client, user_a, user_a.company_id, _mh_bytes())
    assert r.status_code == 422
    cuerpo = r.json()
    assert cuerpo["category"] == "outside_pipeline"
    assert cuerpo["reason"] == "outside_pipeline"
    assert cuerpo["source_document_id"]


def test_nota_de_debito(client, user_a, limpio):
    ns = ("https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.4/"
          "notaDebitoElectronica")
    crudo = f'<NotaDebitoElectronica xmlns="{ns}"><Clave/></NotaDebitoElectronica>'.encode()
    r = _subir(client, user_a, user_a.company_id, crudo)
    assert r.status_code == 422
    cuerpo = r.json()
    assert cuerpo["category"] == "not_yet_supported"
    assert cuerpo["reason"] == "unsupported_type"


def test_xml_invalido_contra_el_xsd(client, user_a, limpio):
    arbol = etree.fromstring(_bytes(FE))
    ns = arbol.tag[1:].split("}")[0]
    arbol.find(f"{{{ns}}}Clave").text = "NO-ES-UNA-CLAVE"
    r = _subir(client, user_a, user_a.company_id, etree.tostring(arbol))
    assert r.status_code == 422
    cuerpo = r.json()
    assert cuerpo["code"] == "xsd_validation_error"
    assert cuerpo["category"] == "invalid_document"
    assert cuerpo["source_document_id"]
    assert "NO-ES-UNA-CLAVE" not in r.text


# ═════════════════════════════════════════════════════════════════════════════
# 7 · Duplicado y conflicto de clave
# ═════════════════════════════════════════════════════════════════════════════

def test_el_mismo_documento_dos_veces_no_es_un_error(client, user_a, limpio):
    crudo = _bytes(FE)
    primero = _subir(client, user_a, user_a.company_id, crudo)
    segundo = _subir(client, user_a, user_a.company_id, crudo)
    assert primero.status_code == segundo.status_code == 200
    assert primero.json()["status"] == "created"
    assert segundo.json()["status"] == "linked_existing"
    # Dos evidencias, un documento normalizado.
    assert (primero.json()["source_document_id"]
            != segundo.json()["source_document_id"])
    assert (primero.json()["electronic_document_id"]
            == segundo.json()["electronic_document_id"])


def test_misma_clave_bytes_distintos_es_409(client, user_a, pool, settings, limpio):
    from app.db import fiscal_transaction

    crudo = _bytes(FE)
    assert _subir(client, user_a, user_a.company_id, crudo).status_code == 200

    arbol = etree.fromstring(crudo)
    ns = arbol.tag[1:].split("}")[0]
    nodo = arbol.find(f"{{{ns}}}NumeroConsecutivo")
    nodo.text = nodo.text[:-1] + ("0" if nodo.text[-1] != "0" else "1")
    r = _subir(client, user_a, user_a.company_id, etree.tostring(arbol))

    assert r.status_code == 409
    cuerpo = r.json()
    assert cuerpo["code"] == "clave_conflict"
    assert cuerpo["category"] == "requires_review"
    sid = cuerpo["source_document_id"]
    assert sid, "sin identificador no se puede revisar después"

    # La evidencia queda parseada y sin enlazar: revisable.
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        fila = conn.execute(
            "select parse_status, parse_error, electronic_document_id "
            "from fiscal.source_documents where id=%s", (sid,)).fetchone()
    assert fila["parse_status"] == "parsed"
    assert fila["parse_error"] is None
    assert fila["electronic_document_id"] is None


# ═════════════════════════════════════════════════════════════════════════════
# 8 · Fallos nuestros
# ═════════════════════════════════════════════════════════════════════════════

def test_persistencia_no_disponible_es_503_con_identificador(
    client, user_a, monkeypatch, pool, settings, limpio
):
    """El 503 SÍ devuelve el artefacto: un reintento podrá reutilizarlo."""
    from app.db import fiscal_transaction
    from app.fiscal import ingestion
    from app.fiscal.errors import PersistenceUnavailable

    def _caida(*a, **k):
        raise PersistenceUnavailable("La persistencia no está disponible",
                                     stage="electronic_document")

    monkeypatch.setattr(ingestion, "persist_parsed_fiscal_document", _caida)
    r = _subir(client, user_a, user_a.company_id, _bytes(FE))

    assert r.status_code == 503
    cuerpo = r.json()
    assert cuerpo["code"] == "persistence_unavailable"
    assert cuerpo["category"] == "temporary"
    sid = cuerpo["source_document_id"]
    assert sid, "la evidencia existe; su identidad no puede perderse"

    # T2 revirtió, T1 sobrevivió.
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        fila = conn.execute(
            "select parse_status, parse_attempt_count, electronic_document_id "
            "from fiscal.source_documents where id=%s", (sid,)).fetchone()
    assert fila is not None, "la evidencia de T1 debe sobrevivir"
    assert fila["parse_status"] == "pending"
    assert fila["parse_attempt_count"] == 0
    assert fila["electronic_document_id"] is None


@pytest.mark.parametrize(
    "excepcion",
    ["PersistenceDatabaseError", "PersistenceMappingError",
     "ValidatorConfigurationError"],
)
def test_fallos_internos_son_500_mudos(client, user_a, monkeypatch, excepcion, limpio):
    """El 500 no dice nada más que su categoría, ni siquiera el artefacto."""
    from app.fiscal import ingestion, errors

    clase = getattr(errors, excepcion)
    objetivo = ("parse_fiscal_document" if excepcion == "ValidatorConfigurationError"
                else "persist_parsed_fiscal_document")

    def _revienta(*a, **k):
        raise clase("fallo inyectado", stage="x")

    monkeypatch.setattr(ingestion, objetivo, _revienta)
    r = _subir(client, user_a, user_a.company_id, _bytes(FE))

    assert r.status_code == 500
    assert r.json() == {"code": "internal_error", "category": "internal",
                        "source_document_id": None, "reason": None}


def test_un_defecto_de_programacion_no_se_convierte_en_error_fiscal(
    client, user_a, monkeypatch, limpio
):
    from app.fiscal import ingestion

    def _bug(*a, **k):
        raise RuntimeError("defecto simulado")

    monkeypatch.setattr(ingestion, "parse_fiscal_document", _bug)
    with pytest.raises(RuntimeError):
        _subir(client, user_a, user_a.company_id, _bytes(FE))


# ═════════════════════════════════════════════════════════════════════════════
# 9 · Privacidad de las respuestas
# ═════════════════════════════════════════════════════════════════════════════

_FUGAS = ("postgres", "psycopg", "lxml", "traceback", "constraint",
          "select ", "insert ", "update ", "relation")


@pytest.mark.parametrize(
    ("nombre", "carga"),
    [
        ("malformado", b"<FacturaElectronica> sin cerrar"),
        ("doctype", b'<!DOCTYPE r [<!ENTITY e "x">]>\n<r/>'),
        ("desconocido", b'<X xmlns="urn:x"/>'),
        ("vacio", b""),
    ],
)
def test_ninguna_respuesta_de_error_filtra_diagnostico(
    client, user_a, nombre, carga, limpio
):
    r = _subir(client, user_a, user_a.company_id, carga)
    assert r.status_code >= 400
    bajo = r.text.lower()
    for fuga in _FUGAS:
        assert fuga not in bajo, f"{nombre} filtró {fuga!r}"


def test_el_xsd_invalido_no_devuelve_datos_del_contribuyente(client, user_a, limpio):
    crudo = _bytes(FE)
    arbol = etree.fromstring(crudo)
    ns = arbol.tag[1:].split("}")[0]
    clave_real = arbol.find(f"{{{ns}}}Clave").text
    arbol.find(f"{{{ns}}}Clave").text = "X" * 50
    r = _subir(client, user_a, user_a.company_id, etree.tostring(arbol))
    assert r.status_code == 422
    assert clave_real not in r.text
    assert "X" * 50 not in r.text


# ═════════════════════════════════════════════════════════════════════════════
# 10 · Endpoints previos intactos
# ═════════════════════════════════════════════════════════════════════════════

def test_health_sigue_sin_autenticacion(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_diagnostics_identity_sigue_exigiendo_jwt(client):
    assert client.get("/diagnostics/identity").status_code == 401


# ═════════════════════════════════════════════════════════════════════════════
# 11 · Contrato de la petición (C3-B1-R1)
# ═════════════════════════════════════════════════════════════════════════════

_CAMPOS_ERROR = {"code", "category", "source_document_id", "reason"}


def test_un_company_id_que_no_es_uuid_usa_el_contrato_estable(
    client, user_a, admin_sql, limpio
):
    """Una ruta mal formada es un fallo de la PETICIÓN, no del documento.

    Con `company_id: UUID`, FastAPI rechazaba antes de entrar y devolvía su
    `{"detail": [...]}`, que contradice el contrato que este endpoint anuncia.
    """
    r = client.post("/companies/no-es-un-uuid/fiscal-documents",
                    content=_bytes(FE),
                    headers={"Authorization": f"Bearer {user_a.token}",
                             "Content-Type": "application/xml"})
    assert r.status_code == 422
    cuerpo = r.json()
    assert "detail" not in cuerpo, "no debe salir el formato de FastAPI"
    assert set(cuerpo) == _CAMPOS_ERROR
    assert cuerpo["code"] == "invalid_request"
    assert cuerpo["category"] == "invalid_request"
    assert cuerpo["source_document_id"] is None
    # Ni se llamó a C2 ni nació evidencia en ninguna empresa del arnés.
    assert _n_artefactos(admin_sql, user_a.company_id) == 0


def test_una_ruta_invalida_no_devuelve_el_cuerpo_enviado(client, user_a, limpio):
    marca = b"<Clave>MARCA-SENSIBLE-0123456789</Clave>"
    r = client.post("/companies/tampoco-es-uuid/fiscal-documents", content=marca,
                    headers={"Authorization": f"Bearer {user_a.token}"})
    assert r.status_code == 422
    assert "MARCA-SENSIBLE" not in r.text


def test_un_company_id_uuid_valido_pero_inexistente_no_es_invalid_request(
    client, user_a, limpio
):
    """Sintaxis correcta: ya no decide el transporte, decide RLS."""
    r = client.post("/companies/00000000-0000-4000-8000-000000000000/fiscal-documents",
                    content=_bytes(FE),
                    headers={"Authorization": f"Bearer {user_a.token}"})
    assert r.status_code == 403
    assert r.json()["code"] == "fiscal_write_forbidden"


# ═════════════════════════════════════════════════════════════════════════════
# 12 · OpenAPI — sobre el documento estructurado, no sobre su texto
# ═════════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def openapi():
    from app.main import app as aplicacion

    return aplicacion.openapi()


RUTA_SUBIDA = "/companies/{company_id}/fiscal-documents"


def test_el_endpoint_esta_publicado(openapi):
    assert RUTA_SUBIDA in openapi["paths"]
    assert "post" in openapi["paths"][RUTA_SUBIDA]


def test_el_cuerpo_crudo_esta_documentado(openapi):
    """El runtime lee por flujo; OpenAPI tiene que decir QUÉ se envía."""
    cuerpo = openapi["paths"][RUTA_SUBIDA]["post"]["requestBody"]
    assert cuerpo["required"] is True
    assert "application/xml" in cuerpo["content"]
    esquema = cuerpo["content"]["application/xml"]["schema"]
    assert esquema["type"] == "string"
    assert esquema["format"] == "binary"


def test_documentar_el_cuerpo_no_lo_consume():
    """`openapi_extra` es metadato: no crea dependencia que lea la petición.

    Declarar un parámetro de cuerpo haría que FastAPI lo bufferizara entero
    antes de ejecutar nada, y la cota acumulada dejaría de proteger.
    """
    import ast
    from app.api import fiscal_documents

    arbol = ast.parse(Path(fiscal_documents.__file__).read_text(encoding="utf-8"))
    firma = next(n for n in ast.walk(arbol)
                 if isinstance(n, ast.AsyncFunctionDef)
                 and n.name == "upload_fiscal_document")
    anotaciones = ast.dump(ast.Module(body=[a for a in [firma.args]], type_ignores=[]))
    for consumidor in ("Body", "File", "UploadFile", "Form"):
        assert consumidor not in anotaciones, f"{consumidor} leería el cuerpo entero"


def test_el_company_id_se_documenta_como_uuid(openapi):
    """La validación es nuestra; la documentación no se pierde por ello."""
    parametros = openapi["paths"][RUTA_SUBIDA]["post"]["parameters"]
    company = next(p for p in parametros if p["name"] == "company_id")
    assert company["in"] == "path"
    assert company["schema"]["format"] == "uuid"


def test_el_esquema_de_exito_es_upload_accepted(openapi):
    respuesta = openapi["paths"][RUTA_SUBIDA]["post"]["responses"]["200"]
    ref = respuesta["content"]["application/json"]["schema"]["$ref"]
    assert ref.endswith("/UploadAccepted")
    propiedades = openapi["components"]["schemas"]["UploadAccepted"]["properties"]
    assert set(propiedades) == {"status", "source_document_id",
                                "electronic_document_id"}


@pytest.mark.parametrize("estado", ["401", "403", "409", "413", "422", "500", "503"])
def test_las_respuestas_de_error_estan_declaradas(openapi, estado):
    assert estado in openapi["paths"][RUTA_SUBIDA]["post"]["responses"]


def test_los_endpoints_previos_siguen_publicados(openapi):
    assert "/health" in openapi["paths"]
    assert "/diagnostics/identity" in openapi["paths"]
