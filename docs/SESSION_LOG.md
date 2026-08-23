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

### Next
- Checkpoint E — Authentication: `proxy.ts`, signup, login, logout, ruta protegida y
  verificación server-side con `getClaims()`
