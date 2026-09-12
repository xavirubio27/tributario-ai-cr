"""Traducción de errores de dominio a respuestas HTTP seguras.

UN SOLO SITIO, a propósito. Construir `HTTPException` por el endpoint dejaría
la política de privacidad repartida por el código de ruta, y basta olvidarla
una vez para filtrar un diagnóstico.

DOS REGLAS QUE GOBIERNAN LA TABLA

1. **El cuerpo nunca contiene diagnóstico.** Ni `str(exc)`, ni `repr(exc)`,
   ni traza, ni mensajes de PostgreSQL, ni nombres de restricción, ni salida
   de lxml. Solo el código estable, la categoría y contexto ya saneado.

2. **`source_document_id` solo cuando la evidencia existe Y la categoría es
   segura.** Un 500 genérico no lo expone aunque el artefacto exista: no hay
   acción que ofrecer y el cuerpo debe decir lo mínimo. Un 503 sí, porque un
   reintento futuro puede reutilizar la evidencia ya guardada.
"""

from __future__ import annotations

from app.api.schemas import ErrorCategory, UploadError
from app.fiscal.errors import (
    ClaveConflict,
    EmptySourceDocument,
    FiscalWriteForbidden,
    MalformedXML,
    PersistenceUnavailable,
    SemanticParseError,
    SourceDocumentNotFound,
    SourceDocumentTooLarge,
    UnsupportedDocument,
    UnsupportedDocumentReason,
    XSDValidationError,
)

#: Categoría de cada motivo de `UnsupportedDocument`. El dominio ya distingue
#: los tres casos; colapsarlos aquí perdería información que el parser sí tiene.
_CATEGORIA_POR_MOTIVO = {
    UnsupportedDocumentReason.UNKNOWN_DOCUMENT: ErrorCategory.UNRECOGNIZED,
    UnsupportedDocumentReason.OUTSIDE_PIPELINE: ErrorCategory.OUTSIDE_PIPELINE,
    UnsupportedDocumentReason.UNSUPPORTED_TYPE: ErrorCategory.NOT_YET_SUPPORTED,
}

#: `excepción → (estado HTTP, categoría)`. El orden importa: se recorre de la
#: clase más específica a la más general.
_TABLA: tuple[tuple[type[Exception], int, ErrorCategory], ...] = (
    (SourceDocumentTooLarge, 413, ErrorCategory.REJECTED_BEFORE_CAPTURE),
    (EmptySourceDocument, 422, ErrorCategory.REJECTED_BEFORE_CAPTURE),
    (MalformedXML, 422, ErrorCategory.INVALID_DOCUMENT),
    (XSDValidationError, 422, ErrorCategory.INVALID_DOCUMENT),
    (SemanticParseError, 422, ErrorCategory.INVALID_DOCUMENT),
    (ClaveConflict, 409, ErrorCategory.REQUIRES_REVIEW),
    (FiscalWriteForbidden, 403, ErrorCategory.FORBIDDEN),
    (SourceDocumentNotFound, 404, ErrorCategory.NOT_FOUND),
    (PersistenceUnavailable, 503, ErrorCategory.TEMPORARY),
)

#: Petición mal formada en su propia estructura —hoy solo un `company_id` que
#: no es un UUID—. Es un fallo de la PETICIÓN, no del documento: etiquetarlo
#: como `malformed_xml` diría que el comprobante del contribuyente está mal
#: cuando ni siquiera se ha mirado.
PETICION_INVALIDA = UploadError(
    code="invalid_request", category=ErrorCategory.INVALID_REQUEST
)

#: Respuesta de los fallos que son NUESTROS y no transitorios: defectos de
#: mapeo, errores inesperados de base, paquete de esquemas mal desplegado y
#: cualquier excepción no prevista. Todos dicen lo mismo, a propósito.
FALLO_INTERNO = UploadError(code="internal_error", category=ErrorCategory.INTERNAL)


def _id_seguro(exc: Exception) -> str | None:
    """Identificador del artefacto, si el dominio lo adjuntó como contexto."""
    valor = getattr(exc, "contexto", {}).get("source_document_id")
    return str(valor) if valor is not None else None


def respuesta_de(exc: Exception) -> tuple[int, UploadError]:
    """`(estado HTTP, cuerpo seguro)` para un error de dominio.

    Lo que no reconoce cae en el 500 genérico. Es deliberado: un error nuevo
    sin entrada en la tabla no debe estrenarse filtrando su mensaje.
    """
    if isinstance(exc, UnsupportedDocument):
        return 422, UploadError(
            code=UnsupportedDocument.code,
            category=_CATEGORIA_POR_MOTIVO[exc.reason],
            source_document_id=_id_seguro(exc),
            reason=exc.reason.value,
        )

    for clase, estado, categoria in _TABLA:
        if isinstance(exc, clase):
            return estado, UploadError(
                code=clase.code,
                category=categoria,
                source_document_id=_id_seguro(exc),
            )

    return 500, FALLO_INTERNO
