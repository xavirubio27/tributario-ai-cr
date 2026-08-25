import Link from 'next/link'
import { getVerifiedUser } from '@/lib/auth/session'

export default async function Home() {
  const user = await getVerifiedUser()

  const linkClass =
    'rounded-md border border-neutral-300 px-4 py-2 text-sm font-medium text-neutral-700 ' +
    'transition-colors hover:bg-neutral-100 dark:border-neutral-700 dark:text-neutral-300 ' +
    'dark:hover:bg-neutral-900'

  return (
    <main className="flex min-h-screen items-center justify-center bg-white px-6 dark:bg-neutral-950">
      <div className="w-full max-w-md text-center">
        <h1 className="text-2xl font-semibold tracking-tight text-neutral-900 dark:text-neutral-100">
          Asistente Tributario IA
        </h1>
        <p className="mt-1 text-sm text-neutral-500 dark:text-neutral-400">Costa Rica</p>

        <hr className="my-8 border-neutral-200 dark:border-neutral-800" />

        <p className="text-sm text-neutral-600 dark:text-neutral-400">Proyecto en desarrollo.</p>
        <p className="mt-2 text-xs text-neutral-400 dark:text-neutral-600">
          Fase 1 — Infraestructura, autenticación y empresa.
        </p>

        <div className="mt-8 flex justify-center gap-3">
          {user ? (
            <Link className={linkClass} href="/app">
              Ir a la aplicación
            </Link>
          ) : (
            <>
              <Link className={linkClass} href="/login">
                Iniciar sesión
              </Link>
              <Link className={linkClass} href="/signup">
                Crear cuenta
              </Link>
            </>
          )}
        </div>
      </div>
    </main>
  )
}
