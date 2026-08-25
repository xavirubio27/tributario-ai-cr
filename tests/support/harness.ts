/**
 * Arnés compartido de los tests de integración.
 *
 * PROBLEMA QUE RESUELVE
 *   Un fallo de setup (signup, login, creación) dejaba variables vacías y los
 *   casos siguientes fallaban con errores secundarios engañosos, como
 *   `invalid input syntax for type uuid: ""`, que ocultan la causa real.
 *
 * REGLAS
 *   1. Cualquier fallo de setup aborta de inmediato.
 *   2. Nunca se continúa con un identificador vacío.
 *   3. El error ORIGINAL de Supabase queda visible (código y mensaje).
 *   4. El límite de tasa se identifica explícitamente, no se disfraza.
 */
import { createClient, type SupabaseClient } from '@supabase/supabase-js'

export class SetupError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'SetupError'
  }
}

type SupabaseError = { message: string; code?: string; status?: number } | null

const RATE_LIMIT_HINT =
  '\n  >>> LÍMITE DE TASA DE SUPABASE AUTH alcanzado.\n' +
  '      [auth.rate_limit] sign_in_sign_ups = 30 por 5 minutos y por IP.\n' +
  '      Espera unos minutos antes de reejecutar la suite.'

function isRateLimit(error: NonNullable<SupabaseError>): boolean {
  return error.status === 429 || error.code === 'over_request_rate_limit' || /rate limit/i.test(error.message)
}

function describe(error: NonNullable<SupabaseError>): string {
  const code = error.code ?? (error.status != null ? `HTTP ${error.status}` : 'sin código')
  return `[${code}] ${error.message}${isRateLimit(error) ? RATE_LIMIT_HINT : ''}`
}

/** Aborta si la operación falló, dejando visible el error original. */
export function assertOk(error: SupabaseError, context: string): void {
  if (error) throw new SetupError(`${context} falló: ${describe(error)}`)
}

/** Aborta si el identificador está vacío: nunca se propaga un id vacío. */
export function requireId(value: string | null | undefined, context: string): string {
  if (!value) {
    throw new SetupError(
      `${context}: identificador vacío. Un paso previo de esta suite falló; ` +
        'revisa el PRIMER error reportado, no este.',
    )
  }
  return value
}

/** Cliente para Node: sin persistencia ni refresco, sesiones aisladas entre usuarios. */
export function newClient(url: string, publishableKey: string): SupabaseClient {
  return createClient(url, publishableKey, {
    auth: { persistSession: false, autoRefreshToken: false, detectSessionInUrl: false },
  })
}

/** Registra un usuario y exige sesión inmediata. Aborta con causa legible si falla. */
export async function signUpOrFail(
  client: SupabaseClient,
  credentials: { email: string; password: string },
  label: string,
): Promise<string> {
  const { data, error } = await client.auth.signUp(credentials)
  assertOk(error, `signUp de ${label}`)

  if (!data.session) {
    throw new SetupError(
      `signUp de ${label} no devolvió sesión. ` +
        'Revisa que [auth.email] enable_confirmations = false en el proyecto de desarrollo (ADR-019).',
    )
  }

  return requireId(data.user?.id, `signUp de ${label}`)
}

/** Inicia sesión y exige éxito. */
export async function signInOrFail(
  client: SupabaseClient,
  credentials: { email: string; password: string },
  label: string,
): Promise<void> {
  const { data, error } = await client.auth.signInWithPassword(credentials)
  assertOk(error, `signIn de ${label}`)
  if (!data.session) throw new SetupError(`signIn de ${label} no devolvió sesión.`)
}

/**
 * Exige que el servidor de Next.js esté escuchando.
 * Sin esto, los casos [HTTP] fallan con un ECONNREFUSED crudo que no dice qué hacer.
 */
export async function requireAppServer(appUrl: string): Promise<void> {
  try {
    const res = await fetch(appUrl, { redirect: 'manual' })
    if (res.status >= 500) {
      throw new SetupError(`El servidor en ${appUrl} respondió ${res.status}.`)
    }
  } catch (cause) {
    if (cause instanceof SetupError) throw cause
    throw new SetupError(
      `El servidor de Next.js no responde en ${appUrl}.\n` +
        '      Arráncalo con `cd frontend && npm run dev` antes de ejecutar la suite.',
    )
  }
}
