/**
 * Contrato de lectura de la bandeja (C3-B3) — módulos puros del frontend.
 *
 * Misma disciplina que la subida: **no se confía en el JSON del backend**. Un
 * ítem con forma imposible no se renderiza deformado; invalida la página,
 * porque media lista es peor que un error honesto — el usuario no sabría qué
 * le falta.
 */
import { describe, it, expect } from 'vitest'

import {
  OPERATIONAL_STATUSES,
  PAGE_SIZE_DEFAULT,
  PAGE_SIZE_MAX,
} from '../../frontend/src/lib/fiscal/inbox-contract'
import {
  interpretInbox,
  LECTURA_INTERNA,
  LECTURA_PROHIBIDA,
  LECTURA_TEMPORAL,
} from '../../frontend/src/lib/fiscal/inbox-response'
import {
  DOCUMENT_TYPE_LABELS,
  INBOX_ERROR_MESSAGES,
  STATUS_LABELS,
  documentTypeLabel,
} from '../../frontend/src/lib/fiscal/inbox-messages'
import { siguientePaginaHref } from '../../frontend/src/lib/fiscal/inbox-navigation'

const EID = 'aaaaaaaa-0000-4000-8000-000000000001'  // v4, variante 8
const SID = 'bbbbbbbb-0000-4000-8000-000000000002'

const documento = (extra: Record<string, unknown> = {}) => ({
  kind: 'document',
  operational_status: 'processed',
  electronic_document_id: EID,
  source_document_id: null,
  received_at: '2026-09-13T10:00:00+00:00',
  receipt_count: 1,
  document_type: 'invoice',
  issued_at_local: '2026-09-12T14:30:00',
  issued_at_offset_minutes: -360,
  consecutive_number: '00100001010000000001',
  currency_code: 'CRC',
  reported_total_document: '1234567.89012',
  ...extra,
})

const recepcion = (extra: Record<string, unknown> = {}) => ({
  kind: 'receipt',
  operational_status: 'invalid_document',
  electronic_document_id: null,
  source_document_id: SID,
  received_at: '2026-09-13T09:00:00+00:00',
  receipt_count: 1,
  document_type: null,
  ...extra,
})

const pagina = (items: unknown[], extra: Record<string, unknown> = {}) => ({
  items,
  next_cursor: null,
  counts: { needs_attention: 0, system_pending: 0 },
  ...extra,
})

// ── forma válida ─────────────────────────────────────────────────────────────

describe('lectura correcta', () => {
  it('interpreta un documento normalizado', () => {
    const r = interpretInbox(200, pagina([documento()]))
    expect(r.ok).toBe(true)
    if (!r.ok) return
    const item = r.page.items[0]
    expect(item.kind).toBe('document')
    expect(item.operationalStatus).toBe('processed')
    if (item.kind !== 'document') return
    expect(item.electronicDocumentId).toBe(EID)
    expect(item.sourceDocumentId).toBeNull()
  })

  it('interpreta una recepción sin normalizar', () => {
    const r = interpretInbox(200, pagina([recepcion()]))
    expect(r.ok).toBe(true)
    if (!r.ok) return
    const item = r.page.items[0]
    expect(item.kind).toBe('receipt')
    if (item.kind !== 'receipt') return
    expect(item.sourceDocumentId).toBe(SID)
    expect(item.electronicDocumentId).toBeNull()
  })

  it('conserva contadores y cursor', () => {
    const r = interpretInbox(200, pagina([], {
      next_cursor: 'Y3Vyc29y', counts: { needs_attention: 3, system_pending: 2 },
    }))
    expect(r.ok).toBe(true)
    if (!r.ok) return
    expect(r.page.counts).toEqual({ needsAttention: 3, systemPending: 2 })
    expect(r.page.nextCursor).toBe('Y3Vyc29y')
  })

  it('una bandeja vacía es una lectura válida, no un error', () => {
    const r = interpretInbox(200, pagina([]))
    expect(r.ok).toBe(true)
    if (r.ok) expect(r.page.items).toEqual([])
  })
})

// ── el decimal exacto ────────────────────────────────────────────────────────

describe('importe reportado', () => {
  it('se conserva como CADENA, con todos sus dígitos', () => {
    // Un valor que delataría cualquier paso por coma flotante binaria.
    const r = interpretInbox(200, pagina([
      documento({ reported_total_document: '9007199254740993.005' }),
    ]))
    expect(r.ok).toBe(true)
    if (!r.ok) return
    const item = r.page.items[0]
    if (item.kind !== 'document') return
    expect(item.reportedTotalDocument).toBe('9007199254740993.005')
    expect(typeof item.reportedTotalDocument).toBe('string')
  })

  it('un importe NUMÉRICO se rechaza: ya habría perdido precisión', () => {
    const r = interpretInbox(200, pagina([
      documento({ reported_total_document: 1234567.89012 }),
    ]))
    expect(r).toEqual(LECTURA_INTERNA)
  })

  it('acepta la ausencia de importe', () => {
    const r = interpretInbox(200, pagina([
      documento({ reported_total_document: null }),
    ]))
    expect(r.ok).toBe(true)
  })
})

// ── formas imposibles ────────────────────────────────────────────────────────

describe('ítems incoherentes', () => {
  const imposibles: [string, unknown][] = [
    ['document sin identificador normalizado',
     documento({ electronic_document_id: null })],
    ['document con identificador de recepción',
     documento({ source_document_id: SID })],
    ['document que no está procesado',
     documento({ operational_status: 'requires_attention' })],
    ['receipt marcado como procesado',
     recepcion({ operational_status: 'processed' })],
    ['receipt sin identificador',
     recepcion({ source_document_id: null })],
    ['receipt con documento normalizado',
     recepcion({ electronic_document_id: EID })],
    ['kind desconocido', recepcion({ kind: 'invoice' })],
    ['estado desconocido', recepcion({ operational_status: 'del_futuro' })],
    ['receipt_count cero', recepcion({ receipt_count: 0 })],
    ['receipt_count no entero', recepcion({ receipt_count: 1.5 })],
    ['sin fecha de recepción', recepcion({ received_at: null })],
  ]

  it.each(imposibles)('%s invalida la página', (_n, item) => {
    expect(interpretInbox(200, pagina([item]))).toEqual(LECTURA_INTERNA)
  })

  it('un solo ítem malo invalida la lista entera', () => {
    // Media lista es peor que un error: el usuario no sabría qué le falta.
    const r = interpretInbox(200, pagina([documento(), { kind: 'x' }, recepcion()]))
    expect(r).toEqual(LECTURA_INTERNA)
  })
})

describe('cuerpos de página inválidos', () => {
  it.each([
    ['sin items', { counts: { needs_attention: 0, system_pending: 0 } }],
    ['items no es lista', pagina({} as never)],
    ['sin contadores', { items: [], next_cursor: null }],
    ['contadores no enteros', pagina([], { counts: { needs_attention: 'tres', system_pending: 0 } })],
    ['contadores negativos', pagina([], { counts: { needs_attention: -1, system_pending: 0 } })],
    ['cursor numérico', pagina([], { next_cursor: 42 })],
    ['cuerpo nulo', null],
    ['cuerpo escalar', 'texto'],
    ['cuerpo array', ['a']],
  ])('%s falla cerrando', (_n, cuerpo) => {
    expect(interpretInbox(200, cuerpo)).toEqual(LECTURA_INTERNA)
  })
})

// ── estados HTTP ─────────────────────────────────────────────────────────────

describe('estados HTTP', () => {
  it('401 y 403 son falta de acceso', () => {
    expect(interpretInbox(401, null)).toEqual(LECTURA_PROHIBIDA)
    expect(interpretInbox(403, { code: 'x' })).toEqual(LECTURA_PROHIBIDA)
  })

  it('503 es temporal', () => {
    expect(interpretInbox(503, { code: 'persistence_unavailable' })).toEqual(LECTURA_TEMPORAL)
  })

  it('422 y 500 son internos para el usuario', () => {
    expect(interpretInbox(422, { code: 'invalid_query' })).toEqual(LECTURA_INTERNA)
    expect(interpretInbox(500, { code: 'internal_error' })).toEqual(LECTURA_INTERNA)
  })
})

// ── copia ────────────────────────────────────────────────────────────────────

describe('copia de la bandeja', () => {
  it('cubre los siete estados con etiquetas distintas', () => {
    const etiquetas = OPERATIONAL_STATUSES.map((s) => STATUS_LABELS[s].label)
    expect(new Set(etiquetas).size).toBe(OPERATIONAL_STATUSES.length)
  })

  it('ningún estado se comunica solo con color', () => {
    for (const s of OPERATIONAL_STATUSES) {
      expect(STATUS_LABELS[s].mark.length).toBeGreaterThan(0)
    }
  })

  it('«no es un comprobante» no se confunde con «inválido»', () => {
    expect(STATUS_LABELS.outside_pipeline.label).not.toContain('inválido')
    expect(STATUS_LABELS.not_yet_supported.label).not.toContain('inválido')
  })

  it('no usa lenguaje tributario ni de ventas/compras', () => {
    const prohibido = ['iva', 'deducib', 'retención', 'impuesto', 'venta',
                       'compra', 'ingreso', 'gasto']
    const textos = [
      ...OPERATIONAL_STATUSES.map((s) => STATUS_LABELS[s].label),
      ...Object.values(DOCUMENT_TYPE_LABELS),
      ...Object.values(INBOX_ERROR_MESSAGES).flatMap((m) => [m.title, m.detail]),
    ]
    for (const t of textos) {
      for (const p of prohibido) expect(t.toLowerCase()).not.toContain(p)
    }
  })

  it('traduce los tipos conocidos y calla ante uno desconocido', () => {
    expect(documentTypeLabel('invoice')).toBe('Factura electrónica')
    expect(documentTypeLabel('hacienda_message')).toBe('Mensaje de Hacienda')
    expect(documentTypeLabel('tipo_del_futuro')).toBeNull()
    expect(documentTypeLabel(null)).toBeNull()
  })

  it('ningún mensaje de error filtra detalle interno', () => {
    const fugas = ['postgres', 'psycopg', 'fastapi', 'http://', 'cursor', 'sql']
    for (const m of Object.values(INBOX_ERROR_MESSAGES)) {
      const t = `${m.title} ${m.detail}`.toLowerCase()
      for (const f of fugas) expect(t).not.toContain(f)
    }
  })
})

describe('tamaños de página', () => {
  it('reflejan el contrato del backend', () => {
    expect(PAGE_SIZE_DEFAULT).toBe(25)
    expect(PAGE_SIZE_MAX).toBe(100)
  })
})

// ── §36-§42 · validación semántica, no «cualquier cadena» ───────────────────

describe('validación semántica de los campos', () => {
  it('un identificador que no es UUID se rechaza', () => {
    for (const malo of ['hello', '', 'aaaa', EID.slice(0, -1), `${EID} `]) {
      expect(interpretInbox(200, pagina([documento({ electronic_document_id: malo })])))
        .toEqual(LECTURA_INTERNA)
      expect(interpretInbox(200, pagina([recepcion({ source_document_id: malo })])))
        .toEqual(LECTURA_INTERNA)
    }
  })

  it('`receivedAt` exige huso: es tiempo del sistema', () => {
    // Sin huso el instante es ambiguo. No confundir con la fecha del
    // comprobante, que sí conserva reloj de pared (ADR-039).
    for (const malo of ['2026-09-13T10:00:00', '13/09/2026', 'ayer', '2026-09-13']) {
      expect(interpretInbox(200, pagina([recepcion({ received_at: malo })])))
        .toEqual(LECTURA_INTERNA)
    }
    for (const bueno of ['2026-09-13T10:00:00Z', '2026-09-13T10:00:00+00:00',
                         '2026-09-13T10:00:00.123456-06:00']) {
      expect(interpretInbox(200, pagina([recepcion({ received_at: bueno })])).ok).toBe(true)
    }
  })

  it('la fecha de emisión se valida SIN convertirla', () => {
    // Convertirla a Date la reinterpretaría en el huso del navegador. La
    // prueba usa una hora que NO EXISTE como instante en los husos con
    // cambio de verano (02:30 del segundo domingo de marzo de 2026 en
    // EE. UU.): `new Date()` la desplazaría; como reloj de pared es válida
    // y debe conservarse LETRA POR LETRA.
    for (const pared of ['2026-09-12T14:30:00', '2026-03-08T02:30:00']) {
      const r = interpretInbox(200, pagina([documento({ issued_at_local: pared })]))
      expect(r.ok).toBe(true)
      if (!r.ok) continue
      const item = r.page.items[0]
      if (item.kind !== 'document') continue
      expect(item.issuedAtLocal).toBe(pared)
    }

    for (const malo of ['2026-09-12T14:30:00Z', 'mañana', '2026-09-12']) {
      expect(interpretInbox(200, pagina([documento({ issued_at_local: malo })])))
        .toEqual(LECTURA_INTERNA)
    }
  })

  it('la fecha de emisión se valida como CALENDARIO, no solo como forma', () => {
    // La gramática sola aceptaba imposibles como `2026-99-99T25:61:61`.
    const imposibles = [
      '2026-99-99T25:61:61',   // el ejemplo del hallazgo
      '2026-02-29T10:00:00',   // 2026 no es bisiesto
      '1900-02-29T10:00:00',   // divisible por 100: tampoco
      '2026-04-31T10:00:00',   // abril tiene 30
      '2026-13-01T10:00:00',   // mes 13
      '2026-00-01T10:00:00',   // mes 0
      '2026-01-00T10:00:00',   // día 0
      '2026-01-32T10:00:00',   // día 32
      '2026-09-12T24:00:00',   // hora 24
      '2026-09-12T14:60:00',   // minuto 60
      '2026-09-12T14:30:60',   // segundo 60
      '2026-09-12T14:30:00.1234567', // el backend emite como mucho 6 dígitos
    ]
    for (const malo of imposibles) {
      expect(interpretInbox(200, pagina([documento({ issued_at_local: malo })])))
        .toEqual(LECTURA_INTERNA)
    }

    const posibles = [
      '2028-02-29T10:00:00',        // 2028 sí es bisiesto
      '2000-02-29T10:00:00',        // divisible por 400: bisiesto
      '2026-12-31T23:59:59',        // los topes exactos de cada componente
      '2026-09-12T14:30:00.5',      // fracción corta
      '2026-09-12T14:30:00.123456', // la fracción que emite `isoformat()`
    ]
    for (const bueno of posibles) {
      const r = interpretInbox(200, pagina([documento({ issued_at_local: bueno })]))
      expect(r.ok).toBe(true)
      if (!r.ok) continue
      const item = r.page.items[0]
      if (item.kind !== 'document') continue
      expect(item.issuedAtLocal).toBe(bueno)
    }
  })

  it('el desplazamiento debe ser un entero de husos reales', () => {
    for (const malo of [1.5, NaN, Infinity, -Infinity, -100000, 10000, '−360']) {
      expect(interpretInbox(200, pagina([documento({ issued_at_offset_minutes: malo })])))
        .toEqual(LECTURA_INTERNA)
    }
    for (const bueno of [-360, 0, 840, -720]) {
      expect(interpretInbox(200, pagina([documento({ issued_at_offset_minutes: bueno })])).ok)
        .toBe(true)
    }
  })

  it('el importe se valida por GRAMÁTICA, sin convertirlo a número', () => {
    for (const malo of ['1,5', '1e5', ' 12', '12 ', 'abc', '-5', '.5', '5.', '']) {
      expect(interpretInbox(200, pagina([documento({ reported_total_document: malo })])))
        .toEqual(LECTURA_INTERNA)
    }
    for (const bueno of ['0', '12', '1234567.89012', '9007199254740993.005']) {
      const r = interpretInbox(200, pagina([documento({ reported_total_document: bueno })]))
      expect(r.ok).toBe(true)
      if (!r.ok) continue
      const item = r.page.items[0]
      if (item.kind !== 'document') continue
      // Se conserva la forma léxica EXACTA, sin renormalizar.
      expect(item.reportedTotalDocument).toBe(bueno)
    }
  })

  it('el cursor se trata como opaco: no se decodifica', () => {
    const r = interpretInbox(200, pagina([], { next_cursor: 'eyJ2IjoxfQ' }))
    expect(r.ok).toBe(true)
    if (r.ok) expect(r.page.nextCursor).toBe('eyJ2IjoxfQ')
    expect(interpretInbox(200, pagina([], { next_cursor: '' }))).toEqual(LECTURA_INTERNA)
  })
})

// ── §45 · navegación de páginas ─────────────────────────────────────────────

describe('navegación a la página siguiente', () => {
  const COMPANY = '11111111-1111-4111-8111-111111111111'

  it('sin nextCursor no hay enlace', () => {
    expect(siguientePaginaHref({ companyId: COMPANY, nextCursor: null })).toBeNull()
  })

  it('con nextCursor apunta al mismo workspace con el cursor en la URL', () => {
    const href = siguientePaginaHref({ companyId: COMPANY, nextCursor: 'Y3Vyc29y' })
    expect(href).toBe(`/app/${COMPANY}?documentCursor=Y3Vyc29y`)
  })

  it('conserva el filtro al pasar de página', () => {
    // Perderlo devolvería al usuario una lista que no pidió.
    const href = siguientePaginaHref({
      companyId: COMPANY, nextCursor: 'Y3Vyc29y', status: 'invalid_document',
    })
    expect(href).toContain('documentCursor=Y3Vyc29y')
    expect(href).toContain('documentStatus=invalid_document')
  })

  it('escapa el cursor para que sea seguro en una URL', () => {
    const href = siguientePaginaHref({ companyId: COMPANY, nextCursor: 'a+b/c=' })
    expect(href).not.toContain('a+b/c=')
    expect(href).toContain(encodeURIComponent('a+b/c='))
  })

  it('es una ruta de la aplicación, nunca del backend', () => {
    const href = siguientePaginaHref({ companyId: COMPANY, nextCursor: 'x' })
    expect(href!.startsWith('/app/')).toBe(true)
    expect(href).not.toContain('http')
    expect(href).not.toContain('fiscal-documents')
  })
})
