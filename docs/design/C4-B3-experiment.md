# C4-B3 — Experimento de decisión: Resend (captura síncrona) vs. AWS SES→S3

> **Estado:** DISEÑO DE EXPERIMENTO APROBADO POR EL TITULAR (GO del 2026-11-13) ·
> ejecución **pendiente de insumos** (§8). **No es implementación de producción.**
> El checkpoint C4-B3 queda reformulado: antes de implementar se decide la
> arquitectura de captura durable **con datos reales**, no sobre papel.
>
> Gobierno: PR #1 en DRAFT · ADR-047/049 ACCEPTED e intactos · ADR-050/016 DRAFT ·
> cero cambios en `backend/` · `terraform apply` requiere GO explícito del titular ·
> **Mailgun queda FUERA del experimento** (decisión del titular, 2026-11-13; sigue
> siendo fallback validado de C4-B0).

## 0. Registro de auditoría — PoC AWS

**Codex dio PASS sobre `81fe67e`** (quinta ronda de remediación del spike
`spikes/c4b3-c2-ses-s3`) **para avanzar a la revisión de Terraform Plan**
(registrado aquí por instrucción del titular, 2026-11-13). El PASS cubre la PoC
local (25 tests con fakes, fail-closed, manifest estricto) y la IaC validada
sin AWS; **no** cubre C4B3-01, que sigue abierto hasta tener evidencia real
(P1–P5) y reauditoría.

## 1. Pregunta de decisión

¿Qué arquitectura garantiza mejor, con evidencia empírica, la invariante de
ADR-047 —**captura durable síncrona de la evidencia antes del ACK**— al costo
operativo que el MVP puede pagar?

- **Brazo A — AWS SES→S3** (`spikes/c4b3-c2-ses-s3`): SES escribe el MIME crudo
  en S3 propio antes de notificar; hipótesis central a probar: *sin escritura S3
  no hay aceptación SMTP* (hoy `PENDIENTE DE PRUEBA`, hallazgos H5/H6).
- **Brazo B — Resend captura síncrona pre-ACK** (`spikes/c4b3-resend-sync-capture`):
  dentro del presupuesto del webhook se descarga el RAW vía API y se persiste
  durable **antes** del 2xx; fallo → non-2xx → reintento Svix. Hipótesis: el caso
  dominante (XML fiscal, PDFs pequeños) cabe holgado en el presupuesto y el techo
  real de tamaño/retención/reintentos es operable.

## 2. Infraestructura del experimento

| | Brazo A (AWS) | Brazo B (Resend) |
|---|---|---|
| Dominio | `ses.<DOMINIO>` (MX → SES us-east-1) | `resend.<DOMINIO>` (inbound Resend) |
| Receptor | worker PoC (SQS long-poll) | `receiver.py` en Render efímero |
| Evidencia | S3 (`inbound-raw/` + `markers/`) | disco del servicio (`capturas/`) + descarga vía `/capturas/*` |
| IaC | Terraform del PoC (plan → revisión del titular → apply con su GO) | alta manual mínima (dominio inbound + webhook) |

`<DOMINIO>` = dominio desechable que el titular compra en Route 53 (cuenta
sandbox). Email de alarma de presupuesto AWS: `facturaspixdea@gmail.com`.
**Nunca `tribuu.ai`. Solo correos sintéticos; ningún comprobante de terceros.**

## 3. Matriz de casos (idéntica en ambos brazos)

| Caso | Correo sintético | Qué se mide |
|---|---|---|
| **T1** | XML fiscal sintético ~50 KB | t(SMTP→durable) p50/p95 · hash reproducible |
| **T2** | XML + PDF ~5 MB | ídem · presupuesto síncrono del brazo B |
| **T3** | adjuntos ~20 MB · ~35 MB · ~45 MB | techo real por proveedor (SES: rebote >40 MB esperado; Resend: comportamiento NO documentado — se mide) · ¿cabe 35 MB pre-ACK? |
| **T4** | duplicados (reenvío + reintento forzado) | una sola captura; idempotencia por `messageId` / marker `email_id` |
| **T5** | **fallo inducido en la captura** — A: revocar permiso S3 / romper KMS → **código SMTP real observado** (¿rebote o aceptación silenciosa?) · B: `SPIKE_FAIL_MODE=http500` → calendario real de reintentos; `hang200` → timeout efectivo (¿15 s o 30 s?) | la garantía central de cada arquitectura |
| **T6** | dos buzones + MIME `To:` falsificado · pérdida de notificación — A: borrar mensaje SQS → `poc_reconcile.py` → cuarentena · B: endpoint caído y luego **Replay/Recover Failed** del portal Svix + `GET /emails/receiving` como backstop | autoridad del sobre · recuperación sin autoridad |

**Sonda de retención (solo brazo B, en paralelo):** correo en día 0 →
`probe_retention.py` diario → acota la retención efectiva (observado ≥17 d en
C4-B0; contractual NO VERIFICADO) y si `raw.download_url` es re-emitible tras
caducar. Duración: 2–3 semanas calendario; no bloquea el resto de casos.

## 4. Métricas y registro

Por caso y brazo: timestamp de envío SMTP · instante de evidencia durable ·
latencias parciales (brazo B: `timings_ms` api/download/total del marker) ·
código SMTP o HTTP observado · bytes y SHA-256 · filas de reintento
(`attempts.jsonl` / redrives SQS) · resultado PASS/FAIL/**PENDIENTE** (nunca se
declara PASS lo no probado — regla del PoC AWS, se mantiene). Evidencia en JSONL
descargada antes de cualquier teardown; resumen en este doc al cierre.

## 5. Criterios de decisión (pactados antes de medir)

1. **Si T5-A demuestra** que sin S3 no hay aceptación SMTP → C2 resuelve C4B3-01
   de raíz; la decisión pasa a costo/complejidad/ADR-011 contra los números de B.
2. **Si T5-A muestra aceptación silenciosa**, la ventaja estructural de C2 cae y
   pesa su complejidad → favorece B si T1–T3-B caben en presupuesto.
3. **Si T1/T2-B caben con margen** (p95 ≪ presupuesto) y T3-B da un techo
   operable con contrato honesto para la cola grande (Híbrido A+B de
   `C4-B3-01-evidence-durability.md`) → B es suficiente para el MVP.
4. Retención/replay de Resend sin respuesta documental ni empírica aceptable →
   punto para A (independencia de retención externa).
5. El resultado alimenta ADR-050 (backend de evidencia) y, si gana A, la
   revisión formal de ADR-047 — **ninguno se toca sin decisión del titular**.

## 6. Verificación documental de Resend (2026-11-13)

Fuentes oficiales consultadas hoy; lo no documentado queda **NO VERIFICADO** y
pasa a §6.1.

| Pregunta | Resultado | Fuente |
|---|---|---|
| ¿RAW MIME completo disponible? | **VERIFICADO**: `GET /emails/receiving/{id}` → `raw.download_url` (URL firmada CloudFront, «todos los adjuntos») + `expires_at` (ejemplo ≈1 h) | [Retrieve Received Email](https://resend.com/docs/api-reference/emails/retrieve-received-email) |
| ¿El webhook trae el cuerpo? | **VERIFICADO**: no; webhooks excluyen cuerpo y adjuntos; se obtienen por API (modelo de 2 pasos confirmado) | [Get Email Content](https://resend.com/docs/dashboard/receiving/get-email-content) |
| Calendario de reintentos | **VERIFICADO (Svix)**: inmediato · 5 s · 5 min · 30 min · 2 h · 5 h · 10 h · 10 h (ventana ≈ 28 h) | [Svix Retries](https://docs.svix.com/retries) |
| Timeout de entrega | **DISCREPANCIA**: Svix publica «30 s»; la evidencia previa del repo (C4-B3-01) registra 15 s verificados. **Se mide en T5 (`hang200`)** y se pregunta a soporte | [Svix Retries](https://docs.svix.com/retries) · docs/design/C4-B3-01 §2 |
| Auto-deshabilitado del endpoint | **VERIFICADO (Svix)**: solo tras ~5 días de fallos sostenidos (con condiciones), con evento operacional `EndpointDisabledEvent` — la estrategia non-2xx del brazo B no muere por unas horas de fallo | [Svix Retries](https://docs.svix.com/retries) |
| Replay manual | **VERIFICADO**: «Replay any webhook event»; portal Svix: *Recover Failed* y *Replay Missing* | [Webhooks Introduction](https://resend.com/docs/dashboard/webhooks/introduction) · [Svix Retries](https://docs.svix.com/retries) |
| Backstop por listado | **VERIFICADO**: `GET /emails/receiving` (paginación por cursor) lista lo recibido por el equipo → reconciliación posible ante webhook perdido | [List Received Emails](https://resend.com/docs/api-reference/emails/list-received-emails) |
| Rate limit API | **VERIFICADO**: 10 req/s por equipo (todas las keys), 429 al exceder, ampliable a petición — cota para el fetch síncrono bajo ráfaga | [API Introduction](https://resend.com/docs/api-reference/introduction) |
| **Retención del correo entrante** | **NO VERIFICADO** (ninguna cifra pública) → soporte + sonda | — |
| **Techo de tamaño inbound** | **NO VERIFICADO** (el 40 MB conocido es de envío; solo hay una nota de HTML inline >100 MB) → soporte + T3 | — |
| **¿`download_url` re-emitible tras caducar?** | **NO VERIFICADO** → soporte + sonda | — |
| **¿RAW = RFC822 original byte a byte (hash estable)?** | **NO VERIFICADO** → T1/T4 + sonda `--full` | — |
| **Región/ubicación del almacenamiento; API de borrado; keys de solo-lectura** | **NO VERIFICADO** (endpoint único `api.resend.com`, sin doc regional) → soporte | — |

### 6.1 Preguntas para soporte de Resend (respuesta por escrito)

1. ¿Cuál es el **período de retención** de un correo entrante y sus adjuntos?
   ¿Es contractual o best-effort? ¿Puede ampliarse?
2. ¿Cuál es el **tamaño máximo** de un correo entrante (incl. adjuntos)? ¿Qué
   ocurre exactamente al excederlo (rebote SMTP, truncado, descarte)?
3. ¿El `raw.download_url` caducado se **re-emite** con cada `GET
   /emails/receiving/{id}`? ¿Hasta cuándo?
4. ¿El fichero RAW descargado es el **RFC822 original sin modificar** (hash
   estable entre descargas)?
5. ¿Cuál es el **timeout** exacto para responder 2xx al webhook (15 s vs 30 s)?
6. ¿**Dónde** (región/proveedor) se almacena el correo entrante? ¿Existe API de
   **borrado** de un correo recibido?
7. ¿Existen API keys de **solo lectura** (scope Receiving) para no desplegar una
   key de acceso total en el receptor?

## 7. Teardown del spike viejo de Render (C4-B0) — previo al despliegue del brazo B

- [ ] Descargar la evidencia restante (`/capturas/*.jsonl`, cuerpos) si queda alguna.
- [ ] Borrar el servicio `tribuu-spike-inbound` en Render.
- [ ] Revocar/invalidar el `RESEND_WEBHOOK_SECRET` del spike viejo (ya rotado
      tras el incidente; confirmar que el valor viejo no sigue configurado en
      ningún endpoint de Resend) y eliminar el endpoint de webhook antiguo.
- [ ] Registrar fecha de teardown en este doc.

## 8. Insumos pendientes del titular (bloquean la ejecución, no la preparación)

| # | Insumo | Estado |
|---|---|---|
| 1 | `<DOMINIO>` desechable comprado en Route 53 (sandbox) | ⏳ |
| 2 | Credenciales sandbox para `terraform plan` (el plan completo se le muestra; **apply solo con su GO aparte**) | ⏳ |
| 3 | API key de Resend dedicada + `RESEND_WEBHOOK_SECRET` nuevo | ⏳ |
| 4 | GO de despliegue del brazo B en Render (tras teardown §7) | ⏳ |

## 9. Estado de ejecución

| Hito | Estado |
|---|---|
| Spike brazo B escrito y probado localmente (18/18, fakes) | ✅ 2026-11-13 |
| Verificación documental Resend | ✅ 2026-11-13 (§6) |
| Preguntas a soporte de Resend | REDACTADAS (§6.1) — envío pendiente |
| `terraform plan` del brazo A | ⏳ bloqueado por §8.2 |
| Casos T1–T6 | NO EJECUTADOS |
| Sonda de retención | NO INICIADA |
| Decisión final + ADR-050/047 | PENDIENTE del experimento |
