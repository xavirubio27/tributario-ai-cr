/**
 * Cliente Supabase para el navegador (Client Components).
 *
 * Patron actual de @supabase/ssr. Verificado contra los tipos del paquete
 * instalado (0.12.4), no reconstruido de memoria.
 *
 * En runtime de navegador, `createBrowserClient` gestiona las cookies via
 * `document.cookie` cuando no se le pasa un almacen personalizado, de modo que
 * comparte sesion con el cliente de servidor.
 *
 * Solo debe usarse la clave PUBLICABLE. Nunca la secret key ni service_role:
 * cualquier cosa que llegue al navegador es publica por definicion.
 */
import { createBrowserClient } from '@supabase/ssr'

function requiredEnv(name: string, value: string | undefined): string {
  if (!value) {
    throw new Error(
      `Falta la variable de entorno ${name}. ` +
        'Copia frontend/.env.example a frontend/.env.local y rellenala.',
    )
  }
  return value
}

export function createClient() {
  return createBrowserClient(
    requiredEnv('NEXT_PUBLIC_SUPABASE_URL', process.env.NEXT_PUBLIC_SUPABASE_URL),
    requiredEnv(
      'NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY',
      process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY,
    ),
  )
}
