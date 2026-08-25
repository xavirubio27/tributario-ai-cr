/**
 * Proxy de Next.js — refresco de sesión de Supabase.
 *
 * Next.js 16 renombró `middleware.ts` a `proxy.ts`. El archivo va junto a `app/`
 * (aquí, dentro de `src/`), exporta una función llamada `proxy` y corre en el
 * runtime de Node.js, que no es configurable.
 *
 * ALCANCE DE ESTE ARCHIVO — leer antes de añadirle lógica
 *   Este proxy SOLO gestiona y refresca la sesión. **No autoriza.**
 *
 *   La documentación de Next.js es explícita: el proxy "should not be used as a
 *   full session management or authorization solution", y advierte que un cambio
 *   de `matcher` puede retirar silenciosamente la cobertura de una ruta.
 *
 *   Por eso la verificación de identidad vive en cada página protegida y en cada
 *   Server Action, vía `getClaims()`. Ver `src/lib/auth/session.ts`.
 *
 *       Proxy      -> gestión y refresco de sesión
 *       getClaims() -> verificación de identidad y autorización
 */
import { NextResponse, type NextRequest } from 'next/server'
import { createServerClient } from '@supabase/ssr'

export async function proxy(request: NextRequest) {
  let response = NextResponse.next({ request })

  const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL
  const supabaseKey = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY

  // Sin configuración no hay sesión que refrescar. Dejamos pasar la petición:
  // las páginas protegidas fallarán de forma explícita y legible.
  if (!supabaseUrl || !supabaseKey) {
    return response
  }

  const supabase = createServerClient(supabaseUrl, supabaseKey, {
    cookies: {
      getAll() {
        return request.cookies.getAll()
      },
      setAll(cookiesToSet, headers) {
        // 1. Escribir en la petición: así los Server Components de esta misma
        //    petición ven ya los tokens refrescados.
        for (const { name, value } of cookiesToSet) {
          request.cookies.set(name, value)
        }

        // 2. Reconstruir la respuesta a partir de la petición mutada.
        response = NextResponse.next({ request })

        // 3. Escribir en la respuesta: así el navegador recibe los tokens nuevos.
        for (const { name, value, options } of cookiesToSet) {
          response.cookies.set(name, value, options)
        }

        // 4. Aplicar las cabeceras anti-caché que entrega la librería
        //    (Cache-Control / Expires / Pragma). Sin esto, un CDN o proxy inverso
        //    podría cachear una respuesta con Set-Cookie y servir la sesión de un
        //    usuario a otro.
        for (const [key, value] of Object.entries(headers)) {
          response.headers.set(key, value)
        }
      },
    },
  })

  // Dispara el refresco del token si corresponde.
  //
  // Debe ocurrir ANTES de que la respuesta quede cerrada: si el refresco termina
  // después, `setAll` ya no puede escribir y la sesión actualizada se pierde,
  // provocando un refresco nuevo en cada petición.
  //
  // Se usa getClaims() -- nunca getSession() -- porque valida el JWT.
  await supabase.auth.getClaims()

  // CABECERAS DE NO-CACHÉ — estado medido (auditoría Codex)
  //
  //   Medición en Next.js 16.3.2, servidor de desarrollo:
  //
  //     GET/POST  /  /login  /signup  /app
  //       -> Cache-Control: no-cache, must-revalidate   (lo fija Next.js)
  //
  //   Next.js CONTROLA `Cache-Control` en las respuestas de rutas dinámicas y
  //   sobrescribe cualquier valor que fijemos aquí o en `next.config.headers()`.
  //   Ambas vías se probaron y ninguna surte efecto. Sí llegan otras cabeceras
  //   fijadas desde el proxy (verificado con una cabecera de sonda), de modo que
  //   `Pragma` y `Expires` de `setAll` sí se aplican.
  //
  //   Lectura de seguridad: `no-cache` obliga a revalidar contra el origen antes
  //   de reutilizar cualquier respuesta almacenada, luego una caché compartida no
  //   puede servir la sesión de un usuario a otro sin consultar al origen. Es más
  //   débil que `private, no-store` porque no impide el ALMACENAMIENTO.
  //
  //   Forzar `private, no-store` exigiría un cambio arquitectónico (servidor
  //   propio, Route Handlers en lugar de páginas, o un proxy inverso). Queda
  //   REGISTRADO COMO PENDIENTE, no resuelto en silencio.
  //
  //   Se conserva esta línea porque es correcta por contrato: si Next.js dejara
  //   de fijar la cabecera, la garantía base pasaría a aplicarse.
  if (!response.headers.has('Cache-Control')) {
    response.headers.set('Cache-Control', 'private, no-store')
  }

  return response
}

export const config = {
  matcher: [
    /*
     * Todas las rutas excepto:
     *  - _next/static      archivos estáticos
     *  - _next/image       optimización de imágenes
     *  - favicon.ico, sitemap.xml, robots.txt
     *  - archivos con extensión de imagen o fuente
     *
     * Nota: `_next/data` sigue pasando por el proxy aunque se excluya. Es
     * intencional en Next.js, para evitar proteger una página y olvidar su ruta
     * de datos.
     */
    '/((?!_next/static|_next/image|favicon\\.ico|sitemap\\.xml|robots\\.txt|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico|woff2?)$).*)',
  ],
}
