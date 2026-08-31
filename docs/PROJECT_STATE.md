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
  Phase E2 — PostgreSQL Fiscal Schema Design — COMPLETED
  Phase E3 — First Fiscal Migration — COMPLETED
  Phase E4-A — Real XML Fixture Intake & Baseline — COMPLETED
  Phase E4-B0 — Real Fixture Compatibility Fix — COMPLETED
  Phase E4-A2 — Fixture Expansion — NOT STARTED
Next: E4-A2. El parser aún no existe.
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

## Checkpoint E — Fases E4-A y E4-B0

### E4-A — Real XML Fixture Intake & Baseline · COMPLETED

Dos Facturas Electrónicas v4.4 **reales**, aceptadas por Hacienda, incorporadas como
golden fixtures en `backend/tests/fixtures/fiscal/real/v4_4/fe/`:

```
50601082600310161019803900001010004596121100000000.xml   16 067 B
  sha256 a1f639d06c79cedfa01fe6e3ca8fce5b8ad7de9225afe6cbf7054ff6515c8b0b

50602082600310161019800100024010059940227200000000.xml   10 911 B
  sha256 b9892fad51b9c9d49aa8d04581088ee69b0d2262b2337b880355b53b4ad70ae0
```

Claves distintas, situaciones distintas (`1` normal · `2` contingencia): **dos
comprobantes independientes**, nunca consolidados. Bytes intactos —CRLF, sin salto
final—; los tests comparan la huella sobre los bytes, sin reserializar.

Cobertura de los 48 campos MVP: **37/48** y **35/48**. Todas las ausencias son legítimas
—campos opcionales no declarados o el nodo `InformacionReferencia` inexistente—. El par
ilustra con datos reales la distinción **ausente ≠ cero**: `TotalDescuentos` ausente en
uno mientras `PlazoCredito` está presente con valor `0`.

### E4-B0 — Real Fixture Compatibility Fix · COMPLETED

**Auditoría independiente de Codex: `CRITICAL 0 · HIGH 0 · MEDIUM 0 · LOW 0` — PASS.**

**Los fixtures reales destaparon un `CHECK` demasiado estricto creado en E3.**

```
E3 cerrada
   ↓
se incorporan fixtures FE 4.4 reales
   ↓
se descubre la incompatibilidad del código de actividad
   ↓
migración correctiva
```

Los dos comprobantes declaran `CodigoActividadEmisor = "6110.0"` —seis caracteres, con
punto—. E3 exigía `^[0-9]{6}$` en ambos códigos de actividad, de modo que **habría
rechazado comprobantes reales**. De las 20 restricciones de forma, 19 pasaron; esta no.

**Corrección:** migración nueva `20260830162516_fix_fiscal_activity_code_constraints`
que cambia la validación estructural de *seis dígitos ASCII* a **exactamente seis
caracteres**.

**Motivo:** fidelidad a la fuente estructural oficial. El XSD v4.4 declara
`xs:string minLength=6 maxLength=6` **sin patrón**, y los Anexos dicen «String 6» con
validación contra el padrón del RUT. La validación semántica de catálogo/RUT **sigue
diferida** a la capa 2; aquí no se introduce catálogo alguno.

La migración de E3 **no se editó**: permanece históricamente intacta.

| | |
|---|---|
| Migraciones | **11 locales · 11 remotas**, versiones idénticas |
| Constraint anterior | `CHECK (issuer_activity_code ~ '^[0-9]{6}$')` |
| Constraint nuevo | `CHECK (char_length(issuer_activity_code) = 6)` |
| Receptor | `CHECK (receiver_activity_code IS NULL OR char_length(...) = 6)` — sigue nullable |
| Verificación | Por `INSERT` real, no solo introspección: `6110.0`, `620100` y `ABC123` aceptados; 5 y 7 caracteres rechazados (`23514`) |

### Remediación tras auditoría de Codex

La auditoría cerró `FAIL` con 1 MEDIUM y 2 LOW. Corregido:

- **Cleanup destructivo sin ámbito.** `test_fiscal_fixtures.py` ejecutaba
  `delete from fiscal.electronic_documents` **sin predicado**, capaz de borrar datos de
  otra ejecución concurrente o de otro desarrollador contra el mismo DEV. **Encontré el
  mismo defecto en `test_fiscal_schema.py`**, que la auditoría no señaló. Los tres
  quedan acotados por el **UUID exacto** de la empresa creada por esa ejecución.
- **Fuga de tenencia.** Las fixtures `user_a`/`user_b` creaban usuario de Auth, empresa y
  membresía **sin teardown**. Ahora se limpian en un bloque `finally`, en el orden que
  imponen las claves foráneas reales: filas fiscales → empresa (la membresía cae por
  CASCADE) → usuario de Auth. Se reutiliza el mecanismo privilegiado de tests ya
  aprobado; no se introduce infraestructura nueva ni se relaja ningún `RESTRICT`.
- **Regresiones nuevas.** Un test *centinela* demuestra por comportamiento —no
  inspeccionando SQL— que el cleanup de una empresa **no borra** documentos de otra. Otro
  lanza una excepción dentro del generador de la fixture, como hace pytest cuando un test
  falla, y comprueba que el teardown se ejecuta igualmente.

**Prueba de estabilidad:** dos ejecuciones consecutivas, 29/29 cada una, sin crecimiento
de usuarios, empresas ni filas fiscales.

### CABYS — formato semántico: **CONFIRMED NUMERIC**

```
XSD v4.4          xs:string, longitud 13        → SOLO longitud, sin patrón
BCCR (CABYS)      código de producto            → 13 DÍGITOS
CHECK actual      cabys_code ~ '^[0-9]{13}$'    → SOPORTADO
migración         NO se requiere
H-3               sigue ABIERTO
```

**Fuentes primarias del respaldo semántico**, las tres del Banco Central de Costa Rica:

| Documento | Qué establece |
|---|---|
| Página oficial CABYS — «Catálogo de bienes y servicios para uso tributario y de Cuentas Nacionales» | Jerarquía de **1 dígito** (categorías generales) → **2** → … → **13 dígitos** (producto) |
| Preguntas frecuentes CABYS | Productos «**identificados por 13 dígitos**» |
| Guía oficial del buscador CABYS | El campo Código es un «**número de trece dígitos que identifica un producto**» |

**No se atribuye «13 dígitos» al XSD**: el XSD aporta la longitud; el respaldo numérico es
del BCCR. Lo corrobora una fuente verificada localmente: los Anexos v4.4
(`sha256 6e093226…`) hablan de «el primer **dígito** del código CABYS sea 0, 1, 2, 3 y 4
(bienes)», y su nota 17 delega la codificación a ese catálogo.

**Cerrar el formato NO cierra H-3.**

```
CABYS format confirmed   ≠   CABYS catalog implemented
```

**H-3 continúa ABIERTO** porque todavía no existe: catálogo CABYS integrado · validación
del código contra el catálogo vigente · enriquecimiento · resolución de descripción ·
manejo de versiones del catálogo. **ADR-029 sigue aplicando**: ningún código externo lleva
clave foránea obligatoria a un catálogo local. Lo que deja de ser una cuestión abierta es
el *formato* del código, no el catálogo.

**Trazabilidad de la conclusión** —no se reescribe el pasado—:

| Momento | Estado |
|---|---|
| **E3** | Se implementó `CHECK (cabys_code ~ '^[0-9]{13}$')` |
| **E4-A / E4-B0** | Se cuestionó que la forma numérica fuera atribuible al **XSD** — y no lo era |
| **Auditoría** | Clasificado temporalmente como `STILL UNPROVEN` al no haberse recuperado el documento primario |
| **Evidencia oficial posterior** | Tres documentos del **BCCR** confirman los 13 dígitos |
| **Estado actual** | `CONFIRMED NUMERIC` · `CHECK` soportado · **sin migración** |

El constraint **nunca cambió**: lo que cambió fue saber qué fuente lo respalda.

**No confundir con el hallazgo del código de actividad**, que es una conclusión distinta y
sigue vigente: para `CodigoActividad` el XSD exige **exactamente 6 caracteres, no seis
dígitos**, la validación contra el padrón del RUT queda diferida, y ahí **sí** hizo falta
una migración correctiva.

Las otras 18 restricciones de forma son fieles a la fuente o deliberadamente más
permisivas.

### Cierre de E4-B0 — baseline verificado

| | |
|---|---|
| Fixtures reales | **2** FE v4.4, byte-estables — huellas en la sección E4-A |
| Tests backend | **295 / 295 PASS** (incluye la cobertura de fixtures y cleanup de E4-B0) |
| Tests Day 2 | **32 / 32 PASS**, 0 omitidos |
| Frontend | `eslint` PASS · `tsc` PASS · `build` PASS |
| Migraciones | **11 locales · 11 remotas**, mismas versiones ordenadas |
| Tablas fiscales | **7** · filas fiscales: **0** |
| Migración de E3 | **sin modificar** |
| Migración correctiva | aplicada **una sola vez** y sincronizada |

**Seguridad del cleanup de tests, estado final:** `0` `DELETE` fiscal sin ámbito · `0`
`TRUNCATE` · `0` reinicio de esquema. La limpieza se acota al UUID exacto de los recursos
que crea la propia ejecución, corre en `finally` y sobrevive al fallo de un test. Es
**exclusiva del andamiaje de tests**: la ruta normal de la aplicación no cambia.

**Deuda histórica de tests, previa a E4-B0 y no introducida por él.** Las suites antiguas
—Day 2 y anteriores— no tenían teardown, y DEV conserva hoy datos de prueba de tenencia y
Auth acumulados. No se borra nada ahora: queda registrado como deuda conocida, fuera del
alcance de esta fase. Lo que sí está demostrado es que **E4-B0 no aporta crecimiento**:
sus ejecuciones dejan 0 residuo fiscal, 0 empresas, 0 membresías y 0 usuarios de Auth
nuevos.

---

## Checkpoint E — Fase E3 · COMPLETED

**Auditoría independiente de Codex: `CRITICAL 0 · HIGH 0 · MEDIUM 0 · LOW 1 no bloqueante ·
INFORMATIONAL 1` — PASS.** Primera implementación física del dominio fiscal.

| | |
|---|---|
| Migración | `20260830132124_create_fiscal_domain_tables.sql` (740 líneas) — **aplicada en DEV** |
| Migraciones | **10 locales · 10 remotas**, versiones ordenadas idénticas |
| Tablas fiscales de producto | **7** |
| Filas tras la limpieza de tests | **0** |
| Helper de escritura | `private.can_write_company(uuid)` |
| Políticas RLS | **21** = 7 SELECT + 7 INSERT + 7 UPDATE · **0 de DELETE** |
| Privilegios | `SELECT, INSERT` en las 7 · **0 UPDATE de tabla** · **15 columnas** con `UPDATE` |
| Índices | 9, según el diseño aprobado |

```
fiscal.source_documents      fiscal.line_discounts
fiscal.electronic_documents  fiscal.line_taxes
fiscal.document_parties      fiscal.document_references
fiscal.document_lines
```

Mapeo preservado: **48 campos lógicos con valor · 52 columnas físicas · 0 omitidos ·
0 pérdida de información**.

La migración lleva **13 comprobaciones de invariantes** en su propio cuerpo: si el estado
resultante no es el que el diseño exige, la migración falla y revierte.

### Integridad de tenant

```
toda fila fiscal está acotada por company_id
padre/hija            FK compuestas tenant-safe
asociación cruzada    RECHAZADA por PostgreSQL (23503)
```

**Topología de las FK directas a `public.companies`** — conclusión auditada:

```
FK directa:  source_documents · electronic_documents
Hijas:       ancladas transitivamente por la FK compuesta obligatoria al padre
Resultado:   SEGURO / NO ES UN DEFECTO
```

No se crean cinco FK redundantes.

### Artefacto y autorización

```
raw_xml         BYTEA NOT NULL
content_sha256  BYTEA NOT NULL
                CHECK octet_length(content_sha256) = 32
                CHECK content_sha256 = pg_catalog.sha256(raw_xml)
índice          (company_id, content_sha256)  NO UNICO

UNIQUE (company_id, clave)   ·   nunca UNIQUE (clave)
clave        50 dígitos ASCII
consecutivo  20 dígitos ASCII

private.can_write_company(uuid)  STABLE · SECURITY DEFINER · search_path="" · owner postgres
owner/editor → escritura fiscal autorizada    ·    viewer → solo lectura

fiscal_backend: sin USAGE sobre auth · sin SELECT sobre company_memberships · NOBYPASSRLS
```

### Evidencia de seguridad comprobada

A no ve a B ni B a A · `INSERT` cruzado rechazado por RLS · FK compuesta cruzada rechazada ·
owner y editor escriben, viewer solo lee · hechos de origen no actualizables ·
`DELETE` denegado · huella correcta aceptada e incorrecta rechazada · XML mal formado
preservado · clave y consecutivo validados · offset ±840 aceptado y fuera de rango
rechazado · `NULL` sigue `NULL` y el cero explícito sigue `0` · ambas FK opcionales
funcionan · `SET NULL` anula solo la columna opcional dejando `company_id` y `raw_xml`
intactos · sin fuga de identidad A→B en la misma sesión · **Data API sigue devolviendo
`PGRST106`** al schema `fiscal`.

### Nota de auditoría no bloqueante

Las 13 comprobaciones internas de la migración podrían ser más exhaustivas como defensa en
profundidad —no inspeccionan todas las expresiones de las políticas ni todos los roles, y
una de ellas usa la representación textual del ACL—. **No es un defecto de esquema,
seguridad, autorización, RLS ni ACL**: el estado real se comprobó por SQL estático,
catálogo, ACL efectivas y tests de comportamiento. Queda como endurecimiento opcional para
una pasada futura; no se modifica una migración ya aplicada por este motivo.

### Topología de las FK a `public.companies` — resuelta en auditoría

Durante la implementación se registró como posible desviación que la FK directa a
`public.companies` existiera solo en las dos raíces y no en las siete. **La auditoría
independiente lo evaluó y lo declaró SEGURO / NO ES UN DEFECTO**: las hijas quedan
ancladas transitivamente por su FK compuesta obligatoria al padre, y `RESTRICT` en las
raíces impide borrar una empresa con evidencia fiscal.

Comprobado además de forma empírica: una fila hija con `company_id` inexistente **es
rechazada** (`23503`). No se añaden cinco FK redundantes.

---

## Checkpoint E — Fase E2 · COMPLETED

**Auditoría final de Codex: `CRITICAL 0 · HIGH 0 · MEDIUM 0 · LOW 0` — PASS.**
Diseño físico únicamente: **0 migraciones, 0 SQL ejecutado, 0 tablas, 0 cambios de
código.**

### Línea base física

```
7  tablas fiscales de producto DISEÑADAS
0  tablas fiscales de producto IMPLEMENTADAS

fiscal.source_documents      fiscal.line_discounts
fiscal.electronic_documents  fiscal.line_taxes
fiscal.document_parties      fiscal.document_references
fiscal.document_lines
```

```
48  campos lógicos con valor del MVP
52  columnas físicas
 0  omitidos   ·   0 pérdida de información
```

```
SourceDocument      →  0..1  ElectronicDocument
ElectronicDocument  →  1..N  SourceDocuments
```

### Tenant

```
company_id en las siete tablas
relaciones padre/hija por FK compuesta (company_id, parent_id)

UNIQUE (company_id, id) SOLO en las tablas destino de FK compuesta:
    electronic_documents   ·   document_lines
```

Las otras cinco **no** lo llevan: sería un índice redundante sin función.

### Artefacto de origen

```
raw_xml         BYTEA NOT NULL
content_sha256  BYTEA NOT NULL
                CHECK octet_length = 32
                CHECK = pg_catalog.sha256(raw_xml)
```

**H-6 → CLOSED FOR MVP.** Trazabilidad: al cerrar **E1 estaba OPEN** —diferido
deliberadamente al diseño físico—; al cerrar **E2 queda CLOSED FOR MVP**. Almacenamiento
de objetos podrá evaluarse después con métricas reales, sin cambiar el modelo lógico.

### Autorización

```
owner   →  lectura + flujos fiscales de escritura autorizados
editor   →  lectura + flujos fiscales de escritura autorizados
viewer  →  solo lectura
DELETE  →  sin camino normal de aplicación

sin UPDATE a nivel de tabla · 15 columnas de metadato mutable en 3 de las 7 tablas
```

### Huecos

```
H-3  catálogos externos        OPEN   — no bloquea el primer esquema físico
H-4  semántica condicional     OPEN   — no bloquea
H-6  almacenamiento y huella   CLOSED FOR MVP
```

| | |
|---|---|
| Documento producido | [FISCAL_PHYSICAL_MODEL.md](FISCAL_PHYSICAL_MODEL.md) |
| Tablas diseñadas | **7**, todas en el schema `fiscal` |
| Cobertura de tipos | **48 / 48** campos con valor, ninguno sin decisión física |
| ADR propuestas | ADR-032 … **ADR-038**, todas en **PROPOSED** |
| Verificado contra la base real | `companies.id = uuid` · `is_company_member(uuid)→boolean` · límites de `numeric` |

**Decisión estructural: claves foráneas compuestas.** Cada tabla lleva `company_id` para
RLS, y cada hija referencia a su padre por `(company_id, parent_id)`. Hace **imposible en
el motor** que una línea de la empresa A cuelgue de un documento de la empresa B, sin
depender de FastAPI ni de RLS.

`UNIQUE (company_id, id)` **sólo en las tablas que son destino de una FK compuesta** —
`electronic_documents` y `document_lines`—, no en las siete. En una hoja que nadie
referencia sería un índice redundante sin función.

**Autorización de escritura cerrada como contrato** (ADR-038): helper privado
`private.can_write_company(uuid)`, `STABLE`, `SECURITY DEFINER`, `SET search_path = ''`,
con identidad de `auth.uid()` resuelta dentro y rol leído de `company_memberships` —nunca
del llamante ni del JWT—. `EXECUTE` sólo para `fiscal_backend`. **Sin `UPDATE` a nivel de
tabla**: 15 columnas mutables explícitas en 3 de las 7 tablas.

**Hallazgo con evidencia.** El XSD publicado enumera 12 códigos de referencia y 19 tipos
de documento referenciado; los Anexos vigentes definen 17 y 20. Un `CHECK` por valor
copiado del XSD **rechazaría comprobantes válidos hoy**. Los catálogos oficiales validan
**forma, nunca valor** — ADR-029 llevado al motor.

**Advertencia verificada.** PostgreSQL redondea en silencio los decimales excedentes
(`1.123456::numeric(18,5)` → `1.12346`) en lugar de rechazarlos. La captura corresponde a
la capa 1 de validación; el tipo no protege solo.

**H-6 CERRADO PARA EL MVP** — resuelve **almacenamiento e integridad del artefacto**, no
la equivalencia lógica entre documentos. `raw_xml bytea` + `content_sha256 bytea` dentro de
PostgreSQL: preserva bytes exactos, atomicidad con los metadatos, y reutiliza la frontera
fiscal ya auditada en vez de abrir una segunda superficie con Storage. Migrar a
almacenamiento de objetos queda como decisión futura con métricas reales, no como
bloqueante.

**Verificado en DEV, no supuesto:** `pgcrypto` 1.3 está instalado, pero `fiscal_backend`
**no tiene `USAGE` sobre `extensions`** —la llamada a `digest` devuelve `42501`—. Usarlo
exigiría ampliar la frontera fiscal. No hace falta: **`sha256(bytea)` es nativa de
`pg_catalog`**, alcanzable por el rol, `IMMUTABLE`, y coincide con pgcrypto y con
`shasum -a 256`. La huella se calcula en FastAPI y **se verifica en la base de datos** con
`CHECK (content_sha256 = pg_catalog.sha256(raw_xml))` — comprobado: acepta la correcta,
rechaza la incorrecta con `23514`.

**Precisión sobre la huella.** Misma huella es una **señal criptográficamente muy fuerte**
de equivalencia de bytes, no una prueba matemática; para certeza con ambos artefactos
disponibles, la comparación directa `raw_xml = raw_xml`. Huella distinta **no** prueba
semántica fiscal distinta: misma `Clave` con huellas divergentes señala **artefactos
divergentes que requieren evaluación**, no automáticamente un conflicto de integridad.
Clasificarlo como conflicto exige comparar el **contenido fiscal reportado**, no hashes.
La única conclusión automática es *no fusionar en silencio*.

**Comportamiento de las FK opcionales verificado** con tablas temporales en transacción
revertida (PG 17.6): `ON DELETE SET NULL (columna)` aceptada; `NULL` permitido; destino
del mismo tenant permitido; destino de **otro tenant rechazado (`23503`)**; el borrado
anula sólo la columna opcional dejando `company_id` y la carga `bytea` intactos.

### Autorización de escritura — contrato cerrado en E2

E2 descubrió que `private.is_company_member` comprueba **pertenencia, no rol**, y que en
todo el proyecto no existía ni una sola política de escritura: con sólo esa condición, un
`viewer` podría modificar datos fiscales por ser miembro. **El contrato que faltaba queda
cerrado en esta fase** ([ADR-038](DECISIONS.md#adr-038)):

```
owner   →  lectura + flujos fiscales de escritura autorizados
editor  →  lectura + flujos fiscales de escritura autorizados
viewer  →  solo lectura
DELETE  →  sin camino normal de aplicación

private.can_write_company(p_company_id uuid)
    RETURNS boolean · LANGUAGE sql · STABLE
    SECURITY DEFINER · SET search_path = ''

autoridad  public.company_memberships
identidad  auth.uid(), resuelta dentro del helper
regla      company_id = p_company_id AND user_id = auth.uid()
           AND role IN ('owner','editor')
ACL        EXECUTE solo para fiscal_backend

RLS  SELECT using(member) · INSERT with check(can_write)
     UPDATE using(can_write) with check(can_write) · DELETE sin política
```

Sin `UPDATE` a nivel de tabla: sólo las 15 columnas de metadato mutable.
`fiscal_backend` sigue **sin `USAGE` sobre `auth`** y **sin `SELECT` sobre
`company_memberships`**.

```
CONTRATO DE DISEÑO  =  CERRADO EN E2
IMPLEMENTACIÓN      =  E3
```

---

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
| Huecos abiertos **al cerrar E0** | 3 — H-3, H-4, H-6. **Cerrados entonces: H-1, H-2, H-5, H-7, H-8.** Registrada la incidencia técnica I-1. *(H-6 quedó **CERRADO PARA EL MVP** en el diseño de E2 — ver la sección de la Fase E2.)* |
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
