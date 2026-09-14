/**
 * Interpretación de la respuesta de la bandeja.
 *
 * Módulo PURO. Misma disciplina que la subida: **no se confía en el JSON del
 * backend**. Se valida forma, discriminante, vocabulario y reglas de
 * nulidad, y lo que no encaje falla cerrando en vez de renderizarse a medias.
 *
 * Un ítem con forma imposible —un `document` sin identificador normalizado, un
 * `receipt` marcado como `processed`— no se muestra deformado: invalida la
 * lectura entera, porque un listado a medias es peor que un error honesto.
 */

import {
  OPERATIONAL_STATUSES,
  type InboxCounts,
  type InboxItem,
  type InboxPage,
  type InboxResult,
  type OperationalStatus,
} from './inbox-contract'
import {
  isExactDecimal,
  isInstant,
  isLocalDateTime,
  isOffsetMinutes,
  isOpaqueCursor,
  isUuid,
} from './validators'

export const LECTURA_PROHIBIDA: InboxResult = { ok: false, category: 'forbidden' }
export const LECTURA_TEMPORAL: InboxResult = { ok: false, category: 'temporary' }
export const LECTURA_INTERNA: InboxResult = { ok: false, category: 'internal' }

function cadena(v: unknown): v is string {
  return typeof v === 'string' && v.length > 0
}

function cadenaONulo(v: unknown): v is string | null {
  return v === null || cadena(v)
}

function entero(v: unknown): v is number {
  return typeof v === 'number' && Number.isInteger(v) && v >= 0
}

function aItem(crudo: unknown): InboxItem | null {
  if (crudo === null || typeof crudo !== 'object' || Array.isArray(crudo)) return null
  const d = crudo as Record<string, unknown>

  const estado = d.operational_status
  if (!cadena(estado) || !(OPERATIONAL_STATUSES as readonly string[]).includes(estado)) {
    return null
  }
  // Instante CON huso: es tiempo del sistema, y sin huso sería ambiguo.
  if (!isInstant(d.received_at) || !entero(d.receipt_count) || d.receipt_count < 1) {
    return null
  }
  if (!cadenaONulo(d.document_type)) return null

  if (d.kind === 'document') {
    // Un documento normalizado SIEMPRE está procesado y SIEMPRE tiene enlace.
    if (estado !== 'processed') return null
    if (!isUuid(d.electronic_document_id) || d.source_document_id !== null) return null
    // Fecha LOCAL del documento: se valida la forma y NO se convierte a `Date`,
    // que la reinterpretaría en el huso del servidor (ADR-039).
    if (d.issued_at_local !== null && !isLocalDateTime(d.issued_at_local)) return null
    if (!cadenaONulo(d.consecutive_number)) return null
    if (!cadenaONulo(d.currency_code)) return null
    // Importe: decimal exacto en su forma léxica. Un número significaría que
    // alguien lo convirtió por el camino y la precisión ya se habría perdido.
    if (d.reported_total_document !== null &&
        !isExactDecimal(d.reported_total_document)) return null
    const offset = d.issued_at_offset_minutes
    if (offset !== null && !isOffsetMinutes(offset)) return null

    return {
      kind: 'document',
      operationalStatus: 'processed',
      electronicDocumentId: d.electronic_document_id,
      sourceDocumentId: null,
      receivedAt: d.received_at,
      receiptCount: d.receipt_count,
      documentType: d.document_type,
      issuedAtLocal: d.issued_at_local,
      issuedAtOffsetMinutes: offset as number | null,
      consecutiveNumber: d.consecutive_number,
      currencyCode: d.currency_code,
      reportedTotalDocument: d.reported_total_document,
    }
  }

  if (d.kind === 'receipt') {
    // Una recepción sin normalizar no puede estar «procesada».
    if (estado === 'processed') return null
    if (!isUuid(d.source_document_id) || d.electronic_document_id !== null) return null
    return {
      kind: 'receipt',
      operationalStatus: estado as Exclude<OperationalStatus, 'processed'>,
      electronicDocumentId: null,
      sourceDocumentId: d.source_document_id,
      receivedAt: d.received_at,
      receiptCount: d.receipt_count,
      documentType: d.document_type,
    }
  }

  return null
}

function aContadores(crudo: unknown): InboxCounts | null {
  if (crudo === null || typeof crudo !== 'object') return null
  const d = crudo as Record<string, unknown>
  if (!entero(d.needs_attention) || !entero(d.system_pending)) return null
  return { needsAttention: d.needs_attention, systemPending: d.system_pending }
}

export function interpretInbox(status: number, cuerpo: unknown): InboxResult {
  if (status === 401 || status === 403) {
    return LECTURA_PROHIBIDA
  }
  if (status === 503) {
    return LECTURA_TEMPORAL
  }
  if (status !== 200) {
    return LECTURA_INTERNA
  }
  if (cuerpo === null || typeof cuerpo !== 'object' || Array.isArray(cuerpo)) {
    return LECTURA_INTERNA
  }

  const d = cuerpo as Record<string, unknown>
  if (!Array.isArray(d.items)) return LECTURA_INTERNA

  const items: InboxItem[] = []
  for (const crudo of d.items) {
    const item = aItem(crudo)
    // Un solo ítem incoherente invalida la página: media lista es peor que un
    // error claro, porque el usuario no sabría qué le falta.
    if (item === null) return LECTURA_INTERNA
    items.push(item)
  }

  const counts = aContadores(d.counts)
  if (counts === null) return LECTURA_INTERNA
  // Opaco: se comprueba que sea nulo o una cadena, sin decodificar nada.
  if (d.next_cursor !== null && !isOpaqueCursor(d.next_cursor)) return LECTURA_INTERNA

  const page: InboxPage = { items, nextCursor: d.next_cursor, counts }
  return { ok: true, page }
}
