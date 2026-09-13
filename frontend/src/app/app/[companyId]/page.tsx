/**
 * Workspace de una empresa.
 *
 * Server Component. Verifica identidad con `requireUser()`; no depende del
 * proxy para estar protegida.
 *
 * LO QUE SE VE AQUÍ NO ES AUTORIZACIÓN
 *   La lista de empresas sirve para navegar y para poner un nombre en la
 *   cabecera. Quien edite el identificador de la URL no gana nada: la
 *   autoridad es RLS en PostgreSQL, a través de FastAPI, y un intento sin
 *   permiso devuelve 403 sin filtrar si la empresa existe.
 *
 * Todavía NO es un dashboard fiscal: no hay IVA, ni calendario, ni bandeja de
 * documentos.
 */
import Link from 'next/link'
import { requireUser } from '@/lib/auth/session'
import { listCompanies } from '@/lib/companies/queries'
import { UploadFiscalDocumentForm } from '@/components/upload-fiscal-document-form'

export default async function CompanyWorkspacePage({
  params,
}: {
  params: Promise<{ companyId: string }>
}) {
  await requireUser()
  const { companyId } = await params
  const { companies } = await listCompanies()
  const empresa = companies.find((c) => c.id === companyId)

  return (
    <main className="min-h-screen bg-white px-6 py-12 dark:bg-neutral-950">
      <div className="mx-auto w-full max-w-xl">
        <nav className="mb-6">
          <Link
            href="/app"
            className="text-sm text-neutral-500 underline-offset-4 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 dark:text-neutral-400"
          >
            ← Mis empresas
          </Link>
        </nav>

        <header className="border-b border-neutral-200 pb-6 dark:border-neutral-800">
          <h1 className="text-lg font-semibold text-neutral-900 dark:text-neutral-100">
            {empresa?.name ?? 'Empresa'}
          </h1>
          {!empresa && (
            <p className="mt-1 text-sm text-neutral-500 dark:text-neutral-400">
              No aparece entre tus empresas.
            </p>
          )}
        </header>

        <section className="mt-10">
          <h2 className="text-sm font-semibold text-neutral-900 dark:text-neutral-100">
            Documentos fiscales
          </h2>
          <p className="mt-1 mb-5 text-sm text-neutral-500 dark:text-neutral-400">
            Sube un comprobante electrónico en XML. Conservamos el archivo tal cual
            lo recibimos.
          </p>
          <UploadFiscalDocumentForm companyId={companyId} />
        </section>
      </div>
    </main>
  )
}
