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
Checkpoint B — FastAPI + Identity/RLS Foundation — COMPLETED
Checkpoint C — Authorization Roles Foundation — COMPLETED
Checkpoint D — Fiscal Data Access Boundary — COMPLETED
  Phase D0 — Architecture Contract & Preflight — COMPLETED
  Phase D1 — Boundary Implementation & Proof — COMPLETED
    · auditoría #1: FAIL/OPEN — 3 MEDIUM + 2 LOW, corregidos
    · reauditoría: 0 CRITICAL / 0 HIGH / 0 MEDIUM / 1 LOW documental — PASS
Checkpoint E — CR Electronic Invoice Domain Foundation
  Phase E0 — Official Source Baseline & Domain Inventory — COMPLETED
    · E0-R1: fuentes revalidadas · H-1 y H-2 cerrados
    · E0-R2: base semántica = Anexos 99 págs (Bitácora 22/04/2026)
             H-5 y H-8 cerrados · ADR-021…026 aceptadas
    · revisión arquitectónica: PASS
  Phase E1 — Logical Fiscal Model Design — COMPLETED
Next: fase E2 — diseño físico del esquema. NO INICIADA.
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
91596df — feat: establish backend identity and rls foundation   (2026-08-28)
```

Este campo identifica el último commit que contiene **implementación o checkpoint
estable**. Deliberadamente **no** referencia el commit documental que actualiza este
propio archivo: hacerlo generaría una autorreferencia infinita.

**Working tree:** contiene D0 (ADR-020) y D1 (la frontera fiscal ya implementada y
aplicada), pendientes ambos de revisión y commit. D1 sí incluye cambio de esquema:
la migración `20260829183152` está **aplicada en la base de datos de desarrollo**.

En `91596df`, `HEAD == origin/main` sin commits por delante ni por detrás.

Historial:
```
91596df  feat: establish backend identity and rls foundation        (2026-08-28)
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
✅ 8 migrations synchronized local/remote
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

## Authorization State — Checkpoint C (COMPLETED)

Auditoría externa: 0 CRITICAL · 0 HIGH · 0 MEDIUM.


**Roles del MVP:** `owner` · `editor` · `viewer` — `company_memberships.role` con
`text` + `CHECK`, sin enum (ADR-015).

**Fuente de verdad: `public.company_memberships`.** El JWT identifica al usuario y nada
más. El rol se consulta en la base de datos en cada operación; no se lee de claims, ni
del frontend, ni de la petición. Verificado: el endpoint no tiene parámetro de rol, y
enviar `role=owner` o `user_id=<otro>` por query, cabecera o cuerpo no altera nada.

**La identidad solo puede nacer de un JWT verificado, y está ligada a su subject.**
`AuthenticatedUser` es un objeto inmutable con `__slots__`, no un dataclass: su evidencia
es un HMAC sobre el `sub` ya verificado, con una clave privada del proceso. La prueba de
A **no vale** para B, `dataclasses.replace` no es aplicable y el objeto no es mutable.
`user_transaction` exige el tipo **y** revalida la ligadura antes de establecer
`request.jwt.claims`: si no corresponde, falla cerrada sin ejecutar SQL.

Los helpers de autorización reciben la **conexión ya contextualizada** y no aceptan
identidad por parámetro, de modo que no existe interfaz por la que suplantar a otro
usuario. Suplantación por query, cabeceras **y cuerpo** probada: la identidad sigue
siendo la del token.

**Sin RBAC granular**: no hay matriz de permisos, ni acciones tipo `invoice.*`, ni roles
personalizados, ni administración de miembros. Un usuario puede tener roles distintos en
empresas distintas. Sin membresía no hay rol por defecto: es `None`.

**La aplicación no puede escribir memberships** (`42501`): un `viewer` no puede
convertirse en `owner`. Las membresías `editor`/`viewer` de los tests se siembran fuera
de la aplicación, por la CLI.

## Backend State

```
FastAPI          0.141.1     Endpoint      GET /diagnostics/identity (diagnóstico)
psycopg          3.3.4       Conexión      session pooler, sslmode=require
pyjwt            2.13.0      JWT           ES256 vía JWKS público
Python           3.12.8      Rol DB        app_backend (NOBYPASSRLS, NOINHERIT)
```

Sin datos fiscales: no hay `invoices`, ni parser, ni Tax Engine.

## Database State

**Tables**
- `public.companies`
- `public.company_memberships`

**Functions**
- `public.create_company` (invoker, expuesta)
- `private.create_company_impl` (definer, no expuesta)
- `private.is_company_member` (definer, no expuesta)

**Migrations** — 8, sincronizadas local/remoto:
```
20260822230619_create_tenancy_tables
20260822230620_create_private_schema_and_rls
20260822230621_create_company_rpc
20260823212422_enforce_least_privilege_on_tenancy_tables
20260823213730_split_create_company_into_private_impl
20260825041622_create_app_backend_role
20260828212056_enforce_app_backend_memberships
20260829001056_extend_membership_roles
20260829183152_establish_fiscal_data_boundary
```

**9 migraciones**, todas sincronizadas local/remoto (9 local == 9 remoto).

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

**Total verificado: 233/233 PASS** — backend 201 + regresión Día 2 32.
Códigos de salida reales capturados sin tubería: `EXIT_PYTEST=0`, `EXIT_VITEST=0`,
`EXIT_ESLINT=0`, `EXIT_FRONT_TYPECHECK=0`, `EXIT_TESTS_TYPECHECK=0`, `EXIT_BUILD=0`.

**Backend: 201/201 PASS** — `backend/tests/`, pytest. `0 failed`, `0 skipped`.
Siete áreas: verificación de JWT (ES256-only, rechazo de RS256/HS256), guardas de
configuración (validación positiva del rol, TLS, marcadores), rol de base de datos y
verificación en runtime, privilegios efectivos medidos con `has_*_privilege`, identidad
transaccional y RLS por HTTP, roles de autorización (22), y **frontera fiscal (36)**.

**Frontera fiscal: 36/36 PASS** — `backend/tests/test_fiscal_boundary.py`. Se prueba
sobre una tabla canario efímera, `fiscal.boundary_probe`, creada y destruida por el
propio fichero: el gate sigue abierto y no existe todavía ninguna tabla fiscal real.
La comprobación de residuo (`tablas=0`, `funciones=0`) es una **aserción automatizada
dentro del teardown**, no un comando manual posterior.

**Inestabilidad ambiental observada** (no es un defecto del proyecto): el Auth de
Supabase en desarrollo alterna entre respuestas de ~0,3 s y episodios en los que agota
120 s. Cuando ocurre, la creación de usuarios de fixture produce **ERROR**, nunca `skip`
ni `PASS` — comprobado. El timeout se mantiene en 120 s: con el servicio sano la
latencia medida es de 0,27–19 s, muy por debajo, y la suite solo hace 2 signups frente
a un límite de `sign_in_sign_ups = 30` por 5 min, así que no es límite de tasa.

**Regresión Día 2: 32/32 PASS** — RLS 11 · Auth 11 · Company 10.

Propiedades demostradas contra la base de datos real:
- JWT de Supabase verificado con **ES256 únicamente**, vía JWKS público; RS256 y HS256
  rechazados con test
- Rol de login validado de forma **positiva**: solo `app_backend` es admisible
- Verificación en runtime al abrir el pool: si la sesión real no cumple, el backend no
  arranca
- `app_backend`: `rolsuper=false`, `rolbypassrls=false`, `rolinherit=false`,
  memberships exactas `{authenticated}`, sin alcance a `service_role`, `postgres` ni
  `supabase_admin`
- Privilegios efectivos: no alcanza las tablas de tenancy, ni los schemas `auth` y
  `private`, ni las funciones sensibles, sin asumir `authenticated`. Conserva `USAGE`
  sobre `public` vía `PUBLIC`, que no se revoca por sus efectos colaterales
- TLS activo en el tramo cliente→pooler (`pgconn.ssl_in_use`); `pg_stat_ssl` describe el
  tramo interno de Supavisor y no es el instrumento aplicable
- Identidad presente dentro de la transacción; **cleanup verificado tras `COMMIT` y
  tras `ROLLBACK` sobre la misma sesión**, demostrada con marca de sesión
  (`set_config(..., false)`) en lugar de `pg_backend_pid()`, que no representa la
  conexión de cliente a través del pooler
- **Sin fuga A→B sobre sesión reutilizada**; A→A permitido, B→A bloqueado, B→B permitido
- TLS obligatorio (`sslmode=require`), cifrado confirmado con `pgconn.ssl_in_use`
- Flujo HTTP `JWT → FastAPI → PostgreSQL → RLS` probado de extremo a extremo

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

## Checkpoint E — Fase E1 · COMPLETED

**Auditoría final de Codex: `CRITICAL 0 · HIGH 0 · MEDIUM 0 · LOW 0` — PASS.**
Diseño lógico únicamente: **0 SQL, 0 migraciones, 0 tablas, 0 cambios de código.**

| | |
|---|---|
| Documento producido | [FISCAL_LOGICAL_MODEL.md](FISCAL_LOGICAL_MODEL.md) |
| Entidades del MVP | **7** — `SourceDocument`, `ElectronicDocument`, `DocumentParty`, `DocumentLine`, `LineDiscount`, `LineTax`, `DocumentReference` |
| Entidades especificadas fuera del MVP | 6 |
| Cobertura del mapeo | **67 / 67** auditados → 59 permanecen (48 con valor + 11 estructurales), 8 reclasificados. **0 perdidos** |
| ADR propuestas | ADR-027 … ADR-031, todas en **PROPOSED** |
| Errata de E0 hallada en E1 | **C-1** (7 campos huérfanos) · **C-2** (`ProveedorSistemas`) |
| ADR aceptadas | ADR-027 … ADR-031 |

### Línea base lógica canónica

```
181  nodos XML totales

 59  MVP normalized
 64  normalize later
 58  raw-only initially

Mapeo MVP:
 59  mapeados  =  48 con valor  +  11 estructurales/contenedor
  0  sin explicar  ·  0 perdidos
```

> **Nota histórica.** E0 clasificó originalmente **67 / 57 / 57**. La reconciliación del
> mapeo de E1 lo corrigió a **59 / 64 / 58** —errata de clasificación, no pérdida de
> información—. Trazabilidad campo por campo en
> [FISCAL_LOGICAL_MODEL.md](FISCAL_LOGICAL_MODEL.md) §12.3.

### Relación artefacto ↔ documento

```
Para cada SourceDocument:      ElectronicDocument  =  0..1
Para cada ElectronicDocument:  SourceDocuments     =  1..N
```

`ElectronicDocument` **no** es hijo obligatorio de `SourceDocument`: es una relación de
normalización y procedencia. **La dirección física de la clave foránea queda para E2.**

### Invariantes de tenant

```
toda entidad fiscal hija pertenece al mismo tenant que su padre
SourceDocument.company_id == ElectronicDocument.company_id   (cuando hay asociación)
DocumentReference.resolved_document_id  resuelve SOLO dentro del mismo tenant
```

### Invariantes de dominio vigentes

```
el XML original se conserva
reported          ≠  computed
ausente           ≠  cero
importes reportados de NC/ND        no negativos
periodo fiscal    ≠  necesariamente mes(fecha de emisión)
schema_version    ≠  ruleset_revision
company_id        ≠  instantánea de emisor/receptor
DocumentParty      =  instantánea histórica de origen
direction          =  metadato derivado del tenant
no poder interpretar un artefacto NO impide conservarlo
```

**Correcciones aplicadas en la revisión de E1:**

- **`DocumentParty` es `1..2`**, no `2..2`. Verificado contra los Anexos v4.4 (rev.
  22/04/2026): el nodo `Receptor` tiene condición **1 (obligatorio) en Factura** y
  **2 (condicional) en NC y ND**. `issuer` exactamente 1, `receiver` 0..1.
- **La detección de versión puede fallar.** `SourceDocument` distingue `detected`,
  `unknown`, `unsupported` y `failed`. Invariante: no poder interpretar un artefacto
  nunca impide conservarlo.
- **Coherencia de tenant** como invariante de dominio: toda entidad hija pertenece al
  mismo tenant que su padre; `resolved_document_id` nunca cruza empresas.
- **Cuarto caso de deduplicación**: misma clave con contenido divergente es un
  **conflicto de integridad**, no un duplicado, y no se fusiona en silencio.

**Errata de clasificación de E0, hallada durante E1.** Al mapear los 67 campos
aparecieron dos inconsistencias verificables:

- **C-1** — siete campos marcados `MVP normalizado` cuyo **contenedor** está en
  «normalizar después» (`CodigoComercial`, `OtrosCargos`, `TotalDesgloseImpuesto`). Es
  imposible normalizar un campo cuyo contenedor no se normaliza. Causa identificable: la
  clasificación de E0 se hizo por nombre de hoja y estos siete colisionan con nombres MVP
  legítimos de otras ramas.
- **C-2** — `ProveedorSistemas` figura en la **categoría C** en la prosa de E0 §15 y como
  **MVP** en la tabla del inventario. Ambas no pueden ser ciertas.

```
Línea base E0 aprobada     67 MVP · 57 después · 57 crudo
Reconciliación de E1       59 MVP · 64 después · 58 crudo
Total                      181  (sin cambio)
```

Es una **errata de clasificación**, no una pérdida de información: los 181 nodos siguen
inventariados y el XML original los conserva todos. Lo incorrecto era la categoría de
ocho de ellos. Tabla campo por campo en [FISCAL_LOGICAL_MODEL.md](FISCAL_LOGICAL_MODEL.md) §12.3.
**Los commits anteriores no se alteran**; la corrección queda registrada como errata
fechada, y la clasificación canónica actualizada en [FISCAL_DOMAIN.md](FISCAL_DOMAIN.md).

**H-7 CERRADO** por C-2: `ProveedorSistemas` es metadata técnica del sistema emisor —no
interviene en ningún cálculo, no es parte de la transacción, ninguna consulta del MVP lo
necesita—, luego `raw-only` inicialmente, preservado en el XML y normalizable después.

---

## Checkpoint E — Fase E0 · COMPLETED

Revisión arquitectónica: **PASS**. Fase de investigación y documentación únicamente;
ningún cambio de código, esquema ni configuración.

### Línea base oficial

```
Official structural baseline
  Comprobantes Electrónicos v4.4
  9 XSD oficiales · sin cambios estructurales

Official semantic baseline
  ANEXOS_Y_ESTRUCTURAS_V4.4.pdf
  99 páginas · Bitácora de Ajustes al 22/04/2026
  sha256 6e093226b29b38c5c8de825f70c1b1cb8ed81e2f4a6eb0b3ff52708fc1eb2769
```

**Fechas — dos cosas distintas, deliberadamente separadas:**

| Fecha | Qué es |
|---|---|
| **01/09/2025** | Entrada en vigor **general de la v4.4** |
| 22/04/2026 | Publicación de la **revisión semántica 2026**, con adopción anticipada permitida |
| 01/11/2026 | Obligatoriedad de esa revisión |

La fecha de 2026 **no** es la entrada en vigor de la v4.4.

### Incidencia I-1

```
ATV y hacienda.go.cr pueden servir revisiones distintas
bajo el mismo nombre de fichero.
```

Regla resultante, aplicable a toda futura actualización de fuentes:

```
identidad de una fuente oficial
  = URL/ubicación  +  huella criptográfica / evidencia de revisión
```

El nombre del fichero **no basta**.

### Invariante de dominio registrado

```
El periodo fiscal/contable NO debe inferirse únicamente
de la fecha de emisión del documento.
```

Requisito pendiente para el Tax Engine, no algoritmo implementado. La semántica de las
referencias puede imputar efectos a periodos distintos ([FISCAL_DOMAIN](FISCAL_DOMAIN.md) §9.2, §13.2.bis).
**No se ha definido ningún `fiscal_period` ni se ha creado nada en la base de datos.**

### Dominio fiscal inicial

```
Factura Electrónica  +  Nota de Crédito  +  Nota de Débito
```

Razón: una factura no puede interpretarse correctamente sin considerar los documentos que
la ajustan. **No implementado todavía.**

| | |
|---|---|
| Versión oficial vigente verificada | **4.4** — no existe 4.5 ni posterior |
| Obligatoriedad de la v4.4 | **1 de setiembre de 2025** |
| Norma original | `MH-DGT-RES-0027-2024` (13-nov-2024) — fijaba 1-jun-2025 |
| Modificación posterior del plazo | `MH-DGT-RES-0001-2025` |
| Revisión del documento técnico | **Bitácora de Ajustes al 22/04/2026** (99 págs, `sha256 6e093226…`) |
| Calendario de la revisión 2026 | disponible 22-abr-2026 · uso anticipado permitido · **obligatoria 1-nov-2026** |
| XSD oficiales descargados y analizados | **9 / 9** — re-descargados: **9 idénticos, 0 distintos**. La revisión 2026 **no añade elementos** |
| Documentos oficiales descargados | 5 PDF (Anexos 99 · Anexos 98 · Resolución 9 · Reglamento 28 · Generalidades 20) |
| Inventario de Factura Electrónica | **181 nodos** (incluida la referencia a la firma). Reparto registrado en E0: 67 · 57 · 57 → **corregido en la reconciliación de E1 a 59 MVP · 64 después · 58 crudo** (errata de clasificación, §Fase E1). `raw-only` **no** significa descartado: todo se conserva en el XML original |
| Catálogos de referencia | nota 9: 12 → **17 códigos** · nota 10: 18 → **20 códigos** |
| Huecos abiertos | 3 — H-3, H-4, H-6. **Cerrados: H-1, H-2, H-5, H-7, H-8.** Registrada la incidencia técnica I-1 |
| Documento producido | [FISCAL_DOMAIN.md](FISCAL_DOMAIN.md) |
| Cambios en código | **ninguno** |
| Tablas fiscales creadas | **0** |

**Dos ubicaciones oficiales, dos revisiones (incidencia I-1).** `hacienda.go.cr` sirve
la revisión vigente de 99 páginas; la ruta de ATV sigue sirviendo la de 98, con **el
mismo nombre de archivo**. Hacienda sí publica la actualización: lo que falla es asumir
una única URL canónica. Regla operativa: fijar la ubicación **y** contrastar la huella.

**Hallazgo de fondo de E0-R2.** La revisión 2026 establece que el **código de referencia
determina el periodo contable** de un ajuste: `01`, `02`, `06` y `12` imputan al periodo
de la nota; `13` y `14`, al del comprobante original. El periodo fiscal de un ajuste
**no se deduce de su fecha**. Detalle en [FISCAL_DOMAIN.md](FISCAL_DOMAIN.md) §9.2.

**Fiscal Gate = PASSED / CLOSED**, pero **no se ha creado ninguna tabla fiscal de
producto**: `invoices`, `invoice_lines`, `source_documents` y `tax_profiles` siguen sin
existir, y el schema `fiscal` está vacío.

---

## ✅ Fiscal Data Access Boundary Gate — PASSED / CLOSED

Registrado hasta ahora como `🔴 BLOCKING BEFORE FIRST FISCAL TABLE`. **Cerrado**
tras la reauditoría independiente de la fase D1.

> FastAPI asume `authenticated` dentro de la transacción para aprovechar RLS.
> `authenticated` es también un rol utilizado por la Supabase Data API. Antes de
> introducir cualquier tabla fiscal debe establecerse una frontera mecánica que permita
> `FastAPI → fiscal data` **sin** habilitar `Frontend → Supabase Data API → fiscal data`.

Conceder a `authenticated` privilegios sobre datos fiscales en un schema expuesto los
haría alcanzables desde el navegador, incumpliendo [ADR-001](DECISIONS.md#adr-001) y
[ADR-012](DECISIONS.md#adr-012).

**No bloquea el cierre de Checkpoint B** —el mecanismo de tenancy está demostrado sobre
tablas de identidad, no fiscales—.

**Arquitectura decidida en la fase D0:** [ADR-020](DECISIONS.md#adr-020) — schema
`fiscal` no expuesto por la Data API, rol de ejecución `fiscal_backend` sin `BYPASSRLS`,
`authenticated` sin privilegios fiscales, y RLS obligatoria como tercera capa.

**Mecanismo implementado en la fase D1** (migración `20260829183152`, aplicada) y
demostrado con 36 tests sobre una tabla canario efímera. La Data API responde
`PGRST106` al schema `fiscal`, no `200 []`.

**GATE CERRADO.** La reauditoría independiente cerró en 0 CRITICAL / 0 HIGH /
0 MEDIUM. La frontera queda demostrada, no supuesta:

```
Frontend / Supabase Data API   → fiscal   ❌  (PGRST106, no 200 [])
authenticated                  → fiscal   ❌  (sin USAGE sobre el schema)
app_backend sin SET ROLE       → fiscal   ❌  (membresía sin herencia)

FastAPI / fiscal_backend / User A → Company A  ✅
                                  → Company B  ❌
FastAPI / fiscal_backend / User B → Company B  ✅
                                  → Company A  ❌
```

Cerrar este gate **autoriza a comenzar el diseño del primer modelo fiscal**. No
significa que exista ninguna tabla fiscal de producto: `invoices`, `invoice_lines`,
`source_documents` y `tax_profiles` siguen sin existir, y el schema `fiscal` está
vacío. Tampoco levanta las demás condiciones del proyecto: cada tabla fiscal se
diseñará por objeto, con sus propios privilegios y sus propias políticas.

### Evidencia de cierre

| Propiedad | Verificado |
|---|---|
| Schema `fiscal` creado, no expuesto por la Data API | `schemas = ["public","graphql_public"]` |
| `Accept-Profile: fiscal` con JWT real de usuario | **`PGRST106`** (no `200 []`) |
| `authenticated` → fiscal | sin `USAGE`; rechazo `42501` |
| `app_backend` → fiscal sin `SET ROLE` | sin privilegio ambiental; rechazo `42501` |
| `fiscal_backend` | NOLOGIN · NOBYPASSRLS · NOINHERIT · NOREPLICATION · sin contraseña |
| `app_backend` asume `fiscal_backend` | solo con `SET` explícito (`inherit_option=false`) |
| Roles de la Data API (`anon`, `authenticated`, `service_role`, `authenticator`) | sin ruta `SET` hacia `fiscal_backend` |
| Cierre efectivo de `SET ROLE` (no superusuarios) | exactamente `{app_backend}` |
| `fiscal_backend` → schema `auth` | sin `USAGE`; políticas vía helpers privados |
| Frontera de membresía | `private.is_company_member()` (`SECURITY DEFINER`) |
| SELECT RLS A/B | completo, ambos sentidos |
| INSERT RLS A/B | completo; rechazo por `WITH CHECK`, no por grants |
| COMMIT / ROLLBACK | rol e identidad descartados; escritura abortada no persiste |
| Misma sesión reutilizada, A→B→A→B | sin fuga de identidad ni de filas |
| Canario efímero | sin residuo (aserción automatizada en el teardown) |
| Suites | backend 201 + Día 2 32 = **233/233 PASS** |
| Checkpoints B y C | sin regresión |

**Norma de autorización fiscal** (registrada en [ADR-020](DECISIONS.md#adr-020)): las
políticas RLS fiscales se apoyan en helpers privados aprobados —`private.is_company_member(...)`—
y `fiscal_backend` **no** recibe `USAGE` directo sobre el schema `auth`. La auditoría
confirmó esta restricción como correcta y se mantiene explícitamente. La identidad del
usuario sigue disponible en `request.jwt.claims`; lo que no está es el atajo `auth.uid()`.
Cubierto por `test_fiscal_backend_no_alcanza_el_schema_auth`.

**Relación inversa de `fiscal_backend`** (hallazgo de la auditoría, corregido): los
miembros reales son `app_backend` (`set_option=true`) y `postgres` (`admin_option=true`,
`set_option=false`). El segundo es comportamiento sistémico de PostgreSQL 16+ —quien crea
un rol recibe pertenencia automática— y figura igual en `anon`, `authenticated`,
`service_role` y `app_backend`. **No puede asumir el rol**: comprobado ejecutándolo,
devuelve `42501 permission denied to set role`. El cierre transitivo de `SET ROLE`,
excluyendo superusuarios, es exactamente `{app_backend}`. El único superusuario del
proyecto es `supabase_admin`.

**El gate SIGUE ABIERTO.** Se retirará cuando la fase D1 esté implementada, probada,
auditada y commiteada. Hoy solo existe el contrato, no la frontera.

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
invoices · invoice_lines · source_documents · tax_profiles
parser XML · Tax Engine · IVA
Knowledge Base · RAG · AI Agent · payments · API de Hacienda
```

> **NO crear tablas fiscales hasta cerrar el modelo conceptual y verificar las fuentes
> oficiales de Hacienda.** El gate de la frontera fiscal está cerrado, pero eso autoriza
> a *diseñar*, no a crear tablas.

`FastAPI` figuraba en esta lista desde el Día 1 y ya no corresponde: existe y quedó
cerrado en el Checkpoint B del Día 3. Se retira por obsoleta, no por levantarla.

---

## Next Action

**Revisión de la fase E0.** El inventario del dominio está hecho y documentado en
[FISCAL_DOMAIN.md](FISCAL_DOMAIN.md); falta aprobación antes de pasar a diseño de
esquema.

E0 fue exclusivamente investigación y documentación. **Ningún cambio en `backend/`,
`frontend/` ni `supabase/migrations/`.** Sigue sin existir ninguna tabla fiscal.

Decisiones conceptuales cerradas: [ADR-021](DECISIONS.md#adr-021) …
[ADR-026](DECISIONS.md#adr-026), las seis aceptadas. Ninguna fija esquema físico:
[ADR-025](DECISIONS.md#adr-025) acota el núcleo MVP sin declarar que todos los tipos
compartan una única tabla.

Checkpoints A, B, C y D del Día 3 cerrados, los cuatro con auditoría externa en
0 CRITICAL / 0 HIGH / 0 MEDIUM. Sigue sin existir código fiscal, ni tablas de
comprobantes, ni parser XML, ni Tax Engine.

Las limitaciones diferidas siguen documentadas más arriba y **no bloquean** el Día 3.

Antes de construir la interfaz real del producto queda pendiente un checkpoint propio
para **elegir la librería de componentes UI / design system**.
