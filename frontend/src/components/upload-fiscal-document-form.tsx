'use client'

/**
 * Subida de un comprobante electrónico.
 *
 * Client Component solo por `useActionState`: necesita estado de envío y
 * resultado sin recargar. Todo lo demás del workspace es Server Component.
 *
 * SIN PORCENTAJES INVENTADOS
 *   La acción es una sola llamada y no expone progreso real de subida.
 *   Mostrar una barra avanzando sería mentir sobre algo que no se mide, así
 *   que hay un único estado de carga honesto.
 *
 * EL IDENTIFICADOR NO SE ENSEÑA
 *   `sourceDocumentId` se conserva en el estado porque B3 lo necesitará para
 *   revisar o reprocesar, pero un UUID no le dice nada a nadie.
 */
import { useActionState, useId, useState } from 'react'
import { uploadFiscalDocumentAction } from '@/lib/fiscal/actions'
import { MAX_SOURCE_XML_BYTES_UI } from '@/lib/fiscal/contract'
import { XML_ACCEPT_HINT } from '@/lib/fiscal/validation'
import { messageFor, type UploadTone } from '@/lib/fiscal/messages'
import { resultadoVisible } from '@/lib/fiscal/display'

const ESTILO_POR_TONO: Record<UploadTone, string> = {
  success: 'bg-emerald-50 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-200',
  info: 'bg-neutral-100 text-neutral-800 dark:bg-neutral-800 dark:text-neutral-200',
  attention: 'bg-amber-50 text-amber-900 dark:bg-amber-950 dark:text-amber-200',
  error: 'bg-red-50 text-red-800 dark:bg-red-950 dark:text-red-300',
}

/** El estado NUNCA se comunica solo con el color. */
const ICONO_POR_TONO: Record<UploadTone, string> = {
  success: '✓',
  info: '•',
  attention: '!',
  error: '×',
}

function tamañoLegible(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export function UploadFiscalDocumentForm({ companyId }: { companyId: string }) {
  const [state, formAction, pending] = useActionState(
    uploadFiscalDocumentAction.bind(null, companyId),
    null,
  )
  const [seleccionado, setSeleccionado] = useState<File | null>(null)
  // El resultado se oculta en cuanto se elige OTRO archivo: si no, «Procesado
  // correctamente» seguiría en pantalla describiendo el archivo anterior y
  // pareciendo hablar del recién seleccionado.
  const [resultadoFresco, setResultadoFresco] = useState(true)
  const inputId = useId()

  // Aviso ANTES de la red. La autoridad sigue siendo el backend.
  const demasiadoGrande =
    seleccionado !== null && seleccionado.size > MAX_SOURCE_XML_BYTES_UI
  const vacio = seleccionado !== null && seleccionado.size === 0
  const bloqueado = pending || seleccionado === null || demasiadoGrande || vacio

  const visible = resultadoVisible(state, resultadoFresco, pending)
  const mensaje = visible ? messageFor(visible) : null

  return (
    <form
      action={(datos) => {
        setResultadoFresco(true)   // el resultado de ESTE envío sí se muestra
        formAction(datos)
      }}
      className="space-y-4"
      aria-busy={pending}
    >
      <div className="space-y-2">
        <label
          htmlFor={inputId}
          className="block text-sm font-medium text-neutral-900 dark:text-neutral-100"
        >
          Archivo XML del comprobante
        </label>
        <input
          id={inputId}
          name="file"
          type="file"
          accept={XML_ACCEPT_HINT}
          disabled={pending}
          onChange={(e) => {
            setSeleccionado(e.target.files?.[0] ?? null)
            setResultadoFresco(false)
          }}
          aria-describedby={`${inputId}-ayuda`}
          className="block w-full text-sm text-neutral-700 file:mr-3 file:rounded-md file:border-0 file:bg-neutral-900 file:px-4 file:py-2 file:text-sm file:font-medium file:text-white hover:file:bg-neutral-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-neutral-900 disabled:opacity-50 dark:text-neutral-300 dark:file:bg-neutral-100 dark:file:text-neutral-900 dark:hover:file:bg-neutral-300 dark:focus-visible:outline-neutral-100"
        />
        <p id={`${inputId}-ayuda`} className="text-xs text-neutral-500 dark:text-neutral-400">
          Un archivo por vez. Máximo {tamañoLegible(MAX_SOURCE_XML_BYTES_UI)}.
        </p>
      </div>

      {seleccionado && (
        <p className="text-sm text-neutral-700 dark:text-neutral-300">
          <span className="font-medium">{seleccionado.name}</span>{' '}
          <span className="text-neutral-500 dark:text-neutral-400">
            ({tamañoLegible(seleccionado.size)})
          </span>
        </p>
      )}

      {demasiadoGrande && (
        <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-800 dark:bg-red-950 dark:text-red-300">
          <span aria-hidden="true">× </span>
          El archivo supera el máximo de {tamañoLegible(MAX_SOURCE_XML_BYTES_UI)}.
        </p>
      )}

      {vacio && (
        <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-800 dark:bg-red-950 dark:text-red-300">
          <span aria-hidden="true">× </span>
          El archivo está vacío.
        </p>
      )}

      <button
        type="submit"
        disabled={bloqueado}
        className="rounded-md bg-neutral-900 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-neutral-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-neutral-900 disabled:opacity-50 dark:bg-neutral-100 dark:text-neutral-900 dark:hover:bg-neutral-300 dark:focus-visible:outline-neutral-100"
      >
        {pending ? 'Enviando…' : 'Subir comprobante'}
      </button>

      {mensaje && (
        <div
          role={mensaje.tone === 'error' ? 'alert' : 'status'}
          className={`rounded-md px-3 py-2 text-sm ${ESTILO_POR_TONO[mensaje.tone]}`}
        >
          <p className="font-medium">
            <span aria-hidden="true">{ICONO_POR_TONO[mensaje.tone]} </span>
            {mensaje.title}
          </p>
          <p className="mt-0.5">{mensaje.detail}</p>
        </div>
      )}
    </form>
  )
}
