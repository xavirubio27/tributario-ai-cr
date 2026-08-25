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
import { type SupabaseClient } from '@supabase/supabase-js'
import { beforeAll, describe, expect, it } from 'vitest'
import { assertOk, newClient as makeClient, requireId, signUpOrFail } from '../support/harness'

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
  return makeClient(SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY)
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
let companyA: { id: string; name: string; created_by: string } | null = null

beforeAll(async () => {
  clientAnon = newClient()

  clientA = newClient()
  userAId = await signUpOrFail(clientA, USER_A, 'User A')

  clientB = newClient()
  userBId = await signUpOrFail(clientB, USER_B, 'User B')

  expect(userAId).not.toBe(userBId)

  // PRERREQUISITO COMPARTIDO (auditoría Codex): la creación de Company A la
  // necesitan 5 casos. Vive en el hook para que un fallo aquí IMPIDA ejecutarlos
  // en lugar de propagar un identificador vacío. El caso 1 solo lo verifica.
  const created = await clientA.rpc('create_company', { p_name: `Company A ${runId}` })
  assertOk(created.error, 'create_company de User A (prerrequisito)')
  companyA = created.data as { id: string; name: string; created_by: string }
  companyAId = requireId(companyA?.id, 'create_company de User A (prerrequisito)')
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

  it('1. User A crea Company A mediante create_company()', () => {
    // La creación ocurre en beforeAll; aquí se verifica su resultado.
    expect(companyA).not.toBeNull()
    expect(companyAId).toBeTruthy()
    expect(companyA!.name).toBe(`Company A ${runId}`)
    expect(companyA!.created_by).toBe(userAId)
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
    expect(data![0].id).toBeTruthy()
  })

  it('4. User B lista companies -> 0 filas (RLS filtra, no da error)', async () => {
    const { data, error } = await clientB.from('companies').select('id')
    // RLS FILTRA: 0 filas y error null. NO es denegacion de privilegio.
    expect(error).toBeNull()
    expect(data).toHaveLength(0)
  })

  it('5. User B consulta Company A por ID explicito -> 0 filas', async () => {
    const { data, error } = await clientB.from('companies').select('id').eq('id', companyAId)
    expect(error).toBeNull()
    expect(data).toHaveLength(0)
  })

  it('6. User B lista memberships -> no ve la membership de User A', async () => {
    // (a) B no ve NINGUNA membership. RLS filtra: 0 filas y error null.
    const todas = await clientB.from('company_memberships').select('id, user_id, company_id')
    expect(todas.error).toBeNull()
    expect(todas.data).toHaveLength(0)

    // (b) Y, explicitamente, ninguna membership DE LA EMPRESA DE A.
    //
    // Antes esto se comprobaba con `.some(r => r.id === membershipAId)` sobre el
    // resultado anterior, usando un id producido por el caso 3. Ademas de crear
    // una dependencia entre tests, la asercion era vacua: sobre una lista vacia
    // `.some()` es falso aunque el id estuviera vacio.
    //
    // Una consulta dirigida por `companyAId` -- que proviene del hook -- prueba
    // la propiedad de seguridad de forma directa y no depende de ningun otro it().
    const deCompanyA = await clientB
      .from('company_memberships')
      .select('id')
      .eq('company_id', companyAId)
    expect(deCompanyA.error).toBeNull()
    expect(deCompanyA.data).toHaveLength(0)
  })

  it('7. User B intenta INSERT en company_memberships para unirse a Company A -> falla', async () => {
    const { data, error } = await clientB
      .from('company_memberships')
      .insert({ company_id: companyAId, user_id: userBId, role: 'owner' })
      .select()
    // Denegacion por PRIVILEGIO: codigo SQLSTATE explicito. Comprobar solo que
    // "hay error" permitiria que un fallo de red o de rate limit diera un PASS
    // falso (auditoria Codex).
    expect(error?.code).toBe('42501')
    expect(data).toBeNull()
  })

  it('8. User B intenta INSERT directo en companies -> falla', async () => {
    const { data, error } = await clientB
      .from('companies')
      .insert({ name: `Intruso ${runId}`, created_by: userBId })
      .select()
    expect(error?.code).toBe('42501')
    expect(data).toBeNull()
  })

  it('9. Cliente anonimo intenta ejecutar create_company() -> falla', async () => {
    const { data, error } = await clientAnon.rpc('create_company', {
      p_name: `Anon ${runId}`,
    })
    expect(error?.code).toBe('42501')
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
    assertOk(errCreate, 'create_company de User B')
    const companyBId = requireId((created as { id?: string } | null)?.id, 'create_company de User B')

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
