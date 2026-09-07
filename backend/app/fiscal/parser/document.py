"""Parser fiscal de producción — sobre del comprobante y partes (B1).

    parse_fiscal_document(raw_xml: bytes) -> ParsedFiscalDocument

**Puro.** No toca la base de datos, no necesita usuario autenticado, no
conoce `company_id` y no sale a la red. Su única entrada son los bytes: el
contenido es la autoridad, nunca el nombre del fichero —en E4-A2 un fichero
llamado «…Estado procesando.xml» resultó ser una Factura, y el único Tiquete
se llamaba «Comprobante_Electronico_…»—.

**Solo emite valores reportados.** No calcula impuestos, no reconcilia
totales, no interpreta catálogos y no juzga la corrección fiscal más allá de
lo estructural. Los `computed_*` son del futuro Tax Engine.

Alcance de B1: `ElectronicDocument` y `DocumentParty`. Líneas, impuestos,
descuentos y referencias llegan en cortes posteriores; aquí **no** se
implementan a medias.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from lxml import etree

from app.fiscal.errors import (
    MalformedXML,
    SemanticParseError,
    UnsupportedDocument,
    ValidatorConfigurationError,
    XSDValidationError,
)
from app.fiscal.models import (
    TIPO_POR_RAIZ,
    FechaFiscal,
    Identificacion,
    ParsedDocumentParty,
    ParsedElectronicDocument,
    ParsedFiscalDocument,
)
from app.fiscal.xsd import bundle
from app.fiscal.xsd.registry import get_verified_schema_registry

# Tipos con soporte SEMÁNTICO probado contra comprobantes reales. La Nota de
# Débito tiene esquema versionado y su raíz se reconoce, pero **no existe
# ningún comprobante real** con el que probar la extracción: aceptarla sería
# afirmar una cobertura que no tenemos.
RAICES_SOPORTADAS = frozenset({
    "FacturaElectronica",
    "TiqueteElectronico",
    "NotaCreditoElectronica",
})

_RE_OFFSET = re.compile(r"(?P<signo>[+-])(?P<h>\d{2}):(?P<m>\d{2})$|Z$")


def _diagnostico_seguro(error_log) -> dict[str, object]:
    """Metadatos estructurales del primer error, **sin texto de libxml2**.

    libxml2 compone mensajes del tipo::

        Element '...Clave': [facet 'pattern'] The value 'XXXX' is not accepted

    …es decir, incrusta el **valor infractor**. Ese valor es justo el dato
    fiscal que no debe salir en un error ni en un log, así que no se toma
    nada del mensaje: solo el tipo de error, la línea y la columna, que
    bastan para diagnosticar y no dicen nada del contenido.
    """
    if not len(error_log):
        return {}
    e = error_log[0]
    return {
        "error_type": getattr(e, "type_name", None),
        "line": getattr(e, "line", None),
        "column": getattr(e, "column", None),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Lectura por namespace, nunca por prefijo
# ─────────────────────────────────────────────────────────────────────────────

def _local(elemento: etree._Element) -> str:
    tag = elemento.tag
    return tag.split("}")[-1] if isinstance(tag, str) and "}" in tag else str(tag)


def _hijo(padre: etree._Element | None, nombre: str) -> etree._Element | None:
    """Primer hijo DIRECTO con ese local-name.

    Se compara el local-name y se ignora el prefijo: los prefijos XML no son
    identidad semántica, y buscar por ruta con prefijos arbitrarios sería
    frágil ante un documento que declarase otros.
    """
    if padre is None:
        return None
    for h in padre:
        if isinstance(h.tag, str) and _local(h) == nombre:
            return h
    return None


def _ruta(raiz: etree._Element, *nombres: str) -> etree._Element | None:
    actual: etree._Element | None = raiz
    for n in nombres:
        actual = _hijo(actual, n)
        if actual is None:
            return None
    return actual


def _texto(elemento: etree._Element | None) -> str | None:
    """Texto de un elemento, distinguiendo AUSENTE de VACÍO.

    - elemento ausente        → `None`
    - elemento presente vacío → `""`
    - elemento con contenido  → el texto, sin espacios en los extremos

    La distinción importa: el corpus real contiene `<Registrofiscal8707 />`,
    un elemento presente y vacío, que no es lo mismo que no estar.
    """
    if elemento is None:
        return None
    return (elemento.text or "").strip()


def _decimal(elemento: etree._Element | None, campo: str) -> Decimal | None:
    """`Decimal` construido desde el LITERAL. Nunca vía `float`.

    Un ausente devuelve `None`, no `Decimal("0")`: el modelo físico distingue
    ambos estados y colapsarlos perdería información fiscal.
    """
    crudo = _texto(elemento)
    if crudo is None or crudo == "":
        return None
    try:
        return Decimal(crudo)
    except InvalidOperation as exc:
        raise SemanticParseError(
            "Importe no interpretable como decimal", campo=campo
        ) from exc


def _entero(elemento: etree._Element | None, campo: str) -> int | None:
    crudo = _texto(elemento)
    if crudo is None or crudo == "":
        return None
    try:
        return int(crudo)
    except ValueError as exc:
        raise SemanticParseError("Valor no entero", campo=campo) from exc


def _obligatorio(valor: str | None, campo: str) -> str:
    """Lo que el XSD garantiza obligatorio debe estar. Si falta, es que el
    esquema oficial cambió y el modelo dejó de ser fiel."""
    if valor is None or valor == "":
        raise SemanticParseError("Campo obligatorio ausente o vacío", campo=campo)
    return valor


def _decimal_obligatorio(elemento: etree._Element | None, campo: str) -> Decimal:
    valor = _decimal(elemento, campo)
    if valor is None:
        raise SemanticParseError("Importe obligatorio ausente", campo=campo)
    return valor


# ─────────────────────────────────────────────────────────────────────────────
# Fecha (ADR-039)
# ─────────────────────────────────────────────────────────────────────────────

def _fecha(literal: str, campo: str) -> FechaFiscal:
    """Interpreta un `xs:dateTime` **sin inventar zona horaria**.

    Con desplazamiento: reloj de pared, instante, desplazamiento y literal.
    Sin desplazamiento: reloj de pared y literal; instante y desplazamiento a
    `None`. Nunca se asume UTC, ni −06:00, ni la zona del servidor.
    """
    m = _RE_OFFSET.search(literal)
    parte_local = literal[: m.start()] if m else literal

    try:
        local = datetime.fromisoformat(parte_local)
    except ValueError as exc:
        raise SemanticParseError("Fecha no interpretable", campo=campo) from exc
    if local.tzinfo is not None:            # defensa: la parte local no lleva huso
        raise SemanticParseError("Fecha local con huso inesperado", campo=campo)

    if m is None:
        return FechaFiscal(local=local, raw=literal)

    if m.group(0) == "Z":
        offset = 0
    else:
        signo = 1 if m.group("signo") == "+" else -1
        offset = signo * (int(m.group("h")) * 60 + int(m.group("m")))

    instante = (local - timedelta(minutes=offset)).replace(tzinfo=timezone.utc)
    return FechaFiscal(
        local=local, raw=literal, instante=instante, offset_minutos=offset
    )


# ─────────────────────────────────────────────────────────────────────────────
# Partes
# ─────────────────────────────────────────────────────────────────────────────

def _parte(nodo: etree._Element, role: str) -> ParsedDocumentParty:
    nombre = _obligatorio(_texto(_hijo(nodo, "Nombre")), f"{role}/Nombre")

    ident_nodo = _hijo(nodo, "Identificacion")
    identificacion = None
    if ident_nodo is not None:
        identificacion = Identificacion(
            tipo=_obligatorio(
                _texto(_hijo(ident_nodo, "Tipo")), f"{role}/Identificacion/Tipo"
            ),
            numero=_obligatorio(
                _texto(_hijo(ident_nodo, "Numero")), f"{role}/Identificacion/Numero"
            ),
        )

    comercial = _texto(_hijo(nodo, "NombreComercial"))
    return ParsedDocumentParty(
        role=role,
        legal_name=nombre,
        identificacion=identificacion,
        trade_name=comercial or None,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Contrato público
# ─────────────────────────────────────────────────────────────────────────────

def parse_fiscal_document(raw_xml: bytes) -> ParsedFiscalDocument:
    """Bytes de un comprobante v4.4 → estructuras tipadas del dominio.

    Orden, deliberado y no negociable:

        bytes → parseo seguro → (raíz, namespace) → ¿soportado?
              → validación XSD oficial → extracción semántica

    La validación XSD va **dentro** del contrato público a propósito: si
    aceptara entrada «ya validada», delegaría en quien llame la
    responsabilidad de no saltarse la única puerta que no debe saltarse.
    """
    # 0 · Los esquemas SIEMPRE se obtienen del registro verificado. Es la
    #     única vía: si la puerta fail-closed rechaza el paquete, aquí no se
    #     compila ni se valida nada.
    registro = get_verified_schema_registry()

    # 1 · Parseo seguro. Mismo endurecimiento probado en A2-C.
    try:
        arbol_completo = etree.fromstring(raw_xml, parser=bundle._parser()).getroottree()
    except etree.XMLSyntaxError as exc:
        # No se propaga la excepción de lxml: puede citar contenido del XML.
        raise MalformedXML("XML mal formado") from exc
    arbol = arbol_completo.getroot()

    # 2 · DOCTYPE, detectado ESTRUCTURALMENTE.
    #     Antes se buscaba el literal en los primeros 8 KiB, y bastaban 9 KiB
    #     de comentario legal por delante para colarlo. `docinfo` lo ve
    #     dondequiera que esté en el prólogo, y sin cargarlo ni resolverlo:
    #     el parser ya trae `load_dtd=False` y `resolve_entities=False`.
    if arbol_completo.docinfo.doctype:
        raise MalformedXML("El documento declara DOCTYPE")
    if arbol_completo.docinfo.internalDTD is not None:
        raise MalformedXML("El documento declara un subconjunto DTD interno")
    if arbol_completo.docinfo.externalDTD is not None:
        raise MalformedXML("El documento declara una DTD externa")

    # 3 · Identidad: namespace + local-name. Nunca el nombre del fichero.
    raiz = _local(arbol)
    tag = arbol.tag
    ns = tag[1:].split("}")[0] if isinstance(tag, str) and tag.startswith("{") else ""

    encontrado = registro.para(raiz, ns)
    if encontrado is None:
        raise UnsupportedDocument(
            "Raíz o namespace no reconocidos", raiz=raiz, namespace=ns
        )
    entrada, schema = encontrado

    if raiz not in TIPO_POR_RAIZ:
        # MensajeHacienda tiene esquema, pero no es un comprobante: no tiene
        # líneas ni totales, y forzarlo en el modelo rompería su semántica.
        raise UnsupportedDocument(
            "El documento no es un comprobante fiscal", raiz=raiz
        )
    if raiz not in RAICES_SOPORTADAS:
        raise UnsupportedDocument(
            "Tipo reconocido pero sin soporte semántico probado", raiz=raiz
        )

    # 4 · Validación contra el esquema oficial VERIFICADO.
    if not schema.validate(arbol_completo):
        raise XSDValidationError(
            "El documento no es conforme a su esquema oficial",
            esquema=entrada.id, **_diagnostico_seguro(schema.error_log),
        )

    # 5 · Extracción semántica.
    return ParsedFiscalDocument(
        document=_sobre(arbol, TIPO_POR_RAIZ[raiz]),
        parties=_partes(arbol),
    )


def _partes(arbol: etree._Element) -> tuple[ParsedDocumentParty, ...]:
    emisor = _hijo(arbol, "Emisor")
    if emisor is None:
        raise SemanticParseError("Falta el Emisor", campo="Emisor")
    partes = [_parte(emisor, "issuer")]

    receptor = _hijo(arbol, "Receptor")
    if receptor is not None:            # opcional en TE, NC y ND
        partes.append(_parte(receptor, "receiver"))
    return tuple(partes)


def _sobre(arbol: etree._Element, document_type: str) -> ParsedElectronicDocument:
    resumen = _hijo(arbol, "ResumenFactura")
    if resumen is None:
        raise SemanticParseError("Falta ResumenFactura", campo="ResumenFactura")

    moneda = _ruta(resumen, "CodigoTipoMoneda")
    fecha_literal = _obligatorio(_texto(_hijo(arbol, "FechaEmision")), "FechaEmision")

    return ParsedElectronicDocument(
        document_type=document_type,
        clave=_obligatorio(_texto(_hijo(arbol, "Clave")), "Clave"),
        consecutive_number=_obligatorio(
            _texto(_hijo(arbol, "NumeroConsecutivo")), "NumeroConsecutivo"
        ),
        fecha=_fecha(fecha_literal, "FechaEmision"),
        issuer_activity_code=_obligatorio(
            _texto(_hijo(arbol, "CodigoActividadEmisor")), "CodigoActividadEmisor"
        ),
        receiver_activity_code=_texto(_hijo(arbol, "CodigoActividadReceptor")) or None,
        sale_condition_code=_obligatorio(
            _texto(_hijo(arbol, "CondicionVenta")), "CondicionVenta"
        ),
        credit_term=_entero(_hijo(arbol, "PlazoCredito"), "PlazoCredito"),
        currency_code=_obligatorio(
            _texto(_hijo(moneda, "CodigoMoneda")), "CodigoMoneda"
        ),
        reported_exchange_rate=_decimal_obligatorio(
            _hijo(moneda, "TipoCambio"), "TipoCambio"
        ),
        # Totales del resumen. Los opcionales quedan en None si el elemento no
        # aparece: ausente no es cero.
        reported_total_taxed=_decimal(_hijo(resumen, "TotalGravado"), "TotalGravado"),
        reported_total_exempt=_decimal(_hijo(resumen, "TotalExento"), "TotalExento"),
        reported_total_exonerated=_decimal(
            _hijo(resumen, "TotalExonerado"), "TotalExonerado"
        ),
        reported_total_not_subject=_decimal(
            _hijo(resumen, "TotalNoSujeto"), "TotalNoSujeto"
        ),
        reported_total_sale=_decimal_obligatorio(
            _hijo(resumen, "TotalVenta"), "TotalVenta"
        ),
        reported_total_discount=_decimal(
            _hijo(resumen, "TotalDescuentos"), "TotalDescuentos"
        ),
        reported_total_net_sale=_decimal_obligatorio(
            _hijo(resumen, "TotalVentaNeta"), "TotalVentaNeta"
        ),
        reported_total_tax=_decimal(_hijo(resumen, "TotalImpuesto"), "TotalImpuesto"),
        reported_total_document=_decimal_obligatorio(
            _hijo(resumen, "TotalComprobante"), "TotalComprobante"
        ),
    )
