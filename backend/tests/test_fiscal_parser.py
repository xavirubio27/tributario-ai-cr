"""Parser fiscal de producción — sobre y partes (B1).

Contrato probado contra los **13 comprobantes reales** del corpus. El parser
es puro: estos tests no abren conexión a la base de datos, no necesitan
usuario autenticado y no conocen `company_id`.

Lo que B1 **no** normaliza —líneas, impuestos, descuentos y referencias— no se
prueba aquí porque no existe: no se finge cobertura.
"""

from __future__ import annotations

import json
import re
import socket
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from app.fiscal.errors import (
    FiscalParseError,
    MalformedXML,
    SemanticParseError,
    UnsupportedDocument,
    XSDValidationError,
)
from app.fiscal.models import ParsedFiscalDocument
from app.fiscal.parser import parse_fiscal_document

FIXTURES = Path(__file__).parent / "fixtures" / "fiscal" / "real" / "v4_4"
NS = "https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.4"


def _comprobantes() -> list[str]:
    """Los 13 comprobantes fiscales: FE, TE y NC. Los MH no lo son."""
    return sorted(
        str(p.relative_to(FIXTURES))
        for sub in ("fe", "te", "nc")
        for p in (FIXTURES / sub).glob("*.xml")
    )


def _mensajes_hacienda() -> list[str]:
    return sorted(str(p.relative_to(FIXTURES)) for p in (FIXTURES / "mh").glob("*.xml"))


def _bytes(rel: str) -> bytes:
    return (FIXTURES / rel).read_bytes()


# ─────────────────────────────────────────────────────────────────────────────
# Los 13 comprobantes reales
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("rel", _comprobantes())
def test_cada_comprobante_real_se_parsea(rel):
    resultado = parse_fiscal_document(_bytes(rel))
    assert isinstance(resultado, ParsedFiscalDocument)


def test_el_reparto_de_tipos_normalizados_es_el_esperado():
    """11 facturas, 1 tiquete, 1 nota de crédito. Ninguna nota de débito."""
    reparto = Counter(
        parse_fiscal_document(_bytes(rel)).document.document_type
        for rel in _comprobantes()
    )
    assert dict(reparto) == {"invoice": 11, "ticket": 1, "credit_note": 1}
    assert "debit_note" not in reparto, (
        "Apareció una Nota de Débito real: revisa el soporte semántico de ND"
    )


@pytest.mark.parametrize("rel", _comprobantes())
def test_clave_y_consecutivo_salen_del_documento(rel):
    """Y el consecutivo es coherente con la Clave que lo contiene.

    Anexos v4.4 §5.2: las posiciones 22-41 de la Clave **son** el consecutivo.
    Si el parser leyera un campo equivocado, esto lo delataría.
    """
    doc = parse_fiscal_document(_bytes(rel)).document
    assert re.fullmatch(r"[0-9]{50}", doc.clave)
    assert re.fullmatch(r"[0-9]{20}", doc.consecutive_number)
    assert doc.clave[21:41] == doc.consecutive_number


@pytest.mark.parametrize("rel", _comprobantes())
def test_los_campos_obligatorios_del_sobre_estan_presentes(rel):
    doc = parse_fiscal_document(_bytes(rel)).document
    assert len(doc.issuer_activity_code) == 6      # 6 caracteres, no 6 dígitos
    assert re.fullmatch(r"[0-9]{2}", doc.sale_condition_code)
    assert doc.currency_code in ("CRC", "USD")
    assert isinstance(doc.reported_exchange_rate, Decimal)
    for campo in ("reported_total_sale", "reported_total_net_sale",
                  "reported_total_document"):
        assert isinstance(getattr(doc, campo), Decimal)


# ─────────────────────────────────────────────────────────────────────────────
# Decimal exacto
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("rel", _comprobantes())
def test_ningun_importe_es_float(rel):
    doc = parse_fiscal_document(_bytes(rel)).document
    for campo in (
        "reported_exchange_rate", "reported_total_sale", "reported_total_net_sale",
        "reported_total_document", "reported_total_taxed", "reported_total_exempt",
        "reported_total_exonerated", "reported_total_not_subject",
        "reported_total_discount", "reported_total_tax",
    ):
        valor = getattr(doc, campo)
        assert valor is None or isinstance(valor, Decimal), f"{campo} no es Decimal"
        assert not isinstance(valor, float)


def test_el_decimal_conserva_la_escala_del_literal():
    """`455.14000` no es `455.14`: la escala es información de la fuente."""
    rel = next(r for r in _comprobantes() if "033159073080" in r)
    doc = parse_fiscal_document(_bytes(rel)).document
    assert doc.reported_exchange_rate == Decimal("455.14000")
    assert -doc.reported_exchange_rate.as_tuple().exponent == 5


def test_el_decimal_acepta_la_forma_sin_cero_inicial():
    """El corpus trae `.00`, que rompe parsers ingenuos."""
    rel = next(r for r in _comprobantes() if "FACTURA_TC" in r)
    texto = _bytes(rel).decode("utf-8")
    assert "<TotalDescuentos>.00</TotalDescuentos>" in texto, (
        "El fixture dejó de ilustrar la forma sin cero inicial"
    )
    doc = parse_fiscal_document(_bytes(rel)).document
    assert doc.reported_total_discount == Decimal("0")
    assert doc.reported_total_discount is not None


def test_ausente_no_se_confunde_con_cero():
    """El caso que separa un dato de una suposición.

    En el golden 2, `TotalDescuentos` **no aparece**; en el golden 1 aparece
    con valor. El primero debe dar `None`, no `Decimal("0")`.
    """
    ausente = next(r for r in _comprobantes() if "50602082600310161019800100024" in r)
    presente = next(r for r in _comprobantes() if "50601082600310161019803900001" in r)

    assert "<TotalDescuentos>" not in _bytes(ausente).decode("utf-8")
    assert parse_fiscal_document(_bytes(ausente)).document.reported_total_discount is None

    doc = parse_fiscal_document(_bytes(presente)).document
    assert doc.reported_total_discount == Decimal("39100.09")


def test_el_plazo_de_credito_distingue_ausente_de_cero_explicito():
    cero = next(r for r in _comprobantes() if "50602082600310161019800100024" in r)
    assert "<PlazoCredito>0</PlazoCredito>" in _bytes(cero).decode("utf-8")
    assert parse_fiscal_document(_bytes(cero)).document.credit_term == 0

    sin_plazo = next(r for r in _comprobantes() if "003101354271-FC" in r)
    assert "<PlazoCredito>" not in _bytes(sin_plazo).decode("utf-8")
    assert parse_fiscal_document(_bytes(sin_plazo)).document.credit_term is None


# ─────────────────────────────────────────────────────────────────────────────
# Fecha — ADR-039
# ─────────────────────────────────────────────────────────────────────────────

def test_fecha_con_desplazamiento_declarado():
    rel = next(r for r in _comprobantes() if "50601082600310161019803900001" in r)
    fecha = parse_fiscal_document(_bytes(rel)).document.fecha

    assert fecha.raw == "2026-08-01T05:24:09-06:00"
    assert fecha.local == datetime(2026, 8, 1, 5, 24, 9)
    assert fecha.offset_minutos == -360
    assert fecha.instante == datetime(2026, 8, 1, 11, 24, 9, tzinfo=timezone.utc)


def test_fecha_sin_desplazamiento_no_inventa_instante():
    """El corazón de ADR-039: si la fuente no lo dice, nosotros tampoco."""
    rel = next(r for r in _comprobantes() if "Comprobante_Electronico" in r)
    fecha = parse_fiscal_document(_bytes(rel)).document.fecha

    assert fecha.raw == "2026-06-30T12:29:12"
    assert fecha.local == datetime(2026, 6, 30, 12, 29, 12)
    assert fecha.instante is None, "Se inventó un instante que la fuente no da"
    assert fecha.offset_minutos is None, "Se inventó un desplazamiento"


def test_el_corpus_cubre_los_dos_casos_de_fecha():
    """Si dejara de cubrirlos, los dos tests anteriores probarían menos."""
    con = [r for r in _comprobantes()
           if parse_fiscal_document(_bytes(r)).document.fecha.instante is not None]
    sin = [r for r in _comprobantes()
           if parse_fiscal_document(_bytes(r)).document.fecha.instante is None]
    assert len(con) == 9 and len(sin) == 4


@pytest.mark.parametrize("rel", _comprobantes())
def test_el_literal_de_la_fecha_se_conserva_intacto(rel):
    doc = parse_fiscal_document(_bytes(rel)).document
    assert f"<FechaEmision>{doc.fecha.raw}</FechaEmision>" in _bytes(rel).decode("utf-8")


@pytest.mark.parametrize("rel", _comprobantes())
def test_instante_y_desplazamiento_son_solidarios(rel):
    fecha = parse_fiscal_document(_bytes(rel)).document.fecha
    assert (fecha.instante is None) == (fecha.offset_minutos is None)


# ─────────────────────────────────────────────────────────────────────────────
# Partes
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("rel", _comprobantes())
def test_el_emisor_existe_y_va_identificado(rel):
    """`Emisor/Identificacion` es minOccurs=1 en los cuatro esquemas."""
    emisor = parse_fiscal_document(_bytes(rel)).issuer
    assert emisor.role == "issuer"
    assert emisor.legal_name
    assert emisor.identificacion is not None
    assert emisor.identificacion.tipo and emisor.identificacion.numero


def test_el_tiquete_no_declara_receptor():
    """`Receptor` es minOccurs=0 en TE: su ausencia es legítima."""
    rel = next(r for r in _comprobantes() if "Comprobante_Electronico" in r)
    resultado = parse_fiscal_document(_bytes(rel))
    assert resultado.receiver is None
    assert len(resultado.parties) == 1


def test_la_nota_de_credito_declara_su_receptor():
    rel = next(r for r in _comprobantes() if r.startswith("nc/"))
    receptor = parse_fiscal_document(_bytes(rel)).receiver
    assert receptor is not None
    assert receptor.role == "receiver"
    assert receptor.identificacion is not None


def test_cuantos_comprobantes_traen_receptor():
    """12 de 13; el único sin receptor es el Tiquete."""
    con = [r for r in _comprobantes() if parse_fiscal_document(_bytes(r)).receiver]
    assert len(con) == 12


@pytest.mark.parametrize("rel", _comprobantes())
def test_la_identificacion_nunca_queda_a_medias(rel):
    """`IdentificacionType` exige `Tipo` y `Numero` juntos."""
    for parte in parse_fiscal_document(_bytes(rel)).parties:
        if parte.identificacion is not None:
            assert parte.identificacion.tipo
            assert parte.identificacion.numero


def test_el_parser_no_resuelve_las_partes_contra_el_saas():
    """Son instantáneas históricas, no referencias vivas.

    El modelo no expone `company_id`, ni identificadores de base de datos, ni
    enlaces a usuarios: si algún día aparecieran, esta frontera se habría roto.
    """
    rel = _comprobantes()[0]
    parte = parse_fiscal_document(_bytes(rel)).issuer
    prohibidos = {"company_id", "id", "user_id", "electronic_document_id"}
    assert prohibidos.isdisjoint(parte.__dataclass_fields__)


def test_el_documento_no_expone_identidad_de_base_de_datos():
    doc = parse_fiscal_document(_bytes(_comprobantes()[0])).document
    prohibidos = {"id", "company_id", "created_at", "updated_at",
                  "direction", "ruleset_revision_status"}
    assert prohibidos.isdisjoint(doc.__dataclass_fields__)


# ─────────────────────────────────────────────────────────────────────────────
# Alcance de B1: lo que NO se normaliza, no se finge
# ─────────────────────────────────────────────────────────────────────────────

def test_el_resultado_no_finge_normalizar_lineas_ni_impuestos():
    """B1 cubre sobre y partes. Devolver listas vacías de líneas sugeriría
    que se intentó y no había, que es distinto de no haberlo implementado."""
    resultado = parse_fiscal_document(_bytes(_comprobantes()[0]))
    for ausente in ("lines", "taxes", "discounts", "references"):
        assert ausente not in resultado.__dataclass_fields__


def test_no_se_emiten_valores_calculados():
    """Invariante duro: el parser solo produce datos reportados."""
    doc = parse_fiscal_document(_bytes(_comprobantes()[0])).document
    assert not [c for c in doc.__dataclass_fields__ if c.startswith("computed_")]


def test_los_campos_diferidos_no_impiden_el_parseo():
    """El corpus real trae campos válidos que el MVP no normaliza.

    `MedioPago` está en los 13 y `TotalDesgloseImpuesto` también. El parser no
    debe fallar por ellos — pero tampoco pretender que los normaliza.
    """
    rel = next(r for r in _comprobantes() if "50601082600310161019803900001" in r)
    texto = _bytes(rel).decode("utf-8")
    for diferido in ("<MedioPago>", "<TotalDesgloseImpuesto>", "<OtrosCargos>",
                     "<CodigoComercial>", "<Registrofiscal8707"):
        assert diferido in texto, f"El fixture perdió {diferido}"

    doc = parse_fiscal_document(_bytes(rel)).document
    for no_normalizado in ("medio_pago", "otros_cargos", "codigo_comercial",
                           "registro_fiscal_8707", "desglose_impuesto"):
        assert no_normalizado not in doc.__dataclass_fields__


# ─────────────────────────────────────────────────────────────────────────────
# Casos negativos
# ─────────────────────────────────────────────────────────────────────────────

def test_xml_mal_formado():
    with pytest.raises(MalformedXML) as exc:
        parse_fiscal_document(b"<FacturaElectronica><sin cerrar>")
    assert exc.value.code == "malformed_xml"


def test_bytes_que_no_son_xml():
    with pytest.raises(MalformedXML):
        parse_fiscal_document(b"esto no es XML en absoluto")


def test_un_documento_con_doctype_se_rechaza():
    """Defensa frente a XXE en la propia frontera pública."""
    with pytest.raises(MalformedXML) as exc:
        parse_fiscal_document(
            b'<?xml version="1.0"?>'
            b'<!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
            b'<r>&x;</r>'
        )
    assert "DOCTYPE" in exc.value.message


def test_raiz_desconocida():
    with pytest.raises(UnsupportedDocument) as exc:
        parse_fiscal_document(b'<?xml version="1.0"?><Inventado xmlns="urn:x"/>')
    assert exc.value.code == "unsupported_document"


def test_raiz_conocida_con_namespace_equivocado():
    """No se selecciona esquema por local-name: el namespace es identidad.

    Una versión distinta del esquema no debe caer en el de la 4.4.
    """
    ns_43 = NS.replace("v4.4", "v4.3")
    with pytest.raises(UnsupportedDocument) as exc:
        parse_fiscal_document(
            f'<?xml version="1.0"?><FacturaElectronica xmlns="{ns_43}"/>'.encode()
        )
    assert exc.value.contexto.get("namespace") == ns_43


def test_el_prefijo_xml_no_altera_la_identidad():
    """Los prefijos no son semántica: el mismo documento con prefijo explícito
    debe comportarse igual que con namespace por defecto."""
    rel = _comprobantes()[0]
    original = parse_fiscal_document(_bytes(rel))

    texto = _bytes(rel).decode("utf-8")
    # Se declara el mismo namespace bajo un prefijo arbitrario en la raíz.
    con_prefijo = texto.replace(
        f'xmlns="{NS}/facturaElectronica"',
        f'xmlns="{NS}/facturaElectronica" xmlns:zz="{NS}/facturaElectronica"',
        1,
    )
    rehecho = parse_fiscal_document(con_prefijo.encode("utf-8"))
    assert rehecho.document.clave == original.document.clave


def test_el_mensaje_de_hacienda_no_es_un_comprobante():
    """Tiene esquema oficial, pero no líneas ni totales: queda fuera."""
    for rel in _mensajes_hacienda():
        with pytest.raises(UnsupportedDocument) as exc:
            parse_fiscal_document(_bytes(rel))
        assert exc.value.contexto.get("raiz") == "MensajeHacienda"


def test_la_nota_de_debito_se_reconoce_pero_no_se_parsea():
    """El esquema está versionado y la raíz se reconoce, pero **no existe
    ningún comprobante real** con el que probar la extracción.

    Aceptarla afirmaría una cobertura que no tenemos.
    """
    xml = (
        f'<?xml version="1.0"?>'
        f'<NotaDebitoElectronica xmlns="{NS}/notaDebitoElectronica"/>'
    ).encode()
    with pytest.raises(UnsupportedDocument) as exc:
        parse_fiscal_document(xml)
    assert exc.value.contexto.get("raiz") == "NotaDebitoElectronica"
    assert "soporte semántico" in exc.value.message


def test_documento_que_incumple_su_esquema():
    """Mutación **en memoria**: no se altera ningún fixture del repositorio."""
    rel = next(r for r in _comprobantes() if r.startswith("fe/"))
    original = _bytes(rel)
    texto = original.decode("utf-8")
    # Una Clave de 49 dígitos incumple `ClaveType`.
    clave = re.search(r"<Clave>(\d{50})</Clave>", texto).group(1)
    roto = texto.replace(f"<Clave>{clave}</Clave>", f"<Clave>{clave[:49]}</Clave>", 1)

    with pytest.raises(XSDValidationError) as exc:
        parse_fiscal_document(roto.encode("utf-8"))
    assert exc.value.code == "xsd_validation_error"
    # Los bytes del repositorio siguen intactos.
    assert _bytes(rel) == original


def test_el_error_de_esquema_no_vuelca_el_documento():
    """El error es compacto y no arrastra el registro de libxml2.

    Reescrito en R1: antes comprobaba que el detalle estuviera *recortado*,
    y recortar no era suficiente. Ahora no hay texto de libxml2 en absoluto.
    """
    rel = next(r for r in _comprobantes() if r.startswith("fe/"))
    texto = _bytes(rel).decode("utf-8")
    clave = re.search(r"<Clave>(\d{50})</Clave>", texto).group(1)
    roto = texto.replace(f"<Clave>{clave}</Clave>", f"<Clave>{clave[:49]}</Clave>", 1)

    with pytest.raises(XSDValidationError) as exc:
        parse_fiscal_document(roto.encode("utf-8"))

    mensaje = str(exc.value)
    assert len(mensaje) < 300, "El error creció: puede estar filtrando contenido"
    assert clave[:49] not in mensaje, "Se filtró el valor infractor"


@pytest.mark.parametrize(
    "clase, esperado",
    [
        (MalformedXML, "malformed_xml"),
        (UnsupportedDocument, "unsupported_document"),
        (XSDValidationError, "xsd_validation_error"),
        (SemanticParseError, "semantic_parse_error"),
    ],
)
def test_cada_error_tiene_codigo_estable(clase, esperado):
    assert clase.code == esperado
    assert issubclass(clase, FiscalParseError)


def test_ninguna_excepcion_de_lxml_cruza_la_frontera():
    """Todo fallo del parser es un `FiscalParseError`."""
    entradas = [
        b"", b"<", b"no es xml", b"<a><b></a>",
        b'<?xml version="1.0"?><X xmlns="urn:desconocido"/>',
    ]
    for datos in entradas:
        with pytest.raises(FiscalParseError):
            parse_fiscal_document(datos)


# ─────────────────────────────────────────────────────────────────────────────
# Seguridad y pureza
# ─────────────────────────────────────────────────────────────────────────────

@contextmanager
def _red_bloqueada():
    intentos: list[str] = []
    orig = (socket.socket.connect, socket.create_connection, socket.getaddrinfo)

    def _c(self, address, *a, **k):
        intentos.append(str(address)); raise OSError("RED BLOQUEADA")

    def _cc(address, *a, **k):
        intentos.append(str(address)); raise OSError("RED BLOQUEADA")

    def _ga(host, port, *a, **k):
        intentos.append(f"{host}:{port}"); raise socket.gaierror("RED BLOQUEADA")

    socket.socket.connect, socket.create_connection, socket.getaddrinfo = _c, _cc, _ga
    try:
        yield intentos
    finally:
        socket.socket.connect, socket.create_connection, socket.getaddrinfo = orig


def test_el_parser_de_produccion_no_sale_a_la_red():
    """Se prueba el camino REAL de producción, no la configuración de un
    ayudante de test."""
    with _red_bloqueada() as intentos:
        for rel in _comprobantes():
            parse_fiscal_document(_bytes(rel))
    assert intentos == [], f"El parser intentó salir a la red: {intentos}"


def test_el_parser_es_puro():
    """Sin base de datos, sin usuario autenticado, sin `company_id`.

    Es un contrato de arquitectura: si el parser necesitara alguno, dejaría de
    poder probarse aisladamente y la persistencia quedaría acoplada a él.
    """
    import inspect

    firma = inspect.signature(parse_fiscal_document)
    assert list(firma.parameters) == ["raw_xml"], (
        "El parser público solo acepta bytes"
    )
    # Y funciona sin ningún fixture de base de datos: este test no pide
    # `pool`, `settings`, `user_a` ni nada equivalente.
    resultado = parse_fiscal_document(_bytes(_comprobantes()[0]))
    assert resultado.document.clave


def test_la_firma_no_se_verifica_criptograficamente():
    """El parser ignora los internos de `ds:Signature`.

    Que el esquema acepte la estructura de la firma **no** dice nada sobre su
    autenticidad: eso exige digest y cadena de certificación, y no está en el
    alcance de B1.
    """
    rel = _comprobantes()[0]
    assert b"Signature" in _bytes(rel)
    doc = parse_fiscal_document(_bytes(rel)).document
    for campo in doc.__dataclass_fields__:
        assert "signature" not in campo.lower()
        assert "firma" not in campo.lower()


# ─────────────────────────────────────────────────────────────────────────────
# R1 · La puerta fail-closed está en el camino de producción (HIGH-1)
#
# Hasta R1, CI verificaba el paquete y el parser compilaba por su cuenta: la
# garantía existía, pero el punto de entrada real no dependía de ella.
# ─────────────────────────────────────────────────────────────────────────────

import shutil
import threading

from app.fiscal.errors import ValidatorConfigurationError
from app.fiscal.xsd import bundle, policy
from app.fiscal.xsd import registry as registry_modulo
from app.fiscal.xsd.registry import (
    VerifiedSchemaRegistry,
    get_verified_schema_registry,
)


def test_el_registro_verificado_inicializa_con_el_paquete_aprobado():
    registro = get_verified_schema_registry()
    assert isinstance(registro, VerifiedSchemaRegistry)
    assert registro.fingerprint == policy.APPROVED_VALIDATOR_BUNDLE_SHA256
    # Los cuatro comprobantes más el mensaje: cinco raíces con esquema.
    assert len(registro._por_clave) == 5


def test_el_registro_se_cachea_y_no_recompila():
    """El vínculo bytes verificados → esquemas consumidos se mantiene porque
    se reutilizan los objetos ya compilados, sin reabrir el paquete."""
    a = get_verified_schema_registry()
    b = get_verified_schema_registry()
    assert a is b
    for clave in a._por_clave:
        assert a._por_clave[clave][1] is b._por_clave[clave][1]


def test_el_parser_obtiene_los_esquemas_solo_del_registro():
    """Estructural: no hay una segunda vía que compile sin pasar la puerta."""
    from app.fiscal.parser import document as modulo

    fuente = Path(modulo.__file__).read_text(encoding="utf-8")
    assert "get_verified_schema_registry()" in fuente
    assert "bundle.compilar(" not in fuente, (
        "El parser compila por su cuenta, saltándose la puerta"
    )
    assert "bundle.esquema_para(" not in fuente


@pytest.fixture
def registro_limpio():
    """Vacía la caché antes y después: cada test parte de estado fresco."""
    get_verified_schema_registry.cache_clear()
    bundle.compilar.cache_clear()
    yield
    get_verified_schema_registry.cache_clear()
    bundle.compilar.cache_clear()


@contextmanager
def _bundle_apuntando_a(destino: Path):
    """Redirige el paquete de producción a una copia, y lo restaura."""
    originales = (bundle.BUNDLE, bundle.MANIFEST)
    bundle.BUNDLE, bundle.MANIFEST = destino, destino / "MANIFEST.json"
    bundle.entries.cache_clear()
    bundle.manifest.cache_clear()
    bundle._por_clave.cache_clear()
    try:
        yield
    finally:
        bundle.BUNDLE, bundle.MANIFEST = originales
        bundle.entries.cache_clear()
        bundle.manifest.cache_clear()
        bundle._por_clave.cache_clear()


@pytest.mark.parametrize(
    "mutacion",
    ["xsd_inesperado", "xsd_ausente", "bytes_mutados", "manifiesto_remapeado",
     "symlink"],
    ids=lambda m: m,
)
def test_un_paquete_alterado_impide_inicializar_produccion(
    mutacion, tmp_path, registro_limpio
):
    """La aserción central de R1: si la puerta rechaza el paquete, la
    inicialización de producción **no puede** tener éxito."""
    copia = tmp_path / "cr"
    shutil.copytree(bundle.BUNDLE, copia, symlinks=False)
    v4 = copia / "esquemas" / "v4_4"

    if mutacion == "xsd_inesperado":
        (v4 / "intruso.xsd").write_bytes(b'<?xml version="1.0"?><x/>')
    elif mutacion == "xsd_ausente":
        (v4 / "NotaDebitoElectronica_V4.4.xsd").unlink()
    elif mutacion == "bytes_mutados":
        objetivo = v4 / "MensajeHacienda_V4.4.xsd"
        objetivo.write_bytes(objetivo.read_bytes() + b"\n<!-- alterado -->")
    elif mutacion == "manifiesto_remapeado":
        nueva = "esquemas/v4_4/FacturaElectronica_renombrada.xsd"
        (v4 / "FacturaElectronica_V4.4.xsd").rename(copia / nueva)
        doc = json.loads((copia / "MANIFEST.json").read_text(encoding="utf-8"))
        for e in doc["schemas"]:
            if e["id"] == "cr.fe.v4_4":
                e["path"] = nueva
        (copia / "MANIFEST.json").write_text(json.dumps(doc), encoding="utf-8")
    elif mutacion == "symlink":
        externo = tmp_path / "fuera"
        externo.mkdir()
        (copia / "enlazado").symlink_to(externo, target_is_directory=True)

    with _bundle_apuntando_a(copia):
        get_verified_schema_registry.cache_clear()
        with pytest.raises(ValidatorConfigurationError) as exc:
            get_verified_schema_registry()

    assert exc.value.code == "validator_bundle_invalid"


def test_el_fallo_del_paquete_no_se_confunde_con_xml_invalido():
    """Un paquete corrupto es un problema NUESTRO, no del contribuyente.

    Clasificarlo como `XSDValidationError` culparía al usuario de un fallo de
    despliegue y ocultaría el incidente real.
    """
    assert ValidatorConfigurationError.code == "validator_bundle_invalid"
    assert not issubclass(ValidatorConfigurationError, XSDValidationError)
    assert issubclass(ValidatorConfigurationError, FiscalParseError)


def test_el_error_de_paquete_no_revela_rutas_del_servidor(tmp_path, registro_limpio):
    copia = tmp_path / "cr"
    shutil.copytree(bundle.BUNDLE, copia, symlinks=False)
    (copia / "esquemas" / "v4_4" / "intruso.xsd").write_bytes(b"<x/>")

    with _bundle_apuntando_a(copia):
        get_verified_schema_registry.cache_clear()
        with pytest.raises(ValidatorConfigurationError) as exc:
            get_verified_schema_registry()

    publico = str(exc.value)
    assert str(tmp_path) not in publico
    assert "intruso.xsd" not in publico
    assert "/" not in publico.replace("El paquete", "")


# ─────────────────────────────────────────────────────────────────────────────
# R1 · Privacidad del diagnóstico XSD (HIGH-2)
# ─────────────────────────────────────────────────────────────────────────────

def test_el_error_de_esquema_no_filtra_el_valor_infractor():
    """Truncar no es redactar.

    libxml2 escribe el valor infractor al **principio** del mensaje, así que
    conservar «los primeros 200 caracteres» conservaba justo lo que no debía
    publicarse. El diagnóstico se construye ahora solo con metadatos
    estructurales.
    """
    CENTINELA = "SENSITIVE-CUSTOMER-ID"
    rel = next(r for r in _comprobantes() if r.startswith("fe/"))
    original = _bytes(rel)
    texto = original.decode("utf-8")
    clave = re.search(r"<Clave>(\d{50})</Clave>", texto).group(1)
    roto = texto.replace(f"<Clave>{clave}</Clave>", f"<Clave>{CENTINELA}</Clave>", 1)

    with pytest.raises(XSDValidationError) as exc:
        parse_fiscal_document(roto.encode("utf-8"))

    superficie = " ".join([
        str(exc.value), exc.value.message, exc.value.code,
        repr(exc.value), str(exc.value.contexto),
        " ".join(map(str, exc.value.contexto.keys())),
        " ".join(map(str, exc.value.contexto.values())),
    ])
    assert CENTINELA not in superficie, "Se filtró el valor infractor"
    # Tampoco fragmentos del documento ni la Clave legítima.
    assert clave not in superficie
    assert "<Clave>" not in superficie
    assert _bytes(rel) == original          # el fixture sigue intacto


def test_el_diagnostico_de_esquema_es_estructural_y_util():
    """Se pierde el texto, no la capacidad de diagnosticar."""
    rel = next(r for r in _comprobantes() if r.startswith("fe/"))
    texto = _bytes(rel).decode("utf-8")
    clave = re.search(r"<Clave>(\d{50})</Clave>", texto).group(1)
    roto = texto.replace(f"<Clave>{clave}</Clave>", "<Clave>X</Clave>", 1)

    with pytest.raises(XSDValidationError) as exc:
        parse_fiscal_document(roto.encode("utf-8"))

    ctx = exc.value.contexto
    assert ctx["error_type"] == "SCHEMAV_CVC_PATTERN_VALID"
    assert isinstance(ctx["line"], int)
    assert "esquema" in ctx
    assert "detalle" not in ctx, "Volvió el volcado de texto de libxml2"


# ─────────────────────────────────────────────────────────────────────────────
# R1 · DOCTYPE detectado estructuralmente (MEDIUM-1)
# ─────────────────────────────────────────────────────────────────────────────

def test_doctype_tras_un_relleno_mayor_que_la_ventana_antigua():
    """El bypass reproducido por la auditoría.

    La detección anterior miraba los primeros 8 KiB; 9 KiB de comentario
    legal por delante bastaban para colar el DOCTYPE.
    """
    relleno = b"<!-- " + b"x" * 9000 + b" -->"
    ataque = (
        b'<?xml version="1.0"?>' + relleno
        + b'<!DOCTYPE r [<!ENTITY e "x">]><r/>'
    )
    assert ataque.index(b"<!DOCTYPE") > 8192

    with pytest.raises(MalformedXML) as exc:
        parse_fiscal_document(ataque)
    assert "DOCTYPE" in exc.value.message


def test_doctype_con_subconjunto_interno():
    with pytest.raises(MalformedXML):
        parse_fiscal_document(
            b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY e "x">]><r/>'
        )


def test_doctype_con_dtd_externa():
    with pytest.raises(MalformedXML):
        parse_fiscal_document(
            b'<?xml version="1.0"?>'
            b'<!DOCTYPE r SYSTEM "http://example.invalid/r.dtd"><r/>'
        )


def test_una_dtd_externa_no_provoca_acceso_a_red():
    with _red_bloqueada() as intentos:
        with pytest.raises(MalformedXML):
            parse_fiscal_document(
                b'<?xml version="1.0"?>'
                b'<!DOCTYPE r SYSTEM "http://example.invalid/r.dtd"><r/>'
            )
    assert intentos == []


def test_un_documento_sin_doctype_se_comporta_con_normalidad():
    """Guarda contra un rechazo indiscriminado."""
    for rel in _comprobantes():
        assert b"<!DOCTYPE" not in _bytes(rel)
    assert parse_fiscal_document(_bytes(_comprobantes()[0])).document.clave


# ─────────────────────────────────────────────────────────────────────────────
# R1 · Sin estado global de directorio (MEDIUM-2)
# ─────────────────────────────────────────────────────────────────────────────

def test_no_queda_ningun_os_chdir_en_el_codigo_fiscal_de_produccion():
    import app.fiscal as paquete

    raiz = Path(paquete.__file__).parent
    culpables = [
        f.name for f in raiz.rglob("*.py")
        if "os.chdir" in f.read_text(encoding="utf-8").replace(
            "**Sin `os.chdir`.**", ""
        )
    ]
    assert culpables == [], f"os.chdir en producción: {culpables}"


def test_la_inicializacion_no_altera_el_directorio_de_trabajo(registro_limpio):
    """`cwd` es estado global del proceso: mutarlo corrompe otros hilos."""
    import os

    antes = os.getcwd()
    get_verified_schema_registry()
    parse_fiscal_document(_bytes(_comprobantes()[0]))
    assert os.getcwd() == antes


def test_la_compilacion_funciona_con_un_cwd_ajeno(tmp_path, registro_limpio):
    """Si dependiera del `cwd`, esto fallaría."""
    import os

    antes = os.getcwd()
    os.chdir(tmp_path)          # solo el TEST cambia de directorio
    try:
        registro = get_verified_schema_registry()
        assert len(registro._por_clave) == 5
        assert parse_fiscal_document(
            (FIXTURES / _comprobantes()[0]).read_bytes()
        ).document.clave
    finally:
        os.chdir(antes)


def test_inicializacion_concurrente(registro_limpio):
    """Determinista, sin depender de tiempos: N hilos inicializan a la vez y
    todos deben obtener un registro equivalente y coherente."""
    resultados: list[VerifiedSchemaRegistry] = []
    errores: list[BaseException] = []
    barrera = threading.Barrier(8)

    def _trabajo():
        try:
            barrera.wait(timeout=10)
            resultados.append(get_verified_schema_registry())
        except BaseException as exc:       # noqa: BLE001
            errores.append(exc)

    hilos = [threading.Thread(target=_trabajo) for _ in range(8)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(timeout=30)

    assert errores == [], f"Fallos concurrentes: {errores}"
    assert len(resultados) == 8
    fingerprints = {r.fingerprint for r in resultados}
    assert fingerprints == {policy.APPROVED_VALIDATOR_BUNDLE_SHA256}


# ─────────────────────────────────────────────────────────────────────────────
# R1 · Invariantes de los modelos (MEDIUM-3)
# ─────────────────────────────────────────────────────────────────────────────

from app.fiscal.models import FechaFiscal, Identificacion, ParsedDocumentParty


@pytest.mark.parametrize(
    "tipo, numero", [("", "3101123456"), ("01", ""), ("", "")],
)
def test_la_identificacion_no_admite_campos_vacios(tipo, numero):
    with pytest.raises(ValueError):
        Identificacion(tipo=tipo, numero=numero)


def test_la_identificacion_completa_se_construye():
    ident = Identificacion(tipo="01", numero="3101123456")
    assert ident.tipo == "01" and ident.numero == "3101123456"


def test_el_emisor_exige_identificacion_al_construirse():
    with pytest.raises(ValueError):
        ParsedDocumentParty(role="issuer", legal_name="Alguien")


def test_el_receptor_puede_construirse_sin_identificacion():
    """B0.1: legal en TE, NC y ND."""
    parte = ParsedDocumentParty(role="receiver", legal_name="Consumidor")
    assert parte.identificacion is None


def test_la_parte_exige_nombre():
    with pytest.raises(ValueError):
        ParsedDocumentParty(role="receiver", legal_name="")


_AWARE = datetime(2026, 8, 1, 11, 24, 9, tzinfo=timezone.utc)
_LOCAL = datetime(2026, 8, 1, 5, 24, 9)


@pytest.mark.parametrize(
    "kwargs, motivo",
    [
        (dict(instante=_AWARE), "instante sin desplazamiento"),
        (dict(offset_minutos=-360), "desplazamiento sin instante"),
        (dict(instante=datetime(2026, 8, 1, 11, 24, 9), offset_minutos=-360),
         "instante sin huso"),
        (dict(instante=_AWARE, offset_minutos=-841), "desplazamiento fuera de rango"),
        (dict(instante=_AWARE, offset_minutos=841), "desplazamiento fuera de rango"),
        (dict(instante=datetime(2026, 12, 1, tzinfo=timezone.utc), offset_minutos=-360),
         "instante incoherente con el reloj de pared"),
    ],
    ids=lambda x: x if isinstance(x, str) else "",
)
def test_fecha_fiscal_rechaza_estados_imposibles(kwargs, motivo):
    with pytest.raises(ValueError):
        FechaFiscal(local=_LOCAL, raw="irrelevante", **kwargs)


def test_fecha_fiscal_rechaza_un_reloj_de_pared_con_huso():
    """Si el `local` llevara huso ya sería un instante, y la separación de
    ADR-039 se habría perdido."""
    with pytest.raises(ValueError):
        FechaFiscal(local=_AWARE, raw="irrelevante")


@pytest.mark.parametrize("offset", [-840, 840, 0])
def test_fecha_fiscal_acepta_los_limites_del_rango(offset):
    """±840 es el límite de `xs:dateTime`, no una regla de Costa Rica."""
    instante = (_LOCAL - timedelta(minutes=offset)).replace(tzinfo=timezone.utc)
    fecha = FechaFiscal(
        local=_LOCAL, raw="x", instante=instante, offset_minutos=offset
    )
    assert fecha.offset_minutos == offset


def test_fecha_fiscal_acepta_la_forma_sin_desplazamiento():
    fecha = FechaFiscal(local=_LOCAL, raw="2026-08-01T05:24:09")
    assert fecha.instante is None and fecha.offset_minutos is None


# ─────────────────────────────────────────────────────────────────────────────
# R2 · Taxonomía de fallos del paquete del validador
#
# La puerta ya cerraba ante un paquete alterado, pero solo cuando el fallo
# llegaba a ella **ya formado**. Un manifiesto ilegible, mal codificado, con el
# JSON roto o con otra estructura reventaba antes, en crudo: `OSError`,
# `UnicodeDecodeError`, `JSONDecodeError`, `KeyError` o `TypeError` salían por
# el contrato público del parser sin pasar por la taxonomía aprobada.
#
# Estos tests recorren la ruta REAL de producción —`get_verified_schema_registry`
# sobre una copia temporal del paquete—, no los ayudantes de política por
# separado.
# ─────────────────────────────────────────────────────────────────────────────

#: Centinela que se inyecta en el texto de bajo nivel. Si aparece en la
#: excepción pública, es que el mensaje original viajó con ella.
SENTINEL = "SECRET-BUNDLE-SENTINEL"


def _copia_del_paquete(tmp_path: Path) -> Path:
    copia = tmp_path / "cr"
    shutil.copytree(bundle.BUNDLE, copia, symlinks=False)
    return copia


def _manifiesto(copia: Path) -> Path:
    return copia / "MANIFEST.json"


def _inicializar_esperando_rechazo(copia: Path) -> ValidatorConfigurationError:
    """Ejecuta la inicialización de producción y devuelve el error público."""
    with _bundle_apuntando_a(copia):
        get_verified_schema_registry.cache_clear()
        with pytest.raises(ValidatorConfigurationError) as exc:
            get_verified_schema_registry()
    return exc.value


def _assert_publico_seguro(error: ValidatorConfigurationError, tmp_path: Path) -> None:
    """El error público no lleva ruta, ni contenido, ni texto de bajo nivel."""
    superficie = " ".join(
        [str(error), repr(error), error.message, repr(sorted(error.contexto.items()))]
    )
    assert SENTINEL not in superficie
    assert str(tmp_path) not in superficie
    assert "MANIFEST.json" not in superficie
    assert "Traceback" not in superficie
    assert error.code == "validator_bundle_invalid"


# §7 · Manifiesto con JSON malformado ─────────────────────────────────────────

def test_manifiesto_con_json_malformado_sale_por_la_taxonomia(
    tmp_path, registro_limpio
):
    """`JSONDecodeError` no puede cruzar la frontera pública del parser."""
    copia = _copia_del_paquete(tmp_path)
    _manifiesto(copia).write_text(
        '{"schemas": [ ' + SENTINEL + ' ROTO', encoding="utf-8"
    )

    error = _inicializar_esperando_rechazo(copia)

    _assert_publico_seguro(error, tmp_path)
    # La causa real sigue disponible para depurar el servidor…
    assert isinstance(error.__cause__, policy.BundleRechazado)
    # …pero el motivo del rechazo es canónico, no el texto de `json`.
    assert policy.RAZON_MANIFIESTO_NO_JSON in str(error.__cause__)


def test_manifiesto_que_no_es_utf8_sale_por_la_taxonomia(tmp_path, registro_limpio):
    """Leer y decodificar son fallos distintos: `read_text` los mezclaba."""
    copia = _copia_del_paquete(tmp_path)
    _manifiesto(copia).write_bytes(b'{"schemas": [\xff\xfe]}')

    error = _inicializar_esperando_rechazo(copia)

    _assert_publico_seguro(error, tmp_path)
    assert policy.RAZON_MANIFIESTO_NO_UTF8 in str(error.__cause__)


# §8 · Fallo de lectura del sistema de ficheros ───────────────────────────────

def test_un_fallo_de_lectura_sale_por_la_taxonomia(
    tmp_path, monkeypatch, registro_limpio
):
    """Se inyecta el fallo en la operación EXACTA que usa la política.

    No se usa `chmod`: el entorno de pruebas puede correr con privilegios que
    lo ignoren, y entonces el test pasaría sin haber ejercitado nada.
    """
    copia = _copia_del_paquete(tmp_path)
    original = Path.read_bytes

    def lectura_que_falla(self, *args, **kwargs):
        if self.name == "MANIFEST.json":
            raise OSError(5, f"Input/output error {SENTINEL}")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", lectura_que_falla)

    error = _inicializar_esperando_rechazo(copia)

    _assert_publico_seguro(error, tmp_path)
    assert policy.RAZON_MANIFIESTO_ILEGIBLE in str(error.__cause__)
    # El OSError original se conserva encadenado, no en el texto.
    assert isinstance(error.__cause__.__cause__, OSError)


def test_un_esquema_ilegible_sale_por_la_taxonomia(
    tmp_path, monkeypatch, registro_limpio
):
    """Mismo trato para los bytes de un `*.xsd`, no solo para el manifiesto."""
    copia = _copia_del_paquete(tmp_path)
    original = Path.read_bytes

    def lectura_que_falla(self, *args, **kwargs):
        if self.suffix == ".xsd":
            raise PermissionError(13, f"Permission denied {SENTINEL}")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", lectura_que_falla)

    error = _inicializar_esperando_rechazo(copia)

    _assert_publico_seguro(error, tmp_path)
    assert policy.RAZON_ESQUEMA_ILEGIBLE in str(error.__cause__)


# §9 · JSON válido, estructura inválida ───────────────────────────────────────

@pytest.mark.parametrize(
    ("caso", "contenido"),
    [
        ("sin_clave_schemas", '{"otra_cosa": []}'),
        ("schemas_no_es_lista", '{"schemas": 42}'),
        ("manifiesto_es_lista", '["no", "es", "un", "objeto"]'),
        ("entrada_no_es_objeto", '{"schemas": ["texto suelto"]}'),
    ],
    ids=lambda v: v if isinstance(v, str) and " " not in v else "",
)
def test_manifiesto_estructuralmente_invalido_sale_por_la_taxonomia(
    caso, contenido, tmp_path, registro_limpio
):
    """`KeyError` y `TypeError` del manifiesto son estado de configuración."""
    copia = _copia_del_paquete(tmp_path)
    _manifiesto(copia).write_text(contenido, encoding="utf-8")

    error = _inicializar_esperando_rechazo(copia)

    _assert_publico_seguro(error, tmp_path)
    assert policy.RAZON_MANIFIESTO_INCOMPLETO in str(error.__cause__)


@pytest.mark.parametrize("campo", ["namespace", "sha256", "bytes"])
def test_un_manifiesto_que_pasa_la_puerta_pero_no_describe_el_catalogo(
    campo, tmp_path, registro_limpio
):
    """El hueco que la auditoría no nombró.

    El fingerprint cubre los bytes de los `*.xsd`, **no** los del manifiesto.
    Así que un manifiesto puede conservar el mapeo `id -> ruta` aprobado —y
    pasar la puerta— y aun así no traer los campos que el catálogo consume.
    Antes de R2 eso salía como un `KeyError` crudo *después* de que la
    verificación hubiera dado el visto bueno.
    """
    copia = _copia_del_paquete(tmp_path)
    doc = json.loads(_manifiesto(copia).read_text(encoding="utf-8"))
    for entrada in doc["schemas"]:
        entrada.pop(campo, None)
    _manifiesto(copia).write_text(json.dumps(doc), encoding="utf-8")

    # La puerta lo aprueba: el mapeo y los bytes de los esquemas siguen bien.
    assert policy.verify_approved_schema_bundle(copia)

    error = _inicializar_esperando_rechazo(copia)
    _assert_publico_seguro(error, tmp_path)


def test_un_campo_del_manifiesto_con_tipo_erroneo_no_llega_como_typeerror(
    tmp_path, registro_limpio
):
    copia = _copia_del_paquete(tmp_path)
    doc = json.loads(_manifiesto(copia).read_text(encoding="utf-8"))
    for entrada in doc["schemas"]:
        entrada["namespace"] = ["no", "es", "texto"]
    _manifiesto(copia).write_text(json.dumps(doc), encoding="utf-8")

    error = _inicializar_esperando_rechazo(copia)
    _assert_publico_seguro(error, tmp_path)


# §3 · Los defectos de programación NO se disfrazan ───────────────────────────

@pytest.mark.parametrize(
    "clase", [AttributeError, NameError, RuntimeError, ZeroDivisionError]
)
def test_un_defecto_de_programacion_sigue_siendo_visible(
    clase, tmp_path, monkeypatch, registro_limpio
):
    """Normalizar de más sería peor que no normalizar.

    Si un bug nuestro saliera como `validator_bundle_invalid`, mandaría a
    revisar el despliegue en lugar del código, y el incidente real quedaría
    tapado bajo un diagnóstico falso. Por eso no se captura `Exception`.
    """
    copia = _copia_del_paquete(tmp_path)
    original = Path.read_bytes

    def bug(self, *args, **kwargs):
        if self.name == "MANIFEST.json":
            raise clase("defecto de programación simulado")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", bug)

    with _bundle_apuntando_a(copia):
        get_verified_schema_registry.cache_clear()
        with pytest.raises(clase):
            get_verified_schema_registry()


def test_el_rechazo_ya_formado_no_se_vuelve_a_envolver():
    """`BundleRechazado` hereda de `AssertionError`, que no está en ninguna
    de las tuplas normalizadas: atraviesa el gestor intacto."""
    for clases in (
        policy.FALLOS_DE_LECTURA,
        policy.FALLOS_DE_DECODIFICACION,
        policy.FALLOS_DE_SINTAXIS,
        policy.FALLOS_DE_ESTRUCTURA,
        policy.FALLOS_DE_RUTA,
        policy.FALLOS_DEL_MANIFIESTO,
    ):
        assert not issubclass(policy.BundleRechazado, clases)

    original = policy.BundleRechazado("motivo original")
    with pytest.raises(policy.BundleRechazado) as exc:
        with policy.rechazar_si_falla("otra razón", policy.FALLOS_DEL_MANIFIESTO):
            raise original
    assert exc.value is original


def test_no_se_captura_exception_en_la_normalizacion():
    """Guardia sobre la fuente: un `except Exception` reabriría el problema."""
    for modulo in (policy, registry_modulo):
        fuente = Path(modulo.__file__).read_text(encoding="utf-8")
        assert "except Exception" not in fuente
        assert "except BaseException" not in fuente


# §11 · Fallo cerrado ─────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "romper_manifiesto",
    [
        lambda p: p.write_text("{ roto", encoding="utf-8"),
        lambda p: p.write_bytes(b"\xff\xfe"),
        lambda p: p.write_text('{"schemas": 42}', encoding="utf-8"),
    ],
    ids=["json_roto", "no_utf8", "estructura"],
)
def test_un_manifiesto_invalido_no_compila_ningun_esquema(
    romper_manifiesto, tmp_path, registro_limpio
):
    """Fallo cerrado: no hay registro, ni compilación, ni respaldo sin verificar."""
    copia = _copia_del_paquete(tmp_path)
    romper_manifiesto(_manifiesto(copia))

    with _bundle_apuntando_a(copia):
        get_verified_schema_registry.cache_clear()
        bundle.compilar.cache_clear()
        with pytest.raises(ValidatorConfigurationError):
            get_verified_schema_registry()
        # Ningún esquema quedó compilado, y el registro no se cacheó.
        assert bundle.compilar.cache_info().currsize == 0
        assert get_verified_schema_registry.cache_info().currsize == 0


# ─────────────────────────────────────────────────────────────────────────────
# R3 · Unicidad de la clave de enrutado de producción
#
# El fingerprint cubre los BYTES de los `*.xsd`; los metadatos de enrutado del
# manifiesto —`root` y `namespace`— no. Así que un manifiesto podía conservar
# ids, rutas y bytes aprobados, **pasar la puerta**, y aun así asignar la misma
# `(raíz, namespace)` a dos esquemas. El registro los metía en un diccionario y
# el segundo pisaba al primero sin decir nada.
#
# El daño no era quedarse corto de rutas: era **validar contra el esquema
# equivocado**. Con TE usurpando la clave de FE, toda factura electrónica
# pasaba a validarse contra el esquema de tiquete.
# ─────────────────────────────────────────────────────────────────────────────

#: Las cinco rutas de comprobante del paquete aprobado. `w3c.xmldsig` no está:
#: es una dependencia compartida, no la raíz de ningún documento.
RUTAS_APROBADAS = {
    "FacturaElectronica": "cr.fe.v4_4",
    "TiqueteElectronico": "cr.te.v4_4",
    "NotaCreditoElectronica": "cr.nc.v4_4",
    "NotaDebitoElectronica": "cr.nd.v4_4",
    "MensajeHacienda": "cr.mh.v4_4",
}


def _duplicar_ruta(copia: Path, usurpador: str, victima: str) -> None:
    """Hace que `usurpador` reutilice la clave de enrutado de `victima`.

    Toca **solo** los metadatos de enrutado. Ids, rutas relativas y bytes de
    los `*.xsd` quedan intactos, que es justo lo que hace que la puerta siga
    aprobando el paquete.
    """
    ruta = copia / "MANIFEST.json"
    doc = json.loads(ruta.read_text(encoding="utf-8"))
    objetivo = next(e for e in doc["schemas"] if e["id"] == victima)
    entrada = next(e for e in doc["schemas"] if e["id"] == usurpador)
    entrada["root"], entrada["namespace"] = objetivo["root"], objetivo["namespace"]
    ruta.write_text(json.dumps(doc, indent=2), encoding="utf-8")


@pytest.mark.parametrize(
    ("usurpador", "victima"),
    [
        ("cr.te.v4_4", "cr.fe.v4_4"),
        ("cr.nd.v4_4", "cr.nc.v4_4"),
        ("cr.mh.v4_4", "cr.fe.v4_4"),
    ],
    ids=["te_usurpa_fe", "nd_usurpa_nc", "mh_usurpa_fe"],
)
def test_una_clave_de_enrutado_duplicada_impide_inicializar(
    usurpador, victima, tmp_path, registro_limpio
):
    """La aserción central de R3: dos esquemas no pueden compartir ruta."""
    copia = _copia_del_paquete(tmp_path)
    _duplicar_ruta(copia, usurpador, victima)

    # 1 · La puerta aprobada SIGUE pasando: ids, rutas y bytes no cambiaron.
    #     Esto es lo que hacía invisible el fallo — y sigue siendo correcto,
    #     porque la política responde de los ficheros, no del enrutado.
    assert policy.verify_approved_schema_bundle(copia)

    with _bundle_apuntando_a(copia):
        get_verified_schema_registry.cache_clear()
        bundle.compilar.cache_clear()

        with pytest.raises(ValidatorConfigurationError) as exc:
            get_verified_schema_registry()

        # 2 · Falla ANTES de compilar: ni un solo esquema llegó a compilarse.
        assert bundle.compilar.cache_info().currsize == 0
        assert bundle.compilar.cache_info().misses == 0
        # 3 · No queda registro cacheado ni se devolvió ninguno.
        assert get_verified_schema_registry.cache_info().currsize == 0

    assert exc.value.code == "validator_bundle_invalid"


def test_el_error_de_ruta_duplicada_no_revela_configuracion(
    tmp_path, registro_limpio
):
    """Mensaje fijo y seguro: ni ruta temporal, ni manifiesto, ni namespace."""
    copia = _copia_del_paquete(tmp_path)
    _duplicar_ruta(copia, "cr.te.v4_4", "cr.fe.v4_4")

    error = _inicializar_esperando_rechazo(copia)

    _assert_publico_seguro(error, tmp_path)
    assert NS not in str(error)
    assert "cr.te.v4_4" not in str(error)
    # El motivo canónico sí identifica el problema, encadenado por dentro.
    assert registry_modulo.RAZON_RUTA_DUPLICADA in str(error.__cause__)


def test_el_manifiesto_aprobado_declara_cinco_rutas_unicas():
    """Cardinalidad normal del paquete real. No se infiere del conteo:
    se asserta la unicidad entrada por entrada y a quién apunta cada una."""
    con_raiz = [e for e in bundle.entries() if e.root is not None]
    claves = [(e.root, e.namespace) for e in con_raiz]

    assert len(claves) == 5
    assert len(set(claves)) == 5, "hay claves de enrutado repetidas"
    assert {e.root for e in con_raiz} == set(RUTAS_APROBADAS)
    for entrada in con_raiz:
        assert RUTAS_APROBADAS[entrada.root] == entrada.id

    # `w3c.xmldsig` es dependencia compartida, no ruta de documento.
    xmldsig = next(e for e in bundle.entries() if e.id == "w3c.xmldsig")
    assert xmldsig.root is None


def test_el_registro_de_produccion_expone_cinco_rutas_unicas():
    """Lo mismo, pero sobre el registro que usa el parser de verdad."""
    registro = get_verified_schema_registry()
    rutas = registro._por_clave

    assert len(rutas) == 5
    assert len({clave for clave in rutas}) == 5
    for (raiz, namespace), (entrada, _esquema) in rutas.items():
        assert RUTAS_APROBADAS[raiz] == entrada.id
        assert (entrada.root, entrada.namespace) == (raiz, namespace)

    # Cada esquema aparece exactamente una vez: ninguno pisó a otro.
    assert sorted(e.id for e, _ in rutas.values()) == sorted(RUTAS_APROBADAS.values())


def test_la_unicidad_se_comprueba_sin_construir_el_diccionario_primero():
    """Guardia sobre el fuente: comparar longitudes a posteriori ya habría
    perdido cuál de los dos esquemas ganó."""
    fuente = Path(registry_modulo.__file__).read_text(encoding="utf-8")
    assert "vistas" in fuente
    assert "if clave in vistas:" in fuente
