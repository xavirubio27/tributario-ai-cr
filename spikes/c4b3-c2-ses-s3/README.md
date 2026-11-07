# Spike C4-B3 / C2 — AWS SES → S3 (PoC aislada)

> **PoC NO PRODUCTIVA.** Investiga la resolución del hallazgo CRITICAL **C4B3-01**
> (durabilidad de la evidencia primaria antes de aceptar el correo). **No es implementación
> productiva.** El PR #1 sigue DRAFT; no se tocan ADR aceptados; no se modifica el sistema
> productivo.
>
> **IaC NO APLICADA.** Este directorio contiene Terraform reproducible **que todavía NO se ha
> ejecutado**. Requiere `terraform init/validate/plan` por el propietario y, **antes de
> `apply`, aprobación explícita del inventario y el presupuesto** (ver §A). **Ninguna persona
> de Claude Code puede aprovisionar esto**: no hay credenciales AWS, ni cuenta, ni control de
> DNS en el entorno. Lo aplica y ejecuta el **propietario** en su cuenta sandbox.
>
> **Datos:** solo correos **sintéticos**. Prohibido usar documentos fiscales reales o datos
> personales de clientes.

---

## A. Paquete de aprobación previo al aprovisionamiento (requerido antes de crear recursos)

### A.1 Cuenta y dominio (a completar/confirmar por el propietario)
- **Cuenta AWS sandbox autorizada:** `<ACCOUNT_ID a indicar por el propietario>` (NO la cuenta
  productiva).
- **Subdominio desechable bajo control del propietario:** `<p.ej. poc-inbox.ejemplo-test.xyz>`
  — **NUNCA `inbox.tribuu.ai`** ni DNS productivo.
- **Región:** `us-east-1` (autorizada).

### A.2 Inventario de recursos (lo que la IaC crearía)
| Recurso | Propósito | Costo recurrente |
|---|---|---|
| KMS CMK + alias | SSE-KMS del bucket (cifrado en reposo) | **$1/mes** |
| S3 bucket (`…-poc-inbound-raw`) + public-access-block + SSE-KMS + versioning + lifecycle(expira 7 d) | Copia durable del MIME crudo | ~$0 (volumen PoC) |
| SQS cola + DLQ | Notificación durable al worker | free tier |
| Lambda (`enqueue`) + log group | Lee `receipt.recipients`, escribe sidecar, encola | free tier |
| SES receipt rule set + rule + domain identity | Recepción → acción S3 + acción Lambda | $0.10/1k + chunks (PoC: céntimos) |
| IAM: rol Lambda, usuario worker PoC (scoped) | Permisos mínimos | $0 |
| CloudWatch alarmas + AWS Budgets | Control de costos y errores | $0–$0.10 |

### A.3 Costo máximo previsto y presupuesto
- **Costo máximo previsto de la PoC: < $5** (dominado por $1/mes de la CMK; uso sintético
  trivial; egress gratis <100 GB).
- **AWS Budget (guardrail): `var.monthly_budget_usd` = $10/mes**, con **alarmas al 50 % / 80 %
  / 100 %** por SNS/email al propietario. Supera ese tope ⇒ revisar/parar.
- La autorización arquitectónica **no** es aprobación de gasto ilimitado: cualquier recurso
  adicional o aumento del tope requiere nueva aprobación.

### A.4 Plan de rollback / eliminación
- `terraform destroy` elimina todo. El bucket usa `force_destroy=true` (PoC) para poder
  destruirse con objetos. La **CMK** entra en ventana de borrado (7–30 días; se usa 7).
- **DNS/MX:** el registro MX del subdominio y el TXT de verificación los **añade y elimina el
  propietario manualmente** (si el DNS no está en Route53). No se tocan registros productivos.
- Checklist de teardown en §D.

### A.5 Identidades y permisos requeridos
- **Para aplicar la IaC:** un principal del **sandbox** con permisos de administración de
  S3/KMS/SQS/Lambda/SES/IAM/Budgets/CloudWatch (deployer de la PoC). No productivo.
- **Worker de la PoC:** un **usuario IAM scoped** (`s3:GetObject` del prefijo, `sqs:Receive/
  DeleteMessage`, `kms:Decrypt` de la CMK) — **solo PoC**, con access key de corta vida que se
  **elimina en el teardown**. Nunca productivo, nunca en el repo.

> **Acción solicitada al orquestador/propietario:** aprobar A.1–A.5 (cuenta, subdominio,
> inventario, presupuesto $10, identidades) **antes** de cualquier `terraform apply`.

---

## B. Terraform (en `./terraform`)
Estructura: `versions.tf`, `variables.tf`, `main.tf`, `outputs.tf`, `lambda/enqueue.py`.
Flujo previsto (por el propietario, **tras** la aprobación A):
```
cd terraform
terraform init
terraform validate
terraform plan -var='subdomain=poc-inbox.ejemplo-test.xyz' -var='monthly_budget_usd=10'
# REVISAR el plan y los costos ⇒ si OK y aprobado:
terraform apply   # <-- solo tras aprobación explícita del inventario/presupuesto
# añadir manualmente el MX/TXT del subdominio (ver outputs) en el DNS del propietario
# ... ejecutar pruebas P1–P5 ...
terraform destroy # teardown
```
> La IaC es un **borrador revisable**; debe pasar `terraform validate`/`plan` en el entorno del
> propietario antes de `apply`. Marcadores `# VERIFY` señalan puntos a confirmar.

---

## C. Plan de pruebas obligatorias (PASS/FAIL)

### P1 — Durabilidad
- Enviar un correo sintético con adjunto → **PASS** si el objeto MIME crudo aparece íntegro en
  S3; `HeadObject` da tamaño/etag; el worker calcula **SHA-256** y recupera los bytes idénticos.
- **Simular fallo de escritura S3** (quitar temporalmente el permiso `s3:PutObject` del rol de
  SES) y enviar → registrar el **resultado SMTP real** (se espera **rebote/5xx al remitente**).
  **PASS** si NO se acepta silenciosamente.

### P2 — Seguridad multitenant
- Dos buzones de empresas simuladas (`emp-a-…@`, `emp-b-…@` del subdominio) → cada evidencia
  va al tenant correcto resuelto desde `receipt.recipients` (SES), con copia por tenant.
- **Falsificar la cabecera MIME `To:`** (apuntando a la otra empresa) → **PASS** si el
  enrutado usa el **sobre SES**, no el MIME, y **no se expone** evidencia entre empresas.

### P3 — Recuperación / reconciliación
- **Simular pérdida de notificación** (borrar el mensaje SQS sin procesar) → el **barrido**
  descubre el objeto S3 pendiente vía el **sidecar `.meta.json`**. **PASS** si se procesa.
- **Sin `.meta.json`:** demostrar cómo recuperar el enrutado original. Si **no** es demostrable
  de forma fiable (el MIME no es autoridad de sobre) → **registrar HALLAZGO BLOQUEANTE** y
  proponer mitigación (p. ej. hacer el sidecar transaccional con la escritura S3, o derivar de
  logs SES/CloudTrail). Documentar el resultado real.

### P4 — Fallos e idempotencia
- **Notificaciones duplicadas** (reencolar el mismo mensaje) → una sola captura (idempotencia
  por `messageId`). **Caída del worker** a mitad → al reiniciar, el lease/visibility-timeout de
  SQS devuelve el mensaje y se recupera sin duplicar ni perder. **Mensajes grandes**: probar
  tamaños crecientes y el **límite 40 MB** (se espera rebote por encima).

### P5 — Seguridad y operaciones
- Verificar: políticas **IAM/KMS mínimas**, **Block Public Access**, cifrado **SSE-KMS**
  (descifrado por el worker **Python**, confirmando que NO se usó la client-side encryption de
  SES), **logs sin PII**. Medir **memoria/latencia** del worker y **costos reales** de la PoC.
  Validar que **`terraform destroy`** deja la cuenta limpia (teardown reproducible).

---

## D. Checklist de teardown
- [ ] `terraform destroy` OK (bucket vaciado por `force_destroy`).
- [ ] Access key del usuario worker PoC **eliminada**.
- [ ] CMK programada para borrado (ventana 7 d).
- [ ] **MX/TXT del subdominio eliminados** del DNS del propietario.
- [ ] Confirmar $0 de recursos residuales en Cost Explorer / Budgets.

---

## E. Entregable final de la PoC
Informe **PASS/FAIL** por prueba, evidencia (capturas/logs sintéticos), **costos reales**,
riesgos residuales y **recomendación de adopción**. Después → **nueva auditoría Codex** para
decidir si **C4B3-01** puede cerrarse. **No** se declara cerrado sin esa auditoría; **no** hay
merge ni cambios productivos.

## F. Gobierno
PR #1 en DRAFT · ADR aceptados intactos · ADR-047/050/016 en DRAFT · sin merge · **IaC no
aplicada** · sin recursos facturables hasta aprobar A · sin DNS productivo · sin datos
reales/PII · teardown reproducible.
