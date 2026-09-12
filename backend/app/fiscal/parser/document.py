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

Alcance: el comprobante completo tal y como lo declara la fuente —
`ElectronicDocument`, `DocumentParty` (B1) y el cuerpo de la transacción:
`DocumentLine` con sus `LineDiscount` y `LineTax`, más `DocumentReference`
(B2)—. Lo que el modelo aprobado no normaliza se deja diferido de forma
explícita, no a medias.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from lxml import etree

from app.fiscal.errors import (
    DocumentDetection,
    MalformedXML,
    SemanticParseError,
    UnsupportedDocument,
    UnsupportedDocumentReason,
    ValidatorConfigurationError,
    XSDValidationError,
)
from app.fiscal.models import (
    TIPO_DETECTADO_POR_RAIZ,
    TIPO_POR_RAIZ,
    FechaFiscal,
    Identificacion,
    ParsedDocumentLine,
    ParsedDocumentParty,
    ParsedDocumentReference,
    ParsedElectronicDocument,
    ParsedFiscalDocument,
    ParsedLineDiscount,
    ParsedLineTax,
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


def _deteccion(entrada, raiz: str) -> DocumentDetection:
    """Identidad del documento, en vocabulario canónico nuestro.

    La versión sale del manifiesto del paquete aprobado, no de deducirla del
    identificador ni del namespace.
    """
    return DocumentDetection(
        document_type=TIPO_DETECTADO_POR_RAIZ[raiz],
        schema_version=entrada.version,
    )


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


def _hijos(padre: etree._Element | None, nombre: str) -> list[etree._Element]:
    """TODOS los hijos directos con ese local-name, **en orden de documento**.

    El orden es evidencia: `lxml` recorre los hijos como aparecen en el XML,
    así que no hace falta ordenar nada — y ordenar sería precisamente el
    error, porque impondría un criterio nuestro sobre el del emisor.
    """
    if padre is None:
        return []
    return [h for h in padre if isinstance(h.tag, str) and _local(h) == nombre]


def _ruta(raiz: etree._Element, *nombres: str) -> etree._Element | None:
    actual: etree._Element | None = raiz
    for n in nombres:
        actual = _hijo(actual, n)
        if actual is None:
            return None
    return actual


def _texto_colapsado(elemento: etree._Element | None) -> str | None:
    """Texto con la normalización `whiteSpace="collapse"` de XML Schema.

    **Solo para tipos cuya faceta `whiteSpace` es realmente `collapse`**, que
    en los campos modelados son `xs:decimal`, `xs:positiveInteger` y
    `xs:dateTime`. Para ellos la normalización no es una comodidad nuestra: la
    define el propio tipo, y el espacio en los extremos no forma parte del
    valor.

    `collapse` no es `strip`: además de recortar los extremos, funde cada
    secuencia interna de espacios en uno solo. Se implementa tal cual, en vez
    de aproximarlo, para no volver a inventar una normalización.

    - elemento ausente        → `None`
    - elemento presente vacío → `""`
    """
    if elemento is None:
        return None
    return " ".join((elemento.text or "").split())


def _texto_literal(elemento: etree._Element | None) -> str | None:
    """Texto EXACTO, sin normalizar, distinguiendo los TRES estados de origen.

    - elemento ausente        → `None`
    - elemento presente vacío → `""`
    - elemento con contenido  → el texto **tal cual**, sin recortar

    **Es el accesor por defecto de todo campo de texto modelado.** Se auditó
    la cadena de tipos de los veinte campos de cadena que B1 y B2 normalizan y
    **todos** derivan de `xs:string`, cuya faceta es `whiteSpace="preserve"`.
    Ninguno es `xs:token` ni `xs:normalizedString`. Es decir: el esquema
    oficial **no define** normalización de espacios para ninguno de ellos, y
    recortarlos era una invención nuestra.

    El argumento de que «tiene enumeración o patrón, luego recortar es
    inocuo» no vale, y por dos motivos. Uno: la faceta de espacios no se
    deduce de las demás facetas, viene del tipo. Y dos: era falso en la
    práctica — `Detalle`, `Nombre`, `NombreComercial`,
    `Identificacion/Numero` y `CodigoActividadEmisor` admiten espacios en un
    documento XSD-válido, y con `Numero` el recorte llegaba a **rechazar**
    el comprobante.

    Que un valor con espacios sea legal o no lo decide el XSD por longitud,
    patrón o enumeración — y lo comprueba antes de que lleguemos aquí.
    """
    if elemento is None:
        return None
    return elemento.text if elemento.text is not None else ""


def _decimal(elemento: etree._Element | None, campo: str) -> Decimal | None:
    """`Decimal` construido desde el LITERAL. Nunca vía `float`.

    Un ausente devuelve `None`, no `Decimal("0")`: el modelo físico distingue
    ambos estados y colapsarlos perdería información fiscal.
    """
    crudo = _texto_colapsado(elemento)
    if crudo is None or crudo == "":
        return None
    try:
        return Decimal(crudo)
    except InvalidOperation as exc:
        raise SemanticParseError(
            "Importe no interpretable como decimal", campo=campo
        ) from exc


def _entero(elemento: etree._Element | None, campo: str) -> int | None:
    crudo = _texto_colapsado(elemento)
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


def _elemento_obligatorio(valor: str | None, campo: str) -> str:
    """Exige que el ELEMENTO exista, no que su texto sea no vacío.

    `_obligatorio` trata `""` como ausente, y eso vale para los campos cuyo
    tipo XSD no admite la cadena vacía. Pero `Identificacion/Numero` es
    `minOccurs=1` y `xs:string` **sin `minLength`**: el elemento es
    obligatorio y su valor puede ser vacío. Son dos exigencias distintas, y
    confundirlas hacía que un comprobante XSD-válido acabara rechazado.
    """
    if valor is None:
        raise SemanticParseError("Elemento obligatorio ausente", campo=campo)
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
    nombre = _obligatorio(_texto_literal(_hijo(nodo, "Nombre")), f"{role}/Nombre")

    ident_nodo = _hijo(nodo, "Identificacion")
    identificacion = None
    if ident_nodo is not None:
        identificacion = Identificacion(
            tipo=_obligatorio(
                _texto_literal(_hijo(ident_nodo, "Tipo")), f"{role}/Identificacion/Tipo"
            ),
            # `Numero` es `minOccurs=1` pero `xs:string` SIN `minLength`: el
            # elemento tiene que estar, su contenido puede ser vacío.
            numero=_elemento_obligatorio(
                _texto_literal(_hijo(ident_nodo, "Numero")),
                f"{role}/Identificacion/Numero",
            ),
        )

    comercial = _texto_literal(_hijo(nodo, "NombreComercial"))
    return ParsedDocumentParty(
        role=role,
        legal_name=nombre,
        identificacion=identificacion,
        trade_name=comercial or None,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Cuerpo de la transacción (B2)
#
# Todo lo de aquí se lee del árbol que YA se parseó de forma segura y YA pasó
# el esquema oficial. No se vuelve a llamar a `etree.fromstring`: un segundo
# parseo sería una segunda configuración que mantener, y la tentación de
# relajarla «solo para las líneas» es exactamente cómo se pierde el
# endurecimiento.
#
# Las rutas de error son ESTRUCTURALES —`LineaDetalle[3]/Impuesto[1]/Monto`—
# y no llevan contenido: ni descripciones, ni identificadores, ni importes.
# ─────────────────────────────────────────────────────────────────────────────

def _impuesto(nodo: etree._Element, ruta: str) -> ParsedLineTax:
    return ParsedLineTax(
        tax_code=_obligatorio(_texto_literal(_hijo(nodo, "Codigo")), f"{ruta}/Codigo"),
        reported_amount=_decimal_obligatorio(_hijo(nodo, "Monto"), f"{ruta}/Monto"),
        # Opcionales en el XSD: ausente es `None`. No se convierte un ausente
        # en «0 %» ni en «exento» — eso sería una conclusión fiscal.
        vat_rate_code=_texto_literal(_hijo(nodo, "CodigoTarifaIVA")),
        reported_rate=_decimal(_hijo(nodo, "Tarifa"), f"{ruta}/Tarifa"),
    )


def _descuento(nodo: etree._Element, ruta: str) -> ParsedLineDiscount:
    return ParsedLineDiscount(
        reported_amount=_decimal_obligatorio(
            _hijo(nodo, "MontoDescuento"), f"{ruta}/MontoDescuento"
        ),
        discount_code=_obligatorio(
            _texto_literal(_hijo(nodo, "CodigoDescuento")), f"{ruta}/CodigoDescuento"
        ),
    )


def _linea(nodo: etree._Element, posicion: int) -> ParsedDocumentLine:
    """Una `LineaDetalle`. `posicion` es 1-based y **solo** sirve para la ruta
    de diagnóstico: el número de línea del modelo sale de `NumeroLinea`."""
    ruta = f"LineaDetalle[{posicion}]"

    numero = _entero(_hijo(nodo, "NumeroLinea"), f"{ruta}/NumeroLinea")
    if numero is None:
        raise SemanticParseError(
            "Campo obligatorio ausente o vacío", campo=f"{ruta}/NumeroLinea"
        )

    return ParsedDocumentLine(
        line_number=numero,
        cabys_code=_obligatorio(
            _texto_literal(_hijo(nodo, "CodigoCABYS")), f"{ruta}/CodigoCABYS"
        ),
        description=_obligatorio(_texto_literal(_hijo(nodo, "Detalle")), f"{ruta}/Detalle"),
        unit_of_measure_code=_obligatorio(
            _texto_literal(_hijo(nodo, "UnidadMedida")), f"{ruta}/UnidadMedida"
        ),
        reported_quantity=_decimal_obligatorio(
            _hijo(nodo, "Cantidad"), f"{ruta}/Cantidad"
        ),
        reported_unit_price=_decimal_obligatorio(
            _hijo(nodo, "PrecioUnitario"), f"{ruta}/PrecioUnitario"
        ),
        reported_gross_amount=_decimal_obligatorio(
            _hijo(nodo, "MontoTotal"), f"{ruta}/MontoTotal"
        ),
        reported_subtotal=_decimal_obligatorio(
            _hijo(nodo, "SubTotal"), f"{ruta}/SubTotal"
        ),
        reported_taxable_base=_decimal_obligatorio(
            _hijo(nodo, "BaseImponible"), f"{ruta}/BaseImponible"
        ),
        reported_net_tax=_decimal_obligatorio(
            _hijo(nodo, "ImpuestoNeto"), f"{ruta}/ImpuestoNeto"
        ),
        reported_line_total=_decimal_obligatorio(
            _hijo(nodo, "MontoTotalLinea"), f"{ruta}/MontoTotalLinea"
        ),
        # 0..5 en el XSD. Una línea sin `Descuento` da una tupla VACÍA, no un
        # descuento sintético de cero: ausente y cero no son lo mismo.
        discounts=tuple(
            _descuento(d, f"{ruta}/Descuento[{i}]")
            for i, d in enumerate(_hijos(nodo, "Descuento"), start=1)
        ),
        # 1..1000 en el XSD. Se recorren todos: aplanar a un solo impuesto por
        # línea perdería documentos legítimos con varios.
        taxes=tuple(
            _impuesto(t, f"{ruta}/Impuesto[{i}]")
            for i, t in enumerate(_hijos(nodo, "Impuesto"), start=1)
        ),
    )


def _lineas(arbol: etree._Element) -> tuple[ParsedDocumentLine, ...]:
    """`DetalleServicio` es 0..1 en FE, TE y NC: si no está, no hay líneas."""
    detalle = _hijo(arbol, "DetalleServicio")
    return tuple(
        _linea(n, i) for i, n in enumerate(_hijos(detalle, "LineaDetalle"), start=1)
    )


def _referencia(nodo: etree._Element, posicion: int) -> ParsedDocumentReference:
    ruta = f"InformacionReferencia[{posicion}]"
    literal = _obligatorio(
        _texto_colapsado(_hijo(nodo, "FechaEmisionIR")), f"{ruta}/FechaEmisionIR"
    )
    return ParsedDocumentReference(
        referenced_document_type_code=_obligatorio(
            _texto_literal(_hijo(nodo, "TipoDocIR")), f"{ruta}/TipoDocIR"
        ),
        # Mismo tratamiento que `FechaEmision` del sobre (ADR-039): reloj de
        # pared siempre; instante y desplazamiento solo si la fuente los da.
        fecha=_fecha(literal, f"{ruta}/FechaEmisionIR"),
        # `Numero` y `Razon` son 0..1 y `xs:string` SIN `minLength`, así que
        # la fuente distingue tres estados: ausente, presente-vacío y con
        # texto. `… or None` fundía los dos primeros y perdía información.
        reported_number=_texto_literal(_hijo(nodo, "Numero")),
        reason=_texto_literal(_hijo(nodo, "Razon")),
        # `Codigo` es `CodigoReferenciaType`, con `minLength=maxLength=2`: un
        # presente-vacío NO es un estado legal, así que aquí sí se colapsa.
        reference_code=_texto_literal(_hijo(nodo, "Codigo")),
    )


def _referencias(arbol: etree._Element) -> tuple[ParsedDocumentReference, ...]:
    """0..10 en FE y TE; **1..10 en NC**, que exige al menos una. El mínimo lo
    impone el esquema oficial, así que aquí no hace falta repetirlo."""
    return tuple(
        _referencia(n, i)
        for i, n in enumerate(_hijos(arbol, "InformacionReferencia"), start=1)
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
        # No se identificó NADA: no hay detección que reportar.
        raise UnsupportedDocument(
            "Raíz o namespace no reconocidos",
            reason=UnsupportedDocumentReason.UNKNOWN_DOCUMENT,
            raiz=raiz, namespace=ns,
        )
    entrada, schema = encontrado
    # A partir de aquí el esquema está identificado, así que todo fallo puede
    # decir QUÉ era el documento sin que nadie vuelva a mirar el XML.
    deteccion = _deteccion(entrada, raiz)

    if raiz not in TIPO_POR_RAIZ:
        # MensajeHacienda tiene esquema, pero no es un comprobante: no tiene
        # líneas ni totales, y forzarlo en el modelo rompería su semántica.
        raise UnsupportedDocument(
            "El documento no es un comprobante fiscal",
            reason=UnsupportedDocumentReason.OUTSIDE_PIPELINE,
            detection=deteccion, raiz=raiz,
        )
    if raiz not in RAICES_SOPORTADAS:
        raise UnsupportedDocument(
            "Tipo reconocido pero sin soporte semántico probado",
            reason=UnsupportedDocumentReason.UNSUPPORTED_TYPE,
            detection=deteccion, raiz=raiz,
        )

    # 4 · Validación contra el esquema oficial VERIFICADO.
    if not schema.validate(arbol_completo):
        raise XSDValidationError(
            "El documento no es conforme a su esquema oficial",
            detection=deteccion,
            esquema=entrada.id, **_diagnostico_seguro(schema.error_log),
        )

    # 5 · Extracción semántica.
    return ParsedFiscalDocument(
        document=_sobre(arbol, TIPO_POR_RAIZ[raiz]),
        parties=_partes(arbol),
        lines=_lineas(arbol),
        references=_referencias(arbol),
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
    fecha_literal = _obligatorio(_texto_colapsado(_hijo(arbol, "FechaEmision")), "FechaEmision")

    return ParsedElectronicDocument(
        document_type=document_type,
        clave=_obligatorio(_texto_literal(_hijo(arbol, "Clave")), "Clave"),
        consecutive_number=_obligatorio(
            _texto_literal(_hijo(arbol, "NumeroConsecutivo")), "NumeroConsecutivo"
        ),
        fecha=_fecha(fecha_literal, "FechaEmision"),
        issuer_activity_code=_obligatorio(
            _texto_literal(_hijo(arbol, "CodigoActividadEmisor")), "CodigoActividadEmisor"
        ),
        receiver_activity_code=_texto_literal(_hijo(arbol, "CodigoActividadReceptor")),
        sale_condition_code=_obligatorio(
            _texto_literal(_hijo(arbol, "CondicionVenta")), "CondicionVenta"
        ),
        credit_term=_entero(_hijo(arbol, "PlazoCredito"), "PlazoCredito"),
        currency_code=_obligatorio(
            _texto_literal(_hijo(moneda, "CodigoMoneda")), "CodigoMoneda"
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
