# TRIBUU AI — Informe maestro de continuidad (HANDOFF)

> **Propósito.** Transferir el contexto completo del proyecto a una nueva conversación de
> orquestación (ChatGPT). Estructura de trabajo: **ChatGPT** = orquestador/arquitecto ·
> **Claude Code** = implementación · **Codex** = auditor independiente.
>
> **Fecha del informe:** 2026-11-06 · **HEAD auditado:** `62e20c9` · **Rama:** `main`
>
> **Reglas de veracidad.** Cada afirmación relevante va etiquetada:
> `[VERIFICADO]` confirmado en esta sesión contra código/tests/registros ·
> `[DOCUMENTADO]` figura en documentación del repo pero no se reverificó aquí ·
> `[PENDIENTE]` sin evidencia suficiente en esta sesión.
>
> Durante esta auditoría **no** se modificó código, migraciones ni despliegues. No se
> exponen secretos. Las únicas escrituras fueron este archivo y las ediciones
> documentales previas de ADR-050 (ver §4).

---

## Resumen ejecutivo (≈650 palabras)

**Tribuu.ai** es una capa de inteligencia tributaria sobre los datos fiscales reales de una
empresa costarricense, bajo el principio rector **`LLM ≠ Tax Engine`**: el modelo interpreta
y explica, un motor determinista calcula, y el LLM nunca emite una cifra fiscal de memoria.
El proyecto avanza por checkpoints estrictos (diseño → implementación → tests → auditoría
Codex → remediación → cierre), con ChatGPT como orquestador, Claude Code como implementador y
Codex como auditor.

**Dónde está realmente** (verificado contra git, migraciones, colección de tests y typecheck,
no contra el roadmap): están **operativos a nivel de código y tests** los cimientos de
seguridad (tenancy multiempresa con RLS; identidad JWT→FastAPI→PostgreSQL→RLS; roles
`app_backend`/`fiscal_backend`/`inbound_backend` sin BYPASSRLS), el **dominio fiscal
costarricense** (parser puro de comprobantes, validación XSD contra esquemas oficiales v4.4,
persistencia transaccional en dos fases que preserva la evidencia antes de interpretarla) y
la **subida manual de XML por web** con bandeja. HEAD `62e20c9`, 31 commits, rama `main`, 20
migraciones **local = remoto sin drift** (verificado en vivo). El backend colecciona **1289
tests** sin errores de importación; el frontend pasa `tsc --noEmit` con exit 0.

**Qué está a medias**: el canal de ingesta por correo (C4). Existen como **librería** la
autorización de máquina y el registro de Buzones Tribuu (C4-B1) y el adaptador Resend +
verificación Svix + routing por destinatario (C4-B2, Codex PASS). Pero **no hay endpoint HTTP
de webhook montado, ni captura durable de evidencia, ni ACK productivo**: eso es C4-B3, que
está **diseñado pero no implementado**. El diseño físico (C4-B3-A2: abstracción EvidenceBlob;
tablas `evidence_blobs`/`provider_events`/`email_messages`; idempotencia de evento y de
mensaje; `observed_blob_id` para preservar conflictos sin sobrescribir; `MAX_RAW_EMAIL_BYTES=
64 MiB` como política; oversize terminal; RLS con solo INSERT+SELECT; FKs compuestas
tenant-safe) está entregado y **pendiente de aprobación del orquestador**. ADR-050 permanece
**DRAFT**.

**Qué no existe todavía** (verificado): el **Tax Engine** (`tax-engine/` está vacío, solo
`.gitkeep`), la Knowledge Base/RAG, el AI Agent, el proveedor LLM y los embeddings. El
producto **aún no "responde con cifra"**: toda la capa de cálculo e IA está por construir. El
MVP está en fase de **ingesta**, no de inteligencia.

**Calidad y seguridad**: 726 funciones de test en backend (1289 casos con parametrización) +
167 casos vitest en frontend. La suite completa de backend **no se ejecutó** esta sesión
(~56–64 min contra el Supabase DEV compartido); se verificó que colecciona limpiamente. Hay
un **flake ambiental conocido** (`test_identity_disappears_after_rollback`). No hay CI. El
`RESEND_WEBHOOK_SECRET` expuesto en una auditoría previa fue rotado; el spike de Render sigue
**pendiente de teardown**.

**Decisiones del orquestador que bloquean el avance**: (1) aprobar C4-B3-A2 y mover ADR-050 a
ACCEPTED; (2) ADR-011 hosting del backend (⏳); (3) ADR-016 procesamiento en segundo plano
(⏳); (4) ADR-013/014 LLM y embeddings (⏳). Sin (1) no empieza la implementación; sin (2)/(3)
no hay webhook productivo ni procesamiento asíncrono durable; (4) bloquea la futura capa de IA.

**Secuencia de producto** (documentada): C4 (buzón + captura durable) → C5 (perfil fiscal +
dirección determinista del documento) → D1/D2 (documento externo + inteligencia documental) →
D3 (clasificación económica) → C6 (Tax Engine de IVA). Hasta D3 la UI puede mostrar "importes
identificados", nunca "gastos".

**Conclusión**: la base de seguridad y el dominio fiscal son sólidos y verificables; el
proyecto está en la frontera entre "recibe y preserva evidencia" e "implementa la captura
durable automatizada". El cuello de botella no es técnico sino de **aprobación de diseño**
(C4-B3-A2 / ADR-050).

---

## Bloqueos críticos

1. **[DECISIÓN] C4-B3-A2 sin aprobar / ADR-050 en DRAFT** — detiene toda la implementación de
   C4-B3. Es el bloqueo nº1.
2. **[DECISIÓN] ADR-011 hosting backend (⏳)** — sin host no hay webhook inbound productivo ni,
   después, runtime del Tax Engine.
3. **[DECISIÓN] ADR-016 procesamiento en segundo plano (⏳)** — necesario para el "procesamiento
   asíncrono durable después del ACK" (ADR-047).
4. **[OPERATIVO] Spike de Render sin teardown + secreto inbound** — superficie viva pendiente de
   cerrar; no reutilizar el secreto del spike en producción.
5. **[RIESGO] Sin CI + suite backend larga (~1 h) + flake ambiental** — la verificación depende
   de ejecución local; la auditoría de C4-B3 será costosa sin CI.
6. **[MENOR] `supabase db query` con TransportError transitorio** — introspección SQL directa
   intermitente (el `migration list` sí funciona).

---

## Recomendación para retomar

**Camino crítico inmediato (una sola decisión desbloquea todo):** que ChatGPT **apruebe el
diseño C4-B3-A2 y promueva ADR-050 a ACCEPTED**. En el mismo turno conviene cerrar ADR-011
(hosting) y ADR-016 (background), porque condicionan el endpoint productivo y el procesamiento
posterior al ACK.

**Primer paso de Claude Code tras ese GO:** abrir **C4-B3-A3** (cierre de diseño de descarga
limitada/streaming, bounded concurrency, endpoint HTTP y cableado del ACK) y luego implementar
C4-B3 en este orden: migración de las 3 tablas `inbound.*` (RLS ENABLE+FORCE, grants
INSERT+SELECT, FKs compuestas, CHECKs con BYTEA(32) y `extensions.digest`) → captura durable
pre-ACK + montaje del router de webhook en `main.py` → tests → **auditoría Codex**. Criterios
de aceptación en §6.

**Antes de implementar**, el orquestador debería decidir también: (a) si commitear las 3
ediciones de docs de ADR-050 hoy sin commitear, (b) dónde documentar el diseño aprobado
(expandir ADR-050 vs `docs/design/C4-B3.md`), y (c) el teardown del spike de Render. Ninguna
requiere escribir código.

---

## 0. Método y comandos ejecutados (evidencia)

`[VERIFICADO]` Comandos no destructivos ejecutados en esta sesión y su resultado:

| Comando | Resultado |
|---|---|
| `git log --pretty -20` / `git rev-list --count HEAD` | HEAD `62e20c9`; **31 commits**; rama `main` |
| `git status --short` | 3 docs modificados sin commitear: `ROADMAP.md`, `docs/DECISIONS.md`, `docs/PROJECT_STATE.md` |
| `supabase migration list --linked` | **20 local = 20 remoto**, sin drift; proyecto DEV accesible |
| `pytest --collect-only` (backend, sin DB) | **1289 tests recogidos** en 0.57s, sin errores de importación |
| `tsc --noEmit` (frontend) | **exit 0** (typecheck limpio) |
| `grep -c 'def test_'` (backend) | **726** funciones de test en 20 archivos |
| conteo `it(`/`test(` (vitest) | **167** casos en 8 archivos `.test.ts` |
| `find tax-engine` | solo `.gitkeep` (0 bytes) |
| `supabase db query --linked "…"` | **falló** con `LegacyDbConfigLoginRoleNetworkError: TransportError` (transitorio) en 3 intentos → introspección SQL directa no completada esta sesión |

> La suite completa de backend **no** se ejecutó (dura ~56–64 min contra el Supabase DEV
> compartido). Se verificó que **colecciona** sin errores; la ejecución end-to-end queda
> `[PENDIENTE]` en esta sesión.

---

## 1. Estado general

### Objetivo y alcance
`[DOCUMENTADO]` **Tribuu.ai** es una capa de inteligencia tributaria sobre los datos
fiscales reales de un contribuyente costarricense: permite a una empresa "conversar con
sus propios datos fiscales" y obtener respuestas con cifra, desglose, fuente normativa y
advertencias. Principio rector: **`LLM ≠ Tax Engine`** — el LLM interpreta/orquesta/explica;
el Tax Engine calcula; el LLM nunca produce una cifra fiscal ni cita normativa de memoria.
Cuatro componentes: Tax Data Layer, Tax Engine, Knowledge Base, AI Agent.

### Funcionalidades implementadas `[VERIFICADO]`
- **Tenancy multiempresa con RLS** (schemas `public`/`private`): tablas de tenancy,
  `company_memberships`, RPC de creación de empresa, least-privilege.
- **Identidad JWT → FastAPI → PostgreSQL → RLS**: endpoint `/diagnostics/identity` que
  demuestra la propiedad de aislamiento; verificación ES256 vía JWKS.
- **Roles de base de datos**: `app_backend` (LOGIN, NOBYPASSRLS, NOINHERIT), `fiscal_backend`,
  `inbound_backend` (NOLOGIN), asumidos vía `SET LOCAL ROLE`.
- **Dominio fiscal CR (comprobantes electrónicos)**: esquema `fiscal`, tablas de dominio,
  parser puro (sobre + partes + líneas + impuestos + descuentos + referencias), validación
  XSD contra esquemas oficiales v4.4 versionados en el repo, persistencia transaccional en
  dos fases (captura de evidencia → interpretación), ingesta/orquestación de SourceDocument.
- **Subida manual de XML por web**: `POST` de comprobante + bandeja (`GET`) con contrato de
  lectura; frontend Next.js (login/signup, workspace de empresa, formulario de subida,
  bandeja fiscal).
- **Canal inbound (parcial, ver abajo)**: registro de Buzones Tribuu (C4-B1) y adaptador
  Resend/Svix + routing (C4-B2) como **librería**.

### Funcionalidades parcialmente implementadas `[VERIFICADO]`
- **Canal de ingesta por correo (C4-B)**: existe la autorización de máquina + registro de
  inbox (C4-B1) y el adaptador de verificación Svix + normalización + routing por
  destinatario (C4-B2), pero **como módulo de librería**. **No hay endpoint HTTP de webhook
  montado**, **no hay captura durable de evidencia**, **no hay ACK productivo**. Eso es C4-B3
  (solo diseñado, no implementado).

### Funcionalidades pendientes `[VERIFICADO / DOCUMENTADO]`
- **Tax Engine**: `tax-engine/` está **vacío** (solo `.gitkeep`). No existe ningún cálculo
  tributario. `[VERIFICADO]`
- **Knowledge Base / RAG, AI Agent, embeddings, LLM**: no existen. `[VERIFICADO]`
- **Perfil fiscal de empresa (C5), documentos externos (D1), inteligencia documental (D2),
  clasificación económica (D3), IVA (C6), WhatsApp (W1–W4)**: no iniciados. `[DOCUMENTADO]`

### Estado del MVP
`[VERIFICADO]` El MVP está en la **fase de ingesta**: cimientos de seguridad + dominio
fiscal + subida web **operativos a nivel de código y tests**; el canal automatizado por
correo está a mitad (adaptador listo, captura durable no). **No hay todavía ningún
cálculo tributario ni IA**: el producto aún no "responde con cifra" — esa parte (Tax
Engine, KB, Agent) está por construir.

---

## 2. Arquitectura técnica

### Stack `[VERIFICADO]` (versiones exactas de los manifiestos)
- **Backend**: Python ≥3.12 · FastAPI 0.141.1 · uvicorn 0.52.4 · psycopg[binary,pool] 3.3.4 ·
  pyjwt[crypto] 2.13.0 · python-dotenv 1.2.3 · lxml 6.0.2 (XSD) · svix 2.9.1 (webhooks).
  Dev: pytest 9.1.1 · httpx 0.28.1. Sin ORM, sin Celery/Redis, sin SDK de IA (deliberado).
- **Frontend**: Next.js 16.3.2 · React 19.2.8 · @supabase/ssr 0.12.4 · @supabase/supabase-js
  2.112.3 · TailwindCSS 4 · TypeScript 5.
- **Infra/tooling**: Supabase CLI 2.115.0 (hay v3.0.0 disponible); PostgreSQL + Auth +
  (pgvector/Storage previstos) vía Supabase; Vercel/GitHub previstos.

### Estructura de carpetas `[VERIFICADO]`
```
backend/app/        FastAPI: api/, auth.py, authorization.py, config.py, db.py, main.py,
                    fiscal/ (parser/, xsd/, ingestion, persistence, inbox, models, errors),
                    inbound/ (events, resend_adapter, routing, tokens, errors)
backend/tests/      20 archivos test_*.py (pytest) + conftest.py
backend/resources/  esquemas XSD oficiales v4.4 (producción, no paquete Python)
frontend/src/       app/ (login, signup, app/[companyId]), components/, lib/ (auth,
                    companies, fiscal, server, supabase), proxy.ts
supabase/migrations/ 20 migraciones .sql
tax-engine/         VACÍO (.gitkeep) — no implementado
tests/              Vitest E2E/contrato (auth, companies, fiscal, rls, config) — TypeScript
spikes/c4b0-email-providers/  spike desechable de evaluación de proveedor (C4-B0)
docs/               PROJECT_STATE, DECISIONS (50 ADR), ROADMAP(raíz), FISCAL_*, GLOSSARY, etc.
```

### Frontend / Backend `[VERIFICADO]`
- **Frontend**: Next.js (server actions + Supabase SSR). Habla **solo** con Supabase Auth
  directamente; los datos fiscales pasan por el backend (`lib/server/backend.ts`,
  `lib/server/inbox.ts`, `proxy.ts`).
- **Backend FastAPI — superficie real montada**: `GET /health`, `GET /diagnostics/identity`,
  `POST` subida de comprobante fiscal, `GET` lista de bandeja fiscal. **Solo** se monta
  `fiscal_documents_router`. No hay router inbound, ni API de impuestos, ni CRUD de empresas.

### Base de datos y esquema principal `[VERIFICADO (migraciones) / parcial]`
- **20 migraciones**, local = remoto, sin drift. Esquemas: `public` (tenancy/empresas/
  memberships), `private` (helpers RLS, p.ej. `current_user_id`, contexto inbound), `fiscal`
  (dominio de comprobantes, `source_documents`, documentos electrónicos, partes, líneas,
  impuestos, referencias), `inbound` (registro `company_inboxes`, rol/contexto de máquina).
- `[DOCUMENTADO/confirmado por orquestador, no reverificado aquí]` `fiscal.source_documents.
  content_sha256` = **BYTEA**; **pgcrypto 1.3** instalado en schema `extensions`;
  `inbound.company_inboxes` tiene **UNIQUE(company_id, id)**. (El `db query` directo falló por
  error transitorio de login del CLI; ver §0.)

### Servicios externos e integraciones `[VERIFICADO/DOCUMENTADO]`
- **Supabase** (Postgres + Auth; pgvector/Storage previstos pero no usados aún).
- **Resend** = proveedor inbound MVP (webhooks firmados con Svix); **Mailgun** = fallback
  validado. `[DOCUMENTADO]` No hay integración productiva aún (solo adaptador + spike).

### Flujo de procesamiento de documentos `[VERIFICADO (web) / DISEÑADO (correo)]`
1. **Hoy (web)**: usuario sube XML → `POST` backend → captura de evidencia (SourceDocument,
   XML original inmutable + SHA-256) → parser puro → persistencia transaccional de hechos
   **reportados** → bandeja.
2. **Correo (C4, no operativo)**: correo → webhook Resend → verificación Svix (RAW antes de
   parsear) → routing por `data.to` → (C4-B3) captura durable pre-ACK de evidencia →
   (C4-B4) wiring al C2 fiscal para XML. Diseñado, no implementado.

### Autenticación y permisos `[VERIFICADO]`
JWT de Supabase Auth verificado por FastAPI (ES256/JWKS) → conexión como `app_backend` →
`SET LOCAL ROLE authenticated` + identidad transaction-scoped (`set_config` de
`request.jwt.claims`) → **RLS** decide visibilidad por tenant. Modelo de permisos
usuario–empresa (ADR-015) resuelto en DB, nunca declarado por el cliente. `inbound` es
backend-only (sin JWT de navegador, sin service_role, sin BYPASSRLS).

### Tax Engine y componentes de IA `[VERIFICADO]`
**No existen.** `tax-engine/` vacío; sin KB/RAG, sin AI Agent, sin proveedor LLM elegido.
La arquitectura (ARCHITECTURE.md §8–§10) los describe pero no hay código.

---

## 3. Últimas implementaciones

### Últimos 20 commits `[VERIFICADO]`
```
62e20c9  feat: add Resend inbound adapter and tenant routing (C4-B2)
4f51728  feat: add inbound inbox registry and machine authorization (C4-B1)
247d3b6  docs: close C4-B0 with Resend selected and ADR-047 accepted
58bbd8c  docs: close C4 email intake architecture
5dc1de1  docs: close C3 web fiscal vertical
fb57c0c  feat: add fiscal document inbox
a488dd8  feat: add company fiscal upload workspace
39deee6  docs: expand MVP roadmap for external documents and WhatsApp
3b04280  feat: add fiscal document upload endpoint
35a6da8  build: prepare fiscal upload runtime
27c7d85  feat: implement fiscal document ingestion
07ab026  feat: implement transactional fiscal persistence
9a798cc  docs: finalize fiscal persistence architecture
9ce64a4  feat: parse fiscal transaction body
4c5c696  feat: implement fiscal document envelope parser
5e7fcce  fix: align receiver identification nullability
2e04d9e  feat: establish reproducible fiscal xsd validation
a9ad23a  feat: harden fiscal fixtures and source semantics
d72bae4  test: establish real fiscal xml fixtures
eb22b89  feat: create fiscal domain tables
```

### Últimos módulos desarrollados `[VERIFICADO]`
`backend/app/inbound/` (events, resend_adapter, routing, tokens, errors) — C4-B1/B2.
Migración `20261102120000_create_inbound_inbox_registry.sql`. Tests
`test_inbound_registry.py` (37 fn) y `test_inbound_resend_adapter.py` (36 fn).

### Cambios recientes importantes `[VERIFICADO]`
- Trabajo sin commitear en el árbol (3 docs): corrección de estado de **ADR-050 → DRAFT**,
  **C4-B3 = DESIGN / NOT IMPLEMENTED** en PROJECT_STATE, y registro de la deuda técnica
  "Evidence Blob Object Storage migration" + el literal normativo en DECISIONS/PROJECT_STATE/
  ROADMAP.

### Decisiones arquitectónicas implementadas (selección) `[DOCUMENTADO]`
ADR-012 (identidad→RLS), ADR-017/020 (frontera fiscal, schema `fiscal` + rol de ejecución),
ADR-044 (ingesta en dos fases: evidencia antes de interpretar), ADR-045 (frontera web
Next→FastAPI→RLS), ADR-046/047/048/049 (Buzón Tribuu, Resend MVP + captura durable pre-ACK,
identidad de máquina inbound, adaptador Resend/Svix). ADR-050 (EvidenceBlob) **DRAFT**.

---

## 4. Calidad y seguridad

### Pruebas automatizadas `[VERIFICADO estructura / PENDIENTE ejecución]`
- **Backend**: 1289 tests coleccionan sin error; 726 funciones en 20 archivos. Ejecución
  completa **no realizada** esta sesión (~56–64 min, Supabase DEV compartido).
- **Frontend/E2E (vitest)**: 167 casos en 8 archivos; `tsc --noEmit` = **exit 0**. Suite
  vitest **no ejecutada** esta sesión.

### Pruebas fallidas conocidas `[DOCUMENTADO]`
`test_transaction_identity.py::test_identity_disappears_after_rollback` es un **flake
ambiental** (el pooler de Supabase cierra la conexión de sesión única); se autodeclara
inconcluso. Histórico reportado: backend "1288 passed + 1 environmental flake".

### Problemas técnicos conocidos `[VERIFICADO/DOCUMENTADO]`
- La ruta del repo contiene `:` (`Projects:Asistente-Tributario`) → rompe la resolución de
  binarios por PATH. Convención: invocar binarios como `./node_modules/.bin/<bin>` y Python
  con `PYTHONPATH=./.pydeps:.`. `[VERIFICADO]`
- `supabase db query --linked` sufre errores transitorios de login-role
  (`TransportError`); el harness ya tiene patrón de reintento. `[VERIFICADO esta sesión]`
- CLI de Supabase desactualizado (2.115.0 vs 3.0.0). `[VERIFICADO]`

### Vulnerabilidades / riesgos pendientes `[DOCUMENTADO]`
- `RESEND_WEBHOOK_SECRET` fue expuesto en una auditoría previa y **rotado manualmente**;
  no reutilizar el secreto del spike en producción.
- Spike en Render (`tribuu-spike-inbound`) con **teardown pendiente**.
- Sin CI (`.github/workflows` ausente `[VERIFICADO]`): los tests dependen de ejecución local.

### Migraciones `[VERIFICADO]`
20 aplicadas, local = remoto, sin drift. Config como código vía `supabase config push`
(empuja el archivo entero, sin `--dry-run`: revisar diff antes — Regla 13/15).

---

## 5. Estado operativo

- **Entornos** `[DOCUMENTADO]`: un único proyecto Supabase de **DESARROLLO** conectado
  (`ACTIVE_HEALTHY`; reachable confirmado por `migration list`). Entorno local con Docker
  **diferido** (ADR-018). No hay staging/producción.
- **Despliegues** `[DOCUMENTADO]`: no hay despliegue productivo de backend ni frontend. El
  único despliegue vivo es el **spike** desechable en Render (pendiente de teardown). Hosting
  de backend **sin decidir** (ADR-011 ⏳).
- **Integraciones activas** `[VERIFICADO]`: Supabase (DB+Auth). Resend/Mailgun **no** en
  producción.
- **Dependencias externas pendientes** `[DOCUMENTADO]`: proveedor LLM (ADR-013 ⏳),
  estrategia de embeddings (ADR-014 ⏳), procesamiento en segundo plano (ADR-016 ⏳),
  Object Storage para evidencia (deuda ADR-050), hosting backend (ADR-011 ⏳).
- **Bloqueos actuales**: ver §"Bloqueos críticos" al final y §8.

---

## 6. Roadmap

### Etapas completadas `[DOCUMENTADO/VERIFICADO]`
Day 2 (tenancy+auth+UI) · Day 3: Checkpoints A–D (FastAPI/identity/RLS, roles, frontera
fiscal) · E (dominio de factura CR: modelo lógico, schema, migración, fixtures reales,
parser de producción, persistencia C1, orquestación C2, subida web C3) · C4-A (arquitectura
de intake) · C4-B0 (elección de proveedor: Resend) · **C4-B1** (registro de inbox) ·
**C4-B2** (adaptador Resend/Svix + routing). Codex PASS en B1 y B2 `[DOCUMENTADO]`.

### Etapa actual `[VERIFICADO]`
**C4-B3 — captura durable / idempotencia / RAW / ACK**: estado **DESIGN / NOT IMPLEMENTED**.
El diseño físico (C4-B3-A2) fue entregado y revisado en conversación (abstracción
EvidenceBlob; tablas `evidence_blobs`, `provider_events`, `email_messages`; idempotencia
evento+mensaje; `observed_blob_id` para conflictos; `MAX_RAW_EMAIL_BYTES=64 MiB` como
política; oversize terminal; RLS/grants INSERT+SELECT; FKs compuestas tenant-safe), **pendiente
de aprobación del orquestador**. ADR-050 permanece **DRAFT**.

### Próximas 10 tareas recomendadas (prioridad) `[recomendación]`
1. **Aprobar C4-B3-A2** y decidir el estado de **ADR-050** (DRAFT→ACCEPTED al aprobar). *(ChatGPT)*
2. **C4-B3-A3** — cierre de diseño: descarga limitada/streaming con tope, bounded concurrency,
   endpoint HTTP de webhook y cableado del ACK.
3. **Migración C4-B3** — crear `inbound.evidence_blobs`, `inbound.provider_events`,
   `inbound.email_messages` con RLS ENABLE+FORCE, grants INSERT+SELECT a `inbound_backend`,
   FKs compuestas, CHECKs (BYTEA(32), `extensions.digest`, invariante de storage).
4. **Captura durable + endpoint** — montar router inbound en `main.py`, captura pre-ACK
   atómica, idempotencia (UNIQUE evento y mensaje), preservación de conflicto, oversize terminal.
5. **Tests C4-B3 + auditoría Codex + remediación** → cierre formal.
6. **C4-B4** — wiring de la evidencia inbound al C2 fiscal (`capture_source_document` /
   `process_source_document`) para el XML de Hacienda.
7. **C5** — perfil fiscal de empresa (identidad fiscal canónica + SOLO relación/dirección
   determinista del documento).
8. **D1-A + D2-A** — dominio mínimo de documento externo + inteligencia documental MVP
   (PDF/imagen/cuerpo, extracción con procedencia y confianza, conciliación).
9. **D3-A** — clasificación económica observada (gasto/ingreso/otro/sin resolver, con revisión).
10. **C6** — Tax Engine de IVA (primer cálculo determinista, versionado, con `as_of_date`).

### Dependencias entre tareas
1→2→3→4→5 secuenciales (cada una cierra antes de la siguiente). 6 depende de 5. 7 (C5) es
prerequisito honesto de 8–10 (sin perfil fiscal no hay dirección del documento). 8→9. 10
(Tax Engine) requiere ADR-011 (hosting), datos fiscales de C2/C4, y probablemente ADR-016.

### Criterios de aceptación de la siguiente etapa (C4-B3) `[recomendación]`
- Migraciones 20→23 aplicadas, **sin drift** (`migration list` local = remoto).
- 3 tablas inbound con **FKs compuestas tenant-safe**, RLS ENABLE+FORCE, `inbound_backend`
  solo **INSERT+SELECT** (sin UPDATE/DELETE).
- Idempotencia de **evento** (`UNIQUE provider, provider_event_id, inbox_id`) y **mensaje**
  (`UNIQUE provider, provider_email_id, inbox_id`) demostradas con tests.
- **Captura durable pre-ACK atómica**; evidencia conflictiva preservada vía `observed_blob_id`
  (nunca overwrite); oversize = terminal; `MAX_RAW_EMAIL_BYTES=64 MiB` en la capa de captura,
  **no** como CHECK de esquema.
- Endpoint de webhook montado; semántica de ACK (2xx/non-2xx) implementada.
- Suite verde (salvo flake ambiental documentado) + **Codex PASS**.

---

## 7. Coordinación con Codex

### Auditorías anteriores `[DOCUMENTADO]`
- **Day 2**: sign-off final "Day 2 can be committed and pushed" (0 CRITICAL/HIGH).
- **D1 (frontera fiscal)**: FAIL/OPEN inicial (3 MEDIUM + 2 LOW) → reauditoría PASS.
- **E0**: revisión arquitectónica PASS; H-1/H-2/H-5/H-8 cerrados.
- **C3-B3**: auditoría final independiente 0/0/0/0/0.
- **C4-B1**: Codex final **PASS** (ADR-048).
- **C4-B2**: hallazgo **HIGH** (autoridad de routing `received_for` → corregido a `data.to`
  exclusivo; `received_for` pasa a trace-only) + MEDIUM/LOW de fixtures y factualidad de docs
  → remediados → Codex final **PASS** (ADR-049).

### Observaciones pendientes de resolver `[VERIFICADO]`
Ninguna abierta sobre lo ya cerrado. El diseño C4-B3-A2 aún **no** ha sido auditado por Codex.

### Cambios implementados a partir de auditorías `[DOCUMENTADO]`
Routing por `data.to` exclusivo; fixtures `limpio` con limpieza en setup+teardown y reintento
de transitorios; desambiguación `data.to` (autoridad) vs cabecera MIME `To:` (no confiable);
conteos de test factuales en la documentación.

### Elementos que necesitan nueva auditoría `[recomendación]`
- **C4-B3** una vez implementado (migración + captura durable + endpoint + idempotencia +
  preservación de conflicto + RLS/grants). Es la próxima auditoría natural.

---

## 8. Decisiones pendientes de ChatGPT (orquestador)

1. **Aprobar o iterar C4-B3-A2** (diseño físico) y, al aprobar, **mover ADR-050 a ACCEPTED**
   (hoy DRAFT). Bloquea toda la implementación de C4-B3.
2. **ADR-011 — hosting del backend FastAPI** (⏳). Bloquea el despliegue de un webhook
   productivo y, más adelante, el runtime del Tax Engine/IA.
3. **ADR-016 — procesamiento en segundo plano** (⏳). Define el "procesamiento asíncrono
   durable después del ACK" (ADR-047).
4. **ADR-013 (proveedor LLM) y ADR-014 (embeddings)** (⏳). Bloquean KB/RAG y AI Agent.
5. **Teardown del spike de Render** y confirmación de rotación definitiva de secretos inbound.
6. **¿Introducir CI?** (hoy no existe) — afecta a la fiabilidad de las auditorías.
7. **Dónde documentar el diseño C4-B3-A2 aprobado**: ¿expandir el cuerpo de ADR-050, o un
   `docs/design/C4-B3.md`?
8. **¿Commitear las 3 ediciones de docs de ADR-050** actualmente sin commitear?

---

## 9. Próximo paso exacto

`[recomendación]` **Tras la aprobación del orquestador** (decisión §8.1), el siguiente paso de
Claude Code es **abrir C4-B3-A3** (cierre de diseño de streaming/bounded-concurrency/endpoint/
ACK) y a continuación la implementación de C4-B3.

- **Archivos involucrados**:
  - `supabase/migrations/` — nueva migración con las 3 tablas `inbound.*` (RLS, grants, FKs
    compuestas, CHECKs con BYTEA(32) y `extensions.digest`).
  - `backend/app/inbound/` — nuevo módulo de captura durable; `backend/app/main.py` — montar
    el router de webhook inbound.
  - `backend/tests/` — tests de captura/idempotencia/conflicto/oversize/RLS.
  - `docs/DECISIONS.md` (ADR-050), `docs/PROJECT_STATE.md`, `ROADMAP.md` — cierre documental.
- **Criterios de aceptación**: los de §6 ("Criterios de aceptación de la siguiente etapa").
- **Restricciones heredadas**: evidencia vía abstracción **EvidenceBlob**; backend durable
  inicial **postgres_bytea** (BYTEA no es el almacenamiento permanente a escala — deuda
  ADR-050); nunca compartir blob cross-tenant; `inbound` backend-only; sin exponer `inbound`
  por el Data API.

> **Si el orquestador aún no aprueba A2**, el paso inmediato es puramente de decisión (§8),
> no de implementación: Claude Code no debe crear migración ni endpoint sin ese GO.
