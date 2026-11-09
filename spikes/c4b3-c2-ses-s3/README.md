# Spike C4-B3 / C2 — AWS SES → S3 (PoC aislada)

> **PoC NO PRODUCTIVA.** Investiga la resolución del CRITICAL **C4B3-01** (preservar la
> evidencia primaria en almacenamiento propio antes de aceptar el correo). **No** es
> implementación productiva. PR #1 en DRAFT; no se tocan ADR aceptados.
>
> **IaC NO APLICADA.** Terraform reproducible **sin ejecutar**. **Ninguna persona de Claude
> Code puede aprovisionar esto** (no hay credenciales AWS, cuenta ni control de DNS en el
> entorno): lo aplica y ejecuta el **propietario** tras aprobar §A. **Solo datos sintéticos**,
> nunca documentos fiscales reales ni PII.

---

## Resoluciones de esta ronda (preflight)

| # | Petición del orquestador | Resolución |
|---|---|---|
| 1 | Worker de prueba SQS (P1/P3/P4/P5) | `poc_worker.py`: idempotencia (SQLite por `messageId`+recipient), SHA-256 en streaming, visibility/DLQ, errores → reintento, logging sin PII |
| 2 | Pérdida de `receipt.recipients` si S3 ok y Lambda falla antes del sidecar | **Rediseño: se elimina la Lambda.** Los `receipt.recipients` (SOBRE) + `objectKey` viajan en la **notificación SNS nativa de SES** → SQS, portador **durable y autoritativo**, independiente de cualquier Lambda. El hueco desaparece. Residual (S3 ok pero SNS perdida) → **cuarentena + alerta**, **nunca MIME** (ver P3) |
| 3 | Compatibilidad real SES + SSE-KMS | Verificado: SES necesita **`kms:GenerateDataKey*`** en la CMK (key policy con `ses.amazonaws.com` + SourceAccount/SourceArn) o el `PutObject` falla; bucket policy con **SourceAccount+SourceArn** (no `aws:Referer`); worker con `kms:Decrypt`. Todo en el TF |
| 4 | Restricciones Terraform | `depends_on` (bucket/KMS/SNS policy antes de la rule), ARN de rule como string para romper ciclos, `active_receipt_rule_set`, `force_destroy`, ventana CMK, teardown (§D) |
| 5 | Validaciones no destructivas | **`terraform`/`tofu` NO están instalados en este entorno** → `fmt/init/validate` **no ejecutables aquí**; el propietario debe correrlos (§C). Revisión manual de sintaxis hecha |
| 6 | Matriz IAM + inventario exacto | §A.2 (inventario) y §A.6 (matriz IAM) |
| 7 | AWS Budgets $10 = alerta, no límite | Aclarado en §A.3/§G: **Budgets NO detiene el gasto**, solo **notifica** |
| 8 | Prompt de auditoría Codex | `CODEX_AUDIT_PROMPT.md` (recuperación, permisos AWS, Terraform, SQS, aislamiento multitenant) |

**Arquitectura (revisada, sin Lambda):**
```
MX subdominio → inbound-smtp.us-east-1.amazonaws.com
  → SES receipt rule (catch-all del subdominio)
       acción S3  → MIME crudo en s3://…/<messageId>  (SSE-KMS, ≤40 MB)
       + topic_arn → SNS (notificación NATIVA: receipt.recipients + objectKey, SIN body)
  → SNS → SQS (raw delivery, DLQ)
  → poc_worker.py: HeadObject → GetObject/stream → SHA-256 → captura idempotente (por tenant)
  → reconciliación (S3 fuente de verdad); orphans sin recipients autoritativos → CUARENTENA
```

---

## A. Paquete de aprobación previo al aprovisionamiento (requerido antes de crear recursos)

### A.1 Cuenta y dominio (a confirmar por el propietario)
- **Cuenta AWS sandbox autorizada:** `<ACCOUNT_ID>` (NO productiva).
- **Subdominio desechable:** `<p.ej. poc-inbox.ejemplo-test.xyz>` — **NUNCA `inbox.tribuu.ai`**.
- **Región:** `us-east-1`.

### A.2 Inventario de recursos (lo que crea la IaC)
| Recurso | Propósito | Costo recurrente |
|---|---|---|
| KMS CMK + alias | SSE-KMS del bucket (cifrado en reposo) | **$1/mes** |
| S3 bucket + BPA + SSE-KMS + versioning + lifecycle(7 d) + policy TLS-only/SES-puts | Copia durable del MIME crudo | ~$0 (volumen PoC) |
| SNS topic + topic policy | Notificación nativa SES (recipients+objectKey) | free tier |
| SNS→SQS subscription | Entrega durable al worker | — |
| SQS cola + DLQ + queue policy | Cola que consume el worker | free tier |
| SES domain identity + receipt rule set (activo) + rule (S3 + SNS) | Recepción → S3 + notificación | $0.10/1k + chunks (PoC: céntimos) |
| IAM: usuario worker scoped | Lectura S3/SQS + Decrypt | $0 |
| CloudWatch/AWS Budgets | Alertas (no límite) | $0–$0.10 |

**No hay Lambda** (eliminada en el rediseño del item 2).

### A.3 Costo máximo previsto y presupuesto
- **Costo máximo previsto de la PoC: < $5** (dominado por $1/mes de la CMK; uso sintético
  trivial; egress gratis <100 GB).
- **AWS Budget `monthly_budget_usd` = $10/mes** con alarmas 50/80/100 %. **ES UNA ALERTA, NO UN
  LÍMITE DE GASTO** (ver §G): AWS Budgets **notifica**, no detiene recursos.

### A.4 Rollback / eliminación
- `terraform destroy` (bucket con `force_destroy`). CMK entra en ventana de borrado (7 d).
- **MX/TXT del subdominio:** el propietario los añade y elimina manualmente (fuera de TF si el
  DNS no está en Route53). No se tocan registros productivos.
- **Access key del worker:** se crea fuera de TF y se **elimina** en el teardown (§D).

### A.5 Identidades y permisos requeridos
- **Para aplicar la IaC:** principal admin del **sandbox** (S3/KMS/SQS/SNS/SES/IAM/Budgets/CW).
- **Worker de la PoC:** usuario IAM scoped (§A.6), access key de corta vida, se elimina al final.

### A.6 Matriz de permisos IAM / recursos (item 6)
| Principal | Acciones | Recurso | Condición |
|---|---|---|---|
| `ses.amazonaws.com` (bucket policy) | `s3:PutObject` | `…/inbound-raw/*` | SourceAccount + SourceArn=receipt-rule |
| `ses.amazonaws.com` (KMS key policy) | `kms:GenerateDataKey*` | CMK | SourceAccount + SourceArn=receipt-rule |
| `ses.amazonaws.com` (SNS topic policy) | `SNS:Publish` | topic | SourceAccount + SourceArn=receipt-rule |
| `sns.amazonaws.com` (SQS queue policy) | `sqs:SendMessage` | cola intake | SourceArn=SNS topic |
| root de la cuenta (KMS key policy) | `kms:*` | CMK | (habilita IAM; evita lockout) |
| usuario worker (IAM) | `s3:GetObject` | `…/inbound-raw/*` | — |
| usuario worker (IAM) | `s3:ListBucket` | bucket | prefix `inbound-raw/*` |
| usuario worker (IAM) | `sqs:ReceiveMessage/DeleteMessage/GetQueueAttributes` | cola intake | — |
| usuario worker (IAM) | `kms:Decrypt` | CMK | — |

> **Acción solicitada:** aprobar A.1–A.6 (cuenta, subdominio, inventario, presupuesto $10,
> identidades) **antes** de cualquier `terraform apply`.

---

## B. Terraform (`./terraform`)
`versions.tf`, `variables.tf`, `main.tf`, `outputs.tf`. Flujo (propietario, **tras** aprobar A):
```
cd terraform
terraform fmt -check
terraform init -backend=false   # o con backend remoto del sandbox
terraform validate
terraform plan -var='subdomain=poc-inbox.ejemplo-test.xyz' \
               -var='budget_alarm_email=owner@ejemplo-test.xyz' -var='monthly_budget_usd=10'
# REVISAR plan/costos ⇒ si OK y aprobado:
terraform apply                 # <-- solo tras aprobación explícita (A)
# añadir MX + TXT del subdominio (ver outputs) en el DNS del propietario
# ... ejecutar P1–P5 con poc_worker.py ...
terraform destroy               # teardown (§D)
```

---

## C. Validaciones no destructivas (item 5) — resultado
- `terraform fmt` / `init -backend=false` / `validate`: **NO ejecutados en el entorno de Claude
  Code** porque **no hay binario `terraform`/`tofu` instalado** (comprobado: `terraform/tofu/
  opentofu not found`). **El propietario debe ejecutarlos** antes de `apply` y adjuntar la
  salida. Se hizo **revisión manual de sintaxis** y se marcaron puntos `# VERIFY` en `main.tf`.

---

## D. Checklist de teardown
- [ ] `terraform destroy` OK (bucket vaciado por `force_destroy`).
- [ ] Access key del usuario worker **eliminada**.
- [ ] CMK programada para borrado (ventana 7 d).
- [ ] **MX/TXT del subdominio eliminados** del DNS del propietario.
- [ ] $0 de recursos residuales en Cost Explorer / Budgets.

---

## E. Plan de pruebas obligatorias (PASS/FAIL)

**P1 — Durabilidad.** Correo sintético con adjunto → **PASS** si el MIME crudo aparece íntegro
en S3, `HeadObject` da tamaño/etag, el worker calcula **SHA-256** y recupera bytes idénticos.
**Fallo de escritura S3** (quitar permiso de SES) → registrar el **resultado SMTP real** (se
espera **rebote**). **PASS** si no hay aceptación silenciosa.

**P2 — Seguridad multitenant.** Dos buzones simulados → cada evidencia al tenant correcto desde
`receipt.recipients`. **MIME `To:` falsificado** → **PASS** si enruta por el **sobre SES** y
**no** se expone evidencia entre empresas.

**P3 — Recuperación / reconciliación.** **Pérdida de notificación** (borrar el mensaje SQS) → el
**barrido** (S3 fuente de verdad) descubre el objeto. **Objeto sin `receipt.recipients`
recuperables** (SNS perdida, sin sidecar): **NO** se usa MIME → **CUARENTENA + alerta**; **PASS**
si el sistema lo marca para revisión y **nunca** mis-enruta. Si alguien propusiera recuperar el
sobre desde el MIME → **registrar HALLAZGO BLOQUEANTE** (el MIME no es autoridad de sobre).

**P4 — Fallos e idempotencia.** Notificación duplicada → una sola captura (por `messageId`).
**Caída del worker** a mitad → visibility timeout re-entrega y se recupera sin duplicar.
**>40 MB** → rebote.

**P5 — Seguridad y operaciones.** Verificar IAM/KMS mínimas (§A.6), **BPA**, **SSE-KMS**
(descifrado por el worker **Python**, confirmando que NO se usó la client-side encryption de
SES), **logs sin PII**. Medir **memoria/latencia/costos** reales y validar **teardown** (§D).

---

## F. Entregable final de la PoC
Informe **PASS/FAIL** por prueba, evidencia (sintética), **costos reales**, riesgos residuales y
recomendación de adopción → **nueva auditoría Codex** para decidir si **C4B3-01** puede cerrarse.
No se cierra sin esa auditoría; no hay merge ni cambios productivos.

## G. Nota sobre AWS Budgets (item 7)
**AWS Budgets es un mecanismo de ALERTA, no un límite de gasto obligatorio.** No detiene ni
elimina recursos al superar el umbral; solo envía notificaciones. Un corte efectivo requeriría
*budget actions*/automatización adicional (no incluida en la PoC). El control real del gasto se
apoya en: el **radio de impacto pequeño** de la PoC (<$5 previsto), el **teardown reproducible**,
y la **vigilancia manual** del propietario ante las alarmas.

## H. Gobierno
PR #1 en DRAFT · ADR aceptados intactos · ADR-047/050/016 en DRAFT · sin merge · **IaC no
aplicada** · sin recursos facturables hasta aprobar §A · sin DNS productivo · sin datos
reales/PII · teardown reproducible.
