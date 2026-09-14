/**
 * Acceso al backend fiscal desde el servidor. **Nunca desde el navegador.**
 *
 * QUÉ IMPIDE QUE ESTO ACABE EN EL BUNDLE
 *   No se usa el paquete `server-only` porque no está instalado y añadirlo
 *   sería una dependencia nueva. La garantía ya existe por otra vía: este
 *   módulo importa `@/lib/supabase/server`, que a su vez importa
 *   `next/headers`, y Next rechaza esa importación en un componente de
 *   cliente. Intentar usar esto desde el navegador rompe la compilación, que
 *   es justo lo que se quería.
 *
 * Vivía dentro de la Server Action de subida; se extrae aquí porque la lectura
 * de la bandeja necesita exactamente la misma secuencia y duplicarla habría
 * significado dos sitios donde equivocarse con la identidad.
 */
import { createClient } from '@/lib/supabase/server'

/** Un XML pequeño se procesa en mucho menos; esto es el techo, no lo normal. */
export const BACKEND_TIMEOUT_MS = 30_000

/**
 * Token verificado listo para reenviar, o `null`.
 *
 * `getClaims()` establece la identidad —la librería advierte explícitamente de
 * no usar `getSession()` para eso—. Pero `getClaims()` devuelve
 * `{claims, header, signature}`, no la cadena compacta, así que el token hay
 * que sacarlo de la sesión.
 *
 * El orden importa y no es casual:
 *
 *   1. `getClaims()` verifica la identidad y, si el token está por vencer,
 *      refresca la sesión antes de seguir;
 *   2. `getSession()` entrega el token que se va a reenviar, tratado como un
 *      VALOR OPACO de transporte: no se lee su `user`, no se deriva de él
 *      ningún permiso;
 *   3. `getClaims(token)` verifica ESE token exacto, el mismo que viajará.
 *
 * El paso 3 no añade seguridad —FastAPI lo verifica otra vez contra JWKS, y esa
 * es la autoridad—; convierte un 401 confuso del backend en un fallo claro
 * aquí.
 */
export async function verifiedAccessToken(): Promise<string | null> {
  const supabase = await createClient()

  const identidad = await supabase.auth.getClaims()
  if (identidad.error || !identidad.data?.claims) {
    return null
  }

  const { data } = await supabase.auth.getSession()
  const token = data.session?.access_token
  if (!token) {
    return null
  }

  const delToken = await supabase.auth.getClaims(token)
  if (delToken.error || !delToken.data?.claims) {
    return null
  }

  return token
}

/** URL base del backend, o `null` si no está configurada. Solo de servidor. */
export function backendUrl(): string | null {
  return process.env.BACKEND_URL ?? null
}
