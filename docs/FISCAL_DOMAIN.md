# FISCAL_DOMAIN — Dominio de comprobantes electrónicos de Costa Rica

> **Estado:** Fase E0 · revisión **E0-R2** (2026-08-29) — inventario y modelado
> conceptual. **No hay implementación.**
>
> **Base semántica: `ANEXOS Y ESTRUCTURAS_V4.4.pdf`, 99 páginas, Bitácora de Ajustes al
> 22/04/2026**, obtenido de `hacienda.go.cr`. Ver §2.1.
> No existe ninguna tabla fiscal, ni parser, ni Tax Engine. Este documento es el
> resultado de leer las fuentes oficiales, no una especificación de esquema.
>
> **Autoridad.** La estructura la fijan los **XSD oficiales v4.4**; la semántica, los
> **Anexos y Estructuras v4.4** y la **Resolución MH-DGT-RES-0027-2024**. Todo lo que
> aparece aquí se extrajo de esos archivos descargados del dominio de Hacienda, no de
> memoria, blogs, librerías ni repositorios de terceros (Regla 2).
>
> Donde una fuente oficial no resuelve algo, queda marcado como **hueco abierto** en
> §18. No se rellena con un valor plausible.

---

## 1. Versión vigente y revisión del documento técnico

**Versión 4.4.** Es la última publicada en el portal oficial de ATV; no existe 4.5 ni
posterior a fecha de esta revisión (2026-08-29). El portal enumera 1.0, 2.0, 3.0, 3.1,
4.0, 4.1, 4.2, 4.3 y 4.4, y los archivos de 4.4 cuelgan de `docs/esquemas/2024/v4.4/`.
Cada XSD declara `version="4.4"` en el propio `xs:schema`.

### 1.1 Cadena normativa

| Norma | Fecha | Qué hace |
|---|---|---|
| `MH-DGT-RES-0027-2024` | 13-nov-2024 | Resolución **original**: establece las disposiciones técnicas y los Anexos y Estructuras v4.4. Fijaba seis meses desde el 1-dic-2024, es decir el 1-jun-2025 |
| `MH-DGT-RES-0001-2025` | 2025 | **Modificación posterior del plazo**: amplía la implementación |

**Fecha de obligatoriedad de la v4.4: 1 de setiembre de 2025.** El plazo original de la
resolución de 2024 fue ampliado por la modificación posterior.

Cita literal del plazo original, que ya **no** es el vigente:

> «los obligados tributarios contarán con un plazo de seis meses contados a partir del
> primero de diciembre del 2024 a efectos de que implementen y pongan en funcionamiento
> todas las disposiciones contenidas en esta resolución y de los Anexos y Estructuras en
> su versión 4.4»

Se conserva la cita porque explica de dónde salía la fecha de junio de 2025 y deja
constancia de que la fecha vigente proviene de una modificación posterior, no de este
texto. **H-1 queda cerrado.**

### 1.1.bis Confirmación en el propio documento oficial

La revisión de 99 páginas **declara la fecha en su texto**, cosa que la de 98 no hacía:

> «Rige a partir del 01 de setiembre del 2025, a partir de dicha fecha se deroga la
> Versión 4.3, esta y versiones anteriores, únicamente se podrán utilizar para generar
> notas de crédito y débito que ajusten comprobantes emitidos durante su vigencia.»

Dos consecuencias, no una:

1. Confirma el **1 de setiembre de 2025** desde la fuente oficial, sin depender de
   fuentes secundarias.
2. **Las versiones anteriores no desaparecen.** Siguen siendo emisibles para notas de
   crédito y débito que ajusten comprobantes emitidos bajo su vigencia. Un sistema que
   solo acepte v4.4 rechazará documentos legítimos. Refuerza [ADR-026](DECISIONS.md#adr-026):
   la versión del esquema es un dato del documento, no una constante del sistema.

### 1.2 Revisión del documento técnico — dos ejes distintos

La versión del esquema y la revisión del documento técnico **no avanzan juntas**:

| Eje | Valor |
|---|---|
| Versión de esquema | **4.4** (sin cambio) |
| Revisión del documento técnico | **Bitácora de Ajustes al 22/04/2026**, 99 páginas |

**Calendario de la v4.4 — dos cosas distintas que no deben confundirse:**

| Fecha | Qué ocurre |
|---|---|
| **01/09/2025** | Entrada en vigor **general de la v4.4**. Deroga la 4.3, que queda limitada a notas de crédito y débito sobre comprobantes de su vigencia |
| **22/04/2026** | Se publica y queda **disponible** la actualización (Bitácora de Ajustes) |
| antes del **01/11/2026** | **Uso anticipado permitido** de los cambios 2026 |
| **01/11/2026** | Los nuevos códigos pasan a ser **obligatorios** en los sistemas de emisión |

La fecha de 2026 **no** es la entrada en vigor de la v4.4: es la de una revisión del
documento técnico dentro de esa misma versión.

A fecha de hoy (29-ago-2026) estamos en el **periodo de uso anticipado**.

Esta separación es la razón de [ADR-026](DECISIONS.md#adr-026). Ver §1.3 y §19.

### 1.3 Dos ubicaciones oficiales, dos revisiones distintas

Ambas son de Hacienda. Sirven contenido diferente:

| Ubicación | Revisión servida | `Last-Modified` | Páginas |
|---|---|---|---|
| `hacienda.go.cr/docs/ANEXOS_Y_ESTRUCTURAS_V4.4.pdf` | **Bitácora al 22/04/2026** ← **vigente** | `Wed, 13 May 2026 15:26:07 GMT` | **99** |
| `atv.hacienda.go.cr/…/esquemas/2024/v4.4/ANEXOS Y ESTRUCTURAS_V4.4.pdf` | septiembre de 2025 | `Tue, 09 Sep 2025 21:38:46 GMT` | 98 |

**Este documento usa la de 99 páginas como base semántica.**

Que la ruta de ATV siga publicando la revisión anterior es un hecho registrado, no una
conclusión sobre lo que Hacienda publica: publica la actualizada, en `hacienda.go.cr`.
Queda como **incidencia técnica de recuperación** (§18), no como hueco de autoridad
normativa.

Consecuencia práctica: **la URL desde la que se descarga determina qué revisión se
obtiene**. Cualquier proceso futuro de actualización de fuentes debe fijar la ubicación
y contrastar la huella, no confiar en el nombre del archivo — que es idéntico en ambas.

---

## 2. Matriz de fuentes oficiales

Todas descargadas y verificadas (HTTP 200) desde dominios de Hacienda.
Base de los esquemas: `https://atv.hacienda.go.cr/ATV/ComprobanteElectronico/docs/esquemas/2024/v4.4/`

| Fuente oficial | Versión / fecha | Qué gobierna | Uso en nuestro modelo |
|---|---|---|---|
| Portal *Anexos y Estructuras* (ATV) | catálogo vivo | Publicación oficial de esquemas y normas | Confirma qué versiones y tipos existen |
| `FacturaElectronica_V4.4.xsd` … (9 XSD) | 4.4 | **Estructura**: elementos, tipos, cardinalidad | Autoridad estructural del inventario |
| `ANEXOS_Y_ESTRUCTURAS_V4.4.pdf` (**99 págs**, Bitácora al 22/04/2026) | 4.4 rev. 2026 | **Semántica**: descripciones, notas, catálogos | **Base semántica vigente** |
| `ANEXOS Y ESTRUCTURAS_V4.4.pdf` (98 págs, ATV) | 4.4 rev. sep-2025 | Revisión anterior | Solo para el diff de §2.3 |
| `MH-DGT-RES-0027-2024` (9 págs) | 13-nov-2024 | Disposiciones técnicas y vigencia | Versión aplicable y plazos |
| `REGLAMENTO_DE_COMPROBANTES_ELECTRONICOS.pdf` (28 págs) | v4.4 | Marco reglamentario | Contexto normativo |
| `ComprobantesElectronicos-GeneralidadesyVersion4.4.marzo2025.pdf` | marzo 2025 | Divulgación oficial de la DGT | Contraste |
| `Codigodemoneda_V4.4.pdf`, `Codificacionubicacion_V4.4`, `Nota_9_Codigo_Forma_Farmaceutica.xlsx` | 4.4 | Catálogos | Pendientes de incorporar |

Fuentes secundarias consultadas solo para contraste técnico; **ninguna** se usa como
autoridad fiscal.

### 2.1 Huellas de los archivos analizados

`sha256`, verificadas el 2026-08-29 y estables entre descargas separadas:

| Archivo | sha256 (truncado) |
|---|---|
| `FacturaElectronica_V4.4.xsd` | `d384afef665573606f6499b2182d6070…` |
| `NotaCreditoElectronica_V4.4.xsd` | `9af7dff4ee0c2787f8fc30cb63aef37b…` |
| `NotaDebitoElectronica_V4.4.xsd` | `ac2c63f93602502af22980a81f26032c…` |
| `TiqueteElectronico_V4.4.xsd` | `cda1c7dd97f9a235111c29948f05d789…` |
| `FacturaElectronicaCompra_V4.4.xsd` | `ae1e5b782b568d225b34e046858012ed…` |
| `FacturaElectronicaExportacion_V4.4.xsd` | `d710032a05cd3d41272c0cceb8130b4a…` |
| `ReciboElectronicoPago_V4.4.xsd` | `81d7be9cd9fc3792c2bb3822079784b8…` |
| `MensajeReceptor_V4.4.xsd` | `37bc1ffcf06a66a5a0b63b2908740dbd…` |
| `MensajeHacienda_V4.4.xsd` | `411d858b0e2e293322910a0d4204243d…` |
| **`ANEXOS_Y_ESTRUCTURAS_V4.4.pdf` (99 págs) — vigente** | **`6e093226b29b38c5c8de825f70c1b1cb`** `8ed81e2f4a6eb0b3ff52708fc1eb2769` |
| `ANEXOS Y ESTRUCTURAS_V4.4.pdf` (98 págs, revisión anterior) | `2e36bd1101bbcabbb391ab1ec8ffc377…` |

Registrarlas permite detectar en el futuro si Hacienda actualiza un archivo sin cambiar
su nombre ni la versión declarada — que es exactamente lo que [ADR-026](DECISIONS.md#adr-026)
anticipa.

### 2.3 Diff semántico: revisión sep-2025 → revisión 22/04/2026

La Bitácora enumera **cinco ajustes**, transcritos del documento oficial:

> 1. Se ajusta la descripción de los campos relacionados con el número de Identificación,
>    con el fin de aclarar que se permite el uso de caracteres alfanuméricos para personas
>    jurídicas, en concordancia con las disposiciones del Registro Nacional.
> 2. Se incluye excepción en el campo teléfono para números telefónicos especiales, por
>    ejemplo: 911.
> 3. Se agrega mayor detalle a la descripción del campo IVA Devuelto para el uso correcto
>    del mismo.
> 4. Se incluyen en la nota 9 los códigos 13, 14, 15, 16 y 17 y se ajusta el código 12
>    para la correcta aplicación de los efectos contables del crédito indicado.
> 5. Se incluyen en la nota 10 los códigos 19 y 20.

Comparando el texto de ambas revisiones frase a frase (1.278 → 1.306 frases):

| Área | Cambio verificado |
|---|---|
| **Identificaciones** | Se añade «Permite ingresar números y letras para personas jurídicas» y «La "Cédula de personas Jurídicas" debe contener 10 caracteres y sin guiones» |
| **Teléfono** | «Deberá contener mínimo 8 dígitos y un máximo de 20, **excepto en aquellos casos que se posea un número telefónico especial, por ejemplo, el 911**» |
| **IVA Devuelto** | Se añade una **fórmula explícita** para ventas mixtas (§10.1) |
| **Nota 9** | 12 → **17 códigos**, más una nota nueva sobre efecto contable (§9.1) |
| **Nota 10** | 18 → **20 códigos** (§9.3) |
| **Vigencia** | El documento pasa a declarar «Rige a partir del 01 de setiembre del 2025» (§1.1.bis) |

### 2.2 Estado de los 9 XSD: **sin cambios estructurales**

Se descargaron de nuevo íntegramente y se compararon con las copias usadas en el E0
original: **9 idénticos, 0 distintos**. Byte a byte, no «equivalentes».

Consecuencia: el inventario de 180 nodos y toda conclusión derivada del XSD siguen
siendo válidos. Se recomprobó ejecutando de nuevo el extractor sobre los archivos
re-descargados — inventario idéntico, no heredado.

**Y la revisión de 2026 tampoco añade elementos.** Se extrajeron todos los
identificadores con forma de etiqueta XML de ambos PDF y se compararon: los únicos
tokens nuevos son `Ajustes` y `Tratamiento`, palabras de prosa («Bitácora de Ajustes»,
«Tratamiento de códigos»), ninguna coincidente con un elemento del esquema. La revisión
cambia **descripciones, notas y catálogos**, no la forma del documento — que es
exactamente la tesis de [ADR-026](DECISIONS.md#adr-026), ahora comprobada.

---

## 3. Tipos de documento oficiales v4.4

Nueve XSD. Siete son comprobantes emitibles; dos son mensajes.

| Tipo | XSD oficial | Código (dígitos 9-10 del consecutivo) | Namespace |
|---|---|---|---|
| Factura Electrónica | `FacturaElectronica_V4.4.xsd` | `01` | `…/v4.4/facturaElectronica` |
| Nota de Débito Electrónica | `NotaDebitoElectronica_V4.4.xsd` | `02` | `…/v4.4/notaDebitoElectronica` |
| Nota de Crédito Electrónica | `NotaCreditoElectronica_V4.4.xsd` | `03` | `…/v4.4/notaCreditoElectronica` |
| Tiquete Electrónico | `TiqueteElectronico_V4.4.xsd` | `04` | `…/v4.4/tiqueteElectronico` |
| Factura Electrónica de Compra | `FacturaElectronicaCompra_V4.4.xsd` | `08` | `…/v4.4/facturaElectronicaCompra` |
| Factura Electrónica de Exportación | `FacturaElectronicaExportacion_V4.4.xsd` | `09` | `…/v4.4/facturaElectronicaExportacion` |
| Recibo Electrónico de Pago | `ReciboElectronicoPago_V4.4.xsd` | `10` | `…/v4.4/reciboElectronicoPago` |
| Mensaje Receptor | `MensajeReceptor_V4.4.xsd` | `05`/`06`/`07` (aceptación, parcial, rechazo) | `…/v4.4/mensajeReceptor` |
| Mensaje Hacienda | `MensajeHacienda_V4.4.xsd` | — | `…/v4.4/mensajeHacienda` |

Los nueve nombres del prompt de apertura existen y son correctos.

### 3.1 Comparación estructural — evidencia, no suposición

Recorriendo los siete XSD emitibles y comparando conjuntos de rutas:

| Tipo | Nodos | Ausentes respecto a FE | Exclusivos |
|---|---|---|---|
| Factura Electrónica | 180 | — | — |
| Tiquete Electrónico | 178 | `CodigoActividadReceptor`, `TipoTransaccion` | ninguno |
| Nota de Crédito | 182 | ninguno | `MontoExportacion`, `PartidaArancelaria` |
| Nota de Débito | 182 | ninguno | `MontoExportacion`, `PartidaArancelaria` |
| Factura de Compra | 140 | 41 (todo `Surtido`, `DatosImpuestoEspecifico`) | `OtrasSenasExtranjero` |
| Factura de Exportación | 139 | 43 (`Exoneracion`, detalle de `Ubicacion`…) | `MontoExportacion`, `PartidaArancelaria` |
| Recibo Electrónico de Pago | 57 | 123 | ninguno |

Y en la raíz, las diferencias son **de cardinalidad, no de forma**:

| Elemento raíz | FE | TE | NC | ND | FEC | FEE | REP |
|---|---|---|---|---|---|---|---|
| `Clave` | 1..1 | 1..1 | 1..1 | 1..1 | 1..1 | 1..1 | 1..1 |
| `CodigoActividadEmisor` | 1..1 | 1..1 | 0..1 | 0..1 | 0..1 | 1..1 | — |
| `CodigoActividadReceptor` | 0..1 | — | 0..1 | 0..1 | **1..1** | — | — |
| `Emisor` | 1..1 | 1..1 | 1..1 | 1..1 | 1..1 | 1..1 | 1..1 |
| `Receptor` | **1..1** | 0..1 | 0..1 | 0..1 | **1..1** | 0..1 | **1..1** |
| `DetalleServicio` | 0..1 | 0..1 | 0..1 | 0..1 | **1..1** | **1..1** | **1..1** |
| `OtrosCargos` | 0..15 | 0..15 | 0..15 | 0..15 | 0..15 | 0..15 | — |
| `ResumenFactura` | 1..1 | 1..1 | 1..1 | 1..1 | 1..1 | 1..1 | 1..1 |
| `InformacionReferencia` | 0..10 | 0..10 | **1..10** | **1..10** | **1..10** | 0..10 | **1..10** |
| `ds:Signature` | 1..5 | 1..5 | 1..5 | 1..5 | 1..5 | 1..5 | 1..5 |

**Lectura.** Los siete comparten el mismo esqueleto: identificación, emisor, receptor,
líneas, resumen, referencias y firma. Nota de Crédito y Nota de Débito son
**estructuralmente Factura Electrónica** más dos campos de exportación, y no les falta
nada. El Recibo Electrónico de Pago es el atípico.

Esto **respalda un modelo unificado con discriminador de tipo**, no siete modelos
paralelos. La decisión se propone en §11 y no se da por cerrada aquí.

### 3.2 El ejemplo del prompt no coincidía con el XSD

Se verificó campo a campo. Dos diferencias reales frente al esquema de apertura:

- **`MedioPago` no está en la raíz.** En v4.4 vive dentro de `ResumenFactura`, es
  `[0..4]` y es una estructura compuesta (`TipoMedioPago`, `MedioPagoOtros`,
  `TotalMedioPago`), no un valor simple.
- **`Signature`** no es un elemento propio: es `ref="ds:Signature"` con cardinalidad
  `[1..5]`, importado de `http://www.w3.org/2000/09/xmldsig#`.

---

## 4. Identificación mecánica del documento (para el parser futuro)

Los nueve tipos tienen **namespace propio y versionado**. El tipo y la versión
estructural se determinan mecánicamente a partir del namespace del elemento raíz, sin
heurísticas:

```
https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.4/<tipoEnCamelCase>
                                            └── versión ──┘ └─── tipo ───┘
```

**La instancia XML no lleva un campo literal de versión.** El atributo `version="4.4"`
—junto a `elementFormDefault="qualified"`— pertenece al `xs:schema`, es decir al XSD, no
al comprobante. Lo que el documento sí trae es el namespace, y de él se deriva la versión
estructural.

Redundancia útil: el tipo también está en los dígitos 9-10 del `NumeroConsecutivo`, que
a su vez está embebido en la `Clave`. Tres fuentes independientes que deben concordar
— una comprobación de integridad barata.

---

## 5. Clave y NumeroConsecutivo

Ambos son cadenas de dígitos con longitud fija, según los XSD:

| Campo | Tipo XSD | Restricción |
|---|---|---|
| `Clave` | `ClaveType` | `xs:string`, `pattern="\d{50,50}"` |
| `NumeroConsecutivo` | `NumeroConsecutivoType` | `xs:string`, `pattern="\d{20,20}"` |

**Son identificadores, no números.** Se guardan como texto: tienen ceros a la izquierda
significativos y ninguna aritmética tiene sentido sobre ellos.

### 5.1 NumeroConsecutivo — 20 dígitos (Anexos v4.4, pág. 65)

| Posición | Longitud | Significado |
|---|---|---|
| 1–3 | 3 | Local o establecimiento. `001` = casa matriz; `002`+ = sucursales |
| 4–8 | 5 | Terminal o punto de venta. `00001` si hay una sola o servidor centralizado |
| 9–10 | 2 | Tipo de comprobante (tabla de §3) |
| 11–20 | 10 | Consecutivo, empieza en 1 **por sucursal/terminal**; puede reiniciarse al llegar al tope |

### 5.2 Clave — 50 dígitos (Anexos v4.4, págs. 66-67)

| Posición | Longitud | Significado |
|---|---|---|
| 1–3 | 3 | Código de país (`506`) |
| 4–5 | 2 | Día de generación |
| 6–7 | 2 | Mes de generación |
| 8–9 | 2 | Año de generación |
| 10–21 | 12 | Cédula del emisor |
| 22–41 | 20 | **El `NumeroConsecutivo` completo** |
| 42 | 1 | Situación: `1` Normal · `2` Contingencia · `3` Sin internet |
| 43–50 | 8 | Código de seguridad, generado por el sistema del obligado tributario |

**Consecuencia de modelado.** La `Clave` **contiene** el consecutivo, así que no son
independientes: guardar ambos es redundancia deliberada y verificable, no duplicación
accidental. La unicidad natural es la `Clave`; el consecutivo solo es único dentro de
emisor + sucursal + terminal + tipo, y **puede reiniciarse**, así que por sí solo no
sirve como identidad. El dígito 42 explica además por qué pueden existir comprobantes
de contingencia que reemplazan a otros.

---

## 6. Exactitud numérica

Extraído de los `simpleType` del XSD. **Nada de coma flotante** (Regla, convenciones).

| Campo | Tipo XSD | Restricciones |
|---|---|---|
| Todos los importes monetarios | `DecimalDineroType` | `xs:decimal`, `totalDigits=18`, `fractionDigits=5`, `minInclusive=0`, `maxInclusive=9999999999999.99999` |
| `Cantidad` | `xs:decimal` | `totalDigits=16`, `fractionDigits=3` |
| `Tarifa`, `TarifaExonerada`, `Porcentaje` | `xs:decimal` | `totalDigits=4`, `fractionDigits=2` |
| `FactorCalculoIVA` | `xs:decimal` | `totalDigits=5`, `fractionDigits=4` |
| `Proporcion` | `xs:decimal` | `totalDigits=10`, `fractionDigits=5` |
| `PorcentajeOC` | `xs:decimal` | `totalDigits=9`, `fractionDigits=5`, `minInclusive=0` |
| `CantidadUnidadMedida`, `VolumenUnidadConsumo` | `xs:decimal` | `totalDigits=7`, `fractionDigits=2` |
| `NumeroLinea` | `xs:positiveInteger` | `minInclusive=1`, `maxInclusive=1000` |
| `PlazoCredito` | `xs:integer` | `totalDigits=5` |

`DecimalDineroType` con 18 dígitos totales y 5 decimales implica 13 dígitos enteros.
Cualquier tipo destino debe cubrir eso **sin truncar los cinco decimales**: el importe
unitario los usa de verdad. La elección concreta del tipo de PostgreSQL se decidirá al
diseñar cada tabla, con esta evidencia delante.

Obsérvese que `minInclusive=0`: **el XSD no admite importes negativos en ningún
comprobante**, tampoco en notas de crédito. El signo lo aporta el tipo de documento, no
el importe. Es determinante para cualquier futuro cálculo de saldos.

---

## 7. Fechas y zona horaria

Los tres campos de fecha del comprobante son `xs:dateTime`:
`FechaEmision`, `InformacionReferencia/FechaEmisionIR`, `Exoneracion/FechaEmisionEX`.

Los Anexos v4.4 lo precisan:

> «Tipo de dato de fecha y hora, basado en el estándar RFC3339 sección 5.6, tipo
> "date-time". Formato: `YYYY-MM-DDThh:mi:ss[Z|(+|-)hh:mm]` Ejemplo:
> `2016-09-26T13:00:00+06:00`. Validación: Se verificará el cumplimiento del formato
> indicado caso contrario se rechazará el comprobante. No podrán señalarse fechas
> posteriores ni anteriores a la fecha de generación del comprobante.»

**La fuente es ambigua sobre si el desplazamiento es obligatorio**, y conviene decirlo con
precisión:

| Lo que dice la fuente | Qué implica |
|---|---|
| Cita «RFC3339 sección 5.6, tipo `date-time`» | En el ABNF de RFC 3339, `full-time = partial-time time-offset` **sin corchetes**: el desplazamiento sería obligatorio |
| Escribe el formato `…ss[Z\|(+\|-)hh:mm]` | Los **corchetes** marcan la parte opcional —compárese con `[time-secfrac]` en el propio RFC—: el desplazamiento sería opcional |
| «Se verificará el cumplimiento **del formato indicado**» | La validación remite al formato escrito, que es el de los corchetes |

**No hay texto normativo explícito que declare obligatorio el desplazamiento.** El XSD lo
resuelve de hecho: declara `xs:dateTime`, cuyo huso es opcional. Y la práctica lo
confirma —4 de 13 comprobantes reales aceptados por Hacienda no lo declaran (E4-A2)—.

**Cuando el desplazamiento está, el instante es inequívoco; cuando falta, no se infiere.**
El desplazamiento local es además información fiscal —determina a qué periodo pertenece
un comprobante— y se pierde al normalizar a UTC. La conclusión de diseño es que el
instante y el desplazamiento original son **dos datos distintos**, y el XML crudo
conserva la forma literal en cualquier caso. Ver [ADR-039](DECISIONS.md#adr-039).

> **Frontera de la evidencia.** La afirmación sobre el XSD —`FechaEmision` declarado como
> `xs:dateTime` puro, sin `xs:pattern`, sin `simpleType` propio y sin `explicitTimezone`—
> procede de una **inspección real de los XSD oficiales v4.4 realizada en A2-B1**, y quedó
> transcrita en [ADR-039](DECISIONS.md#adr-039) y en la cabecera de la migración de fechas.
>
> **Hoy no es reproducible desde un clon limpio de este repositorio**: los XSD oficiales no
> están versionados aquí, tampoco su dependencia `xmldsig-core-schema.xsd`, y el acceso al
> CDN oficial no es reproducible desde el entorno de trabajo. **A2-C** se hará cargo de esa
> verificabilidad. La conclusión de ADR-039 no se debilita —la inspección ocurrió y está
> registrada—; lo que falta es poder repetirla sin depender de nadie.

*(El ejemplo oficial escribe `+06:00` mientras Costa Rica es UTC−6. Es **un ejemplo de
la sintaxis RFC3339, no una regla de zona horaria**: el documento ilustra el formato
`[Z|(+|-)hh:mm]`, no prescribe un desplazamiento. No es un hueco ni afecta a nada de lo
anterior.)*

---

## 8. Estructuras anidadas

### 8.1 Emisor y Receptor — no son la misma estructura

| Campo | Emisor | Receptor |
|---|---|---|
| `Nombre` | 1..1 | 1..1 |
| `Identificacion` (`Tipo`, `Numero`) | 1..1 | 1..1 |
| `Registrofiscal8707` | 0..1 | — |
| `NombreComercial` | 0..1 | 0..1 |
| `Ubicacion` (`Provincia`, `Canton`, `Distrito`, `Barrio`, `OtrasSenas`) | **1..1** | 0..1 |
| `OtrasSenasExtranjero` | — | 0..1 |
| `Telefono` (`CodigoPais`, `NumTelefono`) | 0..1 | 0..1 |
| `CorreoElectronico` | **1..4** | 0..1 |

Dos asimetrías importan: `Ubicacion` es obligatoria para el emisor y opcional para el
receptor, y el emisor puede declarar **hasta cuatro** correos mientras el receptor
declara como mucho uno.

### 8.2 Línea de detalle

`DetalleServicio` `[0..1]` → `LineaDetalle` `[1..1000]`. Campos:

`NumeroLinea`, `CodigoCABYS`, `CodigoComercial[0..5]`, `Cantidad`, `UnidadMedida`,
`TipoTransaccion`, `UnidadMedidaComercial`, `Detalle`, `NumeroVINoSerie[0..1000]`,
`RegistroMedicamento`, `FormaFarmaceutica`, `DetalleSurtido[0..1]`, `PrecioUnitario`,
`MontoTotal`, `Descuento[0..5]`, `SubTotal`, `IVACobradoFabrica`, `BaseImponible`,
`Impuesto[1..1000]`, `ImpuestoAsumidoEmisorFabrica`, `ImpuestoNeto`, `MontoTotalLinea`.

Tres observaciones con consecuencias:

1. **`Impuesto` es obligatorio y repetible** (`[1..1000]`): toda línea lleva al menos un
   impuesto, y una línea puede acumular varios.
2. **`Descuento` es `[0..5]`**: los descuentos son una colección, no un campo.
3. **`DetalleSurtido` es un sub-modelo de línea completo y paralelo**
   (`LineaDetalleSurtido[1..20]`), con su propio CABYS, cantidad, precio, descuentos,
   base imponible e impuestos —incluidos impuestos específicos—. Es prácticamente una
   segunda jerarquía de líneas dentro de la línea. Ignorarlo al diseñar sería un error
   estructural; normalizarlo en el MVP, un coste desproporcionado. Ver §10.

### 8.3 ResumenFactura

Veintiséis elementos. Un bloque de moneda (`CodigoTipoMoneda` → `CodigoMoneda`,
`TipoCambio`), trece totales por naturaleza (servicios/mercancías × gravado, exento,
exonerado, no sujeto, más los cuatro agregados), `TotalVenta`, `TotalDescuentos`,
`TotalVentaNeta`, un desglose repetible `TotalDesgloseImpuesto[0..1000]`,
`TotalImpuesto`, `TotalImpAsumEmisorFabrica`, `TotalIVADevuelto`, `TotalOtrosCargos`,
`MedioPago[0..4]` y `TotalComprobante`.

Solo cuatro son obligatorios: `CodigoTipoMoneda`, `TotalVenta`, `TotalVentaNeta` y
`TotalComprobante`. Todos los demás son opcionales, así que **la ausencia de un total no
significa cero**: significa que no se declaró. Es exactamente el tipo de matiz que un
modelo con `NOT NULL DEFAULT 0` destruiría.

---

## 9. Referencias entre comprobantes

`InformacionReferencia` `[0..10]`:

| Campo | Tipo | Card. |
|---|---|---|
| `TipoDocIR` | `TipoDocReferenciaType` (19 valores) | 1..1 |
| `TipoDocRefOTRO` | string | 0..1 |
| `Numero` | string | **0..1** |
| `FechaEmisionIR` | `xs:dateTime` | 1..1 |
| `Codigo` | `CodigoReferenciaType` (12 valores: 01,02,04–12,99) | 0..1 |
| `CodigoReferenciaOTRO` | string | 0..1 |
| `Razon` | string | 0..1 |

Cómo se relacionan los documentos:

- Una **Nota de Crédito** o **Nota de Débito** debe llevar `InformacionReferencia`
  mínimo una vez (`1..10`): no pueden existir sin apuntar a algo.
- La **Factura de Compra** y el **Recibo Electrónico de Pago** también la exigen.
- Un comprobante puede referenciar **hasta diez** documentos, así que la relación es
  de muchos a muchos, no una clave foránea simple.
- **`Numero` es opcional.** Una referencia puede no traer identificador del documento
  referenciado. Cualquier diseño que asuma una FK obligatoria hacia otro comprobante
  contradice el esquema.
- La enumeración de `CodigoReferenciaType` es `01, 02, 04, 05, 06, 07, 08, 09, 10, 11,
  12, 99`: **el `03` no existe**. Un hueco en la secuencia delata un código retirado en
  alguna versión. Los catálogos son versionados y cambian, así que se guardan como los
  códigos que son, no como enumeraciones cerradas del modelo.

Además, el dígito 42 de la `Clave` distingue comprobantes de contingencia, que por
naturaleza sustituyen a otros documentos.

### 9.1 Nota 9 — códigos de referencia (revisión 22/04/2026)

Leído del documento oficial de 99 páginas. **Diecisiete códigos**, `03` ausente:

| Código | Descripción | Novedad 2026 |
|---|---|---|
| `01` | Anula Documento de Referencia | |
| `02` | Corrige monto | |
| `04` | Referencia a otro documento | |
| `05` | Sustituye comprobante provisional por contingencia | |
| `06` | Devolución de mercancía | |
| `07` | Sustituye comprobante electrónico | |
| `08` | Factura Endosada | |
| `09` | Nota de crédito financiera | |
| `10` | Nota de débito financiera | |
| `11` | Proveedor No Domiciliado | |
| `12` | **Nota de crédito financiera** por exoneración posterior a la facturación | **ajustado** |
| `13` | Anula documento de referencia por error material | **nuevo** |
| `14` | Corrige monto por error material | **nuevo** |
| `15` | Sustituye comprobante electrónico por error material | **nuevo** |
| `16` | Sustituye comprobante electrónico rechazado | **nuevo** |
| `17` | Pago a comprobante electrónico — *uso exclusivo del Recibo Electrónico de Pago* | **nuevo** |
| `99` | Otros | |

El `03` sigue ausente. **No inventamos el motivo**: el documento no lo explica.

El `12` cambió de «Crédito por exoneración posterior a la facturación» a «**Nota de
crédito financiera** por exoneración posterior a la facturación».

### 9.2 El código de referencia determina el periodo contable

La revisión 2026 añade una nota normativa que convierte estos códigos en algo más que
etiquetas descriptivas. Transcrita del documento oficial:

> «Tratamiento de códigos para notas de crédito y débito según su efecto contable en las
> declaraciones autoliquidativas.
>
> 1. Los códigos "01", "02" y "06", cuando se utilizan en las notas de crédito o débito,
>    deben reflejar su efecto contable **en el mismo período en el cual se generó la nota
>    de crédito**. En el caso del código "01", cuando sea necesario generar un nuevo
>    comprobante electrónico deberá indicar en el apartado de referencia de este último
>    el código "07" […]
> 2. Los códigos "13" y "14" […] deben reflejar su efecto contable **en el mismo período
>    del comprobante electrónico que se está modificando** […] En el caso del código
>    "13", cuando sea necesario generar un nuevo comprobante electrónico deberá indicar
>    […] el código "15".
> 3. El código 12 […] deben reflejar su efecto contable en el mismo período en el cual se
>    generó la nota de crédito.»

**Es el hallazgo de dominio más importante de esta revisión.** La distinción entre
`01/02` y `13/14` no es de matiz: determina **a qué periodo fiscal se imputa el ajuste**.

- `01`, `02`, `06`, `12` → periodo de **la nota**.
- `13`, `14` → periodo del **comprobante original**.

Y define cadenas obligatorias entre documentos: `01` → nuevo comprobante con `07`;
`13` → nuevo comprobante con `15`.

Consecuencias de diseño, no de implementación:

1. El periodo fiscal de un ajuste **no se deduce de su fecha de emisión**. Depende del
   código de referencia. Cualquier agregación por periodo que ignore esto producirá
   cifras incorrectas — el error exacto que este producto existe para evitar.
2. `DocumentReference` no es un enlace inerte: transporta semántica contable.
3. Las cadenas `01→07` y `13→15` son relaciones entre tres documentos, no dos.

### 9.3 Nota 10 — tipo de documento de referencia (revisión 22/04/2026)

**Veinte códigos.** La revisión 2026 añade los dos últimos:

| Código | Descripción |
|---|---|
| `01` | Factura electrónica |
| `02` | Nota de débito electrónica |
| `03` | Nota de crédito electrónica |
| `04` | Tiquete electrónico |
| `05` | Nota de despacho |
| `06` | Contrato |
| `07` | Procedimiento |
| `08` | Comprobante emitido en contingencia |
| `09` | Devolución mercadería — *solo notas de crédito y débito* |
| `10` | Comprobante electrónico rechazado por el Ministerio de Hacienda |
| `11` | Sustituye factura rechazada por el Receptor del comprobante |
| `12` | Sustituye Factura de exportación |
| `13` | Facturación mes vencido |
| `14` | Comprobante aportado por contribuyente de Régimen Especial |
| `15` | Sustituye una Factura electrónica de Compra |
| `16` | Comprobante de Proveedor No Domiciliado — *solo Factura Electrónica de Compra* |
| `17` | Nota de Crédito a Factura Electrónica de Compra |
| `18` | Nota de Débito a Factura Electrónica de Compra |
| `19` | **Factura Electrónica de Exportación** — **nuevo 2026** |
| `20` | **Recibo Electrónico de Pago** — **nuevo 2026** |
| `99` | Otros |

**Consecuencia sobre `DocumentReference`.** Los códigos `19` y `20` permiten referenciar
por primera vez, de forma explícita, una Factura de Exportación y un Recibo Electrónico
de Pago. Junto con el `17` de la nota 9 —«Pago a comprobante electrónico», exclusivo del
REP— cierran el circuito de aplicación de pagos: un REP puede ahora apuntar
inequívocamente al comprobante que salda.

Esto **refuerza** la conclusión de §16: `DocumentReference` debe ser una entidad propia
con tipo, código y cardinalidad, no una clave foránea. El conjunto de documentos
referenciables creció de 18 a 20 valores **sin cambiar el esquema**, y volverá a crecer.

El `13` merece una nota aparte: «Facturación mes vencido» exige indicar en la fecha del
documento de referencia **el periodo fiscal al que pertenece el ingreso**, no la fecha
real. Es un segundo mecanismo, independiente del anterior, por el que el periodo fiscal
diverge de la fecha de emisión.


---

## 10. Impuestos — lo que el comprobante **reporta**

> Este inventario describe **cómo el XML representa los impuestos**. No es un conjunto
> de reglas de cálculo. El Tax Engine no existe todavía y esta fase no lo diseña.

Estructura `ImpuestoType`, dentro de cada línea:

| Campo | Tipo | Card. |
|---|---|---|
| `Codigo` | `CodigoImpuestoType` | 1..1 |
| `CodigoImpuestoOTRO` | string | 0..1 |
| `CodigoTarifaIVA` | `CodigoTarifaIVAType` | 0..1 |
| `Tarifa` | decimal(4,2) | 0..1 |
| `FactorCalculoIVA` | decimal(5,4) | 0..1 |
| `DatosImpuestoEspecifico` | compuesto | 0..1 |
| `Monto` | `DecimalDineroType` | 1..1 |
| `Exoneracion` | `ExoneracionType` | 0..1 |

**Códigos de impuesto** (Anexos v4.4, nota 8):

| Código | Impuesto |
|---|---|
| `01` | Impuesto al Valor Agregado |
| `02` | Impuesto Selectivo de Consumo |
| `03` | Impuesto Único a los Combustibles |
| `04` | Impuesto específico de Bebidas Alcohólicas |
| `05` | Impuesto Específico sobre bebidas envasadas sin contenido alcohólico y jabones de tocador |
| `06` | Impuesto a los Productos de Tabaco |
| `07` | IVA (cálculo especial) |
| `08` | IVA Régimen de Bienes Usados (Factor) |
| `12` | Impuesto Específico al Cemento |
| `99` | Otros |

**Códigos de tarifa de IVA** (Anexos v4.4, nota 8.1):

| Código | Tarifa |
|---|---|
| `01` | Tarifa 0% (Artículo 32, num 1, RLIVA) |
| `02` | Tarifa reducida 1% |
| `03` | Tarifa reducida 2% |
| `04` | Tarifa reducida 4% |
| `05` | Transitorio 0% (solo notas de crédito/débito) |
| `06` | Transitorio 4% (solo notas de crédito/débito) |
| `07` | Tarifa transitoria 8% **(código inhabilitado)** |
| `08` | Tarifa general 13% |
| `09` | Tarifa reducida 0.5% |
| `10` | Tarifa Exenta |
| `11` | Tarifa 0% sin derecho a crédito |

Estas tablas se transcriben de los Anexos v4.4 **como catálogo del formato**, con su
fuente y versión. No son reglas de nuestro Tax Engine, y su vigencia no se afirma más
allá de lo que dice el documento citado.

### 10.1 `TotalIVADevuelto` — una fórmula **reportada**, no calculada por nosotros

La revisión 2026 detalla el campo. Obligatorio cuando se facturan servicios de salud
pagados con tarjeta. Antes decía solo que se obtiene «de la sumatoria del Monto de los
Impuestos pagado por los servicios de salud en tarjetas»; ahora añade el caso mixto:

> «Cuando se genere una venta de un servicio de salud con más de un medio de pago y/o se
> incluyan otros productos o servicios, además de los servicios de salud se debe aplicar
> la siguiente fórmula:
>
> `Monto IVA Devuelto = (monto pagado tarjeta / venta neta) * Monto del impuesto`»

Se transcribe **como regla del formato**, con su fuente. Es exactamente el límite de
[ADR-023](DECISIONS.md#adr-023): esta fórmula describe cómo el emisor debe obtener el
valor que **reporta**. Que nuestro Tax Engine la recalcule algún día y compare con lo
reportado es otra cosa, y esa comparación es precisamente el valor del producto. Nunca
sobrescribiremos `reported_total_iva_devuelto` con nuestro resultado.

**`Exoneracion`** cuelga de cada impuesto (`0..1`): `TipoDocumentoEX1`,
`TipoDocumentoOTRO`, `NumeroDocumento`, `Articulo`, `Inciso`, `NombreInstitucion`,
`NombreInstitucionOtros`, `FechaEmisionEX`, `TarifaExonerada`, `MontoExoneracion`.
Es decir: la exoneración es un atributo del impuesto de la línea, no del documento.

---

## 11. Modelo de dominio propuesto — **propuesta, no decisión**

Sin SQL. Entidades conceptuales, con responsabilidad y límites explícitos.

### `SourceDocument` — el artefacto original
- **Contiene:** el XML íntegro tal como se recibió, su huella criptográfica, metadatos
  de procedencia (origen, momento de ingesta, empresa), y la versión/tipo detectados.
- **No contiene:** ningún valor fiscal interpretado.
- **Responsabilidad:** ser la única respuesta a «¿de dónde salió esto?». Inmutable.

### `ElectronicDocument` — el comprobante normalizado
- **Contiene:** `Clave`, `NumeroConsecutivo`, tipo, versión, la fecha de emisión —siempre
  su fecha/hora civil y su literal; el desplazamiento y el instante absoluto **solo si el
  XML declara el desplazamiento**, que nunca se infiere ([ADR-039](DECISIONS.md#adr-039))—,
  moneda y tipo de cambio, y los totales `reported_*` del resumen.
- **No contiene:** el XML; ni un solo valor calculado por nosotros.
- **Relación:** representa la interpretación normalizada de **uno o más**
  `SourceDocument` equivalentes pertenecientes al mismo tenant, y pertenece a una
  empresa. Un `SourceDocument` puede no producir ningún `ElectronicDocument` si está
  pendiente, es inválido, de versión desconocida o no soportada, o falla su
  interpretación. Cardinalidades en
  [FISCAL_LOGICAL_MODEL.md](FISCAL_LOGICAL_MODEL.md) §3.2.

### `DocumentParty` — emisor y receptor **como instantánea**
- **Contiene:** nombre, identificación, nombre comercial, ubicación, teléfono y correos
  tal como aparecían **en ese comprobante**.
- **No contiene:** referencia a un catálogo mutable de empresas.
- **Razón:** ver §12.

### `DocumentLine` — línea de detalle
- **Contiene:** número de línea, CABYS, detalle, cantidad, unidad, precios y totales de
  línea `reported_*`.
- **No contiene:** impuestos ni descuentos: son colecciones.

### `LineTax` — impuesto de línea
- **Contiene:** código de impuesto, código de tarifa, tarifa, monto reportado y, si
  existe, los datos de exoneración.
- **No contiene:** nuestro cálculo del impuesto.

### `LineDiscount` — descuento de línea (`[0..5]`)

### `DocumentReference` — enlace a otro comprobante
- **Contiene:** tipo de documento referenciado, número (opcional), fecha, código y razón.
- **No contiene:** una clave foránea obligatoria — el número puede faltar.

### `DocumentPayment` — medio de pago (`ResumenFactura/MedioPago`, `[0..4]`)

### `DocumentCharge` — otros cargos (`[0..15]`), con identificación de tercero

### `TaxAuthorityMessage` — respuesta de Hacienda
- **Contiene:** el resultado comunicado por Hacienda o por el receptor.
- **No contiene:** nada del contenido reportado por el emisor.
- Se relaciona **solo por `Clave`**: ver §14.

Quedan deliberadamente fuera del MVP: `DetalleSurtido` y sus impuestos específicos,
que viven en el XML crudo hasta que exista una necesidad funcional.

---

## 12. Emisor y receptor: instantánea, no clave foránea

**Recomendación: instantánea (`snapshot`).**

Un comprobante es una declaración sobre un momento. Si en 2026 la factura dice que el
emisor se llamaba «Empresa X» y estaba en cierta dirección, eso siguió siendo cierto en
2026 aunque la empresa cambie de nombre en 2027. Con una clave foránea a una tabla
mutable de empresas, actualizar ese registro reescribiría el pasado: la factura de 2026
empezaría a mostrar datos que nunca contuvo. Para un sistema tributario, cuyo valor es
poder demostrar qué decía un documento, eso es inaceptable.

La instantánea tampoco impide agregar por contribuyente: la identificación (`Tipo` +
`Numero`) permite agrupar sin convertir el catálogo en autoridad sobre el pasado. Si más
adelante hace falta una entidad de contraparte, se construye **sobre** las instantáneas,
nunca sustituyéndolas.

---

## 13. Principios de dominio

### 13.1 `reported_*` frente a `computed_*`

```
reported_*  valor tomado literalmente del comprobante
computed_*  valor calculado por nuestro Tax Engine
```

Nunca uno sobrescribe al otro. Nunca se presenta un `computed_*` como si lo hubiera
reportado el emisor o Hacienda. Que ambos difieran es **información**, no un error a
ocultar: es precisamente lo que un asistente tributario debe saber señalar.

### 13.2 El XML original se conserva

El XML crudo se preserva íntegro aunque normalicemos sus campos, porque:

1. **Es el documento con valor probatorio**, no nuestra interpretación de él.
2. **Nuestro parser evolucionará.** Al corregir un error de interpretación hay que poder
   reprocesar; sin el original, el error es permanente.
3. **La clasificación C de §15 depende de ello.** Solo podemos dejar información fuera
   del modelo relacional porque el original la sigue conteniendo.
4. **Elimina el riesgo sobre la firma.** XAdES/XML-DSig firma una forma canónica, no
   los bytes literales, así que algunas transformaciones sí se toleran; pero saber
   cuáles exige un análisis que no hemos hecho, y equivocarse invalida la firma sin
   vuelta atrás. Con el original guardado, la pregunta no llega a plantearse.

Se conserva además una huella criptográfica que permita detectar alteración. **No se
elige aquí el algoritmo** ni el mecanismo de almacenamiento.

### 13.2.bis Invariante: el periodo fiscal no se deduce de la fecha de emisión

> **INVARIANTE DE DOMINIO — requisito pendiente para el Tax Engine.**
>
> ```
> El periodo fiscal/contable NO debe inferirse únicamente
> de la fecha de emisión del documento.
> ```

No es una preferencia de diseño: sale de la norma. La revisión 2026 de la nota 9
establece que el **código de referencia** determina a qué periodo se imputa un ajuste
(§9.2) — `01`, `02`, `06` y `12` al periodo de la nota; `13` y `14` al del comprobante
original. Y el código `13` de la nota 10, «facturación mes vencido», exige indicar en la
fecha de referencia el periodo fiscal al que pertenece el ingreso, no la fecha real
(§9.3).

Son dos mecanismos independientes por los que periodo fiscal y fecha de emisión divergen.

Queda registrado como **requisito**, no como algoritmo. No se diseña aquí el cálculo, no
se define ningún `fiscal_period`, y no se crea nada en la base de datos. Lo que sí se
fija es que cualquier agregación por periodo que use la fecha de emisión como única
señal producirá cifras incorrectas — exactamente el error que este producto existe para
detectar.

### 13.3 Trazabilidad

Todo dato normalizado debe poder responder «¿de dónde salió?» siguiendo:

```
campo normalizado → SourceDocument → elemento XML
```

La ruta XML de cada campo es una propiedad **estable del tipo y la versión del
documento**, no de cada fila: `FE v4.4 / ResumenFactura / TotalComprobante` es la misma
para todas las facturas v4.4. Almacenar la ruta en cada fila sería redundancia masiva.
La trazabilidad se resuelve mejor con un mapa versionado por tipo de documento —lo que
este documento es— más el enlace de cada registro a los `SourceDocument` de los que
procede.

### 13.4 Los catálogos son datos, no enumeraciones

Los códigos de impuesto, tarifa, referencia, unidad de medida (101 valores), medio de
pago y descuento cambian entre versiones —v4.4 inhabilitó el código de tarifa `07` y
añadió `09`, `10` y `11`—. Se guardan como los códigos que son, con la versión del
comprobante que les da significado.

---

## 14. Comprobante emitido ≠ mensaje de Hacienda

Son documentos distintos y **no deben mezclarse**.

`MensajeHacienda` contiene: `Clave`, datos del emisor y receptor, `Mensaje`,
`EstadoMensaje`, `DetalleMensaje`, `MontoTotalImpuesto`, `TotalFactura`.

`MensajeReceptor` contiene además su propio `NumeroConsecutivoReceptor`,
`CondicionImpuesto`, `MontoTotalImpuestoAcreditar` y `MontoTotalDeGastoAplicable` —
es a su vez un documento numerado y firmado.

**El único vínculo con el comprobante es la `Clave`.** No hay anidamiento: son
artefactos separados, con su propia recepción y su propio ciclo de vida, y un
comprobante puede acumular varios mensajes en el tiempo.

Modelarlos como campos de estado dentro del comprobante perdería esa historia y
confundiría *lo que el emisor declaró* con *lo que la Administración respondió*. Esta
fase **no diseña integración con la API de Hacienda**.

---

## 15. Clasificación de la información

### A — Normalizar en el MVP
Identificación (`Clave`, consecutivo, tipo, versión, fecha), emisor y receptor básicos
(nombre, identificación, nombre comercial), líneas (CABYS, detalle, cantidad, unidad,
precios, totales), impuestos de línea (código, tarifa, monto), descuentos de línea,
moneda y tipo de cambio, totales principales del resumen, y referencias.

### B — Normalizar más adelante
Ubicación y contacto de las partes, exoneraciones, medios de pago, otros cargos, el
desglose `TotalDesgloseImpuesto`, los totales por naturaleza (servicio/mercancía ×
gravado/exento/exonerado/no sujeto), códigos comerciales, `IVACobradoFabrica` y el
impuesto asumido por el emisor de fábrica.

### C — Solo en el XML crudo, de momento
`DetalleSurtido` completo y sus impuestos específicos, `NumeroVINoSerie`,
`RegistroMedicamento`, `FormaFarmaceutica`, `Otros`/`OtroTexto`/`OtroContenido`,
`ProveedorSistemas`, `Registrofiscal8707`, y `ds:Signature`.

*(`ProveedorSistemas` figuraba como MVP en la tabla del inventario por errata; la
categoría correcta es ésta. Ver §15.1 y FISCAL_LOGICAL_MODEL §12.2.)*

**`raw-only` no significa descartado.** Ninguna información se pierde: el XML original
la conserva íntegra (§13.2). La clasificación decide qué se normaliza a estructura
relacional y cuándo, no qué se guarda. Todo lo de la categoría C sigue estando disponible
y es recuperable en cualquier momento reprocesando el original.

### Clasificación canónica — tras la reconciliación de E1

```
59  MVP normalizado
64  normalizar después
58  solo crudo inicialmente
───
181 total
```

> **Nota histórica.** E0 registró originalmente **67 · 57 · 57**. Durante el mapeo lógico
> de la fase E1 se detectó una **errata de clasificación** que afectaba a ocho nodos:
> siete campos marcados MVP cuyo contenedor estaba en categoría B —imposible normalizar
> un campo sin su contenedor—, y `ProveedorSistemas`, que la prosa de este documento
> situaba en categoría C mientras la tabla lo marcaba MVP.
>
> El total de 181 no cambia y **ningún campo se pierde**: la errata afectaba a la
> categoría asignada, no al inventario. Detalle campo por campo en
> [FISCAL_LOGICAL_MODEL.md](FISCAL_LOGICAL_MODEL.md) §12.3. Los commits anteriores no se
> alteran.

**Revalidado contra la revisión de 99 páginas.** Dos comprobaciones independientes:

1. **Extractor reejecutado** sobre los XSD re-descargados y reclasificación con los
   mismos criterios: mismos 180 nodos, mismo reparto que E0 —**67 · 57 · 57** en aquel
   momento—. *(Esos criterios resultaron tener un defecto, corregido después en la
   reconciliación de E1: la clasificación canónica es **59 · 64 · 58**. Lo que esta
   comprobación demuestra sigue siendo válido: la revisión 2026 no altera el inventario.)*
2. **Contraste con el PDF vigente**: se extrajeron todos los identificadores con forma
   de etiqueta XML de ambas revisiones y se compararon. Los únicos tokens nuevos son
   `Ajustes` y `Tratamiento` —palabras de prosa—, **ninguno es un elemento del esquema**.

El recuento se sostiene porque la revisión 2026 cambia descripciones, notas y catálogos
dentro de campos ya clasificados: `InformacionReferencia/Codigo` en A,
`Identificacion/Numero` en A, `TotalIVADevuelto` en B, `NumTelefono` en B,
`ProveedorSistemas` en C. **Ninguno cambia de categoría.**

### 15.1 La firma

`ds:Signature` `[1..5]` es parte inseparable del XML crudo y **no se normaliza** en el
MVP. Extraer material criptográfico al modelo relacional sin una necesidad funcional
demostrada añade superficie sin beneficio. Esta fase **no implementa validación XAdES**
ni afirma nada sobre cómo debe verificarse; solo conserva íntegro aquello sobre lo que
se verificará.

---

## 16. Alcance MVP propuesto — **propuesta, requiere aprobación**

**Dominio fiscal inicial** ([ADR-025](DECISIONS.md#adr-025), aceptada):

```
Factura Electrónica  +  Nota de Crédito  +  Nota de Débito
```

Razón, en una frase: **una factura no puede interpretarse correctamente sin considerar
los documentos que la ajustan.**

No se implementa todavía.

El razonamiento no sale del XSD, sale de lo que significan los documentos:

1. **Una factura sin sus notas miente sobre el importe.** Una nota de crédito modifica o
   anula una factura ya emitida. Un sistema que solo ingiera facturas mostrará totales
   que el contribuyente sabe que son falsos, y ese es exactamente el error que destruye
   la confianza en un asistente tributario.
2. **El coste marginal es casi nulo.** NC y ND son estructuralmente Factura Electrónica
   más `MontoExportacion` y `PartidaArancelaria`, y no les falta ningún campo. Soportar
   los tres es esencialmente el mismo trabajo.
3. **Obliga a acertar con las referencias desde el día uno.** NC y ND exigen
   `InformacionReferencia`. Diseñar primero solo la factura llevaría a un modelo sin
   relaciones documentales que habría que rehacer de inmediato.

Orden propuesto:

| Fase | Documentos | Motivo |
|---|---|---|
| **MVP** | Factura Electrónica, Nota de Crédito, Nota de Débito | Coherencia de saldos y relaciones documentales |
| Siguiente | Tiquete Electrónico | Solo dos campos menos que la factura |
| Después | Factura de Compra, Factura de Exportación | Casos con reglas propias |
| Más tarde | Recibo Electrónico de Pago | Estructura distinta (57 nodos) |
| Aparte | Mensaje Hacienda, Mensaje Receptor | Otro ciclo de vida (§14) |

---

## 17. Revalidación semántica frente a la revisión 2026

Cada área señalada como afectable, contrastada contra el XSD publicado —que **no
cambió**— para separar lo estructural de lo semántico.

| Área | Estructura en el XSD publicado | Efecto de la revisión 2026 | Veredicto |
|---|---|---|---|
| **`InformacionReferencia`** | `Codigo` es `CodigoReferenciaType`, 12 valores; `TipoDocIR` es `TipoDocReferenciaType`, 19 valores; `Numero` opcional | Nota 9: 12 → **17 códigos**, `12` ajustado. Nota 10: 18 → **20 códigos**. Nueva regla de efecto contable | **Estructura intacta, semántica ampliada.** Cardinalidad `[0..10]`, opcionalidad de `Numero` y relación muchos-a-muchos sin cambio. Pero el código pasa a determinar el **periodo contable** (§9.2): hallazgo nuevo, no una variación menor |
| **Identificaciones** | `IdentificacionType/Numero` = `xs:string maxLength=20`; `Tipo` = 6 valores enumerados | «Permite ingresar números y letras para personas jurídicas»; «La "Cédula de personas Jurídicas" debe contener 10 caracteres y sin guiones» | **Sin impacto estructural.** El campo **ya era `xs:string`**: admitir letras no requiere cambio de esquema. Confirma que la revisión es semántica. Refuerza no tratar la identificación como número |
| **Impuestos** | `CodigoImpuestoType` 10 valores; `CodigoTarifaIVAType` 11 valores; `ImpuestoType` sin cambios | Sin cambio reportado de estructura | **Se mantiene.** §10 sigue siendo válido |
| **Condiciones de venta** | `CondicionVenta` con **14 valores**: `01,02,03,04,05,06,07,08,10,12,13,14,15,99` | Sin cambio reportado | **Se mantiene.** Nótese que ya presenta huecos (`09`, `11`), igual patrón de códigos retirados |
| **Medios de pago** | `TipoMedioPago` con **8 valores**: `01`–`07`, `99`, dentro de `ResumenFactura/MedioPago[0..4]` | Sin cambio reportado | **Se mantiene.** La corrección de E0 —`MedioPago` no está en la raíz— sigue siendo válida |
| **Exoneraciones** | `ExoneracionType` colgando de cada `Impuesto` de línea, `[0..1]`, con `TipoExoneracionType` de 12 valores | Sin cambio reportado | **Se mantiene.** La exoneración sigue siendo atributo del impuesto de línea, no del documento |
| **`ProveedorSistemas`** | `xs:string maxLength=20`, **obligatorio** `[1..1]` en los 7 comprobantes emitibles | Sin cambio reportado de estructura | **Se mantiene** en categoría C. Ver H-7 |
| **Teléfono** | `NumTelefono` = `xs:integer`, `minInclusive=100` | «Deberá contener mínimo 8 dígitos y un máximo de 20, **excepto en aquellos casos que se posea un número telefónico especial, por ejemplo, el 911**» | **Sin impacto en el MVP** (categoría B). La excepción es de longitud, no de alfabeto: `911` es entero y ≥ 100, así que el XSD lo admite sin cambios. Confirma que la regla de 8 dígitos vivía en la nota, no en el esquema |
| **IVA Devuelto** | `TotalIVADevuelto`, `DecimalDineroType`, `[0..1]` | Se añade fórmula explícita para ventas mixtas | **Sin impacto estructural.** Es una regla de obtención del valor reportado (§10.1) |

**Conclusión.** Ninguna conclusión estructural de E0 cae. Lo que cambia son **valores de
catálogo y reglas de uso**, no la forma del documento — comprobado extrayendo todos los
identificadores con forma de etiqueta XML de ambas revisiones: **ningún elemento nuevo**.
Es exactamente el fenómeno que [ADR-026](DECISIONS.md#adr-026) modela.

Lo que sí es nuevo y de fondo: la regla de **efecto contable por código de referencia**
(§9.2). No altera el inventario, pero cambia cómo debe entenderse un ajuste.

**Corrección respecto a E0-R1.** En la revisión anterior anoté los códigos `16` y `17`
a partir de fuentes secundarias, como «referencia a comprobantes rechazados» y
«aplicación de pagos en REP». El documento oficial dice **«Sustituye comprobante
electrónico rechazado»** y **«Pago a comprobante electrónico»**. Las descripciones
secundarias eran aproximaciones inexactas; el catálogo de §9.1 está tomado de la fuente.

---

## 18. Huecos abiertos

**~~H-1~~ — CERRADO.** La v4.4 rige oficialmente desde el **1 de setiembre de 2025**.
La resolución original `MH-DGT-RES-0027-2024` fijaba el 1 de junio de 2025; una
modificación posterior amplió el plazo. Ver §1.1.

**~~H-2~~ — CERRADO, no bloqueante.** El `+06:00` de los Anexos es **un ejemplo de
formato RFC3339, no una regla de zona horaria de Costa Rica**. El documento está
especificando la sintaxis `[Z|(+|-)hh:mm]`, no prescribiendo un desplazamiento. La
conclusión de diseño de §7 no dependía de ello y se mantiene: **cuando el valor fuente
incluye desplazamiento, el instante es inequívoco**; cuando no lo incluye, no se infiere
ni el desplazamiento ni el instante absoluto —`issued_at_local` y `issued_at_raw`
preservan la evidencia de la fuente—. El desplazamiento local sigue siendo información
que se pierde al normalizar a UTC. La ingesta la gobierna
[ADR-039](DECISIONS.md#adr-039); H-2 **no se reabre**.

**~~H-8~~ — CERRADO.** El PDF de 99 páginas con la Bitácora al 22/04/2026 se obtuvo de
`hacienda.go.cr` (`sha256 6e093226…`, `Last-Modified 13-may-2026`) y es ahora la base
semántica de este documento. Todo lo que en E0-R1 estaba marcado «⚠ pendiente de
verificación oficial» ha sido verificado o corregido contra la fuente.

**I-1 — Incidencia técnica de recuperación (no es un hueco normativo).** La ruta de ATV
`…/esquemas/2024/v4.4/ANEXOS Y ESTRUCTURAS_V4.4.pdf` sigue sirviendo la revisión de
septiembre de 2025 (98 págs), mientras `hacienda.go.cr/docs/ANEXOS_Y_ESTRUCTURAS_V4.4.pdf`
sirve la vigente (99 págs). **Mismo nombre de archivo, distinto contenido.** Hacienda sí
publica la actualización; lo que falla es asumir que una única URL es canónica.

Regla operativa que se deriva: fijar la ubicación **y** contrastar la huella en cada
actualización de fuentes. El nombre del archivo no distingue las revisiones; el `sha256`
sí.

**H-3 — Catálogos externos sin incorporar.** `Codigodemoneda_V4.4.pdf`, la codificación
territorial (`Codificacionubicacion_V4.4`), CABYS y `Nota_9_Codigo_Forma_Farmaceutica.xlsx`
están identificados pero no inventariados. CABYS en particular es un catálogo grande con
su propia gobernanza.

**H-4 — Semántica condicional.** El XSD expresa cardinalidad, no condicionalidad. Reglas
del tipo «obligatorio cuando el código de impuesto es 03, 04, 05 o 06» viven en las notas
de los Anexos y aún no están inventariadas exhaustivamente.

**~~H-5~~ — CERRADO.** La revisión vigente **sí se identifica dentro del documento**:
declara «Bitácora de Ajustes al 22/04/2026» y «Rige a partir del 01 de setiembre del
2025». La revisión anterior no lo hacía, lo que justifica seguir registrando huella y
`Last-Modified` de cada archivo (§2.1) para poder fechar copias antiguas.

**~~H-6~~ — Algoritmo de huella y almacenamiento del XML.** Deliberadamente sin decidir **en
E0 y E1**; era una decisión física y estas fases eran de inventario y modelo lógico.
**CERRADO PARA EL MVP en el diseño de E2**: `raw_xml BYTEA` + `content_sha256 BYTEA`,
SHA-256 de los bytes originales exactos, almacenado en PostgreSQL. Ver
[FISCAL_PHYSICAL_MODEL.md](FISCAL_PHYSICAL_MODEL.md) §8.

**~~H-7~~ — CERRADO.** `ProveedorSistemas` queda **`raw-only` inicialmente**. Es metadata
técnica del sistema emisor: no interviene en ningún cálculo tributario, no es parte de la
transacción, y ninguna consulta del MVP lo necesita. Se conserva íntegro en el XML
original y puede normalizarse más adelante reprocesando, si aparece una necesidad
operativa o de auditoría. Ninguna fuente oficial exige lo contrario: el campo es
obligatorio para el emisor del comprobante, lo que no determina qué normalizamos
nosotros. Resuelto en la fase E1 (FISCAL_LOGICAL_MODEL §12.2).

---

## 19. `schema_version` frente a `spec_revision` — **propuesta**

Ver [ADR-026](DECISIONS.md#adr-026). Se resume aquí porque es la lección central de esta
revisión.

E0-R1 lo demostró con datos, no con conjeturas:

```
versión del esquema      4.4          sin cambio
XSD publicados           9 idénticos  byte a byte, Last-Modified 09-sep-2025
revisión del documento   22/04/2026   99 páginas, nueva Bitácora de Ajustes
efecto                   nuevos códigos de referencia, cédula alfanumérica,
                         excepción de teléfono, notas técnicas aclaradas
```

**Hacienda puede cambiar semántica y catálogos sin tocar el `4.4`.** Un comprobante
emitido en octubre de 2025 y otro en diciembre de 2026 declararán ambos `version="4.4"`
y estarán sujetos a reglas distintas.

De ahí la propuesta de registrar **dos ejes independientes** por documento ingerido:

| Eje | Qué es | De dónde sale |
|---|---|---|
| `schema_version` | **Versión estructural**, determinada mecánicamente por el tipo de documento, el namespace y el esquema aplicable | Determinable a partir del propio documento — el namespace del elemento raíz lleva tipo y versión (§4). `version="4.4"` vive en el **XSD**, no en la instancia |
| `spec_revision` | Revisión del documento técnico (*ruleset*) aplicable | **No está en el XML, y la fecha por sí sola no lo determina.** Ver §19.1 |

### 19.1 La fecha no basta para identificar el *ruleset*

Sería cómodo deducir la revisión de la `FechaEmision`. **No funciona**, y el propio
calendario lo explica: entre el 22 de abril y el 1 de noviembre de 2026 el uso de los
cambios es **anticipado y opcional**. Durante ese periodo conviven:

```
v4.4 + ruleset anterior     ─┐
                             ├── mismas fechas, reglas distintas
v4.4 + ruleset 2026         ─┘
```

Dos comprobantes emitidos el mismo día pueden estar sujetos a catálogos distintos, según
si su emisor ya adoptó los cambios. Una regla del tipo «si la fecha ≥ 01/11/2026
entonces ruleset 2026» clasificaría mal todo el periodo de transición.

La identificación de la revisión requerirá un mecanismo que pondere varias señales:

- **contenido efectivo del documento** — la presencia de un código `13`–`17` en nota 9 o
  `19`–`20` en nota 10 solo es posible bajo el ruleset 2026;
- **semántica presente** — qué reglas son consistentes con los valores observados;
- **compatibilidad de reglas** — qué ruleset explica el documento sin contradicción;
- **la fecha como señal, no como autoridad**.

**No se diseña aquí ese algoritmo.** Lo que sí se fija es que `spec_revision` es una
propiedad **inferida y registrada por documento**, con su evidencia, y no una constante
global ni una función de la fecha.

Consecuencias si no se hiciera:

- Un `CHECK` sobre los doce códigos de referencia actuales **rechazaría comprobantes
  válidos a partir del 1 de noviembre de 2026**.
- Un código `13` no podría interpretarse: solo tiene significado bajo la revisión que lo
  introdujo. Y su significado no es decorativo — determina el periodo contable (§9.2).
- Al reprocesar el histórico se aplicarían reglas de 2026 a documentos de 2025.
- Un comprobante v4.3 legítimo —admisible aún para notas de crédito y débito sobre
  comprobantes de su vigencia (§1.1.bis)— sería rechazado por un sistema que asuma v4.4.

Colocar `spec_revision` como propiedad del documento ingerido, y no como constante global
del sistema, es lo que permite que el histórico siga siendo interpretable cuando llegue
la siguiente revisión. **Queda como propuesta pendiente de aprobación.**

---

## 20. Inventario de campos — Factura Electrónica v4.4

Extraído programáticamente del XSD oficial. 181 filas.

| XML Path | Campo | Tipo XSD | Card. | Clasificación |
|---|---|---|---|---|
| `FE` | FacturaElectronica | `(inline)` | `1..1` | raw-only inicial |
| `FE/Clave` | Clave | `ClaveType` | `1..1` | **MVP normalizado** |
| `FE/ProveedorSistemas` | ProveedorSistemas | `(vacío)` | `1..1` | raw-only inicial |
| `FE/CodigoActividadEmisor` | CodigoActividadEmisor | `(vacío)` | `1..1` | **MVP normalizado** |
| `FE/CodigoActividadReceptor` | CodigoActividadReceptor | `(vacío)` | `0..1` | **MVP normalizado** |
| `FE/NumeroConsecutivo` | NumeroConsecutivo | `NumeroConsecutivoType` | `1..1` | **MVP normalizado** |
| `FE/FechaEmision` | FechaEmision | `dateTime` | `1..1` | **MVP normalizado** |
| `FE/Emisor` | Emisor | `EmisorType` | `1..1` | **MVP normalizado** |
| `FE/Emisor/Nombre` | Nombre | `(vacío)` | `1..1` | **MVP normalizado** |
| `FE/Emisor/Identificacion` | Identificacion | `IdentificacionType` | `1..1` | **MVP normalizado** |
| `FE/Emisor/Identificacion/Tipo` | Tipo | `(vacío)` | `1..1` | **MVP normalizado** |
| `FE/Emisor/Identificacion/Numero` | Numero | `(vacío)` | `1..1` | **MVP normalizado** |
| `FE/Emisor/Registrofiscal8707` | Registrofiscal8707 | `(vacío)` | `0..1` | raw-only inicial |
| `FE/Emisor/NombreComercial` | NombreComercial | `(vacío)` | `0..1` | **MVP normalizado** |
| `FE/Emisor/Ubicacion` | Ubicacion | `UbicacionType` | `1..1` | normalizar después |
| `FE/Emisor/Ubicacion/Provincia` | Provincia | `(vacío)` | `1..1` | normalizar después |
| `FE/Emisor/Ubicacion/Canton` | Canton | `(vacío)` | `1..1` | normalizar después |
| `FE/Emisor/Ubicacion/Distrito` | Distrito | `(vacío)` | `1..1` | normalizar después |
| `FE/Emisor/Ubicacion/Barrio` | Barrio | `(vacío)` | `0..1` | normalizar después |
| `FE/Emisor/Ubicacion/OtrasSenas` | OtrasSenas | `(vacío)` | `1..1` | normalizar después |
| `FE/Emisor/Telefono` | Telefono | `TelefonoType` | `0..1` | normalizar después |
| `FE/Emisor/Telefono/CodigoPais` | CodigoPais | `(vacío)` | `1..1` | normalizar después |
| `FE/Emisor/Telefono/NumTelefono` | NumTelefono | `(vacío)` | `1..1` | normalizar después |
| `FE/Emisor/CorreoElectronico` | CorreoElectronico | `(vacío)` | `1..4` | normalizar después |
| `FE/Receptor` | Receptor | `ReceptorType` | `1..1` | **MVP normalizado** |
| `FE/Receptor/Nombre` | Nombre | `(vacío)` | `1..1` | **MVP normalizado** |
| `FE/Receptor/Identificacion` | Identificacion | `IdentificacionType` | `1..1` | **MVP normalizado** |
| `FE/Receptor/Identificacion/Tipo` | Tipo | `(vacío)` | `1..1` | **MVP normalizado** |
| `FE/Receptor/Identificacion/Numero` | Numero | `(vacío)` | `1..1` | **MVP normalizado** |
| `FE/Receptor/NombreComercial` | NombreComercial | `(vacío)` | `0..1` | **MVP normalizado** |
| `FE/Receptor/Ubicacion` | Ubicacion | `UbicacionType` | `0..1` | normalizar después |
| `FE/Receptor/Ubicacion/Provincia` | Provincia | `(vacío)` | `1..1` | normalizar después |
| `FE/Receptor/Ubicacion/Canton` | Canton | `(vacío)` | `1..1` | normalizar después |
| `FE/Receptor/Ubicacion/Distrito` | Distrito | `(vacío)` | `1..1` | normalizar después |
| `FE/Receptor/Ubicacion/Barrio` | Barrio | `(vacío)` | `0..1` | normalizar después |
| `FE/Receptor/Ubicacion/OtrasSenas` | OtrasSenas | `(vacío)` | `1..1` | normalizar después |
| `FE/Receptor/OtrasSenasExtranjero` | OtrasSenasExtranjero | `(vacío)` | `0..1` | normalizar después |
| `FE/Receptor/Telefono` | Telefono | `TelefonoType` | `0..1` | normalizar después |
| `FE/Receptor/Telefono/CodigoPais` | CodigoPais | `(vacío)` | `1..1` | normalizar después |
| `FE/Receptor/Telefono/NumTelefono` | NumTelefono | `(vacío)` | `1..1` | normalizar después |
| `FE/Receptor/CorreoElectronico` | CorreoElectronico | `(vacío)` | `0..1` | normalizar después |
| `FE/CondicionVenta` | CondicionVenta | `(vacío)` | `1..1` | **MVP normalizado** |
| `FE/CondicionVentaOtros` | CondicionVentaOtros | `(vacío)` | `0..1` | raw-only inicial |
| `FE/PlazoCredito` | PlazoCredito | `(vacío)` | `0..1` | **MVP normalizado** |
| `FE/DetalleServicio` | DetalleServicio | `(inline)` | `0..1` | **MVP normalizado** |
| `FE/DetalleServicio/LineaDetalle` | LineaDetalle | `(inline)` | `1..1000` | **MVP normalizado** |
| `FE/DetalleServicio/LineaDetalle/NumeroLinea` | NumeroLinea | `(vacío)` | `1..1` | **MVP normalizado** |
| `FE/DetalleServicio/LineaDetalle/CodigoCABYS` | CodigoCABYS | `(vacío)` | `1..1` | **MVP normalizado** |
| `FE/DetalleServicio/LineaDetalle/CodigoComercial` | CodigoComercial | `CodigoType` | `0..5` | normalizar después |
| `FE/DetalleServicio/LineaDetalle/CodigoComercial/Tipo` | Tipo | `(vacío)` | `1..1` | normalizar después |
| `FE/DetalleServicio/LineaDetalle/CodigoComercial/Codigo` | Codigo | `(vacío)` | `1..1` | normalizar después |
| `FE/DetalleServicio/LineaDetalle/Cantidad` | Cantidad | `(vacío)` | `1..1` | **MVP normalizado** |
| `FE/DetalleServicio/LineaDetalle/UnidadMedida` | UnidadMedida | `UnidadMedidaType` | `1..1` | **MVP normalizado** |
| `FE/DetalleServicio/LineaDetalle/TipoTransaccion` | TipoTransaccion | `(vacío)` | `0..1` | normalizar después |
| `FE/DetalleServicio/LineaDetalle/UnidadMedidaComercial` | UnidadMedidaComercial | `(vacío)` | `0..1` | raw-only inicial |
| `FE/DetalleServicio/LineaDetalle/Detalle` | Detalle | `(vacío)` | `1..1` | **MVP normalizado** |
| `FE/DetalleServicio/LineaDetalle/NumeroVINoSerie` | NumeroVINoSerie | `(vacío)` | `0..1000` | raw-only inicial |
| `FE/DetalleServicio/LineaDetalle/RegistroMedicamento` | RegistroMedicamento | `(vacío)` | `0..1` | raw-only inicial |
| `FE/DetalleServicio/LineaDetalle/FormaFarmaceutica` | FormaFarmaceutica | `(vacío)` | `0..1` | raw-only inicial |
| `FE/DetalleServicio/LineaDetalle/DetalleSurtido` | DetalleSurtido | `(inline)` | `0..1` | raw-only inicial |
| `FE/DetalleServicio/LineaDetalle/DetalleSurtido/LineaDetalleSurtido` | LineaDetalleSurtido | `(inline)` | `1..20` | raw-only inicial |
| `FE/DetalleServicio/LineaDetalle/DetalleSurtido/LineaDetalleSurtido/CodigoCABYSSurtido` | CodigoCABYSSurtido | `(vacío)` | `1..1` | raw-only inicial |
| `FE/DetalleServicio/LineaDetalle/DetalleSurtido/LineaDetalleSurtido/CodigoComercialSurtido` | CodigoComercialSurtido | `(inline)` | `0..5` | raw-only inicial |
| `FE/DetalleServicio/LineaDetalle/DetalleSurtido/LineaDetalleSurtido/CodigoComercialSurtido/TipoSurtido` | TipoSurtido | `(vacío)` | `1..1` | raw-only inicial |
| `FE/DetalleServicio/LineaDetalle/DetalleSurtido/LineaDetalleSurtido/CodigoComercialSurtido/CodigoSurtido` | CodigoSurtido | `(vacío)` | `1..1` | raw-only inicial |
| `FE/DetalleServicio/LineaDetalle/DetalleSurtido/LineaDetalleSurtido/CantidadSurtido` | CantidadSurtido | `(vacío)` | `1..1` | raw-only inicial |
| `FE/DetalleServicio/LineaDetalle/DetalleSurtido/LineaDetalleSurtido/UnidadMedidaSurtido` | UnidadMedidaSurtido | `(vacío)` | `1..1` | raw-only inicial |
| `FE/DetalleServicio/LineaDetalle/DetalleSurtido/LineaDetalleSurtido/UnidadMedidaComercialSurtido` | UnidadMedidaComercialSurtido | `(vacío)` | `0..1` | raw-only inicial |
| `FE/DetalleServicio/LineaDetalle/DetalleSurtido/LineaDetalleSurtido/DetalleSurtido` | DetalleSurtido | `(vacío)` | `1..1` | raw-only inicial |
| `FE/DetalleServicio/LineaDetalle/DetalleSurtido/LineaDetalleSurtido/PrecioUnitarioSurtido` | PrecioUnitarioSurtido | `(vacío)` | `1..1` | raw-only inicial |
| `FE/DetalleServicio/LineaDetalle/DetalleSurtido/LineaDetalleSurtido/MontoTotalSurtido` | MontoTotalSurtido | `DecimalDineroType` | `1..1` | raw-only inicial |
| `FE/DetalleServicio/LineaDetalle/DetalleSurtido/LineaDetalleSurtido/DescuentoSurtido` | DescuentoSurtido | `(inline)` | `0..5` | raw-only inicial |
| `FE/DetalleServicio/LineaDetalle/DetalleSurtido/LineaDetalleSurtido/DescuentoSurtido/MontoDescuentoSurtido` | MontoDescuentoSurtido | `DecimalDineroType` | `1..1` | raw-only inicial |
| `FE/DetalleServicio/LineaDetalle/DetalleSurtido/LineaDetalleSurtido/DescuentoSurtido/CodigoDescuentoSurtido` | CodigoDescuentoSurtido | `CodigoDescuentoType` | `1..1` | raw-only inicial |
| `FE/DetalleServicio/LineaDetalle/DetalleSurtido/LineaDetalleSurtido/DescuentoSurtido/DescuentoSurtidoOtros` | DescuentoSurtidoOtros | `(vacío)` | `0..1` | raw-only inicial |
| `FE/DetalleServicio/LineaDetalle/DetalleSurtido/LineaDetalleSurtido/SubTotalSurtido` | SubTotalSurtido | `DecimalDineroType` | `1..1` | raw-only inicial |
| `FE/DetalleServicio/LineaDetalle/DetalleSurtido/LineaDetalleSurtido/IVACobradoFabricaSurtido` | IVACobradoFabricaSurtido | `(vacío)` | `0..1` | raw-only inicial |
| `FE/DetalleServicio/LineaDetalle/DetalleSurtido/LineaDetalleSurtido/BaseImponibleSurtido` | BaseImponibleSurtido | `DecimalDineroType` | `1..1` | raw-only inicial |
| `FE/DetalleServicio/LineaDetalle/DetalleSurtido/LineaDetalleSurtido/ImpuestoSurtido` | ImpuestoSurtido | `(inline)` | `1..1000` | raw-only inicial |
| `FE/DetalleServicio/LineaDetalle/DetalleSurtido/LineaDetalleSurtido/ImpuestoSurtido/CodigoImpuestoSurtido` | CodigoImpuestoSurtido | `CodigoImpuestoType` | `1..1` | raw-only inicial |
| `FE/DetalleServicio/LineaDetalle/DetalleSurtido/LineaDetalleSurtido/ImpuestoSurtido/CodigoImpuestoOTROSurtido` | CodigoImpuestoOTROSurtido | `(vacío)` | `0..1` | raw-only inicial |
| `FE/DetalleServicio/LineaDetalle/DetalleSurtido/LineaDetalleSurtido/ImpuestoSurtido/CodigoTarifaIVASurtido` | CodigoTarifaIVASurtido | `CodigoTarifaIVAType` | `0..1` | raw-only inicial |
| `FE/DetalleServicio/LineaDetalle/DetalleSurtido/LineaDetalleSurtido/ImpuestoSurtido/TarifaSurtido` | TarifaSurtido | `(vacío)` | `0..1` | raw-only inicial |
| `FE/DetalleServicio/LineaDetalle/DetalleSurtido/LineaDetalleSurtido/ImpuestoSurtido/DatosImpuestoEspecificoSurtido` | DatosImpuestoEspecificoSurtido | `(inline)` | `0..1` | raw-only inicial |
| `FE/DetalleServicio/LineaDetalle/DetalleSurtido/LineaDetalleSurtido/ImpuestoSurtido/DatosImpuestoEspecificoSurtido/CantidadUnidadMedidaSurtido` | CantidadUnidadMedidaSurtido | `(vacío)` | `1..1` | raw-only inicial |
| `FE/DetalleServicio/LineaDetalle/DetalleSurtido/LineaDetalleSurtido/ImpuestoSurtido/DatosImpuestoEspecificoSurtido/PorcentajeSurtido` | PorcentajeSurtido | `(vacío)` | `0..1` | raw-only inicial |
| `FE/DetalleServicio/LineaDetalle/DetalleSurtido/LineaDetalleSurtido/ImpuestoSurtido/DatosImpuestoEspecificoSurtido/ProporcionSurtido` | ProporcionSurtido | `(vacío)` | `0..1` | raw-only inicial |
| `FE/DetalleServicio/LineaDetalle/DetalleSurtido/LineaDetalleSurtido/ImpuestoSurtido/DatosImpuestoEspecificoSurtido/VolumenUnidadConsumoSurtido` | VolumenUnidadConsumoSurtido | `(vacío)` | `0..1` | raw-only inicial |
| `FE/DetalleServicio/LineaDetalle/DetalleSurtido/LineaDetalleSurtido/ImpuestoSurtido/DatosImpuestoEspecificoSurtido/ImpuestoUnidadSurtido` | ImpuestoUnidadSurtido | `DecimalDineroType` | `1..1` | raw-only inicial |
| `FE/DetalleServicio/LineaDetalle/DetalleSurtido/LineaDetalleSurtido/ImpuestoSurtido/MontoImpuestoSurtido` | MontoImpuestoSurtido | `DecimalDineroType` | `1..1` | raw-only inicial |
| `FE/DetalleServicio/LineaDetalle/PrecioUnitario` | PrecioUnitario | `DecimalDineroType` | `1..1` | **MVP normalizado** |
| `FE/DetalleServicio/LineaDetalle/MontoTotal` | MontoTotal | `DecimalDineroType` | `1..1` | **MVP normalizado** |
| `FE/DetalleServicio/LineaDetalle/Descuento` | Descuento | `DescuentoType` | `0..5` | **MVP normalizado** |
| `FE/DetalleServicio/LineaDetalle/Descuento/MontoDescuento` | MontoDescuento | `DecimalDineroType` | `1..1` | **MVP normalizado** |
| `FE/DetalleServicio/LineaDetalle/Descuento/CodigoDescuento` | CodigoDescuento | `CodigoDescuentoType` | `1..1` | **MVP normalizado** |
| `FE/DetalleServicio/LineaDetalle/Descuento/CodigoDescuentoOTRO` | CodigoDescuentoOTRO | `(vacío)` | `0..1` | raw-only inicial |
| `FE/DetalleServicio/LineaDetalle/Descuento/NaturalezaDescuento` | NaturalezaDescuento | `(vacío)` | `0..1` | raw-only inicial |
| `FE/DetalleServicio/LineaDetalle/SubTotal` | SubTotal | `DecimalDineroType` | `1..1` | **MVP normalizado** |
| `FE/DetalleServicio/LineaDetalle/IVACobradoFabrica` | IVACobradoFabrica | `(vacío)` | `0..1` | normalizar después |
| `FE/DetalleServicio/LineaDetalle/BaseImponible` | BaseImponible | `DecimalDineroType` | `1..1` | **MVP normalizado** |
| `FE/DetalleServicio/LineaDetalle/Impuesto` | Impuesto | `ImpuestoType` | `1..1000` | **MVP normalizado** |
| `FE/DetalleServicio/LineaDetalle/Impuesto/Codigo` | Codigo | `CodigoImpuestoType` | `1..1` | **MVP normalizado** |
| `FE/DetalleServicio/LineaDetalle/Impuesto/CodigoImpuestoOTRO` | CodigoImpuestoOTRO | `(vacío)` | `0..1` | raw-only inicial |
| `FE/DetalleServicio/LineaDetalle/Impuesto/CodigoTarifaIVA` | CodigoTarifaIVA | `CodigoTarifaIVAType` | `0..1` | **MVP normalizado** |
| `FE/DetalleServicio/LineaDetalle/Impuesto/Tarifa` | Tarifa | `(vacío)` | `0..1` | **MVP normalizado** |
| `FE/DetalleServicio/LineaDetalle/Impuesto/FactorCalculoIVA` | FactorCalculoIVA | `(vacío)` | `0..1` | normalizar después |
| `FE/DetalleServicio/LineaDetalle/Impuesto/DatosImpuestoEspecifico` | DatosImpuestoEspecifico | `(inline)` | `0..1` | raw-only inicial |
| `FE/DetalleServicio/LineaDetalle/Impuesto/DatosImpuestoEspecifico/CantidadUnidadMedida` | CantidadUnidadMedida | `(vacío)` | `1..1` | raw-only inicial |
| `FE/DetalleServicio/LineaDetalle/Impuesto/DatosImpuestoEspecifico/Porcentaje` | Porcentaje | `(vacío)` | `0..1` | raw-only inicial |
| `FE/DetalleServicio/LineaDetalle/Impuesto/DatosImpuestoEspecifico/Proporcion` | Proporcion | `(vacío)` | `0..1` | raw-only inicial |
| `FE/DetalleServicio/LineaDetalle/Impuesto/DatosImpuestoEspecifico/VolumenUnidadConsumo` | VolumenUnidadConsumo | `(vacío)` | `0..1` | raw-only inicial |
| `FE/DetalleServicio/LineaDetalle/Impuesto/DatosImpuestoEspecifico/ImpuestoUnidad` | ImpuestoUnidad | `DecimalDineroType` | `1..1` | raw-only inicial |
| `FE/DetalleServicio/LineaDetalle/Impuesto/Monto` | Monto | `DecimalDineroType` | `1..1` | **MVP normalizado** |
| `FE/DetalleServicio/LineaDetalle/Impuesto/Exoneracion` | Exoneracion | `ExoneracionType` | `0..1` | normalizar después |
| `FE/DetalleServicio/LineaDetalle/Impuesto/Exoneracion/TipoDocumentoEX1` | TipoDocumentoEX1 | `TipoExoneracionType` | `1..1` | normalizar después |
| `FE/DetalleServicio/LineaDetalle/Impuesto/Exoneracion/TipoDocumentoOTRO` | TipoDocumentoOTRO | `(vacío)` | `0..1` | raw-only inicial |
| `FE/DetalleServicio/LineaDetalle/Impuesto/Exoneracion/NumeroDocumento` | NumeroDocumento | `(vacío)` | `1..1` | normalizar después |
| `FE/DetalleServicio/LineaDetalle/Impuesto/Exoneracion/Articulo` | Articulo | `(vacío)` | `0..1` | normalizar después |
| `FE/DetalleServicio/LineaDetalle/Impuesto/Exoneracion/Inciso` | Inciso | `(vacío)` | `0..1` | normalizar después |
| `FE/DetalleServicio/LineaDetalle/Impuesto/Exoneracion/NombreInstitucion` | NombreInstitucion | `(vacío)` | `1..1` | normalizar después |
| `FE/DetalleServicio/LineaDetalle/Impuesto/Exoneracion/NombreInstitucionOtros` | NombreInstitucionOtros | `(vacío)` | `0..1` | raw-only inicial |
| `FE/DetalleServicio/LineaDetalle/Impuesto/Exoneracion/FechaEmisionEX` | FechaEmisionEX | `dateTime` | `1..1` | normalizar después |
| `FE/DetalleServicio/LineaDetalle/Impuesto/Exoneracion/TarifaExonerada` | TarifaExonerada | `(vacío)` | `1..1` | normalizar después |
| `FE/DetalleServicio/LineaDetalle/Impuesto/Exoneracion/MontoExoneracion` | MontoExoneracion | `DecimalDineroType` | `1..1` | normalizar después |
| `FE/DetalleServicio/LineaDetalle/ImpuestoAsumidoEmisorFabrica` | ImpuestoAsumidoEmisorFabrica | `DecimalDineroType` | `1..1` | normalizar después |
| `FE/DetalleServicio/LineaDetalle/ImpuestoNeto` | ImpuestoNeto | `DecimalDineroType` | `1..1` | **MVP normalizado** |
| `FE/DetalleServicio/LineaDetalle/MontoTotalLinea` | MontoTotalLinea | `DecimalDineroType` | `1..1` | **MVP normalizado** |
| `FE/OtrosCargos` | OtrosCargos | `OtrosCargosType` | `0..15` | normalizar después |
| `FE/OtrosCargos/TipoDocumentoOC` | TipoDocumentoOC | `(vacío)` | `1..1` | normalizar después |
| `FE/OtrosCargos/TipoDocumentoOTROS` | TipoDocumentoOTROS | `(vacío)` | `0..1` | raw-only inicial |
| `FE/OtrosCargos/IdentificacionTercero` | IdentificacionTercero | `IdentificacionType` | `0..1` | normalizar después |
| `FE/OtrosCargos/IdentificacionTercero/Tipo` | Tipo | `(vacío)` | `1..1` | normalizar después |
| `FE/OtrosCargos/IdentificacionTercero/Numero` | Numero | `(vacío)` | `1..1` | normalizar después |
| `FE/OtrosCargos/NombreTercero` | NombreTercero | `(vacío)` | `0..1` | normalizar después |
| `FE/OtrosCargos/Detalle` | Detalle | `(vacío)` | `1..1` | normalizar después |
| `FE/OtrosCargos/PorcentajeOC` | PorcentajeOC | `(vacío)` | `0..1` | normalizar después |
| `FE/OtrosCargos/MontoCargo` | MontoCargo | `DecimalDineroType` | `1..1` | normalizar después |
| `FE/ResumenFactura` | ResumenFactura | `(inline)` | `1..1` | **MVP normalizado** |
| `FE/ResumenFactura/CodigoTipoMoneda` | CodigoTipoMoneda | `CodigoMonedaType` | `1..1` | **MVP normalizado** |
| `FE/ResumenFactura/CodigoTipoMoneda/CodigoMoneda` | CodigoMoneda | `(vacío)` | `1..1` | **MVP normalizado** |
| `FE/ResumenFactura/CodigoTipoMoneda/TipoCambio` | TipoCambio | `DecimalDineroType` | `1..1` | **MVP normalizado** |
| `FE/ResumenFactura/TotalServGravados` | TotalServGravados | `DecimalDineroType` | `0..1` | normalizar después |
| `FE/ResumenFactura/TotalServExentos` | TotalServExentos | `DecimalDineroType` | `0..1` | normalizar después |
| `FE/ResumenFactura/TotalServExonerado` | TotalServExonerado | `DecimalDineroType` | `0..1` | normalizar después |
| `FE/ResumenFactura/TotalServNoSujeto` | TotalServNoSujeto | `DecimalDineroType` | `0..1` | normalizar después |
| `FE/ResumenFactura/TotalMercanciasGravadas` | TotalMercanciasGravadas | `DecimalDineroType` | `0..1` | normalizar después |
| `FE/ResumenFactura/TotalMercanciasExentas` | TotalMercanciasExentas | `DecimalDineroType` | `0..1` | normalizar después |
| `FE/ResumenFactura/TotalMercExonerada` | TotalMercExonerada | `DecimalDineroType` | `0..1` | normalizar después |
| `FE/ResumenFactura/TotalMercNoSujeta` | TotalMercNoSujeta | `DecimalDineroType` | `0..1` | normalizar después |
| `FE/ResumenFactura/TotalGravado` | TotalGravado | `DecimalDineroType` | `0..1` | **MVP normalizado** |
| `FE/ResumenFactura/TotalExento` | TotalExento | `DecimalDineroType` | `0..1` | **MVP normalizado** |
| `FE/ResumenFactura/TotalExonerado` | TotalExonerado | `DecimalDineroType` | `0..1` | **MVP normalizado** |
| `FE/ResumenFactura/TotalNoSujeto` | TotalNoSujeto | `DecimalDineroType` | `0..1` | **MVP normalizado** |
| `FE/ResumenFactura/TotalVenta` | TotalVenta | `DecimalDineroType` | `1..1` | **MVP normalizado** |
| `FE/ResumenFactura/TotalDescuentos` | TotalDescuentos | `DecimalDineroType` | `0..1` | **MVP normalizado** |
| `FE/ResumenFactura/TotalVentaNeta` | TotalVentaNeta | `DecimalDineroType` | `1..1` | **MVP normalizado** |
| `FE/ResumenFactura/TotalDesgloseImpuesto` | TotalDesgloseImpuesto | `(inline)` | `0..1000` | normalizar después |
| `FE/ResumenFactura/TotalDesgloseImpuesto/Codigo` | Codigo | `CodigoImpuestoType` | `1..1` | normalizar después |
| `FE/ResumenFactura/TotalDesgloseImpuesto/CodigoTarifaIVA` | CodigoTarifaIVA | `CodigoTarifaIVAType` | `0..1` | normalizar después |
| `FE/ResumenFactura/TotalDesgloseImpuesto/TotalMontoImpuesto` | TotalMontoImpuesto | `DecimalDineroType` | `1..1` | normalizar después |
| `FE/ResumenFactura/TotalImpuesto` | TotalImpuesto | `DecimalDineroType` | `0..1` | **MVP normalizado** |
| `FE/ResumenFactura/TotalImpAsumEmisorFabrica` | TotalImpAsumEmisorFabrica | `DecimalDineroType` | `0..1` | normalizar después |
| `FE/ResumenFactura/TotalIVADevuelto` | TotalIVADevuelto | `DecimalDineroType` | `0..1` | normalizar después |
| `FE/ResumenFactura/TotalOtrosCargos` | TotalOtrosCargos | `DecimalDineroType` | `0..1` | normalizar después |
| `FE/ResumenFactura/MedioPago` | MedioPago | `(inline)` | `0..4` | normalizar después |
| `FE/ResumenFactura/MedioPago/TipoMedioPago` | TipoMedioPago | `(vacío)` | `0..1` | normalizar después |
| `FE/ResumenFactura/MedioPago/MedioPagoOtros` | MedioPagoOtros | `(vacío)` | `0..1` | raw-only inicial |
| `FE/ResumenFactura/MedioPago/TotalMedioPago` | TotalMedioPago | `DecimalDineroType` | `0..1` | normalizar después |
| `FE/ResumenFactura/TotalComprobante` | TotalComprobante | `DecimalDineroType` | `1..1` | **MVP normalizado** |
| `FE/InformacionReferencia` | InformacionReferencia | `(inline)` | `0..10` | **MVP normalizado** |
| `FE/InformacionReferencia/TipoDocIR` | TipoDocIR | `TipoDocReferenciaType` | `1..1` | **MVP normalizado** |
| `FE/InformacionReferencia/TipoDocRefOTRO` | TipoDocRefOTRO | `(vacío)` | `0..1` | raw-only inicial |
| `FE/InformacionReferencia/Numero` | Numero | `(vacío)` | `0..1` | **MVP normalizado** |
| `FE/InformacionReferencia/FechaEmisionIR` | FechaEmisionIR | `dateTime` | `1..1` | **MVP normalizado** |
| `FE/InformacionReferencia/Codigo` | Codigo | `CodigoReferenciaType` | `0..1` | **MVP normalizado** |
| `FE/InformacionReferencia/CodigoReferenciaOTRO` | CodigoReferenciaOTRO | `(vacío)` | `0..1` | raw-only inicial |
| `FE/InformacionReferencia/Razon` | Razon | `(vacío)` | `0..1` | **MVP normalizado** |
| `FE/Otros` | Otros | `(inline)` | `0..1` | raw-only inicial |
| `FE/Otros/OtroTexto` | OtroTexto | `(inline)` | `0..unbounded` | raw-only inicial |
| `FE/Otros/OtroContenido` | OtroContenido | `(inline)` | `0..unbounded` | raw-only inicial |
| `FE/ds:Signature` | ds:Signature | `xmldsig` | `1..5` | raw-only inicial |

