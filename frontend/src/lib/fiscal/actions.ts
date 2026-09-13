'use server'

/**
 * Server Action de subida fiscal.
 *
 * ES LA FRONTERA WEB, NO UNA SEGUNDA TUBERÍA
 *   El navegador NUNCA habla con FastAPI. Esta acción recibe el `FormData`,
 *   comprueba su estructura, reenvía los bytes exactos con el JWT y traduce la
 *   respuesta. No parsea XML, no valida contra XSD y no consulta datos
 *   fiscales en Supabase: los datos fiscales pasan por FastAPI (ADR-001).
 *
 * POR QUÉ AQUÍ Y NO EN EL NAVEGADOR
 *   El JWT vive en cookies `httpOnly` que el navegador no puede leer, la URL
 *   del backend no debe llegar al bundle, y así no hace falta CORS.
 *
 * SIN REINTENTOS AUTOMÁTICOS
 *   C2 conserva cada recepción como evidencia. Un reintento invisible de
 *   transporte crearía un `SourceDocument` de más por un fallo de red. El
 *   reintento explícito del usuario sí es legítimo.
 */

import { createClient } from '@/lib/supabase/server'
import { requireUser } from '@/lib/auth/session'
import type { UploadFiscalDocumentActionResult } from '@/lib/fiscal/contract'
import {
  RESULTADO_INDETERMINADO,
  RESULTADO_INTERNO,
  RESULTADO_SESION,
  interpretResponse,
} from '@/lib/fiscal/response'
import { validateUpload } from '@/lib/fiscal/validation'

/** Un XML pequeño se procesa en mucho menos; esto es el techo, no lo normal. */
const TIMEOUT_MS = 30_000

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

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
async function tokenVerificado(): Promise<string | null> {
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

export async function uploadFiscalDocumentAction(
  companyId: string,
  _prevState: UploadFiscalDocumentActionResult | null,
  formData: FormData,
): Promise<UploadFiscalDocumentActionResult> {
  // Verificación explícita: un cambio de `matcher` en el proxy no debe poder
  // dejar esta acción sin protección.
  await requireUser()

  if (!UUID.test(companyId)) {
    return { ok: false, code: 'invalid_request', category: 'invalid_request' }
  }

  const validacion = validateUpload(formData)
  if (!validacion.ok) {
    return { ok: false, ...validacion.failure }
  }

  const backend = process.env.BACKEND_URL
  if (!backend) {
    // Fallo de configuración del servidor. No se inventa un `localhost` ni se
    // le cuenta al navegador qué falta.
    return RESULTADO_INTERNO
  }

  const token = await tokenVerificado()
  if (!token) {
    return RESULTADO_SESION
  }

  // Los BYTES EXACTOS. Sin `text()`, sin decodificar, sin normalizar saltos de
  // línea: la huella se calcula sobre lo que llegó y el parser mira lo mismo.
  const bytes = await validacion.file.arrayBuffer()

  let respuesta: Response
  try {
    respuesta = await fetch(
      `${backend}/companies/${companyId}/fiscal-documents`,
      {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/xml',
        },
        body: bytes,
        cache: 'no-store',
        // No seguir una redirección con un Bearer adjunto.
        redirect: 'error',
        signal: AbortSignal.timeout(TIMEOUT_MS),
      },
    )
  } catch {
    // NO SABEMOS QUÉ PASÓ. `fetch` rechaza igual si la petición no salió, si
    // salió y se perdió la respuesta, o si venció el temporizador -- y en los
    // dos últimos casos el documento pudo quedar capturado. Devolver
    // `temporary` aquí hacía que la interfaz afirmara «guardamos el documento»
    // sin que nadie lo hubiera confirmado.
    //
    // El error se descarta a propósito: su texto puede contener la URL del
    // backend. Sin reintento -- crearía evidencia duplicada.
    return RESULTADO_INDETERMINADO
  }

  let cuerpo: unknown = null
  try {
    cuerpo = await respuesta.json()
  } catch {
    cuerpo = null      // no era JSON; lo resuelve `interpretResponse`
  }

  return interpretResponse(respuesta.status, cuerpo)
}
