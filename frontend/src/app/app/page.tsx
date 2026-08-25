/**
 * Pantalla del usuario autenticado.
 *
 * Server Component. Verifica identidad server-side con `getClaims()` mediante
 * `requireUser()`; no depende del proxy para estar protegida.
 *
 * Todavía NO es el dashboard fiscal: no hay facturas, ni IVA, ni métricas.
 */
import { requireUser } from '@/lib/auth/session'
import { SignOutForm } from '@/components/sign-out-form'
import { listCompanies } from '@/lib/companies/queries'
import { CreateCompanyForm } from '@/components/create-company-form'

export default async function AppPage() {
  const user = await requireUser()
  const { companies, error } = await listCompanies()

  return (
    <main className="min-h-screen bg-white px-6 py-12 dark:bg-neutral-950">
      <div className="mx-auto w-full max-w-xl">
        {/* Cabecera */}
        <header className="flex items-start justify-between gap-4 border-b border-neutral-200 pb-6 dark:border-neutral-800">
          <div className="min-w-0">
            <h1 className="text-lg font-semibold text-neutral-900 dark:text-neutral-100">
              Asistente Tributario IA
            </h1>
            <p className="mt-0.5 truncate text-sm text-neutral-500 dark:text-neutral-400">
              {user.email ?? 'Sesión autenticada'}
            </p>
          </div>

          <SignOutForm />
        </header>

        {/* Mis empresas */}
        <section className="mt-10">
          <h2 className="text-sm font-semibold text-neutral-900 dark:text-neutral-100">
            Mis empresas
          </h2>

          {error ? (
            <p
              role="alert"
              className="mt-4 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950 dark:text-red-300"
            >
              {error}
            </p>
          ) : companies.length === 0 ? (
            <p className="mt-4 rounded-md border border-dashed border-neutral-300 px-4 py-8 text-center text-sm text-neutral-500 dark:border-neutral-700 dark:text-neutral-400">
              No tienes empresas todavía.
            </p>
          ) : (
            <ul className="mt-4 divide-y divide-neutral-200 rounded-md border border-neutral-200 dark:divide-neutral-800 dark:border-neutral-800">
              {companies.map((company) => (
                <li
                  key={company.id}
                  className="px-4 py-3 text-sm font-medium text-neutral-900 dark:text-neutral-100"
                >
                  {company.name}
                </li>
              ))}
            </ul>
          )}
        </section>

        {/* Crear empresa */}
        <section className="mt-10">
          <h2 className="mb-3 text-sm font-semibold text-neutral-900 dark:text-neutral-100">
            Crear empresa
          </h2>
          <CreateCompanyForm />
        </section>

        <p className="mt-12 text-xs text-neutral-400 dark:text-neutral-600">
          Fase 1 — Infraestructura, autenticación y empresa.
        </p>
      </div>
    </main>
  )
}
