"""Modelos de dominio del parser fiscal.

`dataclass` **congelados**, no Pydantic: es la convención del repositorio para
dominio interno, y aquí hay además una razón de fondo — Pydantic coacciona
tipos, y este parser existe precisamente para *no* transformar la fuente.

Estos modelos **no contienen**: `company_id`, claves primarias, claves ajenas
ni contexto de RLS. Todo eso es de la capa de persistencia. El parser describe
lo que **dice el documento**, no dónde acabará guardado.

Todo valor es **reportado**. Ningún `computed_*` sale de aquí.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

# Tipos normalizados internos. Mapeo aprobado en E4-A2 (A2-B0) y fijado por el
# CHECK de `fiscal.electronic_documents.document_type`.
TIPO_POR_RAIZ: dict[str, str] = {
    "FacturaElectronica": "invoice",
    "TiqueteElectronico": "ticket",
    "NotaCreditoElectronica": "credit_note",
    "NotaDebitoElectronica": "debit_note",
}


#: Tipo canónico DETECTADO, para `source_documents.detected_document_type`.
#: Superconjunto de `TIPO_POR_RAIZ`: añade lo que el paquete sabe identificar
#: pero no se normaliza como comprobante. Un vocabulario, no dos.
TIPO_DETECTADO_POR_RAIZ: dict[str, str] = {
    **TIPO_POR_RAIZ,
    "MensajeHacienda": "hacienda_message",
}


# Cardinalidad de `InformacionReferencia` por tipo de comprobante, verificada
# elemento por elemento en los CUATRO esquemas oficiales vendorizados. La Nota
# de Crédito y la de Débito exigen al menos una referencia; la Factura y el
# Tiquete no.
#
#     invoice      0..10        credit_note  1..10
#     ticket       0..10        debit_note   1..10
REFERENCIAS_POR_TIPO: dict[str, tuple[int, int]] = {
    "invoice": (0, 10),
    "ticket": (0, 10),
    "credit_note": (1, 10),
    "debit_note": (1, 10),
}


@dataclass(frozen=True, slots=True)
class FechaFiscal:
    """La fecha tal y como la declara la fuente (ADR-039).

    El desplazamiento es **opcional en el XSD** —4 de 13 comprobantes reales no
    lo traen—, así que el instante absoluto solo existe cuando la fuente da con
    qué resolverlo. **Nunca se infiere una zona horaria.**
    """

    #: Reloj de pared declarado. Existe siempre.
    local: datetime
    #: Literal exacto del XML. Existe siempre.
    raw: str
    #: Instante absoluto. `None` si la fuente no declara desplazamiento.
    instante: datetime | None = None
    #: Desplazamiento declarado, en minutos. `None` si la fuente no lo declara.
    offset_minutos: int | None = None

    #: Rango legal del desplazamiento en `xs:dateTime`: −14:00 .. +14:00.
    #: Es el límite de XML Schema, no una regla de Costa Rica.
    OFFSET_MINIMO = -840
    OFFSET_MAXIMO = 840

    def __post_init__(self) -> None:
        # El reloj de pared no lleva huso: si lo llevara, el "local" ya sería
        # un instante y la separación de ADR-039 se habría perdido.
        if self.local.tzinfo is not None:
            raise ValueError("local es un reloj de pared: no puede llevar huso")

        # Instante y desplazamiento van juntos o no van: mismo invariante que
        # impone la base de datos.
        if (self.instante is None) != (self.offset_minutos is None):
            raise ValueError(
                "instante y offset_minutos deben ser ambos nulos o ambos presentes"
            )
        if self.instante is None:
            return

        # Un instante absoluto sin huso no es un instante.
        if self.instante.tzinfo is None:
            raise ValueError("el instante absoluto debe llevar huso")

        if not (self.OFFSET_MINIMO <= self.offset_minutos <= self.OFFSET_MAXIMO):
            raise ValueError(
                f"desplazamiento fuera del rango de xs:dateTime: "
                f"{self.offset_minutos}"
            )

        # Las dos representaciones no pueden contradecirse. Es el mismo
        # invariante que el CHECK de coherencia de la base de datos.
        esperado = (self.local - timedelta(minutes=self.offset_minutos)).replace(
            tzinfo=timezone.utc
        )
        if self.instante != esperado:
            raise ValueError(
                "el instante no corresponde al reloj de pared desplazado"
            )


@dataclass(frozen=True, slots=True)
class Identificacion:
    """Identificación reportada de una parte.

    Sus dos campos son solidarios: `IdentificacionType` declara `Tipo` y
    `Numero` con `minOccurs=1`, así que si el nodo existe, existen los dos.
    Cuando el nodo falta, esta clase **no se instancia** — se usa `None`.

    **Que el elemento sea obligatorio no significa que su texto no pueda ser
    vacío**, y los dos campos difieren justo en eso:

    - `Tipo` es `xs:string` con **seis enumeraciones** (`01`…`06`): la cadena
      vacía no está entre ellas, así que no es un estado legal.
    - `Numero` es `xs:string` con `maxLength=20` y **sin `minLength`**: la
      cadena vacía **sí** es legal, y verificado contra el validador oficial.

    De ahí la asimetría de los invariantes. La distinción que importa no es
    vacío/no vacío, sino:

        identificación ausente        →  esta clase no se instancia (`None`)
        identificación con Numero=""  →  Identificacion(tipo, "")

    Colapsar la segunda en la primera diría que el emisor no identificó a la
    parte, cuando sí la identificó — con un número vacío.
    """

    tipo: str
    numero: str

    def __post_init__(self) -> None:
        # No se normaliza el texto para validarlo: el XSD no exige
        # normalización de espacios y hacerlo alteraría el valor reportado.
        if not self.tipo:
            raise ValueError("Identificacion.tipo no puede estar vacío")
        # `numero` NO se comprueba: `""` es un valor legal de la fuente.
        if self.numero is None:                      # type: ignore[unreachable]
            raise ValueError(
                "Identificacion.numero no puede ser None: si Identificacion "
                "existe, Numero existe"
            )


@dataclass(frozen=True, slots=True)
class ParsedDocumentParty:
    """Instantánea de una parte, tal como la declaró el comprobante.

    No se resuelve contra empresas ni usuarios del SaaS: es evidencia
    histórica, no una referencia viva.
    """

    role: str                       # 'issuer' | 'receiver'
    legal_name: str
    identificacion: Identificacion | None = None
    trade_name: str | None = None

    def __post_init__(self) -> None:
        if self.role not in ("issuer", "receiver"):
            raise ValueError(f"role inesperado: {self.role!r}")
        if not self.legal_name:
            raise ValueError("legal_name no puede estar vacío")
        # El emisor va identificado en los cuatro tipos (XSD min=1). El
        # receptor puede no estarlo en TE/NC/ND — ver B0.1.
        if self.role == "issuer" and self.identificacion is None:
            raise ValueError("el emisor siempre declara identificación")


# ─────────────────────────────────────────────────────────────────────────────
# Cuerpo de la transacción (B2)
#
# Cardinalidades **verificadas en el XSD oficial v4.4 vendorizado**, no de
# memoria:
#
#     DetalleServicio            0..1     (FE · TE · NC)
#     DetalleServicio/LineaDetalle
#                                1..1000
#     LineaDetalle/Descuento     0..5
#     LineaDetalle/Impuesto      1..1000
#     InformacionReferencia      0..10    en FE y TE
#                                1..10    en NC   ← la NC exige al menos una
#
# Las colecciones hijas son **tuplas**: los modelos son congelados, y una
# lista dejaría el agregado mutable por dentro pese al `frozen=True`.
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ParsedLineTax:
    """Un `Impuesto` de línea, tal y como lo declara el comprobante.

    **Evidencia reportada, no cálculo.** El parser no multiplica base por
    tarifa, no recalcula `Monto`, no deduce la tarifa del código ni el código
    de la tarifa, y no compara lo reportado con lo que «debería» salir. Eso
    es del Tax Engine, que no existe todavía.

    `CodigoImpuestoOTRO`, `FactorCalculoIVA`, `DatosImpuestoEspecifico` y
    `Exoneracion` existen en el XSD pero **no** están en el modelo aprobado:
    quedan diferidos, no se normalizan y su presencia no hace fallar nada.
    """

    tax_code: str                       # Codigo            1..1
    reported_amount: Decimal            # Monto             1..1
    vat_rate_code: str | None = None    # CodigoTarifaIVA   0..1
    reported_rate: Decimal | None = None  # Tarifa          0..1

    def __post_init__(self) -> None:
        if not self.tax_code:
            raise ValueError("ParsedLineTax.tax_code no puede estar vacío")
        # Ausente es `None`. Una cadena vacía no es ninguno de los dos estados
        # que la fuente puede expresar, así que no se admite.
        if self.vat_rate_code is not None and not self.vat_rate_code:
            raise ValueError("vat_rate_code presente no puede estar vacío")


@dataclass(frozen=True, slots=True)
class ParsedLineDiscount:
    """Un `Descuento` de línea.

    `CodigoDescuentoOTRO` y `NaturalezaDescuento` son opcionales en el XSD y
    no están en el modelo aprobado: diferidos.
    """

    reported_amount: Decimal    # MontoDescuento   1..1
    discount_code: str          # CodigoDescuento  1..1

    def __post_init__(self) -> None:
        if not self.discount_code:
            raise ValueError("ParsedLineDiscount.discount_code no puede estar vacío")


@dataclass(frozen=True, slots=True)
class ParsedDocumentLine:
    """Una `LineaDetalle`.

    `line_number` es el **`NumeroLinea` declarado por la fuente**, no la
    posición en la colección. Si el documento numerase sus líneas de forma
    inesperada, el parser lo reporta tal cual: corregirlo sería inventar.

    Diferidos —presentes en el XSD, fuera del modelo aprobado—:
    `CodigoComercial`, `TipoTransaccion`, `UnidadMedidaComercial`,
    `NumeroVINoSerie`, `RegistroMedicamento`, `FormaFarmaceutica`,
    `DetalleSurtido`, `IVACobradoFabrica` e `ImpuestoAsumidoEmisorFabrica`.
    """

    line_number: int                    # NumeroLinea      1..1
    cabys_code: str                     # CodigoCABYS      1..1
    description: str                    # Detalle          1..1
    unit_of_measure_code: str           # UnidadMedida     1..1
    reported_quantity: Decimal          # Cantidad         1..1
    reported_unit_price: Decimal        # PrecioUnitario   1..1
    reported_gross_amount: Decimal      # MontoTotal       1..1
    reported_subtotal: Decimal          # SubTotal         1..1
    reported_taxable_base: Decimal      # BaseImponible    1..1
    reported_net_tax: Decimal           # ImpuestoNeto     1..1
    reported_line_total: Decimal        # MontoTotalLinea  1..1
    discounts: tuple[ParsedLineDiscount, ...] = ()
    taxes: tuple[ParsedLineTax, ...] = ()

    #: Rango de `NumeroLinea` en el XSD: `minInclusive=1`, `maxInclusive=1000`.
    LINEA_MINIMA = 1
    LINEA_MAXIMA = 1000
    #: `Descuento` es 0..5 por línea.
    DESCUENTOS_MAXIMOS = 5
    #: `Impuesto` es 1..1000 por línea: al menos uno es obligatorio.
    IMPUESTOS_MINIMOS = 1
    IMPUESTOS_MAXIMOS = 1000

    def __post_init__(self) -> None:
        # Cardinalidades ESTRUCTURALES del XSD oficial. Un documento que llega
        # por el contrato público ya pasó el esquema, así que estas guardas
        # protegen la otra puerta: la construcción directa del modelo, que no
        # pasa por ningún validador.
        if not (self.LINEA_MINIMA <= self.line_number <= self.LINEA_MAXIMA):
            raise ValueError(
                f"line_number fuera del rango del XSD "
                f"({self.LINEA_MINIMA}..{self.LINEA_MAXIMA})"
            )
        for campo in ("cabys_code", "description", "unit_of_measure_code"):
            if not getattr(self, campo):
                raise ValueError(f"ParsedDocumentLine.{campo} no puede estar vacío")
        # Las colecciones hijas no pueden ser listas: el modelo es congelado y
        # una lista lo dejaría mutable por dentro.
        if not isinstance(self.discounts, tuple) or not isinstance(self.taxes, tuple):
            raise TypeError("las colecciones hijas deben ser tuplas inmutables")
        if len(self.discounts) > self.DESCUENTOS_MAXIMOS:
            raise ValueError(
                f"el XSD admite hasta {self.DESCUENTOS_MAXIMOS} descuentos por línea"
            )
        # `Impuesto` es 1..1000: una línea sin impuesto no es un estado que la
        # fuente pueda expresar. No se exige NADA sobre su importe —cero es un
        # importe legítimo—, solo que la entidad exista.
        if not (self.IMPUESTOS_MINIMOS <= len(self.taxes) <= self.IMPUESTOS_MAXIMOS):
            raise ValueError(
                f"el XSD exige entre {self.IMPUESTOS_MINIMOS} y "
                f"{self.IMPUESTOS_MAXIMOS} impuestos por línea"
            )
        # NO se comprueba que los importes cuadren entre sí: que
        # `MontoTotalLinea` sea coherente con base, descuentos e impuesto es
        # una conclusión fiscal, y este parser no saca conclusiones.


@dataclass(frozen=True, slots=True)
class ParsedDocumentReference:
    """Una `InformacionReferencia`.

    **Sin resolver.** El parser conserva lo que la referencia dice y nada
    más: no busca el documento referido, no exige que exista en el corpus ni
    en la base, y no rellena ninguna identidad. La resolución es diferida y
    pertenece a la persistencia (ADR-028).

    `TipoDocRefOTRO` y `CodigoReferenciaOTRO` quedan diferidos.

    **Tres estados, no dos, en `reported_number` y `reason`.** Ambos son 0..1
    y `xs:string` **sin `minLength`** en los cuatro esquemas oficiales, de
    modo que la fuente puede decir tres cosas distintas:

        None  → el elemento no viene
        ""    → el elemento viene vacío
        "…"   → el elemento viene con texto

    `""` es un valor **válido**, no un hueco. La asimetría con
    `reference_code` es de la fuente, no nuestra: `CodigoReferenciaType`
    declara `minLength=maxLength=2`, así que ahí un vacío no es legal.
    """

    referenced_document_type_code: str  # TipoDocIR       1..1
    fecha: FechaFiscal                  # FechaEmisionIR  1..1  (ADR-039)
    reported_number: str | None = None  # Numero          0..1  ("" válido)
    reference_code: str | None = None   # Codigo          0..1
    reason: str | None = None           # Razon           0..1  ("" válido)

    def __post_init__(self) -> None:
        if not self.referenced_document_type_code:
            raise ValueError("referenced_document_type_code no puede estar vacío")
        # `Codigo` tiene longitud fija 2 en el XSD: presente-vacío no es un
        # estado que la fuente pueda expresar. `Numero` y `Razon` sí, y por
        # eso NO se comprueban aquí.
        if self.reference_code is not None and not self.reference_code:
            raise ValueError("reference_code presente no puede estar vacío")


@dataclass(frozen=True, slots=True)
class ParsedElectronicDocument:
    """El sobre del comprobante: todo lo que NO es de línea.

    Los importes son `Decimal` construidos desde el literal. Los opcionales son
    `None` cuando el elemento **no aparece** — nunca `Decimal("0")`: ausente y
    cero son cosas distintas y el modelo físico las distingue.
    """

    document_type: str
    clave: str
    consecutive_number: str
    fecha: FechaFiscal
    issuer_activity_code: str
    sale_condition_code: str
    currency_code: str
    reported_exchange_rate: Decimal
    reported_total_sale: Decimal
    reported_total_net_sale: Decimal
    reported_total_document: Decimal

    receiver_activity_code: str | None = None
    credit_term: int | None = None
    reported_total_taxed: Decimal | None = None
    reported_total_exempt: Decimal | None = None
    reported_total_exonerated: Decimal | None = None
    reported_total_not_subject: Decimal | None = None
    reported_total_discount: Decimal | None = None
    reported_total_tax: Decimal | None = None


@dataclass(frozen=True, slots=True)
class ParsedFiscalDocument:
    """El comprobante completo tal y como lo declara la fuente (B1 + B2).

    B1 trajo el sobre y las partes; B2 completa el cuerpo de la transacción:
    líneas con sus descuentos e impuestos, y las referencias del documento.

    **`lines` y `references` son obligatorias, no opcionales.** Se consideró
    darles valor por defecto para no tocar a los consumidores de B1, y se
    descartó: un defecto por omisión convierte «no se extrajeron» en
    «no había», que es justo la confusión que este parser existe para evitar.
    El agregado se construye en un único sitio, así que exigirlas es
    determinista y barato.

    Tampoco incluye `SourceDocument`: los bytes crudos, su huella y el estado
    de parseo son responsabilidad de la ingesta.

    Sin identidad de base de datos en ninguna parte del árbol —ni UUID, ni
    `company_id`, ni claves ajenas—: la relación padre-hijo aquí es
    **estructural**. Los identificadores los pone la persistencia.
    """

    document: ParsedElectronicDocument
    parties: tuple[ParsedDocumentParty, ...]
    lines: tuple[ParsedDocumentLine, ...]
    references: tuple[ParsedDocumentReference, ...]

    def __post_init__(self) -> None:
        for campo in ("parties", "lines", "references"):
            if not isinstance(getattr(self, campo), tuple):
                raise TypeError(f"{campo} debe ser una tupla inmutable")

        # Cardinalidad de referencias, que **depende del tipo**: la Nota de
        # Crédito y la de Débito exigen al menos una. El agregado puede
        # comprobarlo porque conoce su propio `document_type`.
        #
        # Por el contrato público no se llega aquí —el XSD ya lo exigió—, pero
        # construir el agregado a mano no pasa por ningún validador, y una
        # nota de crédito sin referencia no es un estado que la fuente pueda
        # expresar.
        limites = REFERENCIAS_POR_TIPO.get(self.document.document_type)
        if limites is not None:
            minimo, maximo = limites
            if not (minimo <= len(self.references) <= maximo):
                raise ValueError(
                    f"{self.document.document_type} admite entre {minimo} y "
                    f"{maximo} referencias, no {len(self.references)}"
                )

    @property
    def issuer(self) -> ParsedDocumentParty:
        return next(p for p in self.parties if p.role == "issuer")

    @property
    def receiver(self) -> ParsedDocumentParty | None:
        return next((p for p in self.parties if p.role == "receiver"), None)
