"""Receptor del brazo Resend — experimento de decision C4-B3. NO es produccion.

Captura sincrona pre-ACK (ver captura.py): el 2xx SOLO se devuelve con el RAW
ya durable en disco. Fallo de captura -> 500 -> Svix reintenta. SOLO stdlib.

Endpoints:
  POST /webhooks/resend          firma Svix ANTES de parsear; luego captura
  GET  /salud                    publico; 200; fuera del semaforo
  GET  /capturas/attempts.jsonl  Bearer SPIKE_READ_TOKEN (ledger de intentos)
  GET  /capturas/markers/<email_id>.json   Bearer
  GET  /capturas/blobs/<sha256>.eml        Bearer

El LEDGER attempts.jsonl registra cada entrega AUTENTICA (firma valida) con
svix-id, timestamp de Svix, tipo, outcome y duracion: es el instrumento que
mide el calendario real de reintentos (T5) y el timeout efectivo (15 vs 30 s).
Firma invalida -> 401 con metadata minima y SIN fila en el ledger (por diseño:
el ledger mide el comportamiento del proveedor, no el ruido de Internet).

Modos de fallo inducido (T5), SIEMPRE tras verificar la firma:
  SPIKE_FAIL_MODE=none     comportamiento normal (default)
  SPIKE_FAIL_MODE=http500  responde 500 sin capturar (mide reintentos Svix)
  SPIKE_FAIL_MODE=hang200  duerme SPIKE_HANG_SECONDS y responde 200 (si aun
                           asi llega reintento, el timeout efectivo < pausa)

Difiere a proposito de C4-B0: la API key de Resend SI vive en el servidor,
porque el fetch sincrono pre-ACK la necesita — es parte de lo que se evalua.
Mitigacion: key dedicada al experimento, rotacion en el teardown.
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import captura
import firmas

MAX_WEBHOOK_BODY = 1024 * 1024          # el webhook de Resend es metadata (~KB)
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class Settings:
    """Configuracion del receptor; `validate_public` aborta si falta algo."""

    def __init__(self, env: dict[str, str]):
        self.webhook_secret = env.get("RESEND_WEBHOOK_SECRET", "")
        self.read_token = env.get("SPIKE_READ_TOKEN", "")
        self.fail_mode = env.get("SPIKE_FAIL_MODE", "none")
        self.hang_seconds = float(env.get("SPIKE_HANG_SECONDS", "45"))
        self.max_concurrent = int(env.get("SPIKE_MAX_CONCURRENT_REQUESTS", "2"))
        self.store_dir = env.get("SPIKE_STORE_DIR", "capturas")
        self.capture = captura.Config(
            api_base=env.get("RESEND_API_BASE", "https://api.resend.com"),
            api_key=env.get("RESEND_API_KEY", ""),
            budget_seconds=float(env.get("SPIKE_SYNC_BUDGET_SECONDS", "10")),
            max_raw_bytes=int(env.get("SPIKE_MAX_RAW_BYTES",
                                      str(48 * 1024 * 1024))),
            allowed_host_suffixes=tuple(
                env.get("SPIKE_ALLOWED_DOWNLOAD_HOSTS",
                        "cloudfront.net").split(",")),
            store_dir=env.get("SPIKE_STORE_DIR", "capturas"),
        )

    def validate_public(self) -> list[str]:
        problems = []
        if not firmas.secreto_resend_valido(self.webhook_secret):
            problems.append("RESEND_WEBHOOK_SECRET ausente o sin formato "
                            "whsec_+base64 estricto")
        if not self.capture.api_key:
            problems.append("RESEND_API_KEY ausente")
        if not self.read_token:
            problems.append("SPIKE_READ_TOKEN ausente")
        if self.fail_mode not in ("none", "http500", "hang200"):
            problems.append(f"SPIKE_FAIL_MODE invalido: {self.fail_mode}")
        return problems


def _append_jsonl(path: str, row: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    line = json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
    with open(path, "ab") as fh:
        fh.write(line.encode("utf-8"))
        fh.flush()
        os.fsync(fh.fileno())


def build_server(settings: Settings, host: str = "127.0.0.1",
                 port: int = 0) -> ThreadingHTTPServer:
    semaphore = threading.BoundedSemaphore(settings.max_concurrent)
    ledger_path = os.path.join(settings.store_dir, "attempts.jsonl")
    ledger_lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        server_version = "spike-c4b3-resend"

        def log_message(self, fmt, *args):          # stdout solo operacional
            sys.stdout.write("[http] " + (fmt % args) + "\n")
            sys.stdout.flush()

        # -- helpers ------------------------------------------------------
        def _reply(self, status: int, payload: dict | bytes,
                   ctype: str = "application/json") -> None:
            body = (payload if isinstance(payload, bytes) else
                    json.dumps(payload, ensure_ascii=False).encode("utf-8"))
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _bearer_ok(self) -> bool:
            auth = self.headers.get("Authorization", "")
            return (auth.startswith("Bearer ") and settings.read_token and
                    firmas._iguales(auth[7:], settings.read_token))

        def _ledger(self, row: dict) -> None:
            with ledger_lock:
                _append_jsonl(ledger_path, row)

        # -- GET ----------------------------------------------------------
        def do_GET(self):          # noqa: N802
            if self.path == "/salud":              # fuera del semaforo
                self._reply(200, {"ok": True})
                return
            if not self._bearer_ok():
                self._reply(401, {"error": "token"})
                return
            if self.path == "/capturas/attempts.jsonl":
                self._serve_file(ledger_path, "application/x-ndjson")
            elif (m := re.fullmatch(r"/capturas/markers/([A-Za-z0-9_-]{1,128})"
                                    r"\.json", self.path)):
                self._serve_file(captura.marker_path(settings.capture, m[1]),
                                 "application/json")
            elif (m := re.fullmatch(r"/capturas/blobs/([0-9a-f]{64})\.eml",
                                    self.path)):
                self._serve_file(captura.blob_path(settings.capture, m[1]),
                                 "message/rfc822")
            else:
                self._reply(404, {"error": "ruta"})

        def _serve_file(self, path: str, ctype: str) -> None:
            try:
                with open(path, "rb") as fh:
                    data = fh.read()
            except OSError:
                self._reply(404, {"error": "no-existe"})
                return
            self._reply(200, data, ctype)

        # -- POST ---------------------------------------------------------
        def do_POST(self):          # noqa: N802
            if self.path != "/webhooks/resend":
                self._reply(404, {"error": "ruta"})
                return
            if not semaphore.acquire(blocking=False):
                self._reply(503, {"error": "capacidad"})
                return
            try:
                self._webhook()
            finally:
                semaphore.release()

        def _webhook(self) -> None:
            t0 = time.monotonic()
            if self.headers.get("Transfer-Encoding"):
                self._reply(400, {"error": "transfer-encoding"})
                return
            raw_len = self.headers.get("Content-Length")
            if raw_len is None:
                self._reply(411, {"error": "sin content-length"})
                return
            try:
                length = int(raw_len)
            except ValueError:
                self._reply(400, {"error": "content-length ilegible"})
                return
            if length < 0 or length > MAX_WEBHOOK_BODY:
                self._reply(413 if length > MAX_WEBHOOK_BODY else 400,
                            {"error": "tamano"})
                return
            body = self.rfile.read(length)
            if len(body) != length:
                self._reply(400, {"error": "cuerpo truncado"})
                return

            headers = {k.lower(): v for k, v in self.headers.items()}
            ok, reason = firmas.verificar_resend(settings.webhook_secret,
                                                 headers, body)
            if not ok:
                self._reply(401, {"error": "firma", "motivo": reason})
                return

            svix_id = headers.get("svix-id", "")
            svix_ts = headers.get("svix-timestamp", "")
            row = {"schema": "spike-c4b3-resend/attempt/v1",
                   "received_at_unix": round(time.time(), 3),
                   "svix_id": svix_id, "svix_timestamp": svix_ts}

            # Fallos inducidos (T5): SIEMPRE tras firma valida, SIEMPRE al ledger
            if settings.fail_mode == "http500":
                row |= {"outcome": "fallo-inducido-500", "status": 500}
                self._ledger(row)
                self._reply(500, {"outcome": "fallo-inducido"})
                return
            if settings.fail_mode == "hang200":
                time.sleep(settings.hang_seconds)
                row |= {"outcome": "hang200", "status": 200,
                        "slept_s": settings.hang_seconds}
                self._ledger(row)
                self._reply(200, {"outcome": "hang200"})
                return

            try:
                event = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                row |= {"outcome": "json-ilegible", "status": 400}
                self._ledger(row)
                self._reply(400, {"error": "json"})
                return

            event_type = event.get("type")
            if event_type != "email.received":
                row |= {"outcome": "ignorado", "event_type": str(event_type),
                        "status": 200}
                self._ledger(row)
                self._reply(200, {"outcome": "ignorado"})
                return

            email_id = (event.get("data") or {}).get("email_id")
            if not isinstance(email_id, str) or \
                    not captura.safe_email_id(email_id):
                row |= {"outcome": "email-id-invalido", "status": 400}
                self._ledger(row)
                self._reply(400, {"error": "email_id"})
                return
            row["email_id"] = email_id

            if os.path.exists(captura.marker_path(settings.capture, email_id)):
                row |= {"outcome": "duplicado", "status": 200}
                self._ledger(row)
                self._reply(200, {"outcome": "duplicado"})
                return

            deadline = time.monotonic() + settings.capture.budget_seconds
            try:
                marker = captura.capture_sync(settings.capture, email_id,
                                              svix_id, deadline)
            except captura.CaptureError as exc:
                row |= {"outcome": "fallo-captura", "motivo": exc.reason,
                        "status": 500,
                        "ms": round((time.monotonic() - t0) * 1000, 1)}
                self._ledger(row)
                self._reply(500, {"outcome": "fallo-captura",
                                  "motivo": exc.reason})
                return
            row |= {"outcome": "capturado", "status": 200,
                    "sha256": marker["sha256"], "bytes": marker["bytes"],
                    "ms": round((time.monotonic() - t0) * 1000, 1)}
            self._ledger(row)
            self._reply(200, {"outcome": "capturado",
                              "sha256": marker["sha256"],
                              "bytes": marker["bytes"],
                              "timings_ms": marker["timings_ms"]})

    return ThreadingHTTPServer((host, port), Handler)


def main() -> int:
    settings = Settings(dict(os.environ))
    public = os.environ.get("SPIKE_BIND_PUBLIC") == "1"
    if public:
        problems = settings.validate_public()
        if problems:
            for p in problems:
                print(f"[config] {p}", flush=True)
            return 2
    host = "0.0.0.0" if public else "127.0.0.1"
    port = int(os.environ.get("PORT", "8000"))
    server = build_server(settings, host, port)
    print(f"[spike-c4b3-resend] escuchando en {host}:{port} "
          f"fail_mode={settings.fail_mode}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
