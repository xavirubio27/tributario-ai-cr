# PRODUCT SPEC — Asistente Tributario IA (Costa Rica)

> **Estado:** Día 1 — documento fundacional.
> Define *qué* construimos y *por qué*. La materialización técnica está en
> [ARCHITECTURE.md](ARCHITECTURE.md); la secuencia en [ROADMAP.md](ROADMAP.md).

---

## 1. Visión

**Inteligencia tributaria basada en datos reales del contribuyente.**

Esa frase es la propuesta completa del producto y conviene leerla palabra por palabra:

- **Inteligencia** — no registro. No sustituimos al sistema contable ni al de
  facturación: razonamos sobre lo que ellos producen.
- **Tributaria** — dominio especializado, con normativa citable y cálculo
  determinista. No es asistencia genérica.
- **Datos reales del contribuyente** — la diferencia decisiva. No respondemos
  preguntas teóricas sobre el sistema tributario costarricense: respondemos
  preguntas sobre **la situación fiscal concreta de esta empresa**.

A largo plazo, la empresa debería poder abrir el producto y preguntar en lenguaje
natural cualquier cosa sobre su realidad fiscal, y recibir una respuesta con cifra,
desglose, fuente normativa y advertencias.

### Lo que hace la respuesta valiosa

Una respuesta del sistema no es un texto. Es una estructura:

```
RESULTADO
   ├── EXPLICACIÓN      en lenguaje natural
   ├── CÁLCULO          desglose determinista, paso a paso
   ├── FUENTES          normativa con documento, fecha y vigencia
   ├── EVIDENCIA        los datos concretos usados y su origen
   └── ADVERTENCIAS     supuestos, datos faltantes, riesgos detectados
```

Un chatbot entrega el primer elemento. El valor está en los cuatro restantes.

---

## 2. Usuario objetivo

### Usuario primario — la PYME formalizada costarricense

Empresa que ya emite comprobantes electrónicos, ya tiene un sistema de facturación
y ya cumple sus obligaciones, pero:

- descubre cuánto debe pagar tarde, cuando ya no puede reaccionar;
- no entiende de dónde sale la cifra;
- no sabe si hay errores en sus comprobantes hasta que alguien los encuentra;
- depende de un tercero para cualquier pregunta fiscal, por simple que sea.

El decisor suele ser la persona propietaria o la responsable administrativa.
No es un perfil técnico ni necesariamente contable.

### Usuario secundario — contadores y despachos

Profesionales que gestionan múltiples clientes y necesitan revisar, detectar
inconsistencias y justificar cifras con respaldo normativo. Para este perfil el
producto es una herramienta de productividad y de reducción de riesgo, y el
requisito de **explicabilidad** pasa a ser el atributo principal: no adoptarán una
herramienta cuyos números no puedan defender.

### Quién NO es el usuario objetivo (por ahora)

- Grandes corporaciones con departamento fiscal propio y ERP consolidado.
- Personas físicas sin actividad económica.
- Empresas fuera de Costa Rica — la especialización jurisdiccional es deliberada.

---

## 3. El problema

### 3.1. El dato fiscal existe, pero no es utilizable

Toda la información necesaria para conocer la situación tributaria de una empresa
ya existe: está en sus comprobantes electrónicos. Pero está dispersa, en formato
técnico, sin consolidar y sin interpretación. Es un dato **presente pero mudo**.

### 3.2. Las cifras llegan sin explicación

El contribuyente recibe un importe a pagar. No recibe el razonamiento. Cuando quiere
entenderlo, la única vía es preguntar a una persona.

### 3.3. Los errores se detectan tarde o no se detectan

Comprobantes mal emitidos, datos incompletos, secuencias con huecos, clasificaciones
incorrectas. Son problemas detectables mecánicamente que hoy sobreviven hasta que
alguien los busca a mano — si alguien los busca.

### 3.4. La normativa es inaccesible en el momento de la duda

La pregunta surge en un contexto concreto ("¿esta compra da derecho a crédito?"),
pero la norma está escrita en abstracto y en otro lugar.

### 3.5. Por qué un LLM genérico no resuelve esto

Un modelo de lenguaje general:

- no conoce los datos de la empresa;
- no calcula de forma determinista ni reproducible;
- no distingue normativa vigente de derogada;
- puede producir una cifra plausible y equivocada, sin señal de aviso.

**En materia tributaria, una respuesta plausible y errónea es peor que ninguna respuesta.**
Esta afirmación es el fundamento de toda la arquitectura del producto.

---

## 4. Propuesta de valor

> Conocer su situación tributaria real, entender cómo se calculó y saber qué norma
> la respalda — de forma continua, no al cierre.

### Los cuatro pilares

**1. Datos reales del contribuyente.**
Partimos de sus comprobantes electrónicos, normalizados a un modelo interno propio,
con trazabilidad hasta el documento original.

**2. Cálculo determinista.**
El Tax Engine produce cifras reproducibles: mismos datos + misma fecha de
aplicabilidad + misma versión de regla ⇒ mismo resultado, hoy y dentro de años.

**3. Normativa verificable.**
Cada regla lleva fuente, documento o artículo, fecha, vigencia y versión. Sin fuente
verificada, no entra al sistema.

**4. IA como capa de interacción.**
El modelo traduce la intención del usuario a consultas y cálculos, y traduce los
resultados a lenguaje comprensible. **No es la autoridad sobre la cifra.**

### Por qué esta combinación es defendible

Cada pilar por separado es replicable. Juntos producen algo que ni un software
contable ni un chatbot pueden ofrecer: **una respuesta fiscal específica de la
empresa, reproducible y auditable**. Si un contador pregunta "¿de dónde sale este
número?", el sistema puede responder hasta el comprobante concreto y hasta el
artículo concreto.

---

## 5. MVP

El MVP **no es el asistente conversacional**. El asistente es la última capa que se
apoya en todo lo demás.

El MVP es la **base de datos fiscal confiable** que hace posible al asistente.

### Objetivo del primer hito

```
Un XML real de comprobante electrónico costarricense entra al sistema.
        ↓
El sistema lo interpreta correctamente.
        ↓
Lo transforma a nuestro modelo interno.
        ↓
Lo almacena correctamente en PostgreSQL, aislado por empresa.
        ↓
El usuario puede visualizar la factura en la interfaz.
```

### Pipeline conceptual de ingesta

```
Raw XML  →  Source DTO  →  Validation  →  Normalizer  →  InternalInvoice
```

`InternalInvoice` es un modelo **propio**, no una copia de la estructura del formato
externo, y está desacoplado de versiones y proveedores. (Ver
[docs/DECISIONS.md](docs/DECISIONS.md), ADR-006.)

### Por qué empezar por XML

Decisión deliberada, con tres razones:

1. **Independencia** — el XML ya está en poder del contribuyente. No dependemos de
   ninguna integración de terceros en la fase más frágil del proyecto.
2. **Calidad del dato** — es un documento firmado y estructurado, no un extracto
   ni una conciliación aproximada.
3. **Riesgo acotado** — permite construir y validar todo el pipeline de datos antes
   de asumir dependencias externas.

### Fuera del alcance del MVP

Explícitamente excluido por ahora: integración con Hacienda, integración bancaria,
Alegra, Facturele, impuesto sobre la renta, AI Agent, tool calling, RAG, Knowledge
Base, monetización.

---

## 6. Funcionalidades previstas

Enumeradas por capa de madurez. Ninguna está implementada hoy.

### Capa 1 — Datos fiscales (fundación)

- Ingesta de comprobantes electrónicos en XML
- Validación estructural y de contenido
- Normalización a `InternalInvoice`
- Conservación íntegra e inmutable del documento original
- Trazabilidad del dato normalizado hacia su documento fuente
- Perfil fiscal de la empresa
- Aislamiento multiempresa

### Capa 2 — Visibilidad

- Listado y consulta de comprobantes
- Dashboard de situación fiscal
- Consolidados de ventas y compras
- **Valores `reported_*`** — provenientes del documento fuente, siempre etiquetados
  como tales mientras no exista Tax Engine

### Capa 3 — Cálculo

- Tax Engine de IVA, determinista y versionado
- **Valores `computed_*`** — producidos por nuestro motor
- Desglose paso a paso de cada cálculo
- Contraste `reported_*` vs `computed_*` como fuente de detección de errores
- Reproducción histórica de cualquier cálculo mediante `as_of_date` y versión de regla

### Capa 4 — Conocimiento

- Knowledge Base de normativa tributaria con fuente y vigencia
- Búsqueda semántica sobre normativa (pgvector)
- RAG con citación obligatoria de fuentes

### Capa 5 — Asistente

- AI Agent con acceso exclusivo mediante tools controladas
- Respuestas con explicación, cálculo, fuentes, evidencia y advertencias
- Abstracción de proveedor LLM

Tools previstas (**no implementadas hoy**):
`get_company_profile()` · `get_sales()` · `get_purchases()` · `get_invoice()` ·
`calculate_iva()` · `get_tax_rule()` · `search_tax_knowledge()` ·
`find_missing_invoices()` · `find_risks()`

### Capa 6 — Anticipación

- Radar fiscal: detección proactiva de riesgos e inconsistencias
- Alertas sobre datos faltantes o anómalos
- Proyecciones sobre datos observados

---

## 7. Diferenciación

| | Software contable | Facturación electrónica | Chatbot fiscal | **Este producto** |
|---|---|---|---|---|
| Conoce los datos de la empresa | ✅ | ✅ | ❌ | ✅ |
| Explica el cálculo | ❌ | ❌ | ⚠️ genérico | ✅ |
| Cita normativa con vigencia | ❌ | ❌ | ⚠️ sin garantía | ✅ |
| Cálculo determinista y reproducible | ✅ | ✅ | ❌ | ✅ |
| Interacción en lenguaje natural | ❌ | ❌ | ✅ | ✅ |
| Detección proactiva de riesgos | ❌ | ❌ | ❌ | ✅ |

### Los dos vectores reales de diferenciación

**Frente al software tradicional:** la interacción. Los datos ya existen en esos
sistemas, pero preguntarles algo exige saber dónde mirar.

**Frente a las herramientas de IA genéricas:** la fiabilidad. Un chatbot puede
sonar convincente; no puede garantizar que la cifra sea correcta, ni que la norma
citada esté vigente, ni que el resultado sea reproducible mañana.

**Nuestro foso defensivo es la arquitectura, no el modelo.** La separación
LLM ≠ Tax Engine, la trazabilidad del dato y el versionado temporal de reglas no se
replican cambiando de proveedor de IA.

### Especialización jurisdiccional

Costa Rica primero, y a fondo. Un producto tributario superficial en veinte países
no es utilizable en ninguno. La especialización es una ventaja competitiva, no una
limitación.

---

## 8. Principios de producto

**1. Nunca inventar.**
Ni legislación, ni tasas, ni APIs, ni endpoints, ni estructuras de datos externas.
Lo no verificado se declara explícitamente como no verificado.

**2. El LLM no calcula impuestos.**
Interpreta, orquesta y explica. La cifra viene del Tax Engine.

**3. Todo resultado debe ser reproducible.**
Mismos datos + misma `as_of_date` + misma versión de regla ⇒ mismo resultado, siempre.

**4. Todo dato fiscal conserva su origen.**
Debe poder rastrearse hasta el documento del que proviene.

**5. `reported` nunca se confunde con `computed`.**
Lo que dice el documento fuente y lo que calcula nuestro motor son cosas distintas.
Su discrepancia es información valiosa, no un error a ocultar.

**6. Preferimos un hueco honesto a una respuesta plausible.**
Ante datos insuficientes, el sistema lo dice. No estima en silencio.

**7. La explicación es parte del producto.**
Una cifra sin desglose es un producto incompleto.

**8. Aislamiento por diseño.**
Los datos de una empresa jamás son accesibles desde otra.

**9. Construcción incremental.**
Cada capa funciona y se prueba antes de construir la siguiente.

---

## 9. Roadmap conceptual

Secuencia lógica, sin fechas. Detalle en [ROADMAP.md](ROADMAP.md).

```
XML → PARSER → VALIDACIÓN → NORMALIZACIÓN → INTERNAL INVOICE
  → POSTGRESQL → PERFIL FISCAL → DASHBOARD → TAX ENGINE IVA
  → KNOWLEDGE BASE → RAG → AI EXPERT → RADAR FISCAL → MONETIZACIÓN
```

| Fase | Nombre | Resultado |
|---|---|---|
| 0 | Project foundation | Repositorio, documentación, reglas |
| 1 | Infrastructure / Auth / Company | Multiempresa con aislamiento real |
| 2 | XML invoices | Pipeline de ingesta completo |
| 3 | Dashboard | Visibilidad sobre valores `reported_*` |
| 4 | Tax Engine IVA | Primer cálculo determinista `computed_*` |
| 5 | Tax Knowledge Base + RAG | Normativa verificable y consultable |
| 6 | AI Expert | Asistente con tools controladas |
| 7 | Fiscal Radar | Detección proactiva de riesgos |
| 8 | Monetization | Modelo de negocio |
| 9 | Integrations | Fuentes de datos adicionales |
| 10 | Advanced tax capabilities | Ampliación del dominio tributario |

La secuencia importa: **cada fase depende de la confiabilidad de la anterior**. El
asistente de la Fase 6 solo vale lo que valgan los datos de la Fase 2 y el motor de
la Fase 4.

---

## 10. Cómo se mide el éxito

Criterios cualitativos para el MVP, previos a cualquier métrica de negocio:

1. Un XML real entra y se visualiza correctamente, con su dato normalizado
   trazable hasta el documento original.
2. Ninguna empresa puede ver datos de otra — verificado con tests, no por revisión.
3. Todo cálculo tributario tiene tests y es reproducible históricamente.
4. Toda regla tributaria tiene fuente, vigencia y versión.
5. El usuario entiende de dónde sale cada cifra sin preguntar a nadie.
