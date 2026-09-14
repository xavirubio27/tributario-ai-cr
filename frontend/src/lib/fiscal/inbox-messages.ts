/**
 * Copia de la bandeja. El backend posee el código; el frontend, el texto.
 *
 * Módulo PURO Y SIN DEPENDENCIAS.
 *
 * REGLAS DE REDACCIÓN
 *   · Nada de lenguaje tributario: ni IVA, ni deducible, ni retención.
 *   · Nada de ventas, compras, ingresos ni gastos: la dirección del documento
 *     no está establecida y no se insinúa.
 *   · Lo que es límite de Tribuu se dice como tal, no como culpa del archivo.
 */

import type { OperationalStatus } from './inbox-contract'

export type StatusTone = 'neutral' | 'attention' | 'error'

export type StatusLabel = {
  label: string
  tone: StatusTone
  /** El estado nunca se comunica solo con color. */
  mark: string
}

export const STATUS_LABELS: Record<OperationalStatus, StatusLabel> = {
  processed: { label: 'Procesado', tone: 'neutral', mark: '✓' },
  requires_attention: { label: 'Requiere atención', tone: 'attention', mark: '!' },
  system_pending: { label: 'Pendiente del sistema', tone: 'attention', mark: '…' },
  invalid_document: { label: 'Documento inválido', tone: 'error', mark: '×' },
  unrecognized: { label: 'No reconocido', tone: 'error', mark: '×' },
  not_yet_supported: { label: 'Todavía no soportado', tone: 'attention', mark: '•' },
  outside_pipeline: { label: 'No es un comprobante', tone: 'attention', mark: '•' },
}

/** Tipo de documento en lenguaje corriente. */
export const DOCUMENT_TYPE_LABELS: Record<string, string> = {
  invoice: 'Factura electrónica',
  ticket: 'Tiquete electrónico',
  credit_note: 'Nota de crédito',
  debit_note: 'Nota de débito',
  hacienda_message: 'Mensaje de Hacienda',
}

export function documentTypeLabel(tipo: string | null): string | null {
  if (!tipo) return null
  return DOCUMENT_TYPE_LABELS[tipo] ?? null
}

export const INBOX_ERROR_MESSAGES: Record<
  'forbidden' | 'temporary' | 'internal',
  { title: string; detail: string }
> = {
  forbidden: {
    title: 'Sin acceso',
    detail: 'No tienes acceso a los documentos de esta empresa.',
  },
  temporary: {
    title: 'No pudimos cargar los documentos',
    detail: 'Es un problema temporal. Vuelve a intentarlo en un momento.',
  },
  internal: {
    title: 'No pudimos cargar los documentos',
    detail: 'Algo salió mal de nuestro lado.',
  },
}

export const INBOX_EMPTY = {
  title: 'No hay documentos todavía',
  detail: 'Cuando subas un comprobante aparecerá aquí.',
}
