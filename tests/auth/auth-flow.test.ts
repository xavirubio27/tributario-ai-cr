/**
 * Checkpoint E — flujo de autenticación.
 *
 * ALCANCE Y LÍMITE (leer antes de confiar en estos tests)
 *
 *   Los casos se dividen en dos niveles, deliberadamente:
 *
 *   [HTTP]   Peticiones reales al servidor de Next.js. Prueban el proxy, el
 *            enrutado y la protección server-side tal y como las ve un navegador.
 *
 *   [AUTH]   Llamadas a Supabase Auth con la misma librería y los mismos métodos
 *            que usan las Server Actions. Prueban la mecánica de sesión.
 *
 *   NO se invoca el protocolo de Server Actions de Next.js por HTTP: requiere un
 *   identificador de acción que se genera en cada build, y acoplarse a él daría
 *   tests frágiles. Cubrir ese hueco corresponde a una suite de navegador
 *   (Playwright), que sería infraestructura desproporcionada en este punto.
 *
 * Sin service_role, sin secret key, sin Admin API.
 */
import path from 'node:path'
import fs from 'node:fs'
import { fileURLToPath } from 'node:url'
import { config } from 'dotenv'
import { type SupabaseClient } from '@supabase/supabase-js'
import { beforeAll, describe, expect, it } from 'vitest'
import {
  newClient as makeClient,
  requireAppServer,
  signInOrFail,
  signUpOrFail,
} from '../support/harness'

const here = path.dirname(fileURLToPath(import.meta.url))
config({ path: path.resolve(here, '..', '.env.local') })

const SUPABASE_URL = process.env.SUPABASE_URL ?? ''
const SUPABASE_PUBLISHABLE_KEY = process.env.SUPABASE_PUBLISHABLE_KEY ?? ''
const APP_URL = process.env.APP_URL ?? 'http://localhost:3000'

if (!SUPABASE_URL || !SUPABASE_PUBLISHABLE_KEY) {
  throw new Error('Faltan SUPABASE_URL o SUPABASE_PUBLISHABLE_KEY en tests/.env.local')
}

function newClient(): SupabaseClient {
  return makeClient(SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY)
}

const runId = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`
/**
 * Usuario COMPARTIDO: prerrequisito de los casos C, D, E y F.
 * Se registra en el hook del describe anidado, no dentro de un `it`.
 */
const SHARED_USER = { email: `auth-shared-${runId}@example.com`, password: `PwE-${runId}-x9` }

/**
 * Usuario propio del caso B. El signup es EL COMPORTAMIENTO BAJO PRUEBA en ese
 * caso, así que se mantiene dentro del test y con su propio usuario: si el signup
 * se rompiera, B debe FALLAR como test, no degradarse a un error de setup.
 */
const SIGNUP_PROBE_USER = { email: `auth-signup-${runId}@example.com`, password: `PwB-${runId}-x9` }

/** Identidad del usuario compartido, verificada por el hook. */
let sharedUserId = ''

beforeAll(async () => {
  await requireAppServer(APP_URL)
}, 30_000)

describe('Checkpoint E — autenticación', () => {
  it('[HTTP] A. usuario no autenticado en ruta protegida -> redirige a /login', async () => {
    const res = await fetch(`${APP_URL}/app`, { redirect: 'manual' })
    expect([302, 303, 307, 308]).toContain(res.status)
    expect(res.headers.get('location') ?? '').toContain('/login')
  })

  it('[HTTP] rutas públicas accesibles sin sesión', async () => {
    for (const route of ['/', '/login', '/signup']) {
      const res = await fetch(`${APP_URL}${route}`, { redirect: 'manual' })
      expect(res.status, `ruta ${route}`).toBe(200)
    }
  })

  it('[HTTP] el proxy no rompe los assets estáticos excluidos del matcher', async () => {
    const res = await fetch(`${APP_URL}/favicon.ico`, { redirect: 'manual' })
    expect(res.status).toBeLessThan(500)
  })

  it('[AUTH] B. signup correcto -> usuario autenticado', async () => {
    const client = newClient()
    const { data, error } = await client.auth.signUp(SIGNUP_PROBE_USER)
    expect(error).toBeNull()
    // enable_confirmations = false en DEVELOPMENT (ADR-019) -> sesión inmediata.
    expect(data.session).not.toBeNull()
    expect(data.user?.email).toBe(SIGNUP_PROBE_USER.email)

    const { data: claims } = await client.auth.getClaims()
    expect(claims?.claims?.sub).toBe(data.user?.id)
  })

  describe('con un usuario ya registrado', () => {
    /**
     * PRERREQUISITO COMPARTIDO (bloqueante final de la auditoría Codex).
     *
     * Antes, el usuario de estos cuatro casos lo creaba el caso B. Si aquel
     * signup fallaba -- por ejemplo por el límite de tasa de Auth -- Vitest
     * seguía ejecutando C, D, E y F contra un usuario inexistente y producía
     * fallos en cascada que ocultaban la causa.
     *
     * Ahora vive en un hook: si falla, estos cuatro casos NO se ejecutan,
     * `signUpOrFail` deja visible el error original y conserva el diagnóstico de
     * rate limit. Los casos que no dependen de este usuario (A, B, G, H, I) siguen
     * ejecutándose: el hook es de este describe anidado, no de todo el archivo.
     *
     * Un solo signup para los cuatro casos: no se multiplica el consumo de cuota.
     */
    beforeAll(async () => {
      sharedUserId = await signUpOrFail(
        newClient(),
        SHARED_USER,
        'usuario compartido de la suite Auth',
      )
    }, 60_000)

    it('[AUTH] C. logout -> sesión eliminada', async () => {
      const client = newClient()
      await signInOrFail(client, SHARED_USER, 'usuario de prueba (caso C)')

      const { data: before } = await client.auth.getClaims()
      expect(before?.claims?.sub).toBeTruthy()

      const { error } = await client.auth.signOut()
      expect(error).toBeNull()

      const { data: after } = await client.auth.getClaims()
      expect(after?.claims).toBeUndefined()
    })

    it('[AUTH] D. login correcto -> sesión recuperada', async () => {
      const client = newClient()
      const { data, error } = await client.auth.signInWithPassword(SHARED_USER)
      expect(error).toBeNull()
      expect(data.session).not.toBeNull()
      expect(data.user?.email).toBe(SHARED_USER.email)
    })

    it('[AUTH] E. identidad verificable con getClaims() tras login', async () => {
      // Es exactamente la comprobación que hace la página protegida vía requireUser().
      const client = newClient()
      await signInOrFail(client, SHARED_USER, 'usuario de prueba (caso E)')

      const { data, error } = await client.auth.getClaims()
      expect(error).toBeNull()
      expect(data?.claims?.sub).toBe(sharedUserId)
      expect(data?.claims?.email).toBe(SHARED_USER.email)
      expect(data?.claims?.role).toBe('authenticated')
    })

    it('[AUTH] F. contraseña incorrecta -> acceso denegado', async () => {
      const client = newClient()
      const { data, error } = await client.auth.signInWithPassword({
        email: SHARED_USER.email,
        password: `${SHARED_USER.password}-incorrecta`,
      })
      expect(error).not.toBeNull()
      expect(data.session).toBeNull()

      const { data: claims } = await client.auth.getClaims()
      expect(claims?.claims).toBeUndefined()
    })

  })

  it('[STATIC] H. signOutAction comprueba el resultado y no finge éxito', () => {
    const src = fs.readFileSync(
      path.resolve(here, '..', '..', 'frontend', 'src', 'lib', 'auth', 'actions.ts'),
      'utf8',
    )
    const code = src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|\s)\/\/.*$/gm, '')
    const body = code.slice(code.indexOf('export async function signOutAction'))

    // El resultado de signOut() debe capturarse...
    expect(body).toMatch(/const\s*\{\s*error\s*\}\s*=\s*await\s+supabase\.auth\.signOut\(\)/)
    // ...y ramificarse antes de redirigir.
    const errorBranch = body.indexOf('if (error)')
    const redirectAt = body.indexOf("redirect('/login')")
    expect(errorBranch).toBeGreaterThan(-1)
    expect(errorBranch).toBeLessThan(redirectAt)
  })

  it('[HTTP] I. las rutas de sesión no se sirven como cacheables públicamente', async () => {
    // Medido: Next.js fija `no-cache, must-revalidate` en rutas dinámicas y
    // sobrescribe lo que fije el proxy o next.config. Lo mínimo exigible es que
    // NINGUNA respuesta sea cacheable sin revalidar.
    for (const route of ['/', '/login', '/signup', '/app']) {
      const res = await fetch(`${APP_URL}${route}`, { redirect: 'manual' })
      const cc = (res.headers.get('cache-control') ?? '').toLowerCase()
      expect(cc, `ruta ${route}`).toMatch(/no-store|no-cache/)
      expect(cc, `ruta ${route} no debe declararse public`).not.toContain('public')
      expect(cc, `ruta ${route} no debe tener max-age positivo`).not.toMatch(/max-age=[1-9]/)
    }
  })

  it('G. el build no contiene secret key ni credenciales service_role', () => {
    const buildDir = path.resolve(here, '..', '..', 'frontend', '.next')
    expect(fs.existsSync(buildDir), 'no existe frontend/.next; ejecuta el build antes').toBe(true)

    // Se buscan CREDENCIALES, no palabras: el literal `sb_secret_` aparece en los
    // comentarios JSDoc de @supabase/auth-js ("sb_publishable_… / sb_secret_…").
    const SECRET_KEY = /sb_secret_[A-Za-z0-9]{10,}/
    const JWT = /eyJ[A-Za-z0-9_-]{15,}\.([A-Za-z0-9_-]{15,})\.[A-Za-z0-9_-]{10,}/g

    /**
     * Decodifica el payload de un JWT.
     *
     * CORRECCIÓN (auditoría Codex): la versión anterior hacía `b64url.slice(3)`
     * para "saltar" el prefijo `eyJ`. Eso desalinea el base64url y produce basura,
     * de modo que el detector NUNCA encontraba `service_role`: un falso negativo
     * silencioso. El segmento completo ES el base64url y no debe recortarse.
     */
    const decodePayload = (b64url: string): string => {
      try {
        return Buffer.from(b64url, 'base64url').toString('utf8')
      } catch {
        return ''
      }
    }

    const hasServiceRoleJwt = (text: string): boolean => {
      for (const match of text.matchAll(JWT)) {
        let payload: unknown
        try {
          payload = JSON.parse(decodePayload(match[1]))
        } catch {
          continue // segmento malformado: no es un JWT utilizable
        }
        if (
          payload !== null &&
          typeof payload === 'object' &&
          (payload as { role?: unknown }).role === 'service_role'
        ) {
          return true
        }
      }
      return false
    }

    // ── Autotests del detector ────────────────────────────────────────────────
    // Sin ellos el caso podría pasar por no detectar nada. Todos los JWT son
    // SINTÉTICOS y con firma falsa: nunca se usa una credencial real.
    const makeJwt = (payload: Record<string, unknown>): string => {
      const b64 = (o: unknown) => Buffer.from(JSON.stringify(o)).toString('base64url')
      return `${b64({ alg: 'HS256', typ: 'JWT' })}.${b64(payload)}.ZmFrZS1zaWduYXR1cmU`
    }

    // positivo: JWT sintético con role service_role -> debe detectarse
    expect(hasServiceRoleJwt(makeJwt({ iss: 'supabase', role: 'service_role', exp: 1 }))).toBe(true)
    // negativo: JWT sintético legítimo de cliente -> NO debe detectarse
    expect(hasServiceRoleJwt(makeJwt({ iss: 'supabase', role: 'authenticated', exp: 1 }))).toBe(false)
    // negativo: la cadena "service_role" fuera de un JWT no cuenta
    expect(hasServiceRoleJwt('const SUPABASE_SERVICE_ROLE_KEY = "service_role"')).toBe(false)
    // malformado: tiene forma de JWT pero el payload no es base64/JSON válido
    expect(hasServiceRoleJwt('eyJhbGciOiJIUzI1NiJ9.!!!no-es-base64!!!.ZmFrZXNpZ25hdHVyZQ')).toBe(false)
    expect(hasServiceRoleJwt('eyJhbGciOiJIUzI1NiJ9.bm90LWpzb24tYXQtYWxs.ZmFrZXNpZ25hdHVyZQ')).toBe(false)
    // detector de secret key
    expect(SECRET_KEY.test('sb_secret_abcdefghij0123456789')).toBe(true)
    expect(SECRET_KEY.test('`sb_publishable_… / sb_secret_…` are not JWTs')).toBe(false)

    // ── Barrido del build ─────────────────────────────────────────────────────
    const offenders: string[] = []
    const walk = (dir: string) => {
      for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        const full = path.join(dir, entry.name)
        if (entry.isDirectory()) {
          if (entry.name === 'cache') continue
          walk(full)
          continue
        }
        if (!/\.(js|mjs|cjs|json|html|txt|map)$/.test(entry.name)) continue

        const content = fs.readFileSync(full, 'utf8')
        const rel = path.relative(buildDir, full)
        if (SECRET_KEY.test(content)) offenders.push(`${rel} (secret key)`)
        if (hasServiceRoleJwt(content)) offenders.push(`${rel} (service_role JWT)`)
      }
    }
    walk(buildDir)

    expect(offenders, `artefactos con credencial elevada: ${offenders.join(', ')}`).toEqual([])
  })
})
