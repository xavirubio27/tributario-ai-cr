"""Fixtures fiscales reales v4.4 — integridad de bytes y compatibilidad.

Comprobantes REALES aceptados por Hacienda, organizados por raíz XML bajo
`tests/fixtures/fiscal/real/v4_4/{fe,te,nc,mh}/`. Sus **bytes exactos son parte
de la evidencia del test**: no se parsean y reserializan, no se reformatean, no
se normalizan saltos de línea.

La forma original NO es uniforme entre fixtures —hay CRLF, LF y ficheros de una
sola línea; uno termina en salto de línea y el resto no—. Por eso cada fixture
declara su propia forma esperada en lugar de asumir una común.

Estos tests NO son el parser de producción. Son de integridad de fixture y de
compatibilidad del esquema con datos reales.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from pathlib import Path

import psycopg
import pytest
import xml.etree.ElementTree as ET

from app.db import fiscal_transaction

FIXTURES = Path(__file__).parent / "fixtures" / "fiscal" / "real" / "v4_4"

NS_BASE = "https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.4"
NS = f"{NS_BASE}/facturaElectronica"

# Huellas conocidas. Si un fixture cambia un solo byte, estos tests fallan —
# que es exactamente lo que se busca. `razon` documenta por qué se conserva
# cada uno: sin ella, un fixture redundante sobrevive a cualquier limpieza.
GOLDEN = {
    "fe/50601082600310161019803900001010004596121100000000.xml": {
        "sha256": "a1f639d06c79cedfa01fe6e3ca8fce5b8ad7de9225afe6cbf7054ff6515c8b0b",
        "bytes": 16067,
        "root": "FacturaElectronica",
        "ns": f"{NS_BASE}/facturaElectronica",
        "clave": "50601082600310161019803900001010004596121100000000",
        "consecutive": "03900001010004596121",
        "activity": "6110.0",
        "eol": "CRLF",
        "final_newline": False,
        "razon": "7 líneas, 1 descuento, 2 OtrosCargos, Registrofiscal8707 VACÍO, situación Normal",
    },
    "fe/50602082600310161019800100024010059940227200000000.xml": {
        "sha256": "b9892fad51b9c9d49aa8d04581088ee69b0d2262b2337b880355b53b4ad70ae0",
        "bytes": 10911,
        "root": "FacturaElectronica",
        "ns": f"{NS_BASE}/facturaElectronica",
        "clave": "50602082600310161019800100024010059940227200000000",
        "consecutive": "00100024010059940227",
        "activity": "6110.0",
        "eol": "CRLF",
        "final_newline": False,
        "razon": "situación Contingencia (Clave pos. 42 = 2), 1 línea, 0 descuentos, 2 OtrosCargos",
    },
    "fe/003101354271-FC-00300045010000126295.xml": {
        "sha256": "f000df3bd12834129aa04e8736b26c4d238340061876b4b701f4df9ec09d0645",
        "bytes": 13625,
        "root": "FacturaElectronica",
        "ns": f"{NS_BASE}/facturaElectronica",
        "clave": "50618072600310135427100300045010000126295177787759",
        "consecutive": "00300045010000126295",
        "activity": "4752.1",
        "eol": "NONE",
        "final_newline": False,
        "razon": "dos tarifas de IVA (1.00 y 13.00) + doble TotalDesgloseImpuesto",
    },
    "fe/50619062600310111260300100008010000004706367750753.xml": {
        "sha256": "d2badc61df95b2d68f47fe813e6ce0a75d7e6d92ac556bf2d2bb552d2004ffb7",
        "bytes": 10607,
        "root": "FacturaElectronica",
        "ns": f"{NS_BASE}/facturaElectronica",
        "clave": "50619062600310111260300100008010000004706367750753",
        "consecutive": "00100008010000004706",
        "activity": "5510.1",
        "eol": "NONE",
        "final_newline": False,
        "razon": "sin ningún CodigoComercial + total entero sin decimales (54000)",
    },
    "fe/50621052600310192688300100031010000000011134984857.xml": {
        "sha256": "0f3d42f4ca52d10dc116a5774ba808485dded388279f86acae3c932c3d5ff8d2",
        "bytes": 11800,
        "root": "FacturaElectronica",
        "ns": f"{NS_BASE}/facturaElectronica",
        "clave": "50621052600310192688300100031010000000011134984857",
        "consecutive": "00100031010000000011",
        "activity": "5610.0",
        "eol": "NONE",
        "final_newline": False,
        "razon": "CondicionVentaOtros + PorcentajeOC",
    },
    "fe/FACTURA_TC_S1505447W.xml": {
        "sha256": "2418f97a0a7bd6e8aa73308615884a682ddb7773554a22d0be2d3a523b221e4c",
        "bytes": 9211,
        "root": "FacturaElectronica",
        "ns": f"{NS_BASE}/facturaElectronica",
        "clave": "50626072600310127793604800002010000016133168092442",
        "consecutive": "04800002010000016133",
        "activity": "4641.1",
        "eol": "NONE",
        "final_newline": False,
        "razon": 'decimal ".00" sin cero inicial: rompe parsers ingenuos',
    },
    "fe/fe-50626052600310295087500100001010000000033159073080.xml": {
        "sha256": "58c77765ad8562038b0382ea566053fb311515e77353e8b29c5b4552089feb66",
        "bytes": 9730,
        "root": "FacturaElectronica",
        "ns": f"{NS_BASE}/facturaElectronica",
        "clave": "50626052600310295087500100001010000000033159073080",
        "consecutive": "00100001010000000033",
        "activity": "6201.0",
        "eol": "CRLF",
        "final_newline": False,
        "razon": "USD con TipoCambio de 5 decimales",
    },
    "te/Comprobante_Electronico_50630062600310174582200100001040000006999104246127Signature.xml": {
        "sha256": "c2fcd0baa7099a68e303d87a4bbba57c0ada85a403d7cd82640f99678d29cc0d",
        "bytes": 8918,
        "root": "TiqueteElectronico",
        "ns": f"{NS_BASE}/tiqueteElectronico",
        "clave": "50630062600310174582200100001040000006999104246127",
        "consecutive": "00100001040000006999",
        "activity": "9311.0",
        "eol": "CRLF",
        "final_newline": True,
        "razon": "único TiqueteElectronico: USD, contado con PlazoCredito, SIN Receptor",
    },
    "nc/NC-50631082600310181576400100001030000001522114249307.xml": {
        "sha256": "a7c7765486ced65f58b61b14dcf0884adff08edc47367b5c43ea13a3290c7bea",
        "bytes": 10796,
        "root": "NotaCreditoElectronica",
        "ns": f"{NS_BASE}/notaCreditoElectronica",
        "clave": "50631082600310181576400100001030000001522114249307",
        "consecutive": "00100001030000001522",
        "activity": "6619.0",
        "eol": "CRLF",
        "final_newline": False,
        "razon": "única NotaCredito: aporta el primer InformacionReferencia real",
    },
    "mh/AHC-50631082600310181576400100001030000001522114249307.xml": {
        "sha256": "d40e7485932c953a10128934b677f081e8646aaa2bb30a3e5cec13b78ffd5a7b",
        "bytes": 5776,
        "root": "MensajeHacienda",
        "ns": f"{NS_BASE}/mensajeHacienda",
        "clave": "50631082600310181576400100001030000001522114249307",
        "consecutive": None,
        "activity": None,
        "eol": "LF",
        "final_newline": False,
        "razon": "respuesta de Hacienda emparejada con la NC por Clave",
    },
}

# La NC es el único fixture con referencia a otro comprobante. Se fija aparte
# porque cierra el hueco `InformacionReferencia = 0` detectado en A2-A.
NC = "nc/NC-50631082600310181576400100001030000001522114249307.xml"
MH_DE_LA_NC = "mh/AHC-50631082600310181576400100001030000001522114249307.xml"
NC_REFERENCIA = {
    "tipo_doc_ir": "01",
    "numero": "50630082600310181576400100001010000022472103888064",
    "codigo": "01",
    "cantidad": 1,
}


def _raw(name: str) -> bytes:
    """Lee los bytes tal cual. Sin `text`, sin decodificar, sin normalizar."""
    return (FIXTURES / name).read_bytes()


def _eol(data: bytes) -> str:
    crlf = data.count(b"\r\n")
    lf = data.count(b"\n") - crlf
    cr = data.count(b"\r") - crlf
    if crlf and not lf and not cr:
        return "CRLF"
    if lf and not crlf and not cr:
        return "LF"
    if not (crlf or lf or cr):
        return "NONE"
    return "MIXED"


@pytest.mark.parametrize("name", sorted(GOLDEN))
def test_el_fixture_existe(name):
    assert (FIXTURES / name).is_file(), f"Falta el fixture real {name}"


@pytest.mark.parametrize("name", sorted(GOLDEN))
def test_la_huella_del_fixture_no_cambio(name):
    """Se calcula sobre los BYTES, nunca sobre una reserialización."""
    data = _raw(name)
    assert len(data) == GOLDEN[name]["bytes"], (
        f"El tamaño de {name} cambió: {len(data)} != {GOLDEN[name]['bytes']}"
    )
    real = hashlib.sha256(data).hexdigest()
    assert real == GOLDEN[name]["sha256"], (
        f"El fixture {name} fue modificado.\n"
        f"  esperado {GOLDEN[name]['sha256']}\n"
        f"  obtenido {real}"
    )


@pytest.mark.parametrize("name", sorted(GOLDEN))
def test_el_fixture_conserva_su_forma_original(name):
    """La forma NO es uniforme: cada fixture declara la suya.

    Asumir CRLF para todos —como hacía la versión anterior con solo dos
    fixtures— habría fallado en cuanto entró un fichero de una sola línea.
    """
    data = _raw(name)
    esperado = GOLDEN[name]

    assert _eol(data) == esperado["eol"], (
        f"{name}: los saltos de línea cambiaron de {esperado['eol']} "
        f"a {_eol(data)}"
    )
    assert data.endswith(b"\n") is esperado["final_newline"], (
        f"{name}: el salto de línea final cambió"
    )
    assert data.lstrip().startswith(b"<?xml"), "Se alteró la declaración XML"


@pytest.mark.parametrize("name", sorted(GOLDEN))
def test_cada_golden_declara_por_que_se_conserva(name):
    """Un fixture sin razón documentada es un fixture que nadie podrá podar."""
    razon = GOLDEN[name].get("razon")
    assert razon and len(razon) > 15, f"{name} no documenta su aportación"


# ─────────────────────────────────────────────────────────────────────────────
# Metadatos mínimos — no es el parser de producción
# ─────────────────────────────────────────────────────────────────────────────


def _campo(data: bytes, tag: str) -> str | None:
    """Extrae un campo de primer nivel sin construir un parser.

    Se usa una expresión sobre el texto decodificado únicamente para verificar
    metadatos conocidos. El parser real llegará en una fase posterior; aquí no
    se persiste lógica de normalización.
    """
    m = re.search(rf"<{tag}>([^<]*)</{tag}>", data.decode("utf-8"))
    return m.group(1) if m else None


def _campo_en(data: bytes, contenedor: str, tag: str) -> str | None:
    """Extrae un campo DENTRO de un contenedor concreto.

    `<Numero>` aparece tres veces en la Nota de Crédito —cédula del emisor, del
    receptor y clave del documento referenciado—. Buscar el primero devolvía la
    cédula del emisor: por eso hace falta acotar el ámbito.
    """
    texto = data.decode("utf-8")
    m = re.search(rf"<{contenedor}>(.*?)</{contenedor}>", texto, re.S)
    if not m:
        return None
    inner = re.search(rf"<{tag}>([^<]*)</{tag}>", m.group(1))
    return inner.group(1) if inner else None


@pytest.mark.parametrize("name", sorted(GOLDEN))
def test_metadatos_conocidos_del_fixture(name):
    data = _raw(name)
    esperado = GOLDEN[name]
    texto = data.decode("utf-8")

    assert f"<{esperado['root']}" in texto, (
        f"La raíz de {name} no es {esperado['root']}"
    )
    assert esperado["ns"] in texto, "Falta el namespace estructural de la v4.4"
    assert _campo(data, "Clave") == esperado["clave"]

    if esperado["consecutive"] is not None:
        assert _campo(data, "NumeroConsecutivo") == esperado["consecutive"]
    if esperado["activity"] is not None:
        assert _campo(data, "CodigoActividadEmisor") == esperado["activity"]


@pytest.mark.parametrize(
    "name", sorted(n for n in GOLDEN if GOLDEN[n]["activity"] is not None)
)
def test_el_codigo_de_actividad_real_tiene_seis_caracteres(name):
    """El hallazgo que motivó la corrección de E4-B0, fijado como regresión.

    `6110.0` tiene seis caracteres pero no seis dígitos. Si algún día alguien
    reintroduce un CHECK numérico, este test explica por qué está mal.
    """
    valor = _campo(_raw(name), "CodigoActividadEmisor")
    assert valor is not None
    assert len(valor) == 6, "El XSD exige exactamente 6 caracteres"


def test_al_menos_un_fixture_tiene_actividad_no_numerica():
    """La colección entera debe seguir ilustrando el caso, aunque cambie."""
    no_numericos = [
        n for n in GOLDEN
        if GOLDEN[n]["activity"] and not GOLDEN[n]["activity"].isdigit()
    ]
    assert no_numericos, (
        "Ningún golden conserva ya un código de actividad no numérico: "
        "se perdería la evidencia que justifica el CHECK por longitud"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Cobertura por tipo de comprobante
# ─────────────────────────────────────────────────────────────────────────────


def test_el_golden_set_cubre_los_tipos_incorporados():
    raices = {GOLDEN[n]["root"] for n in GOLDEN}
    assert raices == {
        "FacturaElectronica",
        "TiqueteElectronico",
        "NotaCreditoElectronica",
        "MensajeHacienda",
    }


# Expectativa INDEPENDIENTE del tipo, declarada por fixture. No se deriva de
# `GOLDEN[...]["root"]`: si la expectativa y la comprobación salieran de la
# misma fuente, el test sería tautológico y no detectaría nada.
TIPO_ESPERADO = {
    "fe/50601082600310161019803900001010004596121100000000.xml": "FacturaElectronica",
    "fe/50602082600310161019800100024010059940227200000000.xml": "FacturaElectronica",
    "fe/003101354271-FC-00300045010000126295.xml": "FacturaElectronica",
    "fe/50619062600310111260300100008010000004706367750753.xml": "FacturaElectronica",
    "fe/50621052600310192688300100031010000000011134984857.xml": "FacturaElectronica",
    "fe/FACTURA_TC_S1505447W.xml": "FacturaElectronica",
    "fe/fe-50626052600310295087500100001010000000033159073080.xml": "FacturaElectronica",
    "te/Comprobante_Electronico_50630062600310174582200100001040000006999104246127Signature.xml": "TiqueteElectronico",
    "nc/NC-50631082600310181576400100001030000001522114249307.xml": "NotaCreditoElectronica",
    "mh/AHC-50631082600310181576400100001030000001522114249307.xml": "MensajeHacienda",
}

NS_POR_TIPO = {
    "FacturaElectronica": f"{NS_BASE}/facturaElectronica",
    "TiqueteElectronico": f"{NS_BASE}/tiqueteElectronico",
    "NotaCreditoElectronica": f"{NS_BASE}/notaCreditoElectronica",
    "NotaDebitoElectronica": f"{NS_BASE}/notaDebitoElectronica",
    "MensajeHacienda": f"{NS_BASE}/mensajeHacienda",
}

CARPETA_POR_TIPO = {
    "FacturaElectronica": "fe",
    "TiqueteElectronico": "te",
    "NotaCreditoElectronica": "nc",
    "NotaDebitoElectronica": "nd",
    "MensajeHacienda": "mh",
}


def _raiz_real(data: bytes) -> tuple[str, str]:
    """Lee la raíz y el namespace DEL XML, con un parser que no resuelve
    entidades externas ni DTD."""
    if re.search(rb"<!DOCTYPE|<!ENTITY", data[:8192], re.I):
        raise AssertionError("El fixture declara DOCTYPE/ENTITY")
    root = ET.fromstring(data)
    tag = root.tag
    local = tag.split("}")[-1] if "}" in tag else tag
    ns = tag[1:].split("}")[0] if tag.startswith("{") else ""
    return local, ns


@pytest.mark.parametrize("name", sorted(TIPO_ESPERADO))
def test_el_tipo_real_del_xml_coincide_con_la_expectativa(name):
    """La expectativa vive en `TIPO_ESPERADO`; el hecho se lee del XML.

    Comprobar `raiz_real == GOLDEN[name]["root"]` no probaría nada: `GOLDEN` es
    la misma fuente que originó la expectativa.
    """
    local, ns = _raiz_real(_raw(name))
    esperado = TIPO_ESPERADO[name]
    assert local == esperado, f"{name}: la raíz real es {local}, no {esperado}"
    assert ns == NS_POR_TIPO[esperado], f"{name}: namespace inesperado {ns}"


def test_las_dos_fuentes_de_tipo_no_se_han_desincronizado():
    """`GOLDEN[...]["root"]` es metadato de conveniencia; si difiere de la
    expectativa independiente, uno de los dos está mal y hay que mirarlo."""
    assert {n: GOLDEN[n]["root"] for n in GOLDEN} == TIPO_ESPERADO


@pytest.mark.parametrize("name", sorted(GOLDEN))
def test_cada_fixture_esta_en_la_carpeta_de_su_raiz(name):
    """La carpeta se decide por el contenido, nunca por el nombre del fichero.

    En A2-A un fichero llamado «…Estado procesando.xml» resultó ser una
    FacturaElectronica, y el único TiqueteElectronico se llamaba
    «Comprobante_Electronico_…». Clasificar por nombre habría fallado.
    """
    carpeta = name.split("/")[0]
    local, _ns = _raiz_real(_raw(name))
    esperada = CARPETA_POR_TIPO[local]
    assert carpeta == esperada, (
        f"{name} es {local} y debería vivir en {esperada}/"
    )


def test_un_fixture_ilustra_la_ausencia_de_codigo_comercial():
    """`CodigoComercial` es opcional y hay un documento real que no lo trae.

    Se fija porque un parser que lo asuma obligatorio fallaría solo contra ese
    comprobante, y sin este test nadie sabría por qué se conserva.
    """
    sin_codigo = [
        n for n in GOLDEN
        if GOLDEN[n]["root"] != "MensajeHacienda"
        and b"<CodigoComercial>" not in _raw(n)
    ]
    assert sin_codigo, "Se perdió el único caso sin CodigoComercial"


def test_el_tiquete_no_lleva_receptor():
    """Diferencia estructural real entre TE y FE en nuestra muestra."""
    te = next(n for n in GOLDEN if GOLDEN[n]["root"] == "TiqueteElectronico")
    texto = _raw(te).decode("utf-8")
    assert "<Receptor>" not in texto, "El TE dejó de ilustrar la ausencia de Receptor"
    assert "<Emisor>" in texto, "El TE debe conservar su Emisor"


# ─────────────────────────────────────────────────────────────────────────────
# Nota de Crédito: cierra el hueco `InformacionReferencia = 0` de A2-A
# ─────────────────────────────────────────────────────────────────────────────


def test_la_nota_de_credito_referencia_a_otro_comprobante():
    data = _raw(NC)
    texto = data.decode("utf-8")
    assert texto.count("<InformacionReferencia>") == NC_REFERENCIA["cantidad"]
    assert _campo(data, "TipoDocIR") == NC_REFERENCIA["tipo_doc_ir"]
    assert (
        _campo_en(data, "InformacionReferencia", "Numero")
        == NC_REFERENCIA["numero"]
    )
    assert (
        _campo_en(data, "InformacionReferencia", "Codigo")
        == NC_REFERENCIA["codigo"]
    )


def test_la_referencia_de_la_nota_de_credito_tiene_forma_de_clave():
    """El documento referenciado no está entre los fixtures: la referencia
    queda colgante, que es el caso real que debe soportar el modelo."""
    numero = _campo_en(_raw(NC), "InformacionReferencia", "Numero")
    assert re.fullmatch(r"[0-9]{50}", numero), (
        "La referencia debe tener la forma de una Clave de 50 dígitos"
    )
    # Contra TODOS los comprobantes del corpus, no solo los golden: si el
    # documento referenciado entrara por cualquier vía, este test debe fallar
    # y obligar a reclasificar el caso.
    claves = _claves_de_comprobantes()
    assert numero not in claves, (
        f"El documento referenciado por la NC ya está en el corpus "
        f"({len(claves)} comprobantes): deja de ser una referencia colgante y "
        f"este test debe reescribirse"
    )


def test_la_fecha_de_la_referencia_conserva_su_desfase():
    """`FechaEmisionIR` es fecha propia del documento referenciado."""
    valor = _campo_en(_raw(NC), "InformacionReferencia", "FechaEmisionIR")
    assert valor is not None
    assert re.search(r"[+-]\d{2}:\d{2}$", valor), (
        "Se perdió el desfase horario original de la referencia"
    )


def test_el_mensaje_de_hacienda_empareja_con_la_nota_de_credito():
    assert GOLDEN[MH_DE_LA_NC]["clave"] == GOLDEN[NC]["clave"]
    texto = _raw(MH_DE_LA_NC).decode("utf-8")
    assert _campo(_raw(MH_DE_LA_NC), "Clave") == GOLDEN[NC]["clave"]
    assert _campo(_raw(MH_DE_LA_NC), "Mensaje") == "1", "Debe ser un aceptado"
    assert "<EstadoMensaje>Aceptado</EstadoMensaje>" in texto


# ─────────────────────────────────────────────────────────────────────────────
# Formas léxicas decimales reales — el parser deberá usar Decimal, no float
# ─────────────────────────────────────────────────────────────────────────────


def test_la_coleccion_conserva_formas_decimales_diversas():
    """Los importes reales no vienen en una sola forma canónica.

    `.00` sin cero inicial, enteros sin decimales y escalas de 2 a 5 conviven
    en documentos igualmente válidos. Fijarlo evita que una futura «limpieza»
    de fixtures deje solo la forma cómoda.
    """
    formas = set()
    for name in GOLDEN:
        for valor in re.findall(
            r"<Total(?:Venta|Descuentos|VentaNeta|Impuesto|OtrosCargos|Comprobante)>"
            r"([^<]*)</Total",
            _raw(name).decode("utf-8"),
        ):
            if valor.startswith("."):
                formas.add("sin_cero_inicial")
            elif "." not in valor:
                formas.add("entero")
            else:
                formas.add(f"escala_{len(valor.split('.')[1])}")

    assert "sin_cero_inicial" in formas, 'Se perdió el caso ".00"'
    assert "entero" in formas, "Se perdió el caso de importe sin decimales"
    assert {"escala_2", "escala_5"} <= formas, "Se perdió la diversidad de escalas"


def test_hay_un_tipo_de_cambio_de_moneda_extranjera():
    tipos = {_campo(_raw(n), "TipoCambio") for n in GOLDEN}
    tipos.discard(None)
    assert any(t not in ("1", "1.00", "1.00000") for t in tipos), (
        "Ningún golden conserva ya un TipoCambio real distinto de 1"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Compatibilidad del esquema con los códigos de actividad reales
# ─────────────────────────────────────────────────────────────────────────────


def _clave_unica() -> str:
    return f"506{uuid.uuid4().int % 10**47:047d}"


def _insert(
    conn, company_id: str, *, issuer: str, receiver: str | None = None,
    clave: str | None = None, document_type: str = "invoice",
) -> None:
    conn.execute(
        """
        insert into fiscal.electronic_documents (
            company_id, document_type, clave, consecutive_number,
            issued_at_local, issued_at, issued_at_offset_minutes, issued_at_raw,
            issuer_activity_code, receiver_activity_code, sale_condition_code,
            currency_code, reported_exchange_rate,
            reported_total_sale, reported_total_net_sale, reported_total_document,
            ruleset_revision_status, direction, direction_computed_at
        ) values (
            %s, %s, %s, %s,
            -- Fecha fija y coherente: reloj de pared, su instante y su
            -- desplazamiento. Deliberadamente NO se usa now(): estos tests
            -- prueban otras restricciones, y una fecha no determinista los
            -- haría depender del momento de ejecución.
            timestamp '2026-08-01 05:24:09',
            timestamptz '2026-08-01T11:24:09+00:00',
            -360,
            '2026-08-01T05:24:09-06:00',
            %s, %s, '01', 'CRC', 1, 100, 100, 113, 'detected', 'issued', now()
        )
        """,
        (company_id, document_type, clave or _clave_unica(),
         f"{uuid.uuid4().int % 10**20:020d}", issuer, receiver),
    )


@pytest.fixture
def limpiar(admin_sql, user_a):
    """Retira SOLO las filas de la empresa creada por esta ejecucion.

    Un `delete from fiscal.electronic_documents` sin predicado borraria datos de
    otra ejecucion concurrente, de otro test o de un desarrollador trabajando
    contra el mismo proyecto DEV. El ambito es el UUID exacto de la empresa que
    creo esta ejecucion, no un prefijo de nombre.
    """
    yield
    admin_sql(
        "delete from fiscal.source_documents "
        f"where company_id = '{user_a.company_id}'"
    )
    admin_sql(
        "delete from fiscal.electronic_documents "
        f"where company_id = '{user_a.company_id}'"
    )


@pytest.mark.parametrize(
    "valor, motivo",
    [
        ("6110.0", "el valor real de los fixtures: 6 caracteres con punto"),
        ("620100", "seis dígitos sigue siendo válido"),
        ("ABC123", "el XSD dice string, no dígitos"),
        ("61.1.0", "cualquier combinación de 6 caracteres"),
    ],
)
def test_issuer_activity_code_acepta_seis_caracteres(
    pool, settings, user_a, valor, motivo, limpiar
):
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        _insert(conn, user_a.company_id, issuer=valor)


@pytest.mark.parametrize("valor", ["61100", "6110.00", "", "1234567"])
def test_issuer_activity_code_rechaza_otra_longitud(pool, settings, user_a, valor, limpiar):
    with pytest.raises(psycopg.errors.CheckViolation) as exc:
        with fiscal_transaction(pool, settings, user_a.identity) as conn:
            _insert(conn, user_a.company_id, issuer=valor)
    assert exc.value.sqlstate == "23514"


def test_receiver_activity_code_admite_null(pool, settings, user_a, limpiar):
    """La columna es opcional y debe seguir siéndolo."""
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        _insert(conn, user_a.company_id, issuer="6110.0", receiver=None)


@pytest.mark.parametrize("valor", ["6110.0", "620100", "ABC123"])
def test_receiver_activity_code_acepta_seis_caracteres(pool, settings, user_a, valor, limpiar):
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        _insert(conn, user_a.company_id, issuer="6110.0", receiver=valor)


@pytest.mark.parametrize("valor", ["61100", "6110.00"])
def test_receiver_activity_code_rechaza_otra_longitud(pool, settings, user_a, valor, limpiar):
    with pytest.raises(psycopg.errors.CheckViolation) as exc:
        with fiscal_transaction(pool, settings, user_a.identity) as conn:
            _insert(conn, user_a.company_id, issuer="6110.0", receiver=valor)
    assert exc.value.sqlstate == "23514"


def test_ningun_codigo_de_actividad_conserva_patron_numerico(admin_sql):
    """Regresión sobre el catálogo: la restricción es de longitud, no de forma."""
    rows = admin_sql(
        """
        select con.conname, pg_get_constraintdef(con.oid) as def
        from pg_constraint con
        join pg_class c on c.oid = con.conrelid
        join pg_namespace n on n.oid = c.relnamespace
        where n.nspname = 'fiscal' and c.relname = 'electronic_documents'
          and con.conname like '%activity%'
        """
    )
    assert len(rows) == 2
    for r in rows:
        assert "[0-9]" not in r["def"], (
            f"{r['conname']} volvió a exigir dígitos: {r['def']}"
        )
        assert "char_length" in r["def"] and "= 6" in r["def"]


@pytest.mark.parametrize(
    "name", sorted(n for n in GOLDEN if GOLDEN[n]["activity"] is not None)
)
def test_el_codigo_real_del_fixture_es_aceptado_por_la_base(
    pool, settings, user_a, name, limpiar
):
    """Cierra el círculo: el valor exacto del XML real entra en la tabla."""
    valor = _campo(_raw(name), "CodigoActividadEmisor")
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        _insert(conn, user_a.company_id, issuer=valor)


# ─────────────────────────────────────────────────────────────────────────────
# Seguridad del cleanup: no puede tocar datos ajenos
# ─────────────────────────────────────────────────────────────────────────────


def test_el_cleanup_no_borra_datos_de_otra_empresa(
    pool, settings, admin_sql, user_a, user_b
):
    """Regresión de comportamiento, no inspección del SQL.

    Se crean dos documentos en empresas distintas, se ejecuta el cleanup acotado
    de la primera y se comprueba que el CENTINELA de la otra sigue ahí. Un
    `delete` sin predicado —el defecto que motivó esta remediación— haría fallar
    este test.
    """
    clave_a = _clave_unica()
    clave_sentinela = _clave_unica()

    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        _insert(conn, user_a.company_id, issuer="6110.0", clave=clave_a)
    with fiscal_transaction(pool, settings, user_b.identity) as conn:
        _insert(conn, user_b.company_id, issuer="6110.0", clave=clave_sentinela)

    def _existe(clave: str) -> bool:
        return admin_sql(
            f"select count(*) as n from fiscal.electronic_documents where clave = '{clave}'"
        )[0]["n"] == 1

    assert _existe(clave_a), "No se creó el documento de la empresa A"
    assert _existe(clave_sentinela), "No se creó el centinela"

    try:
        # El cleanup REAL, acotado por el UUID de la empresa A.
        admin_sql(
            "delete from fiscal.electronic_documents "
            f"where company_id = '{user_a.company_id}'"
        )

        assert not _existe(clave_a), "El cleanup no retiró lo que debía"
        assert _existe(clave_sentinela), (
            "EL CLEANUP BORRÓ DATOS AJENOS: el centinela de otra empresa desapareció"
        )
    finally:
        admin_sql(
            f"delete from fiscal.electronic_documents where clave = '{clave_sentinela}'"
        )

    assert not _existe(clave_sentinela), "El centinela no se limpió"


def test_el_teardown_se_ejecuta_aunque_el_test_falle(settings, publishable_key, admin_sql):
    """El cleanup no puede depender de que los asertos pasen.

    Se ejerce el generador de la fixture tal como lo finaliza pytest: se lanza
    una excepción DENTRO del `yield` y se comprueba que el bloque `finally`
    ejecutó igualmente el borrado. Es el mecanismo real, no una simulación.
    """
    from tests import conftest

    gen = conftest.user_a.__wrapped__(settings, publishable_key)
    user = next(gen)

    existe = lambda: admin_sql(
        f"select count(*) as n from public.companies where id = '{user.company_id}'"
    )[0]["n"]
    assert existe() == 1, "La fixture no creó la empresa"

    class FalloSimulado(RuntimeError):
        pass

    # pytest finaliza una fixture de tipo `yield` lanzando dentro del generador
    # cuando el test falla. Se reproduce exactamente eso.
    with pytest.raises((FalloSimulado, StopIteration)):
        gen.throw(FalloSimulado("el test falló"))

    assert existe() == 0, (
        "El teardown NO se ejecutó ante una excepción: quedarían recursos huérfanos"
    )
    assert admin_sql(
        f"select count(*) as n from auth.users where id = '{user.id}'"
    )[0]["n"] == 0, "El usuario de Auth sobrevivió al teardown"


# ─────────────────────────────────────────────────────────────────────────────
# Vocabulario de `document_type`: el Tiquete real obligó a ampliarlo (A2-B0)
# ─────────────────────────────────────────────────────────────────────────────

# Tipo fuente (raíz del XML) → tipo normalizado interno. El código oficial se
# anota como referencia; NO es el valor almacenado: la columna usa vocabulario
# propio porque el catálogo de Hacienda puede crecer, y ya lo hizo en 2026.
MAPEO_TIPO = {
    "FacturaElectronica": ("invoice", "01"),
    "TiqueteElectronico": ("ticket", "04"),
    "NotaCreditoElectronica": ("credit_note", "03"),
    "NotaDebitoElectronica": ("debit_note", "02"),
}


@pytest.mark.parametrize(
    "tipo", ["invoice", "ticket", "credit_note", "debit_note"]
)
def test_document_type_admite_los_cuatro_tipos(
    pool, settings, user_a, tipo, limpiar
):
    """Comportamiento real contra la base, no lectura del texto del CHECK."""
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        _insert(conn, user_a.company_id, issuer="6110.0", document_type=tipo)


@pytest.mark.parametrize(
    "tipo", ["unknown_document_type", "receipt", "TICKET", "ticket ", ""]
)
def test_document_type_rechaza_valores_fuera_del_vocabulario(
    pool, settings, user_a, tipo, limpiar
):
    """`receipt` se rechaza a propósito: está reservado para el Recibo
    Electrónico de Pago (código 10), que todavía no se ha incorporado."""
    with pytest.raises(psycopg.errors.CheckViolation) as exc:
        with fiscal_transaction(pool, settings, user_a.identity) as conn:
            _insert(conn, user_a.company_id, issuer="6110.0", document_type=tipo)
    assert exc.value.diag.constraint_name == (
        "electronic_documents_document_type_check"
    )


def test_document_type_no_se_puede_reescribir_en_absoluto(
    pool, settings, user_a, limpiar
):
    """`document_type` es un hecho de origen: no se actualiza, ni a un valor
    válido ni a uno inválido.

    La protección llega antes que el `CHECK`: la columna no está entre las que
    tienen `UPDATE` concedido, así que el motor responde `42501`
    (privilegio insuficiente) sin llegar a evaluar la restricción. Es una
    garantía más fuerte que el `CHECK`, no una más débil.
    """
    clave = _clave_unica()
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        _insert(conn, user_a.company_id, issuer="6110.0", clave=clave,
                document_type="invoice")

    for destino in ("ticket", "unknown_document_type"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with fiscal_transaction(pool, settings, user_a.identity) as conn:
                conn.execute(
                    "update fiscal.electronic_documents set document_type = %s "
                    "where company_id = %s and clave = %s",
                    (destino, user_a.company_id, clave),
                )


@pytest.mark.parametrize("raiz", sorted(MAPEO_TIPO))
def test_cada_tipo_fuente_tiene_representacion_en_la_base(
    pool, settings, user_a, raiz, limpiar
):
    """El contrato de mapeo, comprobado contra el esquema real.

    Antes de A2-B0 el TiqueteElectronico no tenía ningún valor válido: este
    test habría fallado para esa raíz, que es exactamente lo que destapó el
    fixture real.
    """
    normalizado, _codigo = MAPEO_TIPO[raiz]
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        _insert(conn, user_a.company_id, issuer="6110.0",
                document_type=normalizado)


def test_el_tiquete_real_del_corpus_normaliza_a_ticket(
    pool, settings, user_a, limpiar
):
    """Se parte de la raíz REAL del fixture, no de una constante escrita a mano."""
    te = next(n for n in GOLDEN if GOLDEN[n]["root"] == "TiqueteElectronico")
    raiz = GOLDEN[te]["root"]
    assert raiz in MAPEO_TIPO, f"{raiz} no tiene mapeo declarado"
    normalizado, codigo = MAPEO_TIPO[raiz]
    assert (normalizado, codigo) == ("ticket", "04")

    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        _insert(
            conn, user_a.company_id,
            issuer=GOLDEN[te]["activity"],
            clave=GOLDEN[te]["clave"],
            document_type=normalizado,
        )


def test_el_mapeo_no_colapsa_dos_tipos_fuente_en_uno():
    """Si el Tiquete volviera a mapearse a `invoice`, se perdería la
    distinción entre dos tipos fiscales con código oficial distinto."""
    normalizados = [v[0] for v in MAPEO_TIPO.values()]
    assert len(normalizados) == len(set(normalizados)), (
        "Dos tipos fuente comparten tipo normalizado"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Corpus completo: los 24 XML, no solo los 10 GOLDEN (A2-B1)
# ─────────────────────────────────────────────────────────────────────────────

# Comprobantes fiscales. `MensajeHacienda` NO lo es: es una respuesta de
# Hacienda, con su propio ciclo de vida, y no aporta Clave de comprobante.
RAICES_COMPROBANTE = frozenset({
    "FacturaElectronica",
    "TiqueteElectronico",
    "NotaCreditoElectronica",
    "NotaDebitoElectronica",
})


def _todos_los_xml() -> list[str]:
    return sorted(
        str(p.relative_to(FIXTURES))
        for p in FIXTURES.rglob("*.xml")
    )


def _claves_de_comprobantes() -> set[str]:
    """Clave de TODOS los comprobantes del corpus, leída del XML."""
    claves = set()
    for rel in _todos_los_xml():
        data = _raw(rel)
        local, _ns = _raiz_real(data)
        if local in RAICES_COMPROBANTE:
            clave = _campo(data, "Clave")
            assert clave, f"{rel}: comprobante sin Clave"
            claves.add(clave)
    return claves


def test_el_corpus_tiene_el_tamano_esperado():
    """Si aparece o desaparece un fichero, hay que enterarse."""
    todos = _todos_los_xml()
    assert len(todos) == 24, f"El corpus tiene {len(todos)} XML, se esperaban 24"
    assert set(GOLDEN) <= set(todos), "Falta algún GOLDEN en el árbol"
    assert len(GOLDEN) == 10


@pytest.mark.parametrize("rel", _todos_los_xml())
def test_todo_xml_del_corpus_es_valido_y_esta_bien_ubicado(rel):
    """Smoke colectivo sobre los 24: bien formado, raíz reconocida, namespace
    v4.4 y carpeta coherente con el CONTENIDO.

    No sustituye a las aserciones de los GOLDEN; garantiza que ningún fichero
    se corrompa o se mueva mal en silencio.
    """
    data = _raw(rel)
    local, ns = _raiz_real(data)          # falla si no es XML bien formado

    assert local in CARPETA_POR_TIPO, f"{rel}: raíz no reconocida {local!r}"
    assert ns == NS_POR_TIPO[local], f"{rel}: namespace inesperado {ns}"
    assert ns.startswith(NS_BASE + "/"), f"{rel}: no es un namespace v4.4"

    carpeta = rel.split("/")[0]
    assert carpeta == CARPETA_POR_TIPO[local], (
        f"{rel} es {local} y debería estar en {CARPETA_POR_TIPO[local]}/"
    )


def test_el_reparto_del_corpus_por_tipo():
    reparto = {}
    for rel in _todos_los_xml():
        local, _ = _raiz_real(_raw(rel))
        reparto[local] = reparto.get(local, 0) + 1
    assert reparto == {
        "FacturaElectronica": 11,
        "TiqueteElectronico": 1,
        "NotaCreditoElectronica": 1,
        "MensajeHacienda": 11,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Cada GOLDEN prueba la razón por la que se conserva (A2-B1)
# ─────────────────────────────────────────────────────────────────────────────

def _g(clave_parcial: str) -> str:
    """Localiza un golden por fragmento de ruta, sin depender del orden."""
    coincidencias = [n for n in GOLDEN if clave_parcial in n]
    assert len(coincidencias) == 1, (
        f"{clave_parcial!r} no identifica un único golden: {coincidencias}"
    )
    return coincidencias[0]


def test_golden_multi_iva_declara_dos_tarifas_distintas():
    data = _raw(_g("003101354271-FC"))
    tarifas = set(re.findall(r"<Tarifa>([^<]*)</Tarifa>", data.decode("utf-8")))
    assert len(tarifas) >= 2, f"Se esperaban ≥2 tarifas distintas, hay {tarifas}"
    assert data.count(b"<TotalDesgloseImpuesto>") >= 2, (
        "Se esperaba más de un TotalDesgloseImpuesto"
    )


def test_golden_sin_codigo_comercial_no_tiene_el_nodo():
    data = _raw(_g("4706367750753"))
    assert b"<CodigoComercial>" not in data
    # Y el total llega sin decimales: la otra razón por la que se conserva.
    assert _campo(data, "TotalComprobante") == "54000"


def test_golden_condicion_venta_otros_trae_el_nodo_real():
    data = _raw(_g("011134984857"))
    assert b"<CondicionVentaOtros>" in data
    assert b"<PorcentajeOC>" in data


def test_golden_decimal_sin_cero_inicial_conserva_esa_forma_lexica():
    texto = _raw(_g("FACTURA_TC")).decode("utf-8")
    sin_cero = re.findall(r"<(Total\w+)>(\.\d+)</Total\w+>", texto)
    assert sin_cero, 'Se perdió la forma lexica ".00" sin cero inicial'


def test_golden_usd_conserva_el_tipo_de_cambio_lexico_exacto():
    from decimal import Decimal

    data = _raw(_g("033159073080"))
    assert _campo(data, "CodigoMoneda") == "USD"
    tc = _campo(data, "TipoCambio")
    assert tc == "455.14000", f"El TipoCambio léxico cambió: {tc!r}"
    # Decimal exacto, nunca float: 455.14000 conserva su escala de 5.
    assert Decimal(tc) == Decimal("455.14000")
    assert -Decimal(tc).as_tuple().exponent == 5


def test_golden_tiquete_es_contado_con_plazo_y_sin_receptor():
    """`CondicionVenta = 01` es **Contado** según el XSD v4.4, que documenta
    «01 Contado, 02 Crédito». El fixture NO es un caso de crédito.

    Lo que sí ilustra, y es más interesante: una venta de contado que además
    declara `PlazoCredito`.
    """
    data = _raw(_g("Comprobante_Electronico"))
    assert _campo(data, "CondicionVenta") == "01"
    assert _campo(data, "PlazoCredito") == "1"
    assert _campo(data, "CodigoMoneda") == "USD"
    assert b"<Receptor>" not in data
    assert b"<Emisor>" in data


def test_golden_nota_credito_trae_referencia_real():
    data = _raw(NC)
    assert data.count(b"<InformacionReferencia>") == 1
    assert _campo_en(data, "InformacionReferencia", "TipoDocIR") == "01"
    assert _campo_en(data, "InformacionReferencia", "Razon")


def test_golden_mensaje_hacienda_empareja_y_esta_aceptado():
    assert _campo(_raw(MH_DE_LA_NC), "Clave") == _campo(_raw(NC), "Clave")
    assert _campo(_raw(MH_DE_LA_NC), "Mensaje") == "1"


def test_ningun_golden_es_de_credito():
    """El corpus entero es de contado (`CondicionVenta = 01`).

    Se fija para que nadie describa un fixture como «crédito» sin que el dato
    lo respalde: fue exactamente el error que corrigió A2-B1.
    """
    for name in GOLDEN:
        if GOLDEN[name]["root"] == "MensajeHacienda":
            continue
        assert _campo(_raw(name), "CondicionVenta") == "01", (
            f"{name} dejó de ser contado: revisa su descripción"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Fechas: la fuente puede no declarar desplazamiento (ADR-039, A2-B1)
# ─────────────────────────────────────────────────────────────────────────────

_RE_OFFSET = re.compile(r"([+-]\d{2}:\d{2}|Z)$")


def _fecha_emision(name: str) -> str:
    valor = _campo(_raw(name), "FechaEmision")
    assert valor, f"{name} no declara FechaEmision"
    return valor


def _parte_local(literal: str) -> str:
    """Reloj de pared: el literal sin su desplazamiento, si lo trae."""
    return _RE_OFFSET.sub("", literal)


def _offset_minutos(literal: str) -> int | None:
    m = _RE_OFFSET.search(literal)
    if m is None:
        return None
    marca = m.group(1)
    if marca == "Z":
        return 0
    signo = 1 if marca[0] == "+" else -1
    horas, minutos = int(marca[1:3]), int(marca[4:6])
    return signo * (horas * 60 + minutos)


def test_el_corpus_contiene_ambos_casos_de_fecha():
    """Si el corpus dejara de tener uno de los dos, los tests siguientes
    dejarían de probar lo que dicen probar."""
    con_offset, sin_offset = [], []
    for rel in _todos_los_xml():
        local, _ = _raiz_real(_raw(rel))
        if local not in RAICES_COMPROBANTE:
            continue
        literal = _campo(_raw(rel), "FechaEmision")
        (con_offset if _offset_minutos(literal) is not None else sin_offset).append(rel)
    assert con_offset, "Ningún comprobante declara desplazamiento"
    assert sin_offset, "Ningún comprobante omite el desplazamiento"
    assert len(sin_offset) == 4, (
        f"Se esperaban 4 comprobantes sin desplazamiento, hay {len(sin_offset)}"
    )


def _fixture_con_offset() -> str:
    return _g("50601082600310161019803900001010004596121100000000")


def _fixture_sin_offset() -> str:
    return _g("Comprobante_Electronico")


def test_el_fixture_con_offset_lo_declara_de_verdad():
    literal = _fecha_emision(_fixture_con_offset())
    assert _offset_minutos(literal) == -360, literal
    assert _parte_local(literal) == "2026-08-01T05:24:09"


def test_el_fixture_sin_offset_no_lo_declara():
    literal = _fecha_emision(_fixture_sin_offset())
    assert _offset_minutos(literal) is None, (
        f"{literal!r} ya declara desplazamiento: deja de ilustrar el caso"
    )
    assert _parte_local(literal) == "2026-06-30T12:29:12"


def _insert_fecha(
    conn, company_id: str, *, literal: str, document_type: str = "invoice",
    issuer: str = "6110.0", clave: str | None = None,
) -> None:
    """Inserta derivando las columnas de fecha DEL LITERAL del XML.

    No usa `now()`, ni un desplazamiento fijo, ni una fecha inventada: si el
    literal no trae desplazamiento, el instante y el desplazamiento van a NULL.
    """
    local = _parte_local(literal)
    offset = _offset_minutos(literal)
    instante = None if offset is None else literal
    conn.execute(
        """
        insert into fiscal.electronic_documents (
            company_id, document_type, clave, consecutive_number,
            issued_at_local, issued_at, issued_at_offset_minutes, issued_at_raw,
            issuer_activity_code, sale_condition_code,
            currency_code, reported_exchange_rate,
            reported_total_sale, reported_total_net_sale, reported_total_document,
            ruleset_revision_status, direction, direction_computed_at
        ) values (
            %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, '01', 'CRC', 1, 100, 100, 113, 'detected', 'issued', now()
        )
        """,
        (company_id, document_type, clave or _clave_unica(),
         f"{uuid.uuid4().int % 10**20:020d}",
         local, instante, offset, literal, issuer),
    )


def _leer_fechas(conn, company_id: str, clave: str) -> dict:
    cur = conn.execute(
        "select issued_at_local, issued_at, issued_at_offset_minutes, issued_at_raw "
        "from fiscal.electronic_documents where company_id = %s and clave = %s",
        (company_id, clave),
    )
    fila = cur.fetchone()
    assert fila is not None, "No se recuperó la fila recién insertada"
    # El pool de tests usa `dict_row`: las filas son diccionarios, no tuplas.
    return {
        "local": fila["issued_at_local"],
        "instante": fila["issued_at"],
        "offset": fila["issued_at_offset_minutes"],
        "raw": fila["issued_at_raw"],
    }


def test_fecha_con_offset_se_guarda_completa(pool, settings, user_a, limpiar):
    """Caso A — el XML declara desplazamiento: se guardan las tres piezas."""
    from datetime import datetime, timezone, timedelta

    literal = _fecha_emision(_fixture_con_offset())
    clave = _clave_unica()
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        _insert_fecha(conn, user_a.company_id, literal=literal, clave=clave)
        f = _leer_fechas(conn, user_a.company_id, clave)

    assert f["local"] == datetime(2026, 8, 1, 5, 24, 9)
    assert f["offset"] == -360
    assert f["instante"] == datetime(
        2026, 8, 1, 11, 24, 9, tzinfo=timezone.utc
    ), "El instante no corresponde al reloj de pared desplazado"
    assert f["raw"] == literal
    # Y el instante es exactamente local - offset, sin intervención de zonas.
    assert f["instante"] == (
        f["local"] - timedelta(minutes=f["offset"])
    ).replace(tzinfo=timezone.utc)


def test_fecha_sin_offset_deja_el_instante_en_nulo(
    pool, settings, user_a, limpiar
):
    """Caso B — el XML NO declara desplazamiento: no se inventa ninguno."""
    from datetime import datetime

    literal = _fecha_emision(_fixture_sin_offset())
    clave = _clave_unica()
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        _insert_fecha(conn, user_a.company_id, literal=literal, clave=clave,
                      document_type="ticket")
        f = _leer_fechas(conn, user_a.company_id, clave)

    assert f["local"] == datetime(2026, 6, 30, 12, 29, 12)
    assert f["instante"] is None, "Se inventó un instante que la fuente no da"
    assert f["offset"] is None, "Se inventó un desplazamiento"
    assert f["raw"] == literal


# ── Casos negativos: las restricciones de coherencia ────────────────────────

def _insert_crudo(conn, company_id, *, local, instante, offset, clave=None):
    conn.execute(
        """
        insert into fiscal.electronic_documents (
            company_id, document_type, clave, consecutive_number,
            issued_at_local, issued_at, issued_at_offset_minutes, issued_at_raw,
            issuer_activity_code, sale_condition_code,
            currency_code, reported_exchange_rate,
            reported_total_sale, reported_total_net_sale, reported_total_document,
            ruleset_revision_status, direction, direction_computed_at
        ) values (
            %s, 'invoice', %s, %s, %s, %s, %s, 'x',
            '6110.0', '01', 'CRC', 1, 100, 100, 113, 'detected', 'issued', now()
        )
        """,
        (company_id, clave or _clave_unica(),
         f"{uuid.uuid4().int % 10**20:020d}", local, instante, offset),
    )


def test_instante_sin_offset_es_rechazado(pool, settings, user_a, limpiar):
    with pytest.raises(psycopg.errors.CheckViolation) as exc:
        with fiscal_transaction(pool, settings, user_a.identity) as conn:
            _insert_crudo(conn, user_a.company_id,
                          local="2026-06-30 12:29:12",
                          instante="2026-06-30T18:29:12+00:00", offset=None)
    assert exc.value.diag.constraint_name == (
        "electronic_documents_issued_instant_check"
    )


def test_offset_sin_instante_es_rechazado(pool, settings, user_a, limpiar):
    with pytest.raises(psycopg.errors.CheckViolation) as exc:
        with fiscal_transaction(pool, settings, user_a.identity) as conn:
            _insert_crudo(conn, user_a.company_id,
                          local="2026-06-30 12:29:12",
                          instante=None, offset=-360)
    assert exc.value.diag.constraint_name == (
        "electronic_documents_issued_instant_check"
    )


@pytest.mark.parametrize("offset", [-841, 841, -1440, 1440])
def test_offset_fuera_de_rango_es_rechazado(
    pool, settings, user_a, offset, limpiar
):
    """XML Schema limita el desplazamiento a ±840 minutos (±14:00)."""
    from datetime import datetime, timedelta, timezone

    local = datetime(2026, 6, 30, 12, 29, 12)
    instante = (local - timedelta(minutes=offset)).replace(tzinfo=timezone.utc)
    with pytest.raises(psycopg.errors.CheckViolation) as exc:
        with fiscal_transaction(pool, settings, user_a.identity) as conn:
            _insert_crudo(conn, user_a.company_id, local=local,
                          instante=instante, offset=offset)
    assert exc.value.diag.constraint_name == "electronic_documents_offset_check"


def test_instante_incoherente_con_el_reloj_de_pared_es_rechazado(
    pool, settings, user_a, limpiar
):
    """Las dos representaciones no pueden contradecirse."""
    with pytest.raises(psycopg.errors.CheckViolation) as exc:
        with fiscal_transaction(pool, settings, user_a.identity) as conn:
            _insert_crudo(conn, user_a.company_id,
                          local="2026-06-30 12:29:12",
                          instante="2026-06-30T23:00:00+00:00", offset=-360)
    assert exc.value.diag.constraint_name == (
        "electronic_documents_issued_coherence_check"
    )


# ── §21: FE, TE y NC representables con sus valores REALES ─────────────────

@pytest.mark.parametrize(
    "clave_parcial, tipo_normalizado",
    [
        ("50601082600310161019803900001010004596121100000000", "invoice"),
        ("Comprobante_Electronico", "ticket"),
        ("NC-50631082600310181576400100001030000001522114249307", "credit_note"),
    ],
)
def test_los_tres_tipos_reales_son_representables(
    pool, settings, user_a, clave_parcial, tipo_normalizado, limpiar
):
    """Se toman Clave, código de actividad y FechaEmision REALES del fixture.

    No es el parser de producción: es la prueba de que el contrato físico
    admite los documentos que tenemos, incluidos los que no declaran
    desplazamiento.
    """
    name = _g(clave_parcial)
    data = _raw(name)
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        _insert_fecha(
            conn, user_a.company_id,
            literal=_campo(data, "FechaEmision"),
            document_type=tipo_normalizado,
            issuer=_campo(data, "CodigoActividadEmisor"),
            clave=_campo(data, "Clave"),
        )


# ─────────────────────────────────────────────────────────────────────────────
# Contrato semántico de los dos golden ORIGINALES (A2-B2)
#
# Hasta A2-B1 estos dos descansaban sobre huella y metadatos. Aquí se les da
# el mismo trato que a los otros ocho: expectativas declaradas aparte, valores
# LEÍDOS DEL XML.
# ─────────────────────────────────────────────────────────────────────────────

BASELINE_1 = "fe/50601082600310161019803900001010004596121100000000.xml"
BASELINE_2 = "fe/50602082600310161019800100024010059940227200000000.xml"

# Situación del comprobante: dígito 42 de la Clave (base 1). Fuente: Anexos
# v4.4, págs. 66-67, recogidos en docs/FISCAL_DOMAIN.md §5.2. No se infiere
# del nombre del fichero.
SITUACION = {"1": "Normal", "2": "Contingencia", "3": "Sin internet"}


def _situacion_de_la_clave(clave: str) -> str:
    assert re.fullmatch(r"[0-9]{50}", clave), "La Clave debe tener 50 dígitos"
    digito = clave[41]          # posición 42 en base 1
    assert digito in SITUACION, f"Situación desconocida: {digito!r}"
    return SITUACION[digito]


def _cuenta(data: bytes, tag: str) -> int:
    """Cuenta apariciones de un elemento, con o sin contenido.

    `<Registrofiscal8707 />` es autocerrado: contar solo `<Tag>` lo pasaría
    por alto, que es exactamente el error que A2-B2 corrigió.
    """
    texto = data.decode("utf-8")
    return len(re.findall(rf"<{tag}(?:\s[^>]*)?/?>", texto))


def test_la_clave_contiene_su_propio_consecutivo():
    """Anexos v4.4 §5.2: las posiciones 22-41 de la Clave SON el consecutivo.

    Se comprueba sobre los comprobantes reales: si la codificación que usamos
    para leer la situación fuera errónea, esto lo delataría.
    """
    for rel in _todos_los_xml():
        local, _ = _raiz_real(_raw(rel))
        if local not in RAICES_COMPROBANTE:
            continue
        data = _raw(rel)
        clave = _campo(data, "Clave")
        consecutivo = _campo(data, "NumeroConsecutivo")
        assert clave[21:41] == consecutivo, (
            f"{rel}: Clave[22:41]={clave[21:41]} ≠ consecutivo {consecutivo}"
        )


def test_baseline_1_estructura_real():
    """Golden 1 — todo leído del XML, nada de `GOLDEN[...]`."""
    data = _raw(BASELINE_1)
    local, ns = _raiz_real(data)

    assert local == "FacturaElectronica"
    assert ns == f"{NS_BASE}/facturaElectronica"
    assert _cuenta(data, "LineaDetalle") == 7
    assert _cuenta(data, "Descuento") == 1
    assert _cuenta(data, "OtrosCargos") == 2
    assert _campo(data, "CodigoActividadEmisor") == "6110.0"
    assert _campo(data, "TotalComprobante") == "27614.81"
    assert _situacion_de_la_clave(_campo(data, "Clave")) == "Normal"


def test_baseline_1_trae_registrofiscal8707_como_elemento_vacio():
    """El rasgo real NO es que el nodo lleve un valor: es que está **vacío**.

    Aparece como `<Registrofiscal8707 />`, autocerrado y sin contenido. Es el
    caso «elemento presente pero vacío ≠ elemento ausente», que un parser
    ingenuo colapsa. La etiqueta histórica «Registrofiscal8707» sugería un
    dato poblado y era imprecisa; A2-B2 la corrigió.
    """
    texto = _raw(BASELINE_1).decode("utf-8")
    assert "<Registrofiscal8707 />" in texto or "<Registrofiscal8707/>" in texto, (
        "Se perdió el elemento vacío autocerrado"
    )
    assert not re.search(r"<Registrofiscal8707>[^<]+</Registrofiscal8707>", texto), (
        "El elemento dejó de estar vacío: la razón del fixture cambió"
    )


def test_baseline_2_estructura_real():
    """Golden 2 — todo leído del XML."""
    data = _raw(BASELINE_2)
    local, ns = _raiz_real(data)

    assert local == "FacturaElectronica"
    assert ns == f"{NS_BASE}/facturaElectronica"
    assert _cuenta(data, "LineaDetalle") == 1
    assert _cuenta(data, "Descuento") == 0
    assert _cuenta(data, "OtrosCargos") == 2
    assert _campo(data, "CodigoActividadEmisor") == "6110.0"
    assert _campo(data, "TotalComprobante") == "10662.62"


def test_baseline_2_es_de_contingencia_segun_la_clave():
    """La contingencia se demuestra por la codificación OFICIAL de la Clave.

    Anexos v4.4 págs. 66-67: el dígito 42 es la situación del comprobante,
    `1` Normal · `2` Contingencia · `3` Sin internet. No se deduce del nombre
    del fichero, y el XML v4.4 no tiene ningún otro campo que lo declare.
    """
    clave = _campo(_raw(BASELINE_2), "Clave")
    assert _situacion_de_la_clave(clave) == "Contingencia"
    # Y el baseline 1, que es Normal, lo confirma por contraste.
    assert _situacion_de_la_clave(_campo(_raw(BASELINE_1), "Clave")) == "Normal"


def test_baseline_2_distingue_ausente_de_cero():
    """Dos campos del mismo documento, dos significados distintos."""
    data = _raw(BASELINE_2)
    assert _campo(data, "TotalDescuentos") is None, (
        "TotalDescuentos dejó de estar AUSENTE"
    )
    assert _campo(data, "PlazoCredito") == "0", (
        "PlazoCredito dejó de ser un cero EXPLÍCITO"
    )


def test_los_dos_baseline_comparten_emisor_y_actividad():
    """Se conservan como par: mismo emisor, dos situaciones distintas."""
    a, b = _raw(BASELINE_1), _raw(BASELINE_2)
    assert _campo(a, "CodigoActividadEmisor") == _campo(b, "CodigoActividadEmisor")
    assert _situacion_de_la_clave(_campo(a, "Clave")) != (
        _situacion_de_la_clave(_campo(b, "Clave"))
    )
