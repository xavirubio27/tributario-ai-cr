/**
 * Traducción del resultado a algo que una persona entienda.
 *
 * Módulo PURO Y SIN DEPENDENCIAS. El backend es dueño del CÓDIGO ESTABLE; el
 * frontend es dueño del TEXTO. Por eso ninguna de estas frases existe en
 * Python: si viviera en los dos lados, acabarían divergiendo.
 *
 * REGLAS DE REDACCIÓN
 *   · No se culpa al documento del contribuyente de un fallo nuestro.
 *   · No se llama «inválido» a algo que Tribuu simplemente no soporta todavía.
 *   · Nada de lenguaje del Tax Engine: ni deducible, ni crédito de IVA.
 *   · Un duplicado NO es un error.
 */

import type {
  UploadErrorCategory,
  UploadFiscalDocumentActionResult,
  UploadOutcome,
} from './contract'

/** Tono del aviso. Nunca se comunica el estado solo con el color. */
export type UploadTone = 'success' | 'info' | 'attention' | 'error'

export type UploadMessage = {
  tone: UploadTone
  title: string
  detail: string
}

const EXITO: Record<UploadOutcome, UploadMessage> = {
  created: {
    tone: 'success',
    title: 'Procesado correctamente',
    detail: 'El comprobante quedó registrado.',
  },
  linked_existing: {
    tone: 'info',
    title: 'Documento ya registrado',
    detail: 'Ya teníamos este comprobante. Guardamos también esta recepción.',
  },
  already_persisted: {
    tone: 'info',
    title: 'Documento ya registrado',
    detail: 'Este documento ya estaba procesado.',
  },
}

const FALLO: Record<UploadErrorCategory, UploadMessage> = {
  invalid_request: {
    tone: 'error',
    title: 'No se pudo enviar el archivo',
    detail: 'Selecciona un único archivo e inténtalo de nuevo.',
  },
  rejected_before_capture: {
    tone: 'error',
    title: 'Archivo no admitido',
    detail: 'El archivo está vacío o supera el tamaño máximo de 8 MB.',
  },
  invalid_document: {
    tone: 'error',
    title: 'Archivo inválido',
    detail: 'El archivo no es un comprobante electrónico válido.',
  },
  unrecognized: {
    tone: 'error',
    title: 'Documento no reconocido',
    detail: 'No reconocemos este XML como un comprobante electrónico.',
  },
  outside_pipeline: {
    tone: 'attention',
    title: 'No es un comprobante',
    detail:
      'Reconocemos el documento, pero no pertenece a este flujo de comprobantes.',
  },
  not_yet_supported: {
    tone: 'attention',
    title: 'Todavía no soportado',
    detail:
      'Reconocemos el documento, pero aún no procesamos este tipo. No es un problema de tu archivo.',
  },
  requires_review: {
    tone: 'attention',
    title: 'Requiere atención',
    detail:
      'Ya existe un documento con esa clave y no coincide con este. Guardamos el archivo para revisarlo.',
  },
  forbidden: {
    tone: 'error',
    title: 'Sin permiso',
    detail: 'No tienes permiso para registrar documentos en esta empresa.',
  },
  not_found: {
    tone: 'error',
    title: 'No encontrado',
    detail: 'No encontramos el documento indicado.',
  },
  temporary: {
    // El backend CONFIRMÓ que la evidencia quedó guardada. Por eso aquí sí se
    // puede afirmar que el documento está a salvo.
    tone: 'attention',
    title: 'Problema temporal',
    detail:
      'Guardamos el documento, pero no pudimos terminar de procesarlo. Lo retomaremos; no hace falta que lo vuelvas a subir.',
  },
  indeterminate: {
    // Aquí NO sabemos nada: la conexión terminó antes de que llegara una
    // respuesta. Decir «lo guardamos» sería afirmar algo que nadie confirmó, y
    // decir «no llegó» sería igual de falso. Tampoco se pide resubir a ciegas:
    // podría duplicar la evidencia por un fallo de red.
    tone: 'attention',
    title: 'No pudimos confirmar el resultado',
    detail:
      'La conexión terminó antes de que pudiéramos confirmar si el documento fue recibido. Puede que sí lo esté. Revisa antes de volver a subirlo.',
  },
  internal: {
    tone: 'error',
    title: 'Algo salió mal',
    detail: 'No pudimos procesar la solicitud. Inténtalo de nuevo más tarde.',
  },
}

export function messageFor(
  resultado: UploadFiscalDocumentActionResult,
): UploadMessage {
  return resultado.ok ? EXITO[resultado.status] : FALLO[resultado.category]
}
