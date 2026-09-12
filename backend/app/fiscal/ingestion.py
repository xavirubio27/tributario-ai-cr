"""Ingesta fiscal: captura de evidencia y orquestación (C2).

Tres superficies, y el orden entre ellas es la decisión de arquitectura:

    capture_source_document(conn, ...)    guarda la evidencia recibida
    process_source_document(conn, ...)    la interpreta y la normaliza
    ingest_fiscal_xml(pool, ...)          coreografía síncrona canónica

**La evidencia primero.** `ingest_fiscal_xml` comitea la captura ANTES de
interpretar nada, en una transacción propia. Un fallo del parser, un conflicto
de clave, una caída del proceso o un corte de la base **no pueden** borrar unos
bytes ya recibidos: lo que no se pudo interpretar es justo lo que hay que
conservar para investigarlo.

    T1  captura ──► COMMIT      la evidencia ya está a salvo
    T2  procesa ──► COMMIT      el resultado del intento también

**Independiente del canal.** C2 no sabe si los bytes vienen de un navegador,
de un correo o de un conector: solo registra cuál fue. C3 y C4 aportarán
transporte y llamarán aquí; no habrá una segunda tubería fiscal.

**No reimplementa nada.** El parseo seguro, el rechazo de DOCTYPE, la
detección de esquema, la validación XSD y la extracción semántica son de
`parse_fiscal_document`, que se llama **exactamente una vez** por intento. La
persistencia normalizada, la deduplicación y el enlace son de
`persist_parsed_fiscal_document`.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache

import psycopg
from psycopg import Connection, errors as pgerr
from psycopg_pool import ConnectionPool

from app.auth import AuthenticatedUser
from app.config import Settings
from app.db import fiscal_transaction
from app.fiscal.errors import (
    ClaveConflict,
    DocumentDetection,
    EmptySourceDocument,
    FiscalParseError,
    FiscalPersistenceError,
    FiscalWriteForbidden,
    MalformedXML,
    PersistenceDatabaseError,
    SemanticParseError,
    SourceDocumentNotFound,
    SourceDocumentTooLarge,
    UnsupportedDocument,
    UnsupportedDocumentReason,
    XSDValidationError,
)
from app.fiscal.models import TIPO_DETECTADO_POR_RAIZ
from app.fiscal.parser import parse_fiscal_document
from app.fiscal.persistence import persist_parsed_fiscal_document
from app.fiscal.xsd.registry import get_verified_schema_registry

#: Tope de bytes de la frontera de dominio. **Constante, no configuración.**
#: Es la convención del proyecto para invariantes de código —igual que
#: `BACKEND_DB_ROLE`— y por el mismo motivo de ADR-012: un valor puede venir
#: del entorno; un invariante, no. Un límite configurable es un límite que
#: alguien puede desactivar sin querer.
#:
#: 8 MiB ≈ 5× la cota extrapolada del XSD (1000 líneas ≈ 1.4 MiB) y ~500× el
#: mayor comprobante real del corpus (15.7 KiB).
MAX_SOURCE_XML_BYTES = 8 * 1024 * 1024


class IngestionSource(StrEnum):
    """Canal por el que llegó la evidencia. Refleja el CHECK de la base, que
    sigue siendo la defensa autoritativa."""

    MANUAL_UPLOAD = "manual_upload"
    EMAIL = "email"
    API = "api"


class ProcessingStatus(StrEnum):
    """Desenlaces con éxito. Los fracasos son excepciones tipadas, no estados:
    duplicar la taxonomía de errores en un vocabulario paralelo obligaría a
    mantener dos verdades sobre lo mismo."""

    CREATED = "created"
    ALREADY_PERSISTED = "already_persisted"
    LINKED_EXISTING = "linked_existing"


@dataclass(frozen=True, slots=True)
class SourceCaptureResult:
    source_document_id: str
    #: Huella en hexadecimal para el llamante; la base guarda `bytea`.
    content_sha256: str


@dataclass(frozen=True, slots=True)
class IngestionResult:
    source_document_id: str
    electronic_document_id: str
    status: ProcessingStatus


# ─────────────────────────────────────────────────────────────────────────────
# Descriptor de fallo esperado
#
# `process_source_document` NO lanza los desenlaces esperados: los devuelve.
# Si lanzara, el gestor de transacción del llamante revertiría T2 y el estado
# que acabamos de escribir —la verdad sobre este intento— se perdería.
#
# Y no se devuelve la excepción capturada, sino un descriptor con datos
# seguros: un objeto de excepción arrastra `__traceback__` y, según dónde se
# construyera, `__context__`. El orquestador levanta una excepción NUEVA
# después del commit, con la cadena limpia — la lección de C1-B-R2.
# ─────────────────────────────────────────────────────────────────────────────


class ProcessingFailureKind(StrEnum):
    MALFORMED_XML = "malformed_xml"
    UNSUPPORTED_DOCUMENT = "unsupported_document"
    XSD_VALIDATION = "xsd_validation_error"
    SEMANTIC_PARSE = "semantic_parse_error"
    CLAVE_CONFLICT = "clave_conflict"


@dataclass(frozen=True, slots=True)
class ProcessingFailure:
    """Solo datos. Ni excepción, ni traza, ni diagnóstico del motor."""

    kind: ProcessingFailureKind
    reason: UnsupportedDocumentReason | None = None


@dataclass(frozen=True, slots=True)
class ProcessingVerdict:
    """Resultado de un intento. Éxito o fallo esperado, nunca ambos."""

    source_document_id: str
    status: ProcessingStatus | None = None
    electronic_document_id: str | None = None
    failure: ProcessingFailure | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Captura de evidencia
# ─────────────────────────────────────────────────────────────────────────────


def _validar_entrada(raw_xml: bytes) -> None:
    """Frontera de dominio. Se comprueba ANTES de tocar la base y antes del
    parser: nada que no vaya a poder procesarse debería llegar a `bytea`."""
    if not raw_xml:
        raise EmptySourceDocument("El artefacto recibido no tiene contenido")
    if len(raw_xml) > MAX_SOURCE_XML_BYTES:
        raise SourceDocumentTooLarge(
            "El artefacto supera el tamaño máximo admitido",
            max_bytes=MAX_SOURCE_XML_BYTES,
        )


def capture_source_document(
    conn: Connection,
    *,
    company_id: str,
    raw_xml: bytes,
    ingestion_source: IngestionSource,
) -> SourceCaptureResult:
    """Guarda la evidencia tal y como llegó.

    `conn` viene ya dentro de una transacción fiscal autenticada: esta función
    no abre conexión, no comitea, no revierte, no fija rol ni identidad.

    **Los bytes no se tocan.** No se decodifica, no se re-serializa, no se
    normalizan espacios, no se canonicaliza. La huella se calcula sobre los
    bytes exactos recibidos, y PostgreSQL la vuelve a verificar con su propio
    CHECK `content_sha256 = sha256(raw_xml)`.

    **No se busca un duplicado antes de insertar.** Dos recepciones de los
    mismos bytes son dos hechos distintos, y conservar ambos artefactos es
    justo lo que exige ADR-031. Deduplicar es de C1, que tiene la restricción
    única y la evidencia de huella.
    """
    _validar_entrada(raw_xml)
    huella = hashlib.sha256(raw_xml).digest()

    fallo: tuple[str, str | None] | None = None
    try:
        fila = conn.execute(
            "insert into fiscal.source_documents "
            "(company_id, raw_xml, content_sha256, ingestion_source) "
            "values (%s, %s, %s, %s) "
            "returning id, content_sha256",
            (company_id, raw_xml, huella, ingestion_source.value),
        ).fetchone()
        return SourceCaptureResult(
            source_document_id=str(fila["id"]),
            content_sha256=bytes(fila["content_sha256"]).hex(),
        )
    except pgerr.Error as exc:
        fallo = _clasificar_captura(exc)
        # `exc` muere aquí: no se devuelve, no se guarda, no se registra.
    raise _error_de_captura(*fallo)


def _clasificar_captura(exc: pgerr.Error) -> tuple[str, str | None]:
    """Metadatos seguros, DENTRO del `except`. Nunca la excepción."""
    if isinstance(exc, pgerr.InsufficientPrivilege):
        return "forbidden", None
    constraint = getattr(getattr(exc, "diag", None), "constraint_name", None)
    return "database", constraint


def _error_de_captura(categoria: str, constraint: str | None) -> Exception:
    """Se llama FUERA del `except`, para que la cadena quede limpia."""
    if categoria == "forbidden":
        # `viewer`, no miembro y cruce entre empresas dan la MISMA señal, y es
        # deseable: un no miembro no debe aprender nada del tenant ajeno.
        return FiscalWriteForbidden(
            "No se permite registrar evidencia fiscal en esta empresa",
            stage="source_capture",
        )
    return PersistenceDatabaseError(
        "Fallo inesperado de la base de datos al registrar la evidencia",
        stage="source_capture", constraint=constraint,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Procesamiento
# ─────────────────────────────────────────────────────────────────────────────

_COLUMNAS = (
    "id, company_id, raw_xml, parse_status, parse_attempt_count, "
    "schema_detection_status, electronic_document_id"
)

_ACTUALIZAR_CICLO = """
update fiscal.source_documents
   set parse_status            = %s,
       parse_error             = %s,
       schema_detection_status = %s,
       detected_document_type  = %s,
       detected_schema_version = %s,
       parse_attempt_count     = parse_attempt_count + 1,
       parse_attempted_at      = now(),
       updated_at              = now()
 where id = %s and company_id = %s
"""


def _actualizar_ciclo_de_vida(
    conn: Connection, company_id: str, source_document_id: str, *,
    parse_status: str, parse_error: str | None,
    schema_detection_status: str, deteccion: DocumentDetection | None,
) -> None:
    """Escribe el estado COMPLETO del intento, siempre los mismos campos.

    Se escriben todos juntos —incluidos los que quedan en `NULL`— para que un
    reintento no herede metadatos rancios del intento anterior: un documento
    que antes falló y ahora parsea debe quedar con `parse_error` en `NULL` y
    la detección correcta, no con restos.

    **Nunca toca** `raw_xml`, `content_sha256`, `company_id`, `ingested_at`,
    `ingestion_source` ni `electronic_document_id`: los cinco primeros son
    evidencia inmutable y el último es de C1.
    """
    fallo: tuple[str, str | None] | None = None
    try:
        cur = conn.execute(
            _ACTUALIZAR_CICLO,
            (
                parse_status, parse_error, schema_detection_status,
                deteccion.document_type if deteccion else None,
                deteccion.schema_version if deteccion else None,
                source_document_id, company_id,
            ),
        )
    except pgerr.Error as exc:
        fallo = _clasificar_captura(exc)
    if fallo is not None:
        raise _error_de_captura(*fallo)

    # Una política `UPDATE` de RLS no falla: FILTRA. Sin comprobarlo,
    # comitearíamos un estado que nunca llegó a escribirse.
    if cur.rowcount == 1:
        return
    if cur.rowcount == 0:
        raise FiscalWriteForbidden(
            "No se permite actualizar el estado del artefacto",
            stage="source_lifecycle",
            source_document_id=str(source_document_id),
        )
    raise PersistenceDatabaseError(
        "La actualización del artefacto afectó a un número inesperado de filas",
        stage="source_lifecycle", rowcount=cur.rowcount,
    )


def process_source_document(
    conn: Connection, *, company_id: str, source_document_id: str,
) -> ProcessingVerdict:
    """Interpreta un artefacto ya existente y lo normaliza.

    **No comitea ni revierte**: devuelve un veredicto y el llamante cierra la
    transacción. Los desenlaces ESPERADOS —fallo del parser, conflicto de
    clave— viajan en el veredicto precisamente para que el commit ocurra antes
    de que nadie levante una excepción. Los fallos de infraestructura y los
    defectos de programación **sí** se propagan, y revierten T2: no hay ninguna
    verdad sobre el documento que valga la pena conservar cuando el problema
    es nuestro.
    """
    # 1 · ¿lo ve? Agrupa inexistente, de otra empresa y no miembro.
    visible = conn.execute(
        f"select {_COLUMNAS} from fiscal.source_documents "
        "where id = %s and company_id = %s",
        (source_document_id, company_id),
    ).fetchone()
    if visible is None:
        raise SourceDocumentNotFound(
            "El artefacto de origen no existe o no es accesible",
            source_document_id=str(source_document_id),
        )

    # 2 · ¿puede escribir? Cero filas tras haberlo visto es denegación.
    #     La puerta va ANTES de leer el XML y ANTES del parser: un `viewer` no
    #     debe poder provocar trabajo de parseo.
    artefacto = conn.execute(
        f"select {_COLUMNAS} from fiscal.source_documents "
        "where id = %s and company_id = %s for update",
        (source_document_id, company_id),
    ).fetchone()
    if artefacto is None:
        raise FiscalWriteForbidden(
            "No se permite procesar evidencia fiscal en esta empresa",
            stage="source_write_lock",
            source_document_id=str(source_document_id),
        )

    # 3 · ¿ya normalizado? Los bytes son inmutables, así que reprocesarlos
    #     solo podría dar la misma clave: no se reparsea ni se reescribe la
    #     historia del parseo, aunque el estado antiguo parezca inconsistente.
    if artefacto["electronic_document_id"] is not None:
        return ProcessingVerdict(
            source_document_id=str(source_document_id),
            status=ProcessingStatus.ALREADY_PERSISTED,
            electronic_document_id=str(artefacto["electronic_document_id"]),
        )

    # 4 · Un solo parseo por intento. Toda la seguridad XML, la detección, el
    #     XSD y la extracción son suyos.
    parsed = None
    fallo_parseo: ProcessingFailure | None = None
    estado: tuple[str, str | None, str, DocumentDetection | None]
    try:
        parsed = parse_fiscal_document(bytes(artefacto["raw_xml"]))
    except MalformedXML:
        estado = ("failed", MalformedXML.code, "failed", None)
        fallo_parseo = ProcessingFailure(ProcessingFailureKind.MALFORMED_XML)
    except UnsupportedDocument as exc:
        deteccion = exc.detection
        detec_estado = (
            "unknown"
            if exc.reason is UnsupportedDocumentReason.UNKNOWN_DOCUMENT
            else "unsupported"
        )
        estado = ("failed", UnsupportedDocument.code, detec_estado, deteccion)
        fallo_parseo = ProcessingFailure(
            ProcessingFailureKind.UNSUPPORTED_DOCUMENT, reason=exc.reason
        )
    except XSDValidationError as exc:
        estado = ("failed", XSDValidationError.code, "detected", exc.detection)
        fallo_parseo = ProcessingFailure(ProcessingFailureKind.XSD_VALIDATION)
    except SemanticParseError as exc:
        estado = ("failed", SemanticParseError.code, "detected", exc.detection)
        fallo_parseo = ProcessingFailure(ProcessingFailureKind.SEMANTIC_PARSE)
    # `ValidatorConfigurationError` NO se captura: el paquete de esquemas del
    # servidor es problema NUESTRO, no del documento del contribuyente.
    # Se propaga, T2 revierte y el artefacto no queda marcado como fallido.

    if fallo_parseo is not None:
        _actualizar_ciclo_de_vida(
            conn, company_id, source_document_id,
            parse_status=estado[0], parse_error=estado[1],
            schema_detection_status=estado[2], deteccion=estado[3],
        )
        return ProcessingVerdict(
            source_document_id=str(source_document_id), failure=fallo_parseo
        )

    # 5 · El parseo funcionó. Se registra ANTES de intentar persistir, para que
    #     esa verdad sobreviva aunque la persistencia no pueda completarse.
    assert parsed is not None
    deteccion = DocumentDetection(
        document_type=parsed.document.document_type,
        schema_version=_version_por_tipo()[parsed.document.document_type],
    )
    _actualizar_ciclo_de_vida(
        conn, company_id, source_document_id,
        parse_status="parsed", parse_error=None,
        schema_detection_status="detected", deteccion=deteccion,
    )

    # 6 · Persistencia. El `SAVEPOINT` permite que un conflicto de clave
    #     revierta SOLO lo de C1 y deje en pie el estado del parseo.
    try:
        with conn.transaction():
            resultado = persist_parsed_fiscal_document(
                conn, company_id=company_id,
                source_document_id=source_document_id, parsed=parsed,
            )
    except ClaveConflict:
        # Parseó bien; lo que no se pudo fue establecer equivalencia.
        return ProcessingVerdict(
            source_document_id=str(source_document_id),
            failure=ProcessingFailure(ProcessingFailureKind.CLAVE_CONFLICT),
        )
    # Los demás fallos de C1 —autorización, infraestructura, defectos
    # nuestros— se propagan y revierten T2 entera.

    return ProcessingVerdict(
        source_document_id=str(source_document_id),
        status=ProcessingStatus(resultado.status.value),
        electronic_document_id=resultado.electronic_document_id,
    )


@lru_cache(maxsize=1)
def _version_por_tipo() -> dict[str, str]:
    """Tipo canónico → versión estructural, leída del paquete VERIFICADO.

    No se deduce del XML, ni del identificador del esquema, ni del namespace:
    sale del manifiesto que la puerta *fail-closed* ya aprobó.
    """
    registro = get_verified_schema_registry()
    return {
        TIPO_DETECTADO_POR_RAIZ[entrada.root]: entrada.version
        for entrada in registro.entradas()
    }


# ─────────────────────────────────────────────────────────────────────────────
# Orquestador canónico
# ─────────────────────────────────────────────────────────────────────────────

_ERROR_POR_FALLO = {
    ProcessingFailureKind.MALFORMED_XML: (
        MalformedXML, "El documento no es XML bien formado"),
    ProcessingFailureKind.XSD_VALIDATION: (
        XSDValidationError, "El documento no es conforme a su esquema oficial"),
    ProcessingFailureKind.SEMANTIC_PARSE: (
        SemanticParseError, "El documento no se pudo interpretar"),
    ProcessingFailureKind.CLAVE_CONFLICT: (
        ClaveConflict,
        "Ya existe un documento con esa clave y no se pudo establecer "
        "equivalencia con el artefacto recibido"),
}


def _excepcion_de(failure: ProcessingFailure, source_document_id: str) -> Exception:
    """Construye una excepción NUEVA, después del commit.

    Nueva y no la capturada: un objeto de excepción arrastra traza y, según
    dónde naciera, contexto. Al levantarla aquí —sin ningún `except` activo—
    `__cause__` y `__context__` quedan en `None`.

    Lleva `source_document_id` porque, una vez comiteada la captura, el
    artefacto existe y el llamante necesita poder referirse a él. Es un UUID
    interno: contexto estructural, no dato del contribuyente.
    """
    if failure.kind is ProcessingFailureKind.UNSUPPORTED_DOCUMENT:
        return UnsupportedDocument(
            "El documento no entra en el procesamiento de comprobantes",
            reason=failure.reason,
            source_document_id=source_document_id,
        )
    clase, mensaje = _ERROR_POR_FALLO[failure.kind]
    return clase(mensaje, source_document_id=source_document_id)


def ingest_fiscal_xml(
    pool: ConnectionPool,
    settings: Settings,
    user: AuthenticatedUser,
    *,
    company_id: str,
    raw_xml: bytes,
    ingestion_source: IngestionSource,
) -> IngestionResult:
    """Coreografía síncrona canónica: recibir, conservar, interpretar.

    **Dos transacciones, nunca una.** La primera conserva la evidencia y
    comitea; solo entonces se intenta interpretarla. Unirlas haría que un
    documento ilegible se perdiera justo por ser ilegible — que es el caso que
    más falta hace conservar.

    C3 debe llamar aquí en lugar de reproducir este orden. C4 podrá usar los
    dos primitivos por separado alrededor de una cola, sin reescribir nada.
    """
    _validar_entrada(raw_xml)          # antes de abrir ninguna transacción

    with fiscal_transaction(pool, settings, user) as conn:
        captura = capture_source_document(
            conn, company_id=company_id, raw_xml=raw_xml,
            ingestion_source=ingestion_source,
        )
    # ─── la evidencia ya es durable ───

    with fiscal_transaction(pool, settings, user) as conn:
        veredicto = process_source_document(
            conn, company_id=company_id,
            source_document_id=captura.source_document_id,
        )
    # ─── el resultado del intento también ───

    if veredicto.failure is not None:
        raise _excepcion_de(veredicto.failure, veredicto.source_document_id)

    return IngestionResult(
        source_document_id=veredicto.source_document_id,
        electronic_document_id=veredicto.electronic_document_id,
        status=veredicto.status,
    )
