'use client'

/**
 * Formulario de autenticación. Único componente cliente del checkpoint.
 *
 * Sin librería de componentes UI: la elección del design system es un checkpoint
 * aparte, previo a construir la interfaz real del producto.
 */
import { useActionState } from 'react'
import { EMPTY_AUTH_STATE, MIN_PASSWORD_LENGTH, type AuthState } from '@/lib/auth/constants'

type Props = {
  action: (prevState: AuthState, formData: FormData) => Promise<AuthState>
  submitLabel: string
  pendingLabel: string
  withConfirmPassword?: boolean
}

const inputClass =
  'w-full rounded-md border border-neutral-300 bg-white px-3 py-2 text-sm text-neutral-900 ' +
  'placeholder:text-neutral-400 focus:border-neutral-500 focus:outline-none ' +
  'dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-100 dark:placeholder:text-neutral-600'

const labelClass = 'block text-xs font-medium text-neutral-600 dark:text-neutral-400'

export function AuthForm({ action, submitLabel, pendingLabel, withConfirmPassword }: Props) {
  const [state, formAction, pending] = useActionState(action, EMPTY_AUTH_STATE)

  return (
    <form action={formAction} className="space-y-4">
      <div className="space-y-1">
        <label className={labelClass} htmlFor="email">
          Correo electrónico
        </label>
        <input
          className={inputClass}
          id="email"
          name="email"
          type="email"
          autoComplete="email"
          required
        />
      </div>

      <div className="space-y-1">
        <label className={labelClass} htmlFor="password">
          Contraseña
        </label>
        <input
          className={inputClass}
          id="password"
          name="password"
          type="password"
          autoComplete={withConfirmPassword ? 'new-password' : 'current-password'}
          minLength={withConfirmPassword ? MIN_PASSWORD_LENGTH : undefined}
          required
        />
        {withConfirmPassword && (
          <p className="text-xs text-neutral-400 dark:text-neutral-600">
            Mínimo {MIN_PASSWORD_LENGTH} caracteres.
          </p>
        )}
      </div>

      {withConfirmPassword && (
        <div className="space-y-1">
          <label className={labelClass} htmlFor="confirmPassword">
            Repetir contraseña
          </label>
          <input
            className={inputClass}
            id="confirmPassword"
            name="confirmPassword"
            type="password"
            autoComplete="new-password"
            minLength={MIN_PASSWORD_LENGTH}
            required
          />
        </div>
      )}

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

      <button
        type="submit"
        disabled={pending}
        className="w-full rounded-md bg-neutral-900 px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-neutral-700 disabled:opacity-50 dark:bg-neutral-100 dark:text-neutral-900 dark:hover:bg-neutral-300"
      >
        {pending ? pendingLabel : submitLabel}
      </button>
    </form>
  )
}
