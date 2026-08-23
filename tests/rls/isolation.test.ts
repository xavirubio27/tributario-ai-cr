/**
 * Checkpoint C — Prueba empirica del aislamiento multiempresa (RLS).
 *
 * OBJETIVO
 *   Demostrar que dos usuarios autenticados distintos no pueden alcanzar los
 *   datos del otro, y que la escritura directa esta cerrada para el cliente.
 *
 * REGLAS DE LA PRUEBA
 *   - Se usa EXCLUSIVAMENTE la clave publicable y la sesion propia de cada
 *     usuario. Nunca service_role ni secret key: el test debe demostrar que RLS
 *     funciona, no esquivarla (ADR-002).
 *   - Cada usuario tiene su PROPIO cliente. persistSession=false evita que las
 *     sesiones de A y B se pisen entre si.
 *
 * DISTINCION CLAVE
 *   SELECT bloqueado por RLS  -> 0 filas, SIN error.
 *   Operacion sin privilegio  -> error.
 *   Confundirlas produce tests que pasan por el motivo equivocado.
 */
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { config } from 'dotenv'
import { createClient, type SupabaseClient } from '@supabase/supabase-js'
import { beforeAll, describe, expect, it } from 'vitest'

const here = path.dirname(fileURLToPath(import.meta.url))
config({ path: path.resolve(here, '..', '.env.local') })

const SUPABASE_URL = process.env.SUPABASE_URL ?? ''
const SUPABASE_PUBLISHABLE_KEY = process.env.SUPABASE_PUBLISHABLE_KEY ?? ''

if (!SUPABASE_URL || !SUPABASE_PUBLISHABLE_KEY) {
  throw new Error(
    'Faltan SUPABASE_URL o SUPABASE_PUBLISHABLE_KEY. ' +
      'Copia tests/.env.example a tests/.env.local y rellenalo desde el Dashboard.',
  )
}

/** Cliente para ejecucion en Node: sin persistencia ni refresco automatico. */
function newClient(): SupabaseClient {
  return createClient(SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY, {
    auth: {
      persistSession: false,
      autoRefreshToken: false,
      detectSessionInUrl: false,
    },
  })
}

const runId = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`

const USER_A = { email: `rls-a-${runId}@example.com`, password: `PwA-${runId}-x9` }
const USER_B = { email: `rls-b-${runId}@example.com`, password: `PwB-${runId}-x9` }

let clientA: SupabaseClient
let clientB: SupabaseClient
let clientAnon: SupabaseClient

let userAId = ''
let userBId = ''
let companyAId = ''
let membershipAId = ''

beforeAll(async () => {
  clientAnon = newClient()

  clientA = newClient()
  const { data: a, error: errA } = await clientA.auth.signUp(USER_A)
  if (errA) throw new Error(`signUp User A fallo: ${errA.message}`)
  if (!a.session) {
    throw new Error(
      'signUp User A no devolvio sesion. Revisa que enable_confirmations = false (ADR-019).',
    )
  }
  userAId = a.user!.id

  clientB = newClient()
  const { data: b, error: errB } = await clientB.auth.signUp(USER_B)
  if (errB) throw new Error(`signUp User B fallo: ${errB.message}`)
  if (!b.session) throw new Error('signUp User B no devolvio sesion.')
  userBId = b.user!.id

  expect(userAId).not.toBe(userBId)
}, 60_000)

describe('Checkpoint C — aislamiento RLS entre tenants', () => {
  it('10. Ningun test utiliza service_role ni secret key', () => {
    expect(SUPABASE_PUBLISHABLE_KEY.startsWith('sb_publishable_')).toBe(true)
    expect(SUPABASE_PUBLISHABLE_KEY.startsWith('sb_secret_')).toBe(false)
    expect(SUPABASE_PUBLISHABLE_KEY.startsWith('ey')).toBe(false)
    // Ninguna variable del entorno de test puede contener credenciales elevadas.
    for (const [k, v] of Object.entries(process.env)) {
      if (typeof v === 'string' && v.startsWith('sb_secret_')) {
        throw new Error(`Variable ${k} contiene una secret key`)
      }
    }
    expect(process.env.SUPABASE_SERVICE_ROLE_KEY).toBeUndefined()
  })

  it('1. User A crea Company A mediante create_company()', async () => {
    const { data, error } = await clientA.rpc('create_company', {
      p_name: `Company A ${runId}`,
    })
    expect(error).toBeNull()
    expect(data).toBeTruthy()
    companyAId = (data as any).id
    expect(companyAId).toBeTruthy()
    expect((data as any).created_by).toBe(userAId)
  })

  it('2. User A lista companies y ve Company A', async () => {
    const { data, error } = await clientA.from('companies').select('id, name, created_by')
    expect(error).toBeNull()
    expect(data).toHaveLength(1)
    expect(data![0].id).toBe(companyAId)
  })

  it('3. User A lista company_memberships y ve su membership owner', async () => {
    const { data, error } = await clientA
      .from('company_memberships')
      .select('id, company_id, user_id, role')
    expect(error).toBeNull()
    expect(data).toHaveLength(1)
    expect(data![0].company_id).toBe(companyAId)
    expect(data![0].user_id).toBe(userAId)
    expect(data![0].role).toBe('owner')
    membershipAId = data![0].id
  })

  it('4. User B lista companies -> 0 filas (RLS filtra, no da error)', async () => {
    const { data, error } = await clientB.from('companies').select('id')
    expect(error).toBeNull() // RLS filtra; NO es un error de privilegio
    expect(data).toHaveLength(0)
  })

  it('5. User B consulta Company A por ID explicito -> 0 filas', async () => {
    const { data, error } = await clientB.from('companies').select('id').eq('id', companyAId)
    expect(error).toBeNull()
    expect(data).toHaveLength(0)
  })

  it('6. User B lista memberships -> no ve la membership de User A', async () => {
    const { data, error } = await clientB.from('company_memberships').select('id, user_id')
    expect(error).toBeNull()
    expect(data).toHaveLength(0)
    expect((data ?? []).some((r: any) => r.id === membershipAId)).toBe(false)
  })

  it('7. User B intenta INSERT en company_memberships para unirse a Company A -> falla', async () => {
    const { data, error } = await clientB
      .from('company_memberships')
      .insert({ company_id: companyAId, user_id: userBId, role: 'owner' })
      .select()
    expect(error).not.toBeNull() // sin privilegio -> error, no 0 filas
    expect(data).toBeNull()
  })

  it('8. User B intenta INSERT directo en companies -> falla', async () => {
    const { data, error } = await clientB
      .from('companies')
      .insert({ name: `Intruso ${runId}`, created_by: userBId })
      .select()
    expect(error).not.toBeNull()
    expect(data).toBeNull()
  })

  it('9. Cliente anonimo intenta ejecutar create_company() -> falla', async () => {
    const { data, error } = await clientAnon.rpc('create_company', {
      p_name: `Anon ${runId}`,
    })
    expect(error).not.toBeNull()
    expect(data).toBeNull()
  })

  // ---------------------------------------------------------------------------
  // CONTROL DE VALIDEZ
  // ---------------------------------------------------------------------------
  // Sin esto, los casos 4-8 podrian pasar simplemente porque la sesion de B
  // estuviera rota. Demostrar que B SI puede operar en su propio tenant es lo
  // que convierte "B no ve nada" en "B no ve lo ajeno".
  // ---------------------------------------------------------------------------
  it('11. CONTROL: User B crea su propia empresa y ve solo la suya', async () => {
    const { data: created, error: errCreate } = await clientB.rpc('create_company', {
      p_name: `Company B ${runId}`,
    })
    expect(errCreate).toBeNull()
    const companyBId = (created as any).id
    expect(companyBId).toBeTruthy()

    const { data, error } = await clientB.from('companies').select('id')
    expect(error).toBeNull()
    expect(data).toHaveLength(1)
    expect(data![0].id).toBe(companyBId)
    expect(data![0].id).not.toBe(companyAId)

    // Y A sigue viendo solo la suya.
    const { data: aSees } = await clientA.from('companies').select('id')
    expect(aSees).toHaveLength(1)
    expect(aSees![0].id).toBe(companyAId)
  })
})
