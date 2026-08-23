# ARCHITECTURE — Asistente Tributario IA (Costa Rica)

> **Estado:** Día 1 — arquitectura prevista. **Nada de lo aquí descrito está
> implementado.** Este documento describe el diseño objetivo y las fronteras que
> deben respetarse cuando se implemente.
>
> Las decisiones aceptadas y las pendientes están registradas en
> [docs/DECISIONS.md](docs/DECISIONS.md). Las reglas de desarrollo, en
> [AI_INSTRUCTIONS.md](AI_INSTRUCTIONS.md).

---

## 1. Principio rector

```
LLM  ≠  Tax Engine
```

El sistema se organiza alrededor de una separación estricta entre lo **probabilístico**
y lo **determinista**.

| | Determinista | Probabilístico |
|---|---|---|
| Componentes | Tax Data Layer, Tax Engine, Knowledge Base | AI Agent |
| Produce | Datos, cifras, citas normativas | Interpretación, orquestación, redacción |
| Autoridad | **Sí** — es la verdad del sistema | **No** — nunca sobre una cifra o una norma |
| Reproducible | Sí, siempre | No necesariamente |
| Testeable | Sí, obligatorio | Solo parcialmente |

**Consecuencia operativa:** si una cifra fiscal aparece en pantalla, existe una
función determinista y testeada que la produjo. Si aparece una norma, existe un
registro en la Knowledge Base con fuente y vigencia. El LLM nunca es el origen de
ninguna de las dos.

---

## 2. Los cuatro componentes

La arquitectura distingue cuatro componentes con responsabilidades que no se solapan.
Confundirlos es el principal riesgo de diseño del proyecto.

### 2.1. Tax Data Layer — *la verdad observada*

Los hechos fiscales del contribuyente: comprobantes, líneas, contrapartes, perfil
fiscal de la empresa.

**Responsabilidades**
- Conservar los datos fiscales normalizados
- Garantizar el aislamiento entre empresas
- Mantener la trazabilidad de cada dato hasta su documento de origen
- Conservar el documento original íntegro e inmutable

**Fronteras**
- No calcula impuestos
- No interpreta normativa
- No contiene lógica de negocio tributaria

**Distinción central:** dentro de esta capa, los valores `reported_*` (los que
declara el documento fuente) nunca se mezclan con los valores `computed_*` (los que
produce nuestro Tax Engine). Ver §7.

### 2.2. Tax Engine — *el cálculo*

Motor de cálculo tributario determinista.

**Responsabilidades**
- Ejecutar cálculos tributarios de forma reproducible
- Aplicar reglas versionadas, resueltas según fecha de aplicabilidad
- Devolver el resultado **junto con su desglose y la versión de regla aplicada**

**Fronteras — estas son las que hacen al motor auditable**
- ❌ Sin dependencia del LLM
- ❌ Sin FastAPI
- ❌ Sin acceso directo a base de datos
- ❌ Sin I/O innecesario (ni red, ni sistema de archivos)
- ❌ Sin estado global mutable

**Forma prevista:** paquete Python independiente en `tax-engine/`, con funciones
puras. Entran datos + `as_of_date` + versión de reglas; sale un resultado.

Esa forma no es estética: es la garantía **mecánica** de que el motor es testeable en
aislamiento y de que ningún LLM puede influir en su salida. Un motor que pudiera
consultar la base de datos o llamar a un modelo dejaría de ser verificable.

### 2.3. Knowledge Base — *la norma*

Normativa tributaria estructurada y verificable.

**Responsabilidades**
- Almacenar normativa con metadatos obligatorios: **fuente · documento o artículo ·
  fecha · vigencia · versión**
- Permitir búsqueda semántica (pgvector) y recuperación exacta
- Servir citas verificables al AI Agent y al usuario

**Fronteras**
- No calcula
- No contiene datos de contribuyentes
- **No admite contenido sin fuente verificada**

**Naturaleza de acceso opuesta al Tax Data Layer:** la normativa es conocimiento
**compartido** del sistema; los datos fiscales son **privados por tenant**. Aplicar
el mismo patrón de aislamiento a ambos sería un error de diseño. Ver §6.3.

### 2.4. AI Agent — *la interacción*

Capa conversacional. **Sin autoridad sobre cifras ni sobre normas.**

**Responsabilidades**
- Interpretar la pregunta del usuario
- Seleccionar y encadenar tools
- Solicitar datos, normativa y cálculos a los componentes que sí tienen autoridad
- Redactar la respuesta, citando siempre lo que la respalda

**Fronteras**
- ❌ Nunca calcula un impuesto por razonamiento propio
- ❌ Nunca cita normativa de memoria
- ❌ Nunca accede indiscriminadamente a la base de datos
- ❌ Nunca ejecuta SQL libre
- ❌ Nunca opera fuera del tenant y la identidad del usuario que pregunta

---

## 3. Vista general del sistema

```
┌───────────────────────────────────────────────────────────────────────┐
│  FRONTEND — Next.js · React · TypeScript                     (Vercel) │
│  UI · sesión · presentación                                           │
└───────────────┬───────────────────────────────────────┬───────────────┘
                │                                       │
                │ HTTPS + JWT                           │ solo Auth
                │ (todo dato fiscal)                    │ (y Storage con
                │                                       │  políticas explícitas)
┌───────────────▼───────────────────────────────────┐   │
│  BACKEND — Python · FastAPI                       │   │
│  ┌─────────────────────────────────────────────┐  │   │
│  │ API layer      validación · autorización    │  │   │
│  ├─────────────────────────────────────────────┤  │   │
│  │ Service layer  orquestación                 │  │   │
│  ├─────────────────────────────────────────────┤  │   │
│  │ Repository     acceso a datos · tenant      │  │   │
│  ├─────────────────────────────────────────────┤  │   │
│  │ Ingestion      parser · validation · normalizer │   │
│  ├─────────────────────────────────────────────┤  │   │
│  │ AI layer       agente · tools · proveedor   │  │   │
│  └─────────────────────────────────────────────┘  │   │
└──────┬──────────────────┬──────────────────┬──────┘   │
       │                  │                  │          │
       │  invoca          │                  │          │
┌──────▼────────────┐     │           ┌──────▼──────────▼──────────────┐
│  TAX ENGINE       │     │           │  SUPABASE                      │
│  paquete puro     │     │           │  ┌──────────────────────────┐  │
│  ┌──────────────┐ │     │           │  │ PostgreSQL               │  │
│  │ rules        │ │     └───────────┼─▶│  · Tax Data Layer  (RLS) │  │
│  │ versionadas  │ │                 │  │  · Knowledge Base        │  │
│  ├──────────────┤ │                 │  │  · pgvector              │  │
│  │ calculators  │ │                 │  │  · audit log             │  │
│  ├──────────────┤ │                 │  └──────────────────────────┘  │
│  │ explain      │ │                 │  ┌──────────────────────────┐  │
│  └──────────────┘ │                 │  │ Auth   · JWT · usuarios  │  │
│  sin DB · sin red │                 │  ├──────────────────────────┤  │
│  sin LLM · puro   │                 │  │ Storage · XML originales │  │
└───────────────────┘                 │  └──────────────────────────┘  │
                                      └────────────────────────────────┘
```

**Puntos de lectura del diagrama:**

1. **FastAPI es la única puerta a los datos fiscales.** El frontend usa Supabase
   directamente solo para autenticación (y Storage bajo políticas explícitas). No
   existen dos caminos independientes de modificación de datos fiscales.
2. **El Tax Engine no toca la base de datos.** El backend le entrega los datos ya
   leídos y recibe un resultado.
3. **El AI Agent vive dentro del backend**, sujeto a las mismas reglas de
   autorización que cualquier otra ruta.

---

## 4. Frontend

**Stack previsto:** Next.js · React · TypeScript. Hosting: Vercel.

**Responsabilidades:** interfaz, gestión de sesión, presentación de datos fiscales,
visualización de cálculos y sus desgloses.

**Fronteras**
- No contiene lógica tributaria — ni una tasa, ni una regla, ni un cálculo
- No decide autorización; la refleja
- No accede a datos fiscales por vías alternativas a la API

**Requisito de presentación:** cuando se muestre un valor `reported_*`, debe quedar
visualmente claro que proviene del documento fuente y no de un cálculo propio.
Es especialmente relevante en Fase 3, cuando existirá dashboard pero no Tax Engine.

---

## 5. Backend

**Stack previsto:** Python · FastAPI. Hosting: **decisión pendiente** (ADR-011).

### 5.1. Capas

| Capa | Responsabilidad | Frontera |
|---|---|---|
| **API** | Endpoints, validación de entrada, autenticación, autorización | No contiene lógica tributaria |
| **Service** | Orquestación de casos de uso | No accede a la base de datos directamente |
| **Repository** | Acceso a datos, imposición del contexto de tenant | No contiene reglas de negocio |
| **Ingestion** | `parser → validation → normalizer` | No calcula impuestos |
| **AI** | Agente, tools, abstracción de proveedor | No calcula impuestos ni consulta datos fuera de las tools |

### 5.2. Pipeline de ingesta

```
Raw XML
   │   se conserva íntegro e inmutable en Storage + hash de integridad
   ▼
Source DTO         representación fiel del documento externo
   │               (aquí, y solo aquí, vive el conocimiento del formato externo)
   ▼
Validation         estructura, coherencia, completitud
   │
   ▼
Normalizer         capa anticorrupción: traduce al modelo propio
   │
   ▼
InternalInvoice    modelo interno, desacoplado de formatos y proveedores
   │
   ▼
PostgreSQL         con referencia trazable al documento original
```

**Por qué existe la capa anticorrupción.** Si `InternalInvoice` copiase la estructura
del formato externo, cada cambio de versión de ese formato rompería nuestro esquema,
nuestras consultas y nuestro Tax Engine. Aislar el conocimiento del formato en la
capa `Source DTO` reduce el impacto de esos cambios a un solo punto.

El modelo interno debe contemplar desde el inicio el tipo de documento y la versión
del formato de origen, para poder distinguir documentos de distinta naturaleza y
procedencia sin reinterpretar el XML. (Los tipos y versiones concretos del formato
costarricense **no se enumeran aquí**: requieren fuente oficial verificada.)

### 5.3. Requisitos transversales

- **Trazabilidad:** todo dato fiscal conserva referencia a su documento de origen
- **Auditoría:** las operaciones sobre datos fiscales se registran
- **Idempotencia:** reingerir el mismo documento no debe duplicar datos
- **Precisión decimal:** ningún importe monetario se maneja en coma flotante (§8)

---

## 6. Datos, seguridad y multi-tenancy

### 6.1. Modelo de aislamiento

El aislamiento multiempresa es un **requisito crítico**, no una característica.

La unidad de aislamiento es la **empresa (tenant)**. Un usuario puede tener acceso a
una o varias empresas; todo acceso a datos fiscales ocurre siempre en el contexto de
una empresa concreta.

**Row Level Security es el mecanismo de aislamiento**, aplicado en la base de datos.
El aislamiento no puede depender exclusivamente de que el código de aplicación
recuerde filtrar por empresa.

### 6.2. RLS y claves privilegiadas

Decisión aceptada (ADR-002), reproducida aquí por su criticidad:

- Las operaciones normales realizadas en contexto de un usuario **deben preservar la
  identidad del usuario y el aislamiento del tenant**.
- `service_role` y cualquier clave privilegiada **no deben convertirse en el
  mecanismo habitual** de acceso a datos fiscales de usuarios.
- Las operaciones administrativas y los jobs internos que requieran privilegios
  elevados se implementarán como **caminos separados**: estrictamente controlados,
  exclusivamente server-side y auditables.

**El riesgo que esto evita:** una clave privilegiada anula RLS por completo. Si fuese
la vía habitual, el aislamiento pasaría a depender de que ningún desarrollador olvide
nunca una condición de filtrado. Eso no es aislamiento: es disciplina.

### 6.3. Dos categorías de datos, dos políticas

| | Datos del contribuyente | Knowledge Base |
|---|---|---|
| Naturaleza | Privados de cada empresa | Conocimiento compartido |
| Aislamiento | Estricto por tenant (RLS) | No aislado por tenant |
| Acceso | Solo usuarios de esa empresa | Lectura general del sistema |
| Escritura | Vía aplicación, auditada | Proceso controlado con verificación de fuente |

Aplicar el patrón de aislamiento uniformemente a ambas produciría normativa duplicada
por empresa y divergencias entre tenants. Son políticas deliberadamente distintas.

### 6.4. Autenticación y autorización

- **Autenticación:** Supabase Auth. El frontend obtiene una sesión; el backend valida
  el token en cada petición.
- **Autorización:** decidida en el backend, respaldada por RLS en la base de datos.
  Dos capas de defensa, no una.
- **Camino único para datos fiscales:** vía FastAPI (ADR-001).

### 6.5. Storage y documentos originales

- El XML original se conserva **íntegro e inmutable**
- Se almacenará también un **hash de integridad** que permita verificarlo
- El modelo normalizado **siempre** conserva trazabilidad hacia el documento original
- El acceso a documentos está sujeto al mismo aislamiento por tenant

Sin esto, la trazabilidad sería una aspiración documental en lugar de una propiedad
verificable del sistema.

### 6.6. Gestión de secretos

- Nunca en el repositorio. Sin excepciones.
- Variables de entorno, provistas por la plataforma de despliegue.
- Ninguna credencial privilegiada se expone jamás al frontend.
- Ver [AI_INSTRUCTIONS.md](AI_INSTRUCTIONS.md), Regla 6.

### 6.7. Auditoría y trazabilidad

Dos conceptos distintos que conviene no confundir:

- **Trazabilidad del dato** — de dónde viene cada valor fiscal (documento origen,
  posición dentro de él, momento de ingesta).
- **Auditoría de operaciones** — quién hizo qué, cuándo y sobre qué empresa.

Ambos son requisitos desde el diseño, no añadidos posteriores.

---

## 7. `reported_*` vs `computed_*`

Distinción aceptada como principio de diseño (ADR-003) y de aplicación transversal:
base de datos, API, frontend y Tax Engine.

| Prefijo | Origen | Autoridad |
|---|---|---|
| `reported_*` | Valores provenientes del comprobante o documento fuente | Lo que **declaró** el emisor |
| `computed_*` | Valores producidos por nuestro Tax Engine | Lo que **calcula** nuestro motor |

**Nunca deben confundirse ni fusionarse en un mismo campo.**

**Por qué importa desde el primer día.** El Dashboard (Fase 3) llega antes que el Tax
Engine (Fase 4), y mostrará importes de impuestos. Esos importes vendrán del XML: son
valores **declarados por el emisor**, no cálculos nuestros. Si no se distinguen desde
el modelo de datos, el día en que el Tax Engine discrepe del documento nadie sabrá
qué cifra está mirando.

Y esa discrepancia **es precisamente parte del valor del producto**: detectar que un
comprobante recibido declara un impuesto distinto del que corresponde es exactamente
lo que un contribuyente necesita saber. Un modelo que las mezcle destruye esa señal.

---

## 8. Tax Engine

### 8.1. Naturaleza

Paquete Python independiente (`tax-engine/`), determinista y sin efectos secundarios.

```
entrada:  datos fiscales  +  as_of_date  +  contexto
                             │
                             ▼
                    resolución de regla vigente
                             │
                             ▼
                     cálculo determinista
                             │
                             ▼
salida:  resultado  +  desglose  +  versión de regla aplicada
```

### 8.2. Temporalidad — `as_of_date`

Todo cálculo tributario contempla desde su diseño:

- **`as_of_date`** — la fecha que determina qué regla resulta aplicable
- **versión de la regla aplicada** — persistida junto al resultado

El motor **nunca** calcula "con las reglas actuales". Calcula con las reglas vigentes
en la fecha correspondiente al hecho.

**Por qué es innegociable:** sin `as_of_date`, recalcular un período anterior tras un
cambio normativo produciría un resultado distinto del original, y el sistema dejaría
de ser auditable. Introducirlo desde el diseño es gratuito; añadirlo después obliga a
revisar todas las firmas, todos los datos persistidos y todos los tests.

### 8.3. Reglas tributarias

Toda regla debe poder indicar: **fuente · documento o artículo · fecha · vigencia ·
versión**.

Una regla sin fuente verificada no entra al motor. Ver [AI_INSTRUCTIONS.md](AI_INSTRUCTIONS.md),
Reglas 2 y 5.

> **Nota de estado (Día 1):** este repositorio no contiene todavía ninguna tasa,
> artículo ni referencia normativa concreta. Su incorporación requiere fuente oficial
> verificada y se realizará en la fase correspondiente del roadmap.

### 8.4. Precisión monetaria

- Representación **decimal exacta**. Nunca coma flotante donde pueda producir errores
  de precisión.
- Se conserva la **moneda original** y la información de conversión disponible cuando
  aplique.
- Las reglas de redondeo son parte de la regla tributaria, no del código de utilidad.

### 8.5. Testabilidad

Todo cálculo tributario crítico tiene tests. No es una recomendación:
es [AI_INSTRUCTIONS.md](AI_INSTRUCTIONS.md), Regla 4.

- Tests unitarios junto al módulo correspondiente
- `tests/` en la raíz para integración y end-to-end
- Casos de regresión histórica: verificar que un cálculo de un período pasado sigue
  produciendo el mismo resultado

---

## 9. Knowledge Base y RAG

```
Documento normativo (fuente oficial verificada)
        ↓  ingesta controlada
Fragmentación con metadatos obligatorios
        ↓  fuente · documento/artículo · fecha · vigencia · versión
Embeddings  →  pgvector
        ↓
Recuperación  →  respuesta con cita obligatoria
```

**Requisitos**

- Ningún contenido sin fuente verificada
- Toda recuperación devuelve la cita junto al contenido
- La vigencia forma parte del dato: normativa derogada debe ser distinguible de
  normativa vigente
- El RAG **no sustituye al Tax Engine**: aporta contexto normativo, no cifras

**Frontera crítica.** El RAG informa; no calcula. Si una pregunta requiere un número,
ese número procede del Tax Engine aunque la explicación provenga de la Knowledge Base.

---

## 10. AI Agent y tool calling

### 10.1. Flujo

```
USUARIO
   ↓
AI AGENT               interpreta · planifica
   ↓
TOOLS CONTROLADAS      conjunto cerrado y explícito
   ↓
┌──────────────┬──────────────────┬──────────────┐
│ DATOS DEL    │  KNOWLEDGE BASE  │  TAX ENGINE  │
│ CONTRIBUYENTE│                  │              │
└──────────────┴──────────────────┴──────────────┘
   ↓
RESULTADO
   ↓
EXPLICACIÓN + CÁLCULO + FUENTES + EVIDENCIA + ADVERTENCIAS
```

### 10.2. Principio de acceso

**El AI Agent nunca tiene acceso indiscriminado a la base de datos.**

Solo alcanza los datos a través de un conjunto cerrado de tools. Cada tool:

- tiene contrato explícito de entrada y salida
- opera dentro del tenant y la identidad del usuario que pregunta
- está sujeta a las mismas reglas de autorización que cualquier otro acceso
- es auditable

No existe una tool de consulta libre a la base de datos. Es una decisión de seguridad
deliberada: una tool de SQL arbitrario convertiría toda la arquitectura de aislamiento
en decorativa.

### 10.3. Tools previstas

**No implementadas hoy.** Se listan para fijar el alcance previsto:

```
get_company_profile()      get_sales()             get_purchases()
get_invoice()              calculate_iva()         get_tax_rule()
search_tax_knowledge()     find_missing_invoices() find_risks()
```

Obsérvese que `calculate_iva()` **no calcula**: invoca al Tax Engine y devuelve su
resultado. La distinción es la esencia del principio rector.

### 10.4. Arquitectura agnóstica de proveedor LLM

No debemos acoplar la arquitectura a un único proveedor.

```
       ┌──────────────────────────────────┐
       │  Código del agente (del proyecto)│
       └────────────────┬─────────────────┘
                        │  interfaz interna
       ┌────────────────▼─────────────────┐
       │  LLM Provider Interface          │
       │  completions · tool calling ·    │
       │  embeddings                      │
       └───┬──────────┬──────────┬────────┘
           │          │          │
      ┌────▼───┐ ┌────▼────┐ ┌───▼────┐
      │ OpenAI │ │Anthropic│ │ Gemini │   adaptadores
      └────────┘ └─────────┘ └────────┘
```

**Requisitos**
- El código del agente no importa SDK de proveedor directamente
- Cambiar de modelo significa sustituir un adaptador, no reescribir el agente
- El proveedor se configura por entorno, nunca embebido en el código
- Ninguna credencial de proveedor llega al frontend

**Alcance realista de la abstracción:** cubre el uso común (completions, tool calling,
embeddings). No pretende abstraer toda capacidad específica de cada proveedor. Si en
algún momento se requiere una capacidad exclusiva, se documenta como decisión y se
asume conscientemente el acoplamiento.

---

## 11. Estructura del repositorio

```
tributario-ai-cr/
├── supabase/      Migraciones SQL · config.toml
├── frontend/      Next.js · React · TypeScript · Tailwind
├── backend/       Python · FastAPI                    (vacío)
├── tax-engine/    Paquete Python independiente        (vacío)
├── tests/         Integración y end-to-end
└── docs/          Decisiones y glosario
```

**Sobre `supabase/`:** es la convención de la CLI. Contiene las migraciones —única vía
admitida para cambios de esquema (ADR-018)— y `config.toml`, que se aplica al proyecto
remoto con `supabase config push`.

**Sobre el nombre del paquete:** la carpeta conceptual puede llamarse `tax-engine/`,
pero cuando se cree el paquete Python importable deberá utilizar un nombre válido como
`tax_engine` — el guion no es admisible en un identificador de importación de Python.

**Sobre los tests:** `tests/` en la raíz se usará principalmente para integración y
end-to-end. Los tests unitarios específicos vivirán junto al módulo correspondiente.
(ADR-005.)

**Sobre `tax-engine/` separado de `backend/`:** la separación física impone la
separación lógica. Un paquete que no importa FastAPI ni cliente de base de datos no
puede, por construcción, violar sus fronteras.

---

## 12. Decisiones de arquitectura

Registro completo en [docs/DECISIONS.md](docs/DECISIONS.md).

**Aceptadas en Día 1:** camino único de acceso a datos fiscales · RLS como mecanismo
de aislamiento y restricción del uso de claves privilegiadas · separación
`reported`/`computed` · `as_of_date` y versión de regla · Tax Engine aislado ·
pipeline de comprobantes con capa anticorrupción · documento original inmutable con
hash · precisión decimal · políticas diferenciadas para Knowledge Base ·
`AI_INSTRUCTIONS.md` como fuente de verdad.

**Pendientes:** hosting concreto del backend · mecanismo técnico de propagación de
identidad hacia RLS · estrategia de background jobs · proveedor LLM inicial ·
estrategia de embeddings · modelo de permisos usuario–empresa.

---

## 13. Qué NO existe todavía

Ni aplicaciones, ni dependencias, ni esquema SQL, ni migraciones, ni parser, ni
autenticación, ni Tax Engine, ni Knowledge Base, ni tools, ni AI Agent, ni conexión
a Supabase, ni conexión a proveedores de IA, ni CI.

**Nada de este documento describe código existente.** Describe el diseño que el
código deberá respetar cuando se escriba.
