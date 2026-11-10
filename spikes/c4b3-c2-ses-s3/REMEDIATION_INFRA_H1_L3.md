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

## Ronda 2 — reauditoría de `23f6ffd` (NEW-H1..H5, NEW-M1/M2)

| ID | Hallazgo | Estado | Modificación | Prueba |
|---|---|---|---|---|
| **NEW-H1** | `check→put` no atómico; conflictos que podían sobrescribir | Remediado(código) | **Escritura condicional `IfNoneMatch="*"`**; `412 PreconditionFailed` → lee existente y compara; **verificación de contenido** (GetObject) no solo Head; conflictos **append-only** por sha; ids canónicos con delimitador | test_01/02/10/14/15 PASS |
| **NEW-H2** | Completitud multirecipient | Remediado(código) | **Manifest inmutable** con `expected_recipients`; completitud por conjunto `expected-completed` | test_03/14 PASS |
| **NEW-H3** | Reconciliador declaraba éxito por un solo marker; prefijos ambiguos | Remediado(código) | Estados complete/partial/rejected/quarantine; **claves exactas con delimitador** (sin `abc`/`abcd`) | test_03/04/05 PASS |
| **NEW-H4** | Cuarentena/alertas | Remediado(código/IaC) | Cuarentena durable (condicional, verificada) + alarmas DLQ (ronda 1) | test_06/07/11 PASS |
| **NEW-H5** | Heartbeat no cubría el fan-out; borrado inseguro | Remediado(código) | Heartbeat envuelve TODO el procesamiento; **fallo de visibilidad → abortar sin borrar**; `DeleteMessage` solo con resultado durable completo | test_08/12/13 PASS |
| **NEW-M1** | Referencia inequívoca al RAW | Remediado(código) | Cada marker lleva bucket, key, **VersionId**, sha256, size, tipo, event_id, recipient_ref | test_15 PASS |
| **NEW-M2** | Validación de schema SES; bucket ajeno | Remediado(código) | `validate_notification` estricta; bucket≠configurado o key fuera de prefijo → **cuarentena**; nunca MIME | test_11 PASS |
| **P5** | IAM user → rol asumible; deps; prefijos; email confirm | Remediado(IaC) | `aws_iam_role.worker` (STS, `max_session_duration`); `check` de prefijos; `depends_on` (SSE, policies, activación final); output de confirmación de email | terraform validate PASS |

## Verificaciones ejecutadas (evidencia reproducible, ronda 2)
```
python3 tests/test_poc.py                         → Ran 15 tests — OK  (12 escenarios + manifest-fail + concurrencia + raw-ref)
python3 poc_smoke_test.py                         → complete=1, orphan=1, quarantine=1 (E2E con fakes)
python3 -m py_compile (worker,reconcile,smoke,fakes,test) → PASS
terraform v1.9.8 (binario local; sin tocar AWS):
  terraform fmt -check -diff                       → exit 0 (sin cambios)
  terraform init -backend=false                    → OK (hashicorp/aws v5.100.0)
  terraform validate                               → "Success! The configuration is valid." (exit 0)
  terraform plan                                   → NO ejecutado (requiere credenciales sandbox autorizadas)
scan de secretos                                   → sin secretos
```
> Las notas "terraform validate NO ejecutado" de la ronda 1 quedan **superadas**: en esta ronda
> se ejecutó `validate` real (PASS). `plan` sigue pendiente de credenciales sandbox.

## Condiciones que SIGUEN requiriendo AWS real (no verificables sin sandbox)
1. `terraform plan`/`apply` contra la cuenta sandbox (credenciales autorizadas).
2. **Orden S3-antes-de-aceptación-SMTP** y **resultado SMTP** ante éxito/AccessDenied/fallo KMS/
   error de almacenamiento (P1).
3. Que **SES publique a un SNS cifrado con CMK** con la key policy dada (`# VERIFY` en `main.tf`).
4. Entrega real **SNS→SQS** y DLQ de suscripción ante fallo (P3/P4 con infra real).
5. Confirmación efectiva de la **suscripción de email** de las alarmas.
6. Comportamiento real de **>40 MB** (rebote) y límites por región/configuración SES.
7. Aislamiento **C4-B1 + RLS** (fuera del alcance de esta PoC; integración posterior).
8. Costos reales medidos.

## Ronda 3 — bloqueantes finales (reauditoría de `38e96d6`)

| Prioridad | Fix | Evidencia (test/validate) |
|---|---|---|
| 1 Carrera Head/Get | HeadObject fija `VersionId` y el GetObject lee **esa** versión (consistencia intra-invocación) | `test_12_version_pinned_no_race` |
| 2 Conflictos | Marker `conflict/v2` **append-only** con locators COMPLETOS de **canonical y observed**; no se confunde con `completed` ni se sobrescribe | `test_02_conflict_full_locators` |
| 3 Cuarentena global | Eliminada `quarantine/unknown.json`: identidad propia por notificación (messageId válido o `raw-<digest>`) | `test_14_quarantine_independent_identity` |
| 4 Cuarentena+alerta en reconcile | `poc_reconcile.py` escribe cuarentena **durable** de orphans (condicional) y emite **alerta accionable** (sink inyectable → SNS en real) | `test_05_sns_lost_orphan_quarantined_and_alerted` |
| 5 Comparación de manifest | En `exists`, se compara ÍNTEGRO (expected + object.key); mismatch → cuarentena `manifest_mismatch` durable | `test_13_manifest_mismatch` |
| 6 Heartbeat | Cierre con `join`; **verificación final** de `hb.failed` antes de confirmar; fallo asíncrono real aborta sin borrar | `test_08b_heartbeat_async_failure`, `test_08_*` |
| 7 Concurrencia | Pruebas con **8 hilos simultáneos** (un único `completed`) y fallo asíncrono | `test_15_concurrency_real_threads` |
| 8 Terraform | Principal STS **obligatorio y específico** (sin root, validación); `check` de prefijos; `depends_on` (SSE/activación); outputs de confirmación de email | `terraform validate` PASS |
| Aceptación | NUNCA True/DeleteMessage sin terminal durable preservado | `test_17_acceptance_no_delete_without_durable` |

**Verificaciones ejecutadas (ronda 3, reales):**
```
python3 tests/test_poc.py            → Ran 18 tests — OK
python3 poc_smoke_test.py            → complete/orphan(+cuarentena durable+alerta)/quarantine
terraform v1.9.8 (local, sin AWS): fmt -check exit 0 · validate "Success! valid." · plan NO ejecutado
```

## Commit final para reauditoría
Ver el commit de esta remediación en la rama `docs/adr-050-draft` del PR #1 (no merge). Auditar
con `CODEX_AUDIT_PROMPT.md`. **C4B3-01 NO se declara cerrado**: requiere ejecutar la PoC (P1–P5)
con evidencia real y una nueva auditoría independiente.
