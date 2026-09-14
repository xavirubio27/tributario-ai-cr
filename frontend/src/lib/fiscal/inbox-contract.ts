/**
 * Contrato de lectura de la bandeja — espejo del backend.
 *
 * Módulo PURO Y SIN DEPENDENCIAS, importable desde el paquete de tests.
 *
 * AUTORIDAD
 *   Refleja `InboxPageResponse` de `backend/app/api/schemas.py`. No lo define.
 */

export type OperationalStatus =
  | 'processed'
  | 'requires_attention'
  | 'system_pending'
  | 'invalid_document'
  | 'unrecognized'
  | 'not_yet_supported'
  | 'outside_pipeline'

export const OPERATIONAL_STATUSES: readonly OperationalStatus[] = [
  'processed',
  'requires_attention',
  'system_pending',
  'invalid_document',
  'unrecognized',
  'not_yet_supported',
  'outside_pipeline',
] as const

/**
 * Unión discriminada, igual que en el backend.
 *
 * Un `document` colapsa varias recepciones y por eso **no** tiene
 * `sourceDocumentId`: elegir una sería arbitrario. Un `receipt` es una
 * recepción concreta y **no** tiene documento normalizado.
 */
export type InboxItem =
  | {
      kind: 'document'
      operationalStatus: 'processed'
      electronicDocumentId: string
      sourceDocumentId: null
      receivedAt: string
      receiptCount: number
      documentType: string | null
      issuedAtLocal: string | null
      issuedAtOffsetMinutes: number | null
      consecutiveNumber: string | null
      currencyCode: string | null
      /** CADENA: decimal exacto. Convertirlo a `number` lo alteraría. */
      reportedTotalDocument: string | null
    }
  | {
      kind: 'receipt'
      operationalStatus: Exclude<OperationalStatus, 'processed'>
      electronicDocumentId: null
      sourceDocumentId: string
      receivedAt: string
      receiptCount: number
      documentType: string | null
    }

export type InboxCounts = {
  /** Lo que depende del usuario. Excluye los límites de Tribuu. */
  needsAttention: number
  systemPending: number
}

export type InboxPage = {
  items: InboxItem[]
  nextCursor: string | null
  counts: InboxCounts
}

/** Lectura correcta, o un fallo con categoría segura. */
export type InboxResult =
  | { ok: true; page: InboxPage }
  | { ok: false; category: 'forbidden' | 'temporary' | 'internal' }

export const PAGE_SIZE_DEFAULT = 25
export const PAGE_SIZE_MAX = 100
