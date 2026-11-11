# Prompt de auditoría Codex — PoC C4-B3 / C2 (SES → S3)

**Rol:** auditor independiente de seguridad e infraestructura. **No** implementes ni apruebes;
audita el **diseño y la IaC** de una PoC **no productiva, no aplicada**.

**Alcance a auditar (en `spikes/c4b3-c2-ses-s3/` del PR #1):**
- `terraform/` (`versions.tf`, `variables.tf`, `main.tf`, `outputs.tf`) — IaC NO aplicada.
- `poc_worker.py` — consumidor SQS de prueba.
- `README.md` — paquete de aprobación, inventario, plan P1–P5.
- Docs de contexto: `docs/design/C4-B3-C2-SES-feasibility.md`, `docs/design/C4-B3-01-evidence-durability.md`.

**Contexto:** resolver el CRITICAL **C4B3-01** (preservar la evidencia primaria en
almacenamiento propio antes de aceptar el correo). Diseño: SES receipt rule → acción S3 (MIME
crudo) + notificación **SNS nativa** (recipients + objectKey) → **SQS** (sin Lambda) → worker.

## Preguntas de auditoría obligatorias

### A. Recuperación y pérdida de datos
1. ¿El objeto S3 queda durable **antes** de cualquier procesamiento? ¿El worker lo confirma?
2. Si la acción S3 **tiene éxito** pero la **notificación SNS se pierde**: ¿la reconciliación
   descubre el objeto? ¿Los `receipt.recipients` son recuperables de forma **autoritativa** sin
   usar cabeceras MIME? Si **no** lo son, ¿la **cuarentena + alerta** es la respuesta correcta o
   hay un camino mejor? ¿Es un hallazgo bloqueante?
3. ¿Qué ocurre si SES no puede escribir en S3 (permisos/KMS/>40 MB)? ¿Se rebota al remitente
   (no aceptación)? ¿Hay algún camino de **falsa aceptación**?

### B. Permisos AWS (least privilege)
4. Revisa la **key policy KMS** (root + SES `GenerateDataKey*` con SourceAccount/SourceArn), la
   **bucket policy** (TLS-only + SES `PutObject` con SourceAccount/SourceArn) y la **IAM del
   worker** (`GetObject`/`ListBucket`/SQS/`Decrypt`). ¿Hay privilegios excesivos? ¿Falta alguno
   que haga fallar el flujo (p. ej. el worker no puede descifrar)?
5. ¿Las condiciones `AWS:SourceArn` (ARN de la receipt-rule) son correctas y suficientes para
   impedir *confused deputy*?
6. ¿El uso de **SSE-KMS server-side** (no la message-encryption client-side de SES) es coherente
   con un worker Python? ¿Se evita la trampa del cliente de cifrado Java/Ruby?

### C. Terraform
7. Dependencias/orden: ¿la bucket policy, la key policy y la SNS topic policy existen **antes**
   de crear la receipt rule? ¿Hay ciclos? ¿`terraform validate` pasaría? (no se pudo ejecutar
   aquí; ver README §C-validaciones).
8. Aislamiento del sandbox, `force_destroy`, ventana de borrado de la CMK, y **teardown
   reproducible**: ¿`terraform destroy` deja la cuenta limpia? ¿Qué pasos manuales quedan (MX/TXT,
   access key)?
9. ¿El `AWS Budgets` está bien entendido como **alerta, no límite** de gasto? ¿Falta algún
   control de costos?

### D. SQS e idempotencia
10. ¿El manejo de **visibility timeout**, DLQ (`maxReceiveCount`) y `DeleteMessage` evita
    pérdida y duplicación? ¿El worker es **idempotente** ante re-entrega y caída a mitad?
11. ¿La política de la cola permite **solo** a este SNS enviar? ¿`raw_message_delivery` está
    correctamente asumido en el parseo del worker?

### E. Aislamiento multitenant
12. ¿La autoridad de tenant es **exclusivamente** `receipt.recipients` (sobre SES)? ¿Se
    demuestra que una cabecera MIME `To:` falsificada **no** reenruta?
13. ¿El fan-out multi-empresa garantiza **copia/captura por tenant** sin exponer evidencia
    cross-tenant? ¿Se preservan las garantías de C4-B1?
14. ¿El logging evita PII/secretos?

## Formato de salida
Hallazgos clasificados **CRITICAL / HIGH / MEDIUM / LOW** con: descripción, archivo/línea,
impacto, escenario de fallo y remediación propuesta. Veredicto **PASS/FAIL** para autorizar el
aprovisionamiento de la PoC. **No** declares C4B3-01 cerrado: eso requiere ejecutar la PoC y una
auditoría posterior de resultados.
