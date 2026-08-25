import Link from 'next/link'
import { redirect } from 'next/navigation'
import { AuthForm } from '@/components/auth-form'
import { signInAction } from '@/lib/auth/actions'
import { getVerifiedUser } from '@/lib/auth/session'

export default async function LoginPage() {
  // Si ya hay identidad verificada, no tiene sentido mostrar el formulario.
  if (await getVerifiedUser()) {
    redirect('/app')
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-white px-6 dark:bg-neutral-950">
      <div className="w-full max-w-sm">
        <h1 className="text-lg font-semibold text-neutral-900 dark:text-neutral-100">
          Iniciar sesión
        </h1>
        <p className="mt-1 mb-6 text-sm text-neutral-500 dark:text-neutral-400">
          Asistente Tributario IA — Costa Rica
        </p>

        <AuthForm action={signInAction} submitLabel="Entrar" pendingLabel="Entrando…" />

        <p className="mt-6 text-sm text-neutral-500 dark:text-neutral-400">
          ¿No tienes cuenta?{' '}
          <Link className="underline underline-offset-4 hover:text-neutral-900 dark:hover:text-neutral-100" href="/signup">
            Crear cuenta
          </Link>
        </p>
      </div>
    </main>
  )
}
