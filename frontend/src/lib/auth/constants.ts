/**
 * Constantes y tipos compartidos de autenticación.
 *
 * Vive fuera de `actions.ts` porque un módulo `'use server'` solo puede exportar
 * funciones asíncronas.
 */

/**
 * Longitud mínima de contraseña.
 *
 * Debe mantenerse alineada con `supabase/config.toml`:
 *   [auth] minimum_password_length = 8
 *
 * Esta validación es de conveniencia (mensaje claro antes de la llamada de red).
 * La validación real la impone Supabase Auth en el servidor.
 */
export const MIN_PASSWORD_LENGTH = 8

/** Estado devuelto por las Server Actions de autenticación a `useActionState`. */
export type AuthState = {
  /** Mensaje de error seguro para mostrar. Nunca revela si un email existe. */
  error?: string | null
  /** Mensaje informativo (p. ej. confirmación de email pendiente en producción). */
  notice?: string | null
}

export const EMPTY_AUTH_STATE: AuthState = {}
