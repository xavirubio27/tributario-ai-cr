"""Contratos HTTP de la frontera fiscal.

El backend es dueño de la SEMÁNTICA ESTABLE —un código y una categoría que no
cambian aunque cambie la redacción—; el frontend es dueño del texto que lee
una persona. Por eso aquí no hay ni una frase de producto en español: si la
hubiera, la copia viviría en dos sitios y acabarían divergiendo.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class UploadOutcome(StrEnum):
    """Los tres desenlaces con éxito de C2. Reflejan `ProcessingStatus`."""

    CREATED = "created"
    LINKED_EXISTING = "linked_existing"
    ALREADY_PERSISTED = "already_persisted"


class ErrorCategory(StrEnum):
    """Familia del fallo, para que el cliente decida sin leer el código.

    Es deliberadamente más gruesa que `code`: la interfaz agrupa por categoría
    —«no válido», «requiere revisión»— y solo baja al código cuando necesita
    distinguir dentro de una familia.
    """

    #: La petición misma está mal formada —un `company_id` que no es un UUID—.
    #: No habla del documento: no se llegó a mirar ningún byte fiscal.
    INVALID_REQUEST = "invalid_request"
    #: Rechazado ANTES de guardar nada: no existe artefacto que referenciar.
    REJECTED_BEFORE_CAPTURE = "rejected_before_capture"
    #: El artefacto existe, pero no se pudo interpretar.
    INVALID_DOCUMENT = "invalid_document"
    #: No se reconoce qué documento es.
    UNRECOGNIZED = "unrecognized"
    #: Se reconoce, pero no es un comprobante de este pipeline.
    OUTSIDE_PIPELINE = "outside_pipeline"
    #: Comprobante reconocido cuyo soporte semántico no existe todavía.
    NOT_YET_SUPPORTED = "not_yet_supported"
    #: Parseó bien; hace falta una persona para resolverlo.
    REQUIRES_REVIEW = "requires_review"
    FORBIDDEN = "forbidden"
    NOT_FOUND = "not_found"
    #: Fallo transitorio nuestro: reintentar tiene sentido.
    TEMPORARY = "temporary"
    #: Fallo nuestro, no transitorio. El cuerpo no dice más.
    INTERNAL = "internal"


class UploadAccepted(BaseModel):
    """Respuesta de éxito. Mínima a propósito.

    No lleva emisor, fecha ni total: `IngestionResult` no los trae, y sacarlos
    exigiría lecturas adicionales a la base para una comodidad de interfaz.
    Cuando exista una API de lectura, será suya.
    """

    status: UploadOutcome
    source_document_id: str
    electronic_document_id: str


class UploadError(BaseModel):
    """Respuesta de fallo. Estable, segura y sin diagnóstico interno."""

    code: str = Field(description="Identificador estable del fallo.")
    category: ErrorCategory
    #: Presente solo cuando la evidencia SÍ quedó guardada y es seguro
    #: devolverla. Permite retomar el artefacto sin volver a subirlo.
    source_document_id: str | None = None
    #: Discriminador estructurado, cuando el dominio lo define — hoy solo
    #: `UnsupportedDocumentReason`.
    reason: str | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Bandeja de documentos (C3-B3)
# ─────────────────────────────────────────────────────────────────────────────


class InboxItemKind(StrEnum):
    """Qué representa la fila.

    Discrimina el contrato: un `document` colapsa varias recepciones, así que
    NO tiene un `source_document_id` natural — elegir una de ellas sería
    arbitrario, y un cliente acabaría tratándola como «la» evidencia.
    """

    DOCUMENT = "document"
    RECEIPT = "receipt"


class InboxItemResponse(BaseModel):
    """Una fila de la bandeja. Solo hechos durables y seguros.

    Sin emisor ni receptor, sin dirección, sin tratamiento tributario, sin
    deducibilidad y sin IVA. La bandeja informa de OPERACIONES sobre
    documentos, no de fiscalidad.
    """

    kind: InboxItemKind
    operational_status: str
    #: Presente solo en `receipt`.
    source_document_id: str | None = None
    #: Presente solo en `document`.
    electronic_document_id: str | None = None
    #: Instante de llegada de la evidencia; en un `document`, el de la
    #: recepción más reciente de las que colapsa.
    received_at: str
    receipt_count: int
    document_type: str | None = None
    #: Fecha de emisión tal y como la declaró el documento (ADR-039): se
    #: conserva el reloj de pared, y el desplazamiento solo aparece si la
    #: fuente lo declaró. No se inventa huso.
    issued_at_local: str | None = None
    issued_at_offset_minutes: int | None = None
    consecutive_number: str | None = None
    currency_code: str | None = None
    #: CADENA, nunca número: un importe fiscal en coma flotante binaria es un
    #: importe distinto. Se serializa el decimal exacto.
    reported_total_document: str | None = None


class InboxCountsResponse(BaseModel):
    """Contadores de TODA la empresa, ajenos al cursor y al filtro.

    Responden a «¿tengo algo pendiente?», así que filtrarlos por la página que
    se está mirando los haría inútiles.
    """

    #: Lo que depende del usuario. `not_yet_supported` y `outside_pipeline`
    #: quedan fuera a propósito: son límites de Tribuu, no deudas suyas.
    needs_attention: int
    system_pending: int


class InboxPageResponse(BaseModel):
    items: list[InboxItemResponse]
    next_cursor: str | None = None
    counts: InboxCountsResponse
