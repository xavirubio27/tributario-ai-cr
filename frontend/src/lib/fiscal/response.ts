/**
 * Interpretación de la respuesta del backend.
 *
 * Módulo PURO Y SIN DEPENDENCIAS —no hace red— para poder probarlo sin
 * levantar nada.
 *
 * SE VALIDA LA COMBINACIÓN COMPLETA, NO UN CAMPO SUELTO
 *   Reconocer una categoría no basta. Un `409` con cuerpo de éxito, un `500`
 *   con `category: invalid_document` o un `422` con un `code` que no le
 *   corresponde son respuestas CONTRADICTORIAS, y aceptarlas significaría
 *   enseñarle al usuario una conclusión que nadie afirmó. Cada respuesta debe
 *   encajar en una fila de la matriz: estado, código, categoría, motivo y
 *   presencia del identificador.
 *
 * SE FALLA CERRANDO
 *   Lo que no encaje —un código futuro, un motivo desconocido, un cuerpo de
 *   proxy, un campo que falta— cae en `internal`. Es preferible decir «algo
 *   salió mal» a inventar una semántica que el backend no expresó.
 */

import {
  UPLOAD_OUTCOMES,
  type BackendErrorCategory,
  type UploadFiscalDocumentActionResult,
  type UploadOutcome,
} from './contract'

/** Fallo genérico. No dice nada del backend ni de la red. */
export const RESULTADO_INTERNO: UploadFiscalDocumentActionResult = {
  ok: false,
  code: 'internal_error',
  category: 'internal',
}

/**
 * La conexión terminó sin una respuesta válida. **No sabemos qué pasó.**
 *
 * Distinto de un 503 confirmado: allí el backend afirma haber guardado la
 * evidencia; aquí no hay nadie afirmando nada.
 */
export const RESULTADO_INDETERMINADO: UploadFiscalDocumentActionResult = {
  ok: false,
  code: 'upload_outcome_unknown',
  category: 'indeterminate',
}

/** La sesión no sirvió. Sin lenguaje técnico de JWT. */
export const RESULTADO_SESION: UploadFiscalDocumentActionResult = {
  ok: false,
  code: 'session_expired',
  category: 'forbidden',
}

/**
 * Presencia exigida del identificador del artefacto.
 *
 * No es cosmético: deriva de cuándo comitea T1 en C2. Un fallo anterior a la
 * captura no puede traerlo, y un conflicto de clave no puede NO traerlo.
 */
type PresenciaId = 'required' | 'optional' | 'forbidden'

type Regla = {
  status: number
  code: string
  category: BackendErrorCategory
  id: PresenciaId
  /** Solo `unsupported_document`: motivos permitidos y su categoría. */
  reasons?: Readonly<Record<string, BackendErrorCategory>>
}

/**
 * Matriz del contrato, extraída de `backend/app/api/error_mapping.py`.
 *
 * Los motivos van en MINÚSCULAS porque así los serializa
 * `UnsupportedDocumentReason`. La autoridad es el backend.
 */
const MATRIZ: readonly Regla[] = [
  // ── rechazado antes de capturar: no existe artefacto que referenciar ──
  { status: 413, code: 'source_document_too_large', category: 'rejected_before_capture', id: 'forbidden' },
  { status: 422, code: 'empty_source_document', category: 'rejected_before_capture', id: 'forbidden' },
  { status: 422, code: 'invalid_request', category: 'invalid_request', id: 'forbidden' },

  // ── la evidencia SÍ quedó guardada: el identificador es obligatorio ──
  { status: 422, code: 'malformed_xml', category: 'invalid_document', id: 'required' },
  { status: 422, code: 'xsd_validation_error', category: 'invalid_document', id: 'required' },
  { status: 422, code: 'semantic_parse_error', category: 'invalid_document', id: 'required' },
  { status: 409, code: 'clave_conflict', category: 'requires_review', id: 'required' },
  { status: 404, code: 'source_document_not_found', category: 'not_found', id: 'required' },
  // C2 solo levanta `PersistenceUnavailable` dentro de T2, es decir, después
  // de que T1 comiteara, y el orquestador la enriquece. Siempre lo trae.
  { status: 503, code: 'persistence_unavailable', category: 'temporary', id: 'required' },

  // `FiscalWriteForbidden` nace tanto en la captura —sin artefacto— como en
  // T2 —con él—, así que aquí el identificador es opcional de verdad.
  { status: 403, code: 'fiscal_write_forbidden', category: 'forbidden', id: 'optional' },

  // El 500 lo devuelve el endpoint deliberadamente mudo.
  { status: 500, code: 'internal_error', category: 'internal', id: 'forbidden' },

  {
    status: 422,
    code: 'unsupported_document',
    category: 'unrecognized',      // se refina con `reason`
    id: 'required',
    reasons: {
      unknown_document: 'unrecognized',
      outside_pipeline: 'outside_pipeline',
      unsupported_type: 'not_yet_supported',
    },
  },
]

function cadenaNoVacia(v: unknown): v is string {
  return typeof v === 'string' && v.length > 0
}

function idAceptable(presencia: PresenciaId, id: string | undefined): boolean {
  if (presencia === 'required') return id !== undefined
  if (presencia === 'forbidden') return id === undefined
  return true
}

function interpretarExito(
  datos: Record<string, unknown>,
): UploadFiscalDocumentActionResult {
  const estado = datos.status
  const ok =
    cadenaNoVacia(estado) &&
    (UPLOAD_OUTCOMES as readonly string[]).includes(estado) &&
    cadenaNoVacia(datos.source_document_id) &&
    cadenaNoVacia(datos.electronic_document_id)

  if (!ok) {
    // Un 200 con cuerpo de error, un estado desconocido o un identificador
    // ausente NO se convierten en un éxito inventado.
    return RESULTADO_INTERNO
  }
  return {
    ok: true,
    status: estado as UploadOutcome,
    sourceDocumentId: datos.source_document_id as string,
    electronicDocumentId: datos.electronic_document_id as string,
  }
}

/**
 * Convierte `(estado HTTP, cuerpo)` en el resultado de la acción.
 *
 * `cuerpo` es lo que devolvió `response.json()`, o `null` si no era JSON. Que
 * llegara una respuesta y no se pueda confiar en ella **no** es incertidumbre
 * de transporte: hubo respuesta, simplemente incumple el contrato. Por eso cae
 * en `internal` y no en `indeterminate`.
 */
export function interpretResponse(
  status: number,
  cuerpo: unknown,
): UploadFiscalDocumentActionResult {
  // El 401 NO usa el esquema fiscal: es un `HTTPException` con `detail`, así
  // que se resuelve por estado y su cuerpo jamás se mira.
  if (status === 401) {
    return RESULTADO_SESION
  }

  if (cuerpo === null || typeof cuerpo !== 'object' || Array.isArray(cuerpo)) {
    return RESULTADO_INTERNO
  }
  const datos = cuerpo as Record<string, unknown>

  if (status === 200) {
    return interpretarExito(datos)
  }

  const code = datos.code
  if (!cadenaNoVacia(code)) {
    return RESULTADO_INTERNO
  }

  const regla = MATRIZ.find((r) => r.status === status && r.code === code)
  if (!regla) {
    // Código desconocido, o conocido bajo un estado que no le corresponde.
    return RESULTADO_INTERNO
  }

  const id = cadenaNoVacia(datos.source_document_id)
    ? datos.source_document_id
    : undefined
  if (!idAceptable(regla.id, id)) {
    return RESULTADO_INTERNO
  }

  if (regla.reasons) {
    const reason = datos.reason
    if (!cadenaNoVacia(reason)) return RESULTADO_INTERNO
    const categoria = regla.reasons[reason]
    // Motivo desconocido, o categoría que no concuerda con el motivo.
    if (!categoria || datos.category !== categoria) return RESULTADO_INTERNO
    return {
      ok: false,
      code,
      category: categoria,
      ...(id ? { sourceDocumentId: id } : {}),
      reason,
    }
  }

  // La categoría debe ser EXACTAMENTE la que ese código exige.
  if (datos.category !== regla.category) {
    return RESULTADO_INTERNO
  }

  return {
    ok: false,
    code,
    category: regla.category,
    ...(id ? { sourceDocumentId: id } : {}),
  }
}
