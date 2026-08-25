/**
 * Verificación de identidad en el servidor.
 *
 * `getClaims()` valida el JWT. Nunca se usa `getSession()` para autorización:
 * la propia librería advierte que el objeto de usuario obtenido de un medio
 * inseguro (cookies) "must not be trusted".
 *
 * DEFENSA EN PROFUNDIDAD
 *   `proxy.ts` refresca la sesión, pero no autoriza. Cada página protegida y
 *   cada Server Action sensible debe llamar a `requireUser()` explícitamente.
 *   Un cambio de `matcher` en el proxy no debe poder dejar una ruta desprotegida.
 */
import { redirect } from 'next/navigation'
import { createClient } from '@/lib/supabase/server'

export type VerifiedUser = {
  id: string
  email: string | null
}

/**
 * Devuelve la identidad verificada, o `null` si no hay sesión válida.
 *
 * `getClaims()` tiene tres formas de retorno; `{ data: null, error: null }`
 * significa "sin sesión". Por eso se comprueba `data?.claims`, no solo `error`.
 */
export async function getVerifiedUser(): Promise<VerifiedUser | null> {
  const supabase = await createClient()
  const { data, error } = await supabase.auth.getClaims()

  if (error || !data?.claims) {
    return null
  }

  const claims = data.claims
  const id = typeof claims.sub === 'string' ? claims.sub : null
  if (!id) {
    return null
  }

  return {
    id,
    email: typeof claims.email === 'string' ? claims.email : null,
  }
}

/**
 * Exige identidad verificada. Redirige a `/login` si no la hay.
 * Usar en toda página protegida y en toda Server Action sensible.
 */
export async function requireUser(): Promise<VerifiedUser> {
  const user = await getVerifiedUser()
  if (!user) {
    redirect('/login')
  }
  return user
}
