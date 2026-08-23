export default function Home() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-white px-6 dark:bg-neutral-950">
      <div className="w-full max-w-md text-center">
        <h1 className="text-2xl font-semibold tracking-tight text-neutral-900 dark:text-neutral-100">
          Asistente Tributario IA
        </h1>
        <p className="mt-1 text-sm text-neutral-500 dark:text-neutral-400">
          Costa Rica
        </p>

        <hr className="my-8 border-neutral-200 dark:border-neutral-800" />

        <p className="text-sm text-neutral-600 dark:text-neutral-400">
          Proyecto en desarrollo.
        </p>
        <p className="mt-2 text-xs text-neutral-400 dark:text-neutral-600">
          Fase 1 — Infraestructura, autenticación y empresa.
        </p>
      </div>
    </main>
  );
}
