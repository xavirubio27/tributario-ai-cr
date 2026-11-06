# DECISIONS — Registro de decisiones de arquitectura

> Registro ligero tipo ADR (*Architecture Decision Record*).
>
> **Por qué existe:** sin un registro explícito, las decisiones importantes se toman
> implícitamente dentro de un commit cualquiera y nadie recuerda después por qué el
> sistema es como es. Cada decisión relevante se anota aquí **antes** o **en el
> momento** de implementarse.
>
> **Cómo usarlo**
> - Toda decisión que afecte a seguridad, modelo de datos, fronteras entre componentes,
>   trazabilidad o reproducibilidad se registra aquí.
> - Las decisiones **no se borran**: se marcan como sustituidas y se enlaza la nueva.
> - Las decisiones pendientes se registran igual, con lo que se sabe y lo que falta.
>
> Ver [AI_INSTRUCTIONS.md](../AI_INSTRUCTIONS.md), Regla 14.

**Estados:** ✅ Aceptada · ◐ Parcialmente resuelta · ⏳ Pendiente · ♻️ Sustituida · ❌ Rechazada

---

## Índice

| ADR | Título | Estado |
|---|---|---|
| [ADR-001](#adr-001) | Camino único de acceso a datos fiscales | ✅ |
| [ADR-002](#adr-002) | RLS como mecanismo de aislamiento; restricción de claves privilegiadas | ✅ |
| [ADR-003](#adr-003) | Separación `reported_*` / `computed_*` | ✅ |
| [ADR-004](#adr-004) | Temporalidad del Tax Engine: `as_of_date` y versión de regla | ✅ |
| [ADR-005](#adr-005) | Tax Engine como paquete aislado; ubicación de los tests | ✅ |
| [ADR-006](#adr-006) | Pipeline de comprobantes con capa anticorrupción | ✅ |
| [ADR-007](#adr-007) | Documento original íntegro, inmutable y verificable por hash | ✅ |
| [ADR-008](#adr-008) | Precisión monetaria decimal exacta | ✅ |
| [ADR-009](#adr-009) | Knowledge Base compartida vs. datos fiscales aislados | ✅ |
| [ADR-010](#adr-010) | `AI_INSTRUCTIONS.md` como fuente de verdad; convención de idioma | ✅ |
| [ADR-011](#adr-011) | Hosting del backend FastAPI | ⏳ |
| [ADR-012](#adr-012) | Mecanismo de propagación de identidad hacia RLS | ✅ |
| [ADR-013](#adr-013) | Proveedor LLM inicial | ⏳ |
| [ADR-014](#adr-014) | Estrategia de embeddings | ⏳ |
| [ADR-015](#adr-015) | Modelo de permisos usuario–empresa | ✅ |
| [ADR-016](#adr-016) | Estrategia de procesamiento en segundo plano | ⏳ |
| [ADR-017](#adr-017) | Frontera entre datos de identidad/tenancy y datos fiscales | ✅ |
| [ADR-018](#adr-018) | Proyecto Supabase alojado de desarrollo; entorno local diferido | ✅ |
| [ADR-019](#adr-019) | Confirmación de email desactivada solo en desarrollo | ✅ |
| [ADR-020](#adr-020) | Frontera de acceso a datos fiscales: schema `fiscal` y rol de ejecución | ✅ |
| [ADR-021](#adr-021) | Autoridad de las fuentes oficiales de comprobantes electrónicos | ✅ |
| [ADR-022](#adr-022) | Preservación del XML original como artefacto inmutable | ✅ |
| [ADR-023](#adr-023) | `reported_*` frente a `computed_*` | ✅ |
| [ADR-024](#adr-024) | `DocumentParty` como instantánea histórica del comprobante | ✅ |
| [ADR-025](#adr-025) | Núcleo MVP: Factura, Nota de Crédito y Nota de Débito | ✅ |
| [ADR-026](#adr-026) | `schema_version` ≠ revisión del *ruleset* | ✅ |
| [ADR-027](#adr-027) | Modelo lógico de entidades fiscales | ✅ |
| [ADR-028](#adr-028) | Referencia reportada frente a relación resuelta | ✅ |
| [ADR-029](#adr-029) | Códigos externos sin clave foránea obligatoria | ✅ |
| [ADR-030](#adr-030) | Tres capas de validación | ✅ |
| [ADR-031](#adr-031) | Duplicados: artefacto frente a documento lógico | ✅ |
| [ADR-032](#adr-032) | Claves foráneas compuestas para seguridad de tenant | ✅ |
| [ADR-033](#adr-033) | Mapeo decimal exacto y forma sin valor en catálogos | ✅ |
| [ADR-034](#adr-034) | Representación física de fecha y hora | ✅ |
| [ADR-035](#adr-035) | Unicidad lógica y visibilidad del conflicto | ✅ |
| [ADR-036](#adr-036) | Inmutabilidad, borrado y ausencia de `DELETE` | ✅ |
| [ADR-037](#adr-037) | Almacenamiento y huella del artefacto de origen | ✅ |
| [ADR-038](#adr-038) | Autorización de escritura fiscal | ✅ |
| [ADR-039](#adr-039) | La fecha de emisión puede no declarar desplazamiento | ✅ |
| [ADR-040](#adr-040) | Los esquemas oficiales se versionan en el repositorio | ✅ |
| [ADR-041](#adr-041) | El parser fiscal es puro y solo emite datos reportados | ✅ |
| [ADR-042](#adr-042) | Deduplicación conservadora por huella en el MVP | ✅ |
| [ADR-043](#adr-043) | Los documentos externos no entran en el dominio fiscal costarricense | ✅ |
| [ADR-044](#adr-044) | Ingesta fiscal en dos fases: la evidencia se preserva antes de interpretarla | ✅ |
| [ADR-045](#adr-045) | Frontera web fiscal: Next.js de servidor → FastAPI → RLS de PostgreSQL | ✅ |
| [ADR-046](#adr-046) | Buzón Tribuu: intake automatizado, evidencia empresarial y autorización de máquina | ✅ |
| [ADR-047](#adr-047) | Resend como proveedor inbound MVP y captura durable antes del ACK | ✅ |
| [ADR-048](#adr-048) | Identidad de máquina inbound y Buzón Tribuu provider-agnostic | ✅ |
| [ADR-049](#adr-049) | Adaptador inbound de Resend, verificación Svix e identidad de evento | ✅ |
| [ADR-050](#adr-050) | Abstracción EvidenceBlob: BYTEA inicial y migración planificada a Object Storage | 📝 |

---
---

# DECISIONES ACEPTADAS

<a id="adr-001"></a>
## ADR-001 — Camino único de acceso a datos fiscales

**Estado:** ✅ Aceptada (Día 1)

### Contexto

El frontend Next.js puede comunicarse con Supabase directamente **y** con FastAPI. Si
ambos caminos permitieran leer o modificar datos fiscales, existirían dos superficies
de seguridad independientes que mantener sincronizadas indefinidamente.

### Decisión

- Los datos fiscales del contribuyente **pasan normalmente por FastAPI**.
- El frontend puede utilizar Supabase directamente para **autenticación** y, cuando
  corresponda, **Storage bajo políticas explícitas**.
- **No** queremos múltiples caminos independientes que permitan modificar datos
  fiscales sin pasar por nuestra capa de aplicación.

### Consecuencias

- Un único punto donde se aplican validación, autorización, auditoría y trazabilidad.
- El frontend no implementa lógica de acceso a datos fiscales.
- Coste asumido: el backend es una dependencia en el camino crítico de toda lectura
  de datos fiscales, incluidas las triviales.

---

<a id="adr-002"></a>
## ADR-002 — RLS como mecanismo de aislamiento; restricción de claves privilegiadas

**Estado:** ✅ Aceptada (Día 1) · **Criticidad: máxima**

### Contexto

Row Level Security aplica sobre la identidad del solicitante. Una clave privilegiada
del tipo `service_role` **anula RLS por completo**. Si el backend accediera siempre con
ella, el aislamiento multiempresa dejaría de estar garantizado por la base de datos y
pasaría a depender de que ningún desarrollador olvide nunca una condición de filtrado
por empresa. Eso no es aislamiento: es disciplina, y la disciplina falla.

### Decisión

- El aislamiento multiempresa mediante **RLS es un requisito crítico**.
- Las operaciones normales realizadas en contexto de un usuario **deben preservar la
  identidad del usuario y el aislamiento del tenant**.
- `service_role` y las claves privilegiadas **no deben convertirse en el mecanismo
  habitual** para acceder a datos fiscales de usuarios.
- Las operaciones administrativas y los jobs internos que requieran privilegios
  elevados se implementarán como **caminos separados**: estrictamente controlados,
  exclusivamente server-side y auditables.

### Consecuencias

- Dos capas de defensa: autorización en el backend **y** RLS en la base de datos.
- Los caminos privilegiados serán una excepción explícita, identificable y auditada,
  no la vía por defecto.
- El mecanismo técnico concreto de propagación de identidad queda abierto en **ADR-012**.

### Notas

No implementado en Día 1. Documentado para que la Fase 1 lo respete desde el diseño del
esquema.

---

<a id="adr-003"></a>
## ADR-003 — Separación `reported_*` / `computed_*`

**Estado:** ✅ Aceptada (Día 1)

### Contexto

El Dashboard (Fase 3) llega antes que el Tax Engine (Fase 4) y mostrará importes de
impuestos. Esos importes provendrán del XML: son valores **declarados por el emisor**,
no cálculos propios. Si ambos conceptos comparten campo, llegado el momento en que el
Tax Engine discrepe del documento, nadie sabrá qué cifra está mirando.

### Decisión

Distinguir desde el diseño, en base de datos, API, frontend y Tax Engine:

| Prefijo | Significado |
|---|---|
| `reported_*` | Valores provenientes del comprobante o documento fuente |
| `computed_*` | Valores producidos posteriormente por nuestro Tax Engine |

**Nunca deben confundirse ni fusionarse en un mismo campo.**

### Consecuencias

- Mayor número de campos en el modelo de datos. Coste aceptado.
- La discrepancia entre ambos se convierte en **una señal de producto**, no en un
  problema a ocultar: detectar que un comprobante declara un impuesto distinto del que
  corresponde es exactamente lo que el contribuyente necesita saber.
- El frontend debe indicar visualmente el origen de cada valor mostrado.

---

<a id="adr-004"></a>
## ADR-004 — Temporalidad del Tax Engine: `as_of_date` y versión de regla

**Estado:** ✅ Aceptada (Día 1)

### Contexto

Las reglas tributarias tienen vigencia temporal. Un motor que calcule siempre "con las
reglas actuales" produciría, tras un cambio normativo, un resultado distinto al
recalcular un período anterior — y el sistema dejaría de ser auditable.

### Decisión

Todo cálculo tributario contempla desde su diseño:

- **`as_of_date`** — fecha que determina qué regla resulta aplicable
- **versión de la regla aplicada** — persistida junto al resultado

Objetivo explícito: **poder reproducir históricamente cualquier cálculo.**

### Consecuencias

- Toda función de cálculo recibe una fecha de aplicabilidad; ninguna asume "hoy".
- Los resultados persistidos incluyen la versión de regla utilizada.
- Los tests incluyen casos de regresión histórica.
- Introducirlo ahora es gratuito; añadirlo después obligaría a revisar todas las
  firmas, todos los datos persistidos y todos los tests.

---

<a id="adr-005"></a>
## ADR-005 — Tax Engine como paquete aislado; ubicación de los tests

**Estado:** ✅ Aceptada (Día 1)

### Contexto

El principio rector `LLM ≠ Tax Engine` necesita una garantía mecánica, no solo
documental. Un motor capaz de consultar la base de datos o de invocar un modelo dejaría
de ser verificable en aislamiento.

Adicionalmente, `tests/` en la raíz se solapaba conceptualmente con los tests propios de
cada paquete.

### Decisión

`tax-engine/` será conceptualmente un **paquete Python independiente**. Debe buscar ser:

- determinista
- testeable
- sin dependencia del LLM
- sin FastAPI
- sin acceso directo a base de datos
- sin I/O innecesario

Sobre los tests: la raíz `tests/` se utilizará principalmente para **integración y
end-to-end**; los tests unitarios específicos podrán vivir junto al módulo
correspondiente.

### Consecuencias

- La separación física impone la separación lógica: un paquete que no importa FastAPI
  ni cliente de base de datos no puede violar sus fronteras por descuido.
- El backend lee los datos y se los entrega al motor; el motor devuelve un resultado.
- Si una implementación pareciera exigir romper alguna de estas condiciones, se
  replantea la implementación — no se rompe la condición.

---

<a id="adr-006"></a>
## ADR-006 — Pipeline de comprobantes con capa anticorrupción

**Estado:** ✅ Aceptada (Día 1)

### Contexto

Si el modelo interno replicase la estructura del formato XML externo, cada cambio de
versión de ese formato rompería nuestro esquema, nuestras consultas y nuestro Tax
Engine. Además existen distintos tipos de comprobante y distintas versiones del formato.

### Decisión

Se adopta conceptualmente el pipeline:

```
Raw XML  →  Source DTO  →  Validation  →  Normalizer  →  InternalInvoice
```

El modelo `InternalInvoice` **no debe limitarse a copiar la estructura del formato XML
externo**. Debe estar **desacoplado de versiones y proveedores externos**.

### Consecuencias

- El conocimiento del formato externo queda confinado a la capa `Source DTO`.
- Un cambio en el formato externo impacta en un solo punto del sistema.
- El modelo interno debe contemplar desde el inicio el tipo de documento y la versión
  del formato de origen.
- El mismo pipeline se reutilizará para futuras integraciones (Fase 9), preservando el
  desacoplamiento del modelo interno.

> **Nota:** los tipos de comprobante y las versiones concretas del formato costarricense
> **no se enumeran** en esta documentación. Requieren fuente oficial verificada
> (AI_INSTRUCTIONS.md, Regla 2).

---

<a id="adr-007"></a>
## ADR-007 — Documento original íntegro, inmutable y verificable por hash

**Estado:** ✅ Aceptada (Día 1)

### Contexto

El XML de un comprobante electrónico es un documento firmado con valor probatorio. Sin
conservarlo, la trazabilidad del dato sería una aspiración documental en lugar de una
propiedad verificable del sistema.

### Decisión

- El XML original **se conserva íntegro e inmutable**.
- Posteriormente se almacenará también un **hash** que permita comprobar su integridad.
- El modelo normalizado **siempre** conservará trazabilidad hacia el documento original.

### Consecuencias

- Cualquier dato fiscal puede rastrearse hasta el documento del que proviene.
- Ante una discrepancia, siempre existe la fuente original para verificar.
- Es posible re-normalizar documentos ya ingeridos si el normalizador mejora, sin
  pedir de nuevo los datos al usuario.
- Coste asumido: almacenamiento de los documentos originales, sujeto al mismo
  aislamiento por tenant que el resto de datos fiscales.

---

<a id="adr-008"></a>
## ADR-008 — Precisión monetaria decimal exacta

**Estado:** ✅ Aceptada (Día 1)

### Contexto

La coma flotante introduce errores de representación inaceptables en cálculos
tributarios. Además, los comprobantes pueden expresarse en distintas monedas con su
correspondiente información de conversión.

### Decisión

- Los valores monetarios **nunca** se manejan con coma flotante cuando pueda producir
  errores de precisión. Se utiliza **representación decimal exacta**.
- Se conserva la **moneda original** y la **información de conversión disponible**
  cuando aplique.

### Consecuencias

- Tipos decimales exactos en base de datos, backend y Tax Engine.
- La frontera con el frontend (serialización) debe preservar la precisión.
- Las reglas de redondeo pertenecen a la regla tributaria, no al código de utilidad.
- Decisión barata hoy; una migración dolorosa si se pospone.

---

<a id="adr-009"></a>
## ADR-009 — Knowledge Base compartida vs. datos fiscales aislados

**Estado:** ✅ Aceptada (Día 1)

### Contexto

Aplicar uniformemente el patrón de aislamiento por tenant a toda la base de datos
produciría normativa duplicada por empresa y divergencias entre tenants.

### Decisión

Dos categorías de datos con **políticas de acceso deliberadamente distintas**:

| | Datos fiscales del contribuyente | Knowledge Base |
|---|---|---|
| Naturaleza | Privados de cada empresa | Conocimiento compartido del sistema |
| Aislamiento | Estricto por tenant (RLS) | No aislado por tenant |
| Escritura | Vía aplicación, auditada | Proceso controlado con verificación de fuente |

### Consecuencias

- La normativa se mantiene una sola vez, coherente para todos los tenants.
- Las políticas de acceso no pueden diseñarse con una plantilla única.
- La Knowledge Base **no contiene datos de contribuyentes** bajo ninguna circunstancia.

---

<a id="adr-010"></a>
## ADR-010 — `AI_INSTRUCTIONS.md` como fuente de verdad; convención de idioma

**Estado:** ✅ Aceptada (Día 1)

### Contexto

Si `CLAUDE.md` y `AI_INSTRUCTIONS.md` contuvieran ambos el conjunto completo de reglas,
divergirían con el tiempo y nadie sabría cuál obedecer.

Adicionalmente, el proyecto es de dominio costarricense (español) pero el código debe
envejecer bien si el equipo crece.

### Decisión

- **`AI_INSTRUCTIONS.md` es la fuente de verdad** de las reglas permanentes de desarrollo.
- **`CLAUDE.md` es un resumen operativo conciso** que apunta a `AI_INSTRUCTIONS.md`,
  evitando duplicar innecesariamente todas las reglas. Ante discrepancia, prevalece
  `AI_INSTRUCTIONS.md`.
- **Idioma:** documentación explicativa en **español**; código, identificadores, nombres
  técnicos, variables, funciones, clases, nombres de archivo y mensajes de commit en
  **inglés**.

### Consecuencias

- Un único lugar que actualizar cuando cambian las reglas.
- `CLAUDE.md` se mantiene corto por diseño: es contexto operativo, no normativa.

---
---

# DECISIONES ABIERTAS AL CIERRE DEL DÍA 1 — ADR-011 a ADR-016

> Las secciones de este archivo agrupan las decisiones por **el momento en que se
> registraron**, no por su estado actual. Algunas de las que aquí se abrieron ya se han
> cerrado desde entonces. **El estado vigente de cada decisión es el de su propio campo
> `Estado` y el del índice.**

<a id="adr-011"></a>
## ADR-011 — Hosting del backend FastAPI

**Estado:** ⏳ Pendiente · **A cerrar en:** Fase 1

### Contexto

El hosting del frontend está previsto en Vercel. Para el backend solo se ha definido
"servicio administrado compatible con FastAPI", sin elección concreta.

### Por qué importa

La elección condiciona la Fase 2. Si el servicio tiene arranques en frío o límites
estrictos de duración de petición, la ingesta de XML no podrá procesarse de forma
síncrona y requerirá procesamiento en segundo plano (**ADR-016**).

También condiciona: gestión de secretos, conectividad con Supabase, observabilidad,
backups y costes.

### Qué falta

Definir criterios de selección (coste, arranque en frío, límites de ejecución, región,
facilidad de despliegue, observabilidad) y evaluar opciones concretas.

### Situación actual

Abierta. No bloquea la Fase 0.

---

<a id="adr-012"></a>
## ADR-012 — Mecanismo de propagación de identidad hacia RLS

**Estado:** ✅ Aceptada (Día 3) · **Criticidad: máxima** · **Sustituye a:** la resolución
parcial del Día 2

### Contexto

[ADR-002](#adr-002) establece *qué* debe ocurrir: las operaciones en contexto de usuario
preservan su identidad y su tenant, y RLS es el mecanismo de aislamiento. El Día 2
resolvió el caso del acceso directo del frontend a Supabase —el cliente propaga el JWT
por cookies y PostgreSQL evalúa `auth.uid()` de forma nativa—, pero eso solo cubre datos
de identidad y tenancy ([ADR-017](#adr-017)).

Los **datos fiscales** irán por FastAPI ([ADR-001](#adr-001)), y ahí la identidad debe
recorrer un camino más largo. Faltaba cerrar la propiedad de seguridad de ese camino.

### Decisión — arquitectura aprobada

```
User
  ↓
Supabase Auth JWT
  ↓
Next.js
  ↓
FastAPI
  ↓
JWT verification
  ↓
PostgreSQL backend role
  ↓
transaction-scoped user identity
  ↓
RLS
  ↓
company_memberships
```

**Reglas obligatorias**

1. FastAPI es el camino normal de acceso a los **datos fiscales del contribuyente**.
2. FastAPI **valida el JWT** emitido por Supabase Auth antes de confiar en la identidad.
3. FastAPI accede a PostgreSQL con un **rol backend dedicado y de mínimo privilegio**,
   que **no** tiene `BYPASSRLS`, **no** es `service_role` y **no** puede convertirse en
   credencial accesible desde el frontend.
4. La identidad del usuario autenticado se propaga hasta PostgreSQL de forma que las
   políticas RLS puedan evaluarla.

### Requisito crítico — alcance transaccional

La identidad debe tener **alcance de transacción**, nunca quedar como estado persistente
de una conexión reutilizable. La arquitectura debe impedir conceptualmente este fallo:

```
transacción de User A
conexión devuelta al pool
transacción de User B
la conexión conserva accidentalmente la identidad de User A
```

Cada operación establece su propio contexto de identidad, y ese contexto **desaparece al
terminar la transacción**. Con conexiones agrupadas, un contexto que sobreviva al
`COMMIT` es una fuga de tenant silenciosa: no falla, devuelve datos de otro
contribuyente.

### Defensa en profundidad — dos barreras

| Barrera | Responsabilidad |
|---|---|
| **FastAPI** | Autenticación · autorización · validación · auditoría y trazabilidad de aplicación |
| **PostgreSQL RLS** | Vuelve a comprobar tenant, membership y rol |

**Nunca depender únicamente de un filtro `WHERE company_id = ...`.** Un filtro olvidado
es un fallo silencioso; una política RLS ausente es un fallo detectable con tests.

### Frontera frontend/backend

Las futuras tablas fiscales **no** deben quedar disponibles como camino alternativo:

```
✗  Frontend → Supabase Data API → datos fiscales
✓  Frontend → FastAPI → PostgreSQL/RLS
```

Esto preserva [ADR-001](#adr-001). La frontera de [ADR-017](#adr-017) sigue vigente:
`companies` y `company_memberships` son identidad y tenancy, y pueden seguir usando
Supabase directamente bajo RLS.

### `service_role`

Queda reservado para futuros procesos administrativos o internos excepcionales que sean
exclusivamente server-side, claramente separados, controlados y auditables. **Nunca será
el mecanismo normal para operaciones fiscales en contexto de usuario**, en coherencia
con [ADR-002](#adr-002).

### Lo que esta decisión NO cierra

Deliberadamente **no** se decide aquí, y deberá verificarse al implementar la foundation
de FastAPI:

librería Python de PostgreSQL · ORM · SQLAlchemy sí/no · driver concreto · Supavisor
frente a conexión directa · transaction pooler frente a session pooler · hosting de
FastAPI ([ADR-011](#adr-011)) · infraestructura de background jobs ([ADR-016](#adr-016)) ·
estructura exacta del contexto en PostgreSQL · SQL concreto de las futuras políticas
fiscales.

Lo que queda cerrado es la **propiedad de seguridad**:

> identidad verificada · rol backend sin `BYPASSRLS` · contexto de alcance transaccional ·
> RLS como segunda barrera.

Cualquier implementación que preserve esas cuatro condiciones satisface este ADR.

### Consecuencias

- Ninguna elección técnica posterior puede sacrificar el alcance transaccional de la
  identidad: es criterio de aceptación, no preferencia.
- El rol backend deberá crearse mediante migración versionada, con sus `GRANT` mínimos.
- La verificación de que la identidad no sobrevive a la transacción tendrá que ser
  **probada**, no supuesta —igual que el aislamiento A/B del Día 2.

---

<a id="adr-013"></a>
## ADR-013 — Proveedor LLM inicial

**Estado:** ⏳ Pendiente · **A cerrar en:** Fase 6

### Contexto

La arquitectura será agnóstica de proveedor (abstracción con adaptadores para OpenAI,
Anthropic, Gemini u otros). Queda por decidir cuál se implementa primero.

### Por qué importa

Menos de lo que parece — ese es precisamente el objetivo de la abstracción. Afecta al
coste, la calidad del tool calling y la latencia, pero no debe afectar a la arquitectura.

### Qué falta

Evaluar en el momento de la Fase 6, con criterios de calidad de tool calling, coste,
latencia y disponibilidad.

### Situación actual

Abierta. No bloquea ninguna fase anterior a la 6. **Ningún SDK de proveedor se importa
directamente en el código del agente** (ARCHITECTURE.md §10.4).

---

<a id="adr-014"></a>
## ADR-014 — Estrategia de embeddings

**Estado:** ⏳ Pendiente · **A cerrar en:** Fase 5

### Contexto

La Knowledge Base utilizará pgvector para búsqueda semántica sobre normativa. Queda por
decidir el modelo de embeddings, su dimensionalidad y la estrategia de fragmentación.

### Por qué importa

Cambiar de modelo de embeddings obliga a reindexar todo el corpus. La dimensionalidad
condiciona el esquema. La estrategia de fragmentación determina la calidad de la
recuperación y la precisión de las citas.

### Qué falta

Definir modelo, dimensionalidad, estrategia de fragmentación y cómo se preservan los
metadatos obligatorios (fuente, artículo, fecha, vigencia, versión) en cada fragmento.

### Situación actual

Abierta. No bloquea fases anteriores a la 5.

---

<a id="adr-015"></a>
## ADR-015 — Modelo de permisos usuario–empresa

**Estado:** ✅ Aceptada (Día 3) · **Sustituye a:** la resolución parcial del Día 2

### Contexto

Un usuario puede acceder a varias empresas, y el usuario secundario del producto
—contadores y despachos que gestionan múltiples clientes— hace que ese caso sea real
desde el principio, no una hipótesis futura. El Día 2 dejó la relación N:M funcionando
con un único rol `owner`; faltaba decidir el conjunto de roles y dónde reside la verdad
sobre la pertenencia.

### Decisión

**Fuente de verdad.** `public.company_memberships` es la fuente de verdad para
determinar si un usuario pertenece a una empresa y qué rol tiene dentro de ella. Un
usuario puede tener **un rol distinto en cada empresa**. Se mantiene el modelo N:M
`user ↔ company` ya existente.

**Roles iniciales.** El producto inicial tendrá exactamente tres:

| Rol | Puede | No puede |
|---|---|---|
| `owner` | Operar los datos fiscales · realizar las acciones administrativas de empresa que correspondan · administrar memberships cuando exista esa funcionalidad | — |
| `editor` | Operar los datos fiscales necesarios para usar el producto | Administrar propiedad ni memberships sensibles |
| `viewer` | Consultar datos fiscales y resultados | Modificar datos fiscales ni memberships |

**El JWT no es fuente autoritativa de membresía ni de rol.** El JWT identifica al
usuario; la membresía y el rol vigentes se consultan **desde la base de datos** en cada
operación.

### Por qué el rol no vive en el JWT

Un token es una fotografía firmada en el momento de su emisión. Si el rol viajara
dentro, revocar un acceso o degradar a `viewer` no surtiría efecto hasta que el token
expirase, y quien conservara un token anterior seguiría operando con el rol antiguo.
Consultar `company_memberships` en cada operación hace que un cambio de rol sea
inmediato y que exista un único lugar donde mirar. El coste —una consulta más— es
precisamente lo que ADR-002 ya exige para evaluar RLS.

### Fuera de alcance (no implementar todavía)

RBAC granular · permisos individuales tipo `invoice.read` / `invoice.write` · roles
personalizados · sistema de invitaciones · UI de administración de miembros.

### Consecuencias

- El `CHECK` actual de `role` admite solo `'owner'`; ampliarlo a los tres roles será una
  migración futura. **No se diseña en este checkpoint.**
- Las políticas RLS de las futuras tablas fiscales podrán discriminar por rol
  consultando `company_memberships`, no leyendo claims del token.
- Modelar `role` como `text` + `CHECK` en lugar de `enum` (Día 2) resulta acertado:
  ampliarlo es DDL corriente.

### Relación con otras decisiones

Complementa [ADR-002](#adr-002) —RLS como mecanismo de aislamiento— y
[ADR-017](#adr-017): `company_memberships` sigue siendo dato de identidad y tenancy, no
dato fiscal. Es la fuente que consultará el mecanismo de [ADR-012](#adr-012).

---

<a id="adr-016"></a>
## ADR-016 — Estrategia de procesamiento en segundo plano

**Estado:** ⏳ Pendiente · **A cerrar en:** Fase 2

### Contexto

La ingesta de XML (parseo, validación, normalización, almacenamiento, hash) puede no ser
apropiada para ejecución síncrona dentro de una petición HTTP, especialmente en cargas
de múltiples documentos.

### Por qué importa

Depende directamente de **ADR-011**: los límites del hosting elegido determinan si el
procesamiento síncrono es viable. Afecta a la experiencia de carga, al manejo de errores
parciales y a la idempotencia de la reingesta.

### Qué falta

Decidir si la ingesta es síncrona, asíncrona o mixta, y qué mecanismo se utiliza.
Evaluar tras cerrar ADR-011.

### Situación actual

Abierta. No bloquea la Fase 1.

---
---

# DECISIONES ACEPTADAS — DÍA 2

<a id="adr-017"></a>
## ADR-017 — Frontera entre datos de identidad/tenancy y datos fiscales

**Estado:** ✅ Aceptada (Día 2) · **Relacionada con:** [ADR-001](#adr-001)

### Contexto

ADR-001 establece que los datos fiscales del contribuyente pasan normalmente por
FastAPI, y que el frontend usa Supabase directamente solo para autenticación y Storage.

El Día 2 introduce `companies` y `company_memberships`, escritas y leídas por el
frontend directamente contra Supabase, sin FastAPI. Antes de implementarlo hay que
determinar si eso contradice ADR-001 — es decir, si estas tablas son "datos fiscales".

### Decisión

**No lo son.** Se establece la frontera:

| Categoría | Tablas | Camino de acceso |
|---|---|---|
| **Identidad, tenancy y autorización** | `companies`, `company_memberships` | Supabase directo bajo RLS |
| **Datos fiscales del contribuyente** | `invoices`, `tax_profiles`, `tax_calculations`, … | **ADR-001**: capa de aplicación / FastAPI |

`companies` y `company_memberships` responden a *quién es el usuario y a qué empresa
pertenece*. No contienen hechos fiscales, no alimentan al Tax Engine y no requieren
trazabilidad hacia un documento origen.

Por eso, en esta fase, pueden utilizar Supabase directamente siguiendo RLS.

### Consecuencias

- El Día 2 no necesita FastAPI y no incumple ADR-001.
- Las tablas de esta categoría **no deben** acumular campos fiscales por conveniencia.
  Un identificador tributario o un régimen fiscal pertenecen al perfil fiscal, no a
  `companies`. Por eso el esquema del Día 2 los excluye deliberadamente.
- Cuando aparezca la primera tabla fiscal, ADR-001 vuelve a aplicar íntegramente.
- El criterio de clasificación ante una tabla nueva: *¿describe la identidad del
  usuario/empresa, o describe un hecho económico del contribuyente?*

### Notas

Esta frontera es interpretable, y por eso se registra de forma explícita en lugar de
darse por supuesta ([AI_INSTRUCTIONS.md](../AI_INSTRUCTIONS.md), Regla 14).

---

<a id="adr-018"></a>
## ADR-018 — Proyecto Supabase alojado de desarrollo; entorno local diferido

**Estado:** ✅ Aceptada (Día 2)

### Contexto

El stack local de Supabase (`supabase start`) requiere un runtime de contenedores. La
inspección del entorno el Día 2 confirmó que **no hay Docker, Colima, Podman ni
OrbStack instalados**.

Instalar uno era posible, pero se prefirió no añadir esa dependencia todavía.

### Decisión

- Se utiliza un **proyecto Supabase alojado dedicado exclusivamente a desarrollo**.
- Ese proyecto es **DEVELOPMENT y nunca producción**.
- **No** se instala Docker ni se levanta Supabase local por ahora.
- **Todas las migraciones viven en el repositorio** (`supabase/migrations/`) y se
  aplican con la CLI: `supabase login` → `supabase link` → `supabase db push`.
- **No se realizan cambios de esquema manualmente** mediante el Table Editor si pueden
  expresarse como migración.
- La configuración del proyecto se gestiona como código en `supabase/config.toml` y se
  aplica con `supabase config push`.

### Consecuencias

- Se evita instalar un runtime de contenedores hoy.
- **Coste asumido:** no existe `supabase db reset`, de modo que los tests de
  aislamiento no parten de estado limpio. Deben usar identificadores únicos por
  ejecución, y los usuarios de prueba se acumulan en el proyecto de desarrollo.
- Los tests dependen de red.

### Revisión pendiente

**El entorno local reproducible con Docker queda diferido y deberá reconsiderarse
cuando crezca la suite de integración.** El punto de disparo natural es el momento en
que la acumulación de estado en el proyecto de desarrollo empiece a producir tests
frágiles — algo previsible al llegar la ingesta de comprobantes (Fase 2).

---

<a id="adr-019"></a>
## ADR-019 — Confirmación de email desactivada solo en desarrollo

**Estado:** ✅ Aceptada (Día 2) · **Ámbito: exclusivamente desarrollo**

### Contexto

Con la confirmación de email activa, un usuario recién registrado no puede iniciar
sesión hasta confirmar. Eso impide probar el flujo signup → login de inmediato y hace
inejecutables los tests automatizados de aislamiento RLS.

### Decisión

En el proyecto de **desarrollo**, `supabase/config.toml`:

```toml
[auth.email]
enable_confirmations = false
```

Queda registrado como **configuración de desarrollo**, anotado en el propio
`config.toml` y aplicable mediante `supabase config push`.

### Lo que esta decisión NO es

**No constituye la decisión para producción.** La política de confirmación de email en
producción es una decisión aparte, todavía **no tomada**, que deberá evaluarse junto
con el proveedor SMTP, la recuperación de contraseña y la política de verificación de
identidad.

### Consecuencias

- El flujo signup → login funciona de inmediato en desarrollo.
- Los tests de aislamiento son ejecutables sin intervención manual.
- Queda una decisión abierta para producción, que **no debe resolverse por omisión**
  heredando la configuración de desarrollo.

### Ajuste relacionado

En la misma configuración se elevó `minimum_password_length` de 6 a 8: el sistema
procesará información tributaria sensible.


---
---

# DECISIONES ACEPTADAS — DÍA 3

<a id="adr-020"></a>
## ADR-020 — Frontera de acceso a datos fiscales

**Estado:** ✅ Aceptada (Día 3) · **Criticidad: máxima** · **Relacionada con:**
[ADR-001](#adr-001) · [ADR-002](#adr-002) · [ADR-012](#adr-012) · [ADR-017](#adr-017)

### Contexto

FastAPI se conecta como `app_backend` y, para operar datos de tenancy, asume
`authenticated` dentro de la transacción. Funciona para `public.companies` y
`public.company_memberships`, que son datos de identidad ([ADR-017](#adr-017)).

Pero **`authenticated` es también el rol con el que la Supabase Data API atiende a los
usuarios autenticados**. Si una tabla fiscal futura recibiera privilegios para
`authenticated` en un schema expuesto, aparecería un camino alternativo:

```
Frontend → Supabase Data API → datos fiscales
```

Eso incumpliría [ADR-001](#adr-001) aunque RLS siguiera aislando entre tenants: el
aislamiento entre contribuyentes se mantendría, pero la regla de que los datos fiscales
pasan por la capa de aplicación quedaría rota.

### Decisión

**Separación de schemas.**

| Schema | Contenido | Data API |
|---|---|---|
| `public` | Identidad, tenancy y autorización: `companies`, `company_memberships` | Expuesto, bajo RLS ([ADR-017](#adr-017)) |
| `fiscal` | Datos fiscales del contribuyente | **NO expuesto** |

`fiscal` **no se añade** a los schemas expuestos por PostgREST. Los objetos fiscales
vivirán ahí salvo decisión arquitectónica posterior explícita.

**`authenticated` no obtiene acceso fiscal.** Ni `USAGE` sobre `fiscal`, ni `SELECT`,
`INSERT`, `UPDATE` o `DELETE` sobre sus objetos. No se convierte en rol de ejecución de
datos fiscales.

**Nuevo rol `fiscal_backend`** — rol de ejecución de FastAPI para datos fiscales:

```
NOLOGIN · NOSUPERUSER · NOBYPASSRLS · NOCREATEDB · NOCREATEROLE
```

Recibe únicamente los privilegios mínimos necesarios sobre `fiscal`, y **ninguno por
anticipación** sobre objetos que aún no existen.

**`app_backend` sigue siendo el único rol de login del backend.** Podrá asumir
explícitamente ambos roles de ejecución, sin heredar sus privilegios:

```
app_backend  (LOGIN, NOINHERIT)
├── authenticated     ← tenancy
└── fiscal_backend    ← datos fiscales
```

En PostgreSQL 16+ la membresía se declara con `WITH INHERIT FALSE, SET TRUE`: permite
`SET ROLE` y niega la herencia. Sin `ADMIN`, que por defecto es `FALSE`.

### La identidad no cambia

ADR-020 **no** altera el origen de la identidad, que sigue siendo
[ADR-012](#adr-012):

```
Supabase JWT → JwtVerifier → AuthenticatedUser ligada al subject
             → request.jwt.claims de alcance transaccional
```

Nunca del frontend, ni de `user_id`, `company_id` o `role` de la petición, ni de claims
de rol personalizados. **El rol de ejecución fiscal no sustituye al usuario:**

```
dentro de la transacción fiscal        tras COMMIT / ROLLBACK
  session_user  = app_backend            current_user       = app_backend
  current_user  = fiscal_backend         request.jwt.claims = NULL
  auth.uid()    = usuario del JWT
```

### RLS sigue siendo obligatoria

`fiscal_backend` **no** tendrá `BYPASSRLS`, y toda tabla fiscal futura tendrá RLS. Que
`fiscal` no esté expuesto **no sustituye** a RLS: son capas distintas.

```
frontera de red/API   +   privilegios de PostgreSQL   +   RLS
```

Un fallo en cualquiera de las tres no debe bastar para exponer datos de otro
contribuyente.

### `service_role`

Reafirma [ADR-002](#adr-002): **no participa en el camino normal de datos fiscales.**
Las operaciones administrativas excepcionales seguirán exigiendo caminos separados,
exclusivamente server-side y auditables.

### Selección del rol de ejecución

El rol de ejecución **jamás procede de la petición**. Es una decisión estática del
código: el llamante elige entre operar tenancy o datos fiscales, no elige un nombre de
rol de PostgreSQL. Aceptar un rol desde el request reintroduciría por otra vía el
problema de identidad que [ADR-012](#adr-012) cerró.

### Autorización dentro del schema fiscal — norma

> **Las políticas RLS fiscales deben apoyarse en helpers privados de autorización
> aprobados, como `private.is_company_member(...)`. El rol de ejecución
> `fiscal_backend` no recibe acceso directo al schema `auth`.**

`fiscal_backend` **no** tiene `USAGE` sobre `auth`, de modo que `auth.uid()` no es
invocable desde una transacción fiscal. No es un descuido: es la norma.

Esto no priva de identidad al rol fiscal. La identidad del usuario viaja en
`request.jwt.claims`, que es exactamente de donde `auth.uid()` la lee, y el helper
`private.is_company_member()` es `SECURITY DEFINER`: resuelve la pertenencia sin que
quien la consulta necesite privilegios sobre `auth` ni sobre
`public.company_memberships`.

La consecuencia operativa es que la autorización fiscal queda concentrada en un
conjunto pequeño de helpers auditables, en lugar de repetirse como expresiones sueltas
sobre `auth.uid()` en cada política. Una política fiscal escrita con `auth.uid()`
directo fallará en voz alta, y eso es deliberado.

### Pertenencia administrativa ≠ capacidad de `SET ROLE`

Son cosas distintas y confundirlas rompe la verificación de la frontera.

Un rol puede figurar como **miembro** de `fiscal_backend` sin poder **asumirlo**. Lo
que decide si puede asumirlo es `set_option` en `pg_auth_members`, no la existencia de
la fila. La propiedad relevante es, por tanto, el **cierre efectivo de las cadenas de
pertenencia siguiendo `set_option = true` en cada salto**, excluidos los superusuarios,
que alcanzan cualquier rol por definición.

`pg_has_role(rol, 'fiscal_backend', 'MEMBER')` **no sirve** como oráculo: devuelve
cierto para roles que no pueden ejecutar `SET ROLE`. Comprobado ejecutándolo ---
`postgres` figura como miembro con `ADMIN`, y al intentar `SET ROLE fiscal_backend`
recibe `42501: permission denied to set role`.

### Gate --- cerrado

La frontera fue implementada en la fase D1 (migración `20260829183152`) y auditada de
forma independiente hasta `0 CRITICAL / 0 HIGH / 0 MEDIUM`. El gate
`BLOCKING BEFORE FIRST FISCAL TABLE` queda **cerrado**: autoriza a **diseñar** el primer
modelo fiscal. No crea ninguna tabla fiscal por sí mismo, y cada tabla futura llevará su
propio diseño de privilegios y políticas.

### Consecuencias

- La guarda runtime que hoy exige membresías exactas `{authenticated}` pasará a
  `{authenticated, fiscal_backend}`; la migración que lo verifica y sus tests deberán
  actualizarse en el mismo cambio.
- Las políticas RLS fiscales que reutilicen `private.is_company_member()` requerirán
  conceder a `fiscal_backend` `USAGE` sobre `private` y `EXECUTE` sobre esa función:
  hoy solo `authenticated` los tiene.
- La frontera debe **probarse**, no suponerse: que `fiscal` no esté expuesto y que
  `authenticated` no lo alcance son afirmaciones verificables con tests.
- La frontera se verifica **en los dos sentidos**. No basta con que `app_backend` sea
  miembro de `fiscal_backend`: hay que comprobar además que **nadie más** puede
  asumirlo. El oráculo correcto es el cierre transitivo de `set_option` en
  `pg_auth_members`, **no** `pg_has_role(..., 'MEMBER')` --- que devuelve cierto para
  roles que no pueden ejecutar `SET ROLE` y produciría un falso positivo.
- `postgres` figura como miembro de `fiscal_backend` con `ADMIN` y `SET FALSE`. Es
  comportamiento sistémico de PostgreSQL 16+ --- quien crea un rol recibe pertenencia
  automática sobre él --- presente igual en `anon`, `authenticated`, `service_role` y
  `app_backend`. No permite asumir el rol y **no se retira**: dejaría el rol sin
  administrador.

### Requisito previo (histórico)

Esta decisión fue el **requisito previo a la primera tabla fiscal**: ninguna se creaba
hasta que la frontera estuviera implementada, probada y auditada. Cumplido en la fase
D1 --- ver «Gate --- cerrado» más arriba.


---

<a id="adr-021"></a>
## ADR-021 — Autoridad de las fuentes oficiales de comprobantes electrónicos

**Estado:** ✅ Aceptada (Día 3, fase E0) · **Criticidad: alta**

### Contexto

Existe abundante material de terceros sobre facturación electrónica costarricense:
librerías, artículos, repositorios y documentación de proveedores de facturación. Casi
todo es más cómodo de leer que los documentos oficiales, y casi todo está desactualizado,
simplificado o directamente equivocado en algún detalle.

Un error de dominio tomado de una fuente secundaria no se manifiesta como un fallo: se
manifiesta como una cifra fiscal incorrecta que nadie detecta.

### Decisión

- La **estructura** de los comprobantes la fijan los **XSD oficiales** publicados por el
  Ministerio de Hacienda para la versión aplicable.
- La **semántica** —significado de códigos, composición de la clave, formatos, notas
  condicionales— la fijan los **Anexos y Estructuras** oficiales y las resoluciones de
  la Dirección General de Tributación.
- Las fuentes secundarias sirven **solo para contraste técnico**. Nunca como autoridad
  fiscal, y nunca como justificación de un campo o una regla.
- Toda afirmación de dominio se registra con su fuente, versión y fecha.
- Lo que las fuentes oficiales no resuelvan se declara **hueco abierto**. No se rellena
  con un valor plausible.

### Consecuencias

- Los XSD y documentos se descargan y analizan, no se parafrasean de memoria.
- El inventario vive en [FISCAL_DOMAIN.md](FISCAL_DOMAIN.md), con matriz de fuentes.
- Cuando Hacienda publique una versión nueva, la revisión consiste en volver a extraer
  desde el origen, no en aplicar un *diff* narrado por terceros.
- Coste asumido: leer XSD y PDF normativos es más lento que copiar un modelo ajeno.

---

<a id="adr-022"></a>
## ADR-022 — Preservación del XML original como artefacto inmutable

**Estado:** ✅ Aceptada (Día 3, fase E0) · **Criticidad: alta**

### Contexto

Normalizar un comprobante a un modelo relacional es interpretarlo. Toda interpretación
puede estar equivocada, y la nuestra evolucionará.

### Decisión

El XML original se conserva **íntegro e inmutable**, junto a una huella criptográfica y
metadatos de procedencia, aunque sus campos se normalicen por separado.

### Consecuencias

- **Valor probatorio:** el documento es el XML, no nuestra lectura de él.
- **Reprocesable:** al corregir el parser se puede reinterpretar el histórico. Sin el
  original, un error de interpretación sería permanente.
- **Permite dejar información fuera del modelo relacional** sin perderla: lo que hoy no
  justifica una estructura sigue estando en el original.
- **Preserva la verificabilidad de la firma.** XAdES/XML-DSig firma sobre una forma
  canónica del documento, no sobre los bytes literales, así que existen
  transformaciones que una firma sí tolera. Pero determinar cuáles son seguras exige un
  análisis que no hemos hecho, y equivocarse invalida la firma de forma irreversible.
  Conservar el original elimina la pregunta: sea cual sea el método de verificación que
  adoptemos, tendremos exactamente lo que se firmó.
- Coste asumido: almacenamiento.

**Sin decidir cuando se aceptó este ADR (fase E0):** algoritmo de huella y mecanismo de
almacenamiento. **Decididos después en el diseño físico de E2** ([ADR-037](#adr-037)):
`raw_xml BYTEA` y `content_sha256 BYTEA` con SHA-256 de los bytes originales exactos, en
PostgreSQL. Se decidieron con los requisitos reales delante, como aquí se pedía.

---

<a id="adr-023"></a>
## ADR-023 — `reported_*` frente a `computed_*`

**Estado:** ✅ Aceptada (Día 3, fase E0) · **Criticidad: máxima**

### Contexto

El principio rector del proyecto es `LLM ≠ Tax Engine`. Existe un segundo límite igual
de importante y más fácil de borrar por accidente: lo que **el comprobante declara** no
es lo que **nosotros calculamos**.

### Decisión

```
reported_*   valor tomado literalmente del comprobante
computed_*   valor calculado por nuestro Tax Engine
```

- Ninguno sobrescribe al otro. Coexisten.
- Un `computed_*` **nunca** se presenta como si lo hubiera reportado el emisor o Hacienda.
- Que difieran es **información**, no un error a ocultar.

### Consecuencias

- Detectar una discrepancia entre lo declarado y lo calculado es una de las cosas más
  valiosas que el producto puede hacer. Un modelo que sobrescribiera lo reportado la
  haría imposible.
- Refuerza [ADR-022](#adr-022): el origen de todo `reported_*` es el XML conservado.
- Coste asumido: más columnas y más disciplina de nombrado.

---

<a id="adr-024"></a>
## ADR-024 — `DocumentParty` como instantánea histórica del comprobante

**Estado:** ✅ Aceptada (Día 3, fase E0)

### Contexto

Un comprobante declara quién era el emisor y quién el receptor **en el momento de
emitirse**. Si esos datos fueran una clave foránea a un catálogo mutable de empresas,
actualizar ese catálogo reescribiría el pasado.

### Decisión

`DocumentParty` representa la **instantánea histórica** de lo que el comprobante decía
sobre emisor y receptor en el momento de emitirse. **No depende, como autoridad, de una
entidad maestra mutable.**

Si en el futuro existe un catálogo de contrapartes, será un índice construido **sobre**
las instantáneas —útil para agregar y buscar— y nunca la fuente de verdad sobre lo que
un comprobante contenía.

### Consecuencias

- Una factura de 2026 sigue mostrando en 2027 exactamente lo que contenía.
- La identificación (`Tipo` + `Numero`) permite agregar por contribuyente sin que el
  catálogo se convierta en autoridad sobre el pasado.
- Si más adelante hace falta una entidad de contraparte, se construye **sobre** las
  instantáneas, nunca sustituyéndolas.
- Coste asumido: repetición de datos de parte entre comprobantes.

---

<a id="adr-025"></a>
## ADR-025 — Núcleo MVP: Factura, Nota de Crédito y Nota de Débito

**Estado:** ✅ Aceptada (Día 3, fase E0) · **alcance deliberadamente acotado**

### Contexto

Los siete comprobantes emitibles de la v4.4 comparten esqueleto. Analizados los XSD,
Nota de Crédito y Nota de Débito son estructuralmente Factura Electrónica más dos
campos, sin ausencias.

### Decisión

El **núcleo del MVP** son tres tipos de comprobante:

```
Factura Electrónica
Nota de Crédito Electrónica
Nota de Débito Electrónica
```

**Lo que esta decisión NO establece.** No declara que todos los tipos de comprobante
vayan a compartir una única tabla o un modelo definitivo. La evidencia estructural
(§3.1 de FISCAL_DOMAIN) muestra que los siete emitibles comparten esqueleto, y eso
*sugiere* un modelo unificado con discriminador — pero el Recibo Electrónico de Pago
tiene 57 nodos frente a 180, y esa diferencia se evaluará cuando toque incorporarlo, no
ahora. El diseño físico se decide por objeto, en su momento.

### Justificación

1. Una factura sin sus notas **miente sobre el importe**: una nota de crédito modifica o
   anula una factura ya emitida.
2. El **coste marginal es casi nulo**: mismo esqueleto, dos campos más.
3. Obliga a **acertar con las relaciones documentales desde el día uno**, porque las
   notas exigen `InformacionReferencia`.

Orden posterior **orientativo**, no decidido: Tiquete → Factura de Compra y de
Exportación → Recibo Electrónico de Pago. Los mensajes de Hacienda y del receptor van
aparte: tienen su propio ciclo de vida y se relacionan solo por la clave.

La revisión 2026 refuerza el núcleo elegido: los códigos de referencia `13`, `14` y `15`
—y su regla de imputación al periodo contable— existen precisamente para notas de
crédito y débito. Sin ellas, esa semántica no tendría dónde aplicarse.


---

<a id="adr-026"></a>
## ADR-026 — `schema_version` ≠ revisión del *ruleset*

**Estado:** ✅ Aceptada (Día 3, fase E0)

### Contexto

Se comprobó con datos, no por conjetura, contra ambas revisiones del documento oficial:

```
versión del esquema      4.4          sin cambio
XSD publicados           9 idénticos  byte a byte, Last-Modified 09-sep-2025
revisión del documento   22/04/2026   Bitácora de Ajustes, 99 páginas
elementos XML añadidos   NINGUNO      verificado comparando ambos documentos
catálogos ampliados      nota 9: 12 → 17 códigos · nota 10: 18 → 20 códigos
```

Hacienda actualizó la semántica y los catálogos —nuevos códigos de referencia,
identificaciones alfanuméricas, excepciones de teléfono, notas técnicas aclaradas— **sin
cambiar la versión `4.4` ni un solo byte de los esquemas**.

La comprobación más clara: `IdentificacionType/Numero` ya era `xs:string maxLength="20"`,
de modo que admitir cédulas alfanuméricas **no requiere tocar el XSD**. El cambio es
puramente de significado.

Consecuencia: un comprobante emitido en octubre de 2025 y otro en diciembre de 2026
declaran ambos `version="4.4"` y están sujetos a reglas distintas.

### Decisión

Registrar por documento ingerido **dos ejes independientes**:

| Eje | Qué es | Procedencia |
|---|---|---|
| `schema_version` | **Versión estructural**, determinada mecánicamente por el tipo de documento, el namespace y el esquema aplicable | Determinable a partir del propio documento. `version="4.4"` es un atributo del **XSD**, no un campo de la instancia XML |
| `spec_revision` | Revisión del documento técnico (*ruleset*) aplicable | **No está en el XML, y la fecha no la determina.** Ver abajo |

`spec_revision` es una propiedad **del documento ingerido**, no una constante global del
sistema.

No se afirma que exista un campo literal de versión dentro del XML: lo que existe es una
**determinación mecánica** a partir del namespace del elemento raíz, que codifica a la
vez el tipo de documento y la versión estructural.

La propiedad que importa se mantiene intacta:

```
schema_version  ≠  ruleset / spec_revision
```

### La fecha de emisión NO determina el *ruleset*

Entre el **22 de abril** y el **1 de noviembre de 2026** la adopción de los cambios es
**anticipada y opcional**. Durante ese periodo conviven, para fechas idénticas:

```
v4.4 + ruleset anterior
v4.4 + ruleset 2026
```

Dos comprobantes emitidos el mismo día pueden estar sujetos a catálogos distintos, según
si su emisor ya adoptó los cambios. Una regla «fecha ≥ 01/11/2026 → ruleset 2026»
clasificaría mal todo el periodo de transición.

La identificación de la revisión requerirá un mecanismo futuro que pondere:

- el **contenido efectivo del documento** — un código `13`–`17` en nota 9, o `19`–`20`
  en nota 10, solo es posible bajo el ruleset 2026;
- la **semántica presente** y qué reglas son consistentes con los valores observados;
- la **compatibilidad de reglas** — qué ruleset explica el documento sin contradicción;
- la **fecha como señal, no como autoridad**.

**Este ADR no diseña ese algoritmo.** Fija que `spec_revision` es un valor **inferido y
registrado por documento, junto a la evidencia que lo sustenta**, nunca una función de
la fecha ni una constante del sistema.

### Consecuencias

- Los catálogos se validan contra la revisión aplicable a cada documento, no contra una
  lista fija. Un `CHECK` con los doce códigos de referencia actuales rechazaría
  comprobantes válidos a partir del 1 de noviembre de 2026.
- Un código como el `13` solo es interpretable bajo la revisión que lo introdujo.
- Al reprocesar el histórico no se aplican reglas de 2026 a documentos de 2025.
- Refuerza [ADR-021](#adr-021): obliga a fechar cada afirmación de dominio, no solo a
  versionarla.
- Se registran huella y `Last-Modified` de cada archivo oficial analizado, porque el
  documento técnico **no lleva dentro** su propio número de revisión.
- Las versiones anteriores del esquema no desaparecen: la propia v4.4 admite v4.3 y
  anteriores para notas de crédito y débito que ajusten comprobantes de su vigencia. El
  sistema debe aceptar más de una `schema_version`.
- Coste asumido: `spec_revision` hay que **inferirla**, con la evidencia que la sustenta,
  y mantener un calendario de revisiones. Es trabajo real y recurrente. La alternativa
  —suponer que `4.4` significa siempre lo mismo— produce interpretaciones silenciosamente
  erróneas del histórico, que es peor. Y no es hipotético: la regla de efecto contable
  por código de referencia (nota 9, revisión 2026) cambia a qué periodo fiscal se imputa
  un ajuste.


---

<a id="adr-027"></a>
## ADR-027 — Modelo lógico de entidades fiscales

**Estado:** ✅ Aceptada (Día 3, fase E1) · **Criticidad: alta**

### Contexto

Los 67 campos clasificados MVP en E0 pueden materializarse como una serialización
relacional literal del XSD —una columna por nodo— o como entidades del dominio. Lo
primero es mecánico y produce un modelo que nadie puede consultar sin el XSD delante.

### Decisión

Siete entidades para el MVP: `SourceDocument`, `ElectronicDocument`, `DocumentParty`,
`DocumentLine`, `LineDiscount`, `LineTax` y `DocumentReference`. Seis más quedan
especificadas pero fuera del alcance.

Detalle en [FISCAL_LOGICAL_MODEL.md](FISCAL_LOGICAL_MODEL.md).

Puntos que la propuesta fija:

**Las siete entidades del MVP:** `SourceDocument`, `ElectronicDocument`,
`DocumentParty`, `DocumentLine`, `LineDiscount`, `LineTax`, `DocumentReference`.

- **`DocumentParty` es `1..2`**: `issuer` exactamente 1, `receiver` **0..1**. Verificado
  contra los Anexos v4.4 (rev. 22/04/2026): el nodo `Receptor` tiene condición **1
  (obligatorio) en Factura** y **2 (condicional) en Nota de Crédito y Nota de Débito**.
  Un modelo común no puede exigirlo sin rechazar notas válidas; cuándo es obligatorio lo
  decide la validación semántica ([ADR-030](#adr-030)).
- **La detección de versión puede fallar.** `SourceDocument` distingue `detected`,
  `unknown`, `unsupported` y `failed`, y `detected_schema_version` es opcional hasta
  detectarse. Invariante: *no poder interpretar un artefacto nunca impide conservarlo*.
- **Coherencia de tenant obligatoria.** Toda entidad fiscal hija pertenece al mismo
  tenant que su padre, sin excepciones. El `company_id` procede del contexto autorizado,
  nunca de la petición. Cómo garantizarlo mecánicamente lo decide E2.
- **Artefacto y documento son entidades distintas**, ligadas por una relación de
  normalización y procedencia —no de contención—, con cardinalidad por ambos extremos:

  ```
  SourceDocument      →  0..1  ElectronicDocument
  ElectronicDocument  →  1..N  SourceDocuments
  ```

  Un artefacto puede no normalizarse nunca (`pending`, corrupto, `unknown`,
  `unsupported`, `failed`); un documento puede proceder de varios artefactos. **La
  dirección física de la clave foránea la decide E2**, no este ADR.
- **`company_id` directo** en las entidades fiscales, separado de las instantáneas de
  emisor y receptor: propiedad de tenant ≠ papel en el documento.
- **`clave` única por empresa**, no globalmente: emisor y receptor pueden ser ambos
  clientes del SaaS y ambos deben tener el comprobante.
- **`direction`** derivada de comparar la identidad de la empresa con las instantáneas,
  almacenada y recomputable, con `unknown` como estado legítimo.
- **Descuentos e impuestos son colecciones**, nunca campos únicos.
- **Importes reportados siempre positivos**: el signo lo aporta el tipo de documento y
  la semántica de la referencia, no el almacenamiento.
- **Ausencia ≠ cero**: ningún campo reportado opcional lleva valor por defecto.

### Consecuencias

- El modelo se consulta en términos del dominio, no del XSD.
- Coste asumido: más entidades que columnas, y decisiones que habrá que revisar al
  incorporar tipos de comprobante con estructuras distintas —el REP tiene 57 nodos frente
  a 180—.
- La cardinalidad permisiva del receptor traslada trabajo a la capa de validación
  semántica. Es deliberado: el modelo común debe adoptar la cardinalidad **más
  permisiva** del conjunto de tipos que soporta.

---

<a id="adr-028"></a>
## ADR-028 — Referencia reportada frente a relación resuelta

**Estado:** ✅ Aceptada (Día 3, fase E1)

### Contexto

`InformacionReferencia/Numero` es **opcional** en el XSD. Una nota de crédito puede
referenciar un documento sin dar su número. Y el orden de llegada no es el orden lógico:
al importar un histórico, una NC puede llegar antes que la factura que ajusta.

### Decisión

Separar en `DocumentReference` dos cosas:

```
reported_*              lo que el documento dice — inmutable
resolved_document_id    el enlace interno, si lo encontramos — opcional
```

La resolución es **diferida, opcional y reintentable**, y nunca modifica los campos
reportados.

**Invariante de tenant:**

```
resolved_document_id  DEBE apuntar a un ElectronicDocument de la MISMA empresa.
```

La referencia **reportada** puede contener cualquier número oficial que traiga el XML —no
lo restringimos, es lo que el documento dice—. La resolución **interna** no: aunque la
`Clave` coincida, jamás puede conectar un documento de la empresa A con el de la empresa
B. Sería una arista entre tenants dentro de nuestro modelo, atravesando la frontera de
[ADR-020](#adr-020), y bastaría seguirla para leer datos de otro contribuyente.

### Consecuencias

- Se puede ingerir una NC antes que su factura sin rechazarla ni inventar un documento
  vacío.
- Una referencia sin resolver es **información legítima** —«apunta a algo que no
  tenemos»— y no un error.
- Coste asumido: hace falta un proceso de resolución posterior, y las consultas deben
  contemplar que el enlace puede faltar.

---

<a id="adr-029"></a>
## ADR-029 — Códigos externos sin clave foránea obligatoria

**Estado:** ✅ Aceptada (Día 3, fase E1)

### Contexto

Los comprobantes traen códigos de catálogos externos: CABYS, unidad de medida, moneda,
tipo de identificación, condición de venta, impuesto, tarifa, descuento y referencias.
Esos catálogos cambian: la revisión 2026 amplió tres de ellos sin tocar el esquema.

### Decisión

```
El código reportado por el comprobante es la verdad.
El catálogo local es enriquecimiento opcional.
```

Ningún código externo lleva clave foránea obligatoria a un catálogo local.

### Consecuencias

- Un comprobante que Hacienda ya aceptó **nunca** se rechaza porque nuestro catálogo esté
  desactualizado.
- El enriquecimiento es una consulta, no una restricción: un código desconocido se
  conserva y se muestra sin descripción.
- Coste asumido: no hay integridad referencial sobre estos códigos; la validación de
  catálogo pasa a ser una comprobación de dominio, no del motor.
- Complementa [ADR-026](#adr-026): los catálogos son datos versionados por *ruleset*.

---

<a id="adr-030"></a>
## ADR-030 — Tres capas de validación

**Estado:** ✅ Aceptada (Día 3, fase E1)

### Decisión

```
Capa 1 — XML / XSD              ¿es un comprobante bien formado y válido?
Capa 2 — semántica del dominio  ¿es coherente como documento fiscal?
Capa 3 — Tax Engine             ¿el tratamiento tributario es correcto?
```

### Consecuencias

- **Un XML válido no implica un tratamiento tributario correcto.** Son preguntas
  independientes; confundirlas llevaría a dar por bueno un comprobante sólo porque
  Hacienda lo aceptó estructuralmente — y detectar esa diferencia es parte del valor del
  producto.
- Cada capa falla con un diagnóstico propio: un error de estructura y una discrepancia
  tributaria no significan lo mismo para el usuario.
- Refuerza el principio rector `LLM ≠ Tax Engine`: la capa 3 es determinista y
  versionada, nunca razonamiento de un modelo.

### Ejemplo concreto: el receptor

```
capa 1 / modelo lógico     receiver 0..1     ← permite Factura, NC y ND
capa 2 / semántica         ¿debe existir?    ← según document_type y ruleset
```

El nodo `Receptor` es **obligatorio en Factura** y **condicional en NC y ND** (Anexos
v4.4, rev. 22/04/2026). Si el modelo común lo exigiera, rechazaría notas válidas; si la
validación no lo comprobara nunca, aceptaría facturas sin receptor.

**Generalización:** no se codifican las condiciones de Hacienda mediante cardinalidades
rígidas del modelo común. Un modelo compartido adopta la cardinalidad **más permisiva**
del conjunto y delega la condición a la capa 2. Lo contrario obliga a un modelo por tipo
de documento, o a rechazar documentos legítimos.

---

<a id="adr-031"></a>
## ADR-031 — Duplicados: artefacto frente a documento lógico

**Estado:** ✅ Aceptada (Día 3, fase E1)

### Contexto

Un mismo comprobante puede llegar dos veces, o por dos vías distintas. Tratar ambos casos
con un único concepto de «duplicado» produciría ventas o compras contadas dos veces.

### Decisión

**Cuatro casos, no dos:**

| Caso | Condición | Respuesta |
|---|---|---|
| **Artefacto duplicado** | Misma empresa · misma huella | Conservar ambos artefactos; un solo `ElectronicDocument` |
| **Mismo documento lógico** | Misma empresa · misma `clave` · contenido equivalente | Un `ElectronicDocument`, varios `SourceDocument` |
| **Conflicto de contenido** | Misma empresa · misma `clave` · **XML divergente** | **No fusionar.** Anomalía de integridad que requiere investigación |
| **Misma clave, distinto tenant** | Empresas distintas · misma `clave` | **Dos** `ElectronicDocument`, uno por tenant |

De ahí que un `ElectronicDocument` pueda tener **1..N** `SourceDocument`, y que un
`SourceDocument` normalice a **0..1** `ElectronicDocument`.

**Sobre el conflicto.** La `Clave` es identidad oficial fuerte, pero coincidir en ella no
autoriza a ignorar que el contenido difiere. Dos documentos divergentes con la misma clave
sólo admiten explicaciones preocupantes —documento manipulado, fallo del sistema emisor,
confusión entre entornos— y todas exigen que alguien mire. Fusionarlos silenciosamente
escogería una versión al azar y destruiría la evidencia de la discrepancia.

> **Precisión de E2, sin cambiar el significado de este ADR.** «Contenido divergente»
> significa **contenido fiscal autoritativo divergente**, no simplemente una huella de
> bytes distinta. Dos serializaciones del mismo comprobante pueden diferir en bytes
> —espaciado, orden de atributos, codificación, envoltura de firma— sin diferir en un solo
> dato fiscal. Una huella distinta es una **observación sobre artefactos**; el conflicto es
> una **conclusión sobre el documento**, y pasar de una a otra exige comparar el contenido
> reportado. Detalle en [FISCAL_PHYSICAL_MODEL.md](FISCAL_PHYSICAL_MODEL.md) §15.1.

**Sobre los dos tenants.** No existe un `ElectronicDocument` global compartido entre
empresas. **La identidad lógica dentro del SaaS es de ámbito de tenant, aunque la `Clave`
sea oficial y globalmente única**: la clave identifica el comprobante ante Hacienda;
nuestro registro identifica *lo que esa empresa tiene*.

### Consecuencias

- Los informes no duplican importes por recibir un documento dos veces.
- Se conserva la traza de **cómo** llegó cada copia: origen y momento de ingesta propios.
- Dos empresas distintas sí tienen cada una su `ElectronicDocument` del mismo
  comprobante: es lo correcto, para una es venta y para otra compra.
- No fija ninguna restricción de unicidad concreta: eso es E2.

> **Restringido en el MVP por [ADR-042](#adr-042).** Este ADR permite fusionar cuando el
> contenido fiscal autoritativo es equivalente, pero no existe todavía componente capaz de
> establecer esa equivalencia — `ParsedFiscalDocument` no normaliza todos los campos
> fiscalmente relevantes. Mientras tanto, el MVP solo acepta como prueba de equivalencia la
> **igualdad de la huella del artefacto**, y trata misma `clave` + huella distinta como
> conflicto visible. Es deliberadamente más estricto que lo que este ADR autoriza. El texto
> de arriba **no se modifica**: sigue describiendo la arquitectura objetivo.


---

<a id="adr-032"></a>
## ADR-032 — Claves foráneas compuestas para seguridad de tenant

**Estado:** ✅ Aceptada (Día 3, fase E2) · **Criticidad: máxima**

### Contexto

[ADR-027](#adr-027) fijó que toda entidad fiscal hija pertenece al mismo tenant que su
padre. Llevar `company_id` en cada tabla es necesario para que RLS decida sobre una
columna propia, pero **por sí solo permite** que una fila declare un tenant y apunte a un
padre de otro. Una línea de la empresa A colgando de una factura de la empresa B es una
fuga entre contribuyentes.

### Decisión

**Cada tabla fiscal lleva `company_id`** para que RLS decida sobre una columna propia. Y
cada hija referencia a su padre con una **clave foránea compuesta**:

```sql
foreign key (company_id, parent_id) references parent (company_id, id)
```

**`UNIQUE (company_id, id)` sólo en las tablas que son destino de una FK compuesta**, no en
las siete:

| Tabla | ¿Destino de FK compuesta? | ¿`UNIQUE (company_id, id)`? |
|---|---|---|
| `electronic_documents` | Sí — desde `source_documents`, `document_parties`, `document_lines` y **dos veces** desde `document_references` | ✅ **Sí** |
| `document_lines` | Sí — desde `line_discounts` y `line_taxes` | ✅ **Sí** |
| `source_documents` · `document_parties` · `line_discounts` · `line_taxes` · `document_references` | No | ❌ **No** |

En una tabla que nadie referencia, `UNIQUE (company_id, id)` es redundante —`id` ya es
único por ser PK— y sólo añade un índice que mantener en cada escritura. **No se sacrifica
seguridad**: el aislamiento lo impone la FK compuesta de la **hija**, no el índice de la
hoja.

**Los dos enlaces opcionales** acotan la acción de borrado a la columna nullable, porque
`company_id` es `NOT NULL` y un `SET NULL` sin columnas intentaría anularla:

```sql
foreign key (company_id, electronic_document_id)
    references fiscal.electronic_documents (company_id, id)
    on delete set null (electronic_document_id)

foreign key (company_id, resolved_document_id)
    references fiscal.electronic_documents (company_id, id)
    on delete set null (resolved_document_id)
```

### Consecuencias

- El cruce entre tenants pasa a ser **imposible en el motor**: la pareja no existiría en
  el índice del padre. No depende de FastAPI, ni de RLS, ni de una revisión de código.
- Coste: un índice único adicional por tabla y una columna redundante por hija. Para datos
  fiscales el intercambio es evidente.
- **A verificar en la implementación:** con `MATCH SIMPLE` (por defecto) la FK compuesta no
  se comprueba si alguna columna es `NULL`, que es justo lo que necesitan los enlaces
  opcionales. Es comportamiento documentado, pero debe probarse en E3, no asumirse.

---

<a id="adr-033"></a>
## ADR-033 — Mapeo decimal exacto y forma sin valor en catálogos

**Estado:** ✅ Aceptada (Día 3, fase E2)

### Decisión

**Decimales exactos**, verificados contra el motor:

| Tipo XSD | PostgreSQL |
|---|---|
| `DecimalDineroType` (18,5) | `numeric(18,5)` |
| `Cantidad` (16,3) | `numeric(16,3)` |
| `Tarifa` (4,2) | `numeric(4,2)` |
| `FactorCalculoIVA` (5,4) | `numeric(5,4)` |
| `Proporcion` (10,5) | `numeric(10,5)` |
| `PorcentajeOC` (9,5) | `numeric(9,5)` |

Nunca `float`, `real` ni `double precision`.

**Códigos de catálogo oficiales: se valida la forma, nunca el valor.**

```sql
check (tax_code   ~ '^[0-9]{2}$')     -- longitud, no lista de valores
check (cabys_code ~ '^[0-9]{13}$')
```

### Justificación

`numeric(18,5)` almacena exactamente `9999999999999.99999` —el máximo del XSD— y desborda
con un dígito más. Comprobado contra la base de datos.

Sobre los catálogos, la evidencia es directa: el XSD publicado enumera **12** códigos de
referencia y **19** tipos de documento referenciado, mientras los Anexos vigentes definen
**17** y **20**. Un `CHECK IN (...)` copiado del XSD **rechazaría hoy comprobantes
válidos**. Es [ADR-029](#adr-029) llevado al motor.

`document_type`, `direction`, `role` y los estados internos **sí** llevan `CHECK` de valor:
son vocabulario nuestro, no catálogo de Hacienda.

### Consecuencias

- PostgreSQL **redondea en silencio** los decimales excedentes en lugar de rechazarlos. El
  XSD ya lo prohíbe, así que la captura corresponde a la capa 1; conviene no confiar en que
  el tipo protege solo.
- Un código inválido de catálogo pasa la base de datos y lo detecta la capa 2.

---

<a id="adr-034"></a>
## ADR-034 — Representación física de fecha y hora

**Estado:** ✅ Aceptada (Día 3, fase E2) · **parcialmente superada por
[ADR-039](#adr-039)** (Día 3, fase E4-A2)

> La estructura de tres columnas por fecha sigue vigente y fue acertada. Lo que ADR-039
> corrige es su **nulabilidad**: esta ADR asumía que el documento siempre declara su
> desplazamiento, y los comprobantes reales demostraron que no. Hoy hay **cuatro** columnas
> por fecha, y el instante y el desplazamiento son **nullables**. El texto original se
> conserva íntegro.

### Decisión

**Las dos fechas fiscales se almacenan en tres columnas cada una.** Seis columnas en total.

`FechaEmision` → `fiscal.electronic_documents`:

```sql
issued_at                timestamptz  not null,  -- el instante
issued_at_offset_minutes smallint     not null,  -- el desplazamiento declarado
issued_at_raw            text         not null   -- el valor literal del XML
    check (issued_at_offset_minutes between -840 and 840)
```

`FechaEmisionIR` → `fiscal.document_references`:

```sql
reported_reference_date            timestamptz not null,  -- el instante
reported_reference_offset_minutes  smallint    not null,  -- el desplazamiento declarado
reported_reference_date_raw        text        not null   -- el valor literal del XML
    check (reported_reference_offset_minutes between -840 and 840)
```

Cada tríada preserva, respectivamente:

```
instante  ·  desplazamiento reportado en la fuente  ·  representación literal exacta
```

**Rango `−840 .. +840`**, no `±1440`: XML Schema limita el desplazamiento de `xs:dateTime`
a `−14:00 .. +14:00`. Un rango mayor admitiría valores que el propio esquema rechaza.

**Las tres columnas de `FechaEmisionIR` son `NOT NULL`** para toda fila existente de
`document_references`, sin `CHECK` de coherencia entre ellas. El XSD declara
`FechaEmisionIR [1..1]` y los Anexos v4.4 le asignan condición **`1`** —obligatorio— en los
siete tipos de comprobante. La opcionalidad vive en el nodo `InformacionReferencia [0..10]`
y se representa por **ausencia de fila**, no por columnas nulas.

### Justificación

Un `timestamptz` solo pierde el desplazamiento, que es **información fiscal**: determina
el día local del emisor, que puede diferir del día UTC. El literal permite demostrar qué
decía exactamente el documento y reprocesarlo si nuestra interpretación cambia.

**La fecha de referencia no es menos fiscal por referirse a otro documento.** Al contrario:
el código `13` de la nota 10 —«facturación mes vencido»— exige indicar ahí **el periodo
fiscal al que pertenece el ingreso**, no la fecha real. Es justamente el campo donde el
valor literal importa.

**No se codifica la zona horaria de Costa Rica en ninguna parte**: el desplazamiento se
toma del documento, y se almacena como desplazamiento reportado, no como zona IANA.

### Consecuencias

- Seis columnas para dos campos lógicos. Coste bajo para auditoría literal y reproceso.
- Un campo lógico puede mapear a más de una columna física sin contradicción: los 48
  campos con valor del inventario producen **52 columnas físicas** (48 − 2 + 6). Las
  columnas auxiliares **no son nodos XML nuevos**.
- Ninguna de las dos fechas pierde instante, desplazamiento ni literal.

---

<a id="adr-035"></a>
## ADR-035 — Unicidad lógica y visibilidad del conflicto

**Estado:** ✅ Aceptada (Día 3, fase E2)

### Decisión

```sql
unique (company_id, clave)     -- nunca unique (clave) global
```

Y **prohibición explícita** de `INSERT ... ON CONFLICT DO UPDATE` sobre
`electronic_documents`.

### Justificación

Una unicidad global sería incorrecta dos veces: contradice que emisor y receptor puedan
ser ambos clientes del SaaS ([ADR-031](#adr-031)), y **filtraría entre tenants** —un error
de unicidad revelaría a la empresa A que la B ya tiene ese comprobante—.

La restricción por tenant impide el duplicado **y hace visible el conflicto**: un segundo
XML con la misma clave produce `23505`, y ahí la aplicación recupera el documento existente
del mismo tenant y compara la evidencia.

**Una huella distinta no basta para concluir conflicto.** Señala artefactos divergentes,
que es una observación sobre bytes; clasificar el caso como conflicto de integridad exige
comparar el contenido fiscal reportado ([ADR-037](#adr-037), §15.1 del modelo físico). La
única conclusión automática admisible es **no fusionar en silencio**.

`ON CONFLICT DO UPDATE` convertiría ese conflicto en una sobrescritura silenciosa,
escogiendo una versión al azar y destruyendo la evidencia de la discrepancia.

### Consecuencias

- La ingesta debe manejar `23505` explícitamente en lugar de delegar en el motor.
- **No se impone `UNIQUE` sobre la huella del artefacto**: conservar ambos artefactos es
  precisamente lo que ADR-031 describe. La deduplicación es una consulta previa, apoyada
  en un índice **no único**.

---

<a id="adr-036"></a>
## ADR-036 — Inmutabilidad, borrado y ausencia de `DELETE`

**Estado:** ✅ Aceptada (Día 3, fase E2)

### Decisión

**Borrado:**

| Relación | Comportamiento |
|---|---|
| Cualquier tabla fiscal → `public.companies` | `ON DELETE RESTRICT` |
| Dentro del agregado del documento | `ON DELETE CASCADE` |
| `source_documents.electronic_document_id` | `ON DELETE SET NULL (electronic_document_id)` |
| `document_references.resolved_document_id` | `ON DELETE SET NULL (resolved_document_id)` |

**Privilegios:** `fiscal_backend` **no recibe `DELETE`** en el MVP, y **tampoco `UPDATE` a
nivel de tabla**: sólo `GRANT UPDATE (columnas)` sobre la lista explícita de metadatos
mutables. Conceder la tabla y revocar columnas después **no funciona** — el privilegio de
tabla sigue autorizando la columna—. Matriz completa en
[FISCAL_PHYSICAL_MODEL.md](FISCAL_PHYSICAL_MODEL.md) §26.3: 15 columnas mutables en 3 de
las 7 tablas; `document_parties`, `document_lines`, `line_discounts` y `line_taxes` no
reciben ningún `UPDATE`.

**Inmutabilidad:** los hechos de origen —artefacto, campos `reported_*`, instantáneas de
partes, líneas, impuestos y descuentos— no cambian. Sí cambian los metadatos de
interpretación: estado de parseo, enlace al documento, revisión de *ruleset*, `direction` y
`resolved_document_id`.

`updated_at` sólo en `source_documents` y `electronic_documents`.

### Justificación

`RESTRICT` en la frontera de empresa impide destruir evidencia tributaria como efecto
colateral. `CASCADE` dentro del agregado es correcto porque una línea sin su factura no
significa nada. Los dos `SET NULL` **acotados a la columna nullable** protegen datos de
origen que deben sobrevivir a la desaparición de aquello a lo que apuntan; sin acotar,
intentarían anular también `company_id`, que es `NOT NULL`, y el borrado fallaría.

Lo que realmente protege los documentos no es el `CASCADE`, sino **no conceder `DELETE`**:
ningún flujo del MVP necesita borrar un comprobante.

### Consecuencias

- Un borrado legítimo será un camino administrativo explícito y auditable, no un privilegio
  permanente. Misma lógica que [ADR-002](#adr-002) aplica a `service_role`.
- Sin *triggers* de inmutabilidad: la protección viene de no conceder `UPDATE` sobre las
  columnas que no deben cambiar.


---

<a id="adr-037"></a>
## ADR-037 — Almacenamiento y huella del artefacto de origen

**Estado:** ✅ Aceptada (Día 3, fase E2) · **Cierra H-6 para el MVP**

### Contexto

[ADR-022](#adr-022) exige conservar el XML original íntegro. Dónde vive y cómo se
identifica quedó abierto como **H-6**.

### Decisión

```sql
raw_xml        bytea not null,
content_sha256 bytea not null
    check (octet_length(content_sha256) = 32)
    check (content_sha256 = pg_catalog.sha256(raw_xml))
```

Función **nativa calificada**: `pg_catalog.sha256`. No `pgcrypto`, no `digest()`, sin
ampliar `USAGE` sobre `extensions`.

**`bytea` dentro de PostgreSQL**, no `xml`, no `text`, no almacenamiento de objetos en el
MVP.

**`content_sha256`**: SHA-256 sobre los **bytes originales exactos**, 32 bytes crudos.

```
misma huella     →  señal criptográficamente muy fuerte de equivalencia de bytes
huella distinta  ↛  semántica fiscal distinta
```

No es una **prueba matemática** de identidad: dos secuencias distintas con la misma huella
son teóricamente posibles, aunque nadie sepa construirlas. Cuando haga falta certeza y
ambos artefactos estén disponibles, la comparación directa `raw_xml = raw_xml` la da; la
huella evita leer los bytes en el caso común.

Y en el otro sentido: **misma `Clave` con huellas distintas señala artefactos divergentes,
que requieren evaluación — no es automáticamente un conflicto de integridad**
([ADR-031](#adr-031), §15.1 del modelo físico).

No es la firma electrónica, ni validación XAdES, ni huella canónica, ni huella del
documento normalizado, **ni prueba de equivalencia lógica entre comprobantes**. Es huella
de contenido para integridad y para señalar artefactos idénticos. **No se diseña
canonicalización propia** ni ninguna «huella canónica del XML».

**Sin `UNIQUE`.** Los mismos bytes pueden corresponder a dos eventos de ingesta
legítimos, con procedencia y momento distintos. Índice **no único** sobre
`(company_id, content_sha256)` para consultar equivalencia antes de insertar. Dos
`SourceDocument` idénticos **no se colapsan automáticamente**.

**Inmutabilidad.** `raw_xml` y `content_sha256` son hechos de origen: no se actualizan
tras el `INSERT`. Un artefacto incorrecto se registra como **otro** `SourceDocument`; los
bytes históricos no se reescriben.

### Justificación

`bytea` y no `xml`: el tipo `xml` valida y puede normalizar, así que rechazaría al
insertar precisamente el artefacto mal formado que hay que conservar para investigar, y
cualquier normalización rompería la huella. `text` fuerza una codificación y puede alterar
bytes. `bytea` no interpreta nada.

Dentro de PostgreSQL y no en Storage: **atomicidad real** —artefacto y metadatos en la
misma transacción, sin objetos huérfanos— y **una sola frontera** de aislamiento, la ya
auditada en el Checkpoint D, en lugar de una segunda superficie de acceso.

Sobre dónde calcular la huella, se verificó en DEV en lugar de suponerlo: `pgcrypto` está
instalado, pero `fiscal_backend` **no tiene `USAGE` sobre el schema `extensions`** —la
llamada devuelve `42501`—, así que usarlo exigiría ampliar la frontera fiscal por una
función de hash. Innecesario: **`sha256(bytea)` es nativa de `pg_catalog`**, alcanzable
por el rol, `IMMUTABLE`, y produce el mismo valor que pgcrypto y que `shasum -a 256`.

Por eso el hash se **calcula en FastAPI y se verifica en la base de datos**: una huella
que no corresponda a los bytes no se puede guardar, sin depender de que el código acierte
siempre. Una única definición canónica, comprobada en los dos lados.

### Consecuencias

- **H-6 cerrado para el MVP.** Resuelve **almacenamiento e integridad del artefacto**; no
  resuelve la **equivalencia lógica entre documentos**, que pertenece a la deduplicación y
  a la validación semántica ([ADR-031](#adr-031), §15.1 del modelo físico). La
  escalabilidad no es bloqueante.
- Migrar en el futuro a almacenamiento de objetos sigue siendo posible, y deberá preservar
  bytes exactos, huella, procedencia, tenant, inmutabilidad y rastro de auditoría. **No se
  añade ahora ninguna abstracción de almacenamiento** para un futuro hipotético.
- El `CHECK` recalcula el hash en cada inserción. Despreciable frente al coste de escribir
  el propio `bytea`, y compra una garantía que ninguna disciplina de código iguala.
- La base de datos crece con los artefactos. Es el coste asumido a cambio de atomicidad y
  de no duplicar la frontera de seguridad.


---

<a id="adr-038"></a>
## ADR-038 — Autorización de escritura fiscal

**Estado:** ✅ Aceptada (Día 3, fase E2) · **Criticidad: alta**

### Contexto

El diseño físico de E2 descubrió que `private.is_company_member(company_id)` —el único
helper de autorización existente— demuestra **pertenencia, no rol**. Verificado leyendo su
cuerpo: consulta `company_memberships` por `company_id` y `user_id`, sin mirar `role`.

El proyecto tiene roles desde el Checkpoint C ([ADR-015](#adr-015)): `owner`, `editor`,
`viewer`. Y en todo el proyecto **no existe ni una sola política RLS de escritura**.

Si las políticas fiscales de escritura usaran ese helper como única autorización, **un
`viewer` adquiriría capacidad de modificar datos fiscales por el mero hecho de ser
miembro** — exactamente lo que los roles existen para impedir.

### Decisión

| Rol | Capacidad |
|---|---|
| `owner` | lectura + ingesta y escritura fiscal |
| `editor` | lectura + ingesta y escritura fiscal |
| `viewer` | **solo lectura** |

**`DELETE`: ningún rol de aplicación en el MVP.**

**Qué significa «capacidad de escritura».** No es la facultad de alterar a mano hechos
fiscales reportados. Significa que FastAPI puede ejecutar, en nombre de un `owner` o un
`editor`, los flujos autorizados de **ingestión, normalización, resolución de referencias
y actualización de metadatos mutables**.

```
capacidad de escritura  ≠  poder modificar hechos reportados
```

Ni `owner` ni `editor` pueden reescribir `raw_xml`, `content_sha256`, la clave, el
consecutivo, la fecha de emisión, los importes reportados, las instantáneas de las partes
ni los hechos de origen de líneas e impuestos. Corregir un artefacto equivocado es
registrar **otro** `SourceDocument`, no editar el existente.

**Forma de las políticas:**

```sql
select  using      ( private.is_company_member(company_id) )
insert  with check ( private.can_write_company(company_id) )
update  using      ( private.can_write_company(company_id) )
        with check ( private.can_write_company(company_id) )
delete  -- sin política y sin privilegio en el MVP
```

`private.can_write_company` es **nombre conceptual**. Requerirá un helper privado
`SECURITY DEFINER` nuevo, apoyado en `company_memberships` con `role IN ('owner','editor')`,
siguiendo el patrón de [ADR-020](#adr-020): sin conceder a `fiscal_backend` acceso directo
ni a `auth` ni a `company_memberships`.

### Consecuencias

- `UPDATE` exige **las dos cláusulas**. Con sólo `USING`, una actualización podría cambiar
  `company_id` y mover la fila a otra empresa: la fila original era visible y nadie
  comprobaría la de destino. Las FK compuestas ([ADR-032](#adr-032)) son defensa
  estructural adicional.
- Separa **operar el sistema** de **reescribir la evidencia**, que es la distinción que
  sostiene [ADR-023](#adr-023) en el plano de los privilegios.
- Sin `DELETE` en el flujo normal, los `ON DELETE` definidos siguen siendo necesarios para
  coherencia referencial y para operaciones administrativas controladas, que se diseñarán
  aparte.
- El helper todavía no está escrito, pero **su contrato queda cerrado en esta fase**:
  firma, volatilidad, `SECURITY DEFINER`, `search_path` vacío, fuente de autoridad,
  identidad, regla de roles y ACL. Detalle en
  [FISCAL_PHYSICAL_MODEL.md](FISCAL_PHYSICAL_MODEL.md) §25.5 y §25.6.

```
CONTRATO DE DISEÑO  =  CERRADO EN E2
IMPLEMENTACIÓN      =  E3
```

---

<a id="adr-039"></a>
## ADR-039 — La fecha de emisión puede no declarar desplazamiento

**Estado:** ✅ Aceptada (Día 3, fase E4-A2 · subfase A2-B1) · **Criticidad: alta**

### Contexto

[ADR-034](#adr-034) y el diseño de E2 §17 fijaron la representación temporal como
**instante + desplazamiento + literal**, con las tres columnas `NOT NULL`. Ese diseño fue
deliberado en un punto importante —no codificar UTC−6 en ninguna parte— pero descansaba
sobre una premisa que nadie verificó: **que el documento siempre declara su
desplazamiento**.

La expansión de fixtures de E4-A2 la desmintió. De **13 comprobantes reales aceptados por
Hacienda, 4 declaran `FechaEmision` sin desplazamiento**: 3 Facturas Electrónicas y el
Tiquete Electrónico.

```
con desplazamiento    2026-08-31T08:55:48-06:00     9 de 13
sin desplazamiento    2026-06-19T14:05:50           4 de 13
```

**La fuente estructural lo permite.** Los XSD v4.4 declaran el campo como tipo primitivo
puro, sin restricción ni patrón:

```xml
<xs:element name="FechaEmision" type="xs:dateTime"/>
```

En XML Schema el huso de `xs:dateTime` es **opcional**. Verificado además que el XSD no
define ningún `simpleType` de fecha ni ningún `xs:pattern` sobre estos campos: los únicos
patrones del esquema son de dígitos (`ClaveType`, `NumeroConsecutivoType`).

Que Hacienda aceptara los cuatro documentos **corrobora** la lectura, pero la prueba es el
esquema, no la aceptación.

### Decisión

**Se separa el reloj de pared del instante absoluto.**

| Columna | Tipo | Nulabilidad | Qué significa |
|---|---|---|---|
| `issued_at_local` | `timestamp` (sin huso) | **NOT NULL** | El datetime civil que el documento declara. **Existe siempre** |
| `issued_at` | `timestamptz` | **NULL** | El instante absoluto. **Solo si la fuente da con qué resolverlo** |
| `issued_at_offset_minutes` | `smallint` | **NULL** | El desplazamiento **declarado**. Nunca uno inferido |
| `issued_at_raw` | `text` | NOT NULL | El literal exacto del XML (sin cambios) |

Ligadas por una restricción que impide los estados incoherentes: `issued_at` y
`issued_at_offset_minutes` **son ambos nulos o ambos no nulos**, y cuando existen, el
instante debe ser exactamente el reloj de pared desplazado.

**Nunca se inventa una zona horaria.** Ni UTC, ni UTC−6, ni la del servidor, ni una zona
IANA. Si el documento no dice cuándo ocurrió en términos absolutos, **la base de datos
tampoco lo dice**.

`FechaEmisionIR` recibe el mismo tratamiento, por el mismo motivo: es el mismo
`xs:dateTime` sin restricción. E2 §17.1 ya exigía esa paridad.

### Consecuencias

**Lo que se gana.** El modelo deja de rechazar casi un tercio de los comprobantes reales
disponibles, y deja de convertir en instante lo que la fuente no fijó.

**Lo que cuesta.** `issued_at` deja de servir como orden universal: un documento sin
desplazamiento no tiene instante comparable. Para ordenar cronológicamente de forma
homogénea hay que usar `issued_at_local`, aceptando que compara relojes de pared de husos
potencialmente distintos. Cuál usar depende de la pregunta:

| Para | Columna |
|---|---|
| Ordenar por instante absoluto | `issued_at` — solo entre documentos que lo tienen |
| Conservar la fecha civil de la fuente | `issued_at_local` |
| Período fiscal (día/mes de devengo) | `issued_at_local` — el día fiscal es civil, no UTC |
| Trazabilidad literal | `issued_at_raw` |

**Lo que NO decide esta ADR.** No decide cómo el Tax Engine determinará el período fiscal;
eso llegará con el motor. Aquí solo se garantiza que el dato civil **existe y no está
contaminado** por una zona inventada.

### Alternativas descartadas

| Alternativa | Por qué no |
|---|---|
| Asumir UTC−6 cuando falta | Inventa información fiscal. Un comprobante de exportación puede declarar otro desplazamiento, y el emisor puede no estar en Costa Rica |
| Asumir UTC | Igual de inventado, y además desplaza el día civil seis horas |
| Usar la zona del servidor | Hace que el mismo XML produzca datos distintos según dónde se ingiera |
| Guardar solo `issued_at_raw` y parsear al vuelta | Renuncia a indexar y comparar; el literal ya se conserva, pero no basta para operar |
| Dejar `issued_at` NOT NULL y rechazar esos documentos | Rechazaría comprobantes que Hacienda aceptó y que el XSD permite |

### Historia

E2 y E3 asumieron desplazamiento explícito siempre; era una asunción razonable y quedó
escrita como tal. **Los fixtures reales de E4-A2 la desmintieron.** La migración
`20260831181500_support_offsetless_fiscal_issue_datetime` adapta el modelo sin editar
ninguna migración histórica y sin inventar zona horaria alguna.

---

<a id="adr-040"></a>
## ADR-040 — Los esquemas oficiales se versionan en el repositorio

**Estado:** ✅ Aceptada (Día 3, fase E4-A2 · subfase A2-C) · **Criticidad: media**

### Contexto

Hasta A2-C, toda afirmación sobre los XSD oficiales descansaba en inspecciones reales pero
**irrepetibles**: los ficheros vivían en un directorio temporal que desapareció. Cuando
A2-B2 quiso volver a comprobar el hallazgo de `xs:dateTime`, no pudo — y una evidencia que
no se puede repetir no es evidencia, es memoria.

A eso se sumaban dos obstáculos concretos:

1. El CDN `cdn.comprobanteselectronicos.go.cr` devuelve **HTTP 403** a peticiones
   programáticas.
2. Los cinco esquemas importan `../../xmldsig-core-schema.xsd`, y **Hacienda no publica ese
   fichero en esa ruta** (HTTP 404, verificado el 2026-09-03). Sin él, **ningún** esquema
   compila: la validación fallaba entera y el error —«failed to load external entity»—
   parecía decir que los XML eran inválidos cuando el problema era el esquema.

### Decisión

**Los esquemas oficiales se versionan, byte-exactos, dentro del repositorio.**

```
backend/resources/fiscal/xsd/cr/
├── MANIFEST.json                 procedencia, huellas y dependencias
├── xmldsig-core-schema.xsd       W3C — dependencia de los cinco
└── esquemas/v4_4/
    ├── FacturaElectronica_V4.4.xsd
    ├── TiqueteElectronico_V4.4.xsd
    ├── NotaCreditoElectronica_V4.4.xsd
    ├── NotaDebitoElectronica_V4.4.xsd
    └── MensajeHacienda_V4.4.xsd
```

**Fuera de `tests/`**, en `resources/`: son recursos de dominio reutilizables, no material
de prueba. El parser de producción usará estos mismos ficheros.

**La profundidad de directorios no es arbitraria.** Reproduce la que los esquemas
oficiales esperan: desde `esquemas/v4_4/X.xsd`, `../../xmldsig-core-schema.xsd` resuelve a
la raíz del paquete. Así el import funciona **sin editar los ficheros oficiales** y sin
instalar un resolutor a medida. Los XSD se conservan intactos; adaptar el entorno es
correcto, adaptar la fuente no lo sería.

**Procedencia, por autoridad separada:**

| Artefacto | Autoridad | Origen |
|---|---|---|
| Los 5 esquemas v4.4 | Ministerio de Hacienda (ATV) | `atv.hacienda.go.cr/ATV/ComprobanteElectronico/docs/esquemas/2024/v4.4/` |
| `xmldsig-core-schema.xsd` | **W3C** | `www.w3.org/TR/2002/REC-xmldsig-core-20020212/` |

El XMLDSIG **no** se toma de Hacienda: Hacienda no lo sirve, y su autoridad canónica es el
W3C, que es quien define el namespace `http://www.w3.org/2000/09/xmldsig#`.

**Integridad anclada al pasado.** Las huellas de los cinco esquemas descargados hoy
**coinciden con las que E0 registró el 2026-08-29** desde una descarga independiente. No es
solo que el fichero no haya cambiado desde que lo copiamos: es que es el mismo artefacto
oficial que analizamos entonces.

**Validación sin red.** `lxml` sobre libxml2, con `no_network`, `load_dtd` y
`resolve_entities` desactivados. El esquema del W3C declara un subconjunto DTD interno,
pero **sus entidades no se usan en el cuerpo** —verificado—, así que compila igualmente.

A eso se añade una **política de recursos** propia registrada en el parser: solo resuelve
ficheros dentro del paquete y rechaza explícitamente `http`, `https`, `ftp` y cualquier
ruta local fuera de él. `no_network` vive dentro de libxml2 y no deja rastro; la política
sí registra cada intento, de modo que la afirmación «no se salió a la red» es una
**observación**, no una confianza. El test que lo prueba parte de estado limpio —sin
esquemas en caché— e intercepta además `socket.socket.connect`,
`socket.create_connection` y `socket.getaddrinfo`.

### Alcance del validador: XSD 1.0 frente a `vc:minVersion="1.1"`

Los cinco esquemas de Hacienda declaran `vc:minVersion="1.1"`, y **libxml2 es un validador
de XSD 1.0**. La diferencia importa: si un esquema usara una construcción exclusiva de 1.1,
libxml2 no la aplicaría **en silencio**, y estaríamos validando menos de lo que creemos.

Verificado que no ocurre. Ninguno de los seis artefactos usa `xs:assert`, `xs:assertion`,
`xs:alternative`, `xs:openContent`, `xs:override`, `explicitTimezone`, `notQName`,
`notNamespace`, `defaultAttributes` ni `inheritable`; `vc:` no aparece fuera del elemento
`<xs:schema>`. Es decir: **declaran 1.1 pero emplean un subconjunto que 1.0 cubre**, y por
eso los seis compilan y los 24 comprobantes validan.

**Esto no es una garantía general de conformidad con XSD 1.1.** Es una afirmación acotada
a los esquemas versionados hoy.

### La garantía frente al futuro no es un escáner

Sería tentador confiar en la comprobación anterior —«ningún esquema usa construcciones de
1.1»— como defensa permanente. **No lo es, y prometerlo sería falso.** Esa lista cubre
construcciones *conocidas*; las diferencias entre XSD 1.0 y 1.1 no se agotan en una lista,
y ampliarla no la volvería exhaustiva. Un escáner incompleto que se presenta como garantía
es peor que no tenerlo: da seguridad sin darla.

**La garantía real es una puerta que se cierra sola:**

```
el validador esta aprobado UNICAMENTE para el paquete XSD exacto revisado en A2-C
        │
cambia un byte de cualquiera de los seis artefactos
        ↓
cambia el fingerprint  →  FALLO determinista  →  REVISION HUMANA
```

**Fingerprint canónico**, ajeno al sistema de ficheros —sin `mtime`, sin orden del
directorio, sin rutas absolutas, sin depender del orden del manifiesto—:

1. SHA-256 de los bytes de cada artefacto;
2. entradas ordenadas por `artifact id`;
3. concatenar `"{artifact_id}:{sha256}\n"`;
4. SHA-256 de esa secuencia en UTF-8.

El digest aprobado vive en `backend/app/fiscal/xsd/policy.py` —código de **producción**
desde E4-B/B1—, **fuera del `MANIFEST.json`** y a propósito: si estuviera en los metadatos de procedencia, quien
regenerase el manifiesto junto a los esquemas abriría la puerta sin darse cuenta. Un test
comprueba además que el digest **no** aparece en el manifiesto.

### La aprobación cubre también la membresía física

El fingerprint por sí solo protege **bytes de artefactos declarados**, y eso deja dos
huecos: un séptimo `.xsd` que nadie declare pasaría inadvertido, y un fichero renombrado o
movido conservando id y bytes también. La ubicación no es cosmética —determina cómo
resuelve `../../xmldsig-core-schema.xsd`—, así que forma parte de lo aprobado.

**Superficie gobernada: todo `*.xsd` bajo la raíz del paquete**, no solo lo que el
manifiesto mencione. Un esquema no declarado sigue estando en el disco, y un import futuro
podría alcanzarlo.

La aprobación cubre cuatro dimensiones, y cualquiera que cambie cierra la puerta:

| Dimensión | Aprobada en |
|---|---|
| conjunto exacto de artefactos | `APPROVED_SCHEMA_ARTIFACTS` |
| identidad `artifact_id` | `APPROVED_SCHEMA_ARTIFACTS` |
| ruta relativa exacta | `APPROVED_SCHEMA_ARTIFACTS` |
| bytes exactos | `APPROVED_VALIDATOR_BUNDLE_SHA256` |

`verify_approved_schema_bundle(schema_root)` es la puerta única: descubre físicamente los
`.xsd`, exige que el conjunto de rutas sea **exactamente** el aprobado, comprueba que el
manifiesto asocie cada id a la misma ruta que la política, y solo entonces valida el
fingerprint. Opera sobre cualquier raíz, de modo que las pruebas de mutación ejercitan
**este mismo mecanismo** sobre una copia temporal, no una simulación en memoria.

**Desde E4-B/B1 la puerta está en el camino de producción**, no solo en CI:
`get_verified_schema_registry()` la invoca antes de compilar nada, y el parser obtiene los
esquemas **únicamente** de ese registro. Si la verificación falla, no se compila ni se
valida: se lanza `ValidatorConfigurationError`, que es un fallo **del servidor**, no del
documento del contribuyente.

**Taxonomía de los fallos de la puerta (E4-B/B1-R2).** Que el paquete esté mal desplegado
es un estado de **configuración esperado**, no un accidente: puede ser ilegible, venir con
otra codificación, traer el JSON roto o tener otra estructura. Todos esos fallos se
normalizan dentro de la política a `BundleRechazado`, con un motivo canónico —texto fijo,
sin rutas absolutas, sin contenido del manifiesto y sin el mensaje de la excepción
original—, y el registro los traduce a `ValidatorConfigurationError` /
`validator_bundle_invalid`. La causa concreta queda encadenada en `__cause__`, disponible
para depurar el servidor, pero no viaja en el texto público.

Dicho con precisión: se normalizan los **fallos esperados de verificación o configuración
del paquete**. No se convierte «toda excepción posible de la inicialización del validador».
La distinción es deliberada — un `AttributeError`, un `NameError` o un fallo de lógica
nuestro siguen propagándose tal cual, porque etiquetarlos «paquete inválido» mandaría a
revisar el despliegue en lugar del código y taparía el incidente real. Por eso la captura
es por clase y por operación, nunca un `except Exception`.

**La clave de enrutado es única, y eso lo impone el registro (R3).** El reparto de
responsabilidades es explícito: la **política** aprueba *qué ficheros* son el paquete
—membresía física, identidad, rutas relativas, bytes, symlinks—; el **registro de
producción** responde de *cómo se elige* un esquema. Cada esquema que enruta comprobantes
tiene una clave `(raíz, namespace URI)`, y esa clave debe apuntar a **exactamente un**
esquema aprobado. Cinco en el paquete actual: FE, TE, NC, ND y MH — `w3c.xmldsig` no
enruta nada, es dependencia compartida.

Como los metadatos de enrutado del manifiesto no entran en el fingerprint, un manifiesto
podía conservar ids, rutas y bytes aprobados —pasar la puerta— y asignar la misma clave a
dos esquemas. Al insertarlos en un diccionario el segundo pisaba al primero **en
silencio**, y el efecto no era quedarse corto de rutas sino **validar contra el esquema
equivocado**: con el tiquete usurpando la clave de la factura, toda factura se validaba
contra el esquema de tiquete. Ahora la repetición se detecta al construir el catálogo
verificado, **antes de compilar nada**, y se rechaza cerrado como
`validator_bundle_invalid`.

**El fingerprint no cubre el `MANIFEST.json`.** Cubre los bytes de los `*.xsd`. De ahí que
un manifiesto pueda conservar el mapeo `id → ruta` aprobado —y pasar la puerta— y aun así
no describir los campos que el catálogo consume (`namespace`, `sha256`, `bytes`). Ese
consumo se somete a la misma taxonomía, de modo que un manifiesto incompleto sale también
como `validator_bundle_invalid` en lugar de reventar a medio camino ya con el visto bueno
dado.

**El `MANIFEST.json` no define qué es el paquete aprobado.** Es metadato de procedencia e
integridad: debe concordar con la política y con el disco, pero no puede autorizar nada por
sí mismo. Verificado con un caso deliberado: renombrar un esquema **y** actualizar el
manifiesto para que apunte a la ruta nueva con el mismo id y los mismos bytes deja el
paquete internamente coherente — y **falla igualmente**, porque la política vive fuera.

**Ningún enlace simbólico dentro del paquete gobernado**, apunte donde apunte. La política
no distingue interno de externo: la sola presencia de un enlace basta para rechazar.

Cubre cuatro sitios: la **raíz** entregada a la puerta, cualquier **directorio**, cualquier
**fichero**, y el propio **`MANIFEST.json`**. La raíz se comprueba **antes** de resolver
nada — resolver primero y aceptar después equivaldría a tratar un enlace como raíz normal.

**La inspección recorre el árbol completo sin seguir enlaces** (`os.walk(followlinks=False)`),
mirando explícitamente los nombres de directorio antes de descender. No basta con que el
recorrido decida no seguirlos: la puerta tiene que *ver* el enlace para rechazarlo.

Esto corrige un hueco real: `rglob("*.xsd")` no ve un directorio enlazado cuyo nombre no
acabe en `.xsd`, ni desciende por él. Un `linked_dir -> /fuera/` con un esquema dentro
quedaba invisible y el paquete pasaba la puerta.

**Alcance de la garantía, dicho sin exagerar.** Lo que se afirma es exactamente esto y nada
más: la raíz no puede ser un enlace · no se admite ningún enlace bajo la raíz ·
`MANIFEST.json` no puede ser un enlace · el conjunto y las rutas de los `.xsd` regulares
están aprobados · los bytes revisados están aprobados. **No** se afirma resistencia frente a
enlaces duros, *junctions*, puntos de montaje ni condiciones de carrera del sistema de
ficheros: eso queda fuera del modelo de amenazas de A2-C.

Un paquete nuevo falla **aunque compile, aunque no contenga ninguna construcción que el
escáner conozca y aunque los 24 fixtures sigan validando**: la aprobación es de bytes, no
de comportamiento observado. Eso obliga a revisar conscientemente la versión de XSD, las
construcciones nuevas, la idoneidad de `lxml`/libxml2, el grafo de dependencias, los
fixtures y la documentación.

**El escáner de construcciones 1.1 se conserva como diagnóstico**, no como garantía: ayuda
a explicar *por qué* algo dejó de encajar, pero no es lo que protege.

### Consecuencias

Un clon limpio puede validar los 24 comprobantes reales **sin acceso a internet y sin un
solo fichero fuera del repositorio**. La afirmación de [ADR-039](#adr-039) sobre
`xs:dateTime` deja de ser un recuerdo y pasa a ser un test.

**Lo que esto NO es.** La validación XSD comprueba **estructura**, no criptografía. Que un
`ds:Signature` sea conforme al esquema **no dice nada** sobre si la firma es válida: eso
exige verificar digest y cadena de certificación, y no está en el alcance de A2-C.

**Coste asumido:** ~500 KB de esquemas en el repositorio, y la obligación de revisar el
paquete si Hacienda publica una revisión. El `MANIFEST.json` existe precisamente para que
esa revisión sea detectable en lugar de silenciosa —el mismo razonamiento de
[ADR-026](#adr-026)—.

### Alternativas descartadas

| Alternativa | Por qué no |
|---|---|
| Descargar los XSD en cada ejecución | Ata los tests a la disponibilidad de Hacienda y a la red; el CDN ya devuelve 403 |
| Cachear en un directorio temporal | Es exactamente lo que falló: el scratchpad desapareció y la evidencia con él |
| Usar un espejo no oficial | Ningún tercero es autoridad fiscal. Solo valdría como contraste |
| Editar el `schemaLocation` de los XSD | Rompe la huella y convierte un artefacto oficial en uno nuestro |
| Reescribir el XMLDSIG para quitarle el DOCTYPE | Misma objeción, y además innecesario: sus entidades no se usan |

---

<a id="adr-041"></a>
## ADR-041 — El parser fiscal es puro y solo emite datos reportados

**Estado:** ✅ Aceptada (Día 3, fase E4-B · subfase B1) · **Criticidad: alta**

### Contexto

El parser es la puerta por donde entran los datos fiscales reales. Todo lo que decida ahí
se propaga al resto del sistema, y algunas decisiones son fáciles de tomar mal sin notarlo:
rellenar un hueco con un cero, deducir un huso horario, o «aprovechar» que ya se tiene el
XML delante para calcular un total.

El principio rector del proyecto —`LLM ≠ Tax Engine`— tiene aquí su equivalente:
**parser ≠ Tax Engine**, y también **parser ≠ persistencia**.

### Decisión

**1. Puro.** `parse_fiscal_document(raw_xml: bytes) -> ParsedFiscalDocument`. Sin base de
datos, sin usuario autenticado, sin `company_id`, sin red. Se puede ejecutar y probar
aisladamente, y eso no es comodidad: es lo que impide que la persistencia se acople a él.

**2. El contenido es la autoridad.** Solo bytes de entrada. Ni nombre de fichero, ni tipo
esperado, ni carpeta. En E4-A2 un fichero llamado «…Estado procesando.xml» resultó ser una
Factura y el único Tiquete se llamaba «Comprobante_Electronico_…»: clasificar por nombre
habría fallado en ambos.

**3. Identidad por `(namespace, local-name)`.** Los prefijos XML no son semántica. Una
raíz conocida con namespace de otra versión **no** se acepta.

**4. Solo `reported_*`.** Ningún `computed_*` sale del parser. No calcula impuestos, no
reconcilia totales, no interpreta catálogos y no juzga deducibilidad. Eso es del Tax
Engine, que no existe todavía.

**5. `Decimal` desde el literal.** Nunca `float`. `455.14000` conserva su escala porque la
escala es información de la fuente.

**6. Ausente ≠ vacío ≠ cero.** Un elemento que no aparece da `None`, jamás `Decimal("0")`.
El corpus real obliga: `TotalDescuentos` falta en unos comprobantes y vale cero explícito
en otros, y `<Registrofiscal8707 />` está presente y vacío.

**7. La validación XSD va dentro del contrato público.** Podría haberse exigido «entrada ya
validada», pero eso delegaría en quien llame la responsabilidad de no saltarse la única
puerta que no debe saltarse. El orden es: parseo seguro → identidad → ¿soportado? →
validación XSD → extracción.

**8. Errores tipados, sin filtrar el documento.** `MalformedXML`, `UnsupportedDocument`,
`XSDValidationError`, `SemanticParseError`, cada uno con código estable. Ninguna excepción
de lxml cruza la frontera, y el detalle de un error de esquema va **acotado**: libxml2 cita
contenido del XML, y estos documentos llevan nombres, correos y direcciones de terceros.

**9. `MensajeHacienda` queda fuera.** Tiene esquema oficial, pero no es un comprobante: sin
líneas ni totales, forzarlo en las siete entidades rompería su semántica. Tendrá parser
propio cuando se necesite.

**10. Soporte semántico solo con comprobante real.** FE, TE y NC se parsean; la **Nota de
Débito** se reconoce y su esquema está versionado, pero **no existe ningún comprobante real
con el que probar la extracción**, así que se rechaza explícitamente. Aceptarla sería
afirmar una cobertura que no tenemos.

### Consecuencias

El parser se prueba sin infraestructura: 13 comprobantes reales, sin una sola conexión a la
base de datos. La persistencia recibirá `(resultado + contexto de tenant)` y será la única
que sepa de `company_id`, huellas y deduplicación.

**El coste** es que el parser no puede «arreglar» un documento raro: si la fuente no dice
algo, aguas abajo tampoco. Es exactamente lo que se busca —un dato ausente debe verse como
ausente, no como un cero plausible—, pero significa que la capa semántica futura tendrá que
tratar con nulos reales en lugar de con valores cómodos.

### Alternativas descartadas

| Alternativa | Por qué no |
|---|---|
| Parser que también persiste | Ata los tests a la base de datos y mezcla dos responsabilidades con ciclos de vida distintos |
| Aceptar entrada «ya validada» | Hace saltable la validación XSD, que es la garantía estructural |
| Rellenar ausentes con `0` | Destruye la distinción ausente/cero, que el modelo físico conserva a propósito |
| Inferir el huso cuando falta | Inventa un dato fiscal. Ver [ADR-039](#adr-039) |
| Pydantic para el dominio interno | Coacciona tipos; el parser existe para *no* transformar la fuente |
| Devolver `lines=[]` en B1 | Fingiría que se buscaron líneas y no había, en vez de que no está implementado |
| Aplanar impuesto y descuento en la línea (B2) | El XSD admite 0..5 descuentos y 1..1000 impuestos por línea; un solo juego de campos perdería documentos legítimos |
| `lines` y `references` con valor por defecto (B2) | Un defecto por omisión vuelve a confundir «no se extrajeron» con «no había» |
| Listas mutables para las colecciones hijas (B2) | Dejarían el agregado mutable por dentro pese al `frozen=True` |
| Inventar un descuento de cero cuando no hay `Descuento` (B2) | Haría creer que el emisor declaró un descuento nulo; ausente no es cero |
| Deducir «exento» de la ausencia de `Impuesto` (B2) | Es una conclusión fiscal. La ausencia de una entidad es ausencia en la fuente |

### Extensión en B2 — el cuerpo de la transacción

B2 no introduce ninguna decisión arquitectónica nueva: **instancia** las de este ADR sobre
`DocumentLine`, `LineDiscount`, `LineTax` y `DocumentReference`. Por eso no se abre un ADR
propio.

Lo que sí conviene dejar escrito, porque es donde el principio se pone a prueba:

- **`LineTax` es evidencia, no cálculo.** No se multiplica base por tarifa, no se recalcula
  `Monto`, no se deduce la tarifa del código ni el código de la tarifa, y no se compara lo
  reportado con lo que «debería» salir. Un modelo cuyos importes no cuadran se construye
  igual: reconciliar es del Tax Engine.
- **`line_number` es el `NumeroLinea` de la fuente**, no la posición en la colección. Si un
  documento numerase sus líneas de forma inesperada, el parser lo reporta tal cual — un
  test lo comprueba sobre un caso preparado en memoria. El orden del documento se conserva
  aparte, y no se ordena por ningún criterio nuestro.
- **`CodigoCABYS` se conserva literal.** No se resuelve contra el catálogo del BCCR, no se
  infiere clasificación y no se decide tratamiento fiscal. El contrato de 13 dígitos es del
  modelo aprobado, no del XSD, que solo exige 13 caracteres — ver el hueco H-3.
- **`UnidadMedida` se conserva como código.** No se traduce, no se resuelve catálogo y no
  se juzga si la combinación cantidad/unidad tiene sentido fiscal.
- **Las referencias no se resuelven.** El parser no busca el documento referido ni exige
  que exista: la NC real del corpus apunta a una FE que no está, y parsea. La resolución es
  diferida y pertenece a la persistencia ([ADR-028](#adr-028)).

**Regla de texto, precisada en B2-R2.** El parser reporta cada valor de cadena según la
**semántica de espacios que define su tipo XSD**, y el recorte genérico está prohibido.

Se auditó la cadena de tipos de los veinte campos de cadena modelados y **todos** derivan
de `xs:string`, cuya faceta es `whiteSpace="preserve"`. Ninguno es `xs:token` ni
`xs:normalizedString`. Por tanto, para todos ellos el literal se conserva **tal cual**.

El razonamiento que había detrás del recorte —«tiene enumeración, patrón o longitud fija,
luego recortar es inocuo»— era inválido por partida doble. La faceta de espacios viene del
tipo, no se deduce de las demás facetas; y en la práctica era falso: `Detalle`, `Nombre`,
`NombreComercial`, `Identificacion/Numero` y `CodigoActividadEmisor` admiten espacios en un
documento XSD-válido, y con `Numero` el recorte llegaba a **rechazar** el comprobante —
convertía `'   '` en `''` y lo trataba como campo obligatorio ausente.

La única normalización que se aplica es la que el propio tipo declara: `xs:decimal`,
`xs:positiveInteger` y `xs:dateTime` tienen `whiteSpace="collapse"`, y ahí se implementa
`collapse` de verdad —recorta los extremos **y** funde los espacios interiores—, no un
`strip` que lo aproxime.

Esto **no** significa que todo literal del XML se conserve byte a byte: significa que se
conserva el valor que el tipo XSD define. Los dos accesores llevan la semántica en el
nombre, `_texto_literal` y `_texto_colapsado`, y no queda ningún ayudante genérico que
recorte por comodidad.

**Cardinalidad de referencias en el agregado (B2-R2).** `InformacionReferencia` es 0..10 en
Factura y Tiquete, y **1..10 en Nota de Crédito y Nota de Débito** —verificado elemento por
elemento en los cuatro esquemas—. El agregado conoce su `document_type`, así que puede
imponerlo al construirse a mano, que es la puerta que no pasa por el validador. La guarda
describe qué estados del modelo son representables; **no** añade soporte de parseo para la
Nota de Débito, que sigue sin él.


---

<a id="adr-042"></a>
## ADR-042 — Deduplicación conservadora por huella en el MVP

**Estado:** ✅ Aceptada (Día 3, fase C1 · subfase C1-A2) · **Criticidad: alta** ·
**Relacionada con:** [ADR-031](#adr-031) · [ADR-035](#adr-035) · [ADR-041](#adr-041)

### Contexto

[ADR-031](#adr-031) fija cuatro casos de duplicado y admite fusionar cuando dos artefactos
de la misma empresa comparten `clave` y **contenido fiscal autoritativo equivalente**. Y es
explícito en que una huella de bytes distinta es una **observación sobre artefactos**,
mientras que el conflicto es una **conclusión sobre el documento**: pasar de una a otra
exige comparar el contenido reportado.

El problema aparece al implementar la persistencia: **hoy no existe con qué hacer esa
comparación.**

`ParsedFiscalDocument` no normaliza todos los campos fiscalmente relevantes del XSD. B2 dejó
diferidos, de forma deliberada y documentada, `CodigoComercial`, `TipoTransaccion`,
`UnidadMedidaComercial`, `ImpuestoAsumidoEmisorFabrica`, `NaturalezaDescuento`,
`FactorCalculoIVA`, `DatosImpuestoEspecifico`, `Exoneracion` y otros. Comparar el
subconjunto que sí normalizamos —consecutivo, totales, moneda, fechas— **respondería a una
pregunta distinta de la que ADR-031 plantea**: diría que coinciden los campos que miramos,
no que los documentos sean fiscalmente equivalentes.

Dos documentos pueden coincidir en todos los campos normalizados y diferir en una
`Exoneracion`, que cambia el tratamiento fiscal por completo. Fusionarlos sería contar una
sola vez algo que son dos hechos distintos, que es exactamente el daño que ADR-031 existe
para evitar.

### Decisión

**Mientras no exista un componente de equivalencia canónica, la única prueba de
equivalencia que el MVP acepta es la igualdad de la huella del artefacto.**

| Caso | Respuesta | Estado devuelto |
|---|---|---|
| Misma empresa · misma `clave` · **misma** `content_sha256` | Equivalencia establecida. Se reutiliza el `ElectronicDocument` y se enlaza el nuevo `SourceDocument` | `linked_existing` |
| Misma empresa · misma `clave` · **distinta** `content_sha256` | Equivalencia **no** establecida. **No fusionar** | `ClaveConflict` |

**Precisión que no debe perderse.** Una huella distinta **no significa** «se ha probado que
el contenido fiscal difiere». Significa **«el MVP no puede probar la equivalencia
automática»**. La afirmación es sobre nuestra capacidad, no sobre el documento. Redactarlo
al revés convertiría una limitación nuestra en una acusación sobre la evidencia del
contribuyente.

Esta política es **más estricta** que lo que ADR-031 permite: renuncia a fusiones que
ADR-031 consideraría legítimas —dos serializaciones del mismo comprobante que difieren en
espaciado, orden de atributos o envoltura de firma— a cambio de no fusionar nunca de más.

### Por qué se elige errar en esta dirección

Los dos errores posibles no son simétricos:

- **Fusionar de más** mezcla dos hechos fiscales distintos en un registro, destruye la
  evidencia de la discrepancia y falsea importes en los informes. Es silencioso.
- **Fusionar de menos** produce un conflicto visible que alguien revisa. Es ruidoso y
  reversible.

Ante datos tributarios, el error ruidoso y reversible es preferible.

### Evolución futura

La regla de huella **puede sustituirse o ampliarse** por un mecanismo de equivalencia
canónica diseñado explícitamente. Entre las posibilidades: una representación fiscal
canónica, comparación insensible a la firma, o comparación completa de campos
autoritativos.

**Nada de eso se diseña aquí.** Hasta que exista: misma `clave` + huella distinta =
conflicto visible.

### Consecuencias

- La persistencia no necesita motor de equivalencia semántica para el MVP.
- El mismo comprobante recibido dos veces por canales distintos, si llega con bytes
  idénticos, se deduplica correctamente.
- Si llega con bytes distintos, hará falta intervención humana hasta que exista la
  canonicalización. Es un coste operativo conocido y aceptado.
- No cambia ninguna restricción física: `(company_id, clave)` sigue siendo la unicidad, y
  el índice de huella sigue siendo **no único** ([ADR-035](#adr-035)).


---

<a id="adr-043"></a>
## ADR-043 — Los documentos externos no entran en el dominio fiscal costarricense

**Estado:** ✅ Aceptada (Día 3, fase C1 · subfase C1-A2) · **Criticidad: alta** ·
**Relacionada con:** [ADR-021](#adr-021) · [ADR-023](#adr-023) · [ADR-027](#adr-027)

### Contexto

Una empresa costarricense gasta en proveedores que **no emiten comprobante electrónico de
Hacienda**: recibos de Uber, facturas de AWS, Adobe, Meta, Epic, SaaS extranjero,
proveedores internacionales. Son gastos reales, con impacto contable y tributario, y el
producto tendrá que tratarlos.

Esos documentos **no tienen** `Clave` de 50 dígitos, ni `NumeroConsecutivo` costarricense,
ni CABYS, ni `CodigoActividad`, ni la estructura XML de Hacienda. Muchos ni siquiera son
XML.

La tentación evidente es meterlos en el modelo que ya existe, rellenando los huecos. Es
justo lo que este ADR prohíbe.

### Decisión

**Son dos dominios normalizados distintos.**

```
evidencia costarricense  →  dominio ElectronicDocument (las siete tablas actuales)
evidencia externa        →  dominio ExternalDocument (futuro, sin diseñar)
```

**Un documento externo no se convierte artificialmente en un comprobante costarricense.**
No se sintetiza `Clave`, ni consecutivo, ni CABYS, ni código de actividad. Un campo
reportado que la fuente no reporta **no existe**: es la misma regla que ADR-041 impone al
parser y que B2 tuvo que defender tres veces.

Las siete tablas fiscales actuales describen **comprobantes electrónicos costarricenses
normalizados**. No son, ni pretenden ser, un modelo universal de factura.

### Lo que este ADR NO decide

- **No** dice que `fiscal.source_documents` vaya a almacenar PDF, imágenes, correos, HTML o
  facturas extranjeras. El modelo físico actual es explícitamente XML: la columna se llama
  `raw_xml` y un `CHECK` impone `content_sha256 = sha256(raw_xml)`.
- **No** diseña la arquitectura futura de almacenamiento de evidencia externa.
- **No** decide si una abstracción genérica futura envolverá, extenderá o sustituirá el
  concepto actual de `SourceDocument`. Queda **diferido**.
- **No** crea tablas ni diseño físico.

### Reportado frente a derivado, también aquí

Si una factura externa no reporta CABYS, **`reported_cabys_code` no se inventa**: no está.

Lo que un sistema futuro sí podrá producir son valores **derivados**, y viven separados de
la evidencia reportada:

| Reportado | Derivado |
|---|---|
| lo que el documento dice | `suggested_cabys_code` |
| | `expense_category` · `expense_subcategory` |
| | `classification_source` · `classification_confidence` |

**Uno no sobrescribe al otro jamás.** Un CABYS sugerido por un clasificador no es un CABYS
reportado, y confundirlos convertiría una conjetura nuestra en evidencia del contribuyente.
Es [ADR-023](#adr-023) aplicado a un dominio nuevo.

### Clasificación de gasto ≠ Tax Engine

Ambos dominios podrán alimentar sistemas superiores compartidos —clasificación de gasto,
analítica financiera, inteligencia tributaria— y ahí conviene fijar la frontera antes de
construir nada:

```
Clasificador de gasto  responde:  ¿qué compró la empresa?
Tax Engine             responde:  ¿cuál es el tratamiento fiscal?
```

Que una línea se clasifique como «Software / SaaS» **no determina** si es deducible, no
deducible, con IVA acreditable o no acreditable. Eso son determinaciones del Tax Engine,
fundadas en reglas tributarias verificadas con fuente, artículo y vigencia.

```
LLM ≠ Tax Engine
Clasificación ≠ Tax Engine
```

**Intención de producto, no diseño.** La clasificación debería operar principalmente a
nivel de **línea** siempre que sea posible: una misma factura puede contener gastos de
naturaleza distinta. Señales que podrán ponderarse: la descripción reportada, el CABYS
cuando exista, el proveedor y sus metadatos de actividad, el histórico de clasificación de
la empresa, reglas deterministas y clasificación por IA. Categorías conceptuales de
ejemplo: inventario/mercadería, suministros de oficina, software/SaaS, servicios
profesionales, telecomunicaciones, transporte, publicidad, alquiler, logística.

**No se diseñan tablas todavía.**

### Consecuencias

- El modelo fiscal costarricense no se degrada para acomodar datos que no son suyos.
- Los documentos externos esperan a un diseño propio en lugar de entrar mal a uno ajeno.
- La frontera clasificación/Tax Engine queda escrita antes de que exista código que la
  pueda cruzar sin darse cuenta.
- Coste asumido: hasta que exista el dominio externo, esos gastos no están normalizados en
  el sistema.

---

<a id="adr-044"></a>

## ADR-044 — Ingesta fiscal en dos fases: la evidencia se preserva antes de interpretarla

**Estado:** ✅ Aceptada (Día 3, fase C2) · **Criticidad: alta** ·
**Relacionada con:** [ADR-007](#adr-007) · [ADR-031](#adr-031) · [ADR-035](#adr-035) ·
[ADR-037](#adr-037) · [ADR-038](#adr-038) · [ADR-041](#adr-041) · [ADR-042](#adr-042)

### Contexto

Un `SourceDocument` es **evidencia fiscal inmutable**: los bytes que el contribuyente
recibió. Interpretarlos —parsearlos, validarlos contra el esquema oficial, normalizarlos—
es una operación posterior que **puede fallar**, y que falla precisamente en los casos que
más interesa conservar: el XML corrupto, el tipo no soportado, la clave en conflicto.

Si captura e interpretación viven en una sola transacción, un fallo del parser revierte
también la captura. El resultado es que **un documento ilegible se pierde justo por ser
ilegible**, y no queda nada que investigar.

Además, la evidencia llegará por varios canales —subida manual (C3), correo (C4),
conectores—, y ninguno puede tener su propia tubería fiscal: sería multiplicar por tres las
reglas de autorización, de trazabilidad y de estado.

### Decisión

**Dos transacciones, nunca una.**

```
T1  transacción fiscal autenticada
    capture_source_document(...)
    COMMIT  ────────────────────────►  la evidencia ya es durable

T2  transacción fiscal autenticada NUEVA
    process_source_document(...)
    COMMIT o ROLLBACK según la clase de error
```

`ingest_fiscal_xml(...)` es la **coreografía síncrona canónica** y posee ese orden. C3 y C4
llaman aquí en lugar de reproducirlo; C4 podrá además usar los dos primitivos por separado
alrededor de una cola, sin reescribir nada.

**`parse_status` describe el parseo, no la tubería.** Que la normalización se completara lo
representa `electronic_document_id`, y solo eso. De ahí el caso que fija la arquitectura:
parseo correcto + `ClaveConflict` ⇒ `parse_status = 'parsed'`, `parse_error = NULL`, sin
enlace.

**`parse_error` pertenece solo al parseo.** Nunca almacena errores de persistencia,
diagnósticos de PostgreSQL o de lxml, ni un solo dato del contribuyente.

**Los eventos de evidencia duplicada se preservan.** Dos recepciones de los mismos bytes son
dos hechos distintos y generan dos `SourceDocument`. Deduplicar evidencia y deduplicar
documentos normalizados son conceptos deliberadamente separados: lo segundo es de C1
([ADR-031](#adr-031), [ADR-042](#adr-042)).

**C2 es independiente del canal.** Registra por dónde llegó la evidencia; no sabe nada del
transporte.

### Consecuencias

- **La evidencia sobrevive a todo lo que venga después.** Fallo del parser, documento no
  soportado, conflicto de clave, caída temporal de la base, error interno o caída del
  proceso tras T1: ninguno puede borrar los bytes recibidos.
- **Dos transacciones son intencionadas**, no un descuido. Se paga una segunda apertura de
  transacción a cambio de que la evidencia no dependa de que la interpretación funcione.
- **El llamante puede recibir un error cuando el artefacto ya existe.** Es la consecuencia
  directa de comitear T1 primero, y es deseable.
- **Por eso `source_document_id` viaja como contexto del error**: sin él, quien recibe el
  fallo no puede referirse al artefacto que sí se guardó. Es un UUID interno, no un dato
  del contribuyente.
- **El estado del parser y el de la persistencia permanecen separados** y no se deducen uno
  del otro.
- **El procesamiento asíncrono cabe sin rediseño**: `process_source_document` ya es un
  primitivo independiente que opera sobre un artefacto ya durable.
- Coste asumido: un artefacto puede quedar capturado y sin procesar si T2 falla. Es
  preferible a perder la evidencia, y el reintento es idempotente.

### Lo que este ADR NO decide

- **No** implementa transporte: ni subida (C3), ni extracción de correo (C4).
- **No** introduce cola ni procesamiento en segundo plano.
- **No** toca el Tax Engine, que sigue sin existir.
- **No** amplía el dominio a documentos externos ([ADR-043](#adr-043)).
- **No** reimplementa nada de C1: la persistencia normalizada, el arbitraje de la carrera
  por `Clave`, la deduplicación por huella y el enlace final siguen siendo suyos.

---

<a id="adr-045"></a>

## ADR-045 — Frontera web fiscal: Next.js de servidor → FastAPI → RLS de PostgreSQL

**Estado:** ✅ Aceptada (Día 3, fase C3) · **Criticidad: alta** ·
**Relacionada con:** [ADR-001](#adr-001) · [ADR-012](#adr-012) · [ADR-015](#adr-015) ·
[ADR-017](#adr-017) · [ADR-020](#adr-020) · [ADR-038](#adr-038) · [ADR-039](#adr-039) ·
[ADR-044](#adr-044)

### Contexto

C3 construyó la primera vertical web completa sobre el dominio fiscal: un usuario sube un
XML de Hacienda desde el navegador y más tarde ve su estado durable en la bandeja. Ese
camino cruza tres procesos —navegador, servidor de Next.js, FastAPI— antes de llegar a
PostgreSQL, y cada cruce es una decisión de confianza que hasta ahora estaba repartida
entre ADRs de capas más profundas. Este ADR registra la frontera web tal y como quedó
**implementada y probada en ambas direcciones**, no un diseño hipotético.

Las razones de que exista una frontera deliberada de servidor:

- Los datos fiscales son **datos sensibles del contribuyente**, aislados por empresa.
- El navegador no debe recibir credenciales de base de datos ni configuración de
  infraestructura del backend (`BACKEND_URL` es solo de servidor).
- Las tablas fiscales **no se exponen** como acceso normal de Data API al frontend: el
  camino es el de [ADR-001](#adr-001)/[ADR-017](#adr-017)/[ADR-020](#adr-020).
- La autorización no puede depender del estado de la interfaz ni de un rol que aporte el
  propio usuario.
- La identidad del JWT debe estar verificada **antes** de que ninguna operación toque la
  base fiscal.
- RLS de PostgreSQL es la **autoridad final** de autorización por empresa.

### Decisión

**El navegador no habla con FastAPI para el flujo fiscal.** Interactúa con la frontera de
aplicación de Next.js, y ambas direcciones atraviesan el mismo modelo de confianza:

```
ESCRITURA                                  LECTURA
navegador                                  navegación del navegador
  → FormData                                 → Server Component / helper de servidor
  → Server Action de Next.js                 → petición a FastAPI desde el servidor
  → FastAPI                                  → FastAPI
  → identidad en la transacción              → identidad en la transacción
  → RLS de PostgreSQL                        → RLS de PostgreSQL
  → dominio de ingesta fiscal                → dominio de bandeja fiscal
```

No existe arquitectura fiscal de API en el navegador dependiente de CORS.

**Lo que la capa de servidor de Next.js PUEDE hacer:** recibir el `FormData` del
navegador; preservar los bytes exactos de la subida; obtener en el servidor el token de
acceso autenticado de Supabase; verificar y fijar el token exacto antes de reenviarlo;
llamar a FastAPI; validar los contratos de respuesta del backend; traducir resultados a
estado seguro de interfaz; hacer lecturas desde el servidor; y disparar la revalidación
del workspace.

**Lo que NO puede hacer:** convertirse en Tax Engine; parsear o normalizar XML para
producir verdad fiscal; decidir autorización de empresa; inferir membresías o roles
fiscales; ni saltarse FastAPI leyendo tablas fiscales directamente de Supabase.

**Secuencia de token probada.** `getClaims()` establece y valida el contexto de sesión
autenticada; `getSession()` extrae únicamente el `access_token` como valor opaco de
transporte —su `user` no se lee y ningún permiso se deriva de él—; `getClaims(token)`
verifica el token exacto que va a reenviarse; y ese mismo token viaja como
`Authorization: Bearer` a FastAPI, que lo valida **independientemente** contra JWKS.
Ni `session.user` ni ninguna claim de rol o membresía del JWT son autoridad de
autorización: la membresía se resuelve en la base ([ADR-012](#adr-012),
[ADR-015](#adr-015)).

**FastAPI es la frontera fiscal de API**: verificación del JWT, contratos estables de
petición y respuesta, admisión acotada de evidencia cruda, orquestación fiscal, apertura
de la transacción, instalación de la identidad de la petición para RLS e invocación de
los servicios del dominio. No usa comprobaciones de membresía en la capa de aplicación
como mecanismo primario de autorización.

**El camino a la base es el de [ADR-020](#adr-020)**: conexión del backend con un rol
dedicado de privilegio mínimo, identidad de la petición con alcance de transacción, y RLS
como autoridad final. Sin `service_role` como camino normal, sin `BYPASSRLS`, sin acceso
fiscal directo por Data API desde el frontend.

**`company_memberships` sigue siendo la fuente de verdad** ([ADR-015](#adr-015)), con los
roles `owner`, `editor` y `viewer`. Para escrituras fiscales, RLS vía `can_write_company`
permite owner/editor y niega viewer ([ADR-038](#adr-038)); para lecturas,
`private.is_company_member` permite a los tres. No se inventa RBAC granular.

**Lectura y escritura tienen semánticas de negación distintas, y es deliberado.** Una
escritura fiscal no puede convertirse en silencio: los caminos no autorizados producen la
semántica de prohibición existente, incluido el 403 donde corresponde. La colección de
lectura `GET /companies/{company_id}/fiscal-documents` es en cambio **no enumerable**:
para un usuario autenticado al que RLS no expone ninguna fila, la respuesta es HTTP 200
con colección vacía y contadores en cero. Eso hace indistinguibles la empresa propia con
bandeja vacía, la empresa ajena, el UUID cruzado y el UUID inventado. No se añade ningún
preflight de membresía en Python solo para fabricar un 403. Esta regla es una decisión de
**colección de lectura**; no se generaliza a cualquier endpoint futuro.

**La navegación del frontend no es autorización.** El `companyId` de `/app/[companyId]`
es contexto, no prueba: editarlo a mano no concede acceso fiscal. La visibilidad final la
deciden el JWT verificado en el backend y RLS en la base.

**La frontera de datos tiene dos regímenes** ([ADR-017](#adr-017)): los datos públicos de
identidad y tenancy pueden usar los patrones directos de Supabase ya establecidos; los
datos del dominio fiscal van siempre por Next de servidor → FastAPI → base fiscal con
RLS. La división es deliberada y valiosa: no debe erosionarse por conveniencia.

**La evidencia cruza la web intacta** ([ADR-044](#adr-044)): `File` del navegador →
`arrayBuffer()` → cuerpo HTTP crudo → lectura acotada en FastAPI → evidencia del
`SourceDocument`. Next.js no decodifica el XML, no lo normaliza, no quita el BOM, no
altera CRLF, no parsea DOM ni re-serializa.

**Next.js no se fía del JSON de FastAPI.** C3 estableció validación estricta en la
frontera: estado HTTP, forma del cuerpo, combinación código/categoría/razón, presencia
del identificador, ítems discriminados de la bandeja, UUIDs, marcas de tiempo, cadenas
decimales exactas, contadores y cursor. Una respuesta desconocida o contradictoria cierra
en fallo hacia un estado seguro de producto; ningún diagnóstico crudo llega al usuario.

**La incertidumbre de transporte no es un resultado del dominio.** Un 503 confirmado con
`source_document_id` significa que la evidencia se preservó; un `fetch` rechazado, un
timeout o una conexión cortada producen `upload_outcome_unknown` / `indeterminate`, que
no puede afirmar ni recepción ni no-recepción. No hay reintento automático, y el estado
indeterminado **no se persiste** como estado fiscal: la bandeja permite al usuario
comprobar si la evidencia apareció antes de volver a subir.

**El modelo de lectura de B3** —estado durable → clasificación operativa determinista →
bandeja híbrida → contrato de lectura de FastAPI → interfaz de servidor— queda como está:
la clasificación no usa IA y el XML crudo no se reparsea durante la lectura. Los
decimales fiscales reportados cruzan la frontera web como **cadenas exactas**, nunca
convertidas a `Number` de JavaScript; la fecha local de emisión conserva la semántica de
reloj de pared de [ADR-039](#adr-039), separada del instante de sistema. Este ADR
referencia esas decisiones; no las redefine.

### Alternativas rechazadas

- **A. Navegador → FastAPI directamente.** Expone la frontera del backend al navegador,
  exige arquitectura de API/CORS en el cliente, complica la frontera de configuración de
  token y backend, y esquiva la validación de contratos que la capa de servidor ya hace.
- **B. Navegador → Data API fiscal de Supabase.** La arquitectura fiscal está
  deliberadamente detrás de FastAPI; duplicaría fronteras de API y dominio y arriesgaría
  divergencia en autorización y validación fiscal.
- **C. `service_role` para peticiones fiscales ordinarias.** Puentea la autoridad de RLS
  y contradice el diseño de privilegio mínimo.
- **D. Comprobaciones de membresía en Python como autorización primaria.** Duplicarían la
  lógica de autorización de empresa con riesgo de divergir de RLS;
  `company_memberships` + RLS son la fuente de verdad.
- **E. Confiar en claims de rol/empresa del JWT como autoridad.** Las membresías cambian
  con independencia del token; la arquitectura vigente resuelve la membresía en la base.
- **F. Parseo o normalización en el cliente antes de subir.** Cambia la frontera de
  evidencia; los bytes crudos deben conservarse.
- **G. Reintento automático tras un fallo ambiguo de transporte.** Puede duplicar
  evidencia o acciones: quien llama no sabe si el servidor ya capturó el documento.

### Consecuencias

- **Una sola frontera fiscal de API**, con RLS como autoridad de tenant en lectura y
  escritura; el navegador nunca necesita acceso a la base fiscal ni recibe secretos del
  backend.
- **La evidencia se preserva exacta** y los contratos web/backend son consistentes; ambos
  flujos comparten el mismo modelo de confianza.
- **Los canales futuros podrán reutilizar el dominio fiscal** sin copiar su lógica — sin
  afirmar que ningún canal futuro esté implementado.
- Costes asumidos: un salto extra de red/servidor por Next + FastAPI; validación de
  contrato duplicada entre backend y frontera de frontend; manejo de token en el
  servidor; la no-enumerabilidad de lectura hace que una colección vacía no distinga
  empresa no autorizada de empresa genuinamente vacía; y la disciplina de contrato
  SQL/dominio exige tests que la vigilen.

### Invariantes de seguridad

1. El navegador nunca recibe credenciales de base de datos.
2. El navegador nunca recibe `service_role`.
3. El navegador nunca lee tablas fiscales directamente.
4. FastAPI verifica el JWT de forma independiente.
5. La autorización de tenant descansa en última instancia en RLS de PostgreSQL.
6. Un `company_id` en la petición no concede nada por sí solo.
7. Ni la lectura ni la escritura fiscal pueden puentear RLS.
8. La evidencia fiscal cruda no es mutada por decodificación en el frontend.
9. La incertidumbre de transporte no se promociona a falsa certeza de dominio.
10. La frontera web no produce conclusiones tributarias.

### Lo que este ADR NO decide

- La arquitectura de documentos externos ([ADR-043](#adr-043)).
- La ingesta por correo, el proveedor o transporte de WhatsApp, ni el motor de
  notificaciones.
- La lógica del Tax Engine ni el cálculo de IVA.
- El radar normativo ni el perfil fiscal de empresa.
- La dirección venta/compra de los documentos.
- La arquitectura de reprocesamiento de artefactos pendientes.

---

<a id="adr-046"></a>

## ADR-046 — Buzón Tribuu: intake automatizado, evidencia empresarial y autorización de máquina

**Estado:** ✅ Aceptada (Día 3, fase C4-A) · **Criticidad: alta** ·
**Relacionada con:** [ADR-012](#adr-012) · [ADR-015](#adr-015) · [ADR-017](#adr-017) ·
[ADR-020](#adr-020) · [ADR-023](#adr-023) · [ADR-038](#adr-038) · [ADR-039](#adr-039) ·
[ADR-041](#adr-041) · [ADR-043](#adr-043) · [ADR-044](#adr-044) · [ADR-045](#adr-045)

### Contexto

C3 dejó una vertical web completa, pero exige que el usuario abra la aplicación y suba
cada XML a mano. El objetivo de C4 es que *«Tribuu recibe toda la evidencia empresarial
relevante que llega al Buzón Tribuu»*, con un principio rector: **Tribuu puede no
entender todavía un documento, pero si confirma que lo recibió, no debe perderlo.**

Eso introduce dos fronteras nuevas que ningún ADR anterior cubre: una entrada
**máquina-a-máquina** (el correo entrante no es una petición autenticada de usuario) y
un dominio de **evidencia empresarial** más amplio que el XML de Hacienda (PDF, imagen,
y recibos que solo existen como cuerpo de correo). Este ADR congela la arquitectura
durable de ambas; los detalles específicos de proveedor pertenecen a C4-B.

### Decisión

**Buzón por empresa, aprovisionado al activar.** Cada empresa participante puede
activar UN Buzón Tribuu. Configuran owner/editor; viewer ve estado y dirección pero no
muta. Dirección conceptual `<prefijo>-<token>@inbox.tribuu.ai`: el prefijo es
únicamente cosmético; el token es aleatorio de **≥ 80 bits de entropía CSPRNG**, único,
rotable y desactivable. La dirección es **ruta de entrega, jamás autorización para leer
datos del tenant**.

**El remitente es NO CONFIABLE — invariante fundacional.** `From`, `Reply-To`, el
display name, el dominio del remitente, el asunto o el contenido de un adjunto jamás
determinan la empresa. El tenant se resuelve SOLO así: proveedor verificado →
destinatario del sobre → Buzón Tribuu ACTIVO → `company_id`.

**Borde neutral al proveedor.** El payload específico del webhook se traduce en un
adaptador de borde al contrato de intake propio de Tribuu. El núcleo del canal y el
dominio no dependen de Mailgun, Postmark, SES, SendGrid ni de ningún otro; la selección
pertenece a C4-B0.

**Autorización de máquina.** El correo entrante NO es una petición autenticada de
usuario. Quedan rechazados: usuario ficticio, membresía sintética, JWT de navegador,
`service_role` y `BYPASSRLS`. Modelo requerido: evento verificado del proveedor →
buzón activo de la empresa → contexto dedicado de canal/máquina → transacción acotada
a ESA empresa → RLS de PostgreSQL → dominios de canal y C2. **RLS sigue siendo la
autoridad final de tenant** ([ADR-012](#adr-012), [ADR-020](#adr-020)); el rol, las
funciones y las políticas exactas pertenecen a C4-B1. El contexto de máquina solo
puede ejecutar las operaciones canónicas de ingesta que C2/C1 necesitan —captura de
evidencia, lecturas de deduplicación, mutación de ciclo de vida, persistencia del
documento normalizado y de sus hijos— sin lecturas generales del tenant y sin ningún
acceso entre empresas.

**Correo ≠ evidencia ≠ documento.** Un mensaje puede contener varios ítems de
evidencia; un documento económico puede tener varias representaciones
(`factura.xml` + `factura.pdf` pueden ser UNA factura). La abstracción conceptual
neutral es **`InboundEvidenceItem`**, con al menos las clases `attachment` y `body`.
El esquema físico NO se congela aquí (recomendación vigente: almacenes físicos
separados por clase tras la abstracción común; diseño final en C4-B1).

**Fidelidad de la evidencia.** Para los ADJUNTOS: se preservan los **bytes exactos tal
y como el proveedor los presenta a Tribuu** — SHA-256, metadatos, procedencia y estado
durable ANTES de interpretar; sin decode/re-encode previo a la captura. Para el
CUERPO: puede ser evidencia empresarial por sí mismo y **no se llama adjunto**; hasta
la selección de proveedor la garantía es la **representación exacta entregada por el
proveedor** (MIME/RFC822 crudo, HTML, HTML normalizado, texto plano o estructura
normalizada del proveedor), con procedencia explícita de cuál se recibió. No se afirma
fidelidad RFC822 original hasta que las capacidades del proveedor la soporten.

**Seguridad del cuerpo.** El HTML de correo jamás se ejecuta: sin scripts, sin carga
de imágenes remotas, sin píxeles de rastreo, sin contenido activo, sin render de HTML
arbitrario como interfaz de confianza. La inteligencia documental futura trabaja sobre
representaciones saneadas.

**Retención del cuerpo.** Se congela solo el requisito arquitectónico: los recibos que
solo existen como cuerpo deben ser soportables, y puede requerirse un mecanismo de
retención temporal ACOTADA hasta que D1/D2 puedan clasificar si el contenido es
evidencia de negocio. El plazo exacto queda ABIERTO; no se inventan periodos legales.

**Principio de evidencia durable.** Si Tribuu acepta evidencia de negocio y confirma
la recepción, no puede perderla. PDF/imagen/adjuntos de negocio aceptados → bytes
exactos en almacenamiento durable de objetos. El XML fiscal NO se muda: su evidencia
canónica sigue siendo `fiscal.source_documents.raw_xml` ([ADR-044](#adr-044)); C2 no
se rediseña. Frontera de almacenamiento neutral al proveedor: **PostgreSQL** guarda
identidad, metadatos, estado, procedencia, relaciones, huellas y localizadores;
**el almacén de objetos** guarda los bytes grandes de evidencia externa. Sin vendor
elegido.

**El XML es canónico para lo fiscal costarricense.** Para un comprobante electrónico
CR válido, el XML es la fuente canónica de los hechos fiscales REPORTADOS: va por C2
(`ingest_fiscal_xml`, `IngestionSource.EMAIL`, bytes exactos) → SourceDocument →
ElectronicDocument. Un PDF hermano se preserva como representación y **no crea un
segundo ElectronicDocument**. Ninguna extracción futura por OCR/LLM puede sobrescribir
ni competir con los valores reportados del XML: la separación `reported_*` frente a
extraído/derivado/calculado ([ADR-023](#adr-023), [ADR-041](#adr-041)) se mantiene.
No hay segundo parser fiscal, ni segunda persistencia, ni semántica fiscal específica
del correo.

**El enrutador clasifica solo representación física**: XML candidato, PDF, imagen,
cuerpo, otro. No determina validez de Hacienda, tratamiento fiscal, deducibilidad,
venta/compra ni dirección económica. La verdad del XML fiscal la determina C2.

**Representación antes que documento.** La evidencia preservada NO crea
automáticamente un ExternalDocument ([ADR-043](#adr-043) intacto). Primero evidencia;
después: extracción → hechos candidatos → **conciliación** → ¿documento conocido? SÍ →
se asocia como representación/soporte; NO → elegible para ExternalDocument. La
conciliación es obligatoria cuando la evidencia puede representar algo ya conocido;
para comprobantes CR la `Clave` reportada es la señal canónica de alta confianza;
emisor, número, fecha, moneda y total son señales posteriores que nunca se tratan como
verdad perfecta. **Invariante de duplicación:** tras demostrar la conciliación que
XML+PDF o PDF+cuerpo representan UN documento, las representaciones no se cuentan como
eventos económicos independientes — no se suman adjuntos.

**Idempotencia.** Mismo `provider_event_id` → reintento del proveedor → mismo intake,
reanudación, sin registro duplicado de entrega. `provider_event_id` nuevo → entrega
genuina nueva → intake nuevo. No se deduplica entre mensajes genuinos solo por huella
de contenido; la semántica de evidencia duplicada de C2 sigue siendo autoritativa para
el XML.

**Captura durable antes del ACK.** autenticar proveedor → resolver destinatario
activo → capturar idempotente y durablemente la evidencia mínima de intake → solo
entonces elegible para ACK exitoso. NO se congela si la interpretación ocurre antes o
después del ACK: **síncrono vs asíncrono queda ABIERTO para C4-B0**, porque exige
datos reales del proveedor y del hosting (timeout del webhook, contrato de reintentos,
estabilidad del event-id, vida de recuperación de adjuntos, límites de payload). Los
reintentos del proveedor son recuperación de entrega de un transporte externo, **no la
cola de aplicación de Tribuu**.

### Las tres capas de certeza

Tres conceptos de producto y de datos, separados y jamás mezclados:

1. **Evidencia monetaria identificada** — Tribuu identificó hechos monetarios en la
   evidencia (emisor = AWS, moneda = USD, total = 486.37). Prueba solo lo que se
   identificó; NO prueba que sea gasto de la empresa.
2. **Clasificación económica observada** — con suficiente contexto de empresa y de
   documento: gasto · ingreso · otro · sin resolver. Clasificación NO tributaria.
   Este ADR **no congela su mecanismo**.
3. **Tratamiento fiscal** — el Tax Engine determinista decide deducibilidad,
   crédito/débito de IVA, retenciones, periodo y demás consecuencias. `LLM ≠ Tax
   Engine`.

**Quién responde qué.** C5 (perfil fiscal de empresa) determina la RELACIÓN del
documento con la empresa — para XML CR: empresa = emisor → **EMITIDO / saliente**;
empresa = receptor → **RECIBIDO / entrante**; ninguna → ajeno; identidad insuficiente
→ sin resolver. C5 responde *«¿cómo se relaciona este documento con esta empresa?»*,
es **determinista y no se delega jamás a un LLM**, y NO congela emisor = venta/ingreso
ni receptor = compra/gasto.

La clasificación económica pertenece a **D3-A** (*«¿qué representa económicamente?»*),
y este ADR **deja abierto su mecanismo**: el diseño futuro de D3 podrá combinar reglas
deterministas, evidencia estructurada, inteligencia documental, clasificación asistida
por modelo/IA, confianza y revisión humana — en línea con lo que
[ADR-043](#adr-043) ya prevé para la clasificación de gasto con señales sugeridas
separadas de lo reportado. Un modelo PUEDE asistir la clasificación económica; lo que
no puede hacer es convertir en silencio la incertidumbre en un hecho.

Lo tributario pertenece a **C6** (*«¿qué significa tributariamente?»*): ahí el Tax
Engine determinista es la única autoridad, y ningún modelo decide deducibilidad,
crédito/débito de IVA, retenciones, periodo ni consecuencia fiscal alguna. `LLM ≠ Tax
Engine` significa exactamente eso — y **no** se reinterpreta como «LLM ≠ clasificación
económica».

**Multi-moneda:** sin conversión silenciosa. Hasta que exista una política FX
determinista aprobada, los totales se agrupan por moneda de origen; un LLM jamás
inventa una conversión.

**Inteligencia documental (D1-A/D2-A, futura):** extrae inicialmente solo hechos
básicos — emisor, número/referencia, fecha, moneda, subtotal e impuesto reportado
cuando estén claros, total — con los importes como cadenas exactas y **procedencia por
valor**, distinguiendo siempre: hecho reportado del XML estructurado · extracción
determinista · hecho derivado de OCR · candidato derivado de modelo · valor corregido
por humano. Sin conclusiones tributarias. Para los comprobantes CR, la semántica de
fechas reportadas sigue siendo la de [ADR-039](#adr-039).

**Dependencia del roadmap congelada:** C4 (Buzón + intake + preservación) → C5
(perfil fiscal + SOLO dirección de documento) → D1-A + D2-A (dominio mínimo externo +
inteligencia documental) → D3-A (clasificación económica mínima con revisión) → C6
(Tax Engine/IVA). Sin modelos de gasto intermedios desechables. **Superficies de
producto:** antes de D3-A, «Documentos con importes identificados» con totales por
moneda de origen — nunca «Gastos»; tras D3-A, «gasto observado» / «ingreso observado»
pueden ser seguros; la terminología tributaria espera a C6.

**Evolución del Buzón congelada:** (1) reenvío manual → (2) reenvío automático
configurado por el usuario → (3) el mismo buzón entregado directamente a proveedores →
(4) buzón conectado Gmail/Outlook futuro. Misma arquitectura de buzón en todas; sin
ninguna afirmación de domicilio fiscal legal.

### Consecuencias

- La evidencia empresarial aceptada sobrevive aunque Tribuu aún no la entienda; el
  producto puede decir «Recibido y guardado. Análisis automático pendiente» con la
  verdad de su lado.
- Un solo buzón durable acompaña a la empresa desde el reenvío manual hasta la entrega
  directa de proveedores, sin migraciones de dirección.
- La frontera máquina-a-máquina queda bajo la misma autoridad RLS que el resto del
  sistema, sin atajos de privilegio.
- Costes asumidos: almacenamiento de objetos nuevo que operar; retención temporal del
  cuerpo pendiente de una clasificación que aún no existe; y la decisión
  síncrono/asíncrono deliberadamente pospuesta hasta tener hechos del proveedor.

### Lo que este ADR NO decide

- Proveedor de correo entrante · vendor de almacenamiento de objetos · hosting ·
  DNS/dominio del buzón.
- Síncrono vs asíncrono · tecnología de cola, si llega a hacer falta.
- Esquema físico del `InboundEvidenceItem`.
- Duración de retención del cuerpo · retención del asunto · límites definitivos de
  payload.
- Política de conversión FX.
- Proveedor de OCR/modelo de inteligencia documental.
- Tratamiento tributario de documentos externos.

---

<a id="adr-047"></a>

## ADR-047 — Resend como proveedor inbound MVP y captura durable antes del ACK

**Estado:** ✅ Aceptada (Día 3, fase C4-B0) · **Criticidad: alta** ·
**Relacionada con:** [ADR-011](#adr-011) · [ADR-020](#adr-020) · [ADR-043](#adr-043) ·
[ADR-044](#adr-044) · [ADR-046](#adr-046)

### Contexto

C4-B0 ejecutó una evaluación experimental completa de Resend y Mailgun contra
un receptor estable desplegado para el spike, con correos reales: enrutamiento
por destinatario del sobre bajo reenvío real de Gmail, fidelidad byte a byte
de XML/PDF/imagen hasta 10.5 MB, cuerpo-como-evidencia, catch-all, cadencias
reales de reintento y recuperación tras más de dos horas de fallo, con los
códigos HTTP confirmados por los logs de los propios proveedores. La evidencia
íntegra vive en `docs/C4B0_PROVIDER_EVALUATION.md`; el receptor auditado vive
en el repositorio desechable `tribuu-spike-inbound`
(commit `5bed1b9b69368f720bdb05759c5c8325c42b3eb0`).

### Decisión — proveedor

**Resend es el proveedor de correo entrante PRINCIPAL del MVP. Mailgun queda
como fallback validado experimentalmente.** Los desempates que decidieron:
identidad de evento estable entre reintentos (`svix-id`), catch-all nativo del
dominio sin configuración, webhook de ~800 bytes constante incluso con
adjuntos de 10 MB, metadata limpia de adjunto-vs-inline, y menor complejidad
operativa — con la misma fidelidad byte-perfecta que Mailgun. La decisión
**puede revisarse** si cambian el precio, los límites o las necesidades
operativas (el precio es un hecho externo, no una medición del experimento).

### Decisión — flujo de ACK

**«Captura síncrona durable antes del ACK; procesamiento durable después del
ACK.»** Tubería conceptual congelada:

```
webhook Resend verificado
→ seleccionar recipient bajo el dominio controlado por Tribuu
→ resolver Buzón Tribuu ACTIVO → company_id
→ idempotencia
→ recuperar la representación/evidencia necesaria entregada por Resend
→ persistir intake/evidencia DURABLEMENTE en el ámbito de la empresa
→ COMMIT
→ devolver HTTP 2xx
→ procesamiento posterior DURABLE
```

Si la captura durable falla antes del commit: **no se responde 2xx** y se
permite el reintento del proveedor (ventana y cadencias medidas: Svix llegó a
re-entregar 2 h 20 min después; Mailgun escaló 10→10→15→30→60 min). Una vez
durable la evidencia, el parseo, la inteligencia documental, la conciliación,
la clasificación económica y el Tax Engine **no controlan el ACK**. Queda
prohibido usar `BackgroundTasks` de FastAPI como único mecanismo post-ACK: el
trabajo posterior debe tener estado durable y reanudarse tras un reinicio. No
se introduce Redis/SQS/etc. solo para recuperar transporte del proveedor en el
MVP; el mecanismo físico durable post-ACK queda abierto para C4-B.

### Decisión — idempotencia

**Resend:** la identidad de evento es el `svix-id`, observado ESTABLE a través
de todos los reintentos del mismo mensaje; se refuerza con procedencia/huella
donde corresponda.

**Mailgun (fallback):** `token`/`timestamp`/`signature` identifican el
INTENTO, no el mensaje — cada reintento llega con material de firma nuevo
(hecho medido: 6 intentos del mismo correo, 6 tokens distintos). **El token
jamás se usa como clave de idempotencia de mensaje.** La correlación de
mensaje se basa conceptualmente en `Message-Id` + recipient, reforzada con
huella de contenido. La estrategia por proveedor vive detrás de una frontera
pequeña (ADR-046), sin generalizarse a framework.

### Decisión — durabilidad

**El filesystem local del servicio NO es almacenamiento durable de
evidencia.** El experimento lo confirmó empíricamente: un reinicio por cambio
de variable de entorno borró el disco efímero del servicio. Toda evidencia
aceptada vive en almacenamiento durable (PostgreSQL + almacén de objetos,
según ADR-046) antes del ACK.

### Invariantes reafirmadas (ADR-046)

- Email Message ≠ Evidence Item ≠ Economic/Fiscal Document.
- La dirección entrante es SOLO capacidad de enrutamiento/entrega: **jamás
  autentica al remitente**.
- El tenant deriva únicamente de: evento verificado del proveedor →
  recipient bajo dominio controlado → Buzón Tribuu activo → `company_id`.
- `From`/`Reply-To`/subject/cuerpo permanecen NO confiables.
- El XML CR válido sigue yendo EXCLUSIVAMENTE por la ingesta C2: ningún
  segundo parser ni persistencia fiscal ([ADR-044](#adr-044)).
- `LLM ≠ Tax Engine`.

### Lo que este ADR NO decide

- El hosting de producción ([ADR-011](#adr-011) sigue abierto: el spike en
  Render es EVIDENCIA — funcionó estable, Starter soportó la carga probada y
  su disco es efímero — no una selección de producción).
- El vendor de almacenamiento de objetos, el DNS del dominio de producción,
  el TTL contractual de la recuperación de raw en Resend (hoy solo
  observado), el mecanismo físico del worker post-ACK, ni el esquema físico
  del canal (C4-B).

---

<a id="adr-048"></a>

## ADR-048 — Identidad de máquina inbound y Buzón Tribuu provider-agnostic

**Estado:** ✅ Aceptada (Día 3, fase C4-B1) · **Criticidad: alta** ·
**Relacionada con:** [ADR-012](#adr-012) · [ADR-015](#adr-015) · [ADR-017](#adr-017) ·
[ADR-020](#adr-020) · [ADR-044](#adr-044) · [ADR-046](#adr-046) · [ADR-047](#adr-047)

### Contexto

ADR-046/047 congelaron el modelo del canal —tenant por destinatario verificado,
captura durable antes del ACK, Resend como proveedor MVP— y delegaron a C4-B1
el mecanismo físico: cómo una entrega de correo, que no es una petición de
usuario, obtiene acceso company-scoped bajo RLS, y dónde vive el registro de
Buzones Tribuu.

### Decisión — registro provider-agnostic

`inbound.company_inboxes` representa el **Buzón Tribuu de la empresa, no un
buzón de un proveedor**: no tiene columna de proveedor; qué infraestructura
recibe el dominio es asunto de la capa de entrega (C4-B2/B3), y cambiar de
proveedor conserva la dirección. **Máximo UN buzón ACTIVO por empresa**
(índice parcial único por `company_id`). La **dirección es CANÓNICA y la
genera la base** (`prefijo-token@inbox.tribuu.ai`, columna GENERATED ALWAYS
STORED): una sola fuente de verdad, dominio controlado por construcción,
alfabetos verificados por CHECK — los CHECK validan FORMA y longitud; la
entropía (token base32 minúsculo, CSPRNG, 20 caracteres = 100 bits) la
garantizan el backend y sus tests, jamás un CHECK. El mapeo entre dominios de
ENTREGA (producción o pruebas de proveedor) y la dirección canónica pertenece
al adaptador de intake (C4-B2) con allowlist de configuración: el registro
nunca aprende proveedores.

El **ciclo de vida es monotónico**: `active → disabled`, jamás al revés; una
fila deshabilitada queda CONGELADA (trigger de guardia + grants de UPDATE por
columna); no existe DELETE físico. La **rotación** es `disable('rotated') +
insert nuevo` en una transacción, con linaje `rotated_from_id` protegido por
**FK compuesta tenant-safe** `(company_id, rotated_from_id) →
(company_id, id)`, verificación por trigger de que el predecesor está
deshabilitado por rotación, y unicidad de sucesor. La dirección es capability
de routing/submission y **nunca autentica al remitente**.

`created_by` es **procedencia real** vía `private.current_user_id()` —
SECURITY DEFINER que encapsula `auth.uid()`: ningún rol de datos obtiene
acceso nuevo a `auth.*`, el DEFAULT la puebla y el WITH CHECK del INSERT la
exige — el cliente no puede suministrar procedencia arbitraria, y un INSERT
sin identidad autenticada falla. El aprovisionamiento no-humano, si llega,
traerá su propio discriminador por ADR.

### Decisión — identidad de máquina

Rol **`inbound_backend`**: NOLOGIN, NOBYPASSRLS, NOINHERIT, asumible solo por
`app_backend` vía `SET LOCAL ROLE` (patrón ADR-020), con topología verificada
en la migración y en el arranque del backend. El contexto de empresa **se
resuelve EN la base**: `private.enter_inbound_context(recipient)` (SECURITY
DEFINER; EXECUTE solo para el rol máquina) es **fail-closed**: LIMPIA el
contexto al inicio de cada invocación y solo lo establece ante EXACTAMENTE un
buzón activo — cero coincidencias → NULL con contexto vacío; múltiples →
violación de invariante con error (cardinalidad por `INTO STRICT` con manejo
explícito de NO_DATA_FOUND/TOO_MANY_ROWS); un contexto previo jamás sobrevive
a una resolución fallida. **El llamante solo aporta el recipient** — nunca
company_id ni inbox_id — y el context manager del backend
(`inbound_transaction(pool, settings, recipient)`) tampoco los acepta en su
firma. Los lectores `private.inbound_inbox_id()` / `private.inbound_company_id()`
parsean el GUC defensivamente (vacío/malformado → NULL) y **revalidan el par
contra un buzón ACTIVO real en cada chequeo**: un GUC forjado o un buzón
rotado a mitad de transacción niegan en el acto. El rol máquina no tiene
SELECT del registro. El contexto es transaction-local (`is_local`) y muere en
COMMIT/ROLLBACK.

Los **grants fiscales de la máquina están medidos sobre el C2 real, por
columna donde la operación lo permite**: en `fiscal.source_documents`, UPDATE
solo sobre las nueve columnas de ciclo de vida/enlace (`parse_status,
parse_error, parse_attempt_count, parse_attempted_at,
schema_detection_status, detected_document_type, detected_schema_version,
electronic_document_id, updated_at`) — `raw_xml`, `content_sha256`,
`company_id`, `ingested_at`, `ingestion_source` e `id` quedan sin privilegio
de mutación; SELECT solo de las columnas que C2 lee; INSERT en documento e
hijas por el camino canónico (las cláusulas `RETURNING id` reales exigen
SELECT de `id` también en `document_lines`). Las políticas de máquina sobre
las tablas fiscales usan exclusivamente `company_id =
private.inbound_company_id()`, sin tocar las políticas de `fiscal_backend`.
**Ningún segundo parser ni persistencia fiscal: C2 sigue canónico.** Un evento
con N destinatarios Tribuu produce **N transacciones máquina independientes**;
un contexto jamás abarca dos empresas; identidad conceptual de idempotencia:
`(provider, provider_event_id, inbox_id)` (física en C4-B2/B3).

### Frontera de confianza

La autoridad para invocar `enter_inbound_context` descansa en el **trusted
backend tier** — la misma frontera que gobierna `request.jwt.claims`
(ADR-012): un `app_backend` comprometido es un compromiso de ese tier,
residual aceptado. Las defensas son la frontera de backend, los roles
restringidos, el contexto resuelto en base de datos, RLS, los grants mínimos
y el estado transaction-local. Sin `service_role`, sin usuario ficticio, sin
JWT de navegador para M2M, sin BYPASSRLS.

### Alternativas rechazadas

`SET LOCAL app.company_id = <uuid>` elegido por el llamante (sin ancla en
estado durable verificable) · envolver el camino fiscal en funciones SECURITY
DEFINER (duplicaría C2; prohibido por ADR-044/046) · `service_role`/BYPASSRLS
· usuario sintético con claims fabricadas · registro por proveedor con
unicidad `(company, provider)` (ataría la identidad del buzón a la
infraestructura y rompería la portabilidad de dirección) · dirección como
columna libre con CHECKs (tres fuentes de verdad divergibles) ·
`default auth.uid()` directo en la tabla (habría exigido ampliar el acceso de
`fiscal_backend` a `auth.*`) · rol humano nuevo `inbound_admin` (se reutiliza
`fiscal_backend`: el registro es parte de la frontera del canal fiscal) ·
exponer `inbound` por la Data API (frontera backend-only, como `fiscal`).

### Lo que este ADR NO decide

Adaptador Resend / verificación Svix / extracción y canonicalización del
recipient (C4-B2) · tablas de intake, RAW durable y vendor de objetos (C4-B3)
· ACK físico y worker durable post-ACK (C4-B3/B4) · constraint física de
idempotencia · hosting (ADR-011) · aprovisionamiento no-humano de buzones.

---

<a id="adr-049"></a>

## ADR-049 — Adaptador inbound de Resend, verificación Svix e identidad de evento

**Estado:** ✅ Aceptada (Día 3, fase C4-B2) · **Criticidad: alta** ·
**Relacionada con:** [ADR-046](#adr-046) · [ADR-047](#adr-047) · [ADR-048](#adr-048)

### Contexto

ADR-047 eligió Resend como proveedor entrante del MVP y ADR-048 construyó la
autorización de máquina y el registro de Buzones. C4-B2 añade la capa
específica de Resend que convierte un webhook en un evento interno enrutado al
tenant, SIN capturar evidencia durable todavía (eso es C4-B3).

### Decisión — verificación antes de confiar

La firma Svix se verifica sobre el **RAW body** con la librería oficial
(`svix==2.9.1`, dependencia de producción fijada) ANTES de parsear JSON. El
orden es inquebrantable: raw + cabeceras `svix-id`/`svix-timestamp`/
`svix-signature` → `Webhook(secret).verify(raw, headers)` → solo entonces
`json.loads` del MISMO raw. Nunca se parsea-y-reserializa para verificar. La
librería valida el HMAC y la ventana temporal (anti-replay). `RESEND_WEBHOOK_SECRET`
es configuración privada: jamás se registra, ni se devuelve en errores, ni
aparece en repr; su ausencia es fail-closed. No hay criptografía propia.

### Decisión — tipo de evento

C4-B2 solo procesa `email.received`. Un evento válidamente firmado de otro
tipo se reconoce y devuelve `IGNORED_EVENT_TYPE`: sin resolver tenant, sin
tocar contenido. No se implementa lógica para email.sent/delivered/bounced.

### Decisión — tres identidades que no se mezclan

- `provider_event_id` ← cabecera `svix-id` (identidad del EVENTO; base de la
  idempotencia durable futura de C4-B3).
- `provider_email_id` ← `data.email_id` (identidad del CORREO en Resend).
- `internet_message_id` ← `data.message_id` (Message-ID RFC; opcional en el
  contrato real, se transporta si viene).

El `svix-id` jamás se sustituye por `email_id` ni por `message_id`. C4-B2 NO
crea tabla ni constraint de idempotencia durable; solo transporta los tres
identificadores en el evento normalizado.

### Decisión — modelo neutral y autoridad de tenant

`NormalizedInboundEvent` es independiente de Resend. El tenant deriva
EXCLUSIVAMENTE de los recipients de ENTREGA del proveedor, que provienen SOLO de **`data.to`** —el campo PROVIDER-LEVEL de destinatarios
de entrega que Resend expone en el evento, distinto del header MIME `To:` del
mensaje crudo (ese header es contenido no confiable que C4-B3 verá en el RAW)—
resueltos contra el registro C4-B1. **`data.received_for`
NO es autoridad**: se conserva como señal de traza/informativa
(`trace_received_for`) y nunca alimenta `recipients`, ni abre transacción, ni
produce company/inbox — no se le llama «envelope recipient». **No hay fallback
de `to` hacia `received_for`**: si `data.to` falta o está vacío, el evento es
inválido (fail-closed). Motivo: `received_for` deriva de información de
trazabilidad/Received y no está suficientemente sustentado como autoridad de
sobre, en particular bajo forwarding; la evidencia C4-B0 solo muestra el caso
directo `to == received_for`, insuficiente para autorizar con `received_for`.
From, Reply-To, Subject, cuerpo, nombres y bytes de adjuntos, y el dominio del
remitente quedan marcados como NO CONFIABLES y nunca son autoridad. La
normalización de recipients es conservadora: recorta espacios, baja a
minúsculas SOLO el dominio (la parte local se respeta), rechaza vacío o
sintácticamente inválido, sin alias ni fuzzy matching.

### Decisión — enrutamiento multi-tenant aislado

Un evento con N recipients produce N resoluciones INDEPENDIENTES, una
`inbound_transaction()` por recipient: ninguna transacción abarca dos
empresas, y el contexto transaction-local de C4-B1 garantiza que un recipient
desconocido no herede el contexto del anterior. Desenlaces por recipient:
`ACTIVE_RESOLVED` (inbox+company), `UNKNOWN_RECIPIENT` e `INVALID_RECIPIENT`.
Desconocido y deshabilitado colapsan a `UNKNOWN_RECIPIENT` hacia fuera para no
permitir enumerar qué buzones existen; la distinción fina vive solo en logs
internos. Fail-closed: sin buzón activo no se abre trabajo. La autoridad sigue
siendo C4-B1; el router no acepta company_id ni inbox_id de ninguna fuente
externa.

### Forwarding futuro (restricción)

La política actual es terminante: **`data.to` → candidatos de routing;
`received_for` → metadata de traza; sin fallback**. Si en el futuro la
evidencia de forwarding exigiera cambiar esta regla, NO podrá relajarse en
silencio: requerirá una NUEVA decisión arquitectónica (ADR propio), deberá
preservar el aislamiento de tenant, y deberá apoyarse en evidencia real /
contrato del proveedor más nuevas regresiones de seguridad. Hasta entonces,
`received_for` nunca autoriza.

### Lo que este ADR NO decide / NO hace (frontera C4-B3)

C4-B2 NO descarga adjuntos (solo metadata declarada), NO consulta la API de
Resend por bytes, NO guarda RAW/XML/PDF/imágenes, NO usa object storage, NO
llama a C2 (`capture_source_document`/`process_source_document`), parser,
persistencia, Tax Engine, clasificador, OCR ni LLM. **No añade endpoint HTTP
productivo**: el adaptador es función pura importable; C4-B3 lo conectará a la
captura durable y recién entonces activará el endpoint real con ACK. No se usa
`BackgroundTasks` como sustituto de captura durable. Sin `service_role`, sin
JWT de navegador, sin usuario/membresía ficticios. La idempotencia física, el
RAW durable, los adjuntos y el ACK pertenecen a C4-B3.

---

<a id="adr-050"></a>

## ADR-050 — Abstracción EvidenceBlob: BYTEA inicial y migración planificada a Object Storage

**Estado:** 📝 Propuesta (DRAFT) — pendiente de revisión/aprobación · **Criticidad: alta**

> **Alcance del estado.** La evolución CONCEPTUAL de almacenamiento
> `postgres_bytea` (MVP) → `object_storage` (futuro), junto con su invariante de
> identidad y la deuda técnica «Evidence Blob Object Storage migration», está
> **aprobada**. El resto del ADR —diseño FÍSICO de C4-B3: captura durable
> pre-ACK, RAW RFC822, `EvidenceBlob`, provider events, email messages,
> idempotencia, conflictos, tenancy, lifecycle y semántica de errores— está
> **PROPUESTO y aún no revisado/aprobado**. Por tanto ADR-050 **no es ACCEPTED
> todavía**; pasará a ✅ cuando el diseño físico se revise y se acepte.


**Relacionada con:** [ADR-044](#adr-044) · [ADR-046](#adr-046) · [ADR-047](#adr-047) ·
[ADR-048](#adr-048) · [ADR-049](#adr-049)

### Contexto

C4-B3 capturará evidencia inbound durable antes del ACK (ADR-047). El backend
durable INICIAL del MVP/pilotos será **PostgreSQL BYTEA**, porque permite que
metadata, bytes e idempotencia queden bajo UNA sola transacción PostgreSQL
antes de responder 2xx — la atomicidad pre-ACK que ADR-047 exige. Esa elección
**no es la arquitectura final para escala**: los bytes pesados deberán vivir en
Object Storage antes de escala comercial significativa. Para que esa migración
futura no obligue a reescribir C4-B4, C2 ni los consumidores de evidencia, la
abstracción debe desacoplarse DESDE AHORA.

### Decisión — desacoplar identidad lógica de ubicación física

Se introduce la abstracción conceptual **`EvidenceBlob`**: separa la IDENTIDAD
LÓGICA de una evidencia de la UBICACIÓN FÍSICA de sus bytes. Los consumidores
posteriores (C4-B4, C2, inteligencia documental, conciliación) dependen del
`EvidenceBlob`, **nunca directamente de una columna BYTEA**.

```text
EmailMessage
    ↓ raw_blob_id
EvidenceBlob
    ├── id
    ├── company_id
    ├── sha256
    ├── size_bytes
    ├── storage_backend          (MVP: 'postgres_bytea'; futuro: 'object_storage')
    ├── bytes en PostgreSQL / locator inicial
    ├── object key/locator futuro
    ├── created_at
    └── provenance
```

**MVP** — `storage_backend = 'postgres_bytea'`: los bytes viven en PostgreSQL,
atomicidad pre-ACK garantizada. **Target futuro** — `storage_backend =
'object_storage'`: los bytes pesados en Object Storage y PostgreSQL conserva
blob/evidence id, company_id, SHA-256, size, provenance, storage_backend,
object key/locator, lifecycle/status y las relaciones con EmailMessage/Evento
— es decir, PostgreSQL permanece como ÍNDICE y fuente de verdad de metadata,
no de bytes.

El diseño físico EXACTO (nombres de tablas/columnas, tipos, constraints) se
decide en C4-B3, pero debe preservar esta abstracción.

### Invariante

**Mover una evidencia entre backends NO cambia su identidad.** La identidad y
la verificación dependen de `blob/evidence id` + `SHA-256` + `size/provenance`,
jamás de la ubicación física. Un consumidor que pida un `EvidenceBlob` por su
id obtiene los mismos bytes verificables con independencia del backend.

### Migración futura segura (mínimo obligatorio)

1. leer el BYTEA original;
2. verificar su SHA-256;
3. subir a Object Storage;
4. recuperar/verificar el objeto almacenado;
5. comprobar mismo SHA-256 y tamaño;
6. actualizar de forma transaccional el locator/backend en PostgreSQL;
7. solo tras verificación exitosa, permitir eliminar el BYTEA;
8. nunca perder la única copia durable durante la transición.

### Deuda técnica planificada — «Evidence Blob Object Storage migration»

> C4-B3 usa PostgreSQL BYTEA como backend durable inicial para obtener
> atomicidad pre-ACK durante MVP/pilotos. Esta elección no es permanente. Antes
> de escala comercial significativa, los blobs de evidencia deberán migrarse a
> Object Storage. PostgreSQL permanecerá como índice y fuente de verdad de
> metadata, provenance, hash, tenant y ubicación lógica.

**`PostgreSQL BYTEA MUST NOT be treated as the permanent scaled storage backend.`**

### Lo que este ADR NO decide / NO hace

No implementa Object Storage en C4-B3 · no introduce credenciales de S3 /
Storage ahora · no fija el esquema físico del `EvidenceBlob` (eso es C4-B3) ·
no toca C2, Tax Engine ni consumidores existentes. Solo fija la abstracción
para que la migración futura no requiera reescribir C4-B4, C2 ni los
consumidores de evidencia.
