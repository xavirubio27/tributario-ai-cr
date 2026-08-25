'use client'

/**
 * Formulario de creación de empresa.
 *
 * Client Component únicamente porque necesita `useActionState` para mostrar
 * errores y estado de envío sin recargar. Todo lo demás en /app es Server
 * Component.
 */
import { useActionState } from 'react'
import { createCompanyAction } from '@/lib/companies/actions'
import { EMPTY_COMPANY_FORM_STATE } from '@/lib/companies/constants'
import { COMPANY_NAME_MAX_LENGTH } from '@/lib/companies/validation'

export function CreateCompanyForm() {
  const [state, formAction, pending] = useActionState(
    createCompanyAction,
    EMPTY_COMPANY_FORM_STATE,
  )

  return (
    <form action={formAction} className="space-y-3">
      <div className="flex gap-2">
        <input
          id="name"
          name="name"
          type="text"
          required
          maxLength={COMPANY_NAME_MAX_LENGTH}
          placeholder="Nombre de la empresa"
          aria-label="Nombre de la empresa"
          className="w-full rounded-md border border-neutral-300 bg-white px-3 py-2 text-sm text-neutral-900 placeholder:text-neutral-400 focus:border-neutral-500 focus:outline-none dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-100 dark:placeholder:text-neutral-600"
        />
        <button
          type="submit"
          disabled={pending}
          className="shrink-0 rounded-md bg-neutral-900 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-neutral-700 disabled:opacity-50 dark:bg-neutral-100 dark:text-neutral-900 dark:hover:bg-neutral-300"
        >
          {pending ? 'Creando…' : 'Crear'}
        </button>
      </div>

      {state.error && (
        <p
          role="alert"
          className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950 dark:text-red-300"
        >
          {state.error}
        </p>
      )}

      {state.notice && (
        <p
          role="status"
          className="rounded-md bg-neutral-100 px-3 py-2 text-sm text-neutral-700 dark:bg-neutral-800 dark:text-neutral-300"
        >
          {state.notice}
        </p>
      )}
    </form>
  )
}
