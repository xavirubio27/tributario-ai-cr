/**
 * Cliente Supabase para el servidor (Server Components, Server Actions,
 * Route Handlers).
 *
 * Patron actual de @supabase/ssr. Contrato verificado contra los tipos del
 * paquete instalado (0.12.4):
 *
 *   CookieMethodsServer = { getAll: GetAllCookies; setAll?: SetAllCookies }
 *   SetAllCookies = (cookies: {name,value,options}[], headers) => void
 *
 * NOTA SOBRE `headers` (Checkpoint E)
 *   `setAll` recibe un segundo argumento con cabeceras anti-cache
 *   (Cache-Control / Expires / Pragma) que deben aplicarse a la respuesta HTTP
 *   para que ningun CDN cachee una sesion y sirva el token de un usuario a otro.
 *   Desde `next/headers` no es posible fijar cabeceras de respuesta arbitrarias;
 *   ese trabajo corresponde a `proxy.ts`, que se implementara en Checkpoint E.
 *   Por eso aqui se omite ese parametro deliberadamente.
 *
 * IMPORTANTE (documentado en el paquete)
 *   Llamar a `supabase.auth.getClaims()` pronto en el manejador de la peticion,
 *   antes de generar la respuesta. Si un refresco de token termina despues de
 *   haberse enviado la respuesta, la sesion actualizada se pierde.
 *   Nunca confiar en `getSession()` en codigo de servidor.
 */
import { cookies } from 'next/headers'
import { createServerClient } from '@supabase/ssr'

function requiredEnv(name: string, value: string | undefined): string {
  if (!value) {
    throw new Error(
      `Falta la variable de entorno ${name}. ` +
        'Copia frontend/.env.example a frontend/.env.local y rellenala.',
    )
  }
  return value
}

export async function createClient() {
  const cookieStore = await cookies()

  return createServerClient(
    requiredEnv('NEXT_PUBLIC_SUPABASE_URL', process.env.NEXT_PUBLIC_SUPABASE_URL),
    requiredEnv(
      'NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY',
      process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY,
    ),
    {
      cookies: {
        getAll() {
          return cookieStore.getAll()
        },
        setAll(cookiesToSet) {
          try {
            for (const { name, value, options } of cookiesToSet) {
              cookieStore.set(name, value, options)
            }
          } catch {
            // Invocado desde un Server Component, donde las cookies son de solo
            // lectura. Es seguro ignorarlo mientras `proxy.ts` (Checkpoint E)
            // se encargue de refrescar la sesion.
          }
        },
      },
    },
  )
}
