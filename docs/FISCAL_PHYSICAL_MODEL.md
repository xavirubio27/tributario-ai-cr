# FISCAL_PHYSICAL_MODEL — Diseño físico PostgreSQL del esquema fiscal

> **Estado:** Fase E2 — **diseño físico**. **COMPLETED** — auditoría final de Codex
> `CRITICAL 0 · HIGH 0 · MEDIUM 0 · LOW 0`, PASS. Decisiones recogidas en **ADR-032 … ADR-038**,
> todas aceptadas. **Implementación: E3.**
>
> **No hay migración, ni SQL ejecutado, ni tablas creadas.** Este documento es el diseño
> que E3 convertirá en migración. Los fragmentos de DDL que aparecen son **ilustrativos**,
> para poder revisar una restricción concreta; no son el artefacto de implementación.
>
> **Fuentes:** [FISCAL_LOGICAL_MODEL.md](FISCAL_LOGICAL_MODEL.md) (E1, aprobada) y
> [FISCAL_DOMAIN.md](FISCAL_DOMAIN.md) (E0, aprobada). Ninguna decisión aceptada se
> reabre.

---

## 1. Ubicación y frontera

Todas las tablas de producto viven en el schema **`fiscal`**, nunca en `public`.

Se respeta [ADR-020](DECISIONS.md#adr-020) sin modificarlo:

```
fiscal          NO expuesto por la Supabase Data API
authenticated   sin acceso fiscal
FastAPI         SET ROLE fiscal_backend → identidad transaccional → RLS fiscal
```

El schema ya existe y está vacío; los roles y privilegios de frontera están aplicados
desde el Checkpoint D.

---

## 2. Verificaciones realizadas contra la base de datos real

Antes de proponer nada se comprobó el estado real, no el supuesto:

| Verificación | Resultado |
|---|---|
| `public.companies.id` | **`uuid`**, `DEFAULT gen_random_uuid()`, PK |
| `companies.created_by` | FK a `auth.users(id)` **`ON DELETE RESTRICT`** — precedente del proyecto |
| `private.is_company_member` | `(p_company_id uuid) → boolean`, `SECURITY DEFINER`, `STABLE` |
| Patrón RLS existente | `USING (private.is_company_member(id))` |
| `numeric(18,5)` | Almacena exactamente `9999999999999.99999`; desborda con un dígito más |
| Resto de tipos decimales | `numeric(16,3)`, `(4,2)`, `(5,4)`, `(10,5)`, `(9,5)` cubren sus máximos XSD |

**Advertencia descubierta al verificar:** PostgreSQL **redondea en silencio** los
decimales excedentes (`1.123456::numeric(18,5)` → `1.12346`) en lugar de rechazarlos. El
XSD ya prohíbe ese exceso, así que la captura corresponde a la **capa 1** de validación
([ADR-030](DECISIONS.md#adr-030)); la base de datos no avisará. Conviene saberlo antes de
confiar en que el tipo protege por sí solo.

---

## 3. Identidad interna

**Propuesta: `id uuid PRIMARY KEY DEFAULT gen_random_uuid()`.**

| Alternativa | Valoración |
|---|---|
| `uuid` generado por la **base de datos** | **Elegida.** Coherente con `public.companies`, que ya lo hace. Una sola fuente de identificadores, sin depender de que la aplicación acierte |
| `uuid` generado por la aplicación | Permitiría construir el grafo del documento antes de insertar. Pero introduce una segunda fuente de identidad y deja la unicidad en manos del cliente |
| `bigint` / `identity` | Más compacto y con índices más pequeños, pero los identificadores secuenciales **filtran volumen** —cuántos documentos tiene el sistema, y con dos peticiones, a qué ritmo crece—. En un SaaS multiempresa con datos fiscales, eso es información que no debemos regalar |

Sobre el coste: un índice sobre `uuid` es mayor que sobre `bigint`, y el orden aleatorio
fragmenta más. Es un coste real y asumido: a la escala del MVP no es el cuello de
botella, y la consistencia con el esquema existente vale más.

**La `Clave` no es clave primaria.** Se mantiene la separación de E1:

```
identidad interna   ≠   Clave oficial
```

Tres razones concretas: la `Clave` son 50 caracteres que se repetirían en cada línea,
impuesto y descuento; un documento puede existir con la clave aún sin validar; y una PK
natural de 50 bytes infla todos los índices que la referencian.

---

## 4. Nombres físicos

```
fiscal.source_documents
fiscal.electronic_documents
fiscal.document_parties
fiscal.document_lines
fiscal.line_discounts
fiscal.line_taxes
fiscal.document_references
```

Se adoptan los nombres propuestos. Son claros, en plural como `public.companies` y
`public.company_memberships`, sin abreviaturas, y coinciden con las entidades lógicas de
E1 — que alguien pueda leer `FISCAL_LOGICAL_MODEL.md` y encontrar la tabla sin traducir
nombres tiene valor por sí mismo.

Columnas en `snake_case` inglés, conforme a las convenciones del proyecto.

---

## 5. Seguridad de tenant: cómo la base de datos la garantiza

Es la decisión estructural más importante de E2.

E1 fijó el invariante: *toda entidad fiscal hija pertenece al mismo tenant que su padre*.
Repetir `company_id` en cada tabla no basta — permite que un hijo declare un tenant y
apunte a un padre de otro.

**Propuesta: claves foráneas compuestas sobre un único compuesto.**

```sql
-- ilustrativo, no es la migración
create table fiscal.electronic_documents (
    id          uuid not null default gen_random_uuid(),
    company_id  uuid not null references public.companies(id) on delete restrict,
    ...
    primary key (id),
    unique (company_id, id)          -- ← habilita la FK compuesta de los hijos
);

create table fiscal.document_lines (
    id                     uuid not null default gen_random_uuid(),
    company_id             uuid not null,
    electronic_document_id uuid not null,
    ...
    primary key (id),
    unique (company_id, id),
    foreign key (company_id, electronic_document_id)
        references fiscal.electronic_documents (company_id, id)
        on delete cascade
);
```

**Qué consigue.** Insertar una línea de la empresa A apuntando a un documento de la
empresa B es **imposible**: la pareja `(company_id, electronic_document_id)` no existiría
en el índice único del padre. No depende de que FastAPI acierte, ni de RLS, ni de una
revisión de código. Es aritmética del motor.

**Coste asumido.** Un índice único adicional por tabla padre y una columna redundante por
tabla hija. A cambio, una clase entera de fuga entre contribuyentes deja de ser posible.
Nos parece un intercambio evidente para datos fiscales.

### 5.1 Los dos enlaces opcionales: `ON DELETE SET NULL` **de columna**

Los dos enlaces nullable no pueden usar `ON DELETE SET NULL` a secas: intentaría anular
**también `company_id`**, que es `NOT NULL`, y el borrado fallaría.

PostgreSQL 15+ permite acotar la acción a un subconjunto de columnas. DDL conceptual
final:

```sql
-- fiscal.source_documents
foreign key (company_id, electronic_document_id)
    references fiscal.electronic_documents (company_id, id)
    on delete set null (electronic_document_id)

-- fiscal.document_references
foreign key (company_id, resolved_document_id)
    references fiscal.electronic_documents (company_id, id)
    on delete set null (resolved_document_id)
```

`company_id` permanece **`NOT NULL` e intacto**.

### 5.2 `MATCH SIMPLE` — comportamiento verificado

Ambas FK usan la semántica por defecto, **`MATCH SIMPLE`**: la restricción no se comprueba
si *alguna* columna de la clave es `NULL`.

```
optional_id IS NULL       →  relación ausente, válida
optional_id IS NOT NULL   →  (company_id, optional_id) debe existir completo
                             en la tabla destino, es decir en el MISMO tenant
```

**No debilita el aislamiento.** El caso «`NULL` no se comprueba» sólo puede darse por la
columna opcional, porque `company_id` es `NOT NULL` y nunca puede ser el nulo que exime la
comprobación. Cuando hay enlace, la pareja completa debe existir.

**Verificado empíricamente** contra PostgreSQL 17.6 en DEV, con tablas temporales dentro
de una transacción revertida —sin alterar estado persistente—:

| Comprobación | Resultado |
|---|---|
| Sintaxis `ON DELETE SET NULL (columna)` | **aceptada** por PG 17.6 |
| FK opcional con `NULL` | **permitida** |
| Destino del mismo tenant | **permitido** |
| Destino de **otro tenant** | **rechazado**, `23503 foreign_key_violation` |
| `DELETE` del destino | anula **sólo** la columna opcional |
| `company_id` tras ese `DELETE` | **sin cambios** |
| Carga `bytea` de la fila hija | **intacta** |

Estas seis comprobaciones quedan como **pruebas obligatorias de la implementación**: no
basta con que funcionaran aquí, deben formar parte de la suite de E3.

---

## 6. Relación con `public.companies`

```sql
company_id uuid not null references public.companies(id) on delete restrict
```

`uuid` porque el esquema real lo dice, no por suposición (§2).

**`ON DELETE RESTRICT`, no `CASCADE`.** Borrar una empresa que ya tiene documentos
fiscales no debe ser una operación silenciosa: significaría destruir evidencia tributaria
con una sola sentencia. `RESTRICT` obliga a que alguien decida explícitamente qué hacer
con esos documentos antes de eliminar la empresa.

Coincide además con el precedente del proyecto: `companies.created_by` ya usa `RESTRICT`
contra `auth.users`.

---

## 7. `fiscal.source_documents`

**Propósito.** Conservar el artefacto recibido, interpretable o no.

| Columna | Tipo | Null | Notas |
|---|---|---|---|
| `id` | `uuid` | NOT NULL | PK, `gen_random_uuid()` |
| `company_id` | `uuid` | NOT NULL | FK → `public.companies` `ON DELETE RESTRICT` |
| `ingested_at` | `timestamptz` | NOT NULL | `DEFAULT now()`. **Metadato del sistema**, no fecha del comprobante |
| `ingestion_source` | `text` | NOT NULL | Cómo llegó. Catálogo **interno**, con CHECK de valores propios |
| `parse_status` | `text` | NOT NULL | `pending` · `parsed` · `failed` |
| `parse_error` | `text` | NULL | Diagnóstico cuando falla |
| `schema_detection_status` | `text` | NOT NULL | `pending` · `detected` · `unknown` · `unsupported` · `failed` |
| `detected_document_type` | `text` | NULL | Del namespace raíz. Nulo hasta detectarse |
| `detected_schema_version` | `text` | NULL | Ídem |
| `electronic_document_id` | `uuid` | NULL | El enlace `0..1` (§9) |
| `raw_xml` | `bytea` | NOT NULL | **Bytes originales exactos** (§8.1). Inmutable |
| `content_sha256` | `bytea` | NOT NULL | SHA-256 de `raw_xml`. `CHECK octet_length = 32` y `CHECK = sha256(raw_xml)` (§8.4) |
| `parse_attempted_at` | `timestamptz` | NULL | Último intento (§19) |
| `parse_attempt_count` | `integer` | NOT NULL | `DEFAULT 0`. Detecta reintentos que fallan en silencio |
| `updated_at` | `timestamptz` | NOT NULL | `DEFAULT now()`. Sólo los metadatos de interpretación cambian |

`ingestion_source` y los dos campos de estado son catálogos **nuestros**, no de Hacienda:
aquí sí procede un `CHECK` por valor, porque somos la autoridad y controlamos su
evolución. Es la diferencia exacta con los códigos oficiales (§12).

**No contiene:** ningún valor fiscal interpretado.

**Inmutabilidad de los hechos de origen.** `raw_xml`, `content_sha256`, `ingested_at` y
`company_id` **no se actualizan nunca** tras el `INSERT`. Si el artefacto recibido era
incorrecto, se registra **otro** `SourceDocument`; no se reescriben los bytes históricos.
La protección es la de §25: `fiscal_backend` no recibe `UPDATE` sobre esas columnas.

---

## 8. Almacenamiento del artefacto — **H-6 CERRADO PARA EL MVP**

### 8.1 Decisión: `raw_xml bytea` dentro de PostgreSQL

```sql
raw_xml        bytea not null,
content_sha256 bytea not null
    check (octet_length(content_sha256) = 32)
    check (content_sha256 = pg_catalog.sha256(raw_xml))
```

Se escribe **`pg_catalog.sha256`** calificada, para dejar explícito que se usa la función
**nativa** del motor y no `pgcrypto`. Ni `digest()`, ni `USAGE` sobre `extensions`.

**`bytea`, no `xml` ni `text`.** La fuente canónica son **los bytes originales exactos**:

- El tipo `xml` de PostgreSQL **valida y puede normalizar** el contenido. Un artefacto mal
  formado —que es precisamente el que hay que conservar para investigar— sería rechazado
  al insertar. Y cualquier normalización rompería la huella y la verificabilidad de la
  firma.
- `text` fuerza una codificación y podría alterar bytes en un XML con declaración de
  encoding distinta de la del servidor. Deja de ser el artefacto y pasa a ser una
  interpretación.

`bytea` no interpreta nada: guarda lo que llegó.

### 8.2 Por qué dentro de PostgreSQL y no en Object Storage

| Motivo | |
|---|---|
| **Atomicidad real** | Artefacto y metadatos en la misma transacción. Con Storage, el objeto se sube fuera de la transacción: puede quedar huérfano, o la fila puede apuntar a algo que no se subió |
| **Una sola frontera** | Reutiliza el aislamiento fiscal ya construido y auditado en el Checkpoint D. Storage introduciría una **segunda superficie de acceso** con sus propias políticas que mantener y auditar |
| **Copia de seguridad única** | El artefacto viaja con sus metadatos; no hay dos sistemas que puedan desincronizarse |
| **Reproceso directo** | El parser lee de la misma transacción, sin descarga externa |
| **Simplicidad del MVP** | Menos piezas móviles en el camino crítico de la ingesta |

### 8.3 Esta decisión no es arquitectura eterna

Elegir `bytea` para el MVP **no cierra la puerta** a migrar a almacenamiento de objetos si
el volumen o el coste lo justifican. Esa migración deberá preservar, sin excepción:

```
bytes exactos · huella · procedencia · tenant · inmutabilidad · rastro de auditoría
```

**No se añade ahora `storage_kind` ni ninguna abstracción de almacenamiento.** Sería una
capa de indirección construida para un futuro hipotético, con el coste de complicar hoy lo
que aún no sabemos si cambiará. Cuando haya métricas reales, se decide con ellas delante.

### 8.4 La huella: SHA-256 sobre los bytes exactos

```sql
content_sha256 bytea not null check (octet_length(content_sha256) = 32)
```

### Definición exacta

```
content_sha256  =  SHA-256 de los bytes originales exactos almacenados en raw_xml
```

**Qué demuestra:**

```
misma huella  →  señal criptográficamente muy fuerte de equivalencia de bytes
```

La formulación importa. SHA-256 no es una **prueba matemática** de identidad: dos
secuencias distintas con la misma huella son teóricamente posibles, aunque nadie sepa
construirlas. Para detectar artefactos repetidos es una señal más que suficiente. Cuando
haga falta **certeza** y ambos artefactos estén disponibles, la comparación directa
`raw_xml = raw_xml` la da; la huella evita tener que leer los bytes en el caso común.

En el otro sentido la advertencia es distinta, y en la práctica más importante:

```
huella distinta  ↛  semántica fiscal distinta
```

Dos serializaciones del **mismo comprobante** pueden diferir en bytes sin diferir en
contenido fiscal: espaciado, saltos de línea, orden de atributos, declaración de
codificación, o una envoltura de firma distinta. La huella no distingue esos casos de una
divergencia real, y **tratarla como si lo hiciera produciría falsos conflictos**.

**Qué NO es**, escrito para que nadie lo confunda más adelante:

- no es la firma electrónica del comprobante;
- no es validación XAdES;
- no es una huella sobre forma canónica;
- no es la huella del documento normalizado;
- **no es una prueba de equivalencia lógica entre comprobantes**.

**No se diseña canonicalización propia**, y no existe todavía ninguna «huella canónica del
XML». Inventarla ahora significaría decidir qué diferencias de serialización son
irrelevantes —una decisión que puede invalidar la firma— sin ninguna necesidad que lo
justifique.

**32 bytes crudos, no 64 caracteres hexadecimales.** La mitad de espacio en tabla y en
índice, comparación binaria directa, y ninguna ambigüedad de mayúsculas o minúsculas. La
representación hexadecimal es cosa de la presentación, no del almacenamiento.

`CHECK (octet_length(...) = 32)` impide que se guarde ahí cualquier otra cosa —un hash
distinto, una cadena hex, un valor truncado— sin que nadie lo note.

### 8.5 Dónde se calcula la huella — verificado en DEV

Se comprobó qué puede hacer realmente `fiscal_backend`, en lugar de suponerlo:

| Comprobación | Resultado |
|---|---|
| `pgcrypto` instalado | **Sí**, versión 1.3, en el schema `extensions` |
| `extensions.digest(bytea,'sha256')` | Existe, devuelve 32 bytes, `EXECUTE` concedido a `PUBLIC` |
| `fiscal_backend` → `USAGE` sobre `extensions` | **NO** |
| Llamada real como `fiscal_backend` | **`42501 permission denied for schema extensions`** |
| **`pg_catalog.sha256(bytea)`** | **funciona** como `fiscal_backend`, sin extensión |
| `sha256()` volatilidad | **`IMMUTABLE`** → utilizable en un `CHECK` |
| `pg_catalog.sha256()` = `extensions.digest(...,'sha256')` = `shasum -a 256` | **idénticos**, verificado sobre los mismos bytes |
| `CHECK (content_sha256 = pg_catalog.sha256(raw_xml))` | **aceptado**; admite la huella correcta y rechaza la incorrecta con `23514` |

**Hallazgo que cambia la respuesta.** Usar pgcrypto exigiría conceder `USAGE` sobre
`extensions` a `fiscal_backend`, es decir **ampliar la frontera fiscal** por una función de
hash. Innecesario: PostgreSQL trae `sha256(bytea)` en `pg_catalog` desde la versión 11, ya
alcanzable por el rol y sin tocar ADR-020.

| Opción | Valoración |
|---|---|
| **A** — FastAPI calcula, PostgreSQL almacena | Simple, pero nada impide que un error de código guarde una huella que no corresponde |
| **B** — PostgreSQL calcula por columna generada | Elimina la discrepancia, pero el backend no controla la definición y el cálculo ocurre lejos de donde se decide |
| **C** — FastAPI calcula y PostgreSQL **verifica** | **Elegida** |

**Recomendación: opción C.**

```sql
content_sha256 bytea not null
    check (octet_length(content_sha256) = 32)
    check (content_sha256 = pg_catalog.sha256(raw_xml))   -- ← verificación, no cálculo
```

FastAPI calcula la huella con `hashlib.sha256` sobre los mismos bytes que inserta; la base
de datos comprueba que coincide. Una huella incorrecta **no se puede guardar**, y no
depende de que el backend acierte siempre.

Es posible precisamente porque `pg_catalog.sha256()` es `IMMUTABLE` —requisito de un
`CHECK`— y porque las tres implementaciones producen el mismo valor. **Una única
definición canónica de la huella**, verificada en los dos lados: SHA-256 sobre los bytes
originales exactos.

Comprobado en DEV con tablas temporales revertidas: el `CHECK` acepta la fila cuando la
huella corresponde y la rechaza con `23514 check_violation` cuando no.

*(Que un `CHECK` recalcule el hash en cada inserción tiene un coste. Sobre artefactos de
decenas o cientos de kilobytes es despreciable frente al de escribir el propio `bytea`, y
compra una garantía que ninguna disciplina de código iguala. Si algún día el perfilado
dijera otra cosa, se revisa con datos.)*

### 8.6 Estado de H-6

```
H-6  →  CLOSED FOR MVP
```

Queda resuelto lo que bloqueaba el diseño de `source_documents`: **dónde viven los bytes
y cómo se comprueba su integridad**.

**H-6 no resuelve la equivalencia lógica entre documentos.** Que dos artefactos tengan
huellas distintas no dice nada sobre si representan el mismo comprobante (§8.4). Esa
pregunta pertenece a la deduplicación y a la validación semántica (§15), no al
almacenamiento. **La escalabilidad no es un bloqueante actual**: si el volumen o el
coste lo exigen, la migración a almacenamiento de objetos será una decisión futura basada
en métricas reales, con los requisitos de §8.3.

No se encontró ninguna contradicción técnica en DEV que impida esta solución.

---

## 9. Relación artefacto ↔ documento normalizado

Debe representar:

```
Para cada SourceDocument:      ElectronicDocument  =  0..1
Para cada ElectronicDocument:  SourceDocuments     =  1..N
```

**Propuesta: la clave foránea vive en `source_documents`, y es nullable.**

```sql
-- en fiscal.source_documents
electronic_document_id uuid null,
foreign key (company_id, electronic_document_id)
    references fiscal.electronic_documents (company_id, id)
    on delete set null (electronic_document_id)
```

La acción va **acotada a la columna opcional** (§5.1): `company_id` es `NOT NULL` y un
`set null` sin columnas intentaría anularla también, haciendo fallar el borrado.

Por qué esta dirección y no la contraria:

| Propiedad | Cómo se consigue |
|---|---|
| Un artefacto normaliza a **como máximo uno** | La columna es escalar: no puede apuntar a dos |
| Un artefacto puede normalizar a **ninguno** | La columna es `NULL` mientras el estado sea `pending`, `failed`, `unknown` o `unsupported` |
| Un documento puede provenir de **varios** artefactos | Varias filas de `source_documents` pueden compartir el mismo valor |
| **No** hay FK obligatoria del documento a un artefacto único | `electronic_documents` no tiene columna hacia `source_documents` |

**Se descarta la tabla asociativa.** Modelaría N..N, que es más de lo que el dominio
permite —un artefacto nunca produce dos documentos— y añadiría una tabla, dos claves
foráneas y una consulta más para nada.

**El mínimo `1..N` no es declarativo.** Que todo `ElectronicDocument` tenga al menos un
`SourceDocument` no puede imponerse con una restricción sin un *trigger* diferido. Se
resuelve por **disciplina transaccional**: el documento solo se crea dentro de la
transacción que enlaza su artefacto (§18). Es integridad de aplicación, y conviene
llamarla por su nombre en lugar de fingir que la base la garantiza.

`ON DELETE SET NULL (electronic_document_id)` —acotado a la columna, §5.1—: si algún día
se borrara un documento normalizado, **el artefacto debe sobrevivir** con su `raw_xml`
intacto y su `company_id` sin tocar. Es la evidencia; la normalización es nuestra
interpretación.

---

## 10. `fiscal.electronic_documents`

**Propósito.** El comprobante normalizado. Todo su contenido fiscal es `reported_*`.

Además de las 18 columnas del inventario (§20), lleva:

| Columna | Tipo | Null | Notas |
|---|---|---|---|
| `id` | `uuid` | NOT NULL | PK |
| `company_id` | `uuid` | NOT NULL | FK → `public.companies` `RESTRICT` |
| `document_type` | `text` | NOT NULL | `CHECK IN ('invoice','credit_note','debit_note')` (§11) |
| `ruleset_revision` | `text` | **NULL** | Puede no ser determinable (§13) |
| `ruleset_revision_status` | `text` | NOT NULL | `detected` · `ambiguous` · `resolved` |
| `direction` | `text` | NOT NULL | `issued` · `received` · `unknown` (§14) |
| `direction_computed_at` | `timestamptz` | NOT NULL | Cuándo se derivó; permite recomputar por lotes |
| `created_at` | `timestamptz` | NOT NULL | `DEFAULT now()` |

`schema_version` **no se duplica aquí**: vive en `source_documents.detected_schema_version`,
que es donde E1 la situó — es un hecho sobre el artefacto. Se alcanza por la relación.

**Restricciones:**

```sql
primary key (id),
unique (company_id, id),                    -- habilita las FK compuestas de los hijos
unique (company_id, clave),                 -- identidad lógica por tenant (§15)
check (clave ~ '^[0-9]{50}$'),
check (consecutive_number ~ '^[0-9]{20}$'),
check (document_type in ('invoice','credit_note','debit_note')),
check (direction in ('issued','received','unknown')),
check (ruleset_revision_status in ('detected','ambiguous','resolved'))
```

---

## 11. `document_type`: texto con `CHECK`, no `enum`

**Propuesta: `text` + `CHECK`.**

Un `enum` de PostgreSQL es más compacto y valida igual de bien, pero **alterarlo es una
operación de esquema**: añadir un valor exige `ALTER TYPE`, y quitarlo o reordenarlo es
peor. Vamos a añadir tipos —Tiquete, Factura de Compra, de Exportación, Recibo de Pago
están todos en la hoja de ruta de [ADR-025](DECISIONS.md#adr-025)—, y cada uno sería una
migración de tipo en lugar de una de restricción.

Un `CHECK` sobre `text` se reemplaza con un `ALTER TABLE ... DROP CONSTRAINT` y otro
`ADD CONSTRAINT`, ambos triviales y reversibles.

**Aquí sí procede validar el valor**, a diferencia de los códigos oficiales: `document_type`
es **vocabulario nuestro**, no un catálogo de Hacienda. Nosotros decidimos cuándo crece.

---

## 12. Códigos oficiales: se valida la forma, nunca el valor

**Ningún código de catálogo oficial lleva `CHECK` de valores permitidos.**

No es una preferencia estilística: es una conclusión con evidencia. Al comparar el XSD
publicado con los Anexos vigentes (rev. 22/04/2026) aparece esto:

| Catálogo | Valores en el XSD | Valores en los Anexos 2026 |
|---|---|---|
| `CodigoReferenciaType` | **12** | **17** |
| `TipoDocReferenciaType` | **19** | **20** |

El propio esquema oficial ya está por detrás del documento normativo. Un `CHECK IN (...)`
copiado del XSD **rechazaría hoy comprobantes que Hacienda considera válidos**, y volvería
a romperse en la siguiente revisión.

Lo que sí se valida es la **forma**, que sí es estable:

```sql
check (tax_code ~ '^[0-9]{2}$')
check (cabys_code ~ '^[0-9]{13}$')
```

Es exactamente [ADR-029](DECISIONS.md#adr-029) llevado al motor: el código reportado es la
verdad; el catálogo local es enriquecimiento opcional, sin clave foránea obligatoria.

### 12.1 CABYS — forma canónica

```
Fuente estructural       XSD v4.4  →  xs:string, longitud 13, SIN pattern numérico
Fuente semántica         BCCR CABYS →  producto identificado por 13 DÍGITOS
Representación física    text
CHECK                    cabys_code ~ '^[0-9]{13}$'
Estado                   SUPPORTED
Migración correctiva     NO REQUERIDA
```

**Son dos fuentes distintas y aportan cosas distintas.** El XSD acota la **longitud**; que
los caracteres sean numéricos lo establece el **BCCR**, propietario del catálogo.

**Fuentes primarias del respaldo semántico**, todas del Banco Central de Costa Rica:

| Documento | Qué establece |
|---|---|
| Página oficial CABYS — «Catálogo de bienes y servicios para uso tributario y de Cuentas Nacionales» | La jerarquía: **1 dígito** para las categorías generales, **2** para el nivel siguiente, y así sucesivamente hasta los **13 dígitos** del producto |
| Preguntas frecuentes CABYS | Los productos están «**identificados por 13 dígitos**» |
| Guía oficial del buscador CABYS | Describe el campo Código como «**número de trece dígitos que identifica un producto**» |

Corrobora la conclusión una fuente que además tenemos **verificada localmente**: los
Anexos y Estructuras v4.4 (`sha256 6e093226…`) hablan de «el primer **dígito** del código
CABYS sea 0, 1, 2, 3 y 4 (bienes)» —asignan valor numérico a las posiciones— y su **nota
17** delega expresamente la codificación al catálogo del BCCR.

**No se atribuye «13 dígitos» al XSD.** El XSD aporta la longitud; el respaldo numérico es
del BCCR.

**Esto NO cierra H-3.** Que el *formato* esté confirmado no significa que tengamos el
*catálogo*: sigue sin existir la capa de validación y enriquecimiento contra CABYS y el
RUT. **H-3 continúa ABIERTO** por esa razón, y ADR-029 mantiene que ningún código externo
lleva clave foránea obligatoria a un catálogo local.

*(Trazabilidad: E3 implementó el `CHECK` de 13 dígitos; E4-A y E4-B0 cuestionaron que la
atribución fuera del XSD; la auditoría lo clasificó temporalmente como no demostrado; la
evidencia oficial del BCCR lo confirma. El constraint nunca cambió.)*

### 12.2 Código de actividad económica — forma canónica

`CodigoActividadEmisor` y `CodigoActividadReceptor` son el **caso contrario al de CABYS**:
aquí la fuente estructural acota la longitud y **nadie** impone que los caracteres sean
numéricos.

```
Fuente estructural   XSD v4.4  → xs:string, minLength=6, maxLength=6, SIN pattern numérico
Anexos v4.4          «String 6» + validación contra el padrón del RUT
Capa 1 (BD)          exactamente 6 CARACTERES
Capa 2 (diferida)    validez del código contra RUT / catálogo oficial
```

| Columna | Tipo | Null | `CHECK` vigente |
|---|---|---|---|
| `issuer_activity_code` | `text` | NOT NULL | `char_length(issuer_activity_code) = 6` |
| `receiver_activity_code` | `text` | NULLABLE | `receiver_activity_code IS NULL OR char_length(receiver_activity_code) = 6` |

**No se dice «6 dígitos».** La distinción no es teórica: los dos comprobantes FE 4.4 reales
incorporados en E4-A declaran `CodigoActividadEmisor = "6110.0"` —seis caracteres, con
punto—, que un patrón numérico habría rechazado.

*(Trazabilidad: E3 implementó `~ '^[0-9]{6}$'`, más estricto que la fuente; E4-A lo
detectó contra fixtures reales; la migración `20260830162516_fix_fiscal_activity_code_constraints`
de E4-B0 lo corrigió. La migración de E3 **no se editó**.)*

**La validación semántica contra el RUT sigue diferida** a la capa 2 y no se introduce
aquí ningún catálogo.

---

## 13. `ruleset_revision` puede no conocerse

```sql
ruleset_revision        text  null,
ruleset_revision_status text  not null
    check (ruleset_revision_status in ('detected','ambiguous','resolved'))
```

`NULL` en la revisión es un estado legítimo, no un dato faltante por descuido: durante el
periodo de adopción voluntaria (22-abr-2026 → 1-nov-2026) conviven documentos de igual
versión estructural bajo semánticas distintas ([ADR-026](DECISIONS.md#adr-026)).

El **estado sí es obligatorio**: siempre sabemos si la revisión está determinada, es
ambigua o se resolvió después, aunque no sepamos cuál es.

No se diseña catálogo de revisiones: `text` basta hasta que exista una necesidad real.

---

## 14. `direction`

```sql
direction             text        not null check (direction in ('issued','received','unknown')),
direction_computed_at timestamptz not null
```

**Se persiste**, porque toda consulta de negocio separa ventas de compras y recalcularla
en cada lectura la haría depender de un dato de la empresa que puede cambiar.

**`NOT NULL` con `unknown` explícito**, no nullable. `NULL` significaría «no calculado» y
`unknown` significa «calculado, y no coincide con ninguna de las partes»: son cosas
distintas y confundirlas escondería un fallo de derivación detrás de un caso legítimo.

`direction_computed_at` permite recomputar por lotes cuando se corrija la identidad
tributaria de una empresa, sabiendo qué filas están al día.

**Es metadato derivado, no verdad de origen.** La verdad está en `document_parties`.

---

## 15. Unicidad lógica y conflicto

**Propuesta: `UNIQUE (company_id, clave)`. Nunca `UNIQUE (clave)` global.**

Una unicidad global sería incorrecta por dos motivos independientes:

1. **Contradice el modelo.** Emisor y receptor pueden ser ambos clientes del SaaS, y
   entonces los dos deben tener el comprobante ([ADR-031](DECISIONS.md#adr-031)).
2. **Filtra información entre tenants.** Un error de violación de unicidad revelaría a la
   empresa A que la empresa B ya tiene ese comprobante — un canal lateral construido con
   mensajes de error.

### Qué ocurre con un segundo XML de la misma clave

Es la pregunta que el encargo pide responder, y la respuesta importa:

```
INSERT de un segundo electronic_documents con (company_id, clave) existente
  → 23505 unique_violation
```

**El error es deseable.** La restricción impide el duplicado **y** hace visible el
conflicto en lugar de esconderlo, que es la propiedad que ADR-031 exige.

### 15.1 Los cuatro casos — y qué se puede concluir de cada uno

**Corrección respecto a la primera versión de E2**, que trataba «huella distinta» como
sinónimo de conflicto. No lo es (§8.4): dos serializaciones del mismo comprobante pueden
diferir en bytes sin diferir en contenido fiscal.

| Caso | Condición | Conclusión |
|---|---|---|
| **A** | Misma empresa · misma `content_sha256` | **Señal criptográficamente muy fuerte de equivalencia de bytes.** Indica duplicado de artefacto. Para igualdad exacta con ambos artefactos disponibles: comparar `raw_xml` directamente |
| **B** | Misma empresa · misma `clave` · misma `content_sha256` | **Candidato firme** a duplicado de artefacto y mismo documento lógico |
| **C** | Misma empresa · misma `clave` · **`content_sha256` distinta** | **Artefactos divergentes.** No se puede concluir nada más sin analizar el contenido. **No fusionar automáticamente** |
| **D** | Misma empresa · misma `clave` · **contenido fiscal autoritativo divergente** | **Conflicto de integridad** |

**La distinción entre C y D es el punto.** El caso C es una **observación sobre bytes**;
el D es una **conclusión sobre el documento**. Pasar de C a D exige comparar el contenido
fiscal reportado —clave, consecutivo, fecha, partes, totales, líneas—, no comparar hashes.

Un XML puede diferir en espaciado, orden de atributos, codificación declarada o envoltura
de firma sin que cambie un solo dato fiscal. Clasificar eso como conflicto generaría
falsos positivos y enseñaría al equipo a ignorar la alerta, que es la peor consecuencia
posible de un detector de integridad.

**La única conclusión automática admisible en el caso C es:**

```
no fusionar en silencio
```

Ni `merge`, ni `overwrite`, ni `ON CONFLICT DO UPDATE`. La clasificación como conflicto
(caso D) es una evaluación semántica posterior, y **E2 no diseña ese algoritmo**.

### 15.2 Flujo conceptual ante `23505`

```
1. El SourceDocument se preserva primero, siempre        (transacción A, §18)

2. Al normalizar:
     INSERT electronic_documents
       → posible 23505 sobre (company_id, clave)

3. Ante 23505:
       recuperar el ElectronicDocument existente del mismo tenant
       comparar la evidencia
       clasificar:  candidato a duplicado  /  artefactos divergentes  /  conflicto

4. En ningún caso:  merge  ·  overwrite  ·  ON CONFLICT DO UPDATE
```

El artefacto **ya está a salvo** cuando ocurre el `23505`, así que ninguna clasificación
posterior corre el riesgo de perder evidencia. **No se diseña aquí el algoritmo completo
de comparación.**

**Prohibido `INSERT ... ON CONFLICT DO UPDATE`** en esta tabla. Convertiría un conflicto
de integridad en una sobrescritura silenciosa, escogiendo una versión al azar y
destruyendo la evidencia de que hubo discrepancia. Si en algún momento se usa
`ON CONFLICT`, sólo puede ser `DO NOTHING` con manejo explícito posterior.

No se diseña tabla ni flujo de conflictos: E2 sólo garantiza que **no se pueda esconder**.

---

## 16. Deduplicación de artefactos

```
company_id + content_sha256
```

es la señal de equivalencia entre artefactos. Su definición ya está cerrada (§8):
`content_sha256 bytea`, SHA-256 sobre los bytes originales exactos, con
`CHECK (content_sha256 = pg_catalog.sha256(raw_xml))`.

**No lleva `UNIQUE`, y no por prudencia sino por diseño.** Los mismos bytes pueden
corresponder a **dos eventos de ingesta legítimos**, con procedencia y momento distintos —
el mismo comprobante reenviado por correo y recibido después por API—. Conservar ambos
artefactos es exactamente lo que [ADR-031](DECISIONS.md#adr-031) describe; una restricción
de unicidad lo impediría.

La deduplicación es por tanto una **consulta previa a la inserción**, no una prohibición, y
se apoya en un índice **no único** sobre `(company_id, content_sha256)` (§27). Dos
`SourceDocument` idénticos **no se colapsan automáticamente**.

Lo que la huella permite concluir y lo que no está en §8.4; los cuatro casos de
deduplicación, en §15.1.

---

## 17. Fecha y hora

**Propuesta: opción C — instante + desplazamiento + valor literal.**

```sql
issued_at                timestamptz not null,
issued_at_offset_minutes smallint    not null
    check (issued_at_offset_minutes between -840 and 840),
issued_at_raw            text        not null
```

**Rango `−840 .. +840`, no `±1440`.** XML Schema limita el desplazamiento de `xs:dateTime`
a `−14:00 .. +14:00`, es decir **±840 minutos**. Un rango de ±1440 admitiría valores que
el propio esquema rechaza, y una restricción que acepta lo inválido no restringe nada.

Se sigue almacenando el **desplazamiento reportado**, no una zona horaria IANA inferida, y
no se codifica UTC−6 en ninguna parte.

| Columna | Qué preserva |
|---|---|
| `issued_at` | El **instante**. Ordena, compara y filtra por rango correctamente |
| `issued_at_offset_minutes` | El **desplazamiento declarado**. Permite reconstruir el día local del emisor |
| `issued_at_raw` | El **valor literal** del XML. Trazabilidad exacta y reproceso |

Por qué no bastan las opciones más simples:

- **A (`timestamptz` solo)** pierde el desplazamiento. Y el desplazamiento es información
  fiscal: determina a qué día local pertenece el comprobante, que puede diferir del día
  UTC. Para un comprobante emitido a las 23:30 hora local, el día cambia.
- **B (instante + desplazamiento)** ya sirve para operar, pero no permite demostrar qué
  decía exactamente el documento. `issued_at_raw` cuesta una columna de texto y da
  auditoría literal — barato para lo que aporta.

**No se codifica UTC−6 en ninguna parte.** El desplazamiento se toma del documento; un
comprobante de exportación puede declarar otro.

### 17.1 `FechaEmisionIR` recibe el mismo tratamiento

**Corrección respecto a la primera versión de E2**, que reducía la fecha de referencia a
un solo `timestamptz` y perdía información. El argumento de que «es una fecha referida a
otro documento» no la hace menos fiscal: al contrario, el código `13` de la nota 10
—«facturación mes vencido»— exige indicar ahí **el periodo fiscal al que pertenece el
ingreso**, no la fecha real. Es justo el campo donde el literal importa.

```sql
reported_reference_date                  timestamptz not null,
reported_reference_offset_minutes        smallint    not null
    check (reported_reference_offset_minutes between -840 and 840),
reported_reference_date_raw              text        not null
```

**Las tres son `NOT NULL`, y no lleva `CHECK` de coherencia entre ellas.** Verificado
contra la fuente oficial antes de decidirlo:

- El XSD declara `FechaEmisionIR [1..1]` dentro de `InformacionReferencia`.
- Los Anexos v4.4 le asignan condición **`1 1 1 1 1 1 1`** —obligatorio en los siete tipos
  de comprobante— con la nota: «Este campo será de condición obligatoria, cuando se incluya
  información en el campo "Tipo de documento de referencia"», y `TipoDocIR` es a su vez
  obligatorio dentro del nodo.

Es decir: **si existe la fila de referencia, la fecha existe siempre**. La opcionalidad
está en el nodo `InformacionReferencia [0..10]`, que se representa por la ausencia de fila,
no por columnas nulas.

Un `CHECK` del tipo «las tres nulas o las tres pobladas» **describiría una opcionalidad que
la fuente no tiene**. No se añade: sería inventar obligatoriedad condicional donde hay
obligatoriedad simple.

*(Nota para la capa 2, relacionada con H-4: los Anexos añaden una validación que la base
de datos no impone — «se verificará que la fecha de referencia no supere una antigüedad de
10 años».)*

---

## 18. Atomicidad de la ingesta

**Propuesta: dos transacciones, no una.**

```
Transacción A   preservar el artefacto
                INSERT source_documents (parse_status='pending')
                COMMIT                          ← el artefacto ya está a salvo

Transacción B   normalizar
                INSERT electronic_documents
                     + document_parties + document_lines
                     + line_discounts + line_taxes + document_references
                UPDATE source_documents SET electronic_document_id, parse_status='parsed'
                COMMIT                          ← todo o nada
```

**Por qué separadas.** Con una sola transacción, un fallo de normalización haría
`ROLLBACK` de todo —incluido el artefacto—, y perderíamos exactamente el caso que hay que
investigar. Contradiría el invariante de E1: *no poder interpretar un artefacto nunca
impide conservarlo*.

**Por qué la B es indivisible.** Un documento con la mitad de sus líneas sería peor que no
tenerlo: produciría totales incorrectos sin ninguna señal de que está incompleto. La
transacción B es también donde se satisface el mínimo `1..N` de §9.

Si B falla: el artefacto queda con `parse_status='failed'` y su diagnóstico, y no existe
ningún documento parcial.

---

## 19. Reproceso

Un artefacto `failed` debe poder normalizarse más tarde, cuando el parser mejore, **sin
duplicar el artefacto ni borrar el historial**.

Lo que el diseño ya permite, sin columnas nuevas:

- `parse_status` vuelve a `pending` y se reintenta; `parse_error` se sustituye.
- `electronic_document_id` pasa de `NULL` a poblado en la transacción B.
- El artefacto **nunca se reinserta**: su `id` e `ingested_at` no cambian.

Lo que sí conviene registrar, y se propone: `parse_attempted_at` y `parse_attempt_count`
en `source_documents`, para saber si algo lleva reintentándose y fallando en silencio.

### 19.1 Normalización que resultó incorrecta

Caso distinto del anterior, y más incómodo:

```
SourceDocument preservado correctamente
        ↓
el parser tuvo éxito en su momento
        ↓
después se descubre que la proyección normalizada era incorrecta
por un defecto del parser
```

Aquí ya existe un `ElectronicDocument` completo, con sus partes, líneas, impuestos y
referencias — todo mal.

**El camino normal de `fiscal_backend` no debe «arreglarlo» editando hechos de origen.**
Sería reescribir lo que el documento decía para que coincida con lo que ahora creemos, que
es precisamente lo que [ADR-023](DECISIONS.md#adr-023) prohíbe.

Se formaliza una **reconstrucción privilegiada de la proyección normalizada**, fuera del
camino normal de la aplicación, con estas propiedades:

1. `raw_xml` y `content_sha256` del `SourceDocument` permanecen **intactos**.
2. `fiscal_backend` sigue **sin `DELETE`** en el camino normal.
3. El agregado normalizado incorrecto sólo puede eliminarse y reconstruirse mediante una
   **operación privilegiada y explícita**.
4. `ON DELETE SET NULL (electronic_document_id)` preserva los `SourceDocument` al eliminar
   el `ElectronicDocument`: los artefactos sobreviven con su enlace a `NULL`.
5. La reconstrucción vuelve a producir el agregado **atómicamente**, como la transacción B
   de §18.
6. El `SourceDocument` original se **vuelve a enlazar** al resultado correcto.
7. La operación debe ser **auditable antes de llegar a producción**.

**No se diseña aquí la tabla de auditoría**, ni se decide si hace falta un rol nuevo. Lo
que sí queda fijado: **esta capacidad no se concede a `owner`, `editor` ni `viewer`**. No
es una función del producto; es una operación de mantenimiento.

Que el punto 4 funcione no es una suposición: se verificó empíricamente en §5.2 —al borrar
el destino, la carga `bytea` de la fila hija quedó intacta.

**Aquí se cruza una línea que conviene marcar.** `source_documents` es inmutable en su
**contenido de origen** —artefacto, huella, momento de ingesta, empresa—, pero sus
**metadatos de interpretación** —estado, diagnóstico, enlace, contadores— cambian por
definición. La inmutabilidad se predica de los hechos, no de nuestras conclusiones sobre
ellos (§22).

---

## 20. Matriz de tipos — los 48 campos con valor

Los 48 campos con valor del mapeo lógico de E1, cada uno con su decisión física.
Los 11 nodos estructurales **no aparecen**: son relaciones y cardinalidad, no columnas.

| # | XML Path | Tabla | Columna | Tipo PostgreSQL | Null | Default | Tipo fuente | CHECK | Razón |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `FE/Clave` | `electronic_documents` | `clave` | `text` | NOT NULL | — | `ClaveType` `\d{50}` | `~ '^[0-9]{50}$'` | Identificador con ceros significativos: texto, nunca numérico |
| 2 | `FE/CodigoActividadEmisor` | `electronic_documents` | `issuer_activity_code` | `text` | NOT NULL | — | `string` len 6 (**sin patrón**) | `char_length(…) = 6` | Longitud fija oficial. El XSD **no** exige dígitos (§12.2) |
| 3 | `FE/CodigoActividadReceptor` | `electronic_documents` | `receiver_activity_code` | `text` | NULL | — | `string` len 6 `[0..1]` (**sin patrón**) | `… IS NULL OR char_length(…) = 6` | Opcional: ausente ≠ vacío (§12.2) |
| 4 | `FE/NumeroConsecutivo` | `electronic_documents` | `consecutive_number` | `text` | NOT NULL | — | `NumeroConsecutivoType` `\d{20}` | `~ '^[0-9]{20}$'` | Ceros significativos; embebido en la clave |
| 5 | `FE/FechaEmision` | `electronic_documents` | `issued_at` · `issued_at_offset_minutes` · `issued_at_raw` | `timestamptz` · `smallint` · `text` | NOT NULL ×3 | — | `xs:dateTime` RFC3339 | offset `between -840 and 840` | **Un campo lógico → tres columnas** (§17) |
| 6 | `FE/Emisor/Nombre` | `document_parties` | `legal_name` | `text` | NOT NULL | — | `string` 5..100 (emisor) | `length between 1 and 100` | Mínimo relajado: emisor 5, receptor 3 |
| 7 | `FE/Emisor/Identificacion/Tipo` | `document_parties` | `identification_type_code` | `text` | NOT NULL | — | `string` 2, 6 enum | `~ '^[0-9]{2}$'` | Código de catálogo: longitud, no valor (ADR-029) |
| 8 | `FE/Emisor/Identificacion/Numero` | `document_parties` | `identification_number` | `text` | NOT NULL | — | `string` ≤20 | `length between 1 and 20` | **Texto**: admite alfanuméricos (rev. 2026) |
| 9 | `FE/Emisor/NombreComercial` | `document_parties` | `trade_name` | `text` | NULL | — | `string` 3..80 `[0..1]` | `length ≤ 80` |  |
| 10 | `FE/Receptor/Nombre` | `document_parties` | `legal_name` | `text` | NOT NULL | — | `string` 3..100 | misma columna | Misma tabla, `role='receiver'` |
| 11 | `FE/Receptor/Identificacion/Tipo` | `document_parties` | `identification_type_code` | `text` | NOT NULL | — | `string` 2 | misma columna |  |
| 12 | `FE/Receptor/Identificacion/Numero` | `document_parties` | `identification_number` | `text` | NOT NULL | — | `string` ≤20 | misma columna |  |
| 13 | `FE/Receptor/NombreComercial` | `document_parties` | `trade_name` | `text` | NULL | — | `string` 3..80 | misma columna |  |
| 14 | `FE/CondicionVenta` | `electronic_documents` | `sale_condition_code` | `text` | NOT NULL | — | `string` 2, 14 enum | `~ '^[0-9]{2}$'` | Catálogo: longitud, no valor |
| 15 | `FE/PlazoCredito` | `electronic_documents` | `credit_term` | `integer` | NULL | — | `xs:integer` 5 dígitos | `between 0 and 99999` | Tri-estado: ausente ≠ 0 |
| 16 | `FE/DetalleServicio/LineaDetalle/NumeroLinea` | `document_lines` | `line_number` | `integer` | NOT NULL | — | `positiveInteger` 1..1000 | `between 1 and 1000` | Rango oficial explícito |
| 17 | `FE/DetalleServicio/LineaDetalle/CodigoCABYS` | `document_lines` | `cabys_code` | `text` | NOT NULL | — | XSD: `string` len 13 (**sin patrón**) · BCCR (CABYS): **13 dígitos** | `~ '^[0-9]{13}$'` | Longitud del XSD, forma numérica del **BCCR** (§12). **Sin FK a catálogo** (ADR-029) |
| 18 | `FE/DetalleServicio/LineaDetalle/Cantidad` | `document_lines` | `reported_quantity` | `numeric(16,3)` | NOT NULL | — | `xs:decimal` 16,3 | `>= 0` | Exacto, verificado |
| 19 | `FE/DetalleServicio/LineaDetalle/UnidadMedida` | `document_lines` | `unit_of_measure_code` | `text` | NOT NULL | — | `string`, 101 enum | `length between 1 and 15` | Catálogo amplio y creciente |
| 20 | `FE/DetalleServicio/LineaDetalle/Detalle` | `document_lines` | `description` | `text` | NOT NULL | — | `string` 3..200 | `length between 1 and 200` |  |
| 21 | `FE/DetalleServicio/LineaDetalle/PrecioUnitario` | `document_lines` | `reported_unit_price` | `numeric(18,5)` | NOT NULL | — | `DecimalDineroType` | `>= 0` | XSD `minInclusive=0` |
| 22 | `FE/DetalleServicio/LineaDetalle/MontoTotal` | `document_lines` | `reported_gross_amount` | `numeric(18,5)` | NOT NULL | — | `DecimalDineroType` | `>= 0` |  |
| 23 | `FE/DetalleServicio/LineaDetalle/Descuento/MontoDescuento` | `line_discounts` | `reported_amount` | `numeric(18,5)` | NOT NULL | — | `DecimalDineroType` | `>= 0` |  |
| 24 | `FE/DetalleServicio/LineaDetalle/Descuento/CodigoDescuento` | `line_discounts` | `discount_code` | `text` | NOT NULL | — | `string` 2, 10 enum | `~ '^[0-9]{2}$'` |  |
| 25 | `FE/DetalleServicio/LineaDetalle/SubTotal` | `document_lines` | `reported_subtotal` | `numeric(18,5)` | NOT NULL | — | `DecimalDineroType` | `>= 0` |  |
| 26 | `FE/DetalleServicio/LineaDetalle/BaseImponible` | `document_lines` | `reported_taxable_base` | `numeric(18,5)` | NOT NULL | — | `DecimalDineroType` | `>= 0` |  |
| 27 | `FE/DetalleServicio/LineaDetalle/Impuesto/Codigo` | `line_taxes` | `tax_code` | `text` | NOT NULL | — | `string` 2, 10 enum | `~ '^[0-9]{2}$'` |  |
| 28 | `FE/DetalleServicio/LineaDetalle/Impuesto/CodigoTarifaIVA` | `line_taxes` | `vat_rate_code` | `text` | NULL | — | `string` 2, 11 enum `[0..1]` | `~ '^[0-9]{2}$'` |  |
| 29 | `FE/DetalleServicio/LineaDetalle/Impuesto/Tarifa` | `line_taxes` | `reported_rate` | `numeric(4,2)` | NULL | — | `xs:decimal` 4,2 `[0..1]` | `>= 0` | Tarifa **reportada**, no aplicada por nosotros |
| 30 | `FE/DetalleServicio/LineaDetalle/Impuesto/Monto` | `line_taxes` | `reported_amount` | `numeric(18,5)` | NOT NULL | — | `DecimalDineroType` | `>= 0` |  |
| 31 | `FE/DetalleServicio/LineaDetalle/ImpuestoNeto` | `document_lines` | `reported_net_tax` | `numeric(18,5)` | NOT NULL | — | `DecimalDineroType` | `>= 0` |  |
| 32 | `FE/DetalleServicio/LineaDetalle/MontoTotalLinea` | `document_lines` | `reported_line_total` | `numeric(18,5)` | NOT NULL | — | `DecimalDineroType` | `>= 0` |  |
| 33 | `FE/ResumenFactura/CodigoTipoMoneda/CodigoMoneda` | `electronic_documents` | `currency_code` | `text` | NOT NULL | — | `string`, 168 enum | `length between 1 and 3` | Catálogo ISO; sin FK |
| 34 | `FE/ResumenFactura/CodigoTipoMoneda/TipoCambio` | `electronic_documents` | `reported_exchange_rate` | `numeric(18,5)` | NOT NULL | — | `DecimalDineroType` | `>= 0` |  |
| 35 | `FE/ResumenFactura/TotalGravado` | `electronic_documents` | `reported_total_taxed` | `numeric(18,5)` | NULL | **sin default** | `DecimalDineroType` `[0..1]` | `>= 0` | **Ausente ≠ 0** |
| 36 | `FE/ResumenFactura/TotalExento` | `electronic_documents` | `reported_total_exempt` | `numeric(18,5)` | NULL | **sin default** | `[0..1]` | `>= 0` | **Ausente ≠ 0** |
| 37 | `FE/ResumenFactura/TotalExonerado` | `electronic_documents` | `reported_total_exonerated` | `numeric(18,5)` | NULL | **sin default** | `[0..1]` | `>= 0` | **Ausente ≠ 0** |
| 38 | `FE/ResumenFactura/TotalNoSujeto` | `electronic_documents` | `reported_total_not_subject` | `numeric(18,5)` | NULL | **sin default** | `[0..1]` | `>= 0` | **Ausente ≠ 0** |
| 39 | `FE/ResumenFactura/TotalVenta` | `electronic_documents` | `reported_total_sale` | `numeric(18,5)` | NOT NULL | — | `[1..1]` | `>= 0` |  |
| 40 | `FE/ResumenFactura/TotalDescuentos` | `electronic_documents` | `reported_total_discount` | `numeric(18,5)` | NULL | **sin default** | `[0..1]` | `>= 0` | **Ausente ≠ 0** |
| 41 | `FE/ResumenFactura/TotalVentaNeta` | `electronic_documents` | `reported_total_net_sale` | `numeric(18,5)` | NOT NULL | — | `[1..1]` | `>= 0` |  |
| 42 | `FE/ResumenFactura/TotalImpuesto` | `electronic_documents` | `reported_total_tax` | `numeric(18,5)` | NULL | **sin default** | `[0..1]` | `>= 0` | Convivirá con `computed_total_tax` |
| 43 | `FE/ResumenFactura/TotalComprobante` | `electronic_documents` | `reported_total_document` | `numeric(18,5)` | NOT NULL | — | `[1..1]` | `>= 0` | Positivo también en NC/ND |
| 44 | `FE/InformacionReferencia/TipoDocIR` | `document_references` | `referenced_document_type_code` | `text` | NOT NULL | — | `string` 2 · XSD 19 enum / Anexos **20** | `~ '^[0-9]{2}$'` | **Sin CHECK de valor**: el catálogo ya divergió |
| 45 | `FE/InformacionReferencia/Numero` | `document_references` | `reported_number` | `text` | NULL | — | `string` ≤50 `[0..1]` | `length between 1 and 50` | Opcional → sin FK obligatoria |
| 46 | `FE/InformacionReferencia/FechaEmisionIR` | `document_references` | `reported_reference_date` · `reported_reference_offset_minutes` · `reported_reference_date_raw` | `timestamptz` · `smallint` · `text` | NOT NULL ×3 | — | `xs:dateTime` · condición `1` en los 7 tipos | offset `between -840 and 840` | **Un campo lógico → tres columnas** (§17.1). Puede portar el periodo, no la fecha real |
| 47 | `FE/InformacionReferencia/Codigo` | `document_references` | `reference_code` | `text` | NULL | — | `string` 2 · XSD 12 / Anexos **17** | `~ '^[0-9]{2}$'` | **Determina el periodo contable** |
| 48 | `FE/InformacionReferencia/Razon` | `document_references` | `reason` | `text` | NULL | — | `string` ≤180 `[0..1]` | `length between 1 and 180` |  |

### 20.1 Un campo lógico puede necesitar varias columnas

Dos de los 48 se expanden a tres columnas físicas cada uno: **`FechaEmision`** (§17) y
**`FechaEmisionIR`** (§17.1). Aparecen como **una fila cada uno**, porque un dato de origen
es un dato de origen: las columnas auxiliares **no son nodos XML nuevos** y no se cuentan
como tales.

```
48  campos lógicos con valor
52  columnas físicas resultantes   (48 − 2 + 6)
```

No hay contradicción entre ambas cifras, y tampoco pérdida de información:

```
48 / 48  campos lógicos completamente representados
0        pérdida de información
```

Ambas fechas conservan **instante + desplazamiento reportado + valor literal**.

---

## 21. Las siete tablas

| Tabla | PK | Clave de tenant | Padre | Restricciones únicas | Clave RLS |
|---|---|---|---|---|---|
| `fiscal.source_documents` | `id` | `company_id` | `public.companies` | — | `company_id` |
| `fiscal.electronic_documents` | `id` | `company_id` | `public.companies` | `(company_id, id)` · `(company_id, clave)` | `company_id` |
| `fiscal.document_parties` | `id` | `company_id` | `electronic_documents` | `(company_id, electronic_document_id, role)` | `company_id` |
| `fiscal.document_lines` | `id` | `company_id` | `electronic_documents` | `(company_id, id)` · `(company_id, electronic_document_id, line_number)` | `company_id` |
| `fiscal.line_discounts` | `id` | `company_id` | `document_lines` | `(company_id, document_line_id, sequence)` | `company_id` |
| `fiscal.line_taxes` | `id` | `company_id` | `document_lines` | `(company_id, document_line_id, sequence)` | `company_id` |
| `fiscal.document_references` | `id` | `company_id` | `electronic_documents` | `(company_id, electronic_document_id, sequence)` | `company_id` |

### 21.1 `UNIQUE (company_id, id)` sólo donde hace falta

**Corrección respecto a la primera versión de E2**, que lo proponía en las siete «por
uniformidad». Un índice único es obligatorio **únicamente** si `(company_id, id)` es
destino de una FK compuesta; en el resto no aporta integridad —`id` ya es único por ser
PK— y sí cuesta espacio y una escritura de índice por fila.

| Tabla | ¿Referenciada por `(company_id, id)`? | ¿`UNIQUE` compuesta necesaria? | Motivo |
|---|---|---|---|
| `electronic_documents` | **Sí** — desde `source_documents`, `document_parties`, `document_lines`, y **dos veces** desde `document_references` | ✅ **Obligatoria** | Destino de 5 FK compuestas |
| `document_lines` | **Sí** — desde `line_discounts` y `line_taxes` | ✅ **Obligatoria** | Destino de 2 FK compuestas |
| `source_documents` | No | ❌ Redundante | Hoja: nadie la referencia |
| `document_parties` | No | ❌ Redundante | Hoja |
| `line_discounts` | No | ❌ Redundante | Hoja |
| `line_taxes` | No | ❌ Redundante | Hoja |
| `document_references` | No | ❌ Redundante | Hoja. `resolved_document_id` apunta **hacia** `electronic_documents`, no al revés |

**No se sacrifica seguridad.** El aislamiento entre tenants lo impone la FK compuesta de
la **hija**, no el índice único de la hoja. Quitar los cinco redundantes elimina cinco
índices que nadie consulta y ninguna restricción los necesita.

Si en el futuro alguna de esas tablas gana hijas, añadir la restricción es una migración
trivial — mucho más barata que mantener hoy cinco índices sin función.

---

## 22. Matriz de claves foráneas

| Hija | Columnas de la FK | Padre | Cardinalidad | Borrado | ¿Mismo tenant impuesto? |
|---|---|---|---|---|---|
| `source_documents` | `company_id` | `public.companies(id)` | N..1 | **RESTRICT** | — (es la raíz) |
| `source_documents` | `(company_id, electronic_document_id)` | `electronic_documents(company_id, id)` | **0..1** | **SET NULL (`electronic_document_id`)** | ✅ FK compuesta · `MATCH SIMPLE` |
| `electronic_documents` | `company_id` | `public.companies(id)` | N..1 | **RESTRICT** | — (es la raíz) |
| `document_parties` | `(company_id, electronic_document_id)` | `electronic_documents(company_id, id)` | 1..2 | **CASCADE** | ✅ FK compuesta |
| `document_lines` | `(company_id, electronic_document_id)` | `electronic_documents(company_id, id)` | 0..N | **CASCADE** | ✅ FK compuesta |
| `line_discounts` | `(company_id, document_line_id)` | `document_lines(company_id, id)` | 0..5 | **CASCADE** | ✅ FK compuesta |
| `line_taxes` | `(company_id, document_line_id)` | `document_lines(company_id, id)` | 1..1000 | **CASCADE** | ✅ FK compuesta |
| `document_references` | `(company_id, electronic_document_id)` | `electronic_documents(company_id, id)` | 0..10 | **CASCADE** | ✅ FK compuesta |
| `document_references` | `(company_id, resolved_document_id)` | `electronic_documents(company_id, id)` | 0..1 | **SET NULL (`resolved_document_id`)** | ✅ FK compuesta · `MATCH SIMPLE` |

### Por qué cada comportamiento de borrado

**`RESTRICT` en la frontera con la empresa.** Eliminar una empresa con documentos
fiscales no puede ser un efecto colateral de un `DELETE`. Coincide con el precedente del
proyecto (`companies.created_by`).

**`CASCADE` dentro del agregado del documento.** Partes, líneas, descuentos, impuestos y
referencias **no tienen existencia propia**: una línea sin su factura no significa nada, y
dejarla huérfana sería peor que borrarla. El agregado es una unidad.

Esto **no** contradice la preservación de evidencia: lo que protege el documento de ser
borrado es que **`fiscal_backend` no recibe `DELETE`** en el MVP (§25). El `CASCADE`
describe qué debe ocurrir *si* alguna vez se ejecuta un borrado autorizado, no autoriza
a ejecutarlo.

**`SET NULL` de columna en los dos enlaces opcionales.** Tanto el artefacto como la
referencia reportada son **datos de origen** que deben sobrevivir a la desaparición de
aquello a lo que apuntan. Perder la resolución de una referencia es aceptable; perder la
referencia que el emisor declaró, no. Es [ADR-028](DECISIONS.md#adr-028) expresada en el
motor.

**Debe acotarse a la columna opcional** (§5.1). Un `ON DELETE SET NULL` sin columnas
intentaría anular también `company_id`, que es `NOT NULL`, y el borrado fallaría.

### 22.1 Ningún `CASCADE` puede alcanzar `raw_xml`

Comprobación explícita, porque es la propiedad que sostiene [ADR-022](DECISIONS.md#adr-022):

| Ruta de borrado | ¿Alcanza `source_documents`? |
|---|---|
| Borrar una empresa | **No** — `RESTRICT` lo impide antes de empezar |
| Borrar un `electronic_document` | **No** — el enlace es `SET NULL (electronic_document_id)`: la fila del artefacto sobrevive y `raw_xml` queda intacto |
| Cualquier `CASCADE` del agregado | **No** — todos van *desde* `electronic_documents` *hacia abajo*; `source_documents` no es hija suya |

**`fiscal.source_documents` no es destino de ningún `CASCADE`.** Verificado además de
forma empírica en §5.2: tras borrar el destino, la carga `bytea` de la fila hija quedó
intacta.

---

## 23. Matriz de restricciones

| Restricción | Tabla | Propósito | ¿Capa? |
|---|---|---|---|
| `clave ~ '^[0-9]{50}$'` | `electronic_documents` | Forma oficial de la clave | **BD** |
| `consecutive_number ~ '^[0-9]{20}$'` | `electronic_documents` | Forma del consecutivo | **BD** |
| `char_length(issuer_activity_code) = 6` | `electronic_documents` | Longitud del código de actividad, **no** su forma numérica (§12.2) | **BD** |
| `receiver_activity_code IS NULL OR char_length(…) = 6` | `electronic_documents` | Igual, conservando el tri-estado | **BD** |
| `UNIQUE (company_id, clave)` | `electronic_documents` | Identidad lógica por tenant; expone el conflicto | **BD** |
| `document_type IN (…)` | `electronic_documents` | Vocabulario **propio** | **BD** |
| `direction IN (…)` | `electronic_documents` | Vocabulario propio | **BD** |
| `ruleset_revision_status IN (…)` | `electronic_documents` | Vocabulario propio | **BD** |
| `reported_* >= 0` | varias | XSD `minInclusive=0` | **BD** |
| `numeric(p,s)` | varias | Precisión decimal exacta | **BD** |
| `role IN ('issuer','receiver')` | `document_parties` | Vocabulario propio | **BD** |
| `UNIQUE (…, electronic_document_id, role)` | `document_parties` | **Máximo** un emisor y un receptor | **BD** |
| `UNIQUE (…, electronic_document_id, line_number)` | `document_lines` | Orden de origen sin repetir | **BD** |
| `line_number BETWEEN 1 AND 1000` | `document_lines` | Rango oficial | **BD** |
| `sequence BETWEEN 1 AND 5` | `line_discounts` | Cardinalidad oficial `0..5` | **BD** |
| `sequence BETWEEN 1 AND 1000` | `line_taxes` | Cardinalidad oficial | **BD** |
| `sequence BETWEEN 1 AND 10` | `document_references` | Cardinalidad oficial `0..10` | **BD** |
| Códigos de catálogo: forma `^[0-9]{2}$`, `^[0-9]{13}$` | varias | Forma, **nunca valor** (§12) | **BD** |
| FK compuestas `(company_id, …)` | todas las hijas | Imposibilita el cruce entre tenants | **BD** |
| **Al menos un `issuer` por documento** | `document_parties` | Completitud del documento | **Capa 2** |
| **Al menos un `line_tax` por línea** | `line_taxes` | Completitud (§24) | **Capa 2** |
| **Al menos una referencia en NC y ND** | `document_references` | Condición por tipo de documento | **Capa 2** |
| **Al menos un `source_document` por documento** | — | Mínimo `1..N` (§9) | **Capa 2** / transacción |
| **Coherencia de totales** | — | Que la suma de líneas cuadre con el resumen | **Capa 3** |
| **Valores de catálogo válidos** | — | Que el código exista en el catálogo vigente, **padrón del RUT incluido** | **Capa 2** |

La columna «capa» es deliberada. Confundir **integridad relacional** con **completitud
semántica del documento** llevaría a *triggers* que replican reglas de Hacienda dentro del
motor, difíciles de versionar y de probar. [ADR-030](DECISIONS.md#adr-030) ya separó las
capas; esta matriz sólo dice cuál se encarga de qué.

---

## 24. Cardinalidades mínimas: qué puede y qué no puede el motor

Una restricción `UNIQUE` impone **máximos**; ningún mecanismo declarativo impone
**mínimos** en el lado hijo.

| Regla | ¿Declarativa? |
|---|---|
| Máximo 1 emisor, máximo 1 receptor | ✅ `UNIQUE (company_id, electronic_document_id, role)` |
| Máximo 5 descuentos por línea | ✅ `CHECK sequence BETWEEN 1 AND 5` + `UNIQUE` |
| Máximo 10 referencias | ✅ ídem |
| Máximo 1000 líneas | ✅ `CHECK line_number BETWEEN 1 AND 1000` |
| **Mínimo 1 emisor** | ❌ |
| **Mínimo 1 impuesto por línea** | ❌ |
| **Mínimo 1 referencia en NC/ND** | ❌ |

**Propuesta: no usar *triggers* para los mínimos.** Se garantizan en la transacción de
normalización (§18), que es donde el documento se construye completo o no se construye.

El razonamiento: un *trigger* diferido tendría que dispararse al final de la transacción,
consultar tablas hermanas y decidir; sería lógica de dominio dentro del motor, invisible
desde el código, costosa de probar y con un modo de fallo desagradable —un error de
*trigger* en `COMMIT`, lejos de la sentencia que lo causó—. Y no compraría seguridad
adicional: **ninguna de estas reglas es una frontera de tenant**. Un documento incompleto
es un error de datos, no una fuga entre contribuyentes; las fugas sí están cerradas
declarativamente (§5).

Si en el futuro se demuestra que escrituras fuera de la ruta de ingesta producen
documentos incompletos, se reconsidera con evidencia.

---

## 25. Vista previa de RLS y privilegios

**Sin políticas ni `GRANT` en E2.** Sólo la forma que tendrán.

Las siete tablas llevan `company_id`, así que todas admiten la **misma política simple**:

```sql
-- ilustrativo
alter table fiscal.<t> enable row level security;
create policy <t>_select on fiscal.<t>
    for select to fiscal_backend
    using (private.is_company_member(company_id));
```

Se usa `private.is_company_member(uuid)` —`SECURITY DEFINER`, `STABLE`— que es el helper
aprobado y ya probado con la tabla canario del Checkpoint D. **No se concede `USAGE` sobre
`auth` a `fiscal_backend`**: ADR-020 no se toca, y por eso las políticas nunca usan
`auth.uid()` directo.

Que las siete tengan la clave de tenant como columna propia es lo que permite que la
política sea idéntica y barata: sin subconsultas, sin recorrer la jerarquía.

### 25.1 La pertenencia **no** basta para escribir

**Corrección respecto a la primera versión de E2**, que daba a entender que una sola
política de pertenencia serviría para todas las operaciones. No sirve.

El proyecto tiene roles desde el Checkpoint C —`owner`, `editor`, `viewer`
([ADR-015](DECISIONS.md#adr-015))— y `private.is_company_member` **sólo comprueba
pertenencia, no rol**. Verificado leyendo su cuerpo:

```sql
select exists (
    select 1 from public.company_memberships m
    where m.company_id = p_company_id
      and m.user_id    = (select auth.uid())
);
```

Con esa única condición, **un `viewer` adquiriría capacidad de modificar datos fiscales
por el mero hecho de ser miembro**. Es exactamente lo que los roles existen para impedir.

**Requisito, no diseño terminado:**

```
SELECT           →  pertenencia a la empresa
INSERT / UPDATE  →  pertenencia  +  capacidad de escritura aprobada
```

Y las políticas deberán distinguir las dos cláusulas, que responden a preguntas distintas:

| Cláusula | Pregunta | Se aplica a |
|---|---|---|
| `USING` | ¿puede **ver** esta fila? | `SELECT`, `UPDATE`, `DELETE` |
| `WITH CHECK` | ¿puede **dejar** la fila en este estado? | `INSERT`, `UPDATE` |

Un `UPDATE` sin `WITH CHECK` permitiría mover una fila a otra empresa: `USING` valida lo
que se lee, no lo que se escribe.

### 25.2 Falta un helper de capacidad de escritura

**Estado verificado del proyecto:** en el schema `private` existen exactamente dos
funciones —`is_company_member(uuid)` y `create_company_impl(text)`— y **ninguna distingue
rol**. Las únicas políticas existentes en `public` son de `SELECT`; **no hay ni una sola
política de escritura en todo el proyecto**.

Conclusión: **no hay autoridad reutilizable del Checkpoint C**. Habrá que crear un helper
privado `SECURITY DEFINER` específico, del estilo conceptual:

```
private.can_write_company(p_company_id uuid) → boolean
```

que resuelve pertenencia **y** rol contra `public.company_memberships`, siguiendo el mismo
patrón aprobado por [ADR-020](DECISIONS.md#adr-020): helper privado, `SECURITY DEFINER`,
sin conceder a `fiscal_backend` acceso directo ni a `auth` ni a `company_memberships`.

**Su contrato queda cerrado en esta fase** (§25.5): qué roles escriben es
`owner` y `editor`; `viewer` es solo lectura. Lo que resta es escribirlo, y eso es E3.

### 25.3 Propuesta concreta de capacidad de escritura

Se propone en [ADR-038](DECISIONS.md#adr-038), **PROPOSED**:

| Rol | Capacidad |
|---|---|
| `owner` | lectura + ingesta y escritura fiscal |
| `editor` | lectura + ingesta y escritura fiscal |
| `viewer` | **solo lectura** |

**`DELETE`: ningún rol de aplicación, en el MVP.**

**Qué significa exactamente «capacidad de escritura».** No es la facultad de alterar a
mano hechos fiscales reportados. Significa que FastAPI puede ejecutar, en nombre de un
`owner` o un `editor`, los flujos autorizados:

```
ingestión  ·  normalización  ·  resolución de referencias  ·  metadatos mutables
```

```
capacidad de escritura  ≠  poder modificar hechos reportados
```

Un `owner` **no** puede editar el importe de una factura. Puede provocar que el sistema
ingiera una, la normalice y resuelva sus referencias. Es la diferencia entre operar el
sistema y reescribir la evidencia (§26.1).

### 25.4 Forma de las políticas

```sql
-- SELECT: basta la pertenencia
using ( private.is_company_member(company_id) )

-- INSERT: la fila resultante debe quedar en una empresa donde se pueda escribir
with check ( private.can_write_company(company_id) )

-- UPDATE: se comprueban las DOS filas
using      ( private.can_write_company(company_id) )   -- la fila actual
with check ( private.can_write_company(company_id) )   -- la fila resultante
```

### 25.5 Contrato definitivo del helper de escritura

El helper **no existe todavía**; su contrato sí queda cerrado aquí, para que E3 lo
implemente sin reabrir decisiones.

```sql
private.can_write_company(p_company_id uuid)
    returns boolean
    language sql
    stable
    security definer
    set search_path = ''
```

**Autoridad y regla:**

```
FUENTE       public.company_memberships
IDENTIDAD    auth.uid()  —  obtenida DENTRO del helper privilegiado
REGLA        company_id = p_company_id
             AND user_id = auth.uid()
             AND role IN ('owner','editor')
```

**Lo que el helper NO acepta jamás**, y es lo que justifica que sea `SECURITY DEFINER` en
lugar de una condición escrita en la política:

```
user_id proporcionado por el llamante
role    proporcionado por el llamante
role    tomado del JWT como autoridad
role    procedente de petición, cabecera o parámetro
```

Es la misma propiedad que [ADR-012](DECISIONS.md#adr-012) fijó para la identidad: un valor
que llega en una petición no es autoridad sobre nada. La identidad se resuelve dentro del
helper y el rol se lee de la tabla, nunca del cliente.

`set search_path = ''` es obligatorio en un `SECURITY DEFINER`: sin él, un objeto malicioso
en un schema anterior del `search_path` podría suplantar a `public.company_memberships`.
Por eso todas las referencias van calificadas.

`stable` y no `volatile`: el resultado no cambia dentro de una misma sentencia, y permite
al planificador evaluarlo una vez por fila en lugar de repetirlo.

### 25.6 ACL conceptual del helper

| Rol | `EXECUTE` |
|---|---|
| `PUBLIC` | **no** |
| `anon` | **no** |
| `authenticated` | **no** |
| `service_role` | **no** en el camino normal |
| `app_backend` ambiental | **no** |
| **`fiscal_backend`** | **sí** |

`app_backend` alcanza el helper **únicamente** tras asumir explícitamente
`SET ROLE fiscal_backend`, que es el mecanismo de ADR-020 y no un privilegio ambiental.

Sigue sin concederse a `fiscal_backend`:

```
USAGE sobre auth          ·  SELECT sobre public.company_memberships
```

El helper `SECURITY DEFINER` **encapsula** esa autoridad: es lo que permite responder la
pregunta sin repartir el acceso a los datos que la sustentan.

**Por qué `UPDATE` necesita las dos cláusulas.** `USING` decide qué filas son visibles
para actualizar; `WITH CHECK` decide si el resultado es aceptable. Con sólo `USING`, una
actualización podría **cambiar `company_id` y mover la fila a otra empresa**: la fila
original era visible, y nadie comprobaría la de destino.

Las FK compuestas (§5) siguen siendo defensa estructural adicional: aunque la política
fallara, mover la fila rompería la pareja `(company_id, parent_id)`.

**`DELETE`: no se crea política.** Sin privilegio y sin política, el flujo normal no puede
borrar. Los `ON DELETE` de §22 siguen siendo necesarios para la coherencia referencial y
para operaciones administrativas controladas, que se diseñarán aparte.

```
CONTRATO DE DISEÑO  =  CERRADO EN E2
IMPLEMENTACIÓN      =  E3
```

### Privilegios previstos

| Rol | Privilegio propuesto |
|---|---|
| `fiscal_backend` | `SELECT`, `INSERT` en las siete · `UPDATE` **sólo** en las columnas mutables de §26 — nunca sobre `raw_xml` ni `content_sha256` |
| `authenticated` | **ninguno** |
| `anon` | **ninguno** |
| `service_role` | **ninguno** en el camino normal |
| `app_backend` sin `SET ROLE` | **ninguno** (ambiental) |

**`DELETE`: no se concede en el MVP.** Ningún flujo del producto necesita borrar un
comprobante, y la evidencia fiscal no debe desaparecer por un error de código. Si aparece
una necesidad legítima —una corrección, una baja de empresa— será un camino administrativo
explícito y auditable, no un privilegio permanente. Es la misma lógica que ADR-002 aplica
a `service_role`.

---

## 26. Inmutabilidad

| Dato | Naturaleza |
|---|---|
| Artefacto, huella, `ingested_at`, `company_id` | **Inmutable** |
| Todo campo `reported_*` | **Inmutable**: es lo que dijo el documento |
| Instantáneas de `document_parties` | **Inmutable** ([ADR-024](DECISIONS.md#adr-024)) |
| Líneas, impuestos, descuentos | **Inmutables** tras la normalización |
| `parse_status`, `parse_error`, contadores | Mutable — metadato de interpretación |
| `electronic_document_id` en el artefacto | Mutable una vez: `NULL` → poblado |
| `ruleset_revision` y su estado | Mutable: puede resolverse después |
| `direction`, `direction_computed_at` | Mutable: recomputable |
| `resolved_document_id` | Mutable: la resolución es diferida |

La línea es la de E1: **los hechos de origen son inmutables; nuestras conclusiones sobre
ellos, no**.

### 26.1 Ni `owner` ni `editor` pueden reescribir hechos de origen

La capacidad de escritura de §25.3 **no incluye** alterar arbitrariamente, tras una
normalización correcta:

```
raw_xml · content_sha256 · clave · consecutive_number · issued_at (y sus tres columnas)
importes reportados · instantáneas de emisor y receptor
hechos de origen de líneas · hechos de origen de impuestos
```

Frente a lo que **sí** es metadato operativo o derivado, y por tanto mutable:

```
parse_status · parse_error · parse_attempted_at · parse_attempt_count
electronic_document_id (NULL → poblado)
ruleset_revision · ruleset_revision_status
direction · direction_computed_at
resolved_document_id
```

Corregir un artefacto equivocado **no es editarlo**: es registrar **otro**
`SourceDocument`. Los bytes históricos no se reescriben nunca (§7).

### 26.2 RLS y privilegios de columna resuelven cosas distintas

```
autorización de fila     =  RLS
mutabilidad de columna   =  estrategia de GRANT
```

**RLS no hace inmutable una columna.** Una política decide *qué filas* puede tocar un rol,
no *qué columnas*. Con `UPDATE` a nivel de tabla y una política de escritura correcta, un
`owner` podría reescribir `raw_xml` sin violar ninguna política.

Por eso el diseño **no concede `UPDATE` a nivel de tabla**:

```sql
-- NO:
grant update on fiscal.source_documents to fiscal_backend;

-- SÍ:
grant update (parse_status, parse_error, …) on fiscal.source_documents to fiscal_backend;
```

**Y no vale conceder la tabla y revocar columnas después.** `REVOKE UPDATE(col)` sobre un
`GRANT UPDATE` de tabla **no reduce** el privilegio: el permiso de tabla sigue autorizando
esa columna. La única forma correcta es conceder **exclusivamente** la lista de columnas
mutables, desde el principio.

### 26.3 Matriz de mutabilidad por columna

Todas las columnas propuestas de las siete tablas. `INSERT` las crea todas; la columna
«¿mutable?» se refiere al camino normal de la aplicación.

#### `fiscal.source_documents`

| Columna | ¿Mutable? | Motivo |
|---|---|---|
| `id` | ❌ | Identidad |
| `company_id` | ❌ | Tenant — §26.4 |
| `raw_xml` | ❌ | **Hecho de origen.** Artefacto inmutable (ADR-022) |
| `content_sha256` | ❌ | **Hecho de origen.** Huella del artefacto |
| `ingested_at` | ❌ | Momento real de recepción |
| `ingestion_source` | ❌ | Procedencia real |
| `parse_status` | ✅ | Metadato operativo: `pending` → `parsed`/`failed` |
| `parse_error` | ✅ | Diagnóstico del intento |
| `parse_attempted_at` | ✅ | Reproceso (§19) |
| `parse_attempt_count` | ✅ | Reproceso |
| `schema_detection_status` | ✅ | Se resuelve al parsear |
| `detected_document_type` | ✅ | Ídem: `NULL` → poblado |
| `detected_schema_version` | ✅ | Ídem |
| `electronic_document_id` | ✅ | Enlace de normalización: `NULL` → poblado |
| `updated_at` | ✅ | Metadato del sistema |

#### `fiscal.electronic_documents`

| Columna | ¿Mutable? | Motivo |
|---|---|---|
| `id`, `company_id` | ❌ | Identidad y tenant |
| `document_type` | ❌ | Hecho de origen |
| `clave`, `consecutive_number` | ❌ | Hechos de origen |
| `issued_at`, `issued_at_offset_minutes`, `issued_at_raw` | ❌ | Hechos de origen |
| `issuer_activity_code`, `receiver_activity_code` | ❌ | Hechos de origen |
| `sale_condition_code`, `credit_term` | ❌ | Hechos de origen |
| `currency_code`, `reported_exchange_rate` | ❌ | Hechos de origen |
| Los **nueve** `reported_total_*` | ❌ | Hechos de origen |
| `ruleset_revision` | ✅ | Interpretación: puede resolverse después (ADR-026) |
| `ruleset_revision_status` | ✅ | Ídem |
| `direction` | ✅ | Derivado; recomputable |
| `direction_computed_at` | ✅ | Ídem |
| `created_at` | ❌ | Metadato del sistema, fijo |
| `updated_at` | ✅ | Metadato del sistema |

#### `fiscal.document_references`

| Columna | ¿Mutable? | Motivo |
|---|---|---|
| `id`, `company_id`, `electronic_document_id`, `sequence` | ❌ | Identidad, tenant y orden de origen |
| `referenced_document_type_code` | ❌ | **Reportado** |
| `reported_number` | ❌ | **Reportado** |
| `reported_reference_date` · `_offset_minutes` · `_raw` | ❌ | **Reportadas** |
| `reference_code`, `reason` | ❌ | **Reportados** |
| `resolved_document_id` | ✅ | **Única mutable**: resolución diferida (ADR-028) |

#### `fiscal.document_parties` · `fiscal.document_lines` · `fiscal.line_discounts` · `fiscal.line_taxes`

**Ninguna columna mutable. Sin `UPDATE` en el camino normal.**

Toda su información nace por `INSERT` dentro de la transacción de normalización (§18) y es
íntegramente reportada: instantáneas de las partes, líneas, descuentos e impuestos. No
tienen metadato operativo que pueda cambiar, y por tanto **no reciben ningún privilegio de
`UPDATE`** — ni siquiera por columna. **Sin excepciones.**

#### Resumen

| Conjunto | Columnas |
|---|---|
| **Creadas por `INSERT`** | todas las de las siete tablas |
| **Inmutables tras la creación** | todos los hechos de origen, identidades y `company_id` |
| **Con `UPDATE` concedido** | 9 en `source_documents` · 5 en `electronic_documents` · 1 en `document_references` — **15 columnas en total, en 3 de las 7 tablas** |

### 26.4 `company_id` nunca es actualizable

`company_id` **no aparece en ninguna lista de `UPDATE`**, en ninguna tabla.

Tres defensas independientes, cada una suficiente por sí sola:

1. **Privilegio de columna** — no se concede `UPDATE` sobre ella.
2. **RLS** — `WITH CHECK` sobre la fila resultante rechazaría el destino.
3. **FK compuestas** — mover la fila rompería `(company_id, parent_id)`.

Defensa en profundidad: que las tres coincidan no es redundancia inútil, es que cada una
falla de forma distinta.

### 26.5 `DELETE`

```
fiscal_backend  →  sin privilegio DELETE  ·  sin política DELETE
```

Los `ON DELETE` de §22 existen **como semántica referencial** para operaciones
privilegiadas y controladas, no como flujo normal de usuario. Sin privilegio y sin
política, el `CASCADE` no es alcanzable desde la aplicación.

`updated_at` **no se añade a todas las tablas**. Sólo tiene sentido donde algo cambia:
`source_documents` y `electronic_documents`. En `document_parties`, `document_lines`,
`line_taxes`, `line_discounts` y en los campos reportados de `document_references` sería
una columna que nunca cambia —ruido que además insinúa que la mutación es esperable—.
`public.companies` ya sienta el precedente: sólo `created_at`.

Sin *triggers* de inmutabilidad en E2. La protección viene de no conceder `UPDATE` sobre
las columnas que no deben cambiar.

---

## 27. Índices

Todo índice tiene una consulta que lo justifica. Los `UNIQUE` de §21 ya crean el suyo y no
se repiten aquí.

| Índice | Columnas | Consulta que soporta | ¿Único? | Justificación |
|---|---|---|---|---|
| `edoc_company_issued_idx` | `(company_id, issued_at DESC)` | «documentos de mi empresa por fecha» | No | La consulta más frecuente del producto: cualquier listado y todo informe por periodo |
| `edoc_company_type_issued_idx` | `(company_id, document_type, issued_at DESC)` | «mis notas de crédito de agosto» | No | Filtrar por tipo es constante; sin él, filtra tras leer todo el rango |
| `edoc_company_direction_issued_idx` | `(company_id, direction, issued_at DESC)` | «mis ventas» / «mis compras» | No | Separación ventas/compras: la división primaria del dominio |
| `dparty_company_ident_idx` | `(company_id, identification_type_code, identification_number)` | «todo lo emitido por este proveedor» | No | Agregación por contraparte sin catálogo maestro (ADR-024) |
| `dline_company_doc_idx` | `(company_id, electronic_document_id)` | documento → líneas | No | Cubierto por el `UNIQUE (…, line_number)` — **no se crea** |
| `ltax_company_line_idx` | `(company_id, document_line_id)` | línea → impuestos | No | Cubierto por el `UNIQUE (…, sequence)` — **no se crea** |
| `dref_company_unresolved_idx` | `(company_id, reported_reference_date)` **WHERE** `resolved_document_id IS NULL` | «referencias pendientes de resolver» | No | **Índice parcial**: el proceso de resolución diferida (ADR-028) las busca; el parcial es pequeño y se vacía solo al resolverse |
| `sdoc_company_hash_idx` | `(company_id, content_sha256)` | deduplicación previa a insertar | **No** | §16: **no único** a propósito — los mismos bytes pueden representar dos eventos de ingesta legítimos |
| `sdoc_company_status_idx` | `(company_id, parse_status)` **WHERE** `parse_status <> 'parsed'` | artefactos pendientes o fallidos | No | Índice parcial para reproceso (§19) |
| `sdoc_company_edoc_idx` | `(company_id, electronic_document_id)` | documento → sus artefactos de procedencia; y la búsqueda del lado referente al aplicar `SET NULL` | No | **PostgreSQL no indexa automáticamente el lado *referencing* de una FK.** Sin él, borrar un `ElectronicDocument` exigiría recorrer toda la tabla de artefactos |
| `dref_company_resolved_idx` | `(company_id, resolved_document_id)` | «qué referencias apuntan a este documento»; y el lado referente del `SET NULL` | No | Mismo motivo. **Distinto del índice parcial de referencias sin resolver**: aquél sirve la búsqueda de pendientes (`IS NULL`), éste la de resueltas y el borrado |

**Sobre los dos últimos.** PostgreSQL crea índices automáticamente sobre la clave
*referenciada*, nunca sobre las columnas *referentes*. Con `ON DELETE SET NULL (columna)`,
cada borrado del padre obliga a localizar las filas hijas que lo apuntan; sin índice, eso
es un recorrido completo de la tabla.

Se proponen **completos y no parciales** (`WHERE ... IS NOT NULL`). El parcial sería algo
menor, pero introduce una condición que hay que recordar al escribir cada consulta, y el
planificador sólo lo usa si el predicado coincide. A este volumen la diferencia no compensa
la imprevisibilidad: se prefiere lo simple y predecible.

**Los tres primeros comparten prefijo `company_id`** y podrían parecer redundantes. No lo
son: PostgreSQL sólo usa un índice compuesto si el filtro cubre el prefijo, y las tres
consultas filtran por columnas distintas en segunda posición.

**No se indexa `clave`** aparte: el `UNIQUE (company_id, clave)` ya sirve la búsqueda por
clave dentro del tenant, que es la única que existe.

**No se indexan** los códigos de catálogo, los importes ni los campos de texto libre. No
hay consulta del MVP que los filtre, y cada índice tiene coste en cada escritura.

---

## 28. Lo que este diseño deliberadamente **no** incluye

- **Campos `computed_*`.** Cuando exista el Tax Engine, irán en su propia capa
  ([ADR-023](DECISIONS.md#adr-023)). Ninguna columna se reserva ahora.
- **`fiscal_period`.** El periodo no se deduce de la fecha de emisión (E1 §16). No hay
  columna, ni derivada ni reportada.
- **Tablas de las entidades categoría B**: `document_payments`, `document_charges`,
  `document_tax_summaries`, `party_contacts`, `tax_exemptions`.
- **`TaxAuthorityMessage`**: otro ciclo de vida.
- **Catálogos locales** (CABYS, monedas, unidades): H-3 sigue abierto y ADR-029 hace que
  no sean necesarios para ingerir.
- **Tabla de conflictos**: §15 sólo garantiza que el conflicto no se pueda esconder.
- **Los 7 campos de la errata C-1** y `ProveedorSistemas`: están fuera del MVP; el XML
  crudo los conserva.

---

## 29. Huecos

| Hueco | Estado tras E2 |
|---|---|
| **~~H-6~~** — huella y almacenamiento | **CERRADO PARA EL MVP** (§8). `raw_xml bytea` + `content_sha256 bytea`, SHA-256 sobre bytes exactos, verificado en DEV. La escalabilidad queda como decisión futura con métricas reales, no como bloqueante |
| **H-3** — catálogos externos | **ABIERTO**, no bloquea la ingesta: ADR-029 permite ingerir sin catálogo. Sigue abierto por la **capa de validación/enriquecimiento** contra CABYS y RUT, que no existe. El *formato* de CABYS **sí está cerrado**: 13 dígitos según el BCCR (§12) |
| **H-4** — semántica condicional | **ABIERTO**, no bloquea: las condiciones identificadas son de capa 2, no restricciones (§23) |

### 29.1 Autorización de escritura: diseño cerrado, implementación en E3

```
CONTRATO DE DISEÑO  =  CERRADO EN E2
IMPLEMENTACIÓN      =  E3
```

**No es un hueco.** E2 descubrió que `private.is_company_member` sólo demuestra
pertenencia, y cerró el contrato que faltaba:

| | |
|---|---|
| Política de roles | `owner` y `editor` escriben · `viewer` sólo lee · `DELETE` sin camino de aplicación |
| Helper | `private.can_write_company(uuid)` — contrato completo en §25.5 |
| ACL | `EXECUTE` sólo para `fiscal_backend` (§25.6) |
| Políticas RLS | `SELECT`/`INSERT`/`UPDATE`/`DELETE` definidas en §25.4 |
| Privilegios de columna | 15 columnas mutables en 3 de las 7 tablas (§26.3) |

Lo que resta es **escribir** el helper, las políticas y los `GRANT`. Eso es implementación,
y pertenece a E3 — igual que las siete tablas, que también están diseñadas y no creadas.

Ningún hueco impide **revisar** este diseño, y ninguno impide **implementarlo**.
