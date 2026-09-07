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

    De ahí que ninguno pueda ser vacío: una identificación a medias no existe
    en la fuente, y representarla aquí sería inventar un estado.
    """

    tipo: str
    numero: str

    def __post_init__(self) -> None:
        # No se normaliza el texto para validarlo: el XSD no exige
        # normalización de espacios y hacerlo alteraría el valor reportado.
        if not self.tipo:
            raise ValueError("Identificacion.tipo no puede estar vacío")
        if not self.numero:
            raise ValueError("Identificacion.numero no puede estar vacío")


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
    """Resultado del parser para **el alcance de B1**.

    Deliberadamente **no** incluye `lines`, `taxes`, `discounts` ni
    `references`: B1 no los normaliza, y devolver listas vacías fingiría una
    cobertura que no existe. Entrarán como campos propios cuando se
    implementen.

    Tampoco incluye `SourceDocument`: los bytes crudos, su huella y el estado
    de parseo son responsabilidad de la ingesta.
    """

    document: ParsedElectronicDocument
    parties: tuple[ParsedDocumentParty, ...]

    @property
    def issuer(self) -> ParsedDocumentParty:
        return next(p for p in self.parties if p.role == "issuer")

    @property
    def receiver(self) -> ParsedDocumentParty | None:
        return next((p for p in self.parties if p.role == "receiver"), None)
