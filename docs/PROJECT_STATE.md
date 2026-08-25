# PROJECT STATE

> Fotografía del estado actual y punto de entrada de toda sesión nueva. Sustituye al
> historial de conversación: si difieren, manda lo verificable (Git, tests, migraciones).
> Se actualiza al cerrar cada checkpoint. Última actualización: **2026-08-23**.

## Project

**Name:** Asistente Tributario IA para Costa Rica · **Repository:** `tributario-ai-cr`

## Current Phase

```
Day 2 — COMPLETED  (sign-off final de Codex obtenido, commiteado y publicado)

Day 3 — Data Model / Invoice Foundation
Checkpoint A — Architecture & Baseline Gate — COMPLETED
Next: Checkpoint B — por diseñar
```

**Auditoría externa (Codex) — sign-off final:**

| Verificación | Resultado |
|---|---|
| Test dependency isolation | PASS |
| Auth fail-fast | PASS |
| RLS non-vacuous isolation assertion | PASS |
| Hallazgos CRITICAL / HIGH | **Ninguno** |
| Bloqueante para commit | **Ninguno** |
| Day 2 estable | **Sí** |

> *"Day 2 can be committed and pushed."*

Roadmap: **Fase 1 — Infrastructure / Auth / Company** (ver [ROADMAP.md](../ROADMAP.md)).

## Last Substantive Checkpoint Commit

```
22875b1 — feat: complete day 2 auth tenancy and security hardening   (2026-08-24)
```

Este campo identifica el último commit que contiene **implementación o checkpoint
estable**. Deliberadamente **no** referencia el commit documental que actualiza este
propio archivo: hacerlo generaría una autorreferencia infinita.

**Working tree: limpio.** El Día 2 completo —Checkpoints E, F, G y las correcciones
posteriores a Codex— está commiteado y publicado. `HEAD == origin/main == 22875b1`,
sin commits por delante ni por detrás.

Historial:
```
22875b1  feat: complete day 2 auth tenancy and security hardening   (2026-08-24)
ebf3be4  docs: update project state after checkpoint                (2026-08-23)
85c3556  feat: establish secure tenancy and Next.js foundation      (2026-08-23)
4a80ca5  docs: establish project foundation                         (2026-08-22)
```

## Completed — implementado y verificado

```
✅ Day 1 project foundation
✅ Supabase DEVELOPMENT project linked
✅ companies + company_memberships
✅ RLS
✅ least privilege
✅ private schema security pattern
✅ create_company wrapper/implementation pattern
✅ 5 migrations synchronized local/remote
✅ RLS A/B isolation tests — 11/11 PASS
✅ Next.js foundation
✅ TypeScript
✅ Tailwind
✅ ESLint
✅ Supabase browser/server clients
✅ lint / typecheck / build PASS
✅ proxy.ts — refresco de sesión (Next.js 16)
✅ signup / login / logout
✅ protected route con verificación server-side (getClaims)
✅ auth flow tests — 9/9 PASS
✅ Company UI — listar y crear empresa desde /app
✅ createCompanyAction vía RPC create_company (única vía de escritura)
✅ company flow tests — 10/10 PASS
✅ arnés de tests: fallo rápido, causa original visible, suites serializadas
✅ auditoría interna del Día 2
✅ smoke test del flujo completo — 16/16 PASS
✅ correcciones post-Codex: detector JWT, asserts 42501/22023, fixtures, logout,
   typecheck del paquete de tests
✅ fail-fast de la suite Auth: prerrequisito compartido en hook (último bloqueante)
```

## Pending

```
⬜ Elección de librería de componentes UI / design system
⬜ Day 3 — modelo de datos e ingesta de comprobantes
```

---

## Current Architecture

```
Frontend            Next.js + React + TypeScript
Backend (planned)   Python + FastAPI
Infrastructure      Supabase · PostgreSQL · Auth · Storage · pgvector · RLS

Future core         Tax Data Layer · Tax Engine · Knowledge Base · AI Agent
```

**Principio rector:** `LLM ≠ Tax Engine` · Detalle en [ARCHITECTURE.md](../ARCHITECTURE.md).

## Security State

- Multi-tenancy: N:M user ↔ company vía `company_memberships`
- RLS activa en ambas tablas de tenancy (`rls_forced = false`, deliberado)
- `authenticated`: **solo SELECT** sobre tablas de tenancy
- `anon`: **sin acceso** a tablas
- Las escrituras normales **no usan `service_role`**
- `public.create_company` = **SECURITY INVOKER**
- `private.create_company_impl` = **SECURITY DEFINER**
- Schema `private` **no expuesto** por la Data API
- Tests de aislamiento A/B: **11/11 PASS**
- Secretos fuera de Git; `.env.local` ignorado en `frontend/` y `tests/`
- Security & Performance Advisors: sin hallazgos de esquema
- **Leaked password protection pendiente para producción**: requiere plan Pro; el
  proyecto DEV está en Free

## Database State

**Tables**
- `public.companies`
- `public.company_memberships`

**Functions**
- `public.create_company` (invoker, expuesta)
- `private.create_company_impl` (definer, no expuesta)
- `private.is_company_member` (definer, no expuesta)

**Migrations** — 5, sincronizadas local/remoto:
```
20260822230619_create_tenancy_tables
20260822230620_create_private_schema_and_rls
20260822230621_create_company_rpc
20260823212422_enforce_least_privilege_on_tenancy_tables
20260823213730_split_create_company_into_private_impl
```

**Environment:** Supabase alojado, **DEVELOPMENT**. Nunca producción.
Cambios de esquema **solo** por migración (`supabase db push`).
Configuración como código (`supabase config push`) — ver Regla 15.

## Tests

**RLS isolation: 11/11 PASS** — `tests/rls/isolation.test.ts` (vitest). Sin estado
compartido entre casos: todo prerrequisito nace en el hook. Demostrado:
- User B **no puede leer** la empresa de User A (0 filas, sin error → RLS filtra)
- User B **no puede auto-asignarse** membership (error `42501` → falta de privilegio)
- `anon` **no puede ejecutar** `create_company` (`42501`)
- **Control de validez:** User B **sí** puede operar en su propio tenant — sin este
  caso, los anteriores podrían pasar por tener la sesión rota

Usan solo la clave publicable y sesión propia por usuario. Nunca `service_role`.

**Auth flow: 11/11 PASS.** El usuario compartido de los casos C–F se registra en el
hook de un `describe` anidado, no dentro de un `it`. Verificado con un fixture que falla
a propósito: los 4 dependientes quedan **omitidos** y los 7 independientes siguen
ejecutándose. El caso B conserva su propio usuario porque el signup es el
comportamiento bajo prueba.

**Auth flow: 11/11 PASS** — `tests/auth/auth-flow.test.ts`. Dos niveles declarados:
`[HTTP]` peticiones reales al servidor (redirección de ruta protegida, rutas públicas,
assets excluidos del matcher) y `[AUTH]` mecánica de sesión con los mismos métodos que
usan las Server Actions (signup, logout, login, `getClaims()`, contraseña incorrecta).
El caso G verifica que el build no contiene secret key ni JWT de `service_role`, con
autotest del detector para que no pueda pasar en vacío.

**Hueco conocido:** no se invoca el protocolo HTTP de Server Actions de Next.js —
depende de un identificador que cambia en cada build. Cerrarlo requiere una suite de
navegador (Playwright), pendiente como checkpoint propio.

**Company flow: 10/10 PASS** — `tests/companies/company-flow.test.ts`. Cuatro niveles
declarados: `[UNIT]` validación pura importada del propio código de la aplicación,
`[DB]` operaciones reales bajo RLS, `[HTTP]` acceso a ruta protegida, `[STATIC]`
análisis del código fuente (sin INSERT directo, sin `service_role`, sin filtro por
`user_id` en la consulta). Los detectores llevan autotest.

**Total: 32/32 PASS** — RLS 11 · Auth 11 · Company 10.

**Verificación final del Día 2:**

| Comprobación | Resultado |
|---|---|
| Tests (RLS + Auth + Company) | **32/32 PASS** |
| Typecheck del paquete de tests | **PASS** (`tsc --noEmit`, exit 0) |
| Frontend lint | **PASS** (binario directo, exit 0, sin advertencias) |
| Frontend typecheck | **PASS** (binario directo, exit 0) |
| Frontend build | **PASS** (binario directo, exit 0) |
| Dependencias `it()` → `it()` | **0** |

Los scripts `npm run` siguen devolviendo 127 por la anomalía de PATH del entorno, no
del proyecto; los binarios directos son la medida válida.

**Fragilidad: CAUSA CONFIRMADA y reproducida.** `[auth.rate_limit] sign_in_sign_ups = 30`
por 5 minutos e IP. Cada ejecución consume ~9 peticiones de auth, de modo que a partir
de la tercera ejecución seguida el `signUp` devuelve `429 over_request_rate_limit`.

Mitigado, no eliminado:
- suites **serializadas** (`fileParallelism: false`) para no consumir la cuota en ráfaga;
- arnés `tests/support/harness.ts`: todo fallo de setup aborta de inmediato, muestra el
  error original y nombra el límite. Ya no se propagan identificadores vacíos ni
  aparecen errores engañosos como `invalid input syntax for type uuid: ""`.

**El límite sigue existiendo.** Ejecutar la suite más de dos veces en cinco minutos
volverá a fallar — ahora con un mensaje que lo dice. Es el disparador previsto en
ADR-018 para reconsiderar el entorno local con Docker.

## Frontend State

```
Next.js                16.3.2      Lint        PASS
React                  19.2.8      Typecheck   PASS
TypeScript              5.9.3      Build       PASS
Tailwind                4.3.3      Local home  working (http://localhost:3000)
@supabase/supabase-js 2.112.3
@supabase/ssr          0.12.4      Auth        IMPLEMENTED
                                   Company UI  IMPLEMENTED
```

Rutas: `/` (pública) · `/login` · `/signup` · `/app` (protegida, lista y crea empresas).
Las cuatro dinámicas.
`proxy.ts` activo y verificado en el registro del servidor en cada petición.

Clientes en `frontend/src/lib/supabase/{client,server}.ts`. Next.js 16 usa **`proxy.ts`**,
no `middleware.ts`. En servidor: **`getClaims()`**, nunca `getSession()`.

## Important Accepted Decisions — resumen; la fuente es [DECISIONS.md](DECISIONS.md)

- XML primero; sin integración con Hacienda inicialmente
- Supabase alojado DEV por ahora; entorno local con Docker diferido — ADR-018
- Relación usuario–empresa N:M — ADR-015
- RLS obligatoria — ADR-002
- `service_role` no se usa en operaciones normales de usuario — ADR-002
- `companies` / `company_memberships` son datos de tenancy, **no fiscales** — ADR-017
- Los datos fiscales pasarán por la capa de aplicación / FastAPI — ADR-001
- RPC pública invoker; implementación privilegiada privada
- Decimal exacto para importes monetarios — ADR-008
- Distinción `reported_*` vs `computed_*` — ADR-003
- Tax Engine aislado del LLM — ADR-005
- **Librería de componentes UI: pendiente de elegir** antes de la UI real del producto

## Open Decisions

Verificado contra [DECISIONS.md](DECISIONS.md):

| Abierta | Referencia |
|---|---|
| Hosting del backend en producción | ADR-011 ⏳ |
| Confirmación de email en producción | ADR-019 (solo DEV decidido) |
| Leaked password protection / plan de producción | sin ADR |
| Entorno local Supabase con Docker | ADR-018 (a reconsiderar) |
| Librería de componentes UI / design system | **sin ADR todavía** |
| Políticas de MFA / email en producción | sin ADR |
| Procesamiento en segundo plano | ADR-016 ⏳ |
| Proveedor LLM inicial | ADR-013 ⏳ |
| Estrategia de embeddings | ADR-014 ⏳ |

## Pendientes registrados (diferidos conscientemente)

| Pendiente | Motivo |
|---|---|
| **`Cache-Control: private, no-store` en rutas de sesión** | Next.js 16 fija `no-cache, must-revalidate` en rutas dinámicas y **sobrescribe** tanto el proxy como `next.config.headers()`; ambos verificados. Forzarlo exige cambio arquitectónico (servidor propio, Route Handlers o proxy inverso). Medición y análisis en `frontend/src/proxy.ts` |
| Normalización Unicode del nombre de empresa | Diferido |
| Cuota / rate limit propio de `create_company` | Diferido |
| Refactor de `requiredEnv` (duplicado en `client.ts` y `server.ts`) | Diferido |
| Roles más allá de `owner` | ADR-015 ◐ |
| Supabase local con Docker | ADR-018 |
| Leaked Password Protection | Requiere plan Pro |

## Current Constraints — NO construir todavía, hasta que toque en el roadmap

```
XML · invoices · FastAPI · Tax Engine · IVA
Knowledge Base · RAG · AI Agent · payments · Hacienda
```

---

## Next Action

**Day 3 — Data Model / Invoice Foundation · Checkpoint A — Architecture & Baseline Gate**

Completado en este checkpoint:
- Baseline verificado contra Git
- [ADR-012](DECISIONS.md#adr-012) y [ADR-015](DECISIONS.md#adr-015) formalizados como
  aceptados
- Inconsistencias documentales corregidas contra el estado real del repositorio

Siguiente: diseñar el checkpoint que aborde el modelo de datos de comprobantes. Sigue
sin existir código fiscal, ni FastAPI, ni migraciones de invoices.

Las limitaciones diferidas siguen documentadas más arriba y **no bloquean** el Día 3.

Antes de construir la interfaz real del producto queda pendiente un checkpoint propio
para **elegir la librería de componentes UI / design system**.
