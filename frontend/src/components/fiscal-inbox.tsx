/**
 * Bandeja de documentos fiscales.
 *
 * Server Component: no hay estado de cliente, no hay `fetch` del navegador y
 * no hay JWT en el bundle. Se renderiza lo que la lectura de servidor ya
 * validó.
 *
 * LO QUE ESTA LISTA NO DICE
 *   Nada de IVA, deducibilidad ni retenciones. Nada de ventas ni compras: la
 *   dirección del documento no está establecida —`direction` existe en la base
 *   pero vale `unknown`— y no se insinúa. Es visibilidad operativa.
 */
import Link from 'next/link'
import type { InboxItem, InboxResult } from '@/lib/fiscal/inbox-contract'
import {
  INBOX_EMPTY,
  INBOX_ERROR_MESSAGES,
  STATUS_LABELS,
  documentTypeLabel,
  type StatusTone,
} from '@/lib/fiscal/inbox-messages'

const TONO: Record<StatusTone, string> = {
  neutral: 'bg-neutral-100 text-neutral-700 dark:bg-neutral-800 dark:text-neutral-300',
  attention: 'bg-amber-50 text-amber-900 dark:bg-amber-950 dark:text-amber-200',
  error: 'bg-red-50 text-red-800 dark:bg-red-950 dark:text-red-300',
}

function fecha(iso: string | null): string | null {
  if (!iso) return null
  // Solo la parte de fecha: el reloj de pared se conserva tal cual lo declaró
  // el documento (ADR-039) y no se reinterpreta en otro huso.
  return iso.slice(0, 10)
}

function Etiqueta({ item }: { item: InboxItem }) {
  const { label, tone, mark } = STATUS_LABELS[item.operationalStatus]
  return (
    <span
      className={`inline-flex shrink-0 items-center gap-1 rounded-md px-2 py-0.5 text-xs font-medium ${TONO[tone]}`}
    >
      <span aria-hidden="true">{mark}</span>
      {label}
    </span>
  )
}

function Fila({ item }: { item: InboxItem }) {
  const tipo = documentTypeLabel(item.documentType)

  return (
    <li className="flex items-start justify-between gap-3 px-4 py-3">
      <div className="min-w-0">
        <p className="truncate text-sm font-medium text-neutral-900 dark:text-neutral-100">
          {tipo ?? 'Documento recibido'}
          {item.kind === 'document' && item.consecutiveNumber && (
            <span className="ml-2 font-normal text-neutral-500 dark:text-neutral-400">
              {item.consecutiveNumber}
            </span>
          )}
        </p>

        <p className="mt-0.5 text-xs text-neutral-500 dark:text-neutral-400">
          Recibido el {fecha(item.receivedAt)}
          {item.kind === 'document' && item.issuedAtLocal && (
            <> · Emitido el {fecha(item.issuedAtLocal)}</>
          )}
          {item.receiptCount > 1 && <> · {item.receiptCount} recepciones</>}
        </p>

        {item.kind === 'document' && item.reportedTotalDocument && (
          <p className="mt-1 text-sm text-neutral-700 dark:text-neutral-300">
            {/* Importe COMO CADENA. Convertirlo a número aquí destruiría el
                decimal exacto. Y se etiqueta como declarado por el documento:
                no es un cálculo nuestro. */}
            <span className="font-medium">
              {item.currencyCode} {item.reportedTotalDocument}
            </span>
            <span className="ml-1 text-xs text-neutral-500 dark:text-neutral-400">
              según el documento
            </span>
          </p>
        )}
      </div>

      <Etiqueta item={item} />
    </li>
  )
}

export function FiscalInbox({
  resultado,
  siguienteHref,
}: {
  resultado: InboxResult
  /** Ruta de la página siguiente, o `null` si no hay más. */
  siguienteHref: string | null
}) {
  if (!resultado.ok) {
    const { title, detail } = INBOX_ERROR_MESSAGES[resultado.category]
    return (
      <div
        role="alert"
        className="rounded-md bg-red-50 px-4 py-3 text-sm text-red-800 dark:bg-red-950 dark:text-red-300"
      >
        <p className="font-medium">
          <span aria-hidden="true">× </span>
          {title}
        </p>
        <p className="mt-0.5">{detail}</p>
      </div>
    )
  }

  const { items, counts } = resultado.page

  return (
    <div className="space-y-4">
      {(counts.needsAttention > 0 || counts.systemPending > 0) && (
        <div role="status" className="flex flex-wrap gap-4 text-sm">
          {counts.needsAttention > 0 && (
            <span className="text-amber-800 dark:text-amber-300">
              <span aria-hidden="true">! </span>
              Requieren atención: <strong>{counts.needsAttention}</strong>
            </span>
          )}
          {counts.systemPending > 0 && (
            <span className="text-neutral-600 dark:text-neutral-400">
              <span aria-hidden="true">… </span>
              Pendientes del sistema: <strong>{counts.systemPending}</strong>
            </span>
          )}
        </div>
      )}

      {items.length === 0 ? (
        <div className="rounded-md border border-dashed border-neutral-300 px-4 py-8 text-center dark:border-neutral-700">
          <p className="text-sm font-medium text-neutral-700 dark:text-neutral-300">
            {INBOX_EMPTY.title}
          </p>
          <p className="mt-1 text-sm text-neutral-500 dark:text-neutral-400">
            {INBOX_EMPTY.detail}
          </p>
        </div>
      ) : (
        <ul className="divide-y divide-neutral-200 rounded-md border border-neutral-200 dark:divide-neutral-800 dark:border-neutral-800">
          {items.map((item) => (
            <Fila
              key={item.kind === 'document' ? item.electronicDocumentId : item.sourceDocumentId}
              item={item}
            />
          ))}
        </ul>
      )}

      {/* Navegación de servidor: un enlace normal, no una llamada del
          navegador a FastAPI. El cursor viaja en la URL pero NUNCA se enseña
          como texto: es estado opaco del backend, no información de producto.
          Y no se inventa un número de página que el backend no da. */}
      {siguienteHref && (
        <nav aria-label="Paginación de documentos">
          <Link
            href={siguienteHref}
            className="inline-block rounded-md border border-neutral-300 px-4 py-2 text-sm font-medium text-neutral-900 hover:bg-neutral-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 dark:border-neutral-700 dark:text-neutral-100 dark:hover:bg-neutral-900"
          >
            Ver más
          </Link>
        </nav>
      )}
    </div>
  )
}
