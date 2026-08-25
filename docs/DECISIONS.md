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
