/**
 * Enlace a la página siguiente de la bandeja.
 *
 * Módulo PURO, extraído de la página para poder probarlo sin renderizar React
 * —este repositorio no tiene renderizador configurado y no se añade uno por
 * esto—.
 *
 * El cursor viaja en la URL porque la navegación es de SERVIDOR: un enlace
 * normal, no una llamada del navegador a FastAPI. Eso hace que el botón
 * «atrás» funcione sin escribir nada. Pero es estado opaco del backend y
 * **nunca** se muestra como texto de producto.
 */

export type ContextoBandeja = {
  companyId: string
  nextCursor: string | null
  /** Filtro vigente, si la interfaz llega a exponerlo. Se conserva al pasar
   *  de página: perderlo devolvería al usuario una lista que no pidió. */
  status?: string | null
}

export function siguientePaginaHref({
  companyId,
  nextCursor,
  status,
}: ContextoBandeja): string | null {
  if (!nextCursor) {
    return null
  }
  const params = new URLSearchParams()
  params.set('documentCursor', nextCursor)
  if (status) {
    params.set('documentStatus', status)
  }
  return `/app/${companyId}?${params.toString()}`
}
