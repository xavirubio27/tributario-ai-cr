# C2 — Estudio de viabilidad: AWS SES Receiving → S3 (arquitectura objetivo)

> **Estado:** ESTUDIO DE VIABILIDAD Y DISEÑO. **No implementación.** El orquestador eligió
> C2 como arquitectura objetivo **pendiente de validación**; autoriza diseño + PoC, **no** el
> cambio de proveedor ni crear infraestructura AWS. PR #1 en DRAFT. **No se modifica ADR-047,
> ADR-050 ni ADR-016.** Sin migraciones, despliegues, cambios de MX/DNS ni código productivo.
>
> `[VERIFICADO]` doc oficial AWS (fechado hoy) · `[OBSERVADO]` C4-B0 · `[PROPUESTO]` diseño a ratificar · `[SUPUESTO]` hipótesis de cálculo explícita.

## 0. Resumen y recomendación

> **Actualización (remediación INFRA):** diseño unificado **SES → S3 → SNS → SQS** (sin Lambda
> ni sidecar). La afirmación de que una escritura S3 exitosa **precede** a toda aceptación SMTP
> queda **`[PENDIENTE DE PRUEBA]`** (se observará el resultado SMTP real en P1/§C de la PoC);
> no se declara C4B3-01 cerrado sin evidencia real y reauditoría.

C2 busca colocar la **copia durable del `.eml` original en un bucket S3 nuestro antes de
considerar el correo recibido**; `[PENDIENTE DE PRUEBA]` que, si SES no puede almacenarlo,
**rebote al remitente**. Objetivo: resolver C4B3-01 sin dependencia de retención externa.
Técnicamente **viable** y **barato a escala MVP** (ver §8). Principales costos no monetarios:
**cambio de proveedor** (Resend→SES, revisaría ADR-047), **infra/credenciales AWS** nuevas,
techo **40 MB**, región SES **no local** (us-east-1), y un **caveat de cifrado** verificado.

**Recomendación: GO a una PoC aislada y no productiva (§9); NO-GO al cambio de proveedor en
producción** hasta que la PoC valide entrega S3, duplicados, errores y aislamiento
multitenant. Mantener Resend como actual; no tocar ADR-047/050/016 hasta entonces.

## 1. Arquitectura SES Receiving → S3 → notificación durable → worker Tribuu

```
Internet ──(SMTP)──▶ MX: inbox.tribuu.ai → inbound-smtp.us-east-1.amazonaws.com
   └─ SES Email Receiving (receipt rule set, región us-east-1)
        rule (match por recipient del dominio):
          1) [opcional] spam/virus scan
          2) ACCIÓN S3  → escribe el MIME CRUDO en  s3://tribuu-inbound-raw/<prefix>/<messageId>  (≤40 MB)
          3) NOTIFICACIÓN SNS NATIVA (topic_arn del S3 action) → receipt.recipients (ENVELOPE,
                 autoritativo) + action.objectKey/bucketName.  SIN Lambda, SIN sidecar.
   └─ SNS → SQS (cola durable, retención 14 d; DLQ propia de la suscripción)
        └─ Worker Tribuu (ADR-011): long-poll SQS
              a) HeadObject S3 → CONFIRMA que el objeto existe y su tamaño/etag (antes de procesar)
              b) resuelve tenant(s) desde receipt.recipients (NO desde cabeceras MIME)
              c) por tenant activo: GetObject (stream) → SHA-256 → EvidenceBlob(object_storage,
                 locator=s3Key) + provider_event(provider='ses') + email_message  (idempotente)
              d) escribe el ledger DURABLE (markers/) y SOLO entonces borra el mensaje SQS
   └─ Reconciliación (backstop, §5): barrido periódico del bucket vs. locators ya ingeridos
```

**Principio:** **S3 es la fuente de verdad durable**; la notificación (SQS) es una
optimización, no la garantía. El evento `s3:ObjectCreated` / la acción SES sólo ocurren **tras**
la escritura durable del objeto.

## 2. El objeto queda almacenado antes de procesar · fallo de escritura de SES `[PENDIENTE DE PRUEBA]`

- El worker **sólo** procesa tras (i) recibir la notificación —que SES/S3 emiten **después** de
  almacenar durablemente el objeto— y (ii) un `HeadObject` que confirma existencia y
  tamaño/etag. No hay procesamiento sin objeto durable confirmado.
- **Si SES no puede escribir el objeto** (permisos, bucket/región inválidos, **>40 MB**): se
  **espera** que la acción falle → **rebote al remitente** (no aceptación). `[PENDIENTE DE
  PRUEBA]`: el resultado SMTP real ante éxito, AccessDenied, fallo KMS y error de
  almacenamiento se observa en P1/§C antes de afirmarlo.
- **Riesgo verificado:** una mala configuración (p. ej. Access Denied) puede causar "aceptado
  pero fallo silencioso de entrega a S3". Mitigación: el archivo de prueba
  `AMAZON_SES_SETUP_NOTIFICATION` (SES verifica permiso de escritura al configurar), **alarmas
  CloudWatch** sobre SES/bucket, y el **barrido de reconciliación** (§5).

## 3. Enrutado multitenant sin confiar en cabeceras MIME `[PROPUESTO]`

- **Autoridad de tenant = `receipt.recipients` de SES** (los destinatarios de ENVELOPE que SES
  aceptó para nuestro dominio), análogo a la autoridad `data.to` de Resend (ADR-049). **NO** se
  usan las cabeceras MIME `To:`/`Cc:` (manipulables).
- La **notificación SNS nativa de SES** lleva `receipt.recipients` (autoritativo) + `objectKey`
  a SQS; **sin Lambda ni sidecar**. El worker parsea la dirección `prefix-token@inbox.tribuu.ai`, resuelve el
  **inbox activo** vía el registro **C4-B1** (`inbound.company_inboxes`, `enter_inbound_context`,
  validación de token), **fail-closed** ante desconocido/deshabilitado. **Se preservan las
  garantías de aislamiento y autorización de C4-B1** intactas.

## 4. Asociación objeto S3 ↔ destinatario(s); correos multi-empresa `[PROPUESTO]`

- Mapeo `{s3Key → recipients}` proviene de la **notificación SNS de SES**, no del MIME.
- **Multi-recipient:** si `receipt.recipients` contiene varias direcciones Tribuu → **fan-out a
  varios tenants**. Para respetar "nunca compartir blob cross-tenant", se hace **copia
  server-side por tenant** (`CopyObject` a prefijo por tenant) de modo que **cada EvidenceBlob
  apunta a un objeto propio del tenant**. Coste marginal (un PUT/copy + almacenamiento por
  destinatario extra; caso raro).
- Idempotencia: `provider='ses'`, `provider_event_id = SES messageId`, clave de mensaje
  `(provider, provider_email_id=messageId, inbox_id)` — se **reutiliza el modelo C4-B3** (tablas,
  outcomes, `observed_blob_id`, conflicto) con el proveedor SES.

## 5. Reconciliación si falla la notificación `[PROPUESTO]`

- **S3 es la fuente de verdad.** Barrido periódico que **lista el bucket** (o usa **S3
  Inventory** diario) y compara contra los `object_locator` ya registrados en `inbound`;
  cualquier objeto sin captura correspondiente → se encola para procesar. Descubrimiento de
  evidencia pendiente **independiente de la entrega de la notificación**.
- Si un objeto queda **sin `receipt.recipients` recuperables** (notificación SNS perdida), el
  sobre SMTP **no es recuperable** del objeto → **cuarentena durable + alerta**, **nunca** MIME
  (ver `poc_reconcile.py` y §"RAW conservado sin sobre recuperable").
- Defensa en profundidad: SQS (durable, DLQ) como vía primaria + barrido de reconciliación como
  backstop.

## 6. IAM mínimo, cifrado, privacidad, integridad, retención, ciclo de vida `[PROPUESTO]`

- **IAM (least privilege):**
  - SES (bucket/KMS/SNS policy): `s3:PutObject` en `<prefix>/*`; `kms:GenerateDataKey*`+`kms:Decrypt`
    en la CMK; `SNS:Publish` en el topic; condición `AWS:SourceAccount`/`AWS:SourceArn` = la receipt rule.
  - Worker: `s3:GetObject` (solo lectura, prefijo), `sqs:ReceiveMessage/DeleteMessage`,
    `kms:Decrypt` en la CMK; **sin** permisos de borrado ni admin de bucket.
- **Cifrado — caveat verificado:** la opción "message encryption" de SES usa el **cliente de
  cifrado del lado cliente (SDK Java/Ruby)**, NO SSE de S3; un objeto así **solo se descifra con
  ese cliente** → **incompatible con un worker Python**. **Decisión `[PROPUESTO]`:** NO usar la
  message-encryption de SES; SES escribe MIME en claro y el bucket aplica **SSE-KMS por defecto**
  (CMM en la región SES) → cifrado en reposo, descifrado transparente por el worker con
  `kms:Decrypt`.
- **Privacidad:** Block Public Access (los 4) ON; bucket policy restringe a SES (PutObject con
  condiciones de cuenta/ARN) + worker (GetObject); `aws:SecureTransport` (solo TLS).
- **Integridad:** el worker calcula **SHA-256** sobre el stream del GetObject → `EvidenceBlob.
  sha256`; opcionalmente checksums SHA-256 nativos de S3. Invariante EvidenceBlob preservado.
- **Retención / ciclo de vida — limitación verificada:** la acción S3 de SES **no admite buckets
  con Object Lock + retención por defecto**. → No se puede imponer WORM por Object-Lock en el
  bucket destino de SES. Opciones: **lifecycle rules** (transición a clase fría / expiración por
  política) + versioning; si se requiere WORM, **copiar** a un bucket WORM aparte tras la
  ingesta. Política concreta de retención/borrado y base legal = **deuda C4B3-11** (datos
  personales).

## 7. EvidenceBlob y cambios en ADR-047 / ADR-050 / ADR-016 `[PROPUESTO — no se tocan ahora]`

- **EvidenceBlob se preserva tal cual:** `storage_backend='object_storage'`,
  `object_locator = <bucket>/<key>`. PostgreSQL sigue siendo índice/fuente de verdad de
  metadata (id, company_id, sha256, size, provenance, backend, locator, relaciones). El
  invariante de identidad (id+sha256+size, no ubicación) se mantiene. Los CHECK de storage ya
  contemplan `object_storage`.
- **ADR-050:** C2 **adelanta** `object_storage` como backend **inicial** del RAW inbound (en vez
  de `postgres_bytea` MVP → object_storage futuro). Eso **revisa la decisión de backend MVP de
  ADR-050**. (No se modifica aquí.)
- **ADR-047:** cambia el proveedor inbound (Resend → **AWS SES**) y **refuerza** la semántica:
  "recibido" pasaría a significar "almacenado durablemente en nuestro S3" `[PENDIENTE DE PRUEBA]`
  — potencialmente más fuerte que el ACK de Resend. **Revisión requerida.** (No se modifica aquí.)
- **ADR-016:** la cola durable puede pasar a **SQS** (nativa, DLQ) + reconciliación S3, en vez
  del outbox PG como primario; `provider_events` sigue registrando el intake durable. La
  seguridad multitenant del despachador (SECURITY DEFINER) sigue aplicando al lado PG; el consumo
  SQS lo hace el worker con credenciales AWS acotadas. **Revisión requerida.** (No se modifica.)

## 8. Estimación de costos (precios oficiales vigentes) `[VERIFICADO precios]`

**Supuestos explícitos** `[SUPUESTO]`: región **us-east-1**; **tamaño medio 500 KB/email** (XML
+ PDF pequeño) → **2 chunks** SES de 256 KB; **1 destinatario/email** (sin copia multi-tenant);
worker **fuera de AWS** (Render/Fly, ADR-011) → egress S3 a Internet aplica; retención = se
calcula el almacenamiento del flujo de **1 mes**; precios de las páginas oficiales AWS
(us-east-1), susceptibles de cambio.

**Tarifas unitarias verificadas:** SES recepción **$0.10/1.000 emails** + **$0.09/1.000
chunks(256 KB)**; S3 Standard **$0.023/GB-mes**, **PUT $0.005/1.000**, **GET $0.0004/1.000**;
egress a Internet **primeros 100 GB/mes gratis**, luego ~$0.09/GB; SQS **$0.40/millón** (1M
gratis/mes); SNS $0.50/millón (1M gratis); KMS ~$0.03/10.000 req +
**$1/mes por CMK**.

| Concepto (mensual) | 1.000 emails | 10.000 | 100.000 |
|---|---|---|---|
| SES recepción ($0.10/1k) | $0.10 | $1.00 | $10.00 |
| SES chunks (2×, $0.09/1k) | $0.18 | $1.80 | $18.00 |
| S3 PUT (raw + markers) | ~$0.00 | $0.10 | $1.00 |
| S3 GET (raw) | ~$0.00 | ~$0.01 | $0.08 |
| S3 almacenamiento (500 KB × N, 1 mes) | ~$0.01 | $0.12 | $1.15 |
| SQS / SNS | free tier | free tier | ~$0.00–0.20 |
| KMS (req + $1 CMK) | ~$1.01 | ~$1.06 | ~$1.60 |
| Egress S3 (0.5/5/50 GB, <100 GB) | **$0 (gratis)** | **$0 (gratis)** | **$0 (gratis)** |
| **Total aprox./mes** | **~$1.3–1.5** | **~$4–4.5** | **~$31–33** |

**Sensibilidad:** el costo escala casi lineal con SES recepción+chunks (dominante). Si el tamaño
medio sube o el volumen supera ~100 GB/mes de egress (worker fuera de AWS), el **egress** se
activa (~$0.09/GB) y el **almacenamiento acumulado** crece mes a mes según la retención. **Alojar
el worker EN AWS (misma región)** elimina el egress y permite **roles IAM de instancia** (sin
credenciales estáticas) — recomendación ligada a ADR-011.

## 9. Prueba de concepto aislada y no productiva (plan) `[PROPUESTO — requiere autorización AWS]`

**Aislamiento:** cuenta AWS **sandbox**, **subdominio desechable** (p. ej. `poc-inbox.<dominio
de pruebas>`), **NO** `inbox.tribuu.ai`, **NO** MX/DNS productivos. Teardown al terminar.
**No se crea nada hasta autorización expresa.**

Verificaciones:
1. **Entrega S3:** un correo de prueba → objeto MIME crudo en S3; confirmar tamaño/etag y SSE-KMS.
2. **Duplicados:** reenviar el mismo mensaje / reintentos SES → dedup por `messageId`
   (idempotencia del modelo C4-B3).
3. **Errores:** correo **>40 MB** → rebote; bucket sin permiso → rebote + alarma; KMS mal
   configurada → detección.
4. **Seguridad multitenant:** dos destinatarios de prueba → resolución correcta desde
   `receipt.recipients`; un **MIME `To:` falsificado NO debe reenrutar**.
5. **Pérdida de notificación → reconciliación:** borrar/omitir el mensaje SQS → `poc_reconcile.py`
   (S3 fuente de verdad) descubre el objeto huérfano; sin recipients autoritativos → cuarentena, nunca MIME.
6. **Cifrado y descifrado en Python:** objeto SSE-KMS leído y descifrado por el worker Python
   (confirmar que NO se usó la client-side encryption de SES).

Entregable de la PoC: evidencia reproducible + hallazgos de seguridad → insumo del GO/NO-GO de
producción.

## 10. Correos > 40 MB y limitaciones por región/configuración `[VERIFICADO]`

- **>40 MB:** SES **rebota** (techo de 40 MB incl. cabeceras; no ajustable por encima; algunas
  cuentas arrancan en 30 MB y suben hasta 40). Nuestra política de 64 MiB queda **moot**: el
  proveedor cap­a a 40 MB. Dato para la decisión de tamaño pendiente de ADR-050 (alinear a 40 MB).
- **Regiones:** SES Email Receiving **no está en Centroamérica**; endpoints en us-east-1,
  us-east-2, us-west-1/2, sa-east-1, varias de UE/APAC, etc. (no GovCloud). **Todos los recursos
  salvo S3 deben estar en la misma región que el endpoint SES.** Elección `[PROPUESTO]`:
  **us-east-1** (cercano, barato; alinear la región de Supabase/worker reduce latencia/egress).
- **Config:** verificación de dominio + **MX** `inbound-smtp.us-east-1.amazonaws.com`; receipt
  rule sets; el sandbox de SES limita **envío**, no recepción (recepción funciona con dominio
  verificado + MX); **Object Lock con retención por defecto no soportado** en el bucket destino;
  **message-encryption de SES = client-side (Java/Ruby)** → usar SSE-KMS.

## 11. Riesgos y tradeoffs

| Riesgo / tradeoff | Severidad | Nota |
|---|---|---|
| Cambio de proveedor Resend→SES | Alta | revisa ADR-047; Resend/Mailgun quedan como alternativas |
| Infra + credenciales AWS nuevas | Alta | contradice la postura "sin credenciales ahora"; IAM/KMS; superficie operativa |
| Techo 40 MB (rebote) | Media | provider-enforced; alinear política de tamaño |
| Región SES no local (us-east-1) | Baja | latencia aceptable; alinear Supabase/worker |
| Caveat cifrado client-side SES | Media | mitigado: SSE-KMS, no message-encryption |
| Object Lock default-retention no soportado | Media | WORM vía copia a bucket aparte; lifecycle sí |
| Fallo silencioso de escritura por misconfig | Media | setup-test file + alarmas + reconciliación (§2/§5) |
| Egress si worker fuera de AWS a escala | Media | alojar worker en AWS (ADR-011) lo elimina |
| Retención/PII sin política | Media | **deuda C4B3-11**, responsable + criterio de cierre |

## 12. Recomendación GO/NO-GO

- **GO** a la **PoC aislada y no productiva** (§9) para validar entrega S3, duplicados, errores
  y seguridad multitenant — **requiere tu autorización expresa para crear la cuenta/subdominio
  sandbox** (hoy vetado).
- **NO-GO** al cambio de proveedor en producción y a modificar ADR-047/050/016 **hasta** que la
  PoC valide y decidas la sustitución formal.
- **Condición recomendada:** si se adopta C2, **alojar el worker en AWS** (misma región) para
  eliminar egress y usar roles IAM de instancia — a decidir en ADR-011.

## 13. Gobierno
PR #1 en DRAFT · ADR-047/050/016 intactos · sin merge · sin migraciones/despliegues · sin
MX/DNS productivos · **sin crear infraestructura AWS** · sin código productivo. Decisiones no
cuestionadas preservadas.

---
**Fuentes (verificadas hoy):** [SES pricing](https://aws.amazon.com/ses/pricing/) ·
[S3 pricing](https://aws.amazon.com/s3/pricing/) · [SNS pricing](https://aws.amazon.com/sns/pricing/) ·
[SES email receiving regions](https://docs.aws.amazon.com/ses/latest/dg/regions.html) ·
[Deliver to S3 bucket action](https://docs.aws.amazon.com/ses/latest/dg/receiving-email-action-s3.html) ·
[SES receiving concepts](https://docs.aws.amazon.com/ses/latest/dg/receiving-email-concepts.html).
