/**
 * Contrato de la subida fiscal — módulos puros del frontend (C3-B2).
 *
 * Se prueban por importación directa, sin levantar Next ni el backend, porque
 * los módulos son deliberadamente puros y sin dependencias. La tubería fiscal
 * ya está probada de extremo a extremo en el backend; lo que falta cubrir aquí
 * es la TRADUCCIÓN: qué sale del formulario y qué entiende la interfaz.
 */
import { describe, it, expect } from 'vitest'

import {
  BACKEND_ERROR_CATEGORIES,
  MAX_SOURCE_XML_BYTES_UI,
  UPLOAD_OUTCOMES,
  type UploadFiscalDocumentActionResult,
} from '../../frontend/src/lib/fiscal/contract'
import { validateUpload, XML_ACCEPT_HINT } from '../../frontend/src/lib/fiscal/validation'
import {
  interpretResponse,
  RESULTADO_INTERNO,
  RESULTADO_SESION,
} from '../../frontend/src/lib/fiscal/response'
import { messageFor } from '../../frontend/src/lib/fiscal/messages'

// ── §12 · espejo del tamaño ──────────────────────────────────────────────────

describe('tope de tamaño', () => {
  it('espeja los 8 MiB del dominio', () => {
    // AUTORIDAD: MAX_SOURCE_XML_BYTES en backend/app/fiscal/ingestion.py.
    // Este valor es solo para avisar antes de la red.
    expect(MAX_SOURCE_XML_BYTES_UI).toBe(8 * 1024 * 1024)
  })

  it('es MENOR que el sobre de transporte de Next, que son 9 MiB', () => {
    expect(MAX_SOURCE_XML_BYTES_UI).toBeLessThan(9 * 1024 * 1024)
  })
})

// ── §9 · exactamente un fichero ──────────────────────────────────────────────

function formConArchivos(...valores: (File | string)[]): FormData {
  const fd = new FormData()
  for (const v of valores) fd.append('file', v as never)
  return fd
}

const xml = (contenido: string, nombre = 'fe.xml') =>
  new File([contenido], nombre, { type: 'application/xml' })

describe('estructura del formulario', () => {
  it('sin campo file → missing_file', () => {
    const r = validateUpload(new FormData())
    expect(r.ok).toBe(false)
    if (!r.ok) {
      expect(r.failure.code).toBe('missing_file')
      expect(r.failure.category).toBe('invalid_request')
    }
  })

  it('un fichero → continúa', () => {
    const r = validateUpload(formConArchivos(xml('<FacturaElectronica/>')))
    expect(r.ok).toBe(true)
  })

  it('dos ficheros → multiple_files, NUNCA se toma el primero en silencio', () => {
    const r = validateUpload(formConArchivos(xml('<a/>', 'a.xml'), xml('<b/>', 'b.xml')))
    expect(r.ok).toBe(false)
    if (!r.ok) expect(r.failure.code).toBe('multiple_files')
  })

  it('un valor que no es File → invalid_file_field', () => {
    const r = validateUpload(formConArchivos('no soy un fichero'))
    expect(r.ok).toBe(false)
    if (!r.ok) expect(r.failure.code).toBe('invalid_file_field')
  })
})

describe('límites del artefacto', () => {
  it('cero bytes → empty_source_document, no «XML inválido»', () => {
    const r = validateUpload(formConArchivos(new File([], 'vacio.xml')))
    expect(r.ok).toBe(false)
    if (!r.ok) {
      expect(r.failure.code).toBe('empty_source_document')
      expect(r.failure.category).toBe('rejected_before_capture')
    }
  })

  it('exactamente 8 MiB → se acepta', () => {
    const f = new File([new Uint8Array(MAX_SOURCE_XML_BYTES_UI)], 'justo.xml')
    expect(f.size).toBe(MAX_SOURCE_XML_BYTES_UI)
    expect(validateUpload(formConArchivos(f)).ok).toBe(true)
  })

  it('8 MiB + 1 byte → source_document_too_large', () => {
    const f = new File([new Uint8Array(MAX_SOURCE_XML_BYTES_UI + 1)], 'pasado.xml')
    const r = validateUpload(formConArchivos(f))
    expect(r.ok).toBe(false)
    if (!r.ok) expect(r.failure.code).toBe('source_document_too_large')
  })
})

describe('extensión y MIME', () => {
  it('la extensión es una pista del selector, no un filtro', () => {
    expect(XML_ACCEPT_HINT).toContain('.xml')
  })

  it('un comprobante con MIME imperfecto NO se rechaza', () => {
    // El sistema operativo informa el MIME de formas incoherentes. El parser
    // del backend es la autoridad.
    for (const tipo of ['text/xml', 'application/octet-stream', 'text/plain', '']) {
      const f = new File(['<FacturaElectronica/>'], 'fe.xml', { type: tipo })
      expect(validateUpload(formConArchivos(f)).ok).toBe(true)
    }
  })

  it('tampoco se rechaza por la extensión', () => {
    const f = new File(['<FacturaElectronica/>'], 'comprobante.txt')
    expect(validateUpload(formConArchivos(f)).ok).toBe(true)
  })
})

// ── §17-§19 · interpretación de la respuesta ─────────────────────────────────

const OK_200 = {
  status: 'created',
  source_document_id: 'a1b2c3d4-0000-4000-8000-000000000001',
  electronic_document_id: 'a1b2c3d4-0000-4000-8000-000000000002',
}

describe('respuestas de éxito', () => {
  it.each(UPLOAD_OUTCOMES)('200 %s se interpreta como éxito', (estado) => {
    const r = interpretResponse(200, { ...OK_200, status: estado })
    expect(r.ok).toBe(true)
    if (r.ok) {
      expect(r.status).toBe(estado)
      expect(r.sourceDocumentId).toBe(OK_200.source_document_id)
      expect(r.electronicDocumentId).toBe(OK_200.electronic_document_id)
    }
  })

  it('un duplicado exacto NO es un error', () => {
    const r = interpretResponse(200, { ...OK_200, status: 'linked_existing' })
    expect(r.ok).toBe(true)
    expect(messageFor(r).tone).not.toBe('error')
  })

  it('un 200 con forma desconocida no se convierte en éxito inventado', () => {
    expect(interpretResponse(200, { algo: 'raro' })).toEqual(RESULTADO_INTERNO)
  })
})

describe('respuestas de error', () => {
  it.each(BACKEND_ERROR_CATEGORIES)(
    'una categoría %s reconocida NO basta si el código no le corresponde',
    (categoria) => {
      // Antes se aceptaba por reconocer la categoría a secas. La combinación
      // completa -- estado, código, categoría -- es la que manda; el detalle
      // de cada fila vive en `upload-strictness.test.ts`.
      const r = interpretResponse(422, { code: 'codigo_inventado', category: categoria })
      expect(r.ok).toBe(false)
      if (!r.ok) expect(r.category).toBe('internal')
    },
  )

  it('409 clave_conflict → requiere atención, no «inválido» ni «duplicado»', () => {
    const r = interpretResponse(409, {
      code: 'clave_conflict', category: 'requires_review',
      source_document_id: 'sid-409',
    })
    expect(r.ok).toBe(false)
    if (!r.ok) {
      expect(r.category).toBe('requires_review')
      expect(r.sourceDocumentId).toBe('sid-409')
    }
    const m = messageFor(r)
    expect(m.tone).toBe('attention')
    expect(m.title.toLowerCase()).not.toContain('inválido')
    expect(m.title.toLowerCase()).not.toContain('duplicado')
  })

  it('503 conserva el identificador: la evidencia ya existe', () => {
    const r = interpretResponse(503, {
      code: 'persistence_unavailable', category: 'temporary',
      source_document_id: 'sid-503',
    })
    expect(r.ok).toBe(false)
    if (!r.ok) {
      expect(r.category).toBe('temporary')
      expect(r.sourceDocumentId).toBe('sid-503')
    }
    // Y el mensaje no exige volver a subir como única salida.
    expect(messageFor(r).detail).toContain('no hace falta')
  })

  it('500 genérico se queda genérico y sin identificador', () => {
    const r = interpretResponse(500, { code: 'internal_error', category: 'internal' })
    expect(r.ok).toBe(false)
    if (!r.ok) {
      expect(r.category).toBe('internal')
      expect(r.sourceDocumentId).toBeUndefined()
    }
  })

  it('401 se trata como sesión, sin lenguaje técnico de JWT', () => {
    const r = interpretResponse(401, { detail: 'token expired' })
    expect(r).toEqual(RESULTADO_SESION)
    const texto = `${messageFor(r).title} ${messageFor(r).detail}`.toLowerCase()
    for (const tecnico of ['jwt', 'token', 'bearer', 'jwks']) {
      expect(texto).not.toContain(tecnico)
    }
  })

  it('un cuerpo ajeno al contrato no se muestra', () => {
    // El `{"detail": [...]}` de un framework, o el HTML de un proxy.
    expect(interpretResponse(422, { detail: [{ loc: ['x'], msg: 'interno' }] }))
      .toEqual(RESULTADO_INTERNO)
    expect(interpretResponse(502, null)).toEqual(RESULTADO_INTERNO)
  })

  it('conserva el motivo estructurado de unsupported_document', () => {
    const r = interpretResponse(422, {
      code: 'unsupported_document', category: 'not_yet_supported',
      reason: 'unsupported_type', source_document_id: 'sid',
    })
    expect(r.ok).toBe(false)
    if (!r.ok) expect(r.reason).toBe('unsupported_type')
  })
})

// ── §23-§26 · copia mostrada ─────────────────────────────────────────────────

describe('mensajes al usuario', () => {
  const caso = (categoria: string): UploadFiscalDocumentActionResult =>
    ({ ok: false, code: 'x', category: categoria } as UploadFiscalDocumentActionResult)

  it('distingue las tres rutas de documento no soportado', () => {
    const titulos = new Set([
      messageFor(caso('unrecognized')).title,
      messageFor(caso('outside_pipeline')).title,
      messageFor(caso('not_yet_supported')).title,
    ])
    expect(titulos.size).toBe(3)
  })

  it('«todavía no soportado» no culpa al documento del contribuyente', () => {
    const m = messageFor(caso('not_yet_supported'))
    expect(m.detail).toContain('No es un problema de tu archivo')
    expect(m.title.toLowerCase()).not.toContain('inválido')
  })

  it('nunca usa lenguaje del Tax Engine', () => {
    const prohibido = ['deducib', 'crédito de iva', 'retención', 'impuesto a pagar']
    for (const categoria of BACKEND_ERROR_CATEGORIES) {
      const m = messageFor(caso(categoria))
      const texto = `${m.title} ${m.detail}`.toLowerCase()
      for (const p of prohibido) expect(texto).not.toContain(p)
    }
  })

  it('cubre todas las categorías del backend', () => {
    for (const categoria of BACKEND_ERROR_CATEGORIES) {
      const m = messageFor(caso(categoria))
      expect(m.title.length).toBeGreaterThan(0)
      expect(m.detail.length).toBeGreaterThan(0)
    }
  })

  it('ningún mensaje filtra detalle interno', () => {
    const fugas = ['lxml', 'xsd', 'postgres', 'psycopg', 'namespace', 'traceback',
                   'fastapi', 'localhost', 'http://']
    for (const categoria of BACKEND_ERROR_CATEGORIES) {
      const m = messageFor(caso(categoria))
      const texto = `${m.title} ${m.detail}`.toLowerCase()
      for (const f of fugas) expect(texto).not.toContain(f)
    }
  })
})
