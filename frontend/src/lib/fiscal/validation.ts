/**
 * Validación de la subida, previa a la red.
 *
 * Módulo PURO Y SIN DEPENDENCIAS. Dos responsabilidades, y ninguna es
 * autoridad:
 *
 *   1. la ESTRUCTURA de la petición —que venga exactamente un fichero—, que sí
 *      es cosa nuestra porque el backend nunca ve el `FormData`;
 *   2. el TAMAÑO, que es una cortesía: evita subir 8 MiB para que los rechacen.
 *
 * Lo que NO hace, a propósito: mirar la extensión, mirar el tipo MIME o abrir
 * el XML. La extensión es una pista de interfaz y el navegador informa el MIME
 * de formas incoherentes —`application/xml`, `text/xml`,
 * `application/octet-stream`, `text/plain` o vacío— según sistema operativo.
 * Rechazar por ahí negaría comprobantes legítimos. **El parser decide.**
 */

import {
  MAX_SOURCE_XML_BYTES_UI,
  type UploadErrorCategory,
} from './contract'

export type FileValidationFailure = {
  code: 'missing_file' | 'multiple_files' | 'invalid_file_field'
      | 'empty_source_document' | 'source_document_too_large'
  category: UploadErrorCategory
}

export type FileValidationResult =
  | { ok: true; file: File }
  | { ok: false; failure: FileValidationFailure }

/** Extensión sugerida al selector. Pista de interfaz, nunca un filtro. */
export const XML_ACCEPT_HINT = '.xml,application/xml,text/xml'

/**
 * Extrae EL fichero del formulario, o explica por qué no puede.
 *
 * Usa `getAll`, no `get`: con `get` un envío con dos ficheros pasaría en
 * silencio quedándose con el primero, y el usuario creería haber subido algo
 * que nadie miró.
 */
export function validateUpload(formData: FormData): FileValidationResult {
  const valores = formData.getAll('file')

  if (valores.length === 0) {
    return { ok: false, failure: { code: 'missing_file', category: 'invalid_request' } }
  }
  if (valores.length > 1) {
    return { ok: false, failure: { code: 'multiple_files', category: 'invalid_request' } }
  }

  const valor = valores[0]
  if (typeof valor === 'string' || !(valor instanceof File)) {
    return {
      ok: false,
      failure: { code: 'invalid_file_field', category: 'invalid_request' },
    }
  }

  // A partir de aquí el fallo YA NO es de estructura: habla del artefacto, y
  // usa el mismo vocabulario que devolvería el backend.
  if (valor.size === 0) {
    return {
      ok: false,
      failure: {
        code: 'empty_source_document',
        category: 'rejected_before_capture',
      },
    }
  }
  if (valor.size > MAX_SOURCE_XML_BYTES_UI) {
    return {
      ok: false,
      failure: {
        code: 'source_document_too_large',
        category: 'rejected_before_capture',
      },
    }
  }

  return { ok: true, file: valor }
}
