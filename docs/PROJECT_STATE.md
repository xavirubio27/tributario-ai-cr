# PROJECT STATE

> Fotografía del estado actual y punto de entrada de toda sesión nueva. Sustituye al
> historial de conversación: si difieren, manda lo verificable (Git, tests, migraciones).
> Se actualiza al cerrar cada checkpoint. Última actualización: **2026-08-23**.

## Project

**Name:** Asistente Tributario IA para Costa Rica · **Repository:** `tributario-ai-cr`

## Current Phase

```
Day 2
Checkpoint D — Next.js Foundation ...... COMPLETED
Next: Checkpoint E — Authentication
```

Roadmap: **Fase 1 — Infrastructure / Auth / Company** (ver [ROADMAP.md](../ROADMAP.md)).

## Last Stable Commit

```
85c3556 — feat: establish secure tenancy and Next.js foundation   (2026-08-23)
```

Publicado en `origin/main`. `HEAD == origin/main`.

**Working tree: limpio.** Todo el trabajo del Día 2 —Supabase, migraciones, tests,
frontend y documentación— está commiteado y publicado.

Historial:
```
85c3556  feat: establish secure tenancy and Next.js foundation   (2026-08-23)
4a80ca5  docs: establish project foundation                      (2026-08-22)
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
```

## Pending

```
⬜ Auth
⬜ proxy session refresh
⬜ signup
⬜ login
⬜ logout
⬜ protected route
⬜ Company UI
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

**RLS isolation: 11/11 PASS** — `tests/rls/isolation.test.ts` (vitest). Demostrado:
- User B **no puede leer** la empresa de User A (0 filas, sin error → RLS filtra)
- User B **no puede auto-asignarse** membership (error `42501` → falta de privilegio)
- `anon` **no puede ejecutar** `create_company` (`42501`)
- **Control de validez:** User B **sí** puede operar en su propio tenant — sin este
  caso, los anteriores podrían pasar por tener la sesión rota

Usan solo la clave publicable y sesión propia por usuario. Nunca `service_role`.

## Frontend State

```
Next.js                16.3.2      Lint        PASS
React                  19.2.8      Typecheck   PASS
TypeScript              5.9.3      Build       PASS
Tailwind                4.3.3      Local home  working (http://localhost:3000)
@supabase/supabase-js 2.112.3
@supabase/ssr          0.12.4      Auth        NOT IMPLEMENTED
                                   Company UI  NOT IMPLEMENTED
```

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
| Propagación del JWT a través de FastAPI | ADR-012 ◐ |
| Hosting del backend en producción | ADR-011 ⏳ |
| Confirmación de email en producción | ADR-019 (solo DEV decidido) |
| Leaked password protection / plan de producción | sin ADR |
| Entorno local Supabase con Docker | ADR-018 (a reconsiderar) |
| Librería de componentes UI / design system | **sin ADR todavía** |
| Roles más allá de `owner` | ADR-015 ◐ |
| Políticas de MFA / email en producción | sin ADR |
| Procesamiento en segundo plano | ADR-016 ⏳ |
| Proveedor LLM inicial | ADR-013 ⏳ |
| Estrategia de embeddings | ADR-014 ⏳ |

## Current Constraints — NO construir todavía, hasta que toque en el roadmap

```
XML · invoices · FastAPI · Tax Engine · IVA
Knowledge Base · RAG · AI Agent · payments · Hacienda
```

---

## Next Action

**Checkpoint E — Authentication**

Alcance previsto:
- `frontend/.env.local` (lo rellena el usuario; el agente no maneja claves)
- `proxy.ts` — refresco de sesión (Next.js 16: función `proxy`, runtime Node.js)
- signup · login · logout
- ruta protegida
- verificación server-side con `getClaims()` en **cada** Server Action y página
  protegida, no solo en el proxy
