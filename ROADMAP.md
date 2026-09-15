# ROADMAP — Tribuu.ai (Costa Rica)

> **Sin fechas.** Este roadmap describe una **secuencia**, no un calendario.
> El desarrollo es incremental: cada etapa se apoya en la confiabilidad de la anterior.
>
> **El estado vigente y medido está en [docs/PROJECT_STATE.md](docs/PROJECT_STATE.md).**
> Este documento describe la DIRECCIÓN del producto; aquel describe lo que existe.
> Ante cualquier discrepancia, manda `PROJECT_STATE`.

---

## Qué existe hoy, y qué no

Esta separación es deliberada y debe leerse antes que cualquier tabla de este archivo:
un roadmap que suena a producto terminado es un roadmap que engaña.

**IMPLEMENTADO** — tubería de documentos fiscales costarricenses en el backend: parser
del comprobante electrónico, validación contra los esquemas oficiales, persistencia
normalizada, el endpoint HTTP de subida manual, la interfaz de subida en el workspace
de empresa y la bandeja de documentos con estados operativos, paginación y contadores.

**NO IMPLEMENTADO** — dominio de documentos externos, inteligencia sobre PDF o imagen,
clasificación de gasto, ingesta por correo, calendario fiscal, Tax Engine de IVA,
WhatsApp, motor de notificaciones y radar normativo. **Nada de lo anterior existe
todavía**, por muy detallado que aparezca aquí.

---

## Las dos familias de documentos

Una empresa costarricense real gasta en dos mundos a la vez, y Tribuu.ai tendrá que
cubrir ambos:

```
Comprobante electrónico CR  ──▶  Dominio Fiscal
(XML de Hacienda)                parser determinista + XSD

Documento externo           ──▶  Dominio de Documentos Externos
(PDF, imagen, factura no                    (por diseñar)
 costarricense, evidencia
 derivada de un correo)
```

Proveedores de transporte, SaaS, servicios en la nube, plataformas de publicidad,
hoteles, aerolíneas, servicios profesionales y proveedores internacionales producen
gasto real que hoy el sistema no sabe representar. Los ejemplos son **ilustrativos**:
no se codifica lógica específica de ningún proveedor.

**La separación es obligatoria** ([ADR-043](docs/DECISIONS.md#adr-043)). Un documento
externo **nunca** se fuerza dentro del dominio fiscal costarricense. No se sintetiza
`Clave`, ni consecutivo de Hacienda, ni `CodigoActividad`, ni CABYS reportado, ni
aceptación de Hacienda para que encaje en el esquema actual. Un hueco se queda hueco.

Más adelante ambos dominios podrán alimentar clasificación de gasto, analítica, Tax
Engine y notificaciones — pero como fuentes distintas, no fundidas en una.

**La evidencia original se conserva.** El PDF, la imagen o el artefacto derivado de un
correo **son** la evidencia. Lo que extraiga un modelo no la sustituye: la acompaña.

---

## Reportado frente a derivado

El principio que ya gobierna el dominio fiscal se extiende tal cual al externo:

```
LO QUE EL DOCUMENTO DICE     ≠     LO QUE TRIBUU INFIERE
```

| Reportado | Derivado |
|---|---|
| `reported_total` | `suggested_category` |
| `reported_currency` | `suggested_subcategory` |
| `reported_supplier` | `suggested_cabys_code` |
| | `classification_confidence` |

**Un valor derivado jamás se disfraza de evidencia.** En particular, un documento
externo casi nunca reporta CABYS costarricense: en ese caso el CABYS **reportado queda
ausente**. Tribuu podrá sugerir uno más adelante, con su confianza y su procedencia,
pero un CABYS sugerido no es un CABYS reportado.

Los campos extraídos o inferidos por IA deberán poder llevar **valor, procedencia,
confianza cuando proceda y estado de corrección humana**. El esquema físico se diseñará
en D1/D2, no aquí.

---

## Clasificador ≠ Tax Engine

```
Clasificador de gasto  →  «¿qué compró la empresa?»
Tax Engine             →  «¿cuál es el tratamiento tributario en Costa Rica?»
```

El clasificador —y cualquier modelo— **no determina por su cuenta** deducibilidad,
derecho a crédito de IVA, obligaciones de retención ni deuda tributaria final. Es la
misma frontera que gobierna todo el proyecto: **LLM ≠ Tax Engine**.

---

## Arquitectura de notificaciones — principio

El usuario no debería tener que acordarse de abrir Tribuu.ai. El producto debe buscarle
cuando algo merece su atención. Pero un canal es un canal:

```
Documentos ───────────┐
Calendario ───────────┤
Tax Engine ───────────┤
Radar normativo ──────┤
                      ▼
             Motor de notificaciones
              ↙        ↓         ↘
            Web    WhatsApp     Correo
```

**Nunca** `Tax Engine → API del proveedor de WhatsApp`, y **nunca** un modelo estimando
una cifra que sale por WhatsApp. Los canales consumen estado y eventos ya confiables,
producidos en otra parte.

El motor de notificaciones tendrá que ocuparse conceptualmente de evento, prioridad,
destinatario, preferencias de canal, estado de entrega, intención del mensaje, enlace
profundo, deduplicación y enfriamiento, e historial. **Sin esquema, sin cola y sin
integración de proveedor todavía.**

**Consentimiento.** Un mensaje proactivo por WhatsApp exigirá opt-in explícito y
preferencias por tipo — vencimientos, alertas de importe, documentos que requieren
atención, avisos preventivos, novedades normativas, frecuencia y severidad.

**Lenguaje de certeza.** Si faltan datos o hay documentos en revisión, Tribuu no puede
presentar una cifra como definitiva. Habrá que distinguir **estimado**, **calculado /
listo para revisión** y **determinado**. Lo decide el estado del Tax Engine; WhatsApp
solo comunica ese estado.

---

## Roadmap de producto

**Ninguna etiqueta de esta tabla es un nombre inmutable de checkpoint de ingeniería.**
Los checkpoints reales viven en `PROJECT_STATE`.

| Etapa | Nombre | Estado |
|---|---|---|
| **C3** | Subida manual de XML + workspace + bandeja | ✅ **COMPLETADO** |
| D1 | Dominio de documentos externos | ⬜ Planificado |
| D2 | Inteligencia documental | ⬜ Planificado |
| D3 | Clasificación de gasto | ⬜ Planificado |
| D4 | Revisión unificada de documentos | ⬜ Planificado |
| C4 | Canales de ingesta automatizada | 🔵 **EN CURSO** (C4-A: ✅ COMPLETADO, ADR-046 aceptado · **SIGUIENTE: C4-B0**, decisión de proveedor e infraestructura · C4-B: NOT STARTED) |
| C5 | Perfil fiscal de empresa + calendario | ⬜ Planificado |
| C6 | Tax Engine de IVA | ⬜ Planificado |
| W1 | Notificaciones por WhatsApp | ⬜ Planificado |
| C7 | Renta y proyecciones | ⬜ Planificado |
| W2 | Inteligencia fiscal por WhatsApp | ⬜ Planificado |
| C8 | Radar normativo | ⬜ Planificado |
| W3 | Alertas normativas por WhatsApp | ⬜ Planificado |
| W4 | Tribuu conversacional | ⬜ Planificado |

### D1 — Dominio de documentos externos

Ciclo de vida de la evidencia, documento externo normalizado, tenencia y seguridad,
procedencia, y semántica de revisión y corrección.

### D2 — Inteligencia documental

Extracción de texto nativo cuando existe, visión u OCR cuando hace falta, extracción
estructurada asistida por IA, validación, y confianza con procedencia.

### D3 — Clasificación de gasto

Responde a «¿qué compró la empresa?». Señales del proveedor y del contexto, categoría y
subcategoría, clasificación por línea cuando sea posible, CABYS **sugerido** separado
del reportado, y realimentación cuando una persona corrige.

### D4 — Revisión unificada de documentos

Una sola bandeja para ambos dominios: procesado · requiere atención · no soportado
todavía · pendiente de proceso · en revisión o corrección humana.

### C4 — Canales de ingesta automatizada

Reencuadre de lo que antes era «ingesta de XML por correo». El correo es el primer
canal probable, no el alcance:

```
correo / adjunto
        ↓
  recepción de evidencia
        ↓
  detector y enrutador de documento
       ↙                    ↘
XML fiscal CR          PDF / imagen / externo
      ↓                        ↓
Dominio Fiscal          Dominio Externo
```

**El canal no contiene lógica fiscal.** Transporta y enruta; nada más.

**Buzón Tribuu — un solo buzón durable, usos progresivamente más automáticos.** Cada
empresa participante puede activar su propia dirección de recepción de documentos
(conceptualmente `empresa-x7k3@inbox.tribuu.ai`). La dirección del MVP es la MISMA que
sobrevive a toda la evolución — nunca una dirección provisional que luego se sustituya:

1. **MVP** — Tribuu aprovisiona la dirección de la empresa; el usuario reenvía
   manualmente los correos con facturas.
2. **Reenvío automático configurado por el usuario** — misma dirección; el usuario crea
   una regla en Gmail/Outlook/otro. Sin OAuth.
3. **Entrega directa del proveedor** — misma dirección; la empresa la entrega a sus
   proveedores como su dirección de recepción de documentos. Sin arquitectura nueva.
4. **Buzón conectado (futuro, fuera del MVP de C4)** — OAuth de Gmail/Outlook; Tribuu
   detecta documentos en el buzón permitido sin reenvío.

Principio de producto: *«Tribuu recibe tus documentos aunque no abras la aplicación».*
Ninguna de estas etapas está implementada.

**C4 preserva TODA la evidencia empresarial aceptada, no solo el XML.** El objetivo es
«Tribuu recibe toda la evidencia empresarial relevante que llega al Buzón Tribuu», con
un principio rector: *«Tribuu puede no entender todavía un documento, pero si confirma
que lo recibió, no debe perderlo»*. El XML de Hacienda se entiende fiscalmente de
inmediato por el C2 existente. Los ADJUNTOS aceptados se preservan con los bytes
exactos tal y como los entrega el proveedor, con huella SHA-256, en almacenamiento de
objetos neutral al proveedor. El CUERPO del correo (hay recibos que solo existen como
correo) es evidencia de primera clase por derecho propio — no un adjunto — y se
preserva como la **representación exacta que el proveedor entregue** (MIME crudo, HTML,
texto o campos normalizados: no se sabe cuál hasta elegir proveedor), con procedencia
explícita de qué representación se recibió. Todo puede quedar sin procesar al
principio; su estado veraz es «Recibido y guardado. Análisis automático pendiente» —
nunca «procesado».

**Un documento económico puede tener varias representaciones.** `factura.xml` +
`factura.pdf` pueden ser UNA factura: el XML válido costarricense es la fuente canónica
de los hechos fiscales REPORTADOS y produce el ElectronicDocument vía C2; el PDF se
conserva como evidencia/representación y no crea un segundo documento. En el MVP no hay
emparejamiento heurístico por nombre de archivo; la conciliación futura decide si una
evidencia representa un documento ya conocido (la `Clave` reportada es la señal
canónica de alta confianza) o si puede crear un ExternalDocument (ADR-043 intacto).

**Tres capas de certeza, y no se mezclan.** (1) **Evidencia monetaria identificada** —
Tribuu identificó hechos monetarios en la evidencia (emisor AWS, USD 486.37): eso aún
NO demuestra que el importe sea un gasto de la empresa. (2) **Clasificación económica
observada** — con suficiente contexto de empresa y de documento, el evento se
clasifica como gasto · ingreso · otro · sin resolver; sigue sin ser una clasificación
tributaria, y su mecanismo queda abierto: el diseño de D3 podrá combinar reglas
deterministas con clasificación asistida por modelo, confianza y revisión humana — un
modelo puede asistir, pero no convertir en silencio la incertidumbre en un hecho.
(3) **Tratamiento fiscal** — el Tax Engine determinista decide después deducibilidad,
crédito/débito de IVA, retenciones y periodo; ahí ningún modelo es autoridad. Un total
identificado NUNCA se llama «gasto» por el mero hecho de haber recibido la factura.
`LLM ≠ Tax Engine` — que no se reinterpreta como «LLM ≠ clasificación económica».

**Por qué C5 se adelanta.** C5 determina la RELACIÓN del documento con la empresa, no
su clasificación económica. Con un ElectronicDocument de CRC 500 000: empresa = emisor
→ **EMITIDO** (saliente); empresa = receptor → **RECIBIDO** (entrante); ninguna de las
dos → ajeno; identidad insuficiente → sin resolver. Determinación determinista, jamás
de un LLM — y deliberadamente NO se congela «emisor = venta» ni «receptor = gasto»:
qué representa económicamente un documento lo responde D3-A, y qué significa
tributariamente, C6. Sin el perfil fiscal de C5 no hay forma honesta de llamar
«gasto» a nada — y llamar «gasto» a una venta sería peor que no decir nada.

**Secuencia próxima:** C4 (Buzón + intake automatizado + preservación durable de
evidencia) → **C5** (perfil fiscal de empresa: identidad fiscal canónica + SOLO la
relación/dirección determinista del documento) → **D1-A + D2-A** (dominio mínimo de
documento externo + MVP de inteligencia documental: PDF/imagen/cuerpo, extracción
básica con procedencia y confianza, conciliación) → **D3-A** (clasificación económica
mínima: gasto observado · ingreso observado · otro · sin resolver, con revisión donde
haga falta) → C6 (Tax Engine de IVA). Antes de D3-A la interfaz puede mostrar «Documentos con importes identificados»
—con totales por moneda si es útil—, pero no «gastos»; los totales multi-moneda se
muestran por moneda de origen mientras no exista una política determinista de
conversión aprobada.

### W1 — Notificaciones por WhatsApp

Vencimientos fiscales, importe de IVA estimado o calculado **cuando sea confiable**,
documentos que requieren atención, y enlace profundo a Tribuu.

### W2 — Inteligencia fiscal por WhatsApp

Después de renta y proyecciones: proyecciones, advertencias preventivas y cambios
fiscales relevantes.

### W3 — Alertas normativas por WhatsApp

Después del radar normativo. Cada aviso indica sin ambigüedad si la norma está
**EN DISCUSIÓN**, **APROBADA** o **VIGENTE**.

### W4 — Tribuu conversacional

«¿Cuánto tengo que pagar?» · «¿Cuándo vence?» · «¿Por qué?» · «¿Qué tengo pendiente?»
· «¿Qué cambió?»

La capa conversacional **recupera y explica** resultados confiables. No calcula
impuestos por su cuenta.

---

## Fases originales (referencia histórica)

Lo que sigue es el plan por fases con el que arrancó el proyecto. Se conserva porque
describe bien el porqué del orden, pero **sus estados están superados**: consúltese
`PROJECT_STATE`. Las fases 0 a 2 corresponden, a grandes rasgos, a lo ya construido.

**Por qué el orden importa.** El asistente de la Fase 6 solo vale lo que valgan los
datos de la Fase 2 y el motor de la Fase 4. Adelantar la capa de IA sobre datos poco
confiables produciría exactamente el producto que hemos decidido no construir: un
chatbot que suena convincente y no puede garantizar nada.

---

## Fase 0 — Project foundation

**Objetivo:** dejar el repositorio profesionalmente preparado antes de escribir código.

**Alcance**
- Estructura de directorios
- Documentación de producto y arquitectura
- Reglas permanentes para agentes de programación
- Registro de decisiones y glosario
- `.gitignore` preventivo

**Fuera de alcance:** cualquier dependencia, aplicación, esquema o funcionalidad.

**Criterio de finalización:** alcance del MVP claro, arquitectura documentada, reglas
para agentes documentadas y base preparada para comenzar la Fase 1.

---

## Fase 1 — Infrastructure / Auth / Company

**Objetivo:** que el sistema sepa quién es el usuario y a qué empresa pertenece, con
aislamiento real verificable.

**Alcance previsto**
- Proyecto frontend y proyecto backend inicializados
- Supabase conectado (PostgreSQL, Auth)
- Autenticación de usuarios
- Modelo de empresa (tenant) y relación usuario–empresa
- Row Level Security operativa
- Perfil fiscal básico de la empresa
- Gestión de secretos por variables de entorno
- Base de auditoría y logs

**Decisiones a cerrar en esta fase**
- Mecanismo técnico de propagación de identidad hacia RLS (ADR-012)
- Hosting concreto del backend (ADR-011)
- Modelo de permisos usuario–empresa (ADR-015)

**Criterio de finalización:** un usuario autenticado accede a los datos de su empresa
y **no puede acceder a los de otra** — verificado mediante tests de aislamiento, no
por revisión visual.

> Esta fase es la que sostiene todas las demás. El aislamiento no se retrofitea.

---

## Fase 2 — XML invoices

**Objetivo — primer gran hito técnico del proyecto:**

```
Un XML real de comprobante electrónico costarricense entra al sistema.
        ↓
El sistema lo interpreta correctamente.
        ↓
Lo transforma a nuestro modelo interno.
        ↓
Lo almacena correctamente en PostgreSQL.
        ↓
El usuario puede visualizar la factura en la interfaz.
```

**Alcance previsto**
- Carga de XML
- Conservación íntegra e inmutable del documento original en Storage
- Hash de integridad del documento
- Pipeline: `Raw XML → Source DTO → Validation → Normalizer → InternalInvoice`
- Persistencia en PostgreSQL, aislada por empresa
- Trazabilidad del dato normalizado hacia el documento original
- Idempotencia en la reingesta
- Visualización de la factura en la interfaz
- Tests del pipeline con fixtures anonimizados

**Restricciones**
- El modelo `InternalInvoice` **no copia** la estructura del formato externo (ADR-006)
- Los valores procedentes del documento se almacenan como `reported_*` (ADR-003)
- Ninguna versión ni tipo de comprobante se asume sin fuente oficial verificada

**Fuera de alcance:** integración con Hacienda, bancos, Alegra o Facturele. **El XML es
la fuente de datos, no un formato de importación temporal.**

**Criterio de finalización:** el hito descrito arriba, completo y con tests.

---

## Fase 3 — Dashboard

**Objetivo:** dar visibilidad continua sobre la situación fiscal observada.

**Alcance previsto**
- Listado y consulta de comprobantes
- Consolidados de ventas y compras
- Indicadores de situación fiscal
- Filtros por período

**Restricción esencial de esta fase.** Todavía **no existe Tax Engine**. Todos los
importes de impuestos mostrados provienen del documento fuente: son valores
`reported_*`, es decir, **lo que declaró el emisor**, no cálculos nuestros.

La interfaz debe dejarlo visualmente claro. Presentar un valor declarado como si fuese
un cálculo propio sería una promesa que el sistema aún no puede respaldar.

**Criterio de finalización:** el usuario ve su situación fiscal observada y entiende
que lo mostrado procede de sus documentos.

---

## Fase 4 — Tax Engine IVA

**Objetivo:** primer cálculo tributario propio, determinista y auditable.

**Alcance previsto**
- Paquete `tax-engine/` como paquete Python independiente
- Representación de reglas con fuente · documento/artículo · fecha · vigencia · versión
- Resolución de regla vigente según `as_of_date`
- Cálculo de IVA determinista
- Desglose paso a paso del resultado
- Persistencia de valores `computed_*` junto con la versión de regla aplicada
- Contraste `reported_*` vs `computed_*`
- Batería de tests, incluidos casos de regresión histórica

**Restricciones**
- Sin LLM, sin FastAPI, sin acceso a base de datos, sin I/O innecesario (ADR-005)
- Ninguna tasa ni artículo se introduce sin fuente oficial verificada (Regla 2)
- Decimal exacto, nunca coma flotante (ADR-008)

**Criterio de finalización:** un cálculo de IVA reproducible, explicable paso a paso,
respaldado por reglas versionadas con fuente, y con tests que lo verifican.

> Aquí nace la propiedad más valiosa del producto: la discrepancia entre lo declarado
> y lo calculado. Es la señal que el contribuyente necesita ver.

---

## Fase 5 — Tax Knowledge Base + RAG

**Objetivo:** normativa tributaria verificable y consultable.

**Alcance previsto**
- Modelo de normativa con metadatos obligatorios de fuente y vigencia
- Ingesta controlada de documentos normativos desde fuentes oficiales verificadas
- Fragmentación y embeddings
- pgvector y búsqueda semántica
- Recuperación con **cita obligatoria**
- Distinción entre normativa vigente y derogada
- Políticas de acceso propias: conocimiento compartido, no aislado por tenant (ADR-009)

**Decisión a cerrar:** estrategia de embeddings (ADR-014).

**Restricción:** el RAG **no sustituye al Tax Engine**. Aporta contexto normativo, no
cifras.

**Criterio de finalización:** una consulta normativa devuelve contenido con fuente,
artículo, fecha y vigencia verificables.

---

## Fase 6 — AI Expert

**Objetivo:** la capa de interacción. Última en llegar, y deliberadamente.

**Alcance previsto**
- Abstracción de proveedor LLM (completions, tool calling, embeddings)
- AI Agent con acceso exclusivo mediante tools controladas
- Implementación de tools: `get_company_profile()` · `get_sales()` · `get_purchases()` ·
  `get_invoice()` · `calculate_iva()` · `get_tax_rule()` · `search_tax_knowledge()`
- Respuesta estructurada: explicación + cálculo + fuentes + evidencia + advertencias
- Auditoría de las interacciones del agente

**Restricciones**
- Ningún acceso indiscriminado a la base de datos; ningún SQL libre
- Siempre dentro del tenant e identidad del usuario que pregunta
- `calculate_iva()` **no calcula**: invoca al Tax Engine
- Ante datos insuficientes, el agente lo declara. Nunca estima en silencio

**Decisión a cerrar:** proveedor LLM inicial (ADR-013).

**Criterio de finalización:** el usuario pregunta en lenguaje natural sobre su
situación fiscal real y recibe una respuesta con cifra determinista, desglose, fuentes
verificables y advertencias.

---

## Fase 7 — Fiscal Radar

**Objetivo:** pasar de responder preguntas a anticiparlas.

**Alcance previsto**
- `find_missing_invoices()` y `find_risks()`
- Detección de inconsistencias entre `reported_*` y `computed_*`
- Detección de datos faltantes o anómalos
- Alertas y proyecciones sobre datos observados

**Restricción:** toda detección debe ser explicable y trazable hasta los datos
concretos que la originaron.

---

## Fase 8 — Monetization

**Objetivo:** convertir el producto en negocio.

**Alcance previsto**
- Modelo de planes
- Facturación y suscripciones
- Límites de uso y control de costes
- Onboarding

---

## Fase 9 — Integrations

**Objetivo:** ampliar las fuentes de datos más allá del XML cargado manualmente.

**Alcance previsto:** integraciones con sistemas de facturación, otras fuentes de
datos fiscales y entradas automatizadas.

**Restricción absoluta:** ninguna integración se implementa sobre contratos supuestos.
Requiere documentación verificada del sistema externo (Regla 1). Cada integración
mantiene el pipeline `Source DTO → Validation → Normalizer → InternalInvoice`: el
modelo interno permanece desacoplado de cada proveedor.

---

## Fase 10 — Advanced tax capabilities

**Objetivo:** ampliar el dominio tributario cubierto.

**Alcance previsto:** impuestos adicionales, obligaciones periódicas, escenarios
fiscales más complejos, capacidades analíticas avanzadas.

**Restricción:** cada nueva capacidad tributaria repite el mismo estándar — regla con
fuente y vigencia, cálculo determinista, `as_of_date`, tests y explicabilidad. Sin
excepciones por antigüedad del proyecto.

---

## Principios que atraviesan todas las fases

1. **Nunca inventar** legislación, tasas, APIs ni contratos externos.
2. **El LLM nunca calcula** un impuesto.
3. **Todo cálculo es reproducible** — `as_of_date` + versión de regla.
4. **Todo dato conserva su origen.**
5. **`reported` nunca se confunde con `computed`.**
6. **Aislamiento multiempresa** verificado con tests.
7. **Sin secretos en el repositorio.**
8. **Cada fase se prueba** antes de construir la siguiente.

Ver [AI_INSTRUCTIONS.md](AI_INSTRUCTIONS.md) para las reglas completas.
