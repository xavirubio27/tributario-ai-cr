# Asistente Tributario IA — Costa Rica

> **Project Status: Day 1 — Project Foundation**
> Repositorio en fase de fundación. No existe todavía código de producto: ni aplicaciones,
> ni esquema de base de datos, ni parser, ni Tax Engine, ni agente de IA.

Capa de inteligencia tributaria construida sobre los datos fiscales reales de un
contribuyente costarricense.

---

## Qué es este proyecto

Un SaaS que permite a una empresa **conversar con sus propios datos fiscales**.

Los sistemas contables y de facturación electrónica actuales *registran* hechos
tributarios. Este producto *razona sobre ellos*: cruza los datos reales del
contribuyente con un motor de cálculo determinista y con normativa verificable,
para responder preguntas concretas con respaldo auditable.

Preguntas del tipo:

- ¿Cuánto IVA voy a pagar este mes?
- ¿Cuánto vendí?
- ¿Cuánto llevo acumulado de renta?
- ¿Qué facturas requieren revisión?
- ¿Cómo se calculó este impuesto?
- ¿Qué norma respalda este resultado?

Cada respuesta combina cuatro elementos:

```
DATOS REALES DEL CONTRIBUYENTE
        +
TAX ENGINE DETERMINISTA
        +
NORMATIVA TRIBUTARIA VERIFICABLE
        +
IA COMO CAPA DE INTERACCIÓN
```

## Qué problema resuelve

El contribuyente tiene sus datos fiscales dispersos entre el sistema de facturación,
la contabilidad y los comprobantes electrónicos. Sabe *qué* debe pagar solo cuando
alguien lo calcula por él, normalmente tarde, y rara vez sabe *por qué* esa es la
cifra ni *qué norma* la respalda.

El objetivo es cerrar tres brechas:

| Brecha | Situación actual | Lo que aportamos |
|---|---|---|
| **Visibilidad** | El dato fiscal se conoce al cierre | Estado fiscal continuo sobre datos propios |
| **Explicabilidad** | La cifra llega sin desglose | Cálculo trazable paso a paso |
| **Respaldo** | La norma se busca aparte | Cada resultado cita su fuente y su vigencia |

## Qué NO estamos construyendo

Esta lista es tan importante como la anterior. Define el producto por exclusión:

- ❌ Un software contable tradicional
- ❌ Un sistema de facturación electrónica
- ❌ Un POS
- ❌ Un ERP
- ❌ Un chatbot que responde preguntas tributarias genéricas
- ❌ Una interfaz de ChatGPT con legislación dentro del prompt

No competimos con el sistema de facturación del cliente: **nos apoyamos en él**.

---

## Principio arquitectónico fundamental

```
LLM  ≠  Tax Engine
```

Son componentes completamente separados, y esa separación es la propiedad que
hace el producto defendible ante un contribuyente, un contador o la Administración.

**El LLM** interpreta preguntas, selecciona herramientas, consulta datos, consulta
normativa, solicita cálculos y explica resultados.

**El Tax Engine** ejecuta cálculos deterministas con reglas versionadas, es
testeable, y **nunca depende del razonamiento libre del LLM para producir un impuesto**.

> El LLM nunca produce un número fiscal. La cifra siempre proviene del Tax Engine;
> la norma siempre proviene de la Knowledge Base.

Toda regla tributaria debe poder indicar: **fuente · documento o artículo · fecha ·
vigencia · versión**.

---

## Arquitectura general

Cuatro componentes con fronteras estrictas:

| Componente | Función | Naturaleza |
|---|---|---|
| **Tax Data Layer** | Datos fiscales reales, normalizados y trazables | Verdad observada |
| **Tax Engine** | Cálculo tributario | Determinista, versionado, testeado |
| **Knowledge Base** | Normativa con fuente y vigencia | Verificable, citable |
| **AI Agent** | Interpretación e interacción | Probabilístico, sin autoridad de cálculo |

```
                  ┌─────────────────────────────┐
                  │   Next.js / React / TS      │  → Vercel
                  └──────────────┬──────────────┘
                                 │  HTTPS + JWT
                  ┌──────────────▼──────────────┐
                  │      FastAPI (Python)       │  ← única puerta a datos fiscales
                  │  auth · autorización · API  │
                  └───┬──────────┬───────────┬──┘
                      │          │           │
        ┌─────────────▼──┐  ┌────▼──────┐  ┌─▼──────────────┐
        │ Tax Data Layer │  │Tax Engine │  │ Knowledge Base │
        │  (PostgreSQL)  │  │  (puro)   │  │   (pgvector)   │
        │  RLS · tenant  │  │determinista│ │fuente·vigencia │
        └────────────────┘  └───────────┘  └────────────────┘
                      │
        ┌─────────────▼───────────────────────┐
        │ Supabase: Auth · Storage · Postgres │
        └─────────────────────────────────────┘

        [ FASE POSTERIOR ]
        AI Agent → capa abstracta de proveedor (OpenAI | Anthropic | Gemini)
                 → tool calling sobre un conjunto cerrado de tools
                 → nunca SQL libre, nunca acceso indiscriminado a la base de datos
```

**Stack previsto:** Next.js · React · TypeScript · Python · FastAPI · Supabase
(PostgreSQL, Auth, Storage, pgvector, Row Level Security) · Vercel · GitHub.

La capa de IA se implementará mediante una abstracción de proveedor, de modo que
cambiar de modelo signifique sustituir un adaptador y no reescribir el agente.

Detalle completo en [ARCHITECTURE.md](ARCHITECTURE.md).

---

## Estado actual

**Día 1 — Fundación del proyecto.**

Lo que existe hoy es exclusivamente documentación y estructura de directorios.

| Elemento | Estado |
|---|---|
| Documentación de producto y arquitectura | ✅ Creada |
| Reglas para agentes de programación | ✅ Creadas |
| Estructura de directorios | ✅ Creada (vacía) |
| Frontend | ⬜ No iniciado |
| Backend | ⬜ No iniciado |
| Tax Engine | ⬜ No iniciado |
| Esquema de base de datos | ⬜ No iniciado |
| Parser XML | ⬜ No iniciado |
| Autenticación | ⬜ No iniciada |
| Knowledge Base / RAG | ⬜ No iniciada |
| AI Agent | ⬜ No iniciado |

**No hay dependencias instaladas. No hay servicios conectados. No hay secretos.**

### Primer objetivo técnico

El siguiente hito, íntegro:

```
XML real de comprobante electrónico CR
   ↓  parser
   ↓  validación
   ↓  normalización
   ↓  InternalInvoice (modelo propio)
   ↓  PostgreSQL (aislado por empresa)
   ↓  visualización en la interfaz
```

Explícitamente **fuera de alcance por ahora**: integración con Hacienda, bancos,
Alegra o Facturele; impuesto sobre la renta; AI Agent; tools; RAG.

---

## Organización del repositorio

```
tributario-ai-cr/
├── README.md              Este documento
├── PRODUCT_SPEC.md        Especificación de producto
├── ARCHITECTURE.md        Arquitectura técnica
├── AI_INSTRUCTIONS.md     Reglas permanentes para agentes de programación
├── CLAUDE.md              Contexto operativo conciso para Claude Code
├── ROADMAP.md             Fases 0 a 10
├── .gitignore
├── docs/
│   ├── DECISIONS.md       Registro de decisiones de arquitectura
│   └── GLOSSARY.md        Vocabulario compartido del proyecto
├── frontend/              Next.js · React · TypeScript   (vacío)
├── backend/               Python · FastAPI                (vacío)
├── tax-engine/            Paquete Python independiente    (vacío)
└── tests/                 Integración y end-to-end        (vacío)
```

Los directorios contienen `.gitkeep` porque Git no versiona directorios vacíos.

**Convención de idioma:** la documentación explicativa se escribe en español; el
código, los identificadores, los nombres técnicos y los mensajes de commit se
escriben en inglés.

---

## Documentación

| Documento | Contenido |
|---|---|
| [PRODUCT_SPEC.md](PRODUCT_SPEC.md) | Visión, usuario objetivo, problema, propuesta de valor, MVP, diferenciación |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Componentes, seguridad, multi-tenancy, trazabilidad, agnosticismo de proveedor LLM |
| [AI_INSTRUCTIONS.md](AI_INSTRUCTIONS.md) | **Fuente de verdad** de las reglas permanentes de desarrollo |
| [CLAUDE.md](CLAUDE.md) | Resumen operativo para Claude Code |
| [ROADMAP.md](ROADMAP.md) | Secuencia de fases, sin fechas rígidas |
| [docs/DECISIONS.md](docs/DECISIONS.md) | Decisiones aceptadas y decisiones pendientes |
| [docs/GLOSSARY.md](docs/GLOSSARY.md) | Vocabulario compartido |

---

## Seguridad

El sistema procesa información tributaria sensible. Desde el diseño se contemplan:
aislamiento multiempresa, Row Level Security, control de acceso, auditoría, logs,
gestión segura de secretos, backups, protección de documentos y trazabilidad del dato.

**Nunca se colocan en el repositorio** API keys, tokens, contraseñas, credenciales
ni secretos de ningún tipo. Se gestionan mediante variables de entorno.

---

## Nota sobre normativa

Este repositorio **no contiene todavía tasas impositivas, artículos de ley,
resoluciones ni endpoints oficiales**. Ninguna cifra ni referencia normativa se
incorporará sin proceder de una fuente oficial verificada, y siempre acompañada de
fuente, fecha y vigencia.

Es una regla permanente del proyecto: *un documento con huecos honestos es preferible
a uno con cifras plausibles e inventadas.* Ver [AI_INSTRUCTIONS.md](AI_INSTRUCTIONS.md).
