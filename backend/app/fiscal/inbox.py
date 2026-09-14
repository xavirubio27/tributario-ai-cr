"""Bandeja de documentos fiscales — lectura operativa (C3-B3).

RESPONDE A UNA PREGUNTA, Y NO ES TRIBUTARIA
    «¿Qué ha recibido Tribuu, y tengo que hacer algo?» No calcula impuestos, no
    dice si algo es deducible y no clasifica ventas ni compras.

LA CLASIFICACIÓN ES DETERMINISTA Y SALE DE COLUMNAS
    Nada de IA, nada de reparsear XML y —esto es lo que la hace posible— nada
    de interpretar texto de error: `parse_error` guarda el CÓDIGO ESTABLE de la
    clase de error, no un mensaje. Fue una decisión de C2 y es la que sostiene
    toda esta capa.

MODELO HÍBRIDO
    Una fila por documento normalizado, colapsando sus recepciones; y una fila
    por recepción que no llegó a normalizarse. Un modelo centrado solo en el
    documento normalizado escondería justo lo que hay que ver: el XML inválido,
    la Nota de Débito, el MensajeHacienda, el conflicto de clave y lo pendiente.

    La evidencia NO se borra ni se colapsa en la base: colapsar es de la vista.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from psycopg import Connection, errors as pgerr

from app.fiscal.errors import PersistenceDatabaseError, PersistenceUnavailable
from app.fiscal.models import TIPO_POR_RAIZ

#: Tipos que ESTE flujo normaliza. Todo lo demás que el paquete sabe detectar
#: —hoy solo `hacienda_message`— queda fuera del pipeline. Se deriva del
#: vocabulario y no de una lista escrita a mano, para que añadir un documento
#: no normalizable no obligue a tocar esta regla.
TIPOS_DE_COMPROBANTE: frozenset[str] = frozenset(TIPO_POR_RAIZ.values())

PAGINA_POR_DEFECTO = 25
PAGINA_MAXIMA = 100
_VERSION_CURSOR = 1


class OperationalStatus(StrEnum):
    """Estado operativo. Siete valores, y cada uno responde a «¿me toca a mí?»."""

    #: Normalizado y enlazado. Nada que hacer.
    PROCESSED = "processed"
    #: Parseó, pero no se pudo establecer equivalencia con otro de la misma
    #: clave. Hace falta una persona.
    REQUIRES_ATTENTION = "requires_attention"
    #: Recibido y sin terminar de procesar. Es cosa NUESTRA.
    SYSTEM_PENDING = "system_pending"
    #: El archivo no es un comprobante utilizable.
    INVALID_DOCUMENT = "invalid_document"
    #: No reconocemos el XML.
    UNRECOGNIZED = "unrecognized"
    #: Comprobante reconocido cuyo soporte no existe todavía. Cosa nuestra.
    NOT_YET_SUPPORTED = "not_yet_supported"
    #: Reconocido, pero no es un comprobante de este flujo. Cosa nuestra.
    OUTSIDE_PIPELINE = "outside_pipeline"


#: Lo que cuenta como «tengo que hacer algo». `not_yet_supported` y
#: `outside_pipeline` NO entran: son límites de Tribuu, no deudas del usuario.
REQUIEREN_ACCION = frozenset({
    OperationalStatus.REQUIRES_ATTENTION,
    OperationalStatus.INVALID_DOCUMENT,
    OperationalStatus.UNRECOGNIZED,
})

_ERRORES_DE_DOCUMENTO_INVALIDO = frozenset({
    "malformed_xml", "xsd_validation_error", "semantic_parse_error",
})


class InboxQueryError(Exception):
    """Parámetro de consulta inválido. Nunca lleva detalle del decodificador."""

    code = "invalid_query"


def parse_limit(crudo: str | None) -> int:
    """Tamaño de página a partir del valor LÉXICO de la consulta.

    Se recibe sin coerción del framework a propósito: con `limit: int`,
    FastAPI rechazaba `?limit=abc` antes de entrar en la ruta y devolvía su
    `{"detail": [...]}`, que contradice el contrato estable que este endpoint
    anuncia. Es el mismo problema que ya se corrigió con `company_id` en B1.

    Solo se acepta un entero en notación decimal: `1.5`, `1e2`, `٣` y ` 5 ` se
    rechazan.
    """
    if crudo is None:
        return PAGINA_POR_DEFECTO
    if not re.fullmatch(r"-?[0-9]+", crudo):
        raise InboxQueryError("límite no es un entero")
    valor = int(crudo)
    if valor < 1 or valor > PAGINA_MAXIMA:
        raise InboxQueryError("límite fuera de rango")
    return valor


@dataclass(frozen=True, slots=True)
class InboxCursor:
    """Posición en el listado. Opaca para el cliente, validada al abrirla."""

    received_at: datetime
    kind: str
    row_id: UUID

    def encode(self) -> str:
        carga = json.dumps(
            {"v": _VERSION_CURSOR, "receivedAt": self.received_at.isoformat(),
             "kind": self.kind, "rowId": str(self.row_id)},
            separators=(",", ":"),
        ).encode()
        return base64.urlsafe_b64encode(carga).decode().rstrip("=")


#: Alfabeto base64url SIN relleno, que es lo único que emite `encode()`.
_ALFABETO_CURSOR = re.compile(r"^[A-Za-z0-9_-]+$")


def decode_cursor(crudo: str) -> InboxCursor:
    """Cursor validado, o `InboxQueryError`.

    SE ACEPTA SOLO LA FORMA CANÓNICA QUE PRODUCE `encode()`
        `base64.urlsafe_b64decode` es permisivo: tolera relleno de más,
        caracteres del alfabeto estándar y basura al final. Aceptar esas
        variantes significaría que existen muchos cursores distintos para la
        misma posición, y que el cliente puede fabricarlos. Por eso, además de
        validar el contenido, se **vuelve a codificar** el resultado y se exige
        que coincida con lo recibido: si no coincide, no lo emitimos nosotros.

    La marca de tiempo debe llevar huso. Es tiempo DEL SISTEMA —cuándo llegó la
    evidencia—, no la fecha del comprobante, así que aquí no rige la semántica
    de reloj de pared de ADR-039: un instante sin huso es ambiguo y se rechaza.
    """
    if not isinstance(crudo, str) or not _ALFABETO_CURSOR.match(crudo):
        # Cubre espacios, caracteres fuera del alfabeto, relleno `=` y vacío.
        raise InboxQueryError("cursor con formato inesperado")

    try:
        relleno = "=" * (-len(crudo) % 4)
        datos = json.loads(base64.urlsafe_b64decode(crudo + relleno))
    except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
        # El texto del decodificador NO viaja: diría cómo está construido.
        raise InboxQueryError("cursor ilegible") from exc

    if not isinstance(datos, dict) or set(datos) != {"v", "receivedAt", "kind", "rowId"}:
        raise InboxQueryError("cursor con forma inesperada")
    if datos["v"] != _VERSION_CURSOR:
        raise InboxQueryError("versión de cursor no soportada")
    if datos["kind"] not in ("document", "receipt"):
        raise InboxQueryError("tipo de fila desconocido")
    try:
        momento = datetime.fromisoformat(str(datos["receivedAt"]))
        fila = UUID(str(datos["rowId"]))
    except (TypeError, ValueError) as exc:
        raise InboxQueryError("cursor con valores inválidos") from exc
    if momento.tzinfo is None:
        raise InboxQueryError("marca de tiempo sin huso")

    cursor = InboxCursor(received_at=momento, kind=datos["kind"], row_id=fila)
    if cursor.encode() != crudo:
        raise InboxQueryError("cursor no canónico")
    return cursor


@dataclass(frozen=True, slots=True)
class InboxItem:
    """Una fila de la bandeja. Unión discriminada por `kind`.

    `kind='document'` NO lleva `source_document_id`: un documento normalizado
    colapsa VARIAS recepciones y elegir una de ellas sería arbitrario. Quien
    necesite la evidencia individual usará una API de recepciones futura.
    """

    kind: str
    operational_status: OperationalStatus
    received_at: datetime
    receipt_count: int
    row_id: UUID
    source_document_id: UUID | None = None
    electronic_document_id: UUID | None = None
    document_type: str | None = None
    issued_at_local: datetime | None = None
    issued_at_offset_minutes: int | None = None
    consecutive_number: str | None = None
    currency_code: str | None = None
    #: `Decimal`, nunca `float`. Se serializa como cadena.
    reported_total_document: Decimal | None = None


@dataclass(frozen=True, slots=True)
class InboxCounts:
    needs_attention: int
    system_pending: int


@dataclass(frozen=True, slots=True)
class InboxPage:
    items: tuple[InboxItem, ...]
    next_cursor: str | None
    counts: InboxCounts


def clasificar(
    *,
    electronic_document_id: UUID | None,
    parse_status: str,
    parse_error: str | None,
    schema_detection_status: str,
    detected_document_type: str | None,
) -> OperationalStatus:
    """Estado operativo de una recepción. **Única** regla de derivación.

    Existe como función y no repartida por la consulta para que la pregunta
    «¿por qué esto aparece como X?» tenga una sola respuesta.

    Sobre `requires_attention`: hoy es una invariante DEL CÓDIGO, no del
    esquema. `process_source_document` escribe `parsed` antes de llamar a C1, y
    su `except ClaveConflict` es el ÚNICO camino que comitea T2 sin enlazar —
    cualquier otro fallo de C1 propaga y revierte T2 entera, devolviendo la
    fila a `pending`. Si algún día aparece otro desenlace «parseado y sin
    enlazar» —persistencia diferida, cola, revisión manual— colisionará aquí en
    silencio, y entonces hará falta un campo estructurado.
    """
    if electronic_document_id is not None:
        return OperationalStatus.PROCESSED
    if parse_status == "parsed":
        return OperationalStatus.REQUIRES_ATTENTION
    if parse_status == "pending":
        return OperationalStatus.SYSTEM_PENDING
    if parse_status == "failed":
        if parse_error in _ERRORES_DE_DOCUMENTO_INVALIDO:
            return OperationalStatus.INVALID_DOCUMENT
        if parse_error == "unsupported_document":
            if schema_detection_status == "unknown":
                return OperationalStatus.UNRECOGNIZED
            if schema_detection_status == "unsupported":
                return (
                    OperationalStatus.NOT_YET_SUPPORTED
                    if detected_document_type in TIPOS_DE_COMPROBANTE
                    else OperationalStatus.OUTSIDE_PIPELINE
                )
    # Combinación que el ciclo de vida de C2 no produce. Se falla cerrando en
    # vez de inventar un estado: una bandeja que miente es peor que una que
    # admite no saber.
    raise PersistenceDatabaseError(
        "Estado de artefacto no clasificable", stage="inbox_read",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Consulta
#
# UNA sola consulta acotada, sin N+1 y sin seguimiento por fila. Dos ramas
# unidas por `union all`:
#
#   · documentos normalizados, colapsando sus recepciones con `group by`;
#   · recepciones sin enlazar, tal cual.
#
# El orden es TOTAL sobre las dos ramas —`received_at DESC, kind_rank ASC,
# row_id DESC`— porque un keyset sobre filas heterogéneas necesita un
# desempate que valga para ambas. Sin `kind_rank`, dos filas de clases
# distintas con el mismo instante podrían intercalarse de forma no
# determinista y una página repetiría o saltaría.
# ─────────────────────────────────────────────────────────────────────────────

_RANGO = {"document": 0, "receipt": 1}

_COLUMNAS_BANDEJA = """
    select
        'document'::text                     as kind,
        0                                    as kind_rank,
        e.id                                 as row_id,
        null::uuid                           as source_document_id,
        e.id                                 as electronic_document_id,
        max(s.ingested_at)                   as received_at,
        count(s.id)::int                     as receipt_count,
        e.document_type                      as document_type,
        e.issued_at_local                    as issued_at_local,
        e.issued_at_offset_minutes           as issued_at_offset_minutes,
        e.consecutive_number                 as consecutive_number,
        e.currency_code                      as currency_code,
        e.reported_total_document            as reported_total_document,
        'parsed'::text                       as parse_status,
        null::text                           as parse_error,
        'detected'::text                     as schema_detection_status,
        e.document_type                      as detected_document_type
      from fiscal.electronic_documents e
      join fiscal.source_documents s on s.electronic_document_id = e.id
     where e.company_id = %(company)s
     group by e.id

    union all

    select
        'receipt'::text, 1, s.id, s.id, null::uuid,
        s.ingested_at, 1,
        s.detected_document_type,
        null::timestamp, null::smallint, null::text, null::text, null::numeric,
        s.parse_status, s.parse_error,
        s.schema_detection_status, s.detected_document_type
      from fiscal.source_documents s
     where s.company_id = %(company)s
       and s.electronic_document_id is null
"""

#: Predicado SQL por estado. Existe porque filtrar en Python después de traer
#: la página devolvería páginas ralas —25 filas leídas, 2 mostradas—, pero es
#: una SEGUNDA expresión de la misma regla, y dos verdades divergen. Por eso
#: hay un test que enumera TODOS los estados que C2 puede producir y comprueba
#: que el filtro SQL y `clasificar()` coinciden en cada uno.
_PREDICADO: dict[OperationalStatus, str] = {
    OperationalStatus.PROCESSED:
        "electronic_document_id is not null",
    OperationalStatus.REQUIRES_ATTENTION:
        "electronic_document_id is null and parse_status = 'parsed'",
    OperationalStatus.SYSTEM_PENDING:
        "electronic_document_id is null and parse_status = 'pending'",
    OperationalStatus.INVALID_DOCUMENT:
        "electronic_document_id is null and parse_status = 'failed'"
        " and parse_error = any(%(invalidos)s)",
    OperationalStatus.UNRECOGNIZED:
        "electronic_document_id is null and parse_status = 'failed'"
        " and parse_error = 'unsupported_document'"
        " and schema_detection_status = 'unknown'",
    OperationalStatus.NOT_YET_SUPPORTED:
        "electronic_document_id is null and parse_status = 'failed'"
        " and parse_error = 'unsupported_document'"
        " and schema_detection_status = 'unsupported'"
        " and detected_document_type = any(%(comprobantes)s)",
    OperationalStatus.OUTSIDE_PIPELINE:
        "electronic_document_id is null and parse_status = 'failed'"
        " and parse_error = 'unsupported_document'"
        " and schema_detection_status = 'unsupported'"
        " and (detected_document_type is null"
        "      or not (detected_document_type = any(%(comprobantes)s)))",
}


#: Comparador lexicográfico EXPLÍCITO para el keyset.
#:
#: No se usa la comparación de tuplas `(a,b,c) < (x,y,z)`: solo vale cuando
#: todas las componentes ordenan en el MISMO sentido, y aquí `kind_rank` sube
#: mientras las otras dos bajan. Con la tupla, un `receipt` que compartía
#: instante con un `document` se SALTABA, y al paginar desde un `receipt` el
#: `document` del mismo instante se REPETÍA.
#:
#: Va entre paréntesis a propósito: la regla debe poder leerse tal cual, sin
#: depender de la precedencia de `and`/`or`.
_DESPUES_DEL_CURSOR = """(
       received_at < %(cur_at)s
    or (received_at = %(cur_at)s and kind_rank > %(cur_rank)s)
    or (received_at = %(cur_at)s and kind_rank = %(cur_rank)s
        and row_id < %(cur_id)s)
)"""


def _sql_pagina(status: OperationalStatus | None) -> str:
    filtro = f"and ({_PREDICADO[status]})" if status else ""
    return f"""
with bandeja as ({_COLUMNAS_BANDEJA})
select * from bandeja
 where (%(sin_cursor)s or {_DESPUES_DEL_CURSOR})
   {filtro}
 order by received_at desc, kind_rank asc, row_id desc
 limit %(limite)s
"""

#: Los contadores son GLOBALES de la empresa: no dependen del cursor ni del
#: filtro. Es la pregunta «¿tengo algo pendiente?», y filtrarla por la página
#: que se está mirando la haría inútil. Una sola agregación acotada.
_CONTADORES = f"""
with bandeja as ({_COLUMNAS_BANDEJA})
select parse_status, parse_error, schema_detection_status,
       detected_document_type, electronic_document_id, count(*)::int as n
  from bandeja
 group by 1, 2, 3, 4, 5
"""


def _fila_a_item(fila: dict) -> InboxItem:
    estado = clasificar(
        electronic_document_id=fila["electronic_document_id"],
        parse_status=fila["parse_status"],
        parse_error=fila["parse_error"],
        schema_detection_status=fila["schema_detection_status"],
        detected_document_type=fila["detected_document_type"],
    )
    return InboxItem(
        kind=fila["kind"],
        operational_status=estado,
        received_at=fila["received_at"],
        receipt_count=fila["receipt_count"],
        row_id=fila["row_id"],
        source_document_id=fila["source_document_id"],
        electronic_document_id=fila["electronic_document_id"],
        document_type=fila["document_type"],
        issued_at_local=fila["issued_at_local"],
        issued_at_offset_minutes=fila["issued_at_offset_minutes"],
        consecutive_number=fila["consecutive_number"],
        currency_code=fila["currency_code"],
        reported_total_document=fila["reported_total_document"],
    )


def _ejecutar(conn: Connection, sql: str, params: dict):
    """Traduce fallos de base sin dejar salir el diagnóstico del motor."""
    fallo: str | None = None
    try:
        return conn.execute(sql, params).fetchall()
    except pgerr.Error as exc:
        fallo = ("unavailable"
                 if isinstance(exc, (pgerr.OperationalError, pgerr.InsufficientResources))
                 else "database")
    if fallo == "unavailable":
        raise PersistenceUnavailable(
            "La lectura fiscal no está disponible", stage="inbox_read")
    raise PersistenceDatabaseError(
        "Fallo inesperado de la base de datos al leer la bandeja",
        stage="inbox_read")


def read_inbox(
    conn: Connection,
    *,
    company_id: str,
    limit: int = PAGINA_POR_DEFECTO,
    cursor: InboxCursor | None = None,
    status: OperationalStatus | None = None,
) -> InboxPage:
    """Una página de la bandeja más los contadores globales de la empresa.

    `conn` viene ya dentro de una transacción fiscal autenticada: esta función
    no abre conexión, no comitea y no fija identidad. **RLS decide qué filas
    existen**; aquí no se consulta ninguna pertenencia.
    """
    if limit < 1 or limit > PAGINA_MAXIMA:
        raise InboxQueryError("límite fuera de rango")

    # Se pide una fila de más para saber si hay página siguiente sin contar.
    params = {
        "company": company_id,
        "limite": limit + 1,
        "sin_cursor": cursor is None,
        "cur_at": cursor.received_at if cursor else None,
        "cur_rank": _RANGO[cursor.kind] if cursor else None,
        "cur_id": cursor.row_id if cursor else None,
    }
    params["invalidos"] = list(_ERRORES_DE_DOCUMENTO_INVALIDO)
    params["comprobantes"] = sorted(TIPOS_DE_COMPROBANTE)
    filas = _ejecutar(conn, _sql_pagina(status), params)

    hay_mas = len(filas) > limit
    filas = filas[:limit]
    items = [_fila_a_item(f) for f in filas]

    siguiente = None
    if hay_mas and filas:
        ultima = filas[-1]
        siguiente = InboxCursor(
            received_at=ultima["received_at"], kind=ultima["kind"],
            row_id=ultima["row_id"],
        ).encode()

    agregados = _ejecutar(conn, _CONTADORES, {"company": company_id})
    atencion = pendientes = 0
    for g in agregados:
        estado = clasificar(
            electronic_document_id=g["electronic_document_id"],
            parse_status=g["parse_status"], parse_error=g["parse_error"],
            schema_detection_status=g["schema_detection_status"],
            detected_document_type=g["detected_document_type"],
        )
        if estado in REQUIEREN_ACCION:
            atencion += g["n"]
        elif estado is OperationalStatus.SYSTEM_PENDING:
            pendientes += g["n"]

    return InboxPage(
        items=tuple(items),
        next_cursor=siguiente,
        counts=InboxCounts(needs_attention=atencion, system_pending=pendientes),
    )
