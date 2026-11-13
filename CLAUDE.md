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

**La fotografía vigente está en [docs/PROJECT_STATE.md](docs/PROJECT_STATE.md)**
(sección *Current Phase* y *Next Action*) — es el punto de entrada de toda sesión.
Aquí solo va el mapa grueso, para orientarse; ante cualquier duda manda Git.

| Componente | Estado (nov 2026) |
|---|---|
| Tenancy multiempresa, RLS, Auth, UI de empresa | Existe y probado |
| FastAPI + identidad JWT → PostgreSQL → RLS, roles `app_backend` / `fiscal_backend` / `inbound_backend` | Existe y probado |
| Dominio fiscal CR: parser XML v4.4, validación XSD, persistencia en dos fases, subida web y bandeja (C1–C3) | Existe y probado |
| Canal de correo (C4): registro de Buzones Tribuu y adaptador Resend/Svix (C4-B1, C4-B2) | Existe **como librería**; sin endpoint de webhook montado |
| C4-B3 — captura durable, idempotencia, RAW/adjuntos, ACK | Diseñado, **no implementado** (ADR-050 en DRAFT) |
| Tax Engine (`tax-engine/`), Knowledge Base, AI Agent, LLM, WhatsApp | **No existen** |

Fixtures reales: `backend/tests/fixtures/fiscal/real/` contiene comprobantes reales del
propio titular del proyecto y de su empresa, versionados con su autorización expresa.
Es una excepción consciente a la Regla 6; no añadir comprobantes de terceros ajenos.

**Supabase:** proyecto de **DESARROLLO** conectado. Migraciones en `supabase/migrations/`,
aplicadas con `supabase db push`. Config como código con `supabase config push`
(ver Regla 15). Entorno local con Docker diferido (ADR-018).

Verifica contra Git, tests y migraciones antes de asumir que algo existe (Regla 16).

---

## Cómo se trabaja con agentes

Hasta nov 2026 el ciclo era manual: ChatGPT orquestaba, Claude Code implementaba y Codex
auditaba, con el titular copiando y pegando entre ellos. Ahora todo ocurre aquí:

| Rol | Quién | Cómo |
|---|---|---|
| Orquestador e implementador | La sesión principal de Claude Code | `/checkpoint <tarea>` |
| Aprobación de diseño (el **GO**) | **Xavier**, el titular | La sesión se detiene y espera su GO explícito |
| Auditor independiente (antes Codex) | Subagente `auditor` | `/auditar` o lo invoca `/checkpoint` |

Reglas del ciclo:

- **Ninguna implementación arranca sin GO explícito de Xavier** sobre el diseño. Un diseño
  aprobado se registra (ADR o documento de diseño) antes de escribir código.
- **Quien implementa no se audita a sí mismo.** El cierre de un checkpoint exige un
  reporte del subagente `auditor` sin hallazgos CRÍTICO/ALTO abiertos.
- **Commit solo tras auditoría PASS y con visto bueno de Xavier.** Nunca `push` a `main`
  sin que él lo pida.
- Las decisiones de negocio y los criterios tributarios los valida una persona (Xavier
  o un contador). Los tests validan código, no criterio fiscal.

### Ejecución en este entorno

- La ruta local del repo contiene `:` y rompe la resolución de binarios por PATH:
  usar `./node_modules/.bin/<bin>` y, en Python, `PYTHONPATH=./.pydeps:.`.
- La suite completa del backend tarda ~1 h contra Supabase DEV: durante el ciclo se
  corren **tests focalizados**; la suite completa, al cierre del checkpoint.
- Flake ambiental conocido: `test_transaction_identity.py::test_identity_disappears_after_rollback`.
