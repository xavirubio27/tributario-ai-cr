import Link from 'next/link'
import { redirect } from 'next/navigation'
import { AuthForm } from '@/components/auth-form'
import { signUpAction } from '@/lib/auth/actions'
import { getVerifiedUser } from '@/lib/auth/session'

export default async function SignupPage() {
  if (await getVerifiedUser()) {
    redirect('/app')
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-white px-6 dark:bg-neutral-950">
      <div className="w-full max-w-sm">
        <h1 className="text-lg font-semibold text-neutral-900 dark:text-neutral-100">
          Crear cuenta
        </h1>
        <p className="mt-1 mb-6 text-sm text-neutral-500 dark:text-neutral-400">
          Asistente Tributario IA — Costa Rica
        </p>

        <AuthForm
          action={signUpAction}
          submitLabel="Crear cuenta"
          pendingLabel="Creando…"
          withConfirmPassword
        />

        <p className="mt-6 text-sm text-neutral-500 dark:text-neutral-400">
          ¿Ya tienes cuenta?{' '}
          <Link className="underline underline-offset-4 hover:text-neutral-900 dark:hover:text-neutral-100" href="/login">
            Iniciar sesión
          </Link>
        </p>
      </div>
    </main>
  )
}
