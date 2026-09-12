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
