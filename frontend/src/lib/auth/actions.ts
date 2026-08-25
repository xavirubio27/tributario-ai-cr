'use server'

/**
 * Server Actions de autenticación.
 *
 * MENSAJES DE ERROR
 *   Nunca revelan si un correo está registrado ni qué parte de la credencial
 *   falló. Un mensaje distinto para "usuario inexistente" y "contraseña
 *   incorrecta" permite enumerar cuentas.
 *
 * CONTRASEÑAS
 *   Nunca se almacenan, registran ni transmiten fuera de Supabase Auth.
 */
import { redirect } from 'next/navigation'
import { createClient } from '@/lib/supabase/server'
import { MIN_PASSWORD_LENGTH, type AuthState } from '@/lib/auth/constants'
import { requireUser } from '@/lib/auth/session'

function readCredentials(formData: FormData) {
  return {
    email: String(formData.get('email') ?? '').trim(),
    password: String(formData.get('password') ?? ''),
    confirmPassword: String(formData.get('confirmPassword') ?? ''),
  }
}

export async function signUpAction(
  _prevState: AuthState,
  formData: FormData,
): Promise<AuthState> {
  const { email, password, confirmPassword } = readCredentials(formData)

  if (!email) return { error: 'El correo electrónico es obligatorio.' }
  if (!password) return { error: 'La contraseña es obligatoria.' }
  if (password.length < MIN_PASSWORD_LENGTH) {
    return { error: `La contraseña debe tener al menos ${MIN_PASSWORD_LENGTH} caracteres.` }
  }
  if (password !== confirmPassword) {
    return { error: 'Las contraseñas no coinciden.' }
  }

  const supabase = await createClient()
  const { data, error } = await supabase.auth.signUp({ email, password })

  if (error) {
    return { error: 'No se pudo crear la cuenta. Revisa los datos e inténtalo de nuevo.' }
  }

  // En DESARROLLO `enable_confirmations = false`, luego signUp devuelve sesión
  // inmediatamente. En producción esa política está sin decidir (ADR-019), así
  // que NO se asume: si no hay sesión, se informa en lugar de redirigir a una
  // ruta protegida que rebotaría de vuelta.
  if (!data.session) {
    return {
      error: null,
      notice: 'Cuenta creada. Revisa tu correo para confirmarla antes de iniciar sesión.',
    }
  }

  redirect('/app')
}

export async function signInAction(
  _prevState: AuthState,
  formData: FormData,
): Promise<AuthState> {
  const { email, password } = readCredentials(formData)

  if (!email || !password) {
    return { error: 'Introduce tu correo electrónico y tu contraseña.' }
  }

  const supabase = await createClient()
  const { error } = await supabase.auth.signInWithPassword({ email, password })

  if (error) {
    // Mensaje deliberadamente genérico: no distingue entre correo inexistente y
    // contraseña incorrecta.
    return { error: 'Credenciales incorrectas.' }
  }

  redirect('/app')
}

export async function signOutAction(
  _prevState: AuthState,
  _formData: FormData,
): Promise<AuthState> {
  // Verificación explícita antes de operar: esta Server Action no depende del
  // proxy para saber que hay identidad.
  await requireUser()

  const supabase = await createClient()
  const { error } = await supabase.auth.signOut()

  // CORRECCIÓN (auditoría Codex): antes se ignoraba el resultado y se redirigía
  // igualmente, fingiendo éxito. Si signOut falla, las cookies de sesión pueden
  // seguir siendo válidas: redirigir daría al usuario la impresión de haber
  // cerrado sesión cuando no es así.
  if (error) {
    return { error: 'No se pudo cerrar la sesión. Inténtalo de nuevo.' }
  }

  // redirect() lanza una excepción de control de Next.js: debe quedar fuera de
  // cualquier try/catch.
  redirect('/login')
}
