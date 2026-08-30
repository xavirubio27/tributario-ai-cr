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

**Estado:** ✅ Aceptada (Día 3, fase E2)

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
