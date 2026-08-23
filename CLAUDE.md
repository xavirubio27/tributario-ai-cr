# CLAUDE.md

Contexto operativo para Claude Code en este repositorio.

> **Empieza toda sesión leyendo [docs/PROJECT_STATE.md](docs/PROJECT_STATE.md)** — es la
> fotografía del estado actual y el punto de entrada del proyecto.
>
> **Las reglas completas del proyecto están en [AI_INSTRUCTIONS.md](AI_INSTRUCTIONS.md).**
> Este documento es un resumen operativo; ante cualquier discrepancia, prevalece
> `AI_INSTRUCTIONS.md`.

---

## Qué estamos construyendo

**Asistente Tributario IA — Costa Rica.** Una capa de inteligencia tributaria sobre
los datos fiscales reales de un contribuyente costarricense.

Permite a una empresa conversar con sus propios datos fiscales y obtener respuestas con
cifra, desglose, fuente normativa y advertencias.

**No es:** software contable · facturación electrónica · POS · ERP · chatbot tributario ·
ChatGPT con legislación en el prompt.

---

## Principio rector

```
LLM  ≠  Tax Engine
```

El LLM interpreta, orquesta y explica. El Tax Engine calcula.
**El LLM nunca produce una cifra fiscal ni cita normativa de memoria.**

---

## Arquitectura — los cuatro componentes

| Componente | Función | No puede |
|---|---|---|
| **Tax Data Layer** | Datos fiscales, aislados por empresa, trazables | Calcular impuestos |
| **Tax Engine** | Cálculo determinista y versionado | Tocar DB, red, LLM o FastAPI |
| **Knowledge Base** | Normativa con fuente y vigencia | Calcular; contener datos de contribuyentes |
| **AI Agent** | Interacción vía tools controladas | Calcular; acceso libre a la base de datos |

```
Frontend (Next.js) ──JWT──▶ FastAPI ──▶ Tax Data Layer (Postgres + RLS)
                                    ├──▶ Tax Engine (paquete puro)
                                    └──▶ Knowledge Base (pgvector)
       └── Supabase directo: solo Auth (y Storage con políticas explícitas)
```

FastAPI es la **única puerta a los datos fiscales**.

---

## Stack previsto

Next.js · React · TypeScript · Python · FastAPI · Supabase (PostgreSQL, Auth, Storage,
pgvector, RLS) · Vercel · GitHub.
Capa de IA mediante abstracción de proveedor (OpenAI / Anthropic / Gemini).

Hosting del backend: **decisión pendiente** (ADR-011).

---

## Reglas críticas

1. **No inventar APIs** — endpoints, formatos ni contratos externos.
2. **No inventar legislación** — ni tasas, artículos, vigencias o versiones de formato.
   Sin fuente oficial verificada, se deja el hueco marcado.
3. **LLM y Tax Engine separados** — ninguna cifra fiscal sale del razonamiento de un modelo.
4. **Todo cálculo tributario crítico tiene tests.**
5. **Toda regla lleva** fuente · documento o artículo · fecha · vigencia · versión;
   todo cálculo contempla `as_of_date` y persiste la versión aplicada.
6. **Nunca secretos en el repositorio** — variables de entorno; tampoco datos fiscales reales.
7. **Multiempresa siempre** — RLS como mecanismo de aislamiento; `service_role` no es la
   vía habitual de acceso a datos de usuarios.
8. **Trazabilidad** — todo dato fiscal apunta a su documento origen;
   `reported_*` nunca se confunde con `computed_*`.
9. **Construcción incremental** — se sigue el orden del ROADMAP.
10. **Un cambio, un propósito** — nada de refactors masivos ni abstracciones prematuras.
11. **Ciclo:** arquitectura → implementación → tests → ejecución → corrección → documentación.
12. **Avisar antes** de cualquier decisión arquitectónica que pueda comprometer el proyecto.
13. **Revisar el diff completo** antes de aplicar configuración a un entorno remoto
    (`supabase config push` empuja el archivo entero y no tiene `--dry-run`).

### Convenciones

- Documentación en **español**; código, identificadores y commits en **inglés**.
- Importes monetarios en **decimal exacto**, nunca coma flotante.
- Tests unitarios junto al módulo; `tests/` en la raíz para integración y end-to-end.

---

## Flujo de trabajo

**Antes de implementar:**
1. Confirma en qué fase del [ROADMAP.md](ROADMAP.md) estás. No adelantes fases.
2. Lee la documentación del componente que vas a tocar (tabla siguiente).
3. Si la tarea implica una decisión arquitectónica relevante, **explícala antes**.

**Al implementar:** sigue el ciclo de la Regla 11. Los tests forman parte de la
implementación.

**Si algo no está verificado:** decláralo, márcalo como hueco, y regístralo en
`docs/DECISIONS.md` si condiciona el diseño. Nunca rellenes con un valor plausible.

---

## Qué consultar antes de modificar

| Vas a tocar | Lee antes |
|---|---|
| Modelo de datos fiscales | ARCHITECTURE.md §6, §7 · docs/GLOSSARY.md |
| Tax Engine | ARCHITECTURE.md §8 · DECISIONS ADR-004, ADR-005 |
| Seguridad, RLS, autenticación | ARCHITECTURE.md §6 · DECISIONS ADR-001, ADR-002 |
| Pipeline de ingesta XML | ARCHITECTURE.md §5.2 · DECISIONS ADR-006, ADR-007 |
| Knowledge Base o RAG | ARCHITECTURE.md §9 · DECISIONS ADR-009 |
| AI Agent o tools | ARCHITECTURE.md §10 |
| Alcance, fases o producto | PRODUCT_SPEC.md · ROADMAP.md |
| Cualquier regla de desarrollo | **AI_INSTRUCTIONS.md** |

---

## Estado del repositorio

**Day 2 — Infrastructure & Tenancy.**

| Componente | Estado |
|---|---|
| Documentación y reglas | ✅ |
| Esquema de tenancy (`companies`, `company_memberships`) | ✅ migraciones aplicadas |
| Row Level Security | ✅ activa, aislamiento probado (11/11 tests) |
| **Next.js foundation** | ✅ **implementada** |
| **Auth** | ⬜ **no implementada** |
| **Company UI** | ⬜ **no implementada** |
| Backend FastAPI · Tax Engine · Parser XML · KB/RAG · AI Agent · CI | ⬜ no iniciados |

**Supabase:** proyecto de **DESARROLLO** conectado. Migraciones en `supabase/migrations/`,
aplicadas con `supabase db push`. Config como código con `supabase config push`
(ver Regla 15). Entorno local con Docker diferido (ADR-018).

**Frontend:** Next.js 16 (App Router, `src/`, Tailwind 4, TypeScript). Clientes Supabase
preparados en `src/lib/supabase/{client,server}.ts`. Sesión y `proxy.ts` pendientes.

Verifica antes de asumir que algo existe.

**Siguiente hito:** signup / login / sesión, y creación y listado de empresa desde la
interfaz. Después, la ingesta de XML.
