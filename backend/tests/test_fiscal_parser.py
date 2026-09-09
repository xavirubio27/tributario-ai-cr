"""Parser fiscal de producción — sobre y partes (B1).

Contrato probado contra los **13 comprobantes reales** del corpus. El parser
es puro: estos tests no abren conexión a la base de datos, no necesitan
usuario autenticado y no conocen `company_id`.

Lo que B1 **no** normaliza —líneas, impuestos, descuentos y referencias— no se
prueba aquí porque no existe: no se finge cobertura.
"""

from __future__ import annotations

import copy
import dataclasses
import json
import re
import socket
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from lxml import etree

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

def test_el_resultado_no_finge_normalizar_lo_que_no_normaliza():
    """En B1 este test comprobaba que `lines` y `references` NO existían:
    devolver listas vacías habría sugerido «se buscó y no había» en vez de
    «no está implementado». B2 los implementa de verdad, así que ahora
    existen — y lo que se comprueba es lo que sigue siendo cierto: el
    agregado no finge cubrir lo que el modelo aprobado deja fuera.

    Los hijos de línea viven en la línea, no aplanados en el agregado.
    """
    resultado = parse_fiscal_document(_bytes(_comprobantes()[0]))
    campos = resultado.__dataclass_fields__
    assert "lines" in campos and "references" in campos
    # Ni `taxes` ni `discounts` cuelgan del documento: son de cada línea.
    for aplanado in ("taxes", "discounts", "tax_code", "tax_rate", "tax_amount"):
        assert aplanado not in campos


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
    "tipo, numero", [("", "3101123456"), ("", "")],
)
def test_la_identificacion_no_admite_un_tipo_vacio(tipo, numero):
    """En B1 este test exigía también `numero` no vacío. B2-R3 lo corrigió:
    `Tipo` es enumerado (01..06) y el vacío no está entre sus valores, pero
    `Numero` es `xs:string` con `maxLength=20` y **sin `minLength`**, así que
    para él la cadena vacía sí es un estado legal de la fuente.

    La asimetría es del esquema oficial, no nuestra."""
    with pytest.raises(ValueError):
        Identificacion(tipo=tipo, numero=numero)


def test_la_identificacion_si_admite_un_numero_vacio():
    assert Identificacion(tipo="01", numero="").numero == ""


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


# ═════════════════════════════════════════════════════════════════════════════
# B2 · Cuerpo de la transacción: líneas, descuentos, impuestos y referencias
# ═════════════════════════════════════════════════════════════════════════════

from app.fiscal.models import (          # noqa: E402
    REFERENCIAS_POR_TIPO,
    ParsedDocumentLine,
    ParsedDocumentReference,
    ParsedLineDiscount,
    ParsedLineTax,
)
from app.fiscal.models import ParsedElectronicDocument  # noqa: E402
from app.fiscal.parser.document import RAICES_SOPORTADAS  # noqa: E402

# ─────────────────────────────────────────────────────────────────────────────
# Tabla de expectativas ESTÁTICA.
#
# Estos números NO salen del parser. Se obtuvieron inspeccionando el XML de
# cada comprobante directamente con lxml, contando `LineaDetalle`,
# `Descuento`, `Impuesto` e `InformacionReferencia`. Si el parser se
# equivocara, esta tabla no se equivocaría con él — que es justamente para lo
# que está.
#
#                                         líneas, descuentos, impuestos, refs
# ─────────────────────────────────────────────────────────────────────────────
COBERTURA_REAL: dict[str, tuple[str, int, int, int, int]] = {
    "003101354271-FC-00300045010000126295":         ("invoice",     6, 0, 6, 0),
    "50601082600310161019803900001010004596121100": ("invoice",     7, 1, 7, 0),
    "50602082600310161019800100024010059940227200": ("invoice",     1, 0, 1, 0),
    "50603082600060362024500100002010000010585199": ("invoice",     1, 0, 1, 0),
    "50607072600310100718611000011010000006677144": ("invoice",     2, 0, 2, 0),
    "50619062600310111260300100008010000004706367": ("invoice",     2, 0, 2, 0),
    "50621052600310192688300100031010000000011134": ("invoice",     4, 0, 4, 0),
    "FACTURA_TC_S1505447W":                         ("invoice",     1, 0, 1, 0),
    "FE-50614082600020768066800100001010000000021": ("invoice",     1, 0, 1, 0),
    "FE-50627072600011276035800100001010000000741": ("invoice",     1, 0, 1, 0),
    "fe-50626052600310295087500100001010000000033": ("invoice",     1, 0, 1, 0),
    "NC-50631082600310181576400100001030000001522": ("credit_note", 1, 0, 1, 1),
    "Comprobante_Electronico_50630062600310174582": ("ticket",      1, 0, 1, 0),
}

#: Totales agregados del corpus, contados a mano sobre la tabla de arriba.
TOTALES_REALES = {"lineas": 29, "descuentos": 1, "impuestos": 29, "referencias": 1}


def _fixture(prefijo: str) -> Path:
    """Localiza un comprobante por prefijo de nombre.

    Se busca SOLO entre `fe/`, `te/` y `nc/`: cada comprobante comparte los
    primeros 44 caracteres de su nombre con el `MensajeHacienda` que responde
    a su Clave, así que un `rglob` sobre todo el corpus devolvía a veces el MH
    —que no es un comprobante— según el orden del sistema de ficheros.
    """
    candidatos = [
        FIXTURES / rel for rel in _comprobantes()
        if Path(rel).name.startswith(prefijo)
    ]
    if len(candidatos) != 1:
        raise AssertionError(
            f"el prefijo {prefijo!r} identifica {len(candidatos)} comprobantes"
        )
    return candidatos[0]


def _parseado(prefijo: str):
    return parse_fiscal_document(_fixture(prefijo).read_bytes())


def test_la_tabla_de_expectativas_cubre_los_trece_comprobantes():
    """Guardia de la propia tabla: si entra un fixture nuevo, este test avisa
    antes de que los demás lo ignoren en silencio."""
    assert len(COBERTURA_REAL) == 13
    assert len(_comprobantes()) == 13
    for prefijo in COBERTURA_REAL:
        assert _fixture(prefijo).exists()
    assert sum(v[1] for v in COBERTURA_REAL.values()) == TOTALES_REALES["lineas"]
    assert sum(v[2] for v in COBERTURA_REAL.values()) == TOTALES_REALES["descuentos"]
    assert sum(v[3] for v in COBERTURA_REAL.values()) == TOTALES_REALES["impuestos"]
    assert sum(v[4] for v in COBERTURA_REAL.values()) == TOTALES_REALES["referencias"]


@pytest.mark.parametrize("prefijo", sorted(COBERTURA_REAL), ids=lambda p: p[:28])
def test_cada_comprobante_real_produce_el_cuerpo_esperado(prefijo):
    """Contrato sobre el corpus real, contra números inspeccionados aparte."""
    tipo, n_lineas, n_desc, n_imp, n_refs = COBERTURA_REAL[prefijo]
    doc = _parseado(prefijo)

    # B1 sigue intacto.
    assert doc.document.document_type == tipo
    assert doc.issuer is not None and doc.issuer.legal_name

    assert len(doc.lines) == n_lineas
    assert sum(len(l.discounts) for l in doc.lines) == n_desc
    assert sum(len(l.taxes) for l in doc.lines) == n_imp
    assert len(doc.references) == n_refs


def test_totales_y_maximos_del_corpus_real():
    """Los agregados que la ronda declara, medidos sobre los 13 comprobantes."""
    lineas = desc = imp = refs = 0
    max_lineas = max_desc = max_imp = max_refs = 0
    for prefijo in COBERTURA_REAL:
        doc = _parseado(prefijo)
        lineas += len(doc.lines); refs += len(doc.references)
        max_lineas = max(max_lineas, len(doc.lines))
        max_refs = max(max_refs, len(doc.references))
        for l in doc.lines:
            desc += len(l.discounts); imp += len(l.taxes)
            max_desc = max(max_desc, len(l.discounts))
            max_imp = max(max_imp, len(l.taxes))

    assert (lineas, desc, imp, refs) == (
        TOTALES_REALES["lineas"], TOTALES_REALES["descuentos"],
        TOTALES_REALES["impuestos"], TOTALES_REALES["referencias"],
    )
    # Máximos observados. Que el máximo de descuentos, impuestos y referencias
    # sea 1 es un HUECO DE CORPUS declarado, no una cota del formato: el XSD
    # admite 0..5, 1..1000 y 0..10 respectivamente.
    assert (max_lineas, max_desc, max_imp, max_refs) == (7, 1, 1, 1)


# ── Valores exactos, leídos del XML fuente ───────────────────────────────────

def test_valores_exactos_de_una_linea_con_descuento():
    """FE 50601… línea 6: la única línea del corpus con `Descuento`."""
    doc = _parseado("50601082600310161019803900001010004596121100")
    linea = doc.lines[5]

    assert linea.line_number == 6
    assert linea.cabys_code == "8422200000000"
    assert linea.description == "500MBPS/500MBPS_FTTH_LY_2025_FMC"
    assert linea.unit_of_measure_code == "Os"
    assert linea.reported_quantity == Decimal("1")
    assert linea.reported_unit_price == Decimal("58210.99")
    assert linea.reported_gross_amount == Decimal("58210.99")
    assert linea.reported_subtotal == Decimal("19110.90")
    assert linea.reported_taxable_base == Decimal("19110.90")
    assert linea.reported_net_tax == Decimal("2484.42")
    assert linea.reported_line_total == Decimal("21595.32")

    assert len(linea.discounts) == 1
    assert linea.discounts[0] == ParsedLineDiscount(
        reported_amount=Decimal("39100.09"), discount_code="07"
    )

    assert len(linea.taxes) == 1
    assert linea.taxes[0] == ParsedLineTax(
        tax_code="01", reported_amount=Decimal("2484.42"),
        vat_rate_code="08", reported_rate=Decimal("13"),
    )


def test_valores_exactos_del_tiquete():
    doc = _parseado("Comprobante_Electronico_50630062600310174582")
    linea = doc.lines[0]

    assert (linea.line_number, linea.cabys_code) == (1, "9723000000200")
    assert linea.unit_of_measure_code == "Os"
    assert linea.reported_unit_price == Decimal("100")
    assert linea.reported_subtotal == Decimal("100")
    assert linea.reported_taxable_base == Decimal("100")
    assert linea.reported_net_tax == Decimal("13")
    assert linea.reported_line_total == Decimal("113")
    assert linea.discounts == ()
    assert linea.taxes[0].tax_code == "01"
    assert linea.taxes[0].vat_rate_code == "08"
    assert linea.taxes[0].reported_amount == Decimal("13")


def test_el_literal_decimal_se_conserva_tal_cual():
    """`Decimal` desde el literal, no vía `float`: la escala de la fuente
    sobrevive. El corpus escribe la misma tarifa como '13', '13.00' y
    '13.00000', y las tres deben distinguirse aunque valgan lo mismo."""
    te = _parseado("Comprobante_Electronico_50630062600310174582")
    nc = _parseado("NC-50631082600310181576400100001030000001522")

    assert str(te.lines[0].taxes[0].reported_rate) == "13"
    assert str(nc.lines[0].taxes[0].reported_rate) == "13.00"
    # Numéricamente iguales, textualmente distintos: eso es preservar la fuente.
    assert te.lines[0].taxes[0].reported_rate == nc.lines[0].taxes[0].reported_rate
    assert str(te.lines[0].taxes[0].reported_rate) != str(
        nc.lines[0].taxes[0].reported_rate
    )


def test_ningun_importe_de_linea_pasa_por_float():
    """Guardia sobre la fuente del parser."""
    fuente = Path(parse_fiscal_document.__module__.replace(".", "/") + ".py")
    texto = (Path(__file__).parents[1] / "app/fiscal/parser/document.py").read_text(
        encoding="utf-8"
    )
    assert "float(" not in texto


# ── Orden y numeración de la fuente ──────────────────────────────────────────

def test_se_conserva_el_orden_del_documento_y_el_numero_declarado():
    """El orden es el del XML; `line_number` sale de `NumeroLinea`, no de la
    posición. En este corpus coinciden — y el test lo comprueba sin **derivar**
    uno del otro."""
    doc = _parseado("50601082600310161019803900001010004596121100")
    assert [l.line_number for l in doc.lines] == [1, 2, 3, 4, 5, 6, 7]
    # La línea con descuento es la 6ª del documento: si el parser reordenara,
    # el descuento aparecería en otra posición.
    assert [i for i, l in enumerate(doc.lines) if l.discounts] == [5]


def test_el_parser_no_renumera_ni_repara_la_numeracion():
    """Sobre un documento cuyo `NumeroLinea` no sigue la posición, el parser
    reporta lo que dice la fuente. Se construye en MEMORIA a partir de un
    comprobante real: no se toca ningún byte versionado."""
    crudo = _fixture("50607072600310100718611000011010000006677144").read_bytes()
    arbol = etree.fromstring(crudo)
    ns = arbol.tag[1:].split("}")[0]
    lineas = arbol.findall(f".//{{{ns}}}LineaDetalle")
    assert len(lineas) == 2
    # Se intercambian los NumeroLinea sin mover los elementos.
    a = lineas[0].find(f"{{{ns}}}NumeroLinea")
    b = lineas[1].find(f"{{{ns}}}NumeroLinea")
    a.text, b.text = b.text, a.text

    doc = parse_fiscal_document(etree.tostring(arbol))
    # Orden del documento intacto; numeración tal y como quedó en la fuente.
    assert [l.line_number for l in doc.lines] == [2, 1]


# ── Multiplicidad ────────────────────────────────────────────────────────────

def test_el_modelo_admite_varios_descuentos_e_impuestos_por_linea():
    """**Cobertura de contrato, no de fixture real.**

    El corpus real no contiene ninguna línea con más de un descuento ni con
    más de un impuesto — máximo observado: 1 y 1—. El XSD sí los admite
    (0..5 y 1..1000), así que el modelo y el bucle de extracción deben
    soportarlos. Esto se prueba a nivel de MODELO, sin fabricar un
    comprobante de aspecto auténtico que fingiera cobertura real.
    """
    linea = ParsedDocumentLine(
        line_number=1, cabys_code="8422200000000", description="x",
        unit_of_measure_code="Os", reported_quantity=Decimal("1"),
        reported_unit_price=Decimal("1"), reported_gross_amount=Decimal("1"),
        reported_subtotal=Decimal("1"), reported_taxable_base=Decimal("1"),
        reported_net_tax=Decimal("0"), reported_line_total=Decimal("1"),
        discounts=(
            ParsedLineDiscount(reported_amount=Decimal("1.00"), discount_code="01"),
            ParsedLineDiscount(reported_amount=Decimal("2.00"), discount_code="07"),
        ),
        taxes=(
            ParsedLineTax(tax_code="01", reported_amount=Decimal("1")),
            ParsedLineTax(tax_code="07", reported_amount=Decimal("2")),
        ),
    )
    assert len(linea.discounts) == 2 and len(linea.taxes) == 2
    # El orden de la fuente se conserva; no se ordena por código ni por importe.
    assert [d.discount_code for d in linea.discounts] == ["01", "07"]
    assert [t.tax_code for t in linea.taxes] == ["01", "07"]


def test_el_bucle_de_extraccion_recorre_todos_los_descuentos_e_impuestos():
    """Multiplicidad en la EXTRACCIÓN, no solo en el modelo. Se duplica en
    memoria el `Descuento` y el `Impuesto` de un comprobante real —el XSD
    admite hasta 5 y hasta 1000—, sin tocar ningún byte versionado."""
    crudo = _fixture("50601082600310161019803900001010004596121100").read_bytes()
    arbol = etree.fromstring(crudo)
    ns = arbol.tag[1:].split("}")[0]
    linea = arbol.findall(f".//{{{ns}}}LineaDetalle")[5]

    desc = linea.find(f"{{{ns}}}Descuento")
    linea.insert(list(linea).index(desc) + 1, copy.deepcopy(desc))
    imp = linea.find(f"{{{ns}}}Impuesto")
    linea.insert(list(linea).index(imp) + 1, copy.deepcopy(imp))

    doc = parse_fiscal_document(etree.tostring(arbol))
    assert len(doc.lines[5].discounts) == 2
    assert len(doc.lines[5].taxes) == 2
    assert doc.lines[5].discounts[0] == doc.lines[5].discounts[1]


def test_una_linea_sin_descuento_no_inventa_un_descuento_de_cero():
    """Ausente no es cero. Un descuento sintético de `Decimal("0")` haría
    creer que el emisor declaró un descuento nulo."""
    doc = _parseado("Comprobante_Electronico_50630062600310174582")
    assert doc.lines[0].discounts == ()
    assert doc.lines[0].discounts is not None
    assert not any(d.reported_amount == 0 for d in doc.lines[0].discounts)


# ── Referencias ──────────────────────────────────────────────────────────────

def test_la_referencia_real_de_la_nota_de_credito():
    """La NC referencia una FE que **no está en el corpus**. Debe parsear."""
    doc = _parseado("NC-50631082600310181576400100001030000001522")
    assert len(doc.references) == 1
    ref = doc.references[0]

    assert ref.referenced_document_type_code == "01"
    assert ref.reported_number == (
        "50630082600310181576400100001010000022472103888064"
    )
    assert len(ref.reported_number) == 50
    assert ref.reference_code == "01"
    assert ref.reason == "Factura erronea"


def test_la_fecha_de_la_referencia_sigue_adr_039():
    doc = _parseado("NC-50631082600310181576400100001030000001522")
    fecha = doc.references[0].fecha

    assert fecha.raw == "2026-08-31T08:48:19-06:00"
    assert fecha.local == datetime(2026, 8, 31, 8, 48, 19)
    assert fecha.local.tzinfo is None
    assert fecha.offset_minutos == -360
    assert fecha.instante == datetime(2026, 8, 31, 14, 48, 19, tzinfo=timezone.utc)


def test_una_referencia_sin_desplazamiento_no_inventa_zona_horaria():
    """El XSD declara `FechaEmisionIR` como `xs:dateTime`, cuyo desplazamiento
    es opcional. Sin él: reloj de pared y literal; instante y offset a `None`.
    Se prepara en memoria sobre el comprobante real."""
    crudo = _fixture("NC-50631082600310181576400100001030000001522").read_bytes()
    arbol = etree.fromstring(crudo)
    ns = arbol.tag[1:].split("}")[0]
    nodo = arbol.find(f".//{{{ns}}}InformacionReferencia/{{{ns}}}FechaEmisionIR")
    nodo.text = "2026-08-31T08:48:19"

    fecha = parse_fiscal_document(etree.tostring(arbol)).references[0].fecha
    assert fecha.raw == "2026-08-31T08:48:19"
    assert fecha.local == datetime(2026, 8, 31, 8, 48, 19)
    assert fecha.instante is None
    assert fecha.offset_minutos is None


def test_el_parser_no_resuelve_la_referencia():
    """Sin `resolved_document_id` ni nada que se le parezca: resolver es de la
    persistencia (ADR-028), y aquí no hay base de datos."""
    ref = _parseado("NC-50631082600310181576400100001030000001522").references[0]
    campos = {f.name for f in dataclasses.fields(ref)}
    assert campos == {
        "referenced_document_type_code", "fecha",
        "reported_number", "reference_code", "reason",
    }
    assert not any("resolved" in c or "_id" in c for c in campos)


def test_varias_referencias_se_conservan_en_orden():
    """El XSD admite 0..10 (1..10 en NC). El corpus real solo tiene una, así
    que la multiplicidad se prueba duplicando en memoria — cobertura de
    contrato, no de fixture real."""
    crudo = _fixture("NC-50631082600310181576400100001030000001522").read_bytes()
    arbol = etree.fromstring(crudo)
    ns = arbol.tag[1:].split("}")[0]
    ref = arbol.find(f".//{{{ns}}}InformacionReferencia")
    copia = copy.deepcopy(ref)
    copia.find(f"{{{ns}}}Razon").text = "Segunda razon"
    ref.getparent().insert(list(ref.getparent()).index(ref) + 1, copia)

    refs = parse_fiscal_document(etree.tostring(arbol)).references
    assert len(refs) == 2
    assert [r.reason for r in refs] == ["Factura erronea", "Segunda razon"]


def test_un_documento_sin_referencias_devuelve_tupla_vacia():
    doc = _parseado("FACTURA_TC_S1505447W")
    assert doc.references == ()


# ── Campos diferidos ─────────────────────────────────────────────────────────

def test_los_campos_diferidos_no_se_normalizan_ni_hacen_fallar():
    """`CodigoComercial` está en 27 de 29 líneas reales, `TipoTransaccion` en
    14 y `UnidadMedidaComercial` en 5. No están en el modelo aprobado: su
    presencia no rompe nada, y el modelo no finge haberlos normalizado."""
    campos = {f.name for f in dataclasses.fields(ParsedDocumentLine)}
    for diferido in (
        "commercial_code", "codigo_comercial", "transaction_type",
        "commercial_unit", "unidad_medida_comercial", "vin", "medicine_registry",
        "pharmaceutical_form", "assorted_detail", "factory_vat",
        "factory_assumed_tax",
    ):
        assert diferido not in campos

    # Y sin embargo los 13 comprobantes —que los traen— parsean.
    for prefijo in COBERTURA_REAL:
        assert _parseado(prefijo) is not None


def test_la_exoneracion_no_esta_modelada_y_no_se_finge():
    """`Exoneracion` es 0..1 dentro de `Impuesto` en el XSD, pero **no** está
    en el modelo físico aprobado de `line_taxes`, y **no se observa** en
    ninguno de los 29 impuestos del corpus. Queda diferida, declarada."""
    campos = {f.name for f in dataclasses.fields(ParsedLineTax)}
    assert campos == {"tax_code", "reported_amount", "vat_rate_code", "reported_rate"}
    assert not any("exon" in c for c in campos)

    vistos = 0
    for prefijo in COBERTURA_REAL:
        crudo = _fixture(prefijo).read_bytes()
        arbol = etree.fromstring(crudo)
        ns = arbol.tag[1:].split("}")[0]
        vistos += len(arbol.findall(f".//{{{ns}}}Exoneracion"))
    assert vistos == 0, "el corpus ya contiene Exoneracion: hay que revisar el modelo"


# ── Invariantes de modelo ────────────────────────────────────────────────────

def test_invariantes_estructurales_de_los_modelos_hijos():
    base = dict(
        line_number=1, cabys_code="8422200000000", description="x",
        unit_of_measure_code="Os", reported_quantity=Decimal("1"),
        reported_unit_price=Decimal("1"), reported_gross_amount=Decimal("1"),
        reported_subtotal=Decimal("1"), reported_taxable_base=Decimal("1"),
        reported_net_tax=Decimal("0"), reported_line_total=Decimal("1"),
        # `Impuesto` es 1..1000 en el XSD: una línea sin impuesto no es un
        # estado que la fuente pueda expresar (R1).
        taxes=(ParsedLineTax(tax_code="01", reported_amount=Decimal("0")),),
    )
    ParsedDocumentLine(**base)                       # válido

    with pytest.raises(ValueError):
        ParsedDocumentLine(**{**base, "line_number": 0})
    for campo in ("cabys_code", "description", "unit_of_measure_code"):
        with pytest.raises(ValueError):
            ParsedDocumentLine(**{**base, campo: ""})
    with pytest.raises(TypeError):
        ParsedDocumentLine(**{**base, "taxes": []})   # lista, no tupla

    with pytest.raises(ValueError):
        ParsedLineTax(tax_code="", reported_amount=Decimal("1"))
    with pytest.raises(ValueError):
        ParsedLineTax(tax_code="01", reported_amount=Decimal("1"), vat_rate_code="")
    with pytest.raises(ValueError):
        ParsedLineDiscount(reported_amount=Decimal("1"), discount_code="")
    with pytest.raises(ValueError):
        ParsedDocumentReference(
            referenced_document_type_code="", fecha=FechaFiscal(
                local=datetime(2026, 1, 1), raw="2026-01-01T00:00:00"
            ),
        )


def test_el_parser_no_valida_aritmetica_fiscal():
    """Un modelo cuyos importes no cuadran **se construye igual**: reconciliar
    totales es del Tax Engine. Si el parser lo rechazara, estaría emitiendo un
    juicio fiscal disfrazado de invariante estructural."""
    linea = ParsedDocumentLine(
        line_number=1, cabys_code="8422200000000", description="x",
        unit_of_measure_code="Os", reported_quantity=Decimal("2"),
        reported_unit_price=Decimal("10"),
        reported_gross_amount=Decimal("999"),     # ≠ 2 × 10
        reported_subtotal=Decimal("1"), reported_taxable_base=Decimal("1"),
        reported_net_tax=Decimal("500"), reported_line_total=Decimal("0"),
        taxes=(ParsedLineTax(
            tax_code="01", reported_amount=Decimal("0"),
            reported_rate=Decimal("13"),          # 1 × 13% ≠ 0
        ),),
    )
    assert linea.reported_gross_amount == Decimal("999")
    assert linea.taxes[0].reported_amount == Decimal("0")


def test_las_colecciones_del_agregado_son_inmutables():
    doc = _parseado("50601082600310161019803900001010004596121100")
    assert isinstance(doc.lines, tuple)
    assert isinstance(doc.references, tuple)
    assert isinstance(doc.lines[5].discounts, tuple)
    assert isinstance(doc.lines[5].taxes, tuple)

    with pytest.raises(AttributeError):
        doc.lines.append(doc.lines[0])            # type: ignore[attr-defined]
    with pytest.raises(dataclasses.FrozenInstanceError):
        doc.lines[0].line_number = 99             # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        doc.lines[5].taxes[0].tax_code = "99"     # type: ignore[misc]


def test_el_agregado_exige_lineas_y_referencias():
    """No tienen valor por defecto: «no se extrajeron» no puede confundirse
    con «no había»."""
    obligatorios = {
        f.name for f in dataclasses.fields(ParsedFiscalDocument)
        if f.default is dataclasses.MISSING
        and f.default_factory is dataclasses.MISSING  # type: ignore[misc]
    }
    assert {"document", "parties", "lines", "references"} <= obligatorios


def test_ningun_modelo_del_cuerpo_lleva_identidad_de_base_de_datos():
    prohibidos = ("id", "uuid", "company_id", "electronic_document_id",
                  "document_line_id", "resolved_document_id", "tenant")
    for modelo in (ParsedDocumentLine, ParsedLineDiscount, ParsedLineTax,
                   ParsedDocumentReference, ParsedFiscalDocument):
        campos = {f.name for f in dataclasses.fields(modelo)}
        for p in prohibidos:
            assert p not in campos, f"{modelo.__name__} expone {p}"


# ── Privacidad del diagnóstico semántico ─────────────────────────────────────

def test_el_error_semantico_de_linea_no_filtra_contenido():
    """La ruta es estructural —`LineaDetalle[6]/Detalle`—, sin el texto del
    contribuyente. Se vacía en memoria un campo obligatorio."""
    crudo = _fixture("50601082600310161019803900001010004596121100").read_bytes()
    arbol = etree.fromstring(crudo)
    ns = arbol.tag[1:].split("}")[0]
    linea = arbol.findall(f".//{{{ns}}}LineaDetalle")[5]
    detalle = linea.find(f"{{{ns}}}Detalle")
    original = detalle.text
    detalle.text = ""

    with pytest.raises((SemanticParseError, XSDValidationError)) as exc:
        parse_fiscal_document(etree.tostring(arbol))

    publico = str(exc.value)
    assert original not in publico
    assert "500MBPS" not in publico
    assert "<" not in publico


def test_la_ruta_del_error_semantico_identifica_la_posicion():
    """Se ataca directamente al extractor: el XSD atraparía antes casi
    cualquier documento inválido, así que probar la ruta a través de un XML
    completo exigiría fabricar un caso irreal."""
    from app.fiscal.parser import document as modulo

    nodo = etree.fromstring(b"<LineaDetalle><NumeroLinea>3</NumeroLinea></LineaDetalle>")
    with pytest.raises(SemanticParseError) as exc:
        modulo._linea(nodo, 3)
    assert exc.value.contexto["campo"] == "LineaDetalle[3]/CodigoCABYS"

    imp = etree.fromstring(b"<Impuesto><Codigo>01</Codigo></Impuesto>")
    with pytest.raises(SemanticParseError) as exc:
        modulo._impuesto(imp, "LineaDetalle[3]/Impuesto[1]")
    assert exc.value.contexto["campo"] == "LineaDetalle[3]/Impuesto[1]/Monto"


# ── Integridad del corpus y del pipeline ─────────────────────────────────────

def test_no_se_ha_tocado_ningun_byte_de_los_fixtures():
    """B2 muta SOLO en memoria. Los ficheros del corpus quedan intactos."""
    import subprocess
    salida = subprocess.run(
        ["git", "status", "--porcelain", "backend/tests/fixtures/fiscal/"],
        cwd=Path(__file__).parents[2], capture_output=True, text=True,
    ).stdout.strip()
    assert salida == "", f"fixtures modificados: {salida}"


def test_b2_no_introduce_un_segundo_parseo_de_xml():
    """La extracción trabaja sobre el árbol ya validado. Un `fromstring` por
    línea sería una segunda configuración de parseo que mantener."""
    texto = (Path(__file__).parents[1] / "app/fiscal/parser/document.py").read_text(
        encoding="utf-8"
    )
    assert texto.count("etree.fromstring(") == 1
    assert "etree.parse(" not in texto


# ═════════════════════════════════════════════════════════════════════════════
# B2-R1 · Fidelidad del estado vacío en la referencia, y cardinalidades
# ═════════════════════════════════════════════════════════════════════════════

# ─────────────────────────────────────────────────────────────────────────────
# MEDIUM · `Numero` y `Razon` distinguen TRES estados
#
# Los cuatro XSD oficiales declaran ambos como 0..1 y `xs:string` **sin
# `minLength`**. Al no haber mínimo, la cadena vacía es un valor legal, así que
# la fuente puede decir tres cosas y no dos:
#
#     ausente          → None
#     presente vacío   → ""
#     con texto        → el texto reportado
#
# El parser fundía los dos primeros con `… or None`, y la base de datos
# rechazaba el vacío con `char_length >= 1`. Los dos extremos discrepaban de la
# fuente, y entre ellos no discrepaban — que es lo que lo hacía invisible.
#
# **Cobertura de contrato/XSD, no de fixture real.** El único comprobante con
# referencia del corpus la trae con texto en los dos campos. Estos casos se
# preparan mutando en memoria, y cada uno se valida contra el esquema oficial
# ANTES de afirmar nada.
# ─────────────────────────────────────────────────────────────────────────────

NS_NC = "https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.4/notaCreditoElectronica"


def _nc_con_referencia(campo: str, estado: str) -> bytes:
    """Devuelve la NC real con `campo` en el estado pedido. Solo en memoria."""
    arbol = etree.fromstring(
        _fixture("NC-50631082600310181576400100001030000001522").read_bytes()
    )
    ns = arbol.tag[1:].split("}")[0]
    ref = arbol.find(f".//{{{ns}}}InformacionReferencia")
    nodo = ref.find(f"{{{ns}}}{campo}")
    if estado == "ausente":
        ref.remove(nodo)
    elif estado == "vacio":
        nodo.text = None
    elif estado != "con_texto":
        raise AssertionError(estado)
    return etree.tostring(arbol)


def _valida_contra_el_esquema_oficial(datos: bytes) -> bool:
    _entrada, esquema = get_verified_schema_registry().para(
        "NotaCreditoElectronica", NS_NC
    )
    return bool(esquema.validate(etree.fromstring(datos).getroottree()))


@pytest.mark.parametrize("campo", ["Numero", "Razon"])
@pytest.mark.parametrize("estado", ["ausente", "vacio", "con_texto"])
def test_los_tres_estados_son_xsd_validos(campo, estado):
    """Primero la premisa: el esquema oficial acepta los tres. Sin esto, el
    resto del apartado estaría probando una situación imposible."""
    assert _valida_contra_el_esquema_oficial(_nc_con_referencia(campo, estado))


@pytest.mark.parametrize(
    ("campo", "estado", "esperado"),
    [
        ("Numero", "ausente",   None),
        ("Numero", "vacio",     ""),
        ("Numero", "con_texto", "50630082600310181576400100001010000022472103888064"),
        ("Razon",  "ausente",   None),
        ("Razon",  "vacio",     ""),
        ("Razon",  "con_texto", "Factura erronea"),
    ],
    ids=lambda v: v if isinstance(v, str) and len(v) < 12 else "",
)
def test_el_parser_conserva_los_tres_estados(campo, estado, esperado):
    doc = parse_fiscal_document(_nc_con_referencia(campo, estado))
    obtenido = (
        doc.references[0].reported_number if campo == "Numero"
        else doc.references[0].reason
    )
    assert obtenido == esperado
    # La distinción es de identidad, no solo de valor: `""` no es `None`.
    if estado == "vacio":
        assert obtenido is not None
        assert obtenido == ""
    if estado == "ausente":
        assert obtenido is None


def test_el_vacio_no_se_colapsa_por_veracidad():
    """`"" or None` da `None`. La extracción es consciente de la PRESENCIA del
    elemento, no de si su texto es «verdadero»."""
    vacio = parse_fiscal_document(_nc_con_referencia("Razon", "vacio")).references[0]
    ausente = parse_fiscal_document(_nc_con_referencia("Razon", "ausente")).references[0]
    assert vacio.reason == "" and ausente.reason is None
    assert vacio.reason != ausente.reason

    fuente = (Path(__file__).parents[1] / "app/fiscal/parser/document.py").read_text(
        encoding="utf-8"
    )
    assert '_texto(_hijo(nodo, "Numero")) or None' not in fuente
    assert '_texto(_hijo(nodo, "Razon")) or None' not in fuente


def test_el_texto_del_contribuyente_no_se_recorta():
    """`xs:string` tiene `whiteSpace=preserve` y estos campos no traen patrón:
    recortar alteraría el valor reportado."""
    arbol = etree.fromstring(
        _fixture("NC-50631082600310181576400100001030000001522").read_bytes()
    )
    ns = arbol.tag[1:].split("}")[0]
    ref = arbol.find(f".//{{{ns}}}InformacionReferencia")
    ref.find(f"{{{ns}}}Razon").text = "  Factura erronea  "
    datos = etree.tostring(arbol)

    assert _valida_contra_el_esquema_oficial(datos)
    assert parse_fiscal_document(datos).references[0].reason == "  Factura erronea  "


def test_el_codigo_de_referencia_no_admite_vacio():
    """La asimetría es de la fuente: `CodigoReferenciaType` declara
    `minLength=maxLength=2`, así que ahí el vacío no es un estado legal."""
    with pytest.raises(ValueError):
        ParsedDocumentReference(
            referenced_document_type_code="01",
            fecha=FechaFiscal(local=datetime(2026, 1, 1), raw="2026-01-01T00:00:00"),
            reference_code="",
        )
    # Y sin embargo `Numero` y `Razon` vacíos SÍ se aceptan.
    ref = ParsedDocumentReference(
        referenced_document_type_code="01",
        fecha=FechaFiscal(local=datetime(2026, 1, 1), raw="2026-01-01T00:00:00"),
        reported_number="", reason="",
    )
    assert ref.reported_number == "" and ref.reason == ""


def test_todo_estado_del_parser_cabe_en_el_modelo_fisico():
    """Contrato de representabilidad: parser y modelo físico ya no discrepan.

    Se comprueban los límites del CHECK **sin persistir nada** — B2 no
    implementa persistencia—: para cada estado que el parser puede producir
    existe un valor que la restricción física acepta.
    """
    limites = {"reported_number": 50, "reason": 180}
    for campo, maximo in limites.items():
        for valor in (None, "", "x", "x" * maximo):
            ref = ParsedDocumentReference(
                referenced_document_type_code="01",
                fecha=FechaFiscal(local=datetime(2026, 1, 1), raw="2026-01-01T00:00:00"),
                **{campo: valor},
            )
            obtenido = getattr(ref, campo)
            assert obtenido == valor
            # La regla física es: NULL, o longitud entre 0 y el máximo.
            assert obtenido is None or 0 <= len(obtenido) <= maximo


# ─────────────────────────────────────────────────────────────────────────────
# LOW · Cardinalidades estructurales en la construcción directa
#
# Por el contrato público no se puede llegar aquí: el XSD ya rechazó el
# documento. Estas guardas protegen la OTRA puerta —construir el modelo a
# mano—, que no pasa por ningún validador.
# ─────────────────────────────────────────────────────────────────────────────

def _linea_valida(**cambios):
    base = dict(
        line_number=1, cabys_code="8422200000000", description="x",
        unit_of_measure_code="Os", reported_quantity=Decimal("1"),
        reported_unit_price=Decimal("1"), reported_gross_amount=Decimal("1"),
        reported_subtotal=Decimal("1"), reported_taxable_base=Decimal("1"),
        reported_net_tax=Decimal("0"), reported_line_total=Decimal("1"),
        taxes=(ParsedLineTax(tax_code="01", reported_amount=Decimal("0")),),
    )
    return ParsedDocumentLine(**{**base, **cambios})


@pytest.mark.parametrize(
    ("numero", "valido"), [(0, False), (1, True), (1000, True), (1001, False)]
)
def test_cardinalidad_de_numero_de_linea(numero, valido):
    """`NumeroLinea`: `minInclusive=1`, `maxInclusive=1000` en el XSD."""
    if valido:
        assert _linea_valida(line_number=numero).line_number == numero
    else:
        with pytest.raises(ValueError):
            _linea_valida(line_number=numero)


@pytest.mark.parametrize("cuantos", [0, 1, 5, 6])
def test_cardinalidad_de_descuentos(cuantos):
    """`Descuento` es 0..5 por línea. Cero es válido: no se exige que haya."""
    descuentos = tuple(
        ParsedLineDiscount(reported_amount=Decimal("1"), discount_code="01")
        for _ in range(cuantos)
    )
    if cuantos <= 5:
        assert len(_linea_valida(discounts=descuentos).discounts) == cuantos
    else:
        with pytest.raises(ValueError):
            _linea_valida(discounts=descuentos)


@pytest.mark.parametrize("cuantos", [0, 1, 1000, 1001])
def test_cardinalidad_de_impuestos(cuantos):
    """`Impuesto` es 1..1000: al menos uno. Es cardinalidad estructural, no
    lógica de Tax Engine — no se dice nada sobre su importe."""
    impuestos = tuple(
        ParsedLineTax(tax_code="01", reported_amount=Decimal("0"))
        for _ in range(cuantos)
    )
    if 1 <= cuantos <= 1000:
        assert len(_linea_valida(taxes=impuestos).taxes) == cuantos
    else:
        with pytest.raises(ValueError):
            _linea_valida(taxes=impuestos)


def test_las_guardas_de_cardinalidad_no_son_aritmetica_fiscal():
    """Una línea con cardinalidades correctas y aritmética absurda se
    construye igual: reconciliar importes sigue siendo del Tax Engine."""
    linea = _linea_valida(
        reported_quantity=Decimal("2"), reported_unit_price=Decimal("10"),
        reported_gross_amount=Decimal("999"),        # ≠ 2 × 10
        reported_line_total=Decimal("0"),
        discounts=(ParsedLineDiscount(
            reported_amount=Decimal("999999"), discount_code="01"),),  # > bruto
        taxes=(ParsedLineTax(
            tax_code="01", reported_amount=Decimal("0"),
            reported_rate=Decimal("13")),),                            # ≠ base×tarifa
    )
    assert linea.reported_gross_amount == Decimal("999")
    assert linea.discounts[0].reported_amount == Decimal("999999")


def test_las_lineas_reales_siguen_dentro_de_las_cardinalidades():
    """Las guardas nuevas no pueden rechazar ninguna de las 29 líneas reales."""
    total = 0
    for prefijo in COBERTURA_REAL:
        for linea in _parseado(prefijo).lines:
            assert 1 <= linea.line_number <= 1000
            assert len(linea.discounts) <= 5
            assert 1 <= len(linea.taxes) <= 1000
            total += 1
    assert total == TOTALES_REALES["lineas"]


# ═════════════════════════════════════════════════════════════════════════════
# B2-R2 · Fidelidad léxica y cardinalidad de referencias en el agregado
# ═════════════════════════════════════════════════════════════════════════════

# ─────────────────────────────────────────────────────────────────────────────
# MEDIUM · El parser no inventa normalización de espacios
#
# Se auditó la cadena de tipos de los VEINTE campos de cadena que B1 y B2
# normalizan, y todos derivan de `xs:string`, cuya faceta es
# `whiteSpace="preserve"`. Ninguno es `xs:token` ni `xs:normalizedString`. El
# esquema oficial NO define normalización de espacios para ninguno de ellos.
#
# El razonamiento «tiene enumeración o patrón, luego recortar es inocuo» no
# vale: la faceta de espacios viene del tipo, no de las demás facetas. Y era
# falso en la práctica — cinco campos admiten espacios en documentos
# XSD-válidos, y en uno el recorte llegaba a RECHAZAR el comprobante.
# ─────────────────────────────────────────────────────────────────────────────

NS_FE = "https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.4/facturaElectronica"


def _fe_con(elemento: str, valor: str, contenedor: str | None = None) -> bytes:
    """FE real con `elemento` puesto a `valor`. Solo en memoria."""
    arbol = etree.fromstring(
        _fixture("50601082600310161019803900001010004596121100").read_bytes()
    )
    ns = arbol.tag[1:].split("}")[0]
    padre = (
        arbol.find(f".//{{{ns}}}{contenedor}") if contenedor else arbol
    )
    nodo = (
        padre.find(f"{{{ns}}}{elemento}") if contenedor
        else arbol.find(f".//{{{ns}}}{elemento}")
    )
    nodo.text = valor
    return etree.tostring(arbol)


def _fe_es_xsd_valida(datos: bytes) -> bool:
    _entrada, esquema = get_verified_schema_registry().para("FacturaElectronica", NS_FE)
    return bool(esquema.validate(etree.fromstring(datos).getroottree()))


#: Los cinco campos que un documento XSD-válido puede traer con espacios.
#: `valor` está elegido para respetar las facetas de longitud de cada tipo.
CAMPOS_CON_ESPACIOS = [
    ("Detalle",               None,             "  Servicio ejemplo  ",
     lambda d: d.lines[0].description),
    ("Nombre",                "Emisor",         "  Nombre emisor  ",
     lambda d: d.issuer.legal_name),
    ("NombreComercial",       "Emisor",         "  Comercial  ",
     lambda d: d.issuer.trade_name),
    ("Numero",                "Identificacion", "   ",
     lambda d: d.issuer.identificacion.numero),
    ("CodigoActividadEmisor", None,             " 1234 ",
     lambda d: d.document.issuer_activity_code),
]


@pytest.mark.parametrize(
    ("elemento", "contenedor", "valor", "leer"),
    CAMPOS_CON_ESPACIOS,
    ids=[c[0] for c in CAMPOS_CON_ESPACIOS],
)
def test_el_espacio_del_literal_xsd_valido_se_conserva(
    elemento, contenedor, valor, leer
):
    """Primero la premisa —el esquema oficial acepta el literal—, y solo
    entonces qué hace el parser con él."""
    datos = _fe_con(elemento, valor, contenedor)
    assert _fe_es_xsd_valida(datos), f"{elemento} con {valor!r} no es XSD-válido"

    assert leer(parse_fiscal_document(datos)) == valor


def test_un_numero_de_identificacion_de_solo_espacios_ya_no_rechaza_el_documento():
    """El caso más grave: `.strip()` convertía `'   '` en `''` y el documento
    XSD-válido acababa rechazado con `SemanticParseError`."""
    datos = _fe_con("Numero", "   ", "Identificacion")
    assert _fe_es_xsd_valida(datos)

    doc = parse_fiscal_document(datos)          # no lanza
    assert doc.issuer.identificacion.numero == "   "


def test_el_parser_no_recorta_ningun_campo_de_cadena_modelado():
    """Guardia sobre el fuente: no queda ningún `_texto(` genérico, y el único
    `.strip()` desapareció en favor de accesores con semántica explícita."""
    fuente = (Path(__file__).parents[1] / "app/fiscal/parser/document.py").read_text(
        encoding="utf-8"
    )
    sin_helpers = fuente.replace("_texto_literal(", "").replace("_texto_colapsado(", "")
    assert "_texto(" not in sin_helpers, "queda un llamante del recorte genérico"
    assert ".strip()" not in fuente, "queda un recorte genérico"


def test_el_colapso_se_aplica_solo_donde_el_tipo_xsd_lo_define():
    """`xs:decimal`, `xs:positiveInteger` y `xs:dateTime` sí declaran
    `whiteSpace="collapse"`: ahí la normalización la define el tipo, no
    nosotros. Y `collapse` no es `strip` — también funde los espacios
    interiores—, así que se implementa tal cual."""
    from app.fiscal.parser import document as modulo

    nodo = etree.fromstring(b"<X>  1  234  </X>")
    assert modulo._texto_colapsado(nodo) == "1 234"
    assert modulo._texto_literal(nodo) == "  1  234  "
    # Ausente y presente-vacío se distinguen en ambos accesores.
    vacio = etree.fromstring(b"<X></X>")
    assert modulo._texto_colapsado(vacio) == ""
    assert modulo._texto_literal(vacio) == ""
    assert modulo._texto_colapsado(None) is None
    assert modulo._texto_literal(None) is None


def test_los_decimales_conservan_su_semantica_exacta():
    """El refactor de cadenas no toca los números: `Decimal` desde el literal,
    sin `float`, con la escala de la fuente intacta."""
    doc = _parseado("50601082600310161019803900001010004596121100")
    assert doc.lines[5].reported_unit_price == Decimal("58210.99")
    assert str(doc.lines[5].taxes[0].reported_rate) == "13"
    te = _parseado("Comprobante_Electronico_50630062600310174582")
    assert str(te.lines[0].taxes[0].reported_rate) == "13"
    nc = _parseado("NC-50631082600310181576400100001030000001522")
    assert str(nc.lines[0].taxes[0].reported_rate) == "13.00"


def test_los_valores_reales_no_cambian_al_dejar_de_recortar():
    """Ningún comprobante real trae espacios en los extremos, así que el
    arreglo no altera un solo valor del corpus. Si algún día los trajera,
    ahora se conservarían."""
    doc = _parseado("50601082600310161019803900001010004596121100")
    assert doc.lines[5].description == "500MBPS/500MBPS_FTTH_LY_2025_FMC"

    # El código de actividad se contrasta contra el LITERAL de la fuente, leído
    # aparte: fijarlo a mano fue un error —este comprobante trae `6110.0`, que
    # además confirma que el XSD pide seis caracteres y no seis dígitos—.
    arbol = etree.fromstring(
        _fixture("50601082600310161019803900001010004596121100").read_bytes()
    )
    ns = arbol.tag[1:].split("}")[0]
    literal = arbol.find(f".//{{{ns}}}CodigoActividadEmisor").text
    assert doc.document.issuer_activity_code == literal

    for prefijo in COBERTURA_REAL:
        d = _parseado(prefijo)
        assert d.document.clave == d.document.clave.strip()
        assert d.issuer.legal_name == d.issuer.legal_name.strip()
        for linea in d.lines:
            assert linea.description == linea.description.strip()
            assert linea.cabys_code == linea.cabys_code.strip()


# ── §14 · R1 sigue en pie ────────────────────────────────────────────────────

def test_r1_no_regresiona_con_el_refactor_de_accesores():
    """Los tres estados de `Numero` y `Razon` siguen distinguiéndose, y ahora
    además el texto con espacios se conserva."""
    assert parse_fiscal_document(
        _nc_con_referencia("Numero", "ausente")
    ).references[0].reported_number is None
    assert parse_fiscal_document(
        _nc_con_referencia("Numero", "vacio")
    ).references[0].reported_number == ""
    assert parse_fiscal_document(
        _nc_con_referencia("Razon", "ausente")
    ).references[0].reason is None
    assert parse_fiscal_document(
        _nc_con_referencia("Razon", "vacio")
    ).references[0].reason == ""

    arbol = etree.fromstring(
        _fixture("NC-50631082600310181576400100001030000001522").read_bytes()
    )
    ns = arbol.tag[1:].split("}")[0]
    arbol.find(f".//{{{ns}}}InformacionReferencia/{{{ns}}}Razon").text = "  Razon  "
    datos = etree.tostring(arbol)
    assert _valida_contra_el_esquema_oficial(datos)
    assert parse_fiscal_document(datos).references[0].reason == "  Razon  "


# ─────────────────────────────────────────────────────────────────────────────
# LOW · Cardinalidad de referencias en el agregado, según el tipo
#
# Verificado elemento por elemento en los cuatro esquemas oficiales:
#
#     invoice 0..10 · ticket 0..10 · credit_note 1..10 · debit_note 1..10
#
# El agregado puede comprobarlo porque conoce su propio `document_type`. Esta
# guarda NO significa que el parser soporte la Nota de Débito: sigue sin
# soporte semántico. Solo dice qué estados del MODELO son representables.
# ─────────────────────────────────────────────────────────────────────────────

def _agregado(document_type: str, n_referencias: int) -> ParsedFiscalDocument:
    sobre = ParsedElectronicDocument(
        document_type=document_type, clave="5" * 50, consecutive_number="0" * 20,
        fecha=FechaFiscal(local=datetime(2026, 1, 1), raw="2026-01-01T00:00:00"),
        issuer_activity_code="620100", sale_condition_code="01", currency_code="CRC",
        reported_exchange_rate=Decimal("1"), reported_total_sale=Decimal("1"),
        reported_total_net_sale=Decimal("1"), reported_total_document=Decimal("1"),
    )
    emisor = ParsedDocumentParty(
        role="issuer", legal_name="Emisor",
        identificacion=Identificacion(tipo="01", numero="1"),
    )
    referencia = ParsedDocumentReference(
        referenced_document_type_code="01",
        fecha=FechaFiscal(local=datetime(2026, 1, 1), raw="2026-01-01T00:00:00"),
    )
    return ParsedFiscalDocument(
        document=sobre, parties=(emisor,), lines=(),
        references=tuple(referencia for _ in range(n_referencias)),
    )


@pytest.mark.parametrize(
    ("tipo", "cuantas", "valido"),
    [
        ("invoice", 0, True), ("invoice", 10, True), ("invoice", 11, False),
        ("ticket", 0, True), ("ticket", 10, True), ("ticket", 11, False),
        ("credit_note", 0, False), ("credit_note", 1, True),
        ("credit_note", 10, True), ("credit_note", 11, False),
        ("debit_note", 0, False), ("debit_note", 1, True),
        ("debit_note", 10, True), ("debit_note", 11, False),
    ],
    ids=lambda v: str(v),
)
def test_cardinalidad_de_referencias_por_tipo(tipo, cuantas, valido):
    if valido:
        assert len(_agregado(tipo, cuantas).references) == cuantas
    else:
        with pytest.raises(ValueError):
            _agregado(tipo, cuantas)


def test_la_tabla_de_cardinalidad_coincide_con_los_esquemas_oficiales():
    """La tabla del modelo no puede divergir del XSD: se lee del paquete."""
    from lxml import etree as _etree
    XS = "{http://www.w3.org/2001/XMLSchema}"
    esperado = {
        "FacturaElectronica_V4.4.xsd": "invoice",
        "TiqueteElectronico_V4.4.xsd": "ticket",
        "NotaCreditoElectronica_V4.4.xsd": "credit_note",
        "NotaDebitoElectronica_V4.4.xsd": "debit_note",
    }
    for fichero, tipo in esperado.items():
        raiz = _etree.parse(
            str(bundle.BUNDLE / "esquemas" / "v4_4" / fichero)
        ).getroot()
        el = next(
            e for e in raiz.iter(f"{XS}element")
            if e.get("name") == "InformacionReferencia"
        )
        del_xsd = (int(el.get("minOccurs", "1")), int(el.get("maxOccurs", "1")))
        assert REFERENCIAS_POR_TIPO[tipo] == del_xsd, tipo


def test_la_guarda_de_referencias_no_implica_soporte_de_nota_de_debito():
    """Construir el modelo con `debit_note` es representable; PARSEAR una ND
    sigue sin estar soportado."""
    assert _agregado("debit_note", 1).document.document_type == "debit_note"
    assert "NotaDebitoElectronica" not in RAICES_SOPORTADAS


def test_la_nota_de_credito_real_cumple_su_cardinalidad():
    doc = _parseado("NC-50631082600310181576400100001030000001522")
    assert doc.document.document_type == "credit_note"
    assert len(doc.references) == 1
    minimo, maximo = REFERENCIAS_POR_TIPO["credit_note"]
    assert minimo <= len(doc.references) <= maximo


# ═════════════════════════════════════════════════════════════════════════════
# B2-R3 · `Identificacion/Numero` presente y vacío
#
# Tercer caso del mismo patrón: un elemento OBLIGATORIO cuyo TEXTO puede ser
# vacío. `Numero` es `minOccurs=1` y `xs:string` con `maxLength=20` y SIN
# `minLength` en los cuatro esquemas. `_obligatorio` trataba `""` como ausente
# y el comprobante XSD-válido acababa rechazado.
#
# La distinción que importa NO es vacío/no vacío:
#
#     Identificacion ausente        → identificacion is None
#     Identificacion con Numero=""  → Identificacion(tipo, "")
#
# Colapsar la segunda en la primera diría que el emisor no identificó a la
# parte, cuando sí la identificó — con un número vacío.
#
# Cobertura de contrato/XSD: el corpus real no trae ningún número vacío.
# ═════════════════════════════════════════════════════════════════════════════

def _fe_identificacion(parte: str, valor: str | None) -> bytes:
    """FE real con `<parte>/Identificacion/Numero` puesto a `valor`."""
    arbol = etree.fromstring(
        _fixture("50601082600310161019803900001010004596121100").read_bytes()
    )
    ns = arbol.tag[1:].split("}")[0]
    nodo = arbol.find(f".//{{{ns}}}{parte}/{{{ns}}}Identificacion/{{{ns}}}Numero")
    nodo.text = valor
    return etree.tostring(arbol)


@pytest.mark.parametrize("parte", ["Emisor", "Receptor"])
@pytest.mark.parametrize(
    ("caso", "valor", "esperado"),
    [("vacio", None, ""), ("espacios", "   ", "   "), ("texto", "3101123456", "3101123456")],
    ids=lambda v: v if isinstance(v, str) and len(v) <= 9 else "",
)
def test_el_numero_de_identificacion_conserva_su_estado(parte, caso, valor, esperado):
    datos = _fe_identificacion(parte, valor)
    assert _fe_es_xsd_valida(datos), f"{parte}/Numero {caso} no es XSD-válido"

    doc = parse_fiscal_document(datos)
    quien = doc.issuer if parte == "Emisor" else doc.receiver
    assert quien.identificacion is not None
    assert quien.identificacion.numero == esperado
    # Presente-vacío NO es ausente: la identificación existe.
    assert quien.identificacion.tipo


def test_un_numero_vacio_ya_no_rechaza_el_comprobante():
    """El defecto exacto de R3: `''` se leía como campo obligatorio ausente."""
    datos = _fe_identificacion("Emisor", None)
    assert _fe_es_xsd_valida(datos)
    doc = parse_fiscal_document(datos)          # no lanza
    assert doc.issuer.identificacion.numero == ""


def test_elemento_obligatorio_no_es_lo_mismo_que_cadena_no_vacia():
    """Si el ELEMENTO falta, sigue siendo un fallo semántico. Se ataca al
    extractor: el XSD no dejaría llegar aquí un documento sin `Numero`."""
    from app.fiscal.parser import document as modulo

    nodo = etree.fromstring(
        b"<Emisor><Nombre>X</Nombre>"
        b"<Identificacion><Tipo>01</Tipo></Identificacion></Emisor>"
    )
    with pytest.raises(SemanticParseError) as exc:
        modulo._parte(nodo, "issuer")
    assert exc.value.contexto["campo"] == "issuer/Identificacion/Numero"

    # Con el elemento presente y vacío, en cambio, se construye sin problema.
    nodo = etree.fromstring(
        b"<Emisor><Nombre>X</Nombre>"
        b"<Identificacion><Tipo>01</Tipo><Numero></Numero></Identificacion></Emisor>"
    )
    assert modulo._parte(nodo, "issuer").identificacion.numero == ""


def test_una_identificacion_ausente_no_se_confunde_con_una_vacia():
    """Los dos estados son distintos y ambos representables."""
    ausente = ParsedDocumentParty(role="receiver", legal_name="X", identificacion=None)
    vacia = ParsedDocumentParty(
        role="receiver", legal_name="X",
        identificacion=Identificacion(tipo="01", numero=""),
    )
    assert ausente.identificacion is None
    assert vacia.identificacion is not None and vacia.identificacion.numero == ""
    assert ausente.identificacion != vacia.identificacion


def test_invariantes_de_identificacion():
    """`Tipo` es enumerado (01..06): el vacío no es legal. `Numero` no lo es:
    la asimetría viene de la fuente, no de nosotros."""
    assert Identificacion(tipo="01", numero="").numero == ""
    assert Identificacion(tipo="01", numero=" ").numero == " "
    assert Identificacion(tipo="01", numero="x" * 20).numero == "x" * 20

    with pytest.raises(ValueError):
        Identificacion(tipo="", numero="1")
    # `numero=None` sigue prohibido: si `Identificacion` existe, `Numero` existe.
    with pytest.raises(ValueError):
        Identificacion(tipo="01", numero=None)          # type: ignore[arg-type]


def test_no_se_sintetiza_identificacion_cuando_el_nodo_falta():
    """El receptor sin `Identificacion` da `None`, nunca un objeto con
    valores inventados. Se prueba sobre el extractor porque el XSD de la FE
    exige la identificación del receptor — la ausencia es legal en TE/NC/ND."""
    from app.fiscal.parser import document as modulo

    nodo = etree.fromstring(b"<Receptor><Nombre>Consumidor</Nombre></Receptor>")
    parte = modulo._parte(nodo, "receiver")
    assert parte.identificacion is None
    assert parte.legal_name == "Consumidor"


def test_representabilidad_de_los_estados_de_identificacion():
    """§11 · cada estado fuente→parser cabe en el modelo físico.

    Regla física tras la migración de R3:
      NULL                     → Identificacion ausente
      longitud 0..20           → Identificacion presente
    Y la solidaridad de B0.1: emisor siempre ambos; receptor ambos o ninguno.
    """
    estados = [
        ("receptor sin identificación", None),
        ("Numero vacío",                Identificacion(tipo="01", numero="")),
        ("Numero con espacios",         Identificacion(tipo="01", numero="   ")),
        ("Numero normal",               Identificacion(tipo="01", numero="3101123456")),
        ("Numero de 20",                Identificacion(tipo="01", numero="x" * 20)),
    ]
    for etiqueta, ident in estados:
        parte = ParsedDocumentParty(
            role="receiver", legal_name="X", identificacion=ident
        )
        if ident is None:
            tipo_col, numero_col = None, None
        else:
            tipo_col, numero_col = ident.tipo, ident.numero
        # CHECK de longitud
        assert numero_col is None or 0 <= len(numero_col) <= 20, etiqueta
        # CHECK de solidaridad del receptor: ambos NULL o ninguno
        assert (tipo_col is None) == (numero_col is None), etiqueta
        assert parte.identificacion is ident

    # El emisor exige ambos, y el vacío cuenta como presente.
    emisor = ParsedDocumentParty(
        role="issuer", legal_name="X",
        identificacion=Identificacion(tipo="01", numero=""),
    )
    assert emisor.identificacion.numero == ""


def test_las_identidades_reales_no_cambian():
    """El corpus real no trae ningún número vacío: el arreglo no altera nada."""
    vacios = 0
    for prefijo in COBERTURA_REAL:
        doc = _parseado(prefijo)
        assert doc.issuer.identificacion is not None
        assert doc.issuer.identificacion.numero != ""
        for parte in doc.parties:
            if parte.identificacion is not None and parte.identificacion.numero == "":
                vacios += 1
    assert vacios == 0, "el corpus ya trae identificaciones vacías: revisar"
