/**
 * Lectura de la bandeja desde el servidor.
 *
 * El navegador NO habla con FastAPI: esto corre en el Server Component del
 * workspace, con el token verificado que nunca llega al bundle. Sin CORS y sin
 * consultas directas a las tablas fiscales de Supabase — los datos fiscales
 * pasan por FastAPI (ADR-001).
 */
import {
  PAGE_SIZE_DEFAULT,
  type InboxResult,
} from '@/lib/fiscal/inbox-contract'
import {
  LECTURA_INTERNA,
  LECTURA_PROHIBIDA,
  LECTURA_TEMPORAL,
  interpretInbox,
} from '@/lib/fiscal/inbox-response'
import { BACKEND_TIMEOUT_MS, backendUrl, verifiedAccessToken } from '@/lib/server/backend'

export async function fetchInbox(
  companyId: string,
  opciones: { limit?: number; cursor?: string } = {},
): Promise<InboxResult> {
  const backend = backendUrl()
  if (!backend) {
    return LECTURA_INTERNA
  }

  const token = await verifiedAccessToken()
  if (!token) {
    return LECTURA_PROHIBIDA
  }

  const params = new URLSearchParams({
    limit: String(opciones.limit ?? PAGE_SIZE_DEFAULT),
  })
  if (opciones.cursor) params.set('cursor', opciones.cursor)

  let respuesta: Response
  try {
    respuesta = await fetch(
      `${backend}/companies/${companyId}/fiscal-documents?${params}`,
      {
        headers: { Authorization: `Bearer ${token}` },
        cache: 'no-store',
        redirect: 'error',
        signal: AbortSignal.timeout(BACKEND_TIMEOUT_MS),
      },
    )
  } catch {
    // El texto del error puede contener la URL del backend: se descarta.
    return LECTURA_TEMPORAL
  }

  let cuerpo: unknown = null
  try {
    cuerpo = await respuesta.json()
  } catch {
    cuerpo = null
  }
  return interpretInbox(respuesta.status, cuerpo)
}
