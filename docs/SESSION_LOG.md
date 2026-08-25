# SESSION LOG

> Historial cronológico del proyecto. Se añade una entrada **al cerrar cada día de
> construcción**. Solo hechos verificables contra Git, migraciones, tests y árbol de
> trabajo — no narrativa de conversación.
>
> El estado **actual** vive en [PROJECT_STATE.md](PROJECT_STATE.md). Este archivo es el
> pasado; aquel es el presente.

---

## 2026-08-22 — Day 1

### Completed
- Estructura del repositorio: `docs/` `frontend/` `backend/` `tax-engine/` `tests/`
- Documentación fundacional: `README.md`, `PRODUCT_SPEC.md`, `ARCHITECTURE.md`,
  `AI_INSTRUCTIONS.md`, `CLAUDE.md`, `ROADMAP.md`
- `docs/DECISIONS.md` (ADR-001 a ADR-016) y `docs/GLOSSARY.md`
- `.gitignore` preventivo, con excepción explícita para `.env.example`
- Commit `4a80ca5 — docs: establish project foundation` (13 archivos, 2 823 líneas)

### Decisions
- ADR-001 a ADR-010 aceptadas: camino único a datos fiscales, RLS como mecanismo de
  aislamiento, `reported_*` vs `computed_*`, `as_of_date` + versión de regla, Tax Engine
  aislado, capa anticorrupción en la ingesta, documento original inmutable con hash,
  decimal exacto, Knowledge Base compartida, `AI_INSTRUCTIONS.md` como fuente de verdad
- ADR-011 a ADR-016 registradas como pendientes
- Idioma: documentación en español; código e identificadores en inglés
- Ninguna tasa, artículo ni referencia normativa entra sin fuente oficial verificada

### Tests
- Ninguno. No había código.

### Issues / discoveries
- Se detectaron y documentaron tensiones de diseño antes de implementar: RLS frente a
  `service_role`, doble camino de acceso a datos, y la distinción `reported`/`computed`
  como inconsistencia latente del roadmap (dashboard antes que Tax Engine)
- El push a `origin/main` **falló por autenticación** durante la sesión (sin `gh`, sin
  claves SSH, sin credencial válida). El usuario lo completó después: `4a80ca5` está
  verificado en `origin/main`

### Next
- Day 2: infraestructura, autenticación y modelo de empresa

---

## 2026-08-23 — Day 2

### Completed
- **Supabase DEVELOPMENT alojado** enlazado; CLI fijada en `package.json` raíz
- **Esquema de tenancy**: `public.companies`, `public.company_memberships` (N:M, rol
  `owner`, índices para RLS)
- **RLS activa** en ambas tablas, con `private.is_company_member()` como helper
  `security definer` para evitar recursión
- **Remediación de mínimo privilegio**: `anon` sin privilegios; `authenticated` solo
  `SELECT`
- **Hardening pre-C**: `public.create_company` pasó a `SECURITY INVOKER`, delegando en
  `private.create_company_impl` (`SECURITY DEFINER`, schema no expuesto)
- **5 migraciones** sincronizadas local/remoto
- **Tests de aislamiento A/B: 11/11 PASS**
- **Next.js foundation**: Next 16.3.2, React 19, TypeScript, Tailwind 4, ESLint, App
  Router, `src/`; clientes Supabase browser/server preparados
- **lint / typecheck / build: PASS**; home local sirviendo en `http://localhost:3000`
- Sistema de continuidad: `docs/PROJECT_STATE.md` y `docs/SESSION_LOG.md`

### Decisions
- **ADR-017** — `companies` y `company_memberships` son datos de identidad y tenancy,
  **no fiscales**; por eso pueden usar Supabase directamente bajo RLS sin incumplir
  ADR-001. Los datos fiscales futuros sí pasarán por la capa de aplicación
- **ADR-018** — proyecto alojado de desarrollo; entorno local con Docker **diferido**,
  a reconsiderar cuando crezca la suite de integración
- **ADR-019** — confirmación de email desactivada **solo en desarrollo**; la política de
  producción sigue sin decidir
- ADR-012 y ADR-015 pasan a **parcialmente resueltas**: resuelto el acceso directo a
  Supabase y la relación N:M con rol `owner`; abiertos la propagación del JWT a FastAPI
  y los roles adicionales
- **Regla 15** en `AI_INSTRUCTIONS.md`: revisar el diff completo antes de aplicar
  configuración remota
- Se decidió **no** revocar `EXECUTE` sobre `private.is_company_member`: los grants son
  mínimos y el experimento no compensa

### Tests
- `tests/rls/isolation.test.ts` — **11/11 PASS** (vitest, clave publicable, sesión propia
  por usuario, sin `service_role`)
- Verificado que RLS **filtra** en SELECT (0 filas, sin error) y **deniega** en escritura
  (`42501`), que son cosas distintas
- Caso 11 añadido como **control de validez**: User B sí puede operar en su propio
  tenant, lo que descarta que los casos negativos pasen por una sesión rota

### Issues / discoveries
- **`config push` empuja el archivo completo, no solo lo editado.** Un push desactivó
  MFA TOTP y redujo `otp_length` de forma no intencionada. Remediado, y origen de la
  Regla 15
- **`authenticated` conservaba `TRUNCATE`, `TRIGGER` y `REFERENCES`**: el `revoke` inicial
  solo cubría INSERT/UPDATE/DELETE, mientras que los privilegios por defecto conceden
  `ALL`. `TRUNCATE` no está sujeto a RLS. Remediado
- **`frontend/.env.example` quedaba ignorado**: el `.gitignore` de `create-next-app`
  (`.env*`) tiene prioridad sobre la negación de la raíz. Corregido
- Warning de build por múltiples lockfiles: resuelto fijando `turbopack.root`
- Los patrones de Supabase + Next.js habían cambiado respecto a lo habitual:
  `@supabase/ssr` (no auth-helpers), `getClaims()` (no `getSession()`), **`proxy.ts`**
  (no `middleware.ts`, renombrado en Next.js 16) y `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`
- El advisor de seguridad quedó **sin hallazgos** tras el hardening; después apareció
  *Leaked Password Protection Disabled*, que **requiere plan Pro** y no es accionable en
  Free ni fue causado por nuestra configuración
- Coste previsto en ADR-018 materializándose: los usuarios de prueba se acumulan en el
  proyecto de desarrollo y no hay limpieza sin `service_role`

### Cierre del día — Checkpoints E, F y G

**E — Authentication.** `proxy.ts` (Next.js 16 renombró `middleware.ts`), refresco de
sesión con `getClaims()` y aplicación de las cabeceras anti-caché de `setAll`. Signup,
login, logout y ruta protegida `/app`. Separación explícita: el proxy gestiona sesión,
`getClaims()` autoriza. Cada página protegida y cada Server Action verifica identidad
por su cuenta. 9/9 tests.

**F — Company UI.** `/app` lista y crea empresas. Lectura sin filtro por usuario: RLS
decide. Escritura exclusivamente por `create_company()`; no existe INSERT directo ni
sería posible (`authenticated` solo tiene SELECT). Validación en módulo puro
compartido por la acción y los tests. 10/10 tests.

**G — Auditoría y cierre.** Regresión, smoke test, advisors y auditoría interna.

### Tests — estado final
- **30/30 PASS**: 11 RLS + 9 Auth + 10 Company
- Smoke test del flujo completo: **16/16 PASS** (HTTP + datos)
- 10 ejecuciones de regresión; las que fallaron lo hicieron por el límite de tasa, con
  causa visible

### Problemas encontrados y corregidos
- **Fragilidad de tests: causa confirmada.** `sign_in_sign_ups = 30` por 5 min e IP.
  Reproducido: `429 over_request_rate_limit` en `signUp`. Antes se manifestaba como
  `invalid input syntax for type uuid: ""` —cascada que ocultaba la causa—. Corregido
  con `tests/support/harness.ts` (fallo rápido, error original visible, sin
  identificadores vacíos) y serialización de suites. **Mitigado, no eliminado.**
- `ECONNREFUSED` crudo cuando el servidor no estaba arrancado → guarda legible.
- Caso G del build buscaba *palabras* (`sb_secret_`) y daba falso positivo con los
  comentarios de `@supabase/auth-js`; reescrito para detectar *forma de credencial*,
  con autotest del detector.

### Auditoría interna
- Sin `getSession()` en servidor · sin `service_role` · sin `sb_secret` · sin INSERT
  directo · sin `user_id` desde el cliente · el frontend nunca consulta
  `company_memberships` · errores de auth con mensajes fijos que no permiten enumerar
  cuentas · solo 2 Client Components, ambos justificados
- **Pendiente:** `requiredEnv` duplicado en `client.ts` y `server.ts`; el paquete de
  tests no puede ejecutar `tsc` por falta de `@types/node`. Ninguno corregido: quedan
  para la auditoría externa
- `@supabase/supabase-js` sin import directo, pero es **peer dependency obligatoria**
  de `@supabase/ssr`: no es dependencia muerta

### Estado final
- Advisors: Performance sin hallazgos; Security solo *Leaked Password Protection*,
  limitación del plan Free, pendiente para producción
- 5 migraciones sincronizadas local/remoto · lint, typecheck y build en exit 0
- **`npm run` falla con exit 127 por anomalía de PATH del entorno**, no del proyecto
- 82 usuarios de prueba acumulados en DEV: disparador previsto en ADR-018

### Correcciones posteriores a la auditoría de Codex

La sesión anterior quedó congelada al empezar estas correcciones; ninguna estaba
aplicada. Se retomaron desde el estado real del repositorio.

- **Detector JWT `service_role`: falso negativo confirmado y corregido.**
  `decodePayload` hacía `b64url.slice(3)` para saltar el prefijo `eyJ`, lo que
  desalineaba el base64url y devolvía basura: el detector **nunca** disparaba. Se
  demostró con un JWT sintético antes de tocar nada. Ahora decodifica el segmento
  completo, compara `payload.role === 'service_role'` y lleva seis autotests
  (positivo, negativo, cadena suelta, dos malformados y secret key). Todos los JWT
  de prueba son sintéticos con firma falsa.
- **Asserts de código explícito.** `expect(error).not.toBeNull()` permitía que un
  fallo de red o de rate limit diera un PASS falso. Se midieron los códigos reales
  y ahora se exige `42501` en las denegaciones por privilegio y `22023` en la
  validación del RPC. El SELECT filtrado por RLS sigue exigiendo 0 filas y
  `error === null`.
- **Fail-fast con fixtures.** La creación de Company A, prerrequisito de cinco
  casos, pasó al `beforeAll`; en la suite de empresas va en un `describe` anidado
  porque el caso A debe observar el estado vacío antes. Un fallo de setup ahora
  **impide** los casos dependientes en lugar de propagar identificadores vacíos.
- **Logout.** `signOutAction` ignoraba el resultado de `signOut()` y redirigía
  igualmente: fingía éxito mientras las cookies podían seguir siendo válidas. Ahora
  captura el error, devuelve un mensaje genérico y solo redirige si tuvo éxito.
  Nuevo componente `SignOutForm` para mostrarlo, más un caso `[STATIC]` que verifica
  que la rama de error precede al `redirect`.
- **Typecheck del paquete de tests.** Añadidos `tsconfig.json`, `@types/node@22.20.1`
  —alineado con el runtime Node 22— y `typescript@5.9.3`. `tsc --noEmit` en exit 0 e
  incluye el módulo de validación importado desde `frontend/src`. Sin workspaces.
- **ESLint.** `argsIgnorePattern: '^_'` para los parámetros que `useActionState`
  impone por contrato. Lint queda sin errores **ni advertencias**.

### Cabeceras de caché — investigado, no resuelto

Medido en Next.js 16.3.2: todas las rutas dinámicas responden
`Cache-Control: no-cache, must-revalidate`. **Next.js sobrescribe la cabecera**, tanto
la que fija el proxy como la de `next.config.headers()`; ambas vías se probaron y
ninguna surte efecto. Una cabecera de sonda sí llegó, lo que confirma que el problema
es específico de `Cache-Control` y no del proxy.

`no-cache` obliga a revalidar contra el origen, de modo que una caché compartida no
puede servir la sesión de un usuario a otro sin consultar al origen; pero es más débil
que `private, no-store` porque no impide el almacenamiento. Forzarlo exige un cambio
arquitectónico, así que **queda registrado como pendiente**, con la medición y el
análisis en `frontend/src/proxy.ts`. Se añadió un caso que exige que ninguna ruta se
declare `public` ni con `max-age` positivo.

### Estado tras las correcciones
- **32/32 PASS** (11 RLS + 11 Auth + 10 Company), una sola ejecución para no provocar
  el rate limit conocido
- Frontend y tests: lint, typecheck y build en exit 0 por binario directo;
  `npm run` sigue en 127 por la anomalía de PATH del entorno
- Advisors: Performance sin hallazgos; Security solo *Leaked Password Protection*
- 5 migraciones sincronizadas; **ninguna migración nueva**
- Diferidos registrados: Unicode del nombre, cuota de `create_company`, refactor de
  `requiredEnv`, roles adicionales, Supabase local

### Último bloqueante de Codex — corregido

La verificación final de Codex dio PASS a todo salvo un punto: en
`tests/auth/auth-flow.test.ts` el signup del usuario compartido vivía dentro del caso
B, mientras C, D, E y F dependían de ese usuario. Si B fallaba, Vitest seguía
ejecutando los cuatro contra un usuario inexistente y producía fallos en cascada.

Corregido separando los dos usos que estaban mezclados:

- **Prerrequisito** → `SHARED_USER`, registrado con `signUpOrFail` en el `beforeAll` de
  un `describe` anidado que envuelve C, D, E y F.
- **Comportamiento bajo prueba** → `SIGNUP_PROBE_USER`, con su propio usuario dentro del
  caso B. El signup sigue siendo un test real que puede fallar como test, no un paso de
  setup degradado.

Un solo signup para los cuatro casos dependientes: no se multiplica el consumo de cuota.

Verificado con un fixture que falla a propósito: **7 pasan, 4 omitidos**. Los
dependientes no se ejecutan, los independientes sí, y el error original queda visible.
`fileParallelism: false` y `sequence.concurrent: false` intactos; ningún límite de
Supabase modificado.

**Hallazgo residual — corregido después.** En `tests/rls/isolation.test.ts`,
`membershipAId` se asignaba en el caso 3 y se leía en el 6, donde la aserción resultaba
vacua: sobre una lista vacía `.some()` es falso aunque el id lo estuviera. En lugar de
mover el id a un hook, se eliminó la necesidad de compartirlo: el caso 6 consulta ahora
`company_memberships` filtrando por `companyAId` —valor que ya proviene del hook—, lo
que prueba la propiedad de seguridad de forma directa. El caso 3 conserva íntegras sus
aserciones sobre la membership de A.

Inspección estática final sobre `tests/auth/`, `tests/companies/` y `tests/rls/`:
**cero dependencias `it()` → `it()`**; todo el estado compartido nace en hooks.

### Sign-off final de Codex — Day 2 cerrado

Auditoría externa independiente sobre la totalidad del Día 2:

| Verificación | Resultado |
|---|---|
| Test dependency isolation | PASS |
| Auth fail-fast | PASS |
| RLS non-vacuous isolation assertion | PASS |
| Hallazgos CRITICAL / HIGH | Ninguno |
| Bloqueante para commit | Ninguno |
| Day 2 estable | Sí |

Veredicto: *"Day 2 can be committed and pushed."*

### Estado final verificado

- **Tests: 32/32 PASS** — RLS 11 · Auth 11 · Company 10
- Typecheck del paquete de tests: PASS
- Frontend lint, typecheck y build: PASS por binario directo (los scripts `npm run`
  siguen en 127 por la anomalía de PATH del entorno, no del proyecto)
- Cero dependencias `it()` → `it()` en las tres suites
- Advisors: Performance sin hallazgos; Security solo *Leaked Password Protection*
- 5 migraciones sincronizadas local/remoto

### Limitaciones diferidas — siguen documentadas y no bloquean el Día 3

`Cache-Control: private, no-store` en rutas de sesión (Next.js 16 sobrescribe la
cabecera; exigiría cambio arquitectónico) · normalización Unicode del nombre de empresa ·
cuota propia de `create_company` · refactor de `requiredEnv` · roles más allá de `owner` ·
Supabase local con Docker (ADR-018) · Leaked Password Protection (requiere plan Pro).

### Next
- **Day 3 — Data Model / Invoice Foundation**, tras el commit y push del Día 2
