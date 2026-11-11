# C4B3-01 (CRITICAL) — Durabilidad de la evidencia primaria vs. ACK del webhook

> **Estado:** ANÁLISIS DE REMEDIACIÓN — primer entregable post-auditoría Codex. **Diseño,
> no implementación.** PR #1 en DRAFT. **No se modifica ADR-047 ni ADR-050.** Sin código,
> migraciones ni despliegue. Decisión solicitada al orquestador al final (§6).
>
> `[VERIFICADO]` doc oficial/repo · `[OBSERVADO]` medido en C4-B0 · `[PROPUESTO]` requiere ratificación.

## 1. El hallazgo CRITICAL

El diseño de dos fases (A3) devuelve el **ACK (2xx) en la fase 1** confirmando la recepción de
un **evento** cuya **evidencia primaria (RAW RFC822)** todavía **depende de Resend** (se
descarga después, en la fase 2). Conservar el `raw_webhook` (~800 B de metadata firmada) **no
es** conservar el documento, y **depender de una retención observada de ~17 días no es una
garantía**. Por tanto: **el ACK del webhook no debe presentarse como garantía de preservación
del documento.**

## 2. Hechos verificados que condicionan las alternativas

| Hecho | Valor | Fuente |
|---|---|---|
| Timeout del webhook (responder 2xx) | **15 s** | Svix `[VERIFICADO]` |
| Resend inbound: el RAW **no** viaja en el webhook | fetch de 2 pasos (API → `download_url` CloudFront, válido 1 h) | Resend `[VERIFICADO]` |
| Resend: retención del email recibido | ≥17 días, **sin garantía contractual localizada** | C4-B0 `[OBSERVADO]` |
| Resend: límite de **envío** | 40 MB; **inbound sin ceiling documentado** | Resend `[VERIFICADO]` |
| Mailgun inbound: tamaño máx | **25 MB**; con URL `…/mime` el POST incluye **`body-mime` (RAW in-band)** | Mailgun `[VERIFICADO]` |
| AWS SES receiving → **S3** (bucket propio) | escribe el `.eml` original durable hasta **40 MB** (no ajustable por encima); vía SNS solo 150 KB | AWS `[VERIFICADO]` |

**Hallazgo rector:** el **techo inbound real es dependiente del proveedor (~25–40 MB)**, por
debajo de la política Tribuu de 64 MiB. La cifra de 64 MiB es defensiva, pero **ningún
proveedor concreto acepta inbound de 64 MiB**; el máximo operativo real es ~40 MB (Resend-send
/ SES) o 25 MB (Mailgun). Esto hace la captura pre-ACK más plausible de lo estimado en A3 (el
volumen a mover es menor), aunque **40 MB en 15 s sigue siendo ajustado**.

## 3. Alternativas

### Alternativa A — Evidencia íntegra antes del ACK
Dentro de los 15 s: verificar Svix → resolver tenant → fetch del RAW (streaming, tope) → hash →
INSERT `evidence_blob`+`email`+`event(state=captured)` → COMMIT → 2xx. **2xx ⇒ original durable
en nuestro control.**
- **Archivos pequeños** (XML fiscal, <1–2 MB): holgadamente viable; es el caso dominante.
- **Cola grande** (hasta ~40 MB): descargar 40 MB en <15 s exige ≳22 Mbit/s sostenidos **sin
  margen** para latencia de API, hash e insert → **no fiable**. Si agota los 15 s → Svix
  reintenta → trabajo pesado repetido → **riesgo de que Resend auto-deshabilite el endpoint**.
  Contradice la guía oficial de Svix ("encolar y responder pronto").
- **Comportamiento con grandes:** o bien un **tope síncrono bajo** (p. ej. ≤8–16 MB) y los
  mayores no entran, o bien timeouts/reintentos. **A pura no honra a la vez "evidencia íntegra
  antes del ACK" y "aceptar hasta ~40 MB".**

### Alternativa B — Dos fases con contrato de aceptación diferenciado
Fase 1 persiste el evento y ACK; fase 2 asíncrona descarga el RAW. **Viable sólo si se
redefine explícitamente el contrato:** el 2xx significa **"evento recibido y encolado para
captura durable"**, NO "documento preservado". Requiere: estado observable separado
("Recibido · captura en curso" → "Preservado"), reintentos acotados dentro de la retención,
escalación/alerta, y responsabilidad ante pérdida declarada. **Escala a cualquier tamaño y
respeta el contrato de 15 s**, pero **mantiene una ventana de pérdida** acotada por la
retención externa — justo lo que el CRITICAL señala como insuficiente si se presenta como
garantía.

### Alternativa C1 — Cambiar a un proveedor con RAW in-band (Mailgun)
Mailgun entrega el **RAW completo en el POST** (`body-mime`) hasta **25 MB**. Permite persistir
el original **antes del ACK sin fetch externo** → sin dependencia de `download_url`/retención
para lo que llegue. **Pero:** un POST de hasta 25 MB debe recibirse y persistirse dentro del
timeout (mismo problema de cuerpo grande, por eso Resend eligió el modelo de fetch); **techo de
25 MB** (< 40 MB y < 64 MiB); **cambio de proveedor** (Mailgun es el fallback validado,
ADR-047). Preservación más fuerte que B para lo que entra, con ceiling menor.

### Alternativa C2 — Recepción que escribe el original en almacenamiento propio (AWS SES → S3)
SES recibe y, por *receipt rule*, **escribe el `.eml` original en un bucket S3 nuestro** (hasta
40 MB) **antes** de notificar (SNS/Lambda). **La copia durable del original queda en nuestro
control sin depender de una ventana de retención externa** → **resuelve C4B3-01 de raíz.**
- **Costos/complejidad:** infra AWS (SES receiving, S3, SNS/Lambda, verificación de dominio y
  MX), **credenciales nuevas** (hoy vetadas por postura ADR-050), **cambio de proveedor**
  (ADR-047 = Resend MVP), más superficie para el MVP.
- **Techo 40 MB** (no ajustable por encima); vía SNS 150 KB (hay que usar la acción S3 para el
  cuerpo grande). Es la opción de **preservación más fuerte** y **provider-independiente de
  retención**, pero la **más pesada** para el MVP.

### Alternativa derivada — Híbrido A(≤umbral) + B-honesto(cola grande)
Captura síncrona durable para lo que entra en un **sub-presupuesto estricto** (p. ej. ~10 s,
tamaño ≤ umbral a calibrar por benchmark C4B3-08): para esos, **2xx ⇒ preservado**
(`state=captured`). Para la cola grande o fetch lento, **fallback a B-honesto**: 2xx =
"recibido, captura en curso", estado "Preservado" sólo tras fase 2, reintentos acotados +
escalación. **El caso dominante (XML fiscal/PDF pequeños) obtiene garantía real pre-ACK; la
minoría grande queda explícitamente contratada como "en curso"** — nunca un "preservado" falso.

## 4. Matriz comparativa

| Dimensión | A (pre-ACK full) | B (dos fases honesto) | C1 (Mailgun in-band) | C2 (SES→S3) | **Híbrido A+B** |
|---|---|---|---|---|---|
| 2xx ⇒ original durable | **Sí** (si entra) | No (recibido≠preservado) | **Sí** (≤25 MB) | **Sí** (en S3 propio) | **Sí** para ≤umbral; No (contratado) para el resto |
| Dependencia de retención externa | No | **Sí** (riesgo CRITICAL) | No | **No** | Solo para la cola grande |
| Escala de tamaño | baja (tope seguro ~8–16 MB) | alta | 25 MB | 40 MB | alta (umbral + fallback) |
| Cumple 15 s | solo pequeños | **Sí** | riesgo con grandes | **Sí** (async tras S3) | **Sí** |
| Complejidad MVP | media | baja | media (cambio proveedor) | **alta** | media-alta (dos caminos) |
| Credenciales/infra nueva | no | no | adaptador Mailgun | **sí (AWS)** | no |
| Cambio de proveedor / ADR-047 | no | no | **sí** | **sí** | no |
| Impacto UX / contrato | mínimo | **alto** (redefinir contrato) | mínimo | mínimo | medio (contrato solo para la cola) |
| Responsabilidad ante pérdida | nula (si entra) | explícita, acotada | nula (≤25 MB) | **nula** | explícita solo para la cola |
| Resuelve C4B3-01 | parcial (por tamaño) | solo con contrato honesto | sí (≤25 MB) | **sí (de raíz)** | **sí** (real para el grueso; honesto para la cola) |

## 5. Recomendación fundamentada `[PROPUESTO]`

**Para el MVP: Híbrido A+B** — captura síncrona durable **antes del ACK** para todo lo que
entre en un sub-presupuesto de ~10 s (incluye **todo el XML fiscal** y la mayoría de PDFs), de
modo que **el 2xx signifique "preservado"** para el caso dominante; y **fallback a B-honesto**
(contrato de recepción diferenciado, estado "Preservado" separado, reintentos acotados +
escalación) **sólo** para la cola grande/lenta. Esto resuelve C4B3-01 sin tope de tamaño
restrictivo y sin falsa garantía.

**Dirección estratégica (post-MVP o si el negocio exige 0 dependencia de retención):** **C2
(SES→S3)**, que coloca la copia durable del original en almacenamiento propio antes de
procesar, eliminando de raíz la dependencia de la ventana externa. Es la más fuerte pero la más
pesada; implicaría revisar ADR-047 (proveedor) y la postura de credenciales de ADR-050.

**No recomendado como solución única:** B puro (el CRITICAL lo rechaza si se presenta como
garantía) ni A puro (no escala al techo real de ~40 MB en 15 s).

### Riesgos residuales de la recomendación (Híbrido)
- La **cola grande** conserva la ventana de pérdida acotada por retención — pero es minoría,
  **explícitamente contratada** y con estado veraz; nunca "preservado" en falso. (R12 pasa de
  "silencioso" a "contratado".)
- **Dos caminos de código** (síncrono/asíncrono) → más complejidad y más tests (negativos).
- El **umbral** depende de un **benchmark real** (C4B3-08): latencia de fetch Resend + ancho de
  banda CloudFront + hash + INSERT BYTEA, bajo concurrencia. Hasta medir, el umbral es
  provisional.
- La **política de 64 MiB** excede el techo real del proveedor (~40 MB); conviene alinearla
  (decisión aparte, no se toca ADR-050 aquí).

## 6. Decisión solicitada al orquestador

1. **Elegir alternativa** para C4B3-01: A · B(-honesto) · C1(Mailgun) · C2(SES→S3) · **Híbrido
   A+B (recomendado)**.
2. Si B o Híbrido: **aprobar el contrato de recepción redefinido** (ACK = "recibido/encolado",
   estado "Preservado" separado; el ACK no es garantía de preservación).
3. **Proveedor:** ¿mantener Resend (ADR-047) o autorizar evaluar/cambiar a C1/C2? (Un cambio
   exigiría **revisar ADR-047**, que NO se toca sin tu aprobación.)
4. **Tamaño:** ¿se mantiene 64 MiB como cota defensiva o se alinea al techo real (~40 MB)?
   (afecta ADR-050; no se toca aquí). Umbral síncrono del Híbrido: sujeto a benchmark C4B3-08.

## 7. Plan de remediación de los demás hallazgos (Fases 2 y 3) — vista previa

Varios HIGH/MEDIUM dependen de la alternativa elegida en §6, así que se **redactarán en detalle
tras el GO** para evitar retrabajo. Mapa propuesto:

| Hallazgo | Resolución propuesta | ¿Depende de A/B/C? | Pruebas negativas a implementar |
|---|---|---|---|
| **C4B3-02** lease_token + CAS | `lease_token` opaco por claim; avance sólo por **compare-and-swap** (`UPDATE … WHERE id=? AND lease_token=?`); sin CAS, no se puede mutar | Sólo si hay worker (B/Híbrido) | dos workers compiten → solo uno gana el CAS; lease caducado no puede commitear |
| **C4B3-03** contexto tenant desde claim válido | `enter_inbound_context` deriva tenant **solo** de un claim verificado vía función controlada; **nunca** acepta `company_id`/`inbox_id` arbitrarios | Independiente | inyección de IDs arbitrarios → rechazo fail-closed |
| **C4B3-04** máquina de estados por funciones+constraints | transiciones **solo** vía funciones `SECURITY DEFINER` + CHECK/trigger que prohíben saltos ilegales; sin UPDATE libre de `state` | Principio independiente; estados según modelo | transición ilegal (p. ej. `captured`→`received`) → error |
| **C4B3-05** dependencias exactas para aprobar ADR-011/016/050 | lista de precondiciones medibles por ADR (hosting elegido, mecanismo de cola, backend de storage) | Parcial (016 sólo si B) | n/a (documental) |
| **C4B3-06** concurrencia / blobs huérfanos | blob + email + evento en **una** transacción; si falla, nada queda; reclamo idempotente no crea huérfanos | Depende del modelo de captura | fallo entre INSERT blob y commit → sin huérfano |
| **C4B3-07** credenciales/URLs/redirects Resend | validar host del `download_url` (allowlist CloudFront), **no seguir redirects**, TLS estricto, secreto en gestor, nunca en logs | Independiente | URL con host no permitido / redirect → abortar |
| **C4B3-08** memoria + benchmarks | medir pico real por captura y bajo `W`; fijar umbral síncrono y `W` con datos | Independiente (insumo del umbral) | carga con N×grandes → memoria acotada |
| **C4B3-09** reintentos, SLO, alertas, recuperación | backoff + presupuesto; SLO de preservación; alerta en `fetch_failed_exhausted`; reclamo tras lease | Depende del modelo | fetch que siempre falla → dead-letter + alerta, no loop infinito |
| **C4B3-10** constraints, índices, verificación `extensions.digest` | índice para el polling (`state,next_attempt_at`); verificar que `digest` es IMMUTABLE y schema-qualified en CHECK; fallback app-side | Independiente | digest no-IMMUTABLE → la migración falla en diseño, no en prod |
| **C4B3-11** deuda retención + datos personales | registrar como **deuda** con responsable y criterio de cierre (política de retención/borrado y tratamiento PII de evidencia) | Independiente | n/a (gobernanza) |

**C4B3-11** se registra como **deuda abierta**: *"Retención y tratamiento de datos personales
de la evidencia inbound"* — responsable: orquestador/Tribuu; criterio de cierre: política de
retención/borrado aprobada + base legal de tratamiento documentada, antes de producción con
datos reales.

## 8. Gobierno (sin cambios no cuestionados)
PR #1 en DRAFT · ADR-011/016/050 en DRAFT · ADR-047 intacto · sin merge · sin código,
migraciones ni despliegue · se preservan todas las decisiones no cuestionadas (abstracción
EvidenceBlob, idempotencia, conflictos, FKs tenant-safe, backend-only, RLS). Tras la decisión
de §6 y la remediación de Fases 2/3 → **segunda auditoría Codex** antes de implementar.
