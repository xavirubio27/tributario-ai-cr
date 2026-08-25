import { defineConfig } from 'vitest/config'

export default defineConfig({
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
