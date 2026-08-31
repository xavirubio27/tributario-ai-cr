# FISCAL_LOGICAL_MODEL — Modelo lógico de comprobantes electrónicos

> **Estado:** Fase E1 — **diseño lógico**. **COMPLETED** — auditoría final de Codex
> `CRITICAL 0 · HIGH 0 · MEDIUM 0 · LOW 0`, PASS.
>
> **No hay SQL, ni migraciones, ni tablas, ni código.** Los nombres de entidad y campo
> son conceptuales: fijan *qué representa* cada cosa, no cómo se escribirá en PostgreSQL.
> Tipos, precisiones, índices y restricciones se deciden en E2.
>
> **Fuente:** [FISCAL_DOMAIN.md](FISCAL_DOMAIN.md) (fase E0, aprobada) y las ADR-020…026.
> Este documento no reabre ninguna decisión cerrada; donde encontró una contradicción
> técnica demostrable, la señaló y se corrigió (§12). Las decisiones que formaliza están
> recogidas en **ADR-027 … ADR-031**, todas aceptadas.

Se separa de `FISCAL_DOMAIN.md` porque aquél documenta **la fuente oficial** y éste
**nuestra interpretación**. Mezclarlos haría difícil saber qué afirma Hacienda y qué
decidimos nosotros — distinción que ADR-021 exige mantener nítida.

---

## 1. Qué transforma esta fase

```
181 nodos XML          →   entidades del dominio tributario
67 clasificados MVP        (no una columna por nodo)
```

El criterio no es reproducir el XSD, sino responder preguntas del dominio: qué se
vendió, a quién, cuánto impuesto se declaró, qué documento ajusta a cuál. Un nodo del
XML puede convertirse en tres campos (`FechaEmision`, §8), varios nodos en una sola
entidad (`Emisor`/`Receptor` → `DocumentParty`, §5), y un contenedor puede desaparecer
aportando solo su cardinalidad (`DetalleServicio`).

---

## 2. Diagrama conceptual

```
Company  (tenancy existente, public.companies)
   │
   │ 1..N                         ┌──────────────────────────────────────┐
   ▼                              │ Cada entidad fiscal lleva company_id │
SourceDocument                    │ como propietario de tenant (§4)      │
   │                              └──────────────────────────────────────┘
   │   SourceDocument      0..1 ──▶  ElectronicDocument
   │   ElectronicDocument  1..N ──▶  SourceDocument
   │   (relación de normalización y procedencia, §3.2)
   ▼
ElectronicDocument ──────────────────────────────────┐
   │                                                 │
   ├── 1..2  DocumentParty                           │
   │            issuer   exactamente 1                │
   │            receiver 0..1  (§5)                   │
   │                                                 │
   ├── 0..N  DocumentLine                            │
   │            ├── 0..5     LineDiscount            │
   │            └── 1..1000  LineTax                 │
   │                                                 │
   └── 0..10 DocumentReference ──── 0..1 ────────────┘
                                  resolved_document
                                  (auto-referencia opcional)
```

**Diferencias frente al diagrama de partida, con motivo:**

| Cambio | Motivo |
|---|---|
| La relación `SourceDocument` ↔ `ElectronicDocument` **no es 1..1** | Un artefacto puede no normalizarse nunca (§3.1) y un documento puede provenir de varios artefactos (§13). Cardinalidades exactas en §3.2 |
| `DocumentPayment` y `DocumentCharge` **fuera del MVP** | `MedioPago` y `OtrosCargos` están clasificados «normalizar después» en E0 (§7.2) |
| `DocumentReference` puede apuntar a un `ElectronicDocument` | Resolución diferida y opcional (§10.2) |
| `DocumentLine` es **0..N** | `DetalleServicio` es `[0..1]`: un comprobante puede no tener líneas |

---

## 3. `SourceDocument` — el artefacto

### Propósito
Representar el artefacto original recibido, exactamente como llegó. Es la única
respuesta a «¿de dónde salió este dato?» y el sustrato de [ADR-022](DECISIONS.md#adr-022).

### Identidad
Identificador interno propio. **No** la `Clave`: un artefacto puede ser ilegible, estar
duplicado o no haberse parseado todavía, y aun así debe existir como registro.

### Relaciones
- Pertenece a una `Company` (propietario de tenant).
- Referencia a lo sumo un `ElectronicDocument`, una vez parseado con éxito.

### Contenido conceptual
| Concepto | Notas |
|---|---|
| XML original íntegro | Referencia al contenido; **no se decidió en E1** dónde vive (H-6 — ver nota) |
| Huella de integridad | Existencia decidida en E1; **algoritmo no decidido en E1** (H-6 — ver nota) |
| `company_id` | Propietario de tenant |
| Origen | Cómo llegó: carga manual, correo, API… catálogo interno, no oficial |
| Tipo de documento detectado | Del namespace raíz (§9). **Opcional**: puede no determinarse |
| `detected_schema_version` | Versión **estructural**. **Opcional hasta detectarse** (§3.1) |
| `schema_detection_status` | `detected` · `unknown` · `unsupported` · `failed` (§3.1) |
| Estado de parseo | `pending`, `parsed`, `failed`, `rejected` |
| Diagnóstico de parseo | Por qué falló, si falló |
| Momento de ingesta | Cuándo lo recibimos nosotros — distinto de `FechaEmision` |
| Enlace al documento normalizado | Opcional: sólo existe tras un parseo correcto |

> **Nota temporal sobre H-6.** Al cerrar E1, **H-6 estaba ABIERTO**: el almacenamiento y
> el algoritmo de huella se difirieron deliberadamente a E2, porque son decisiones físicas
> y esta fase es de modelo lógico. **Estado actual del proyecto, tras el diseño de E2:
> H-6 está CERRADO PARA EL MVP.**
>
> ```
> raw_xml         BYTEA
> content_sha256  BYTEA
> huella          SHA-256 de los bytes originales exactos
> almacenamiento  PostgreSQL
> ```
>
> Detalle en [FISCAL_PHYSICAL_MODEL.md](FISCAL_PHYSICAL_MODEL.md) §8 y
> [ADR-037](DECISIONS.md#adr-037). Las dos filas anteriores describen el estado **de E1**,
> no el actual.

### Lo que explícitamente **no** representa
- Ningún valor fiscal interpretado. Ni un total, ni un impuesto, ni una parte.
- La revisión de *ruleset*: eso es interpretación, no artefacto (§9).
- Decisiones de almacenamiento: E1 no fija bucket, ruta ni algoritmo de huella — **E2 sí
  las fijó** (ver nota anterior).

### 3.1 La versión no siempre es detectable

**Corrección respecto a la primera versión de E1**, que afirmaba que la versión
estructural era «siempre determinable». Eso contradice el propósito mismo de
`SourceDocument`: si sólo pudiera representar artefactos interpretables, no serviría
para conservar los que no lo son — que son justo los que hay que investigar.

`SourceDocument` debe poder representar los cinco casos:

| Caso | `schema_detection_status` | `detected_schema_version` |
|---|---|---|
| XML válido de versión soportada | `detected` | presente |
| XML bien formado, versión desconocida | `unknown` | ausente |
| Versión reconocida pero no soportada — p. ej. v4.3 | `unsupported` | presente |
| XML corrupto o no parseable | `failed` | ausente |
| Recibido, aún sin intentar interpretar | `pending` (estado de parseo) | ausente |

La taxonomía es **conceptual y no definitiva**: fija los estados que hay que poder
distinguir, no sus nombres finales.

El caso `unsupported` no es hipotético: la propia v4.4 admite v4.3 y anteriores para
notas de crédito y débito que ajusten comprobantes de su vigencia (FISCAL_DOMAIN §1.1.bis).
Reconocer la versión y no soportarla todavía es distinto de no reconocerla.

### 3.2 Cardinalidad canónica frente a `ElectronicDocument`

Enunciada por ambos extremos, porque uno solo se presta a malinterpretación:

```
Para cada SourceDocument:
    ElectronicDocument normalizado  =  0..1

Para cada ElectronicDocument:
    SourceDocuments de procedencia  =  1..N
```

**`SourceDocument` puede existir sin `ElectronicDocument`** — y no es un caso raro:
ocurre siempre que el artefacto está `pending`, corrupto, de versión `unknown`,
`unsupported`, o cuyo parseo `failed` (§3.1). Conservarlo es justamente el punto: un
XML que no supimos leer sigue siendo evidencia de que algo llegó.

**Un `ElectronicDocument` puede provenir de varios `SourceDocument`** cuando el mismo
comprobante se ingiere más de una vez, llega por fuentes distintas, o existen artefactos
equivalentes (§13). Nunca de cero: un documento normalizado siempre procede de algún
artefacto — ésa es la trazabilidad que exige [ADR-022](DECISIONS.md#adr-022).

**`ElectronicDocument` no es «hijo» de `SourceDocument`.** Es una relación de
**normalización y procedencia**, no una jerarquía de contención. Describirla como
paternidad induce a suponer 1:1 o una clave foránea obligatoria, y ninguna de las dos
cosas es cierta. **La dirección física de la clave foránea no se decide aquí**: es
materia de E2.

**Invariante de tenant.** Cuando la asociación existe:

```
SourceDocument.company_id  ==  ElectronicDocument.company_id
```

La **ausencia** de `ElectronicDocument` sigue siendo un estado válido y no viola nada.

### Invariantes
1. Un `SourceDocument` es **inmutable** una vez creado. Reprocesar produce una
   interpretación nueva, nunca modifica el artefacto.
2. Puede existir sin `ElectronicDocument` — un XML corrupto sigue siendo evidencia de
   que algo llegó, y perderlo sería perder la traza.
3. Su `company_id` no cambia jamás.
4. **No poder interpretar un artefacto nunca impide conservarlo.**

   ```
   failure to interpret  MUST NOT prevent  preservation of source artifact
   ```

   Es la consecuencia directa de [ADR-022](DECISIONS.md#adr-022): si el parseo fallido
   descartara el fichero, perderíamos precisamente el caso en que el original es más
   necesario. Un artefacto no interpretable se conserva, con su estado y su diagnóstico,
   y puede reprocesarse cuando el parser mejore.

---

## 4. `ElectronicDocument` — el comprobante normalizado

### Propósito
Representación normalizada y consultable del comprobante. Todo lo que contiene es
**reportado**; nada es calculado por nosotros.

### Tipos soportados en el MVP
| `document_type` | Código oficial | Documento |
|---|---|---|
| `invoice` | `01` | Factura Electrónica |
| `debit_note` | `02` | Nota de Débito Electrónica |
| `credit_note` | `03` | Nota de Crédito Electrónica |

**Discriminador explícito y necesario.** Los tres comparten esqueleto (E0 §3.1), pero el
tipo gobierna reglas distintas: NC y ND **exigen** al menos una referencia; la factura no.
Y el tipo participa en el signo del efecto (§14). Se propone un valor de dominio propio
(`invoice`) en lugar del código oficial (`01`) como identificador primario, conservando
el código: el catálogo oficial puede crecer, y ya lo hizo en 2026.

### Identidad
Ver §6.

### Contenido conceptual
Agrupado por concepto, no por orden del XSD:

**Identificación**
`clave` · `consecutive_number` · `document_type` · `issued_at` (+offset+literal, §8)

**Contexto del emisor y del receptor**
`issuer_economic_activity_code` · `receiver_economic_activity_code`

**Condiciones comerciales**
`sale_condition_code` · `credit_term`

**Moneda**
`currency_code` · `reported_exchange_rate`

**Totales reportados** — todos con prefijo `reported_`, todos tri-estado salvo los cuatro obligatorios
`reported_total_sale` · `reported_total_discount` · `reported_total_net_sale` ·
`reported_total_tax` · `reported_total_document` · `reported_total_taxed` ·
`reported_total_exempt` · `reported_total_exonerated` · `reported_total_not_subject`

**Interpretación**
`ruleset_revision` + `ruleset_revision_status` (§9)

**Tenancy y dirección**
`company_id` · `direction` (§7)

**Trazabilidad**
Enlace al `SourceDocument` de origen.

### Lo que explícitamente **no** representa
- El XML: vive en `SourceDocument`.
- Ningún `computed_*`. Cuando exista el Tax Engine, sus resultados irán a una capa
  separada, nunca sobre estos campos ([ADR-023](DECISIONS.md#adr-023)).
- El estado ante Hacienda: es otro documento con otro ciclo de vida (§15).
- El periodo fiscal: **no se deriva de la fecha** (§16).
- Emisor y receptor: son `DocumentParty`, no columnas de aquí.

---

## 5. `DocumentParty` — instantánea histórica

[ADR-024](DECISIONS.md#adr-024) está aceptada: instantánea, nunca clave foránea a un
maestro mutable.

### Propósito
Conservar lo que **el comprobante decía** sobre cada parte en el momento de emitirse.

### Identidad y relaciones
Identificador propio; pertenece a un `ElectronicDocument`.

**Cardinalidad agregada: `1..2`.** Desglosada por papel:

```
issuer    exactamente 1
receiver  0..1
```

**Corrección respecto a la primera versión de E1**, que proponía `2..2`. Era incorrecta.
Verificado contra los Anexos v4.4 (revisión 22/04/2026), fila del nodo `Receptor`, con
columnas `FE FEE FEC TE NC ND REP`:

```
Receptor   1  2  1  2  2  2  1
           ▲           ▲  ▲
           FE          NC ND
```

Y la leyenda oficial del mismo documento:

> «Condición 1. **Campo Obligatorio**: El dato debe estar en el documento siempre,
> independiente de las características de la transacción.
> Condición 2. **Campo Condicional**: El dato no es obligatorio en todos los documentos,
> pero pasa a ser obligatorio en determinadas operaciones si se cumple una cierta
> condición o circunstancia especial que posea la transacción.»

Es decir: **obligatorio en Factura, condicional en Nota de Crédito y Nota de Débito**.
Coincide con el XSD, que declara `Receptor [1..1]` en FE y `[0..1]` en NC y ND.

Un modelo lógico común para los tres tipos **no puede exigir el receptor**: hacerlo
rechazaría notas de crédito y débito perfectamente válidas.

**Cuándo el receptor es obligatorio lo deciden las reglas semánticas por
`document_type` y *ruleset*, no la cardinalidad del modelo** (§20). No se convierte en
regla SQL aquí.

### Campos MVP
| Campo | Emisor | Receptor |
|---|---|---|
| `role` | `issuer` | `receiver` |
| `legal_name` | 1..1 | 1..1 |
| `identification_type_code` | 1..1 | 1..1 |
| `identification_number` | 1..1 | 1..1 |
| `trade_name` | 0..1 | 0..1 |

**Un modelo común sí representa ambos sin perder semántica** — para estos cinco campos,
las cardinalidades coinciden. La asimetría real de E0 (§8.1) está en `Ubicacion`
(obligatoria para el emisor, opcional para el receptor), `CorreoElectronico` (`1..4`
frente a `0..1`) y en los campos exclusivos `Registrofiscal8707` y
`OtrasSenasExtranjero` — **todos ellos clasificados «normalizar después»**. Es decir:
la asimetría cae fuera del MVP, y por eso el modelo común es seguro *hoy*. Cuando esos
campos entren, habrá que reevaluarlo, y §5.1 explica cómo.

`identification_number` es **texto**, nunca numérico: la revisión 2026 admite
alfanuméricos para personas jurídicas (E0 §2.3).

### 5.1 Multiplicidad de contactos — decisión

`CorreoElectronico` del emisor es `[1..4]`. Modelarlo como un único campo de texto
**destruiría cardinalidad oficial**, y ese es precisamente el error a evitar.

**Decisión para el MVP: no se normalizan los contactos.** Ubicación, teléfono y correos
están en categoría B de E0, así que quedan **solo en el XML crudo**, íntegros y
recuperables. No se crea ningún campo `email` que pueda perder los otros tres.

Cuando entren, será como **colección separada** (`PartyContact`, con `contact_type` y
`sequence`), nunca como campos planos. Registrarlo ahora evita que alguien resuelva
después el camino fácil y equivocado.

### Lo que explícitamente **no** representa
- Una entidad de contraparte reutilizable. Si algún día existe, se construirá **sobre**
  estas instantáneas y jamás será autoridad sobre lo que un comprobante contenía.
- La identidad de la empresa del SaaS: eso es `company_id` (§7).

---

## 6. Identidad natural y ámbito de unicidad

### La `Clave` como identidad natural
Cincuenta dígitos que incluyen país, fecha, cédula del emisor, el consecutivo completo,
la situación y un código de seguridad (E0 §5.2). Es **globalmente única por
construcción** y es lo que Hacienda usa para identificar el comprobante.

### Propuesta: identificador interno + clave oficial
| | |
|---|---|
| **Identificador interno** | Sustituto, estable, sin significado. Lo que referencian las demás entidades |
| **`clave`** | Identidad oficial. Se conserva íntegra y se usa para buscar y cotejar |

Por qué ambos: la `Clave` es texto de 50 dígitos que aparecería repetido en cada línea,
impuesto y descuento; y un comprobante puede existir en nuestro sistema con la clave
aún sin validar. El sustituto da estabilidad interna sin restar autoridad a la clave.

### Ámbito de unicidad — el punto delicado

**Propuesta: la `clave` es única por empresa, no globalmente.**

El motivo no es técnico sino de producto. Si el emisor y el receptor de una misma
factura son ambos clientes del SaaS, **los dos deben tener ese comprobante**: para uno
es una venta, para el otro una compra. Una unicidad global obligaría a compartir una
fila entre dos tenants, lo que contradice el aislamiento de [ADR-020](DECISIONS.md#adr-020)
y de las políticas RLS por empresa.

| Caso | Resultado esperado |
|---|---|
| Mismo XML subido dos veces por la misma empresa | Un `ElectronicDocument`; el segundo artefacto se conserva y se enlaza (§13) |
| Mismo comprobante recibido por dos vías por la misma empresa | Un `ElectronicDocument`, dos `SourceDocument` |
| Mismo comprobante en dos empresas distintas | **Dos `ElectronicDocument`**, uno por tenant, con `direction` distinta |
| La empresa es emisora en unos y receptora en otros | Sin conflicto: `direction` es un atributo, no la identidad |

**No se decide aquí la restricción concreta.** Se fija la propiedad: *unicidad de la
clave dentro del ámbito de una empresa*. Cómo se exprese —y si además conviene una
unicidad sobre la huella del artefacto— es materia de E2.

---

## 7. Empresa y documento: propiedad de tenant ≠ papel en el documento

**Son dos conceptos distintos y el modelo los mantiene separados.**

| | `company_id` | `DocumentParty` |
|---|---|---|
| Qué es | Quién **posee y puede ver** el registro | Qué decía el comprobante sobre las partes |
| Naturaleza | Decisión del sistema | Hecho histórico del documento |
| Cambia con el tiempo | No | Nunca — es instantánea |
| Para qué sirve | Aislamiento, RLS, permisos | Semántica fiscal |

`ElectronicDocument` lleva `company_id` **directo**, con independencia de lo que digan
las instantáneas. Razones:

1. **RLS necesita una columna sobre la que decidir.** Derivar la pertenencia comparando
   identificaciones dentro de una política sería frágil y caro.
2. Una empresa puede legítimamente custodiar un comprobante en el que no es ninguna de
   las dos partes —por ejemplo, documentos aportados por un tercero—. El modelo no debe
   impedirlo por construcción.
3. Confundirlos haría que **corregir un dato de la empresa alterase quién ve qué**, que
   es exactamente el tipo de acoplamiento que rompe un sistema multiempresa.

### 7.1 Invariante de coherencia de tenant

```
Toda entidad fiscal hija pertenece al MISMO tenant que su padre.
```

Sin excepciones:

```
DocumentParty.company      = ElectronicDocument.company
DocumentLine.company       = ElectronicDocument.company
LineDiscount.company       = DocumentLine.company
LineTax.company            = DocumentLine.company
DocumentReference.company  = ElectronicDocument.company
ElectronicDocument.company = SourceDocument.company
```

**Por qué se enuncia como invariante y no se da por supuesto.** Llevar `company_id` en
cada entidad es lo que permite que RLS decida sobre una columna propia, sin recorrer la
jerarquía. Pero eso mismo abre la posibilidad de que un hijo declare un tenant distinto
del de su padre — y una línea de factura que pertenezca a otra empresa que su factura es
una fuga de datos entre contribuyentes, exactamente lo que ADR-020 cierra.

Es un invariante **del dominio**, no una recomendación. Cómo garantizarlo mecánicamente
—claves compuestas, restricciones, o ambas— **lo decide E2**. Aquí sólo se fija que debe
garantizarse en la base de datos y no depender de que el código de aplicación no se
equivoque nunca.

**El tenant jamás procede de la petición.** El `company_id` de una entidad fiscal se
toma del contexto autorizado del usuario, nunca de un valor enviado por el frontend. Es
la misma propiedad que ADR-012 estableció para la identidad: un valor que llega en el
cuerpo de una petición no es autoridad sobre nada.

### `direction` — derivada, pero almacenada
Valores propuestos: `issued`, `received`, `unknown`.

Se **deriva** comparando la identificación tributaria de la empresa contra las
instantáneas de emisor y receptor. Nunca se acepta del frontend.

Se **almacena** por tres motivos: se consulta constantemente (todo informe separa ventas
de compras); recalcularla en cada consulta obligaría a comparar contra un dato de la
empresa que puede cambiar, produciendo resultados distintos para el mismo documento en
momentos distintos; y `unknown` es un estado legítimo que conviene poder ver y depurar.

Debe seguir siendo **recomputable**, y ésa no es una propiedad decorativa: la identidad
tributaria configurada de una empresa **puede estar mal y corregirse después**. Si al dar
de alta la empresa se tecleó mal la cédula, todos sus documentos quedarían clasificados
`unknown` —o peor, al revés—. Al corregir el dato, la dirección debe poder recalcularse
sobre el histórico.

**Por eso `direction` no es evidencia inmutable del XML.** La distinción importa:

| | `DocumentParty` | `direction` |
|---|---|---|
| Qué es | **Verdad de origen** — lo que el comprobante decía | **Metadato derivado del tenant** |
| Cambia | Nunca | Sí, si cambia la identidad configurada de la empresa |
| Autoridad | El documento | Nuestra clasificación |

Recalcular `direction` **nunca** toca las instantáneas: éstas siguen diciendo lo que
decía el comprobante. Lo que cambia es nuestra conclusión sobre qué papel juega la
empresa en él.

---

## 8. `FechaEmision` — tres representaciones de un dato

Los Anexos exigen RFC3339 con desplazamiento: `YYYY-MM-DDThh:mi:ss[Z|(+|-)hh:mm]`
(E0 §7). El instante es inequívoco, pero el desplazamiento **también es información
fiscal** y se pierde al normalizar a UTC.

| Representación | Para qué |
|---|---|
| `issued_at` — instante absoluto | Ordenar, comparar, filtrar por rango |
| `issued_at_offset` — desplazamiento declarado | Interpretar el día local del emisor |
| `issued_at_raw` — valor literal del XML | Trazabilidad exacta y reproceso |

**No se codifica UTC−6 en ninguna parte.** El desplazamiento se toma del documento. Un
comprobante de exportación puede declarar otro, y presuponerlo sería inventar un dato.

El literal cumple además lo que [ADR-026](DECISIONS.md#adr-026) exige: conservar
contexto suficiente para interpretar reglas que dependen del tiempo, incluso si nuestra
interpretación del instante cambiara.

Se aplica igual a `FechaEmisionIR` en `DocumentReference`. No se elige tipo SQL.

---

## 9. `schema_version` y `ruleset_revision` — dónde viven

Se separan porque son cosas distintas ([ADR-026](DECISIONS.md#adr-026)) y **se conocen
en momentos distintos**.

| | `detected_schema_version` | `ruleset_revision` |
|---|---|---|
| Qué es | Versión **estructural**, del namespace y esquema aplicable | Revisión semántica que rige la interpretación |
| Dónde vive | **`SourceDocument`** | **`ElectronicDocument`** |
| Cuándo se conoce | Al parsear, **si se consigue** (§3.1) | Puede no ser determinable de inmediato |
| Naturaleza | Hecho sobre el artefacto | Interpretación del documento |

**Por qué esa ubicación.** La versión estructural es una propiedad del fichero: se lee
del namespace del elemento raíz y no depende de cómo lo interpretemos. Que sea una
propiedad del fichero no la hace siempre legible: un XML corrupto no tiene namespace que
leer, y por eso `SourceDocument` lleva un estado de detección explícito (§3.1). La revisión de
*ruleset* es lo contrario: es nuestra conclusión sobre qué reglas aplican, y pertenece
al documento normalizado, que es la interpretación.

### `ruleset_revision_status`
La revisión **no siempre es determinable al ingerir**, porque durante el periodo
voluntario (22-abr-2026 → 1-nov-2026) conviven documentos de igual versión estructural
bajo semánticas distintas. Estados propuestos:

| Estado | Significado |
|---|---|
| `detected` | El contenido lo determina sin ambigüedad — p. ej. un código de referencia `13`–`17` sólo existe bajo el *ruleset* 2026 |
| `ambiguous` | Compatible con más de una revisión; no hay señal discriminante |
| `resolved` | Fijada posteriormente con información adicional |

**No se diseña el algoritmo.** Se fija que la revisión es un valor **inferido, con
estado explícito**, nunca una función de la fecha ni una constante del sistema.

---

## 10. Líneas, descuentos, impuestos y referencias

### 10.1 `DocumentLine`

**Propósito:** una línea de detalle normalizada.
**Identidad:** identificador propio. `line_number` es el orden reportado, no la identidad
— es un dato del emisor y no debe gobernar nuestras claves.
**Relación:** pertenece a un `ElectronicDocument`; cardinalidad `0..N` (hasta 1000).

**Campos MVP:** `line_number` · `cabys_code` · `description` · `unit_of_measure_code` ·
`reported_quantity` · `reported_unit_price` · `reported_gross_amount` ·
`reported_subtotal` · `reported_taxable_base` · `reported_net_tax` · `reported_line_total`.

**No representa:** descuentos ni impuestos —son colecciones—, ni `DetalleSurtido` (§11),
ni ningún importe calculado por nosotros.

### 10.2 `LineDiscount`

`Descuento` es `[0..5]` por línea. **No se colapsa a un único importe**: hacerlo
perdería tanto el número de descuentos como su código, y un total no permite explicar
de qué se compone.

Campos respaldados por la fuente: `reported_amount` (obligatorio), `discount_code`
(obligatorio, catálogo de 10 valores) y `sequence` — el orden dentro de la línea, que
importa porque el XSD es una secuencia y sin él no podríamos reconstruir el original.
`CodigoDescuentoOTRO` y `NaturalezaDescuento` existen en el XSD pero **no** están en el
conjunto MVP: no se incluyen.

**Identidad:** interna, más `sequence` dentro de la línea.
**No representa:** ningún descuento calculado por nosotros, ni el total de descuentos del
documento —que es `reported_total_discount` en `ElectronicDocument` y puede no coincidir
con la suma de las líneas; esa discrepancia es información, no un error a corregir.

### 10.3 `LineTax`

`Impuesto` es `[1..1000]` — **obligatorio**: toda línea lleva al menos un impuesto.

| Campo | Origen | Notas |
|---|---|---|
| `tax_code` | `Impuesto/Codigo` | Obligatorio, catálogo de 10 |
| `vat_rate_code` | `CodigoTarifaIVA` | Opcional, catálogo de 11 |
| `reported_rate` | `Tarifa` | Opcional, decimal (4,2) |
| `reported_amount` | `Monto` | Obligatorio |
| `sequence` | posición | Reconstrucción del original |

La base imponible vive en la línea (`reported_taxable_base`), no aquí: el XSD la sitúa
en `LineaDetalle`, y duplicarla por impuesto inventaría un dato que el documento no da.
`FactorCalculoIVA` y `DatosImpuestoEspecifico` **no** están en el conjunto MVP.

**Identidad:** interna, más `sequence` dentro de la línea.

**Todo es reportado.** No se infiere IVA, no se calcula, no se valida contra tarifa
esperada. Eso es Tax Engine, y no existe.

**No representa:** la exoneración (entidad aparte, §10.4), los datos de impuestos
específicos (fuera del conjunto MVP), ni ningún importe calculado. Tampoco el desglose de
impuestos a nivel de documento, que es `DocumentTaxSummary` y está fuera del MVP.

### 10.4 `TaxExemption` — decisión

`Exoneracion` está clasificada **«normalizar después»** en E0, así que **queda fuera del
MVP**.

Cuando entre, la recomendación es **entidad propia dependiente de `LineTax`**, no
componente aplanado. Tres razones de fondo, no de elegancia relacional:

1. Tiene **diez campos propios** —tipo de documento, número, institución, artículo,
   inciso, fecha, tarifa exonerada, monto—: aplanarlos añadiría diez campos casi siempre
   vacíos a una entidad que sí se usa siempre.
2. Es **directamente relevante para el Tax Engine**: una exoneración cambia el impuesto
   efectivo, y necesitará consultarse y agregarse por sí sola.
3. Tiene **su propia fecha y su propio documento de respaldo**, con vigencia propia. Es
   un hecho jurídico distinto del impuesto al que modifica.

### 10.5 `DocumentReference` — entidad de primer nivel

`InformacionReferencia` es `[0..10]`: **muchos a muchos**, no una clave foránea.

| Campo | Notas |
|---|---|
| `referenced_document_type_code` | Obligatorio. Catálogo de **20** valores tras la revisión 2026 |
| `reported_number` | **Opcional** — el punto crítico |
| `reported_reference_date` | Obligatorio |
| `reference_code` | Opcional. **Determina el periodo contable** |
| `reason` | Opcional |
| `sequence` | Orden dentro del documento |

**`reported_number` es opcional, luego no puede existir una clave foránea obligatoria.**
Un diseño que la exija contradice el esquema oficial y rechazaría documentos válidos.

### 10.6 Referencia reportada ≠ relación resuelta

Se separan dos cosas que es tentador confundir:

```
reported_*                      resolved_document_id
lo que el documento dice        el enlace interno, si lo encontramos
inmutable                       opcional, poblado después
```

Esto permite **ingerir una Nota de Crédito antes que la factura que ajusta** — caso
frecuente y no un borde: al importar un histórico o recibir documentos desordenados, el
orden de llegada no es el orden lógico. Con FK obligatoria habría que rechazar la NC o
inventar una factura vacía; ambas cosas corrompen los datos.

Propiedades: la resolución es **diferida, opcional y reintentable**; nunca modifica los
campos reportados; y su ausencia es información legítima («referencia a un documento que
no tenemos»), no un error.

### 10.6.1 Las resoluciones nunca cruzan tenants

```
resolved_document_id  DEBE apuntar a un ElectronicDocument de la MISMA empresa.
```

La distinción es fina y conviene enunciarla con precisión:

| | Alcance |
|---|---|
| **Referencia reportada** (`reported_number`) | Cualquier número oficial que traiga el XML. No lo restringimos: es lo que el documento dice |
| **Resolución interna** (`resolved_document_id`) | **Sólo** documentos de la misma empresa |

Aunque la `Clave` coincida, una resolución jamás puede conectar un documento de la
empresa A con el `ElectronicDocument` de la empresa B. Permitirlo crearía una arista
entre tenants dentro de nuestro propio modelo, atravesando la frontera que
[ADR-020](DECISIONS.md#adr-020) estableció — y bastaría con seguir esa arista para leer
datos de otro contribuyente.

Que dos empresas tengan el mismo comprobante es **normal** (§6): para una es venta y
para otra compra. Cada una resuelve contra su propia copia.

**Identidad:** interna, más `sequence` dentro del documento.

**No representa:** el efecto contable del ajuste —el código lo determina, pero
calcularlo es Tax Engine (§16)—, ni una relación garantizada: `resolved_document_id`
puede quedar vacío para siempre de forma legítima.

### 10.7 Cadenas de referencias

El modelo debe soportar, sin relaciones 1:1:

```
Factura ← NC (código 01, anula)     → nuevo comprobante (código 07)
Factura ← NC (código 13, error mat.) → nuevo comprobante (código 15)
```

Al ser `DocumentReference` una entidad con cardinalidad `0..10` y resolución opcional,
las cadenas se representan de forma natural: cada eslabón es una fila. Un documento
puede ser referenciado por varios y referenciar a varios.

**No se calcula aquí ningún efecto contable.** El hecho de que `13`/`14` imputen al
periodo del comprobante original y `01`/`02`/`06`/`12` al de la nota (E0 §9.2) queda
registrado como **requisito** del Tax Engine (§16), no como lógica de este modelo.

---

## 11. Códigos externos: el documento manda

**Invariante propuesta:**

```
El código reportado por el comprobante es la verdad.
El catálogo local es enriquecimiento opcional.
```

Afecta a `cabys_code`, `unit_of_measure_code`, `currency_code`,
`identification_type_code`, `sale_condition_code`, `tax_code`, `vat_rate_code`,
`discount_code` y los códigos de referencia.

**Ninguno lleva clave foránea obligatoria a un catálogo local.** Si nuestro catálogo
está desactualizado —y lo estará: CABYS cambia, y la revisión 2026 amplió tres
catálogos sin tocar el esquema— un documento legítimo sería rechazado por una carencia
nuestra. Eso es inaceptable: el comprobante ya fue aceptado por Hacienda.

El enriquecimiento (descripción del CABYS, nombre de la unidad) es una **consulta**, no
una restricción. Un código desconocido se conserva tal cual y se muestra sin descripción.

Complementa a [ADR-026](DECISIONS.md#adr-026): los catálogos son datos versionados por
*ruleset*, no enumeraciones cerradas del modelo.

### 11.1 `DetalleSurtido` — se mantiene fuera

E0 lo clasificó `raw-only` y **la decisión se mantiene**: no hay contradicción técnica
que justifique reabrirla. Es un sub-modelo de línea completo y paralelo (41 nodos) cuyo
uso está restringido a fabricantes, industriales e importadores que facturan surtidos.

No se pierde nada: el XML original lo conserva íntegro, y `SourceDocument` es inmutable
y reprocesable ([ADR-022](DECISIONS.md#adr-022)). El día que un cliente lo necesite, se
normaliza reprocesando el histórico ya almacenado — sin pedir nada a nadie.

---

## 12. Errata de clasificación de E0, hallada durante E1

> **Naturaleza del hallazgo.** Esto es una **errata de clasificación de E0, descubierta
> durante la reconciliación del mapeo lógico de E1**. No es una pérdida de información
> ni una reinterpretación de la fuente oficial: los 181 nodos siguen inventariados y el
> XML original los conserva todos. Lo que estaba mal era la **categoría asignada** a
> ocho de ellos.
>
> ```
> Línea base E0 aprobada        67 MVP · 57 después · 57 crudo
> Reconciliación de E1          59 MVP · 64 después · 58 crudo
> Total                         181  (sin cambio)
> ```
>
> **No se reescribe la historia.** El commit de E0 (`b98a801`) queda intacto; la
> corrección se registra como errata fechada, con la evidencia campo por campo (§12.3).

### 12.1 C-1 — Siete campos MVP huérfanos

Siete entradas están clasificadas `MVP normalizado` mientras **su contenedor está en
«normalizar después»**:

| Campo MVP | Contenedor | Clase del contenedor |
|---|---|---|
| `CodigoComercial/Tipo` | `CodigoComercial` `[0..5]` | normalizar después |
| `CodigoComercial/Codigo` | `CodigoComercial` | normalizar después |
| `OtrosCargos/IdentificacionTercero/Tipo` | `OtrosCargos` `[0..15]` | normalizar después |
| `OtrosCargos/IdentificacionTercero/Numero` | `OtrosCargos` | normalizar después |
| `OtrosCargos/Detalle` | `OtrosCargos` | normalizar después |
| `TotalDesgloseImpuesto/Codigo` | `TotalDesgloseImpuesto` `[0..1000]` | normalizar después |
| `TotalDesgloseImpuesto/CodigoTarifaIVA` | `TotalDesgloseImpuesto` | normalizar después |

**Es imposible normalizar un campo cuyo contenedor no se normaliza**: no habría dónde
ponerlo. La causa es identificable: la clasificación de E0 se hizo por **nombre de
hoja**, y estos siete tienen nombres (`Tipo`, `Codigo`, `Numero`, `Detalle`,
`CodigoTarifaIVA`) que coinciden con campos MVP legítimos de otras ramas.

**Propuesta:** reclasificar los siete a «normalizar después», junto a sus contenedores.

### 12.2 C-2 — `ProveedorSistemas`: la tabla y la prosa se contradicen

`FISCAL_DOMAIN.md` §15 lo incluye en la **categoría C** (solo XML crudo); la tabla del
inventario lo marca **MVP normalizado**. Ambas cosas no pueden ser ciertas.

**Resolución de H-7.** `ProveedorSistemas` identifica al proveedor del software emisor.
Es obligatorio `[1..1]`, pero:

- no interviene en ningún cálculo tributario;
- no es parte de la transacción — no compra, no vende, no cobra;
- ninguna consulta del MVP lo necesita: no responde a cuánto se vendió, a quién, ni
  cuánto impuesto se declaró;
- es, en propiedad, **metadata técnica del documento**.

**Resolución: `raw-only` inicialmente**, alineando la tabla con la prosa de E0.

Esto **cierra H-7**. Se conserva íntegro en el XML original y puede normalizarse más
adelante reprocesando, si aparece una necesidad operativa o de auditoría — por ejemplo,
saber qué sistemas emiten en nombre del contribuyente. Ninguna fuente oficial exige lo
contrario: el campo es obligatorio en el comprobante, pero eso obliga al emisor, no
determina qué debemos normalizar nosotros.

### 12.3 Los ocho cambios, campo por campo

Reconciliación completa. Éstos y sólo éstos salen del conjunto MVP anterior:

| # | XML Path | Clasificación E0 | Clasificación corregida | Motivo |
|---|---|---|---|---|
| 1 | `FE/DetalleServicio/LineaDetalle/CodigoComercial/Tipo` | MVP normalizado | normalizar después | **C-1** · Colisión de nombre de hoja: `Tipo` es MVP en `Identificacion`. Su contenedor `CodigoComercial [0..5]` es categoría B |
| 2 | `FE/DetalleServicio/LineaDetalle/CodigoComercial/Codigo` | MVP normalizado | normalizar después | **C-1** · `Codigo` es MVP en `Impuesto`. Mismo contenedor categoría B |
| 3 | `FE/OtrosCargos/IdentificacionTercero/Tipo` | MVP normalizado | normalizar después | **C-1** · `Tipo` colisiona. Contenedor `OtrosCargos [0..15]` es categoría B |
| 4 | `FE/OtrosCargos/IdentificacionTercero/Numero` | MVP normalizado | normalizar después | **C-1** · `Numero` es MVP en `Identificacion`. Contenedor categoría B |
| 5 | `FE/OtrosCargos/Detalle` | MVP normalizado | normalizar después | **C-1** · `Detalle` es MVP en `LineaDetalle`. Contenedor categoría B |
| 6 | `FE/ResumenFactura/TotalDesgloseImpuesto/Codigo` | MVP normalizado | normalizar después | **C-1** · `Codigo` colisiona. Contenedor `TotalDesgloseImpuesto [0..1000]` es categoría B |
| 7 | `FE/ResumenFactura/TotalDesgloseImpuesto/CodigoTarifaIVA` | MVP normalizado | normalizar después | **C-1** · `CodigoTarifaIVA` es MVP en `Impuesto`. Contenedor categoría B |
| 8 | `FE/ProveedorSistemas` | MVP normalizado | **solo crudo** | **C-2** · Contradicción interna de E0: la **prosa §15 lo sitúa en categoría C**, la **tabla del inventario lo marca MVP**. Resuelto a favor de la prosa (§12.2) |

**Regla que unifica C-1.** Un campo no puede normalizarse si su contenedor no se
normaliza: no habría estructura donde alojarlo. Los siete son consecuencia de que E0
clasificó por **nombre de hoja**, y `Tipo`, `Codigo`, `Numero`, `Detalle` y
`CodigoTarifaIVA` aparecen en más de una rama con significados distintos.

### 12.4 Aritmética de la reconciliación

Para evitar cualquier lectura ambigua de las cifras:

```
67   nodos auditados  (el conjunto MVP de E0)
 ─8  reclasificados fuera del MVP  (§12.3)
───
59   permanecen en el modelo lógico MVP
```

Y **dentro de esos 59**, no sumados a ellos:

```
48   campos con valor        → se convierten en atributos de una entidad
11   nodos estructurales     → contenedores; aportan relación y cardinalidad,
                               no un atributo propio
───
59
```

Los once contenedores son `Emisor`, `Receptor`, sus dos `Identificacion`,
`DetalleServicio`, `LineaDetalle`, `Descuento`, `Impuesto`, `ResumenFactura`,
`CodigoTipoMoneda` e `InformacionReferencia`. **No son nodos adicionales**: son los
mismos 59, clasificados por cómo se representan.

```
0 sin explicar    ·    0 perdidos
```

### 12.5 Efecto sobre el modelo lógico

**Ninguno.** Los ocho campos reclasificados no estaban asignados a ninguna entidad —
quedaron sin destino en el mapeo precisamente porque su lugar no existe en el MVP. Las
siete entidades y sus cardinalidades son idénticas con la clasificación corregida.

---

## 13. Duplicados: artefacto frente a documento lógico

Dos preguntas distintas que un solo concepto de «duplicado» confundiría — y confundirlas
duplicaría ventas o compras en los informes, que es el daño concreto a evitar.

| | Artefacto duplicado | Mismo documento lógico | **Conflicto** |
|---|---|---|---|
| Qué es | El mismo fichero recibido otra vez | El mismo comprobante por vías distintas | Misma clave, **contenido fiscal divergente** |
| Condición | Misma empresa · misma huella | Misma empresa · misma `clave` · contenido equivalente | Misma empresa · misma `clave` · **contenido fiscal autoritativo divergente** |
| Respuesta | Conservar ambos artefactos; **no** crear un segundo documento | Un `ElectronicDocument`, varios `SourceDocument` | **No fusionar.** Anomalía de integridad que requiere investigación |

De ahí que un `ElectronicDocument` pueda tener **1..N** `SourceDocument` (§3.2).
Conservar los artefactos
repetidos no es redundancia: cada uno tiene su origen y su momento de ingesta, y esa es
la traza de cómo llegó la información.

Casos y comportamiento esperado:

| Caso | Resultado |
|---|---|
| Mismo XML, misma empresa, dos veces | 2 `SourceDocument` → 1 `ElectronicDocument` |
| Mismo comprobante por correo y por API | 2 `SourceDocument` → 1 `ElectronicDocument` |
| Mismo comprobante, dos empresas | 2 `SourceDocument` → **2** `ElectronicDocument`, uno por tenant |
| XML corrupto | 1 `SourceDocument` con estado `failed`, **0** `ElectronicDocument` |
| **Misma clave, contenido fiscal divergente, misma empresa** | 2 `SourceDocument`; **conflicto marcado**, sin fusión silenciosa |

### 13.1 El conflicto: misma clave, contenido fiscal divergente

Es el caso que obliga a tratar la deduplicación con cuidado.

La `Clave` es identidad oficial fuerte —incluye emisor, fecha, consecutivo y un código de
seguridad— y en condiciones normales dos XML con la misma clave deberían ser el mismo
documento. Pero **coincidir en la clave no autoriza a ignorar que el contenido difiere**.

Si aparecen, para la misma empresa, dos artefactos con la misma `clave` y contenido
divergente **en su contenido fiscal**, sólo hay explicaciones preocupantes: un documento
manipulado, un error grave
del sistema emisor, una colisión que no debería existir, o una confusión entre entornos
de pruebas y producción. Todas exigen que alguien mire.

**Fusionar silenciosamente sería lo peor posible**: escogeríamos arbitrariamente una de
las dos versiones y destruiríamos la evidencia de que hubo discrepancia — el mismo error
que `reported_*` frente a `computed_*` evita en otro plano.

Comportamiento conceptual: ambos artefactos se conservan (`SourceDocument` es inmutable),
la situación se marca como **anomalía de integridad**, y no se produce fusión automática.

*(Precisión de E2: una **huella de bytes distinta no basta** para concluir conflicto. Dos
serializaciones del mismo comprobante pueden diferir en bytes sin diferir en un dato
fiscal. La huella señala artefactos divergentes; el conflicto exige comparar el contenido
reportado. Ver [FISCAL_PHYSICAL_MODEL.md](FISCAL_PHYSICAL_MODEL.md) §15.1.)*

**No se diseña aquí ni el flujo de resolución ni ninguna tabla de conflictos**, ni se
decide si el segundo documento se ingiere, se retiene o se rechaza. Se fija que el caso
existe, que es distinto de un duplicado, y que no puede resolverse en silencio.

### 13.2 Dos empresas con el mismo comprobante oficial

Se preserva la decisión de §6: `Company A + Clave X` y `Company B + Clave X` producen
**dos `ElectronicDocument` distintos, uno por tenant**.

**No existe un `ElectronicDocument` global compartido entre empresas.** Motivos:

- **Aislamiento y RLS** — una fila compartida entre tenants no tiene dueño único sobre el
  que decidir el acceso.
- **Procedencia** — cada empresa recibe su propio artefacto, por su propia vía y en su
  propio momento. Esa traza es distinta para cada una.
- **Sin aristas entre tenants** — un documento compartido obligaría a que las entidades
  hijas apuntaran a filas de otro tenant, rompiendo §7.1 y §10.6.1.
- **Papeles distintos** — para una es venta y para otra compra; `direction` difiere.

La consecuencia conceptual conviene enunciarla: **la identidad lógica dentro del SaaS es
de ámbito de tenant, aunque la `Clave` sea oficial y globalmente única.** La clave
identifica el comprobante ante Hacienda; nuestro registro identifica *lo que esa empresa
tiene*. No son la misma cosa.

**No se decide aquí ninguna restricción de unicidad.** Se fija qué debe considerarse
duplicado, qué conflicto y qué no es ninguno de los dos.

---

## 14. Notas de crédito y débito: los importes no se niegan

**Los importes reportados se conservan positivos, siempre.**

El XSD declara `minInclusive="0"` en `DecimalDineroType`: **ningún importe puede ser
negativo en ningún comprobante**, tampoco en una nota de crédito (E0 §6). Guardar
`reported_total_document = -100` porque el documento es una NC sería **inventar un dato
que el comprobante no contiene**, y rompería la correspondencia con el original que
[ADR-023](DECISIONS.md#adr-023) exige.

El signo y el efecto provienen de tres fuentes combinadas:

```
document_type  +  semántica de la referencia  +  reglas fiscales futuras
```

Y no es una simple negación: el código de referencia decide además **a qué periodo** se
imputa el ajuste (E0 §9.2). Un modelo que resolviera el signo al ingerir perdería esa
información antes de poder usarla.

Cuando exista el Tax Engine, el efecto con signo será un `computed_*` en su capa, junto
al *ruleset* aplicado. Nunca sobre el valor reportado.

---

## 15. Mensajes de Hacienda — relación futura

`MensajeHacienda` y `MensajeReceptor` **no se normalizan en el MVP** ni se mezclan con
`ElectronicDocument`. Son documentos distintos, con su propia recepción, su propia firma
y su propio ciclo de vida; `MensajeReceptor` tiene incluso su propio consecutivo.

Relación conceptual futura:

```
ElectronicDocument   1 ── 0..N   TaxAuthorityMessage
                     enlazados por `clave`, dentro del mismo tenant
```

`0..N` y no `0..1`: un comprobante puede acumular varios mensajes en el tiempo, y esa
secuencia **es** la historia de su estado. Aplanarla a un campo `status` la destruiría y
confundiría *lo que el emisor declaró* con *lo que la Administración respondió*.

No se diseña integración con la API de Hacienda.

---

## 16. Periodo fiscal — requisito, no campo

```
El periodo fiscal/contable NO debe inferirse únicamente
de la fecha de emisión del documento.
```

Registrado como **invariante de dominio y requisito pendiente del Tax Engine**
(FISCAL_DOMAIN §13.2.bis). Dos mecanismos oficiales lo provocan: el código de referencia
imputa el ajuste al periodo de la nota o al del comprobante original (nota 9), y el
código `13` de la nota 10 exige poner en la fecha de referencia el periodo, no la fecha
real.

**Este modelo no incluye ningún campo de periodo fiscal.** Si en el futuro existe un
`effective_fiscal_period`, pertenecerá a la capa `computed_*`/*ruleset*, con la regla y
la versión que lo produjeron — salvo que aparezca un campo fuente explícito, que hoy no
existe.

---

## 17. Exactitud numérica

Ningún importe en coma flotante. Cada grupo lógico, con el tipo XSD que lo respalda:

| Grupo lógico | Tipo XSD | Restricción oficial |
|---|---|---|
| Todos los `reported_*` monetarios y `reported_exchange_rate` | `DecimalDineroType` | `xs:decimal`, 18 dígitos, 5 decimales, ≥ 0 |
| `reported_quantity` | `xs:decimal` | 16 dígitos, 3 decimales |
| `reported_rate` | `xs:decimal` | 4 dígitos, 2 decimales |
| `credit_term` | `xs:integer` | 5 dígitos |
| `line_number` | `xs:positiveInteger` | 1..1000 |

`FactorCalculoIVA` (5,4), `Proporcion` (10,5) y `PorcentajeOC` (9,5) **no** están en los
el conjunto MVP; se listan para que la elección de tipos en E2 los contemple.

El modelo lógico marca estos campos como **decimal exacto**. La precisión concreta de
PostgreSQL se decide en E2, con estas restricciones delante.

---

## 18. Ausencia frente a cero

**Invariante propuesta.** Tres estados distinguibles donde la fuente lo permite:

```
ausente en el origen   ≠   presente = 0   ≠   presente > 0
```

Afecta a nueve campos opcionales de `ElectronicDocument`
(`reported_total_taxed`, `_exempt`, `_exonerated`, `_not_subject`, `_discount`,
`_tax`) y a `receiver_economic_activity_code`, `credit_term` y `reference_code`.

De los 26 elementos de `ResumenFactura`, **sólo cuatro son obligatorios**. Que un total
no aparezca significa que el emisor **no lo declaró**, no que valga cero. Un valor por
defecto de `0` convertiría silenciosamente una omisión en una afirmación — y sobre esa
afirmación se construirían agregados y, más tarde, comparaciones del Tax Engine.

**Ningún campo reportado opcional lleva valor por defecto.**

---

## 19. Semántica condicional que afecta al modelo (H-4)

El XSD expresa cardinalidad, no condicionalidad. Estas condiciones afectan al MVP y
**deberán validarse en la capa de dominio**, no en el esquema:

| Condición | Origen | Efecto |
|---|---|---|
| NC y ND exigen ≥ 1 referencia | XSD: `InformacionReferencia [1..10]` | `DocumentReference` obligatorio según `document_type` |
| `TipoCambio` cuando la moneda no es la local | Anexos | Coherencia entre `currency_code` y `reported_exchange_rate` |
| `Tarifa` obligatoria según el código de impuesto | Anexos, nota 8 | Validación cruzada en `LineTax` |
| `CodigoTarifaIVA` sólo aplica a códigos de IVA | Anexos, nota 8.1 | Validación cruzada |
| Códigos `05` y `06` de tarifa, sólo en NC y ND | Anexos, nota 8.1 | Depende de `document_type` |
| Código `07` de tarifa **inhabilitado** | Anexos, nota 8.1 | Aceptar en histórico, rechazar en emisión futura |
| Código `17` de referencia, exclusivo del REP | Anexos, nota 9 | Fuera del MVP; se registra |
| Código `16` de tipo de referencia, sólo en Factura de Compra | Anexos, nota 10 | Fuera del MVP; se registra |
| `TotalIVADevuelto` sólo con servicios de salud pagados con tarjeta | Anexos | Fuera del MVP |
| El código de referencia determina el periodo contable | Anexos, nota 9, rev. 2026 | **Requisito del Tax Engine** (§16) |

La lista **no es exhaustiva**: H-4 sigue abierto. Recoge lo que afecta al MVP.

---

## 20. Tres capas de validación

```
Capa 1 — XML / XSD              ¿es un comprobante bien formado y válido?
Capa 2 — semántica del dominio  ¿es coherente como documento fiscal?
Capa 3 — Tax Engine             ¿el tratamiento tributario es correcto?
```

| Capa | Qué comprueba | Ejemplos |
|---|---|---|
| **1** | Estructura y tipos | Elementos obligatorios, cardinalidades, patrones de `Clave` y consecutivo, tipos decimales |
| **2** | Coherencia como documento | Las condiciones de §19; que la clave contenga el consecutivo; que el tipo del namespace concuerde con los dígitos 9-10 |
| **3** | Tratamiento tributario | Si la tarifa aplicada corresponde, si la exoneración es válida, si el total declarado coincide con el calculado |

**Un XML válido no implica un tratamiento tributario correcto.** Son preguntas
independientes, y confundirlas llevaría a dar por bueno un comprobante sólo porque
Hacienda lo aceptó estructuralmente.

### 20.1 El receptor: por qué el modelo no debe codificar la condición

Es el ejemplo más claro de la separación entre capa 1 y capa 2.

```
modelo lógico común       receiver 0..1        ← permite los tres tipos
validación semántica      ¿debe existir?       ← depende de document_type y ruleset
```

El modelo permite que falte porque **debe** permitirlo: en NC y ND el receptor es
condicional. Si el modelo lo exigiera, rechazaríamos documentos que Hacienda acepta.

Pero «condicional» no significa «opcional a voluntad»: pasa a obligatorio en
determinadas operaciones. Esa regla vive en la **capa 2**, donde puede consultar el tipo
de documento, el *ruleset* aplicable y el resto del contenido.

**Generalización.** No se intenta codificar las condiciones de Hacienda mediante
cardinalidades rígidas del modelo común. Un modelo compartido por varios tipos de
documento debe adoptar la cardinalidad **más permisiva** del conjunto, y delegar la
condición a la validación semántica. Lo contrario obliga a un modelo por tipo, o a
rechazar documentos válidos.

Ninguna capa se implementa en E1.

---

## 21. Convención `reported_*`

**Regla propuesta.** Lleva prefijo `reported_` todo campo que:

1. contenga un **importe, cantidad, tarifa o total**; **y**
2. pueda tener algún día un homólogo `computed_*`.

**No** lo llevan los identificadores, códigos de catálogo, fechas ni descripciones: no
hay una versión «calculada» de una clave o de un código CABYS, y prefijarlos añadiría
ruido sin distinguir nada.

`DocumentParty` y `SourceDocument` son **inequívocamente reportados en su totalidad**: no
contienen importes y su naturaleza de instantánea es explícita. No se prefijan.

En `DocumentReference` sí se prefijan `reported_number` y `reported_reference_date`,
porque conviven con `resolved_document_id`, que es conclusión nuestra (§10.6).

Los campos derivados por nosotros que **no** son cálculo fiscal —`direction`,
`ruleset_revision`— no llevan `computed_`: ese prefijo se reserva al Tax Engine, para
que su aparición signifique siempre lo mismo.

---

## 22. Entidades fuera del MVP, ya diseñadas

Se especifican para que su ausencia sea una decisión y no un olvido, y para que quien
las implemente no rehaga el análisis.

### `DocumentPayment` — `ResumenFactura/MedioPago [0..4]`
Categoría B en E0. Campos: `payment_type_code` (catálogo de 8), `other_payment_type`
(sólo con código `99`), `reported_amount`, `sequence`.
**No confundir con el Recibo Electrónico de Pago**, que es un tipo de comprobante
distinto, con su propio esquema y su propio código `10`.

### `DocumentCharge` — `OtrosCargos [0..15]`
Categoría B. Campos: `charge_type_code`, `description`, `reported_amount`,
`reported_percentage`, e identificación del tercero cuando exista. La afectan las
correcciones C-1.

### `DocumentTaxSummary` — `TotalDesgloseImpuesto [0..1000]`
Categoría B. Desglose de impuestos a nivel de documento. Afectada por C-1.

### `PartyContact` — ubicación, teléfono y correos
Categoría B. **Colección**, nunca campos planos (§5.1).

### `TaxExemption` — `Exoneracion [0..1]` por impuesto
Categoría B. Entidad propia dependiente de `LineTax` (§10.4).

### `TaxAuthorityMessage`
Ciclo de vida propio (§15).

---

## 23. Qué queda sin decidir

| Asunto | Estado |
|---|---|
| Tipos, precisiones e índices de PostgreSQL | E2 |
| Restricciones de unicidad concretas | E2 |
| Algoritmo de huella y almacenamiento del XML | **H-6** — abierto **al cerrar E1**; diferido deliberadamente a E2. **Estado actual: CERRADO PARA EL MVP** (`raw_xml BYTEA` + `content_sha256 BYTEA`, SHA-256 de los bytes exactos, en PostgreSQL). Ver [FISCAL_PHYSICAL_MODEL.md](FISCAL_PHYSICAL_MODEL.md) §8 |
| Catálogos externos: CABYS, moneda, ubicación | **H-3**, abierto — §11 fija cómo se tratan sin resolverlos |
| Semántica condicional completa | **H-4**, abierto — §19 recoge lo que afecta al MVP |
| Algoritmo de detección del *ruleset* | Abierto por diseño (§9) |
| Nombres definitivos de entidades y campos | Conceptuales; se fijan en E2 |
| Correcciones C-1 y C-2 | **Propuestas**, pendientes de aprobación (§12) |

---

## 24. Resumen de entidades y cardinalidades

| Entidad | Padre | Cardinalidad | En MVP | Identidad |
|---|---|---|---|---|
| `SourceDocument` | `Company` | 1..N por empresa | ✅ | interna |
| `ElectronicDocument` | — *(no es hijo de `SourceDocument`; ver §3.2)* | `SourceDocument` **1..N** ↔ `ElectronicDocument` **0..1** | ✅ | interna + `clave` única por empresa |
| `DocumentParty` | `ElectronicDocument` | **1..2** — `issuer` exactamente 1, `receiver` 0..1 | ✅ | interna, discriminada por `role` |
| `DocumentLine` | `ElectronicDocument` | 0..N (máx. 1000) | ✅ | interna |
| `LineDiscount` | `DocumentLine` | **0..5** | ✅ | interna + `sequence` |
| `LineTax` | `DocumentLine` | **1..1000** (mín. 1) | ✅ | interna + `sequence` |
| `DocumentReference` | `ElectronicDocument` | **0..10** | ✅ | interna + `sequence` |
| `DocumentPayment` | `ElectronicDocument` | 0..4 | ⏳ B | — |
| `DocumentCharge` | `ElectronicDocument` | 0..15 | ⏳ B | — |
| `DocumentTaxSummary` | `ElectronicDocument` | 0..1000 | ⏳ B | — |
| `PartyContact` | `DocumentParty` | 0..N | ⏳ B | — |
| `TaxExemption` | `LineTax` | 0..1 | ⏳ B | — |
| `TaxAuthorityMessage` | `ElectronicDocument` | 0..N | ⏳ futuro | — |

**Siete entidades en el MVP.** Las seis restantes quedan especificadas (§22) pero no
forman parte del alcance.

---

## 25. Mapeo — los 67 nodos auditados

Los 67 nodos que E0 clasificó `MVP normalizado`, auditados uno a uno con su destino
lógico. Ocho salen del conjunto MVP por la errata de §12; los **59** restantes son la
clasificación canónica. **Ninguno desaparece**: los ocho marcados con corrección propuesta (§12) quedan sin entidad
precisamente porque su lugar no existe en el MVP, y eso es el hallazgo, no una omisión.

| # | XML Path | Entidad lógica | Campo lógico | Req/Opc | Notas |
|---|---|---|---|---|---|
| 1 | `FE/Clave` | ElectronicDocument | clave | Obligatorio | Clave natural oficial, 50 dígitos. Identidad natural (§6) |
| 2 | `FE/ProveedorSistemas` | — | — | — | **Corrección propuesta C-2**: a `raw-only`. Ver §12 |
| 3 | `FE/CodigoActividadEmisor` | ElectronicDocument | issuer_economic_activity_code | Obligatorio | Código de **exactamente 6 caracteres** (el XSD no exige dígitos). Se guarda como código (§11) |
| 4 | `FE/CodigoActividadReceptor` | ElectronicDocument | receiver_economic_activity_code | Opcional | Tri-estado: ausente ≠ vacío |
| 5 | `FE/NumeroConsecutivo` | ElectronicDocument | consecutive_number | Obligatorio | 20 dígitos. Redundante con `clave[22:41]`: se conserva para verificación cruzada |
| 6 | `FE/FechaEmision` | ElectronicDocument | issued_at + issued_at_offset + issued_at_raw | Obligatorio | Tres representaciones del mismo dato (§8) |
| 7 | `FE/Emisor` | DocumentParty | — | Obligatorio | Contenedor → una fila con `role = issuer` |
| 8 | `FE/Emisor/Nombre` | DocumentParty | legal_name | Obligatorio |  |
| 9 | `FE/Emisor/Identificacion` | DocumentParty | — | Obligatorio | Contenedor |
| 10 | `FE/Emisor/Identificacion/Tipo` | DocumentParty | identification_type_code | Obligatorio | Código de catálogo |
| 11 | `FE/Emisor/Identificacion/Numero` | DocumentParty | identification_number | Obligatorio | **Texto, no número**: admite alfanuméricos (revisión 2026) |
| 12 | `FE/Emisor/NombreComercial` | DocumentParty | trade_name | Opcional |  |
| 13 | `FE/Receptor` | DocumentParty | — | Obligatorio | Contenedor → una fila con `role = receiver` |
| 14 | `FE/Receptor/Nombre` | DocumentParty | legal_name | Obligatorio | Misma entidad, distinto `role` |
| 15 | `FE/Receptor/Identificacion` | DocumentParty | — | Obligatorio | Contenedor |
| 16 | `FE/Receptor/Identificacion/Tipo` | DocumentParty | identification_type_code | Obligatorio |  |
| 17 | `FE/Receptor/Identificacion/Numero` | DocumentParty | identification_number | Obligatorio |  |
| 18 | `FE/Receptor/NombreComercial` | DocumentParty | trade_name | Opcional |  |
| 19 | `FE/CondicionVenta` | ElectronicDocument | sale_condition_code | Obligatorio | Código de catálogo (14 valores) |
| 20 | `FE/PlazoCredito` | ElectronicDocument | credit_term | Opcional | Entero. Tri-estado |
| 21 | `FE/DetalleServicio` | — | — | — | Contenedor sin contenido propio: absorbido por la colección `DocumentLine` |
| 22 | `FE/DetalleServicio/LineaDetalle` | DocumentLine | — | 1..1000 | Cada ocurrencia es una fila |
| 23 | `FE/DetalleServicio/LineaDetalle/NumeroLinea` | DocumentLine | line_number | Obligatorio | Orden reportado; no es la identidad |
| 24 | `FE/DetalleServicio/LineaDetalle/CodigoCABYS` | DocumentLine | cabys_code | Obligatorio | Código externo sin FK obligatoria (§11) |
| 25 | `FE/DetalleServicio/LineaDetalle/CodigoComercial/Tipo` | — | — | — | **Corrección propuesta C-1**: huérfano, contenedor es `normalizar después` |
| 26 | `FE/DetalleServicio/LineaDetalle/CodigoComercial/Codigo` | — | — | — | **Corrección propuesta C-1**: huérfano |
| 27 | `FE/DetalleServicio/LineaDetalle/Cantidad` | DocumentLine | reported_quantity | Obligatorio | Decimal exacto (16,3) |
| 28 | `FE/DetalleServicio/LineaDetalle/UnidadMedida` | DocumentLine | unit_of_measure_code | Obligatorio | Catálogo de 101 valores |
| 29 | `FE/DetalleServicio/LineaDetalle/Detalle` | DocumentLine | description | Obligatorio |  |
| 30 | `FE/DetalleServicio/LineaDetalle/PrecioUnitario` | DocumentLine | reported_unit_price | Obligatorio | Decimal exacto (18,5) |
| 31 | `FE/DetalleServicio/LineaDetalle/MontoTotal` | DocumentLine | reported_gross_amount | Obligatorio | Antes de descuentos |
| 32 | `FE/DetalleServicio/LineaDetalle/Descuento` | LineDiscount | — | 0..5 | Colección, **no** un campo único (§10) |
| 33 | `FE/DetalleServicio/LineaDetalle/Descuento/MontoDescuento` | LineDiscount | reported_amount | Obligatorio |  |
| 34 | `FE/DetalleServicio/LineaDetalle/Descuento/CodigoDescuento` | LineDiscount | discount_code | Obligatorio | Catálogo de 10 valores |
| 35 | `FE/DetalleServicio/LineaDetalle/SubTotal` | DocumentLine | reported_subtotal | Obligatorio | Tras descuentos |
| 36 | `FE/DetalleServicio/LineaDetalle/BaseImponible` | DocumentLine | reported_taxable_base | Obligatorio |  |
| 37 | `FE/DetalleServicio/LineaDetalle/Impuesto` | LineTax | — | 1..1000 | Colección **obligatoria**: toda línea lleva ≥1 impuesto |
| 38 | `FE/DetalleServicio/LineaDetalle/Impuesto/Codigo` | LineTax | tax_code | Obligatorio | Catálogo de 10 valores |
| 39 | `FE/DetalleServicio/LineaDetalle/Impuesto/CodigoTarifaIVA` | LineTax | vat_rate_code | Opcional | Catálogo de 11 valores |
| 40 | `FE/DetalleServicio/LineaDetalle/Impuesto/Tarifa` | LineTax | reported_rate | Opcional | Decimal (4,2). **Reportada, no aplicada por nosotros** |
| 41 | `FE/DetalleServicio/LineaDetalle/Impuesto/Monto` | LineTax | reported_amount | Obligatorio |  |
| 42 | `FE/DetalleServicio/LineaDetalle/ImpuestoNeto` | DocumentLine | reported_net_tax | Obligatorio |  |
| 43 | `FE/DetalleServicio/LineaDetalle/MontoTotalLinea` | DocumentLine | reported_line_total | Obligatorio |  |
| 44 | `FE/OtrosCargos/IdentificacionTercero/Tipo` | — | — | — | **Corrección propuesta C-1**: huérfano |
| 45 | `FE/OtrosCargos/IdentificacionTercero/Numero` | — | — | — | **Corrección propuesta C-1**: huérfano |
| 46 | `FE/OtrosCargos/Detalle` | — | — | — | **Corrección propuesta C-1**: huérfano |
| 47 | `FE/ResumenFactura` | ElectronicDocument | — | Obligatorio | Contenedor: sus campos se aplanan en `ElectronicDocument` (§7) |
| 48 | `FE/ResumenFactura/CodigoTipoMoneda` | ElectronicDocument | — | Obligatorio | Contenedor |
| 49 | `FE/ResumenFactura/CodigoTipoMoneda/CodigoMoneda` | ElectronicDocument | currency_code | Obligatorio | ISO 4217 según catálogo oficial |
| 50 | `FE/ResumenFactura/CodigoTipoMoneda/TipoCambio` | ElectronicDocument | reported_exchange_rate | Obligatorio | Decimal exacto |
| 51 | `FE/ResumenFactura/TotalGravado` | ElectronicDocument | reported_total_taxed | Opcional | **Tri-estado** (§9) |
| 52 | `FE/ResumenFactura/TotalExento` | ElectronicDocument | reported_total_exempt | Opcional | **Tri-estado** |
| 53 | `FE/ResumenFactura/TotalExonerado` | ElectronicDocument | reported_total_exonerated | Opcional | **Tri-estado** |
| 54 | `FE/ResumenFactura/TotalNoSujeto` | ElectronicDocument | reported_total_not_subject | Opcional | **Tri-estado** |
| 55 | `FE/ResumenFactura/TotalVenta` | ElectronicDocument | reported_total_sale | Obligatorio |  |
| 56 | `FE/ResumenFactura/TotalDescuentos` | ElectronicDocument | reported_total_discount | Opcional | **Tri-estado** |
| 57 | `FE/ResumenFactura/TotalVentaNeta` | ElectronicDocument | reported_total_net_sale | Obligatorio |  |
| 58 | `FE/ResumenFactura/TotalDesgloseImpuesto/Codigo` | — | — | — | **Corrección propuesta C-1**: huérfano |
| 59 | `FE/ResumenFactura/TotalDesgloseImpuesto/CodigoTarifaIVA` | — | — | — | **Corrección propuesta C-1**: huérfano |
| 60 | `FE/ResumenFactura/TotalImpuesto` | ElectronicDocument | reported_total_tax | Opcional | **Tri-estado**. Convive con futuro `computed_total_tax` |
| 61 | `FE/ResumenFactura/TotalComprobante` | ElectronicDocument | reported_total_document | Obligatorio |  |
| 62 | `FE/InformacionReferencia` | DocumentReference | — | 0..10 | Entidad de primer nivel (§10) |
| 63 | `FE/InformacionReferencia/TipoDocIR` | DocumentReference | referenced_document_type_code | Obligatorio | Catálogo de 20 valores (rev. 2026) |
| 64 | `FE/InformacionReferencia/Numero` | DocumentReference | reported_number | **Opcional** | Por eso no puede haber FK obligatoria (§10.2) |
| 65 | `FE/InformacionReferencia/FechaEmisionIR` | DocumentReference | reported_reference_date | Obligatorio | Puede llevar el periodo fiscal, no la fecha real (nota 10, código 13) |
| 66 | `FE/InformacionReferencia/Codigo` | DocumentReference | reference_code | Opcional | **Determina el periodo contable** (§10.3) |
| 67 | `FE/InformacionReferencia/Razon` | DocumentReference | reason | Opcional |  |

### Cobertura

```
67   nodos auditados  (conjunto MVP de E0)
 ─8  reclasificados fuera del MVP  (§12.3)
───
59   permanecen en el modelo lógico MVP
```

Dentro de esos 59 —no sumados a ellos—:

| | Nodos | Representación |
|---|---|---|
| Campos con valor | **48** | Atributo de una entidad |
| Nodos estructurales | **11** | Contenedores: aportan relación y cardinalidad, no atributo |
| **Total** | **59** | |

```
0 sin explicar    ·    0 perdidos    ·    67 / 67 contabilizados
```

Transformaciones que no son uno-a-uno: `FechaEmision` se expande en tres campos lógicos
(§8); `Emisor` y `Receptor` se funden en una sola entidad `DocumentParty` discriminada
por `role` (§5).
