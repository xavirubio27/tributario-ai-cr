/**
 * Doble de `next/cache` para los tests.
 *
 * POR QUÉ UN ALIAS Y NO `vi.mock`
 *   `next` es dependencia de `frontend/`, no de este paquete. `vi.mock('next/
 *   cache')` se registra bajo la ruta que resuelve DESDE AQUÍ, mientras que
 *   `actions.ts` resuelve otra dentro de `frontend/node_modules`: para el
 *   resolvedor son dos módulos distintos y el mock nunca llegaba a aplicarse.
 *   Un alias en `vitest.config.ts` hace que ambos lados vean este fichero.
 *
 * `revalidatePath` real exige el contexto de petición de Next, que no existe
 * en un test unitario.
 */

/** Rutas cuya revalidación se solicitó, en orden. */
export const revalidatedPaths: string[] = []

export function revalidatePath(ruta: string): void {
  revalidatedPaths.push(ruta)
}

export function resetRevalidated(): void {
  revalidatedPaths.length = 0
}
