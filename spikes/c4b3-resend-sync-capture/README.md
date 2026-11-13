# Spike C4-B3 — Brazo Resend: captura síncrona pre-ACK (experimento de decisión)

> **SPIKE NO PRODUCTIVO.** Es el **brazo Resend** del experimento de decisión de C4-B3
> (ver [docs/design/C4-B3-experiment.md](../../docs/design/C4-B3-experiment.md)): mide si la
> **Alternativa A/Híbrido** del análisis C4B3-01 —RAW durable **antes** del 2xx, regla de
> ADR-047— es viable con Resend y con qué límites reales. **Solo datos sintéticos.**
> No toca `backend/`, ni migraciones, ni ADR. PR #1 en DRAFT.

## Qué implementa

```
Resend ──POST firmado (Svix)──▶ /webhooks/resend
  1) verificación de firma sobre el RAW body ANTES de parsear (firmas.py, esquema
     confirmado en vivo en C4-B0)                       inválida → 401, sin efectos
  2) type != email.received → 200 "ignorado"
  3) marker existente para data.email_id → 200 "duplicado" (sin re-fetch)
  4) captura síncrona (captura.py) con presupuesto SPIKE_SYNC_BUDGET_SECONDS:
       GET /emails/receiving/{id} → raw.download_url (HTTPS, host en allowlist
       CloudFront, redirects PROHIBIDOS) → descarga en streaming A DISCO con
       tope SPIKE_MAX_RAW_BYTES → SHA-256 → blob + marker con fsync
  5) todo durable → 200 {capturado, sha256, timings}; cualquier fallo → 500
     (Svix reintenta; ésa es la semántica bajo prueba)
```

**El 2xx significa «RAW bajo control propio», o no se emite.** No hay estados parciales
visibles: el marker sólo existe si el blob quedó durable; los temporales se limpian en
todo camino de error (fijado por tests 05/06/07).

**Ledger `capturas/attempts.jsonl`**: una fila por entrega **auténtica** (svix-id,
svix-timestamp, outcome, status, duración). La serie de filas bajo fallo inducido **es la
medición** del calendario real de reintentos de Svix/Resend y del timeout efectivo.

## Diferencia deliberada con C4-B0

En C4-B0 la regla era «en la nube jamás viven API keys de proveedor». Aquí la
**`RESEND_API_KEY` SÍ vive en el servidor**: el fetch síncrono pre-ACK la necesita, y
evaluar esa superficie es parte del experimento. Mitigación: key dedicada sólo a este
experimento y **rotación en el teardown**. Pregunta abierta a soporte: ¿existen keys de
sólo-lectura para Receiving? (hoy NO VERIFICADO).

## Modos de fallo inducido (T5) — siempre tras firma válida

| `SPIKE_FAIL_MODE` | Comportamiento | Qué mide |
|---|---|---|
| `none` | normal | caso base |
| `http500` | 500 sin capturar | calendario completo de reintentos; umbral de auto-deshabilitado del endpoint |
| `hang200` | duerme `SPIKE_HANG_SECONDS` y responde 200 | timeout efectivo del webhook (¿15 s o 30 s?): si aun así llega reintento, la entrega caducó antes de la pausa |

## Variables de entorno

| Variable | Default | Nota |
|---|---|---|
| `RESEND_WEBHOOK_SECRET` | — | obligatoria en público; formato `whsec_` estricto |
| `RESEND_API_KEY` | — | obligatoria en público; key dedicada, rotar en teardown |
| `SPIKE_READ_TOKEN` | — | obligatoria en público; Bearer de `/capturas/*` |
| `RESEND_API_BASE` | `https://api.resend.com` | en tests apunta al fake |
| `SPIKE_SYNC_BUDGET_SECONDS` | `10` | presupuesto total de captura pre-ACK |
| `SPIKE_MAX_RAW_BYTES` | `50331648` (48 MiB) | tope de descarga (T3 explora el techo real) |
| `SPIKE_ALLOWED_DOWNLOAD_HOSTS` | `cloudfront.net` | sufijos permitidos del download_url |
| `SPIKE_MAX_CONCURRENT_REQUESTS` | `2` | semáforo global; sin capacidad → 503 |
| `SPIKE_FAIL_MODE` / `SPIKE_HANG_SECONDS` | `none` / `45` | tabla anterior |
| `SPIKE_STORE_DIR` | `capturas` | blobs/markers/ledger |
| `SPIKE_BIND_PUBLIC` | — | `1` activa 0.0.0.0 y la validación fail-fast |

## Cómo correr las pruebas locales (sin red, sin Resend)

```
cd spikes/c4b3-resend-sync-capture
python3 tests/test_spike.py        # 18 tests, fakes stdlib
```

Resultado real (2026-11-13): **Ran 18 tests — OK**.

## Despliegue efímero en Render (brazo del experimento)

Igual que el receptor de C4-B0: servicio web Python sin dependencias
(`python3 receiver.py`), `SPIKE_BIND_PUBLIC=1` + las env obligatorias. Endpoint estable
para que los reintentos de Svix sean medibles. **Antes de desplegar este spike se ejecuta
el teardown del spike viejo de C4-B0** (checklist en el doc del experimento §7).

## Sonda de retención (`probe_retention.py`)

```
RESEND_API_KEY=... python3 probe_retention.py --email-id <id> [--full]
```

Una corrida diaria por email sondeado añade una fila a `retention.jsonl`. El primer día
en que la API deje de devolver el correo acota la **retención efectiva** (hoy NO
VERIFICADO; observado ≥17 d en C4-B0); si `raw.download_url` reaparece firmada tras
caducar, la URL es **re-emitible** y la ventana de recuperación es la del email.

## Evidencia a descargar antes de cualquier restart/teardown

`/capturas/attempts.jsonl` · `/capturas/markers/<email_id>.json` ·
`/capturas/blobs/<sha256>.eml` (Bearer `SPIKE_READ_TOKEN`). El filesystem de Render es
efímero: descargar tras cada tanda de casos.

## Gobierno

Spike desechable bajo `spikes/`; cero cambios en `backend/`; ADR-047/049 intactos;
ADR-050/016 siguen DRAFT. El GO de implementación de C4-B3 sólo puede salir del
experimento documentado en `docs/design/C4-B3-experiment.md`, no de este spike.
