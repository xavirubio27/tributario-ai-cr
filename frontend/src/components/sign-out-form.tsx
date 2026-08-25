'use client'

/**
 * Botón de cierre de sesión.
 *
 * Client Component porque `signOutAction` puede fallar y el usuario debe verlo:
 * un logout que falla en silencio deja cookies de sesión potencialmente válidas
 * mientras la interfaz aparenta lo contrario.
 */
import { useActionState } from 'react'
import { signOutAction } from '@/lib/auth/actions'
import { EMPTY_AUTH_STATE } from '@/lib/auth/constants'

export function SignOutForm() {
  const [state, formAction, pending] = useActionState(signOutAction, EMPTY_AUTH_STATE)

  return (
    <div className="flex flex-col items-end gap-2">
      <form action={formAction}>
        <button
          type="submit"
          disabled={pending}
          className="shrink-0 rounded-md border border-neutral-300 px-3 py-1.5 text-sm font-medium text-neutral-700 transition-colors hover:bg-neutral-100 disabled:opacity-50 dark:border-neutral-700 dark:text-neutral-300 dark:hover:bg-neutral-900"
        >
          {pending ? 'Cerrando…' : 'Cerrar sesión'}
        </button>
      </form>

      {state.error && (
        <p
          role="alert"
          className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950 dark:text-red-300"
        >
          {state.error}
        </p>
      )}
    </div>
  )
}
