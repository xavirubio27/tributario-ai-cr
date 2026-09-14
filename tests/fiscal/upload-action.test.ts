/**
 * Server Action de subida (C3-B2) — reenvío, autenticación y privacidad.
 *
 * Se simula `fetch` y el cliente de Supabase: lo que se prueba aquí es la
 * TRADUCCIÓN y el REENVÍO, no la tubería fiscal, que ya está probada contra
 * PostgreSQL real en el backend (66 tests de endpoint, 1111 en total).
 *
 * Lo que sí importa comprobar de verdad: que los bytes llegan intactos, que la
 * URL y las cabeceras se construyen bien, que el canal de ingesta no lo decide
 * el cliente, que no hay reintentos y que el token no se escapa a ninguna
 * parte.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

const COMPANY = '11111111-1111-4111-8111-111111111111'
const TOKEN = 'ey.TOKEN-DE-PRUEBA.firma'
const BACKEND = 'http://backend.interno:8000'

const claimsOk = { data: { claims: { sub: 'u1' } }, error: null }

let getClaims: ReturnType<typeof vi.fn>
let getSession: ReturnType<typeof vi.fn>
let fetchMock: ReturnType<typeof vi.fn>

// Se simula por el ALIAS, que es como lo importan la acción y el ayudante de
// servidor compartido. Con la ruta relativa el mock no aplicaría: para el
// resolvedor son dos módulos distintos.
vi.mock('@/lib/supabase/server', () => ({
  createClient: async () => ({ auth: { getClaims, getSession } }),
}))
vi.mock('@/lib/auth/session', () => ({
  requireUser: async () => ({ id: 'u1', email: 'u@example.com' }),
}))


async function accion() {
  const m = await import('../../frontend/src/lib/fiscal/actions')
  return m.uploadFiscalDocumentAction
}

/**
 * Rutas cuya revalidación se pidió.
 *
 * Se importa DINÁMICAMENTE: `vi.resetModules()` reinstancia el grafo en cada
 * test, y una importación estática dejaría al test mirando un array distinto
 * del que usa la acción. (`next/cache` está aliasado a este doble en
 * `vitest.config.ts`.)
 */
async function rutasRevalidadas(): Promise<string[]> {
  const m = await import('../support/next-cache-stub')
  return m.revalidatedPaths
}

function respuesta(status: number, cuerpo: unknown, json = true): Response {
  return {
    status,
    json: async () => {
      if (!json) throw new SyntaxError('no es JSON')
      return cuerpo
    },
  } as Response
}

function formCon(f: File): FormData {
  const fd = new FormData()
  fd.append('file', f)
  return fd
}

const XML = '<FacturaElectronica>…</FacturaElectronica>'

beforeEach(() => {
  vi.resetModules()
  process.env.BACKEND_URL = BACKEND
  getClaims = vi.fn(async () => claimsOk)
  getSession = vi.fn(async () => ({ data: { session: { access_token: TOKEN } } }))
  fetchMock = vi.fn(async () =>
    respuesta(200, {
      status: 'created',
      source_document_id: 'sid-1',
      electronic_document_id: 'eid-1',
    }),
  )
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  vi.unstubAllGlobals()
  delete process.env.BACKEND_URL
})

// ── §15 · construcción de la petición ────────────────────────────────────────

describe('petición al backend', () => {
  it('usa la URL de servidor y el company_id de la ruta', async () => {
    await (await accion())(COMPANY, null, formCon(new File([XML], 'fe.xml')))
    const [url] = fetchMock.mock.calls[0]
    expect(url).toBe(`${BACKEND}/companies/${COMPANY}/fiscal-documents`)
  })

  it('reenvía el Bearer verificado y declara application/xml', async () => {
    await (await accion())(COMPANY, null, formCon(new File([XML], 'fe.xml')))
    const [, init] = fetchMock.mock.calls[0]
    expect(init.method).toBe('POST')
    expect(init.headers.Authorization).toBe(`Bearer ${TOKEN}`)
    expect(init.headers['Content-Type']).toBe('application/xml')
  })

  it('no cachea y no sigue redirecciones con el token adjunto', async () => {
    await (await accion())(COMPANY, null, formCon(new File([XML], 'fe.xml')))
    const [, init] = fetchMock.mock.calls[0]
    expect(init.cache).toBe('no-store')
    expect(init.redirect).toBe('error')
    expect(init.signal).toBeDefined()
  })

  it('§14 · reenvía los BYTES EXACTOS, sin decodificar ni normalizar', async () => {
    // Bytes que delatarían cualquier normalización de texto: CRLF, BOM y un
    // carácter fuera del plano básico.
    const crudo = new Uint8Array([
      0xef, 0xbb, 0xbf, 0x3c, 0x61, 0x3e, 0x0d, 0x0a, 0xf0, 0x9f, 0x93, 0x84,
      0x3c, 0x2f, 0x61, 0x3e,
    ])
    await (await accion())(COMPANY, null, formCon(new File([crudo], 'raro.xml')))
    const [, init] = fetchMock.mock.calls[0]
    const enviado = new Uint8Array(init.body as ArrayBuffer)
    expect(Array.from(enviado)).toEqual(Array.from(crudo))
  })

  it('§21 · el canal NO lo decide el cliente', async () => {
    const fd = formCon(new File([XML], 'fe.xml'))
    fd.append('ingestion_source', 'email')        // intento de inyección
    await (await accion())(COMPANY, null, fd)
    const [url, init] = fetchMock.mock.calls[0]
    expect(String(url)).not.toContain('ingestion_source')
    expect(JSON.stringify(init.headers)).not.toContain('email')
  })
})

// ── §16 · sin reintentos ─────────────────────────────────────────────────────

describe('reintentos', () => {
  it('un fallo de red NO se reintenta: crearía evidencia duplicada', async () => {
    fetchMock.mockRejectedValue(new Error(`no se pudo conectar a ${BACKEND}`))
    const r = await (await accion())(COMPANY, null, formCon(new File([XML], 'fe.xml')))
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(r.ok).toBe(false)
    // INDETERMINADO, no `temporary`: no sabemos si la petición llegó. Decir
    // `temporary` afirmaba que el documento estaba guardado.
    if (!r.ok) {
      expect(r.category).toBe('indeterminate')
      expect(r.code).toBe('upload_outcome_unknown')
      expect(r.sourceDocumentId).toBeUndefined()
    }
  })

  it('un 503 tampoco se reintenta', async () => {
    fetchMock.mockResolvedValue(
      respuesta(503, { code: 'persistence_unavailable', category: 'temporary',
                       source_document_id: 'sid-503' }),
    )
    const r = await (await accion())(COMPANY, null, formCon(new File([XML], 'fe.xml')))
    expect(fetchMock).toHaveBeenCalledTimes(1)
    if (!r.ok) expect(r.sourceDocumentId).toBe('sid-503')
  })
})

// ── §6/§7 · secuencia de autenticación ───────────────────────────────────────

describe('autenticación', () => {
  it('getClaims establece la identidad ANTES de pedir el token', async () => {
    await (await accion())(COMPANY, null, formCon(new File([XML], 'fe.xml')))
    expect(getClaims).toHaveBeenCalled()
    expect(getClaims.mock.calls[0][0]).toBeUndefined()   // identidad, sin argumento
  })

  it('verifica el token EXACTO que va a reenviar', async () => {
    await (await accion())(COMPANY, null, formCon(new File([XML], 'fe.xml')))
    const verificados = getClaims.mock.calls.map((c) => c[0]).filter(Boolean)
    expect(verificados).toContain(TOKEN)
    const [, init] = fetchMock.mock.calls[0]
    expect(init.headers.Authorization).toBe(`Bearer ${TOKEN}`)
  })

  it('sin identidad verificada no se llama al backend', async () => {
    getClaims = vi.fn(async () => ({ data: null, error: { message: 'x' } }))
    const r = await (await accion())(COMPANY, null, formCon(new File([XML], 'fe.xml')))
    expect(fetchMock).not.toHaveBeenCalled()
    expect(r.ok).toBe(false)
  })

  it('si el token exacto no verifica, no se reenvía', async () => {
    getClaims = vi.fn(async (jwt?: string) =>
      jwt ? { data: null, error: { message: 'inválido' } } : claimsOk)
    const r = await (await accion())(COMPANY, null, formCon(new File([XML], 'fe.xml')))
    expect(fetchMock).not.toHaveBeenCalled()
    expect(r.ok).toBe(false)
  })

  it('sin sesión no hay token que reenviar', async () => {
    getSession = vi.fn(async () => ({ data: { session: null } }))
    const r = await (await accion())(COMPANY, null, formCon(new File([XML], 'fe.xml')))
    expect(fetchMock).not.toHaveBeenCalled()
    expect(r.ok).toBe(false)
  })
})

// ── §37 · configuración ──────────────────────────────────────────────────────

describe('configuración del backend', () => {
  it('sin BACKEND_URL falla como error interno, sin inventar localhost', async () => {
    delete process.env.BACKEND_URL
    const r = await (await accion())(COMPANY, null, formCon(new File([XML], 'fe.xml')))
    expect(fetchMock).not.toHaveBeenCalled()
    expect(r.ok).toBe(false)
    if (!r.ok) {
      expect(r.category).toBe('internal')
      expect(JSON.stringify(r)).not.toContain('localhost')
    }
  })
})

// ── §4 · company_id ──────────────────────────────────────────────────────────

describe('identificador de empresa', () => {
  it('uno que no es UUID se corta antes de la red', async () => {
    const r = await (await accion())('no-soy-uuid', null, formCon(new File([XML], 'f.xml')))
    expect(fetchMock).not.toHaveBeenCalled()
    if (!r.ok) expect(r.category).toBe('invalid_request')
  })

  it('un UUID de otra empresa SÍ se envía: decide RLS, no el navegador', async () => {
    fetchMock.mockResolvedValue(
      respuesta(403, { code: 'fiscal_write_forbidden', category: 'forbidden' }),
    )
    const otra = '22222222-2222-4222-8222-222222222222'
    const r = await (await accion())(otra, null, formCon(new File([XML], 'f.xml')))
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(String(fetchMock.mock.calls[0][0])).toContain(otra)
    if (!r.ok) expect(r.category).toBe('forbidden')
  })
})

// ── §19 · respuestas anómalas ────────────────────────────────────────────────

describe('respuestas anómalas', () => {
  it('un cuerpo que no es JSON no rompe la acción', async () => {
    fetchMock.mockResolvedValue(respuesta(502, '<html>Bad Gateway</html>', false))
    const r = await (await accion())(COMPANY, null, formCon(new File([XML], 'f.xml')))
    expect(r.ok).toBe(false)
    if (!r.ok) expect(r.category).toBe('internal')
  })

  it('un timeout es INDETERMINADO: el backend pudo haber capturado', async () => {
    fetchMock.mockRejectedValue(new DOMException('The operation was aborted', 'TimeoutError'))
    const r = await (await accion())(COMPANY, null, formCon(new File([XML], 'f.xml')))
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(r.ok).toBe(false)
    if (!r.ok) expect(r.category).toBe('indeterminate')
  })

  it('un 503 CONFIRMADO sigue siendo temporary, con su identificador', async () => {
    // Distinto del anterior a propósito: aquí el backend sí nos dijo algo.
    fetchMock.mockResolvedValue(
      respuesta(503, { code: 'persistence_unavailable', category: 'temporary',
                       source_document_id: 'sid-503' }),
    )
    const r = await (await accion())(COMPANY, null, formCon(new File([XML], 'f.xml')))
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(r.ok).toBe(false)
    if (!r.ok) {
      expect(r.category).toBe('temporary')
      expect(r.sourceDocumentId).toBe('sid-503')
    }
  })
})

// ── §42 · privacidad del token y de la infraestructura ───────────────────────

describe('privacidad', () => {
  const escenarios: [string, () => void][] = [
    ['red caída', () => fetchMock.mockRejectedValue(
      new Error(`connect ECONNREFUSED ${BACKEND} con Bearer ${TOKEN}`))],
    ['500 del backend', () => fetchMock.mockResolvedValue(
      respuesta(500, { code: 'internal_error', category: 'internal' }))],
    ['401 del backend', () => fetchMock.mockResolvedValue(
      respuesta(401, { detail: `token ${TOKEN} expirado` }))],
    ['cuerpo no JSON', () => fetchMock.mockResolvedValue(
      respuesta(502, `proxy ${BACKEND}`, false))],
  ]

  it.each(escenarios)('el resultado de %s no filtra token ni URL', async (_n, montar) => {
    montar()
    const r = await (await accion())(COMPANY, null, formCon(new File([XML], 'f.xml')))
    const serializado = JSON.stringify(r)
    expect(serializado).not.toContain(TOKEN)
    expect(serializado).not.toContain(BACKEND)
    expect(serializado.toLowerCase()).not.toContain('bearer')
    expect(serializado.toLowerCase()).not.toContain('authorization')
  })

  it('el resultado de éxito tampoco los lleva', async () => {
    const r = await (await accion())(COMPANY, null, formCon(new File([XML], 'f.xml')))
    const s = JSON.stringify(r)
    expect(s).not.toContain(TOKEN)
    expect(s).not.toContain(BACKEND)
  })
})


// ── §48 · refresco de la bandeja ─────────────────────────────────────────────

describe('refresco de la bandeja tras subir', () => {
  it('un éxito refresca el workspace', async () => {
    await (await accion())(COMPANY, null, formCon(new File([XML], 'fe.xml')))
    expect(await rutasRevalidadas()).toContain(`/app/${COMPANY}`)
  })

  it('un fallo POSTERIOR a la captura también refresca', async () => {
    // La evidencia existe: el usuario debe verla aparecer en la bandeja. Si
    // solo se refrescara el éxito, la lista quedaría vieja justo en los casos
    // que hay que revisar.
    fetchMock.mockResolvedValue(
      respuesta(422, { code: 'xsd_validation_error', category: 'invalid_document',
                       source_document_id: 'sid-1' }),
    )
    await (await accion())(COMPANY, null, formCon(new File([XML], 'fe.xml')))
    expect(await rutasRevalidadas()).toContain(`/app/${COMPANY}`)
  })

  it('un 409 de conflicto de clave refresca', async () => {
    fetchMock.mockResolvedValue(
      respuesta(409, { code: 'clave_conflict', category: 'requires_review',
                       source_document_id: 'sid-2' }),
    )
    await (await accion())(COMPANY, null, formCon(new File([XML], 'fe.xml')))
    expect(await rutasRevalidadas()).toHaveLength(1)
  })

  it('un rechazo PREVIO a la captura no refresca: no hay nada nuevo', async () => {
    const fd = new FormData()          // sin fichero
    await (await accion())(COMPANY, null, fd)
    expect(await rutasRevalidadas()).toEqual([])
  })

  it('un resultado indeterminado no refresca: no hay identificador fiable', async () => {
    fetchMock.mockRejectedValue(new Error('red caída'))
    await (await accion())(COMPANY, null, formCon(new File([XML], 'f.xml')))
    expect(await rutasRevalidadas()).toEqual([])
  })
})
