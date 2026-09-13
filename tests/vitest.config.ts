import path from 'node:path'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  resolve: {
    alias: {
      /**
       * El alias `@/` del frontend, para que sus módulos se puedan importar
       * aquí tal cual están escritos.
       *
       * La alternativa era obligar al código de producción a usar rutas
       * relativas para ser testeable, que es deformarlo para acomodar al
       * ejecutor de tests. Los módulos PUROS del frontend sí lo evitan a
       * propósito -- ver `companies/validation.ts` --, pero una Server Action
       * no puede: importa el cliente de Supabase y la sesión.
       */
      '@': path.resolve(import.meta.dirname, '../frontend/src'),
    },
  },
  test: {
    /**
     * Las tres suites comparten el MISMO proyecto Supabase de desarrollo y la
     * misma IP. Ejecutarlas en paralelo multiplica la ráfaga de peticiones de
     * autenticación contra un límite compartido:
     *
     *   [auth.rate_limit] sign_in_sign_ups = 30  (por 5 min y por IP)
     *
     * Verificado empíricamente: el intento 33 devuelve
     * `429 over_request_rate_limit`.
     *
     * Serializar no elimina el límite -- lo reparte en el tiempo y evita que
     * tres arranques simultáneos lo consuman de golpe. Es la mitigación más
     * simple disponible sin tocar límites de seguridad.
     */
    fileParallelism: false,
    sequence: { concurrent: false },
    testTimeout: 30_000,
    hookTimeout: 60_000,
  },
})
