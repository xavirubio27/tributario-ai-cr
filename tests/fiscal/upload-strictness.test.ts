/**
 * Contrato estricto y certeza del transporte (C3-B2-R1).
 *
 * DOS PROPIEDADES, Y LAS DOS SON DE HONESTIDAD
 *
 * 1. Una respuesta CONTRADICTORIA no se interpreta. Reconocer una categoría no
 *    basta: un 409 con cuerpo de éxito o un 500 con `invalid_document` son
 *    afirmaciones que nadie hizo, y mostrarlas sería inventar.
 *
 * 2. No saber qué pasó NO es lo mismo que saber que se guardó. Un `fetch`
 *    rechazado y un 503 confirmado decían lo mismo, y el mensaje afirmaba
 *    «guardamos el documento» sin que nadie lo hubiera confirmado.
 */
import { describe, it, expect } from 'vitest'

import {
  interpretResponse,
  RESULTADO_INDETERMINADO,
  RESULTADO_INTERNO,
  RESULTADO_SESION,
} from '../../frontend/src/lib/fiscal/response'
import { messageFor } from '../../frontend/src/lib/fiscal/messages'
import { resultadoVisible } from '../../frontend/src/lib/fiscal/display'
import type { UploadFiscalDocumentActionResult } from '../../frontend/src/lib/fiscal/contract'

const SID = 'aaaaaaaa-0000-4000-8000-000000000001'
const EID = 'bbbbbbbb-0000-4000-8000-000000000002'
const exito = (status = 'created') => ({
  status, source_document_id: SID, electronic_document_id: EID,
})

// ── §9 · el éxito exige su contrato completo ─────────────────────────────────

describe('contrato de éxito', () => {
  it('200 con cuerpo válido es éxito', () => {
    expect(interpretResponse(200, exito()).ok).toBe(true)
  })

  it('200 con cuerpo de ERROR no se convierte en éxito', () => {
    expect(interpretResponse(200, {
      code: 'malformed_xml', category: 'invalid_document', source_document_id: SID,
    })).toEqual(RESULTADO_INTERNO)
  })

  it('200 con estado desconocido falla cerrando', () => {
    expect(interpretResponse(200, exito('procesado_quizas'))).toEqual(RESULTADO_INTERNO)
  })

  it('200 sin identificador falla cerrando: no se fabrica', () => {
    expect(interpretResponse(200, {
      status: 'created', electronic_document_id: EID,
    })).toEqual(RESULTADO_INTERNO)
    expect(interpretResponse(200, {
      status: 'created', source_document_id: SID,
    })).toEqual(RESULTADO_INTERNO)
  })

  it('un cuerpo de éxito bajo un estado de error NO es éxito', () => {
    for (const estado of [409, 500, 503, 422]) {
      expect(interpretResponse(estado, exito())).toEqual(RESULTADO_INTERNO)
    }
  })
})

// ── §10/§11 · la matriz valida la combinación completa ───────────────────────

describe('matriz estricta', () => {
  const validos: [number, string, string, boolean][] = [
    [413, 'source_document_too_large', 'rejected_before_capture', false],
    [422, 'empty_source_document', 'rejected_before_capture', false],
    [422, 'invalid_request', 'invalid_request', false],
    [422, 'malformed_xml', 'invalid_document', true],
    [422, 'xsd_validation_error', 'invalid_document', true],
    [422, 'semantic_parse_error', 'invalid_document', true],
    [409, 'clave_conflict', 'requires_review', true],
    [404, 'source_document_not_found', 'not_found', true],
    [503, 'persistence_unavailable', 'temporary', true],
    [500, 'internal_error', 'internal', false],
  ]

  it.each(validos)('%i %s / %s se acepta', (status, code, category, conId) => {
    const cuerpo: Record<string, unknown> = { code, category }
    if (conId) cuerpo.source_document_id = SID
    const r = interpretResponse(status, cuerpo)
    expect(r.ok).toBe(false)
    if (!r.ok) {
      expect(r.code).toBe(code)
      expect(r.category).toBe(category)
      expect(r.sourceDocumentId).toBe(conId ? SID : undefined)
    }
  })

  it('un código conocido bajo el estado equivocado falla cerrando', () => {
    // clave_conflict es 409; con 422 es una contradicción.
    expect(interpretResponse(422, {
      code: 'clave_conflict', category: 'requires_review', source_document_id: SID,
    })).toEqual(RESULTADO_INTERNO)
  })

  it('una categoría que no corresponde al código falla cerrando', () => {
    expect(interpretResponse(500, {
      code: 'internal_error', category: 'invalid_document',
    })).toEqual(RESULTADO_INTERNO)
    expect(interpretResponse(422, {
      code: 'malformed_xml', category: 'requires_review', source_document_id: SID,
    })).toEqual(RESULTADO_INTERNO)
  })

  it('un código desconocido falla cerrando, aunque la categoría exista', () => {
    expect(interpretResponse(422, {
      code: 'future_new_error', category: 'invalid_document', source_document_id: SID,
    })).toEqual(RESULTADO_INTERNO)
  })

  it('una categoría desconocida falla cerrando', () => {
    expect(interpretResponse(422, {
      code: 'malformed_xml', category: 'categoria_del_futuro', source_document_id: SID,
    })).toEqual(RESULTADO_INTERNO)
  })

  it('falta el identificador donde el contrato lo garantiza → falla cerrando', () => {
    for (const [status, code, category] of [
      [409, 'clave_conflict', 'requires_review'],
      [503, 'persistence_unavailable', 'temporary'],
      [422, 'malformed_xml', 'invalid_document'],
    ] as [number, string, string][]) {
      expect(interpretResponse(status, { code, category })).toEqual(RESULTADO_INTERNO)
    }
  })

  it('un identificador donde NO debería estar → falla cerrando', () => {
    // El 500 se devuelve deliberadamente mudo.
    expect(interpretResponse(500, {
      code: 'internal_error', category: 'internal', source_document_id: SID,
    })).toEqual(RESULTADO_INTERNO)
  })

  it('403 acepta identificador o su ausencia: nace en T1 y en T2', () => {
    const sin = interpretResponse(403, {
      code: 'fiscal_write_forbidden', category: 'forbidden',
    })
    const con = interpretResponse(403, {
      code: 'fiscal_write_forbidden', category: 'forbidden', source_document_id: SID,
    })
    expect(sin.ok).toBe(false)
    expect(con.ok).toBe(false)
    if (!sin.ok) expect(sin.sourceDocumentId).toBeUndefined()
    if (!con.ok) expect(con.sourceDocumentId).toBe(SID)
  })
})

describe('unsupported_document', () => {
  const motivos: [string, string][] = [
    ['unknown_document', 'unrecognized'],
    ['outside_pipeline', 'outside_pipeline'],
    ['unsupported_type', 'not_yet_supported'],
  ]

  it.each(motivos)('reason %s → categoría %s', (reason, category) => {
    const r = interpretResponse(422, {
      code: 'unsupported_document', category, reason, source_document_id: SID,
    })
    expect(r.ok).toBe(false)
    if (!r.ok) {
      expect(r.reason).toBe(reason)
      expect(r.category).toBe(category)
    }
  })

  it('un motivo desconocido falla cerrando', () => {
    expect(interpretResponse(422, {
      code: 'unsupported_document', category: 'unrecognized',
      reason: 'algun_motivo_futuro', source_document_id: SID,
    })).toEqual(RESULTADO_INTERNO)
  })

  it('sin motivo falla cerrando', () => {
    expect(interpretResponse(422, {
      code: 'unsupported_document', category: 'unrecognized', source_document_id: SID,
    })).toEqual(RESULTADO_INTERNO)
  })

  it('motivo y categoría que no concuerdan falla cerrando', () => {
    expect(interpretResponse(422, {
      code: 'unsupported_document', category: 'not_yet_supported',
      reason: 'unknown_document', source_document_id: SID,
    })).toEqual(RESULTADO_INTERNO)
  })
})

// ── §7/§14 · respuestas que llegaron pero no se pueden creer ─────────────────

describe('respuestas recibidas pero no confiables', () => {
  it('un cuerpo no JSON es INTERNO, no indeterminado: hubo respuesta', () => {
    expect(interpretResponse(502, null)).toEqual(RESULTADO_INTERNO)
    expect(interpretResponse(502, null)).not.toEqual(RESULTADO_INDETERMINADO)
  })

  it('el {"detail": [...]} de un framework no se muestra', () => {
    expect(interpretResponse(422, { detail: [{ loc: ['body'], msg: 'interno' }] }))
      .toEqual(RESULTADO_INTERNO)
  })

  it('un array o un escalar fallan cerrando', () => {
    expect(interpretResponse(422, ['x'])).toEqual(RESULTADO_INTERNO)
    expect(interpretResponse(422, 'texto')).toEqual(RESULTADO_INTERNO)
  })

  it('401 se resuelve por ESTADO y su cuerpo nunca se mira', () => {
    // No usa UploadError: es un HTTPException con `detail`.
    expect(interpretResponse(401, { detail: 'token caducado' })).toEqual(RESULTADO_SESION)
    expect(interpretResponse(401, null)).toEqual(RESULTADO_SESION)
  })
})

// ── §2-§5 · certeza: lo confirmado frente a lo desconocido ───────────────────

describe('503 confirmado frente a transporte incierto', () => {
  const confirmado = interpretResponse(503, {
    code: 'persistence_unavailable', category: 'temporary', source_document_id: SID,
  })

  it('son categorías DISTINTAS', () => {
    expect(confirmado.ok).toBe(false)
    if (!confirmado.ok) expect(confirmado.category).toBe('temporary')
    expect(RESULTADO_INDETERMINADO.ok).toBe(false)
    if (!RESULTADO_INDETERMINADO.ok) {
      expect(RESULTADO_INDETERMINADO.category).toBe('indeterminate')
      expect(RESULTADO_INDETERMINADO.code).toBe('upload_outcome_unknown')
    }
  })

  it('el 503 confirmado conserva el identificador; el indeterminado no tiene ninguno', () => {
    if (!confirmado.ok) expect(confirmado.sourceDocumentId).toBe(SID)
    if (!RESULTADO_INDETERMINADO.ok) {
      expect(RESULTADO_INDETERMINADO.sourceDocumentId).toBeUndefined()
    }
  })

  it('solo el confirmado afirma que se guardó el documento', () => {
    expect(messageFor(confirmado).detail).toContain('Guardamos el documento')
  })

  it('el indeterminado NO afirma que se guardó', () => {
    const m = messageFor(RESULTADO_INDETERMINADO)
    const texto = `${m.title} ${m.detail}`
    expect(texto).not.toContain('Guardamos el documento')
    expect(texto.toLowerCase()).not.toContain('lo guardamos')
  })

  it('el indeterminado TAMPOCO afirma que no llegó', () => {
    const texto = messageFor(RESULTADO_INDETERMINADO).detail.toLowerCase()
    expect(texto).not.toContain('no fue recibido')
    expect(texto).not.toContain('no llegó')
    expect(texto).not.toContain('no se recibió')
  })

  it('el indeterminado admite que PUEDE haber llegado', () => {
    expect(messageFor(RESULTADO_INDETERMINADO).detail).toContain('Puede que sí')
  })

  it('el indeterminado no manda resubir a ciegas', () => {
    const texto = messageFor(RESULTADO_INDETERMINADO).detail.toLowerCase()
    expect(texto).toContain('revisa antes')
  })

  it('sus mensajes son visiblemente distintos', () => {
    expect(messageFor(confirmado).title)
      .not.toBe(messageFor(RESULTADO_INDETERMINADO).title)
  })
})

// ── §24 · las categorías siguen distinguiéndose ──────────────────────────────

describe('copia', () => {
  it('los nueve desenlaces tienen títulos distinguibles', () => {
    const casos: UploadFiscalDocumentActionResult[] = [
      { ok: true, status: 'created', sourceDocumentId: SID, electronicDocumentId: EID },
      { ok: true, status: 'linked_existing', sourceDocumentId: SID, electronicDocumentId: EID },
      { ok: false, code: 'clave_conflict', category: 'requires_review' },
      { ok: false, code: 'unsupported_document', category: 'not_yet_supported' },
      { ok: false, code: 'unsupported_document', category: 'outside_pipeline' },
      { ok: false, code: 'malformed_xml', category: 'invalid_document' },
      { ok: false, code: 'persistence_unavailable', category: 'temporary' },
      RESULTADO_INDETERMINADO,
      RESULTADO_INTERNO,
    ]
    const titulos = casos.map((c) => messageFor(c).title)
    // `created` y `linked_existing` difieren; el resto también entre sí.
    expect(new Set(titulos).size).toBe(titulos.length)
  })

  it('ningún mensaje filtra detalle interno', () => {
    const fugas = ['lxml', 'xsd', 'postgres', 'traceback', 'fetch', 'http://', 'abort']
    for (const cat of ['indeterminate', 'internal', 'temporary'] as const) {
      const m = messageFor({ ok: false, code: 'x', category: cat })
      const texto = `${m.title} ${m.detail}`.toLowerCase()
      for (const f of fugas) expect(texto).not.toContain(f)
    }
  })
})

// ── §20-§22 · el resultado anterior no describe el archivo nuevo ─────────────

describe('resultado obsoleto al cambiar de archivo', () => {
  const exitoA: UploadFiscalDocumentActionResult = {
    ok: true, status: 'created', sourceDocumentId: SID, electronicDocumentId: EID,
  }
  const errorA: UploadFiscalDocumentActionResult = {
    ok: false, code: 'malformed_xml', category: 'invalid_document', sourceDocumentId: SID,
  }

  it('tras enviar, el resultado de ESE envío se muestra', () => {
    expect(resultadoVisible(exitoA, true, false)).toBe(exitoA)
  })

  it('al elegir otro archivo, un ÉXITO anterior deja de mostrarse', () => {
    // Si no, «Procesado correctamente» quedaría junto al nombre del archivo
    // nuevo, pareciendo describirlo.
    expect(resultadoVisible(exitoA, false, false)).toBeNull()
  })

  it('al elegir otro archivo, un ERROR anterior deja de mostrarse', () => {
    expect(resultadoVisible(errorA, false, false)).toBeNull()
  })

  it('elegir archivo sin resultado previo se comporta normal', () => {
    expect(resultadoVisible(null, false, false)).toBeNull()
    expect(resultadoVisible(null, true, false)).toBeNull()
  })

  it('el ciclo completo: subir A, elegir B, subir B', () => {
    const exitoB: UploadFiscalDocumentActionResult = {
      ok: false, code: 'clave_conflict', category: 'requires_review', sourceDocumentId: 'sid-b',
    }
    expect(resultadoVisible(exitoA, true, false)).toBe(exitoA)   // A subido
    expect(resultadoVisible(exitoA, false, false)).toBeNull()    // B seleccionado
    expect(resultadoVisible(exitoA, true, true)).toBeNull()      // B enviándose
    expect(resultadoVisible(exitoB, true, false)).toBe(exitoB)   // B completado
  })

  it('mientras B se envía, el ÉXITO de A no reaparece', () => {
    // `useActionState` conserva el resultado de A hasta que la acción nueva
    // termina, y `frescoParaEsteEnvio` vuelve a `true` al enviar. Sin la
    // condición de envío en curso, el aviso de A reaparecía describiendo a B.
    expect(resultadoVisible(exitoA, true, true)).toBeNull()
  })

  it('mientras B se envía, el ERROR de A no reaparece', () => {
    expect(resultadoVisible(errorA, true, true)).toBeNull()
  })

  it('el primer envío tampoco muestra nada mientras está en curso', () => {
    expect(resultadoVisible(null, true, true)).toBeNull()
  })

  it('completado el envío, el resultado nuevo se muestra con normalidad', () => {
    const resultadoB: UploadFiscalDocumentActionResult = {
      ok: false, code: 'malformed_xml', category: 'invalid_document',
      sourceDocumentId: 'sid-b',
    }
    expect(resultadoVisible(resultadoB, true, true)).toBeNull()    // en curso
    expect(resultadoVisible(resultadoB, true, false)).toBe(resultadoB)
  })
})
