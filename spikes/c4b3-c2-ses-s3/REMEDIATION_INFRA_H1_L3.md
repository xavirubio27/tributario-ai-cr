# Remediación INFRA-H1 → L3 — PoC C4-B3 / C2 (SES → S3 → SNS → SQS)

> Respuesta a la auditoría Codex del commit `a388848`. **Diseño/IaC de PoC; sin aplicar, sin
> recursos AWS, sin DNS, sin datos reales.** PR #1 en DRAFT, sin merge. ADR-047/050/016 en DRAFT.
>
> **Leyenda de estado:** `Remediado(código/IaC)` · `Remediado(doc)` · `Mitigado — prueba pendiente
> de la PoC` (comportamientos de runtime que exigen ejecutar la PoC con AWS, P1–P5).
> **Leyenda de prueba:** `py_compile PASS` (ejecutado aquí) · `terraform validate NO ejecutado`
> (sin binario en el entorno; §C del README) · `pendiente PoC` · `N/A (doc)`.

## HIGH

| ID | Hallazgo (resumen) | Estado | Modificación aplicada | Prueba | Evidencia |
|---|---|---|---|---|---|
| **H1** | Cuarentena durable para evidencia sin destinatarios/conflictos/rechazos | Remediado(código/IaC) · Mitigado—prueba PoC | Ledger durable en S3 `markers/{processed,quarantine,rejected}`; cuarentena durable en el worker; **la cuarentena NO es recuperación automática del tenant** | py_compile PASS; func. pendiente PoC (P3/P4) | `poc_worker.py` (`_marker_key`, `process_message`), IAM `RWMarkers` en `main.tf` |
| **H2** | Prohibir `DeleteMessage` sin resultado durable verificable | Remediado(código) · Mitigado—PoC | `process_message` devuelve "borrar" **solo** tras escribir y `HeadObject`-verificar el/los marker(s); fallo → no borra → SQS re-entrega | py_compile PASS; func. pendiente PoC (P4) | `poc_worker.py` (`_write_marker_verified`, `return all_durable`) |
| **H3** | `poc_reconcile.py` + huérfanos + DLQ independiente de la suscripción SNS→SQS | Remediado(código/IaC) · Mitigado—PoC | `poc_reconcile.py` (S3 vs markers, id/antigüedad/motivo, sin PII); **sns-DLQ** + `redrive_policy` en la suscripción + alarmas CloudWatch | py_compile PASS; func. pendiente PoC (P3) | `poc_reconcile.py`; `aws_sqs_queue.sns_dlq`, `aws_sns_topic_subscription.intake.redrive_policy`, alarmas en `main.tf` |
| **H4** | Key policy KMS con permisos reales de SES; SourceAccount/SourceArn | Remediado(IaC) | CMK policy: SES `kms:GenerateDataKey*`+`kms:Decrypt` (sin esto el PutObject SSE-KMS falla) con SourceAccount/SourceArn; bucket/SNS policies con las mismas condiciones | terraform validate NO ejecutado; balance OK | `aws_kms_key.evidence.policy`, `aws_s3_bucket_policy.raw`, `aws_sns_topic_policy.receipt` |
| **H5** | Unificar docs bajo SES→S3→SNS→SQS; retirar Lambda/sidecar | Remediado(doc) | Doc de viabilidad reescrito a SES→S3→SNS→SQS; descripciones activas de Lambda/sidecar retiradas (solo quedan negaciones) | N/A (doc) | `docs/design/C4-B3-C2-SES-feasibility.md` §0/§1/§3/§4/§5/§6/§8/§9 |
| **H6** | Reclasificar "escritura S3 precede a la aceptación SMTP" como PENDIENTE DE PRUEBA; diseñar pruebas SMTP | Remediado(doc) | §2 y §0 marcadas `[PENDIENTE DE PRUEBA]`; P1 observa el **código SMTP real** ante éxito/AccessDenied/fallo KMS/error de almacenamiento | N/A (doc); SMTP pendiente PoC (P1) | feasibility §0/§2; README §E-P1 |
| **H7** | Ampliar retención S3 > ventana SQS/DLQ/reconciliación (30 d) | Remediado(IaC) | `object_expiration_days` default **30**; validación `>= 30`; lifecycle actualizado | terraform validate NO ejecutado | `variables.tf`, `aws_s3_bucket_lifecycle_configuration.raw` |
| **H8** | Aislamiento multitenant: autoridad del sobre, C4-B1, RLS, storage tenant-scoped | Remediado(doc/diseño) · **alcances PENDIENTE** | P2 distingue y marca por separado: autoridad del sobre (probable PoC), storage tenant-scoped (probable PoC), **C4-B1 y RLS = PENDIENTE (fuera del alcance PoC)**; no se marca PASS lo no probado | pendiente PoC (P2) | README §E-P2; worker enruta solo por `receipt.recipients` |

## MEDIUM

| ID | Hallazgo | Estado | Modificación | Prueba | Evidencia |
|---|---|---|---|---|---|
| **M1** | Idempotencia SQLite / persistencia ante reinicios | Remediado(código) | Idempotencia **durable** por existencia de marker `processed` en S3 (sobrevive reinicios); SQLite deja de ser la fuente | py_compile PASS; PoC (P4) | `poc_worker.py` (`_marker_exists`) |
| **M2** | Visibility timeout, heartbeat y permisos | Remediado(código/IaC) | `_Heartbeat` extiende visibilidad (`ChangeMessageVisibility`); IAM worker con `sqs:ChangeMessageVisibility` | py_compile PASS; PoC (P4) | `poc_worker.py` (`_Heartbeat`); `main.tf` IAM `Sqs` |
| **M3** | Redacción de destinatarios y claves S3 en logs | Remediado(código) | `_redact()` (HMAC efímero) sobre messageId/recipient/key; nunca cuerpo/remitente | py_compile PASS | `poc_worker.py` (`_redact`, llamadas `log.*`) |
| **M4** | Alarmas efectivamente provisionadas | Remediado(IaC) | `aws_cloudwatch_metric_alarm` para ambas DLQ → SNS `alerts` → email | terraform validate NO ejecutado | `main.tf` (`consumer_dlq`, `sns_dlq`, `alerts`) |
| **M5** | Cifrado de metadatos | Remediado(IaC) | markers en bucket SSE-KMS; SNS con CMK; SQS con SSE-SQS | terraform validate NO ejecutado | `main.tf` (SSE S3/SNS/SQS) |
| **M6** | Orden de dependencias Terraform | Remediado(IaC) | `depends_on` en subscription (queue policies) y rule (bucket/KMS/SNS policy); ARN de rule como string (sin ciclos) | balance OK; validate NO ejecutado | `main.tf` (`depends_on`, `local.receipt_rule_arn`) |
| **M7** | Credenciales temporales y revocación | Remediado(IaC/doc) | No se emite access key en TF; se recomienda **STS AssumeRole**; revocación en teardown | N/A | `main.tf` nota worker; README §A.3/§D |
| **M8** | Validaciones reales de Terraform | **Documentado (no ejecutable aquí)** | Reportado: `terraform`/`tofu` no instalados → `fmt/init/validate` NO ejecutados; **no** se declara PASS por inspección manual | `terraform validate NO ejecutado` | README §C; salida `terraform not found` |

## LOW

| ID | Hallazgo | Estado | Modificación | Prueba | Evidencia |
|---|---|---|---|---|---|
| **L1** | Variables con restricciones de seguridad | Remediado(IaC) | `validation` en `subdomain` (prohíbe tribuu.ai), `budget_alarm_email` (regex), `monthly_budget_usd` (0<x<=50), `object_expiration_days` (>=30) | validate NO ejecutado | `variables.tf` |
| **L2** | Protección ante reemplazo de un rule set activo existente | Remediado(IaC) | `activate_rule_set` (default **false**, `count`): no reemplaza el rule set activo salvo opt-in explícito | validate NO ejecutado | `variables.tf`, `aws_ses_active_receipt_rule_set.poc` |
| **L3** | Verificación de costos vigentes | Remediado(doc) | Precios AWS verificados 2026-11 (SES/S3/SNS/SQS/KMS, citados); nota de **re-verificar al aprovisionar** | N/A (doc) | feasibility §8; `main.tf` comentario Budgets |

## Diferencias documentales
- **Eliminada la Lambda y el sidecar** del diseño y de la documentación activa; autoridad de
  destinatarios ahora vía **notificación SNS nativa de SES** (`receipt.recipients` + `objectKey`).
- Afirmación de **orden S3-antes-de-aceptación-SMTP** → **`[PENDIENTE DE PRUEBA]`** en feasibility
  §0/§2; P1 define la observación del resultado SMTP real.
- **Alcance multitenant** (P2) separa lo probable en PoC de lo **PENDIENTE** (C4-B1, RLS).
- Nuevo documento de **RAW conservado sin sobre recuperable** (README §F).

## Riesgos residuales
1. **Huérfanos sin sobre recuperable** (S3 ok, SNS perdida): RAW preservado pero **tenant no
   resoluble** → cuarentena + alerta, **nunca MIME**. Acotado por la durabilidad de SNS→SQS+DLQ.
2. **Orden S3/SMTP no probado:** se confirma solo con la PoC (P1); hasta entonces es hipótesis.
3. **SNS cifrado con CMK + publish de SES:** marcado `# VERIFY` (requiere plan/apply real).
4. **C4-B1/RLS fuera del alcance PoC:** el aislamiento real a nivel de tenant en DB no se prueba
   aquí; queda PENDIENTE para la integración posterior.
5. **`terraform validate` no ejecutado** en este entorno: el propietario debe correrlo antes de apply.

## Verificaciones ejecutadas (evidencia reproducible)
```
python3 -m py_compile poc_worker.py poc_reconcile.py   → PASS
command -v terraform / tofu / opentofu                 → not found (fmt/init/validate NO ejecutados)
balance de llaves/corchetes de *.tf                    → OK (no es un validate)
scan de secretos                                       → sin secretos
```

## Commit final para reauditoría
Ver el commit de esta remediación en la rama `docs/adr-050-draft` del PR #1 (no merge). Auditar
con `CODEX_AUDIT_PROMPT.md`. **C4B3-01 NO se declara cerrado**: requiere ejecutar la PoC (P1–P5)
con evidencia real y una nueva auditoría independiente.
