# GLOSSARY — Vocabulario compartido del proyecto

> **Por qué existe.** Un proyecto tributario multilingüe (documentación en español,
> código en inglés) con cuatro componentes de fronteras estrictas necesita que todos
> —personas y agentes— usen las mismas palabras con el mismo significado. Fijarlo hoy
> es barato; imponerlo cuando ya existen tres módulos que llaman "factura" a cosas
> distintas, no.
>
> **Alcance.** Este documento define **vocabulario de proyecto**, no términos jurídicos.
> Las definiciones legales formales requieren fuente oficial verificada y se
> incorporarán en la Fase 5 (Knowledge Base), con fuente, fecha y vigencia.
> Ver [AI_INSTRUCTIONS.md](../AI_INSTRUCTIONS.md), Regla 2.

---

## 1. Componentes del sistema

### Tax Data Layer
Capa que almacena los hechos fiscales del contribuyente ya normalizados. **La verdad
observada.** No calcula ni interpreta normativa.
→ [ARCHITECTURE.md §2.1](../ARCHITECTURE.md)

### Tax Engine
Motor de cálculo tributario determinista y versionado. Paquete Python independiente,
sin acceso a base de datos, red, LLM ni FastAPI. **La autoridad sobre cualquier cifra
calculada.**
→ [ARCHITECTURE.md §8](../ARCHITECTURE.md) · [ADR-005](DECISIONS.md#adr-005)

### Knowledge Base
Repositorio de normativa tributaria estructurada, con fuente y vigencia. Conocimiento
**compartido** del sistema, no aislado por empresa. **La autoridad sobre cualquier
norma citada.**
→ [ARCHITECTURE.md §9](../ARCHITECTURE.md) · [ADR-009](DECISIONS.md#adr-009)

### AI Agent
Capa de interacción conversacional. Interpreta preguntas, selecciona tools, orquesta y
explica. **Sin autoridad sobre cifras ni sobre normas.**
→ [ARCHITECTURE.md §10](../ARCHITECTURE.md)

### Tool
Función de un conjunto **cerrado y explícito** mediante la cual el AI Agent accede a
datos, normativa o cálculos. Con contrato definido, sujeta a autorización, auditable y
siempre dentro del tenant del usuario. **No existe una tool de consulta libre.**

---

## 2. Datos fiscales

### Contribuyente
Persona física o jurídica con obligaciones tributarias. En este sistema, el titular de
los datos fiscales. *(Definición operativa del proyecto; la definición legal requiere
fuente verificada.)*

### Empresa · Tenant
Unidad de aislamiento del sistema. Todo dato fiscal pertenece a exactamente una empresa.
Un usuario puede tener acceso a una o varias. **Ninguna consulta, endpoint o tool puede
diseñarse asumiendo un único tenant.**

### Comprobante electrónico
Documento fiscal electrónico emitido por un contribuyente. Es la **fuente de datos
primaria** del sistema, no un formato de importación temporal. *(Sus tipos y versiones
concretas no se enumeran aquí: requieren fuente oficial verificada.)*

### Raw XML
El documento XML tal y como entra al sistema, **sin transformar**. Se conserva íntegro
e inmutable, con hash de integridad.
→ [ADR-007](DECISIONS.md#adr-007)

### Source DTO
Representación fiel del documento externo, previa a cualquier normalización.
**El único lugar del sistema donde vive el conocimiento del formato externo.** Aislarlo
aquí es lo que limita el impacto de un cambio de formato a un solo punto.
→ [ADR-006](DECISIONS.md#adr-006)

### Normalizer
Componente que traduce del `Source DTO` al modelo interno. Es la **capa anticorrupción**
del sistema: impide que la estructura de un formato externo contamine el modelo propio.

### InternalInvoice
Modelo **propio** de comprobante, desacoplado de versiones y proveedores externos.
**No es una copia de la estructura del XML.** Conserva siempre trazabilidad hacia su
documento original.
→ [ADR-006](DECISIONS.md#adr-006) · [ADR-007](DECISIONS.md#adr-007)

### Perfil fiscal
Conjunto de características fiscales de una empresa que condicionan cómo se interpretan
y calculan sus obligaciones. *(Su contenido concreto requiere fuente verificada.)*

---

## 3. Distinciones críticas

> Las tres distinciones de esta sección son las que más fácilmente se pierden al
> implementar y las más costosas de recuperar después.

### `reported_*` vs `computed_*`

| Prefijo | Origen | Significa |
|---|---|---|
| `reported_*` | El comprobante o documento fuente | Lo que **declaró** el emisor |
| `computed_*` | Nuestro Tax Engine | Lo que **calcula** nuestro motor |

**Nunca se fusionan en un mismo campo.** Su discrepancia no es un error a ocultar: es
una **señal de producto**. Detectar que un comprobante declara un impuesto distinto del
que corresponde es exactamente lo que el contribuyente necesita saber.
→ [ADR-003](DECISIONS.md#adr-003)

### Trazabilidad vs Auditoría

| | Responde a | Ejemplo |
|---|---|---|
| **Trazabilidad del dato** | ¿De dónde viene este valor? | Este importe procede de la línea N del documento X |
| **Auditoría de operaciones** | ¿Quién hizo qué y cuándo? | El usuario U ingirió el documento X el día D |

Ambas son requisitos desde el diseño. No son lo mismo y no se sustituyen.

### Determinista vs Probabilístico

| | Determinista | Probabilístico |
|---|---|---|
| Componentes | Tax Data Layer, Tax Engine, Knowledge Base | AI Agent |
| Autoridad | Sí | **No** |
| Reproducible | Siempre | No necesariamente |

Es la traducción operativa del principio rector `LLM ≠ Tax Engine`.

---

## 4. Cálculo tributario

### Regla tributaria
Unidad de conocimiento normativo aplicable a un cálculo. **Debe poder indicar siempre:**

```
fuente · documento o artículo · fecha · vigencia · versión
```

Una regla sin fuente verificada no entra al sistema.
→ [AI_INSTRUCTIONS.md, Regla 5](../AI_INSTRUCTIONS.md)

### `as_of_date`
Fecha que determina **qué versión de una regla resulta aplicable** a un cálculo.
El motor nunca calcula "con las reglas actuales": calcula con las vigentes en la fecha
correspondiente al hecho.
→ [ADR-004](DECISIONS.md#adr-004)

### Vigencia
Período durante el cual una regla o norma es aplicable. Normativa derogada debe ser
**distinguible** de normativa vigente, no eliminada: los cálculos históricos siguen
necesitándola.

### Versión de regla
Identificador de la variante concreta de una regla aplicada en un cálculo. **Se persiste
junto al resultado**, y es lo que permite reproducir el cálculo años después.

### Reproducibilidad
Propiedad central del sistema:

> Mismos datos + misma `as_of_date` + misma versión de regla ⇒ **mismo resultado, siempre.**

Sin ella, el sistema no es auditable y el producto pierde su razón de ser.

### Desglose
Detalle paso a paso de cómo se produjo un resultado. **Forma parte del producto**, no es
un extra de depuración: una cifra sin desglose es un producto incompleto.

### Precisión decimal exacta
Representación de importes monetarios sin errores de coma flotante. Se conserva la
moneda original y la información de conversión cuando aplique. Las reglas de redondeo
pertenecen a la regla tributaria, no al código de utilidad.
→ [ADR-008](DECISIONS.md#adr-008)

---

## 5. Seguridad

### Multi-tenancy
Arquitectura en la que múltiples empresas coexisten en el mismo sistema con
**aislamiento estricto** entre ellas.

### Row Level Security (RLS)
Mecanismo de PostgreSQL que restringe qué filas puede ver o modificar un solicitante.
**Es el mecanismo de aislamiento del sistema**: el aislamiento no puede depender
exclusivamente de que el código recuerde filtrar por empresa.
→ [ADR-002](DECISIONS.md#adr-002)

### Clave privilegiada · `service_role`
Credencial que **anula RLS por completo**. No debe ser el mecanismo habitual de acceso a
datos fiscales de usuarios. Los usos legítimos (operaciones administrativas, jobs
internos) son **caminos separados**: controlados, server-side y auditables.
→ [ADR-002](DECISIONS.md#adr-002)

### Camino único
Principio por el cual los datos fiscales pasan normalmente por FastAPI. El acceso
directo del frontend a Supabase se limita a autenticación y, cuando corresponda,
Storage bajo políticas explícitas.
→ [ADR-001](DECISIONS.md#adr-001)

### Fixture anonimizado
Documento de prueba derivado de un comprobante real del que se han eliminado los datos
identificativos. **Es lo único que puede versionarse** en el repositorio; los documentos
fiscales reales nunca.
→ [AI_INSTRUCTIONS.md, Regla 6](../AI_INSTRUCTIONS.md)

---

## 6. Funcionalidades

### Dashboard
Vista de la situación fiscal observada. **En Fase 3 muestra exclusivamente valores
`reported_*`**, y debe indicarlo visualmente: todavía no existe Tax Engine.

### RAG
*Retrieval-Augmented Generation.* Recuperación de fragmentos de la Knowledge Base para
fundamentar una respuesta, **con cita obligatoria**. Aporta contexto normativo, **no
cifras**: si la respuesta requiere un número, ese número procede del Tax Engine.

### Radar fiscal
Detección proactiva de riesgos, inconsistencias y datos faltantes (Fase 7). Toda
detección debe ser explicable y trazable hasta los datos que la originaron.

### Respuesta estructurada
Forma que adopta toda respuesta del sistema:

```
EXPLICACIÓN + CÁLCULO + FUENTES + EVIDENCIA + ADVERTENCIAS
```

Un chatbot entrega solo el primer elemento. **El valor está en los cuatro restantes.**

---

## 7. Términos de proceso

### Fase
Etapa del [ROADMAP.md](../ROADMAP.md). Numeradas de 0 a 10. No se adelantan.

### ADR
*Architecture Decision Record.* Registro de una decisión de arquitectura en
[DECISIONS.md](DECISIONS.md). Las decisiones no se borran: se marcan como sustituidas.

### Hueco declarado
Punto donde falta información no verificada, **marcado explícitamente** en lugar de
rellenado con un valor plausible.

> Un documento con huecos honestos es preferible a uno con cifras plausibles e
> inventadas. En materia tributaria, una respuesta plausible y errónea es peor que
> ninguna respuesta.

### Capa anticorrupción
Frontera que traduce entre un modelo externo y el modelo propio, impidiendo que la
estructura externa contamine el interior del sistema. En este proyecto: el `Normalizer`.

---

## 8. Convención de idioma

| | Idioma |
|---|---|
| Documentación explicativa | Español |
| Código, identificadores, variables, funciones, clases | Inglés |
| Nombres de archivo | Inglés |
| Mensajes de commit | Inglés |

Por eso este glosario define conceptos en español pero nombra los identificadores en
inglés (`reported_*`, `as_of_date`, `InternalInvoice`).
→ [ADR-010](DECISIONS.md#adr-010)
