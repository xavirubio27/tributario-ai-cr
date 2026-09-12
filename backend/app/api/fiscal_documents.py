"""Subida manual de un comprobante fiscal — primera API de producto.

    POST /companies/{company_id}/fiscal-documents

QUÉ HACE Y QUÉ NO

    Recibe bytes, autentica, los entrega a C2 y traduce el desenlace a HTTP.
    **No parsea XML, no valida contra XSD, no calcula nada fiscal, no consulta
    pertenencias y no escribe filas normalizadas.** Todo eso ya existe y tiene
    un solo dueño: `ingest_fiscal_xml`, la coreografía canónica de ADR-044.

    C3 es transporte sobre C2, no una segunda tubería de ingesta.

POR QUÉ CUERPO CRUDO Y NO MULTIPART

    El navegador no habla con FastAPI. La capa BFF de Next.js recibe el
    `FormData`, extrae los bytes exactos del fichero y los reenvía como cuerpo.
    Así el backend no necesita `python-multipart` y los bytes llegan intactos:
    sin decodificar, sin re-serializar, sin normalizar.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Request, Response, status
from fastapi.responses import JSONResponse

from app.api.dependencies import require_user
from app.api.error_mapping import FALLO_INTERNO, PETICION_INVALIDA, respuesta_de
from app.api.schemas import UploadAccepted, UploadError, UploadOutcome
from app.auth import AuthenticatedUser
from app.fiscal.errors import (
    FiscalIngestionError,
    FiscalParseError,
    FiscalPersistenceError,
    SourceDocumentTooLarge,
)
from app.fiscal.ingestion import (
    MAX_SOURCE_XML_BYTES,
    IngestionSource,
    ingest_fiscal_xml,
)

router = APIRouter(tags=["fiscal"])


def _demasiado_grande() -> JSONResponse:
    """El mismo 413 que daría C2, pero sin haber leído el cuerpo entero.

    Se construye el error del dominio y se traduce con la tabla común, para
    que transporte y dominio no puedan discrepar sobre cómo se ve un rechazo
    por tamaño.
    """
    estado, cuerpo = respuesta_de(
        SourceDocumentTooLarge(
            "El artefacto supera el tamaño máximo admitido",
            max_bytes=MAX_SOURCE_XML_BYTES,
        )
    )
    return JSONResponse(status_code=estado, content=cuerpo.model_dump())


async def _leer_cuerpo_acotado(request: Request) -> bytes | None:
    """Bytes del cuerpo, o `None` si excede el máximo del dominio.

    NO se usa `request.body()`: acumula el flujo entero sin tope, así que un
    cliente que omita `Content-Length` o use `Transfer-Encoding: chunked`
    haría crecer la memoria sin límite. Verificado en el código de Starlette.

    `Content-Length` es solo una OPTIMIZACIÓN de rechazo temprano; jamás la
    cota. Puede faltar, puede mentir y puede venir mal formada. La cota real
    es el acumulado que se cuenta trozo a trozo.

    En ningún momento se retiene más que el máximo más el trozo en curso.
    """
    declarado = request.headers.get("content-length")
    if declarado is not None:
        try:
            if int(declarado) > MAX_SOURCE_XML_BYTES:
                return None
        except ValueError:
            pass        # cabecera mal formada: se ignora y decide el acumulado

    total = 0
    trozos: list[bytes] = []
    async for trozo in request.stream():
        total += len(trozo)
        if total > MAX_SOURCE_XML_BYTES:
            return None          # se deja de acumular de inmediato
        trozos.append(trozo)
    return b"".join(trozos)


#: Descripción del cuerpo para OpenAPI. Va como METADATO —`openapi_extra`— y no
#: como parámetro del endpoint: declarar un `body` haría que FastAPI lo leyera
#: entero antes de ejecutar nada, y la cota acumulada de 8 MiB dejaría de servir
#: de nada. Documenta sin consumir.
_CUERPO_CRUDO = {
    "requestBody": {
        "required": True,
        "description": (
            "Comprobante electrónico, tal cual. Los bytes se conservan exactos: "
            "no se decodifican ni se re-serializan."
        ),
        "content": {
            "application/xml": {"schema": {"type": "string", "format": "binary"}}
        },
    }
}


@router.post(
    "/companies/{company_id}/fiscal-documents",
    response_model=UploadAccepted,
    openapi_extra=_CUERPO_CRUDO,
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "Identidad no verificada"},
        status.HTTP_403_FORBIDDEN: {"model": UploadError},
        status.HTTP_409_CONFLICT: {"model": UploadError},
        status.HTTP_413_CONTENT_TOO_LARGE: {"model": UploadError},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": UploadError},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": UploadError},
        status.HTTP_503_SERVICE_UNAVAILABLE: {"model": UploadError},
    },
    summary="Registra un comprobante fiscal electrónico",
)
async def upload_fiscal_document(
    company_id: Annotated[
        str,
        Path(
            description="Identificador de la empresa (UUID).",
            # Se recibe como cadena y se valida abajo. Con `company_id: UUID`,
            # FastAPI rechazaba antes de entrar y devolvía su `{"detail": [...]}`,
            # que contradice el contrato estable que este endpoint anuncia.
            # `json_schema_extra` conserva el formato en OpenAPI sin devolver la
            # validación al framework.
            json_schema_extra={"format": "uuid"},
        ),
    ],
    request: Request,
    response: Response,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> object:
    """Recibe UN documento y devuelve el desenlace de su procesamiento.

    Los tres desenlaces de éxito comparten **200**: los tres significan que el
    documento quedó procesado. Que ya estuviera registrado no es un error del
    usuario, es información. El 409 se reserva al conflicto de clave, que sí
    necesita intervención.

    `Content-Type` NO se usa como prueba de nada: solo el parser sabe si unos
    bytes son un comprobante, y rechazar por cabecera negaría documentos
    legítimos que un cliente etiquetó mal.

    `ingestion_source` lo fija el SERVIDOR. No hay parámetro para ello, así
    que ningún cliente puede declarar que sus bytes llegaron por otro canal.
    """
    try:
        empresa = UUID(company_id)
    except ValueError:
        # La PETICIÓN está mal formada, no el documento: no se ha leído ni un
        # byte fiscal, no se llama a C2 y no nace ningún artefacto.
        return JSONResponse(status_code=422, content=PETICION_INVALIDA.model_dump())

    raw_xml = await _leer_cuerpo_acotado(request)
    if raw_xml is None:
        return _demasiado_grande()

    try:
        resultado = ingest_fiscal_xml(
            request.app.state.pool,
            request.app.state.settings,
            user,
            company_id=str(empresa),
            raw_xml=raw_xml,
            ingestion_source=IngestionSource.MANUAL_UPLOAD,
        )
    except (FiscalParseError, FiscalPersistenceError, FiscalIngestionError) as exc:
        estado, cuerpo = respuesta_de(exc)
        # Un fallo NUESTRO no transitorio no dice más que su categoría, ni
        # siquiera el artefacto: no hay acción que ofrecer con esa información.
        if estado >= 500 and cuerpo.code != "persistence_unavailable":
            cuerpo = FALLO_INTERNO
        return JSONResponse(status_code=estado, content=cuerpo.model_dump())

    response.status_code = status.HTTP_200_OK
    return UploadAccepted(
        status=UploadOutcome(resultado.status.value),
        source_document_id=resultado.source_document_id,
        electronic_document_id=resultado.electronic_document_id,
    )
