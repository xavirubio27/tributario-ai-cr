/**
 * Checkpoint F — flujo de empresas.
 *
 * NIVELES (mismo criterio declarado en Checkpoint E)
 *
 *   [UNIT]   Validación pura importada directamente del código de la aplicación.
 *            Es la MISMA función que ejecuta la Server Action, no una copia.
 *   [DB]     Operaciones reales contra Supabase con sesión de usuario y RLS.
 *   [HTTP]   Peticiones reales al servidor de Next.js.
 *   [STATIC] Análisis del código fuente de la aplicación.
 *
 *   NO se invoca el protocolo HTTP de Server Actions: depende de un identificador
 *   que se regenera en cada build. El hueco se cubre importando la validación
 *   real [UNIT] y ejerciendo el RPC real [DB], que es lo que la acción hace.
 *
 * Sin service_role, sin secret key, sin Admin API.
 */
import path from 'node:path'
import fs from 'node:fs'
import { fileURLToPath } from 'node:url'
import { config } from 'dotenv'
import { type SupabaseClient } from '@supabase/supabase-js'
import { beforeAll, describe, expect, it } from 'vitest'
import { assertOk, newClient as makeClient, requireAppServer, requireId, signUpOrFail } from '../support/harness'
import {
  COMPANY_NAME_MAX_LENGTH,
  validateCompanyName,
} from '../../frontend/src/lib/companies/validation'

const here = path.dirname(fileURLToPath(import.meta.url))
config({ path: path.resolve(here, '..', '.env.local') })

const SUPABASE_URL = process.env.SUPABASE_URL ?? ''
const SUPABASE_PUBLISHABLE_KEY = process.env.SUPABASE_PUBLISHABLE_KEY ?? ''
const APP_URL = process.env.APP_URL ?? 'http://localhost:3000'
const SRC_DIR = path.resolve(here, '..', '..', 'frontend', 'src')

if (!SUPABASE_URL || !SUPABASE_PUBLISHABLE_KEY) {
  throw new Error('Faltan SUPABASE_URL o SUPABASE_PUBLISHABLE_KEY en tests/.env.local')
}

function newClient(): SupabaseClient {
  return makeClient(SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY)
}

/** Recorre el código fuente de la aplicación devolviendo [rutaRelativa, contenido]. */
function sourceFiles(): Array<[string, string]> {
  const out: Array<[string, string]> = []
  const walk = (dir: string) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name)
      if (entry.isDirectory()) walk(full)
      else if (/\.(ts|tsx)$/.test(entry.name)) {
        out.push([path.relative(SRC_DIR, full), fs.readFileSync(full, 'utf8')])
      }
    }
  }
  walk(SRC_DIR)
  return out
}

const runId = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`
const USER_A = { email: `co-a-${runId}@example.com`, password: `PwA-${runId}-x9` }
const USER_B = { email: `co-b-${runId}@example.com`, password: `PwB-${runId}-x9` }

let clientA: SupabaseClient
let clientB: SupabaseClient
let companyAId = ''
const companyAName = `Empresa A ${runId}`

beforeAll(async () => {
  await requireAppServer(APP_URL)

  clientA = newClient()
  await signUpOrFail(clientA, USER_A, 'User A')

  clientB = newClient()
  await signUpOrFail(clientB, USER_B, 'User B')
}, 60_000)

describe('Checkpoint F — empresas', () => {
  it('[DB] A. usuario autenticado sin empresas obtiene lista vacía válida', async () => {
    const { data, error } = await clientA.from('companies').select('id, name, created_at')
    expect(error).toBeNull() // lista vacía, NO error
    expect(data).toEqual([])
  })

  describe('tras crear una empresa', () => {
    // PRERREQUISITO COMPARTIDO (auditoría Codex): la creación vive en un hook,
    // de modo que un fallo aquí impide ejecutar los casos dependientes en lugar
    // de propagar un identificador vacío. Va en un describe anidado porque el
    // caso A debe observar el estado vacío ANTES de que exista la empresa.
    beforeAll(async () => {
      const { data, error } = await clientA.rpc('create_company', { p_name: companyAName })
      assertOk(error, 'create_company de User A (prerrequisito)')
      companyAId = requireId((data as { id?: string } | null)?.id, 'create_company de User A (prerrequisito)')
    }, 30_000)

  it('[DB] B. usuario autenticado crea empresa mediante create_company RPC', () => {
    expect(companyAId).toBeTruthy()
  })

  it('[DB] C. tras crearla, la consulta de companies devuelve esa empresa', async () => {
    // Misma consulta que listCompanies(): sin filtro por usuario, RLS decide.
    const { data, error } = await clientA
      .from('companies')
      .select('id, name, created_at')
      .order('created_at', { ascending: false })

    expect(error).toBeNull()
    expect(data).toHaveLength(1)
    expect(data![0].id).toBe(companyAId)
    expect(data![0].name).toBe(companyAName)
  })

  it('[DB] D. usuario B no obtiene la empresa de usuario A', async () => {
    const all = await clientB.from('companies').select('id')
    expect(all.error).toBeNull()
    expect((all.data ?? []).some((c: { id: string }) => c.id === companyAId)).toBe(false)

    const byId = await clientB.from('companies').select('id').eq('id', companyAId)
    expect(byId.error).toBeNull()
    expect(byId.data).toHaveLength(0)
  })
  })

  it('[HTTP] E. usuario no autenticado no puede acceder al flujo protegido', async () => {
    const res = await fetch(`${APP_URL}/app`, { redirect: 'manual' })
    expect([302, 303, 307, 308]).toContain(res.status)
    expect(res.headers.get('location') ?? '').toContain('/login')
  })

  it('[UNIT] F. nombre vacío es rechazado por la capa de aplicación', () => {
    for (const value of ['', '   ', '\t\n', null, undefined, 123]) {
      const result = validateCompanyName(value)
      expect(result.ok, `valor: ${JSON.stringify(value)}`).toBe(false)
    }
    // Autotest: la función debe aceptar un nombre válido, o el caso pasaría en vacío.
    expect(validateCompanyName('  Empresa válida  ')).toEqual({ ok: true, name: 'Empresa válida' })
  })

  it('[UNIT+DB] G. nombre fuera de la longitud permitida es rechazado', async () => {
    const tooLong = 'x'.repeat(COMPANY_NAME_MAX_LENGTH + 1)
    expect(validateCompanyName(tooLong).ok).toBe(false)
    expect(validateCompanyName('x'.repeat(COMPANY_NAME_MAX_LENGTH)).ok).toBe(true)

    // La base de datos es la autoridad: si la validación local se saltara, el RPC
    // debe rechazarlo igualmente.
    const { data, error } = await clientA.rpc('create_company', { p_name: tooLong })
    // 22023 = invalid_parameter_value: lo lanza la validación del RPC, NO es una
    // denegación de privilegio. Distinguirlo evita un PASS por el motivo erróneo.
    expect(error?.code).toBe('22023')
    expect(data).toBeNull()

    const empty = await clientA.rpc('create_company', { p_name: '   ' })
    expect(empty.error?.code).toBe('22023')
  })

  it('[STATIC] H. ningún código usa INSERT directo sobre companies o memberships', () => {
    const forbidden = [
      /\.from\(\s*['"`]companies['"`]\s*\)[\s\S]{0,120}?\.insert\s*\(/,
      /\.from\(\s*['"`]company_memberships['"`]\s*\)[\s\S]{0,120}?\.insert\s*\(/,
      /\.from\(\s*['"`]companies['"`]\s*\)[\s\S]{0,120}?\.upsert\s*\(/,
      /\.from\(\s*['"`]company_memberships['"`]\s*\)[\s\S]{0,120}?\.upsert\s*\(/,
    ]
    // Autotest del detector.
    expect(forbidden[0].test(`supabase.from('companies').insert({})`)).toBe(true)
    expect(forbidden[0].test(`supabase.from('companies').select('id')`)).toBe(false)

    const offenders: string[] = []
    for (const [rel, content] of sourceFiles()) {
      if (forbidden.some((re) => re.test(content))) offenders.push(rel)
    }
    expect(offenders, `archivos con INSERT directo: ${offenders.join(', ')}`).toEqual([])
  })

  it('[STATIC] I. ningún código usa service_role ni secret key', () => {
    const SECRET_KEY = /sb_secret_[A-Za-z0-9]{10,}/
    const SERVICE_ROLE_USE = /(SERVICE_ROLE|serviceRole|service_role_key)/
    // Autotest del detector.
    expect(SECRET_KEY.test('sb_secret_abcdefghij0123456789')).toBe(true)
    expect(SERVICE_ROLE_USE.test('process.env.SUPABASE_SERVICE_ROLE_KEY')).toBe(true)

    const offenders: string[] = []
    for (const [rel, content] of sourceFiles()) {
      // Se ignoran los comentarios: varios documentan justamente que NO se usa.
      const code = content
        .replace(/\/\*[\s\S]*?\*\//g, '')
        .replace(/(^|\s)\/\/.*$/gm, '')
      if (SECRET_KEY.test(code) || SERVICE_ROLE_USE.test(code)) offenders.push(rel)
    }
    expect(offenders, `archivos con credencial elevada: ${offenders.join(', ')}`).toEqual([])
  })

  it('[STATIC] la consulta de empresas no filtra por user_id desde la aplicación', () => {
    const queries = fs.readFileSync(path.join(SRC_DIR, 'lib/companies/queries.ts'), 'utf8')
    const code = queries.replace(/\/\*[\s\S]*?\*\//g, '')
    expect(code).toContain("from('companies')")
    // El aislamiento debe venir de RLS, no de un filtro de la aplicación.
    expect(code).not.toMatch(/\.eq\(\s*['"`](user_id|created_by)['"`]/)
  })
})
