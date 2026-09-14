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

import { revalidatePath } from 'next/cache'

import { requireUser } from '@/lib/auth/session'
import type { UploadFiscalDocumentActionResult } from '@/lib/fiscal/contract'
import {
  RESULTADO_INDETERMINADO,
  RESULTADO_INTERNO,
  RESULTADO_SESION,
  interpretResponse,
} from '@/lib/fiscal/response'
import { validateUpload } from '@/lib/fiscal/validation'
import { BACKEND_TIMEOUT_MS, backendUrl, verifiedAccessToken } from '@/lib/server/backend'

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

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

  const backend = backendUrl()
  if (!backend) {
    // Fallo de configuración del servidor. No se inventa un `localhost` ni se
    // le cuenta al navegador qué falta.
    return RESULTADO_INTERNO
  }

  const token = await verifiedAccessToken()
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
        signal: AbortSignal.timeout(BACKEND_TIMEOUT_MS),
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

  const resultado = interpretResponse(respuesta.status, cuerpo)

  // Refrescar la bandeja SIEMPRE que exista evidencia durable, no solo cuando
  // todo fue bien. Un XSD inválido, un tipo no soportado o un conflicto de
  // clave también crearon un artefacto, y el usuario debe verlo aparecer; si
  // solo se revalidara el éxito, la bandeja se quedaría vieja justo en los
  // casos que hay que revisar.
  const hayEvidencia = resultado.ok || resultado.sourceDocumentId !== undefined
  if (hayEvidencia) {
    revalidatePath(`/app/${companyId}`)
  }

  return resultado
}
