/**
 * Contrato de la subida fiscal — espejo del backend.
 *
 * Módulo PURO Y SIN DEPENDENCIAS, como `companies/validation.ts`: lo importan
 * la Server Action y los tests directamente, sin alias `@/` para que el
 * paquete `tests/` pueda cargarlo por ruta relativa.
 *
 * AUTORIDAD
 *   Estos valores REFLEJAN el contrato que define el backend en
 *   `backend/app/api/schemas.py`. No lo definen. Si divergieran, manda el
 *   backend; aquí solo se traduce a algo que React pueda consumir.
 */

/** Desenlaces con éxito. Espeja `UploadOutcome`. */
export type UploadOutcome = 'created' | 'linked_existing' | 'already_persisted'

export const UPLOAD_OUTCOMES: readonly UploadOutcome[] = [
  'created',
  'linked_existing',
  'already_persisted',
] as const

/** Familias de fallo del BACKEND. Espeja `ErrorCategory` de `schemas.py`. */
export type BackendErrorCategory =
  | 'invalid_request'
  | 'rejected_before_capture'
  | 'invalid_document'
  | 'unrecognized'
  | 'outside_pipeline'
  | 'not_yet_supported'
  | 'requires_review'
  | 'forbidden'
  | 'not_found'
  | 'temporary'
  | 'internal'

/**
 * Categoría propia de ESTA capa, que el backend no conoce ni puede conocer.
 *
 * `indeterminate` es el caso en que la conexión terminó antes de que llegara
 * una respuesta válida: `fetch` rechazado, DNS caído, conexión reiniciada,
 * redirección rechazada o el temporizador agotado.
 *
 * **No es lo mismo que un 503.** Un 503 es el backend DICIÉNDONOS que guardó
 * la evidencia y no pudo terminar de procesarla. Aquí no sabemos nada: la
 * petición pudo no salir, pudo llegar y capturarse, o pudo completarse entera
 * y perderse solo la respuesta. Fundir ambos casos hacía que la interfaz
 * afirmara «guardamos el documento» sin tener ni idea.
 *
 * Vive SOLO en el contrato de la Server Action. No se añade al dominio ni se
 * finge que lo emitió FastAPI.
 */
export type ActionErrorCategory = 'indeterminate'

export type UploadErrorCategory = BackendErrorCategory | ActionErrorCategory

export const BACKEND_ERROR_CATEGORIES: readonly BackendErrorCategory[] = [
  'invalid_request',
  'rejected_before_capture',
  'invalid_document',
  'unrecognized',
  'outside_pipeline',
  'not_yet_supported',
  'requires_review',
  'forbidden',
  'not_found',
  'temporary',
  'internal',
] as const

/** Todas las categorías que la interfaz puede recibir. */
export const ALL_ERROR_CATEGORIES: readonly UploadErrorCategory[] = [
  ...BACKEND_ERROR_CATEGORIES,
  'indeterminate',
] as const

/**
 * Tope de bytes, ESPEJO del dominio.
 *
 * La autoridad es `MAX_SOURCE_XML_BYTES` en
 * `backend/app/fiscal/ingestion.py`, que vale lo mismo. Este valor existe solo
 * para avisar antes de subir 8 MiB para nada; el backend vuelve a comprobarlo
 * y su respuesta es la que manda.
 *
 * NO confundir con el sobre de transporte de Next (9 MiB, en
 * `next.config.ts`), que es mayor a propósito para alojar el marco multipart.
 */
export const MAX_SOURCE_XML_BYTES_UI = 8 * 1024 * 1024

/** Resultado de la Server Action. Serializable: lo consume React. */
export type UploadFiscalDocumentActionResult =
  | {
      ok: true
      status: UploadOutcome
      /** Se conserva para B3 (revisión, reproceso). No se muestra. */
      sourceDocumentId: string
      electronicDocumentId: string
    }
  | {
      ok: false
      code: string
      category: UploadErrorCategory
      /** Presente cuando la evidencia SÍ quedó guardada. */
      sourceDocumentId?: string
      /** Discriminador estructurado de `unsupported_document`. */
      reason?: string
    }

export const EMPTY_UPLOAD_STATE: UploadFiscalDocumentActionResult | null = null
