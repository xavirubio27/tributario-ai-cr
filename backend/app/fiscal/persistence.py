"""Persistencia fiscal transaccional (C1).

    persist_parsed_fiscal_document(conn, *, company_id, source_document_id, parsed)
        -> PersistenceResult

Guarda un `ParsedFiscalDocument` —ya parseado y validado— en el esquema
`fiscal`, y enlaza el artefacto de origen que le dio lugar.

**Todo o nada.** La operación completa pertenece a UNA transacción fiscal
autenticada, que abre y cierra el llamante. O queda el agregado entero con su
artefacto enlazado, o no queda ninguna fila nueva de ese intento.

**No calcula nada.** Ni totales, ni impuestos, ni deducibilidad, ni dirección a
partir del emisor, ni revisión de *ruleset*. Persistencia ≠ Tax Engine, igual
que LLM ≠ Tax Engine.

**No vuelve a parsear.** Recibe el agregado ya construido; no lee `raw_xml`, no
revalida contra el XSD y no llama al parser. Los invariantes de los modelos
congelados de B1/B2 se dan por buenos: si un estado que pasó el parser no cupo
en la base, el defecto es del mapeo, no del contribuyente.

**No autoriza en Python.** PostgreSQL RLS es la única autoridad. Este módulo no
consulta `company_memberships` ni reproduce la lógica de roles: se limita a
observar dos capacidades distintas que RLS ya decide —ver y poder escribir—.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import psycopg
from psycopg import Connection, errors as pgerr

from app.fiscal.errors import (
    ClaveConflict,
    FiscalPersistenceError,
    FiscalWriteForbidden,
    PersistenceDatabaseError,
    PersistenceMappingError,
    PersistenceUnavailable,
    SourceDocumentNotFound,
    SourceDocumentStateConflict,
)
from app.fiscal.models import ParsedFiscalDocument

#: Único `UNIQUE` que puede abrir el camino de deduplicación. Cualquier otra
#: violación de unicidad es un defecto de mapeo, no un duplicado (ADR-042).
UNIQUE_CLAVE = "electronic_documents_company_clave_key"

#: C1 no determina la dirección: `public.companies` no almacena identificación
#: tributaria, así que no hay con qué compararla. `unknown` significa «la
#: dirección no está establecida», no «se comparó y no coincidió».
DIRECTION_SIN_ESTABLECER = "unknown"

#: C1 no ejecuta el resolutor de revisión semántica (ADR-026).
RULESET_SIN_RESOLVER = "ambiguous"


class PersistenceStatus(StrEnum):
    """Resultado de la operación. `StrEnum` como `CompanyRole`: refleja un
    vocabulario cerrado y no admite cadenas arbitrarias."""

    CREATED = "created"
    ALREADY_PERSISTED = "already_persisted"
    LINKED_EXISTING = "linked_existing"


@dataclass(frozen=True, slots=True)
class PersistenceResult:
    """Lo mínimo que el llamante necesita. No devuelve el agregado: ya lo tiene."""

    electronic_document_id: str
    source_document_id: str
    status: PersistenceStatus


# ─────────────────────────────────────────────────────────────────────────────
# Traducción de errores de PostgreSQL
#
# Dos propiedades, y ninguna es opcional.
#
# 1 · NADA DE PSYCOPG SIGUE ALCANZABLE. No basta `raise Safe(...) from None`:
#     medido, deja el original en `__context__` aunque limpie `__cause__`. La
#     única forma de que ambos queden en `None` es **lanzar fuera del bloque
#     `except`**, cuando Python ya ha descartado la excepción en curso. Por eso
#     el patrón de abajo clasifica dentro y lanza después.
#
# 2 · LA CLASIFICACIÓN ES ESTRECHA. `PersistenceMappingError` significa algo
#     concreto —«lo que el dominio aprobó no cupo en el modelo físico»— y no
#     puede ser el cajón de sastre. Un `UndefinedColumn` es un bug nuestro, y
#     llamarlo defecto de mapeo mandaría a revisar los datos del contribuyente
#     en lugar del código. Lo desconocido va a `PersistenceDatabaseError`.
#
# Tampoco se registra la excepción cruda en ningún log: este módulo no tiene
# logging, y es deliberado.
# ─────────────────────────────────────────────────────────────────────────────

#: Fallos ESPERADOS del modelo físico. Lista explícita, no una clase base
#: amplia: `DataError` e `IntegrityError` cubren también casos que no sabemos
#: interpretar, y esos deben caer en el cajón de «inesperado».
_DEFECTOS_DE_MAPEO = (
    pgerr.UniqueViolation,
    pgerr.CheckViolation,
    pgerr.NotNullViolation,
    pgerr.ForeignKeyViolation,
    pgerr.StringDataRightTruncation,
    pgerr.NumericValueOutOfRange,
)

#: Infraestructura y concurrencia: los únicos reintentables.
_FALLOS_DE_INFRAESTRUCTURA = (
    pgerr.SerializationFailure,
    pgerr.DeadlockDetected,
    psycopg.OperationalError,
)

# Categorías internas. Son cadenas y no excepciones a propósito: lo que sale
# del bloque `except` no puede ser un objeto que arrastre la excepción real.
_MAPEO = "mapping"
_PROHIBIDO = "forbidden"
_NO_DISPONIBLE = "unavailable"
_INESPERADO = "database"


def _clasificar(exc: pgerr.Error) -> tuple[str, str | None]:
    """Metadatos SEGUROS de la excepción. Se llama DENTRO del `except`.

    Devuelve `(categoría, restricción)` — dos cadenas. **Nunca** devuelve ni
    guarda la excepción: si la devolviera, viajaría hasta el llamante y el
    trabajo de limpiar la cadena no habría servido de nada.
    """
    constraint = getattr(getattr(exc, "diag", None), "constraint_name", None)

    # Primero lo específico: `InsufficientPrivilege` es un `ProgrammingError`,
    # igual que `UndefinedColumn`. Comprobar la base antes taparía la
    # denegación de RLS bajo «defecto de programación».
    if isinstance(exc, pgerr.InsufficientPrivilege):
        return _PROHIBIDO, None
    if isinstance(exc, _DEFECTOS_DE_MAPEO):
        return _MAPEO, constraint
    if isinstance(exc, _FALLOS_DE_INFRAESTRUCTURA):
        return _NO_DISPONIBLE, None
    return _INESPERADO, None


def _error(categoria: str, constraint: str | None, etapa: str) -> FiscalPersistenceError:
    """Construye la excepción pública. Se llama FUERA del `except`."""
    if categoria == _PROHIBIDO:
        return FiscalWriteForbidden(
            "La operación fiscal no está autorizada", stage=etapa
        )
    if categoria == _MAPEO:
        return PersistenceMappingError(
            "El estado del documento no encaja en el modelo físico",
            stage=etapa, constraint=constraint,
        )
    if categoria == _NO_DISPONIBLE:
        return PersistenceUnavailable(
            "La persistencia no está disponible", stage=etapa
        )
    return PersistenceDatabaseError(
        "Fallo inesperado de la base de datos durante la persistencia",
        stage=etapa,
    )


def _ejecutar(conn: Connection, sql: str, params: Any, etapa: str):
    """Ejecuta y traduce. El `raise` va DESPUÉS del `except`, no dentro."""
    fallo: tuple[str, str | None] | None = None
    try:
        return conn.execute(sql, params)
    except pgerr.Error as exc:
        fallo = _clasificar(exc)
        # `exc` no sale de aquí: ni se devuelve, ni se guarda, ni se registra.
    raise _error(*fallo, etapa)


def _ejecutar_muchos(conn: Connection, sql: str, filas: list[tuple], etapa: str) -> None:
    if not filas:                       # nada que insertar: no se llama al motor
        return
    fallo: tuple[str, str | None] | None = None
    try:
        with conn.cursor() as cur:
            cur.executemany(sql, filas)
        return
    except pgerr.Error as exc:
        fallo = _clasificar(exc)
    raise _error(*fallo, etapa)


# ─────────────────────────────────────────────────────────────────────────────
# Puerta del artefacto de origen — dos lecturas, dos capacidades
#
# Medido contra PostgreSQL 17.6 con las políticas vigentes:
#
#     actor        SELECT simple   SELECT ... FOR UPDATE
#     owner        1 fila          1 fila
#     editor       1 fila          1 fila
#     viewer       1 fila          0 filas, SIN excepción
#     no miembro   0 filas         0 filas
#
# `SELECT ... FOR UPDATE` aplica, además de la política `SELECT`, la cláusula
# `USING` de la política `UPDATE`, y **filtra en silencio** lo que no la pasa.
# No lanza error. Por eso hacen falta dos lecturas para distinguir «no lo ves»
# de «lo ves pero no puedes escribir»: la primera observa visibilidad, la
# segunda intención de escritura. Ninguna consulta `company_memberships`.
# ─────────────────────────────────────────────────────────────────────────────

_COLUMNAS_ARTEFACTO = (
    "id, company_id, content_sha256, electronic_document_id"
)


def _leer_visible(conn: Connection, company_id: str, source_document_id: str):
    """PASO A · visibilidad. Sin `FOR UPDATE`, política `SELECT` ordinaria."""
    return _ejecutar(
        conn,
        f"select {_COLUMNAS_ARTEFACTO} from fiscal.source_documents "
        "where id = %s and company_id = %s",
        (source_document_id, company_id),
        "source_visibility",
    ).fetchone()


def _bloquear(conn: Connection, company_id: str, source_document_id: str):
    """PASO B · intención de escritura **y** bloqueo de concurrencia.

    Cumple dos funciones a la vez, y las dos son necesarias: cero filas aquí
    tras haber sido visible en el paso A significa que RLS no concede la
    escritura; y la fila devuelta queda bloqueada hasta el fin de la
    transacción, que es lo que cierra la ventana entre decidir y enlazar.
    """
    return _ejecutar(
        conn,
        f"select {_COLUMNAS_ARTEFACTO} from fiscal.source_documents "
        "where id = %s and company_id = %s for update",
        (source_document_id, company_id),
        "source_write_lock",
    ).fetchone()


# ─────────────────────────────────────────────────────────────────────────────
# SQL de inserción
# ─────────────────────────────────────────────────────────────────────────────

_INSERT_EDOC = """
insert into fiscal.electronic_documents (
    company_id, document_type, clave, consecutive_number,
    issued_at_local, issued_at, issued_at_offset_minutes, issued_at_raw,
    issuer_activity_code, receiver_activity_code,
    sale_condition_code, credit_term,
    currency_code, reported_exchange_rate,
    reported_total_taxed, reported_total_exempt, reported_total_exonerated,
    reported_total_not_subject, reported_total_sale, reported_total_discount,
    reported_total_net_sale, reported_total_tax, reported_total_document,
    ruleset_revision, ruleset_revision_status,
    direction, direction_computed_at
) values (
    %s, %s, %s, %s,
    %s, %s, %s, %s,
    %s, %s,
    %s, %s,
    %s, %s,
    %s, %s, %s,
    %s, %s, %s,
    %s, %s, %s,
    null, %s,
    %s, now()
) returning id
"""

_INSERT_PARTY = """
insert into fiscal.document_parties (
    company_id, electronic_document_id, role, legal_name, trade_name,
    identification_type_code, identification_number
) values (%s, %s, %s, %s, %s, %s, %s)
"""

_INSERT_LINE = """
insert into fiscal.document_lines (
    company_id, electronic_document_id, line_number,
    cabys_code, description, unit_of_measure_code,
    reported_quantity, reported_unit_price, reported_gross_amount,
    reported_subtotal, reported_taxable_base, reported_net_tax,
    reported_line_total
) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
returning id
"""

_INSERT_DISCOUNT = """
insert into fiscal.line_discounts (
    company_id, document_line_id, sequence, reported_amount, discount_code
) values (%s, %s, %s, %s, %s)
"""

_INSERT_TAX = """
insert into fiscal.line_taxes (
    company_id, document_line_id, sequence,
    tax_code, vat_rate_code, reported_rate, reported_amount
) values (%s, %s, %s, %s, %s, %s, %s)
"""

_INSERT_REFERENCE = """
insert into fiscal.document_references (
    company_id, electronic_document_id, sequence,
    referenced_document_type_code, reported_number,
    reported_reference_date_local, reported_reference_date,
    reported_reference_offset_minutes, reported_reference_date_raw,
    reference_code, reason, resolved_document_id
) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, null)
"""


def _insertar_documento(conn: Connection, company_id: str, parsed) -> str:
    """El sobre. Devuelve el `id` que genera PostgreSQL.

    Los valores van **tal cual** los dejó el parser: sin recortar, sin
    convertir vacío en `NULL`, sin `float`. `Decimal` viaja como `Decimal`.
    """
    d = parsed.document
    fila = _ejecutar(
        conn, _INSERT_EDOC,
        (
            company_id, d.document_type, d.clave, d.consecutive_number,
            # ADR-039: reloj de pared siempre; instante y desplazamiento solo
            # si la fuente los declara. `local` es naive y así se pasa, para
            # que psycopg lo adapte a `timestamp` y no a `timestamptz`.
            d.fecha.local, d.fecha.instante, d.fecha.offset_minutos, d.fecha.raw,
            d.issuer_activity_code, d.receiver_activity_code,
            d.sale_condition_code, d.credit_term,
            d.currency_code, d.reported_exchange_rate,
            d.reported_total_taxed, d.reported_total_exempt,
            d.reported_total_exonerated, d.reported_total_not_subject,
            d.reported_total_sale, d.reported_total_discount,
            d.reported_total_net_sale, d.reported_total_tax,
            d.reported_total_document,
            RULESET_SIN_RESOLVER, DIRECTION_SIN_ESTABLECER,
        ),
        "electronic_document",
    ).fetchone()
    return fila["id"]


def _insertar_partes(conn: Connection, company_id: str, edoc_id: str, parsed) -> None:
    filas = []
    for parte in parsed.parties:
        ident = parte.identificacion
        filas.append((
            company_id, edoc_id, parte.role, parte.legal_name, parte.trade_name,
            # Identificación ausente → ambas columnas NULL. Presente con
            # `numero=""` → tipo NOT NULL y número cadena vacía. Son estados
            # distintos y aquí no se colapsan.
            ident.tipo if ident is not None else None,
            ident.numero if ident is not None else None,
        ))
    _ejecutar_muchos(conn, _INSERT_PARTY, filas, "document_parties")


def _insertar_lineas(conn: Connection, company_id: str, edoc_id: str, parsed) -> None:
    """Cada línea se inserta por separado porque su `id` generado hace falta
    para sus descuentos e impuestos. No se confía en el orden de retorno de una
    operación por lotes: se toma el `id` de cada inserción."""
    for linea in parsed.lines:
        fila = _ejecutar(
            conn, _INSERT_LINE,
            (
                company_id, edoc_id,
                # `line_number` es el `NumeroLinea` REPORTADO, nunca la
                # posición en la colección.
                linea.line_number,
                linea.cabys_code, linea.description, linea.unit_of_measure_code,
                linea.reported_quantity, linea.reported_unit_price,
                linea.reported_gross_amount, linea.reported_subtotal,
                linea.reported_taxable_base, linea.reported_net_tax,
                linea.reported_line_total,
            ),
            "document_line",
        ).fetchone()
        linea_id = fila["id"]

        # `sequence` SÍ es enumeración: el XSD no numera estos hijos, y el
        # orden de la tupla del parser es el del documento.
        _ejecutar_muchos(
            conn, _INSERT_DISCOUNT,
            [
                (company_id, linea_id, i, d.reported_amount, d.discount_code)
                for i, d in enumerate(linea.discounts, start=1)
            ],
            "line_discounts",
        )
        _ejecutar_muchos(
            conn, _INSERT_TAX,
            [
                (company_id, linea_id, i, t.tax_code, t.vat_rate_code,
                 t.reported_rate, t.reported_amount)
                for i, t in enumerate(linea.taxes, start=1)
            ],
            "line_taxes",
        )


def _insertar_referencias(conn: Connection, company_id: str, edoc_id: str, parsed) -> None:
    """`resolved_document_id` siempre `NULL`: C1 no resuelve referencias.

    El documento referido **no tiene por qué existir**. La Nota de Crédito real
    del corpus apunta a una Factura que no está, y debe persistir igual.
    """
    filas = [
        (
            company_id, edoc_id, i,
            r.referenced_document_type_code, r.reported_number,
            r.fecha.local, r.fecha.instante, r.fecha.offset_minutos, r.fecha.raw,
            r.reference_code, r.reason,
        )
        for i, r in enumerate(parsed.references, start=1)
    ]
    _ejecutar_muchos(conn, _INSERT_REFERENCE, filas, "document_references")


def _enlazar(conn: Connection, company_id: str, source_document_id: str,
             edoc_id: str) -> None:
    """Última escritura del agregado. **La única mutación de `source_documents`
    que hace C1**: `parse_status` pertenece a la ingesta, que ejecuta el parser.

    **Se comprueba que afecte exactamente a una fila.** No es una formalidad:
    una política `UPDATE` de RLS no lanza error, *filtra*. Si la capacidad de
    escritura del usuario cambiara entre la puerta y este momento —otra
    transacción tocando `company_memberships`—, el `UPDATE` afectaría a cero
    filas y, sin esta comprobación, devolveríamos `created` con el artefacto
    **sin enlazar**: un documento normalizado huérfano de su evidencia.

    El predicado exige además `electronic_document_id is null`. La fila ya está
    bloqueada desde el paso B, así que no es el mecanismo de concurrencia sino
    defensa en profundidad; C1 solo enlaza artefactos no enlazados y jamás
    reenlaza. Como el bloqueo excluye que otro lo enlace mientras tanto, cero
    filas sigue significando **denegación de escritura**, no «ya estaba».
    """
    cur = _ejecutar(
        conn,
        "update fiscal.source_documents "
        "set electronic_document_id = %s, updated_at = now() "
        "where id = %s and company_id = %s "
        "and electronic_document_id is null",
        (edoc_id, source_document_id, company_id),
        "source_link",
    )
    if cur.rowcount == 1:
        return
    if cur.rowcount == 0:
        # Interpretación aprobada: RLS filtró la escritura. La transacción
        # externa revierte el agregado entero y el artefacto queda sin enlazar.
        raise FiscalWriteForbidden(
            "No se permite escribir datos fiscales en esta empresa",
            stage="source_link",
            source_document_id=str(source_document_id),
        )
    # Imposible bajo un predicado de clave primaria. Que ocurra indicaría un
    # estado de base de datos inesperado, no un problema del contribuyente.
    raise PersistenceDatabaseError(
        "El enlace del artefacto afectó a un número inesperado de filas",
        stage="source_link", rowcount=cur.rowcount,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Contrato público
# ─────────────────────────────────────────────────────────────────────────────

def persist_parsed_fiscal_document(
    conn: Connection,
    *,
    company_id: str,
    source_document_id: str,
    parsed: ParsedFiscalDocument,
) -> PersistenceResult:
    """Guarda el agregado normalizado y enlaza su artefacto de origen.

    `conn` viene **ya dentro** de una transacción fiscal autenticada. Esta
    función no abre conexión, no comitea, no revierte y no fija identidad ni
    rol: el dueño de la transacción es la capa de caso de uso. El único
    anidamiento que usa es un `SAVEPOINT` para recuperarse de la colisión de
    clave, que es una rama esperada y no un error.
    """
    # A · ¿lo ve? Agrupa a propósito inexistente, de otra empresa y no miembro.
    if _leer_visible(conn, company_id, source_document_id) is None:
        raise SourceDocumentNotFound(
            "El artefacto de origen no existe o no es accesible",
            source_document_id=str(source_document_id),
        )

    # B · ¿puede escribir? Cero filas aquí, tras haberlo visto, es denegación.
    #     La puerta va ANTES de cualquier decisión de idempotencia: un `viewer`
    #     no debe recibir `already_persisted` ni `linked_existing`, aunque ese
    #     reintento concreto no fuera a mutar nada. C1 es un caso de uso de
    #     escritura, y la autorización no depende de la suerte del camino.
    artefacto = _bloquear(conn, company_id, source_document_id)
    if artefacto is None:
        raise FiscalWriteForbidden(
            "No se permite escribir datos fiscales en esta empresa",
            source_document_id=str(source_document_id),
        )

    # C · ¿ya estaba normalizado?
    ya_enlazado = artefacto["electronic_document_id"]
    if ya_enlazado is not None:
        return _resolver_ya_enlazado(
            conn, company_id, source_document_id, ya_enlazado, parsed
        )

    # D · crear, o recuperarse de una colisión de clave.
    try:
        with conn.transaction():          # anidada → SAVEPOINT
            edoc_id = _insertar_documento(conn, company_id, parsed)
    except PersistenceMappingError as exc:
        # `_ejecutar` ya tradujo. Solo la colisión de la clave abre dedup; el
        # resto de violaciones de unicidad son defectos de mapeo y se propagan.
        if exc.contexto.get("constraint") != UNIQUE_CLAVE:
            raise
        return _resolver_clave_existente(
            conn, company_id, source_document_id, artefacto, parsed
        )

    _insertar_partes(conn, company_id, edoc_id, parsed)
    _insertar_lineas(conn, company_id, edoc_id, parsed)
    _insertar_referencias(conn, company_id, edoc_id, parsed)
    _enlazar(conn, company_id, source_document_id, edoc_id)

    return PersistenceResult(
        electronic_document_id=str(edoc_id),
        source_document_id=str(source_document_id),
        status=PersistenceStatus.CREATED,
    )


def _resolver_ya_enlazado(conn, company_id, source_document_id, edoc_id, parsed):
    """El artefacto ya apunta a un documento. Reintento o conflicto de estado."""
    fila = _ejecutar(
        conn,
        "select clave from fiscal.electronic_documents "
        "where id = %s and company_id = %s",
        (edoc_id, company_id),
        "linked_document",
    ).fetchone()

    if fila is None or fila["clave"] != parsed.document.clave:
        # Nunca se reenlaza: el enlace es evidencia de cómo llegó esta copia.
        raise SourceDocumentStateConflict(
            "El artefacto ya está normalizado como otro documento",
            source_document_id=str(source_document_id),
            electronic_document_id=str(edoc_id),
        )

    # Reintento del mismo artefacto: ni una escritura, ni siquiera `updated_at`.
    return PersistenceResult(
        electronic_document_id=str(edoc_id),
        source_document_id=str(source_document_id),
        status=PersistenceStatus.ALREADY_PERSISTED,
    )


def _resolver_clave_existente(conn, company_id, source_document_id, artefacto, parsed):
    """Tras el `23505` de `(company_id, clave)`: ¿duplicado o conflicto?

    La única prueba de equivalencia que el MVP acepta es la **igualdad de la
    huella del artefacto** (ADR-042). Comparar el subconjunto de campos que el
    parser normaliza respondería a otra pregunta: B2 dejó fuera campos
    fiscalmente relevantes, y dos documentos podrían coincidir en todo lo que
    miramos y diferir en una `Exoneracion`.
    """
    existente = _ejecutar(
        conn,
        "select id from fiscal.electronic_documents "
        "where company_id = %s and clave = %s",
        (company_id, parsed.document.clave),
        "existing_document",
    ).fetchone()
    if existente is None:                 # pragma: no cover - carrera imposible
        raise PersistenceMappingError(
            "La clave colisionó pero el documento no es visible",
            stage="existing_document",
        )
    edoc_id = existente["id"]

    # ¿Hay ya un artefacto de esta empresa, enlazado a ese documento, con la
    # misma huella? Lo sirve `sdoc_company_hash_idx (company_id, content_sha256)`.
    evidencia = _ejecutar(
        conn,
        "select 1 as ok from fiscal.source_documents "
        "where company_id = %s and electronic_document_id = %s "
        "and content_sha256 = %s limit 1",
        (company_id, edoc_id, artefacto["content_sha256"]),
        "duplicate_evidence",
    ).fetchone()

    if evidencia is None:
        # Huella distinta NO prueba que el contenido fiscal difiera: prueba que
        # no podemos establecer la equivalencia automáticamente. Se hace visible
        # en lugar de fusionar al azar.
        raise ClaveConflict(
            "Ya existe un documento con esa clave y no se pudo establecer "
            "equivalencia con el artefacto recibido",
            source_document_id=str(source_document_id),
            electronic_document_id=str(edoc_id),
        )

    # Mismo documento lógico, otro artefacto: se conserva la evidencia de cómo
    # llegó cada copia y no se duplica el agregado normalizado.
    _enlazar(conn, company_id, source_document_id, edoc_id)
    return PersistenceResult(
        electronic_document_id=str(edoc_id),
        source_document_id=str(source_document_id),
        status=PersistenceStatus.LINKED_EXISTING,
    )
