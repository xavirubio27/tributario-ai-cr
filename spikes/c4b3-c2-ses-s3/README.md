# Spike C4-B3 / C2 — AWS SES → S3 → SNS → SQS (PoC aislada)

> **PoC NO PRODUCTIVA.** Investiga la resolución del CRITICAL **C4B3-01**. **IaC NO APLICADA.**
> **Ninguna persona de Claude Code puede aprovisionar esto** (sin credenciales AWS, cuenta ni
> DNS): lo aplica y ejecuta el **propietario** tras aprobar §A. **Solo datos sintéticos.**
> PR #1 en DRAFT; ADR aceptados intactos; ADR-047/050/016 en DRAFT.
>
> **Diseño unificado:** `SES receipt rule → acción S3 (MIME crudo, SSE-KMS) + notificación SNS
> nativa (receipt.recipients + objectKey) → SQS → worker`. **Sin Lambda ni sidecar.** Ledger
> durable de resultados en S3 bajo `markers/`.

## Remediación INFRA-H1→L3 (resumen)
Matriz completa con estado/modificación/prueba/evidencia en
[`REMEDIATION_INFRA_H1_L3.md`](REMEDIATION_INFRA_H1_L3.md). Cambios clave de esta ronda:
- **Cuarentena/ledger DURABLE en S3** (`markers/processed|quarantine|rejected`); el worker **no
  borra de SQS** sin resultado durable y verificado (H1/H2).
- **`poc_reconcile.py`**: S3 fuente de verdad; detecta huérfanos (id, antigüedad, motivo, sin PII) (H3).
- **DLQ independiente** para la suscripción SNS→SQS + alarmas CloudWatch de ambas DLQ (H3/M4).
- **KMS key policy** con SES `GenerateDataKey*`+`Decrypt` (o el PutObject SSE-KMS falla) y
  SourceAccount/SourceArn; **cifrado en reposo** en S3 (SSE-KMS), SNS (CMK) y SQS (SSE-SQS) (H4/M5).
- **Retención S3 = 30 d** (> SQS/DLQ/reconciliación) (H7).
- Worker: **idempotencia durable** (markers en S3, no solo SQLite), **heartbeat** de visibilidad,
  **logs redactados** sin PII (M1/M2/M3).
- Terraform: **validaciones de variables**, **protección del rule set activo** (`activate_rule_set`
  opt-in), orden de dependencias, credenciales temporales (M6/M7/L1/L2).
- Docs **unificadas**; la afirmación "escritura S3 precede a la aceptación SMTP" reclasificada
  **PENDIENTE DE PRUEBA** (H5/H6).

---

## A. Paquete de aprobación previo al aprovisionamiento

### A.1 Cuenta y dominio (a confirmar por el propietario)
- **Cuenta AWS sandbox:** `<ACCOUNT_ID>` (NO productiva). **Subdominio desechable:**
  `<poc-inbox.ejemplo-test.xyz>` (NUNCA `inbox.tribuu.ai`; validado por `variables.tf`).
  **Región:** `us-east-1`.

### A.2 Inventario de recursos
| Recurso | Propósito | Costo |
|---|---|---|
| KMS CMK + alias | SSE-KMS de S3 y SNS | $1/mes |
| S3 bucket (BPA, SSE-KMS, versioning, lifecycle **30 d**, policy TLS-only/SES-puts) | RAW + ledger `markers/` | ~$0 |
| SNS topic (SSE) + topic policy | Notificación nativa SES (recipients+objectKey) | free tier |
| SNS→SQS subscription (con DLQ propia) | Entrega durable | — |
| SQS intake + **consumer-DLQ** + **sns-DLQ** (SSE-SQS) + policies | Cola del worker + DLQs | free tier |
| CloudWatch alarms (2× DLQ) + SNS `alerts` + email | Alarmas provisionadas | ~$0 |
| SES domain identity + receipt rule set (+ rule) | Recepción → S3 + SNS | céntimos |
| IAM **rol** worker asumible (STS, scoped, Deny negativos) | Lectura RAW, R/W markers, SQS, KMS — credenciales temporales | $0 |
| AWS Budgets $10 (ALERTA) | Aviso de costo | ~$0 |

**Sin Lambda.** **Costo máximo previsto: < $5** (CMK $1/mes + uso sintético trivial).

### A.3 Presupuesto, rollback, identidades
- **AWS Budget $10/mes**, alarmas 50/80/100 % — **ES ALERTA, NO LÍMITE** (§G).
- **Rollback:** `terraform destroy` (bucket `force_destroy`; CMK ventana 7 d). MX/TXT y access
  key del worker: manual (§D).
- **Identidades:** aplicar = admin sandbox; worker = **credenciales temporales (STS AssumeRole)**
  preferidas; si se usa access key, se **revoca** en teardown (M7).

### A.4 Matriz de permisos IAM (item 6 + permisos negativos)
| Principal | Acciones | Recurso | Condición/Nota |
|---|---|---|---|
| `ses.amazonaws.com` (bucket policy) | `s3:PutObject` | `…/inbound-raw/*` | SourceAccount+SourceArn=rule |
| `ses.amazonaws.com` (KMS key policy) | `kms:GenerateDataKey*`,`kms:Decrypt` | CMK | SourceAccount+SourceArn=rule |
| `ses.amazonaws.com` (SNS topic policy) | `SNS:Publish` | topic | SourceAccount+SourceArn=rule |
| `sns.amazonaws.com` (SQS policies) | `sqs:SendMessage` | intake + sns-DLQ | SourceArn=topic |
| root (KMS) | `kms:*` | CMK | habilita IAM; evita lockout |
| worker (IAM) | `s3:GetObject` | `inbound-raw/*` | — |
| worker (IAM) | `s3:GetObject`,`s3:PutObject` | `markers/*` | ledger durable |
| worker (IAM) | `s3:ListBucket` | bucket | prefix `inbound-raw/*`,`markers/*` |
| worker (IAM) | `sqs:Receive/Delete/ChangeMessageVisibility/GetQueueAttributes` | intake | heartbeat |
| worker (IAM) | `kms:Decrypt`,`kms:GenerateDataKey*` | CMK | leer RAW / escribir markers cifrados |
| worker (IAM) **DENY** | `s3:DeleteObject`,`s3:PutObject` | `inbound-raw/*` | **permiso negativo** (no mutar RAW) |

> **Acción solicitada:** aprobar A.1–A.4 (cuenta, subdominio, inventario, presupuesto $10,
> identidades) **antes** de cualquier `terraform apply`.

---

## B. Terraform (`./terraform`) — flujo del propietario (tras aprobar A)
```
cd terraform
terraform fmt -check && terraform init -backend=false && terraform validate
terraform plan -var='subdomain=poc-inbox.ejemplo-test.xyz' \
               -var='budget_alarm_email=owner@ejemplo-test.xyz' \
               -var='worker_assumer_principal_arn=arn:aws:iam::<ACCT>:user/<bootstrap>'
# REVISAR ⇒ si aprobado:  terraform apply
# activar el rule set SOLO tras verificar que no hay otro activo:
#   terraform apply -var='activate_rule_set=true'   (o activarlo manual en la consola SES)
# añadir MX + TXT del subdominio (outputs) en el DNS del propietario
# ejecutar P1–P5 (poc_worker.py / poc_reconcile.py) ; luego  terraform destroy
```

## C. Validaciones ejecutadas (resultado real)
Terraform v1.9.8 (binario descargado localmente, **sin tocar AWS**):
- `terraform fmt -check -diff` → **exit 0** (sin cambios).
- `terraform init -backend=false` → **OK** (provider `hashicorp/aws` v5.100.0).
- `terraform validate` → **"Success! The configuration is valid."** (exit 0).
- `terraform plan` → **NO ejecutado** (requiere credenciales sandbox autorizadas).

Pruebas locales (sin AWS, stdlib + fakes):
- `python3 tests/test_poc.py` → **Ran 23 tests — OK** (12 escenarios + concurrencia real 8 hilos + heartbeat async/cierre + version-pinning + manifest malformado/incoherente + cuarentena independiente + alerta durable con reintento + estado conflict + aceptación).
- `python3 poc_smoke_test.py` → E2E: complete=1, orphan=1, quarantine=1.
- `python3 -m py_compile` (worker/reconcile/smoke/fakes/test) → PASS · scan de secretos → limpio.

## C-bis. Cómo correr las pruebas locales
```
cd spikes/c4b3-c2-ses-s3
python3 tests/test_poc.py      # suite unittest con fakes AWS (sin red, sin AWS)
python3 poc_smoke_test.py      # demo E2E en memoria
```

## D. Teardown
- [ ] `terraform destroy` OK (bucket vaciado por `force_destroy`).
- [ ] Access key / sesión STS del worker **revocada**.
- [ ] CMK programada para borrado (7 d).
- [ ] **MX/TXT del subdominio eliminados** del DNS del propietario.
- [ ] $0 residual en Cost Explorer / Budgets; markers y DLQs vacíos.

---

## E. Plan de pruebas (PASS/FAIL) — a ejecutar en la PoC

**P1 — Durabilidad y resultado SMTP (H6).** Correo sintético → MIME crudo íntegro en S3;
`HeadObject`; **SHA-256** reproducible. **Observar el código SMTP real** ante: éxito (se espera
250), **AccessDenied** de S3, **fallo KMS** (sin GenerateDataKey), y **error de almacenamiento**.
**PASS** si ninguna condición produce aceptación silenciosa; registrar el resultado SMTP de cada
caso (NO se declara el orden "almacenado antes de aceptar" sin esta evidencia).

**P2 — Seguridad multitenant (H8) — alcance explícito.** Dos buzones simulados + **MIME `To:`
falsificado**. Distinguir y marcar por separado:
- **autoridad del sobre** (routing **solo** desde `receipt.recipients`) → **probable en la PoC**;
- **almacenamiento tenant-scoped** (copia/markers por tenant) → **probable en la PoC**;
- **resolución de empresa vía C4-B1** (registro Supabase) → **PENDIENTE (fuera del alcance PoC)**;
- **aislamiento real con RLS** (Postgres) → **PENDIENTE (fuera del alcance PoC)**.
Si una garantía no se prueba, se declara **PENDIENTE**, nunca PASS.

**P3 — Recuperación.** Pérdida de notificación (borrar SQS) → `poc_reconcile.py` descubre el
huérfano. **Sin `receipt.recipients` recuperables** → **CUARENTENA durable + alerta**, **nunca
MIME**; **PASS** si se marca para revisión manual (la cuarentena **no** es recuperación
automática del tenant). Proponer recuperar el sobre desde el MIME → **HALLAZGO BLOQUEANTE**.

**P4 — Fallos e idempotencia.** Duplicados → una sola captura (marker durable). **Caída del
worker** a mitad → visibility/heartbeat re-entrega y recupera sin duplicar ni perder; el worker
**no borró** sin marker durable. **>40 MB** → rebote.

**P5 — Seguridad/operaciones.** IAM/KMS mínimas (§A.4) + Deny negativos; **BPA**; **SSE** en S3
(KMS)/SNS(CMK)/SQS(SSE-SQS); descifrado del worker en **Python** (no client-side SES); **logs sin
PII**; memoria/latencia/costos reales; **teardown** (§D).

## F. RAW conservado sin sobre recuperable (documentación expresa, item A7)
Si la acción S3 tiene éxito pero **la notificación SNS se pierde** y no hay otro portador
autoritativo, el `.eml` queda en S3 **pero el sobre SMTP (`receipt.recipients`) no es
recuperable** del objeto (las cabeceras MIME **no** son autoridad). Resultado: el objeto es un
**huérfano** → `poc_reconcile.py` lo detecta → **cuarentena + alerta**, **sin** enrutar. No se
pierde la evidencia (RAW preservado), pero **el tenant no se resuelve automáticamente**. Mitigación:
SNS→SQS es durable (reintentos + DLQ de suscripción); los huérfanos son un caso límite acotado.

## G. AWS Budgets = ALERTA, no límite (item 7)
AWS Budgets **no detiene el gasto**; solo notifica. El control real = radio de impacto pequeño
(<$5), teardown reproducible y vigilancia manual.

## Reconciliación manual (sin EventBridge) — comando + checklist OBLIGATORIO
La reconciliación/alertas NO son automáticas en esta PoC. Procedimiento reproducible:
```
cd spikes/c4b3-c2-ses-s3
# credenciales TEMPORALES del rol worker (STS):
#   aws sts assume-role --role-arn <worker_role_arn> --role-session-name poc-recon --duration-seconds 3600
RAW_BUCKET=<raw_bucket> RAW_PREFIX=inbound-raw/ MARKERS_PREFIX=markers/ \
  ALERTS_TOPIC_ARN=<alerts_topic_arn> python3 poc_reconcile.py
```
Checklist obligatorio tras cada corrida:
- [ ] Revisar `states` (orphan/partial/conflict > 0 => acción).
- [ ] Verificar `pending_retried_sent` y que no queden `alerts/pending/*` sin `alerts/sent/*`.
- [ ] Atender cada alerta `action_required` (orphan → cuarentena manual; conflict → revisar
      canonical vs observed; partial → reprocesar recipients pendientes).
- [ ] Confirmar que la suscripción de email del topic de alertas está **confirmada**.
> No existe ejecución automática; esta reconciliación debe lanzarse manualmente de forma periódica.

## Preparar `terraform plan` (comandos) — requiere credenciales sandbox autorizadas
```
cd terraform
terraform init                       # backend real del sandbox (o -backend=false para validar)
terraform plan \
  -var='subdomain=poc-inbox.ejemplo-test.xyz' \
  -var='budget_alarm_email=owner@ejemplo-test.xyz' \
  -var='worker_assumer_principal_arn=arn:aws:iam::<ACCT>:user/<bootstrap>'
# (activate_rule_set=false por defecto; activar solo tras verificar que no hay rule set activo)
```

## H. Gobierno
PR #1 DRAFT · ADR aceptados intactos · ADR-047/050/016 DRAFT · sin merge · **IaC no aplicada** ·
sin recursos AWS/DNS · sin datos reales/PII · **C4B3-01 NO se declara cerrado** sin PoC real +
reauditoría Codex.
