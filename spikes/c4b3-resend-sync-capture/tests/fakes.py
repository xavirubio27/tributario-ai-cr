"""Fakes en memoria para los tests del spike (stdlib; sin red externa).

- FakeResend: servidor HTTP local que simula la API de Resend
  (`GET /emails/receiving/<id>`) y el host de descarga del RAW, con
  comportamientos configurables por email_id.
- sign(): firma Svix v1 real (mismo esquema que firmas.py) para construir
  entregas autenticas en los tests.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SECRET_KEY = b"k" * 24
SECRET = "whsec_" + base64.b64encode(SECRET_KEY).decode()


def sign(body: bytes, svix_id: str = "msg_1", ts: int | None = None,
         secret_key: bytes = SECRET_KEY) -> dict[str, str]:
    ts = int(time.time()) if ts is None else ts
    base = f"{svix_id}.{ts}.".encode() + body
    sig = base64.b64encode(hmac.new(secret_key, base,
                                    hashlib.sha256).digest()).decode()
    return {"svix-id": svix_id, "svix-timestamp": str(ts),
            "svix-signature": f"v1,{sig}"}


def event_body(email_id: str, event_type: str = "email.received") -> bytes:
    return json.dumps({"type": event_type,
                       "data": {"email_id": email_id}}).encode()


class FakeResend:
    """API + host de descarga en un unico servidor local.

    behaviors[email_id] es un dict con:
      raw: bytes del RAW a servir (default b"RAW...")
      api: "ok" | "404" | "500" | "slow" (duerme api_delay)
      download: "ok" | "500" | "slow" | "redirect" | "drip" (gotea lento)
      api_delay / download_delay: segundos
      no_raw_field: True -> respuesta API sin objeto raw
    """

    def __init__(self):
        self.behaviors: dict[str, dict] = {}
        self.api_calls: list[str] = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):          # silencioso
                pass

            def _reply(self, status, body: bytes,
                       ctype="application/json", extra=()):
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                for k, v in extra:
                    self.send_header(k, v)
                self.end_headers()
                if body:
                    self.wfile.write(body)

            def do_GET(self):          # noqa: N802
                if self.path.startswith("/emails/receiving/"):
                    email_id = self.path.rsplit("/", 1)[1]
                    fake.api_calls.append(email_id)
                    beh = fake.behaviors.get(email_id, {})
                    mode = beh.get("api", "ok")
                    if mode == "slow":
                        time.sleep(beh.get("api_delay", 2.0))
                        mode = "ok"
                    if mode == "404":
                        self._reply(404, b'{"message":"not found"}')
                        return
                    if mode == "500":
                        self._reply(500, b"{}")
                        return
                    if beh.get("no_raw_field"):
                        payload = {"id": email_id}
                    else:
                        payload = {"id": email_id, "raw": {
                            "download_url":
                                f"http://127.0.0.1:{fake.port}/raw/{email_id}",
                            "expires_at": "2099-01-01T00:00:00Z"}}
                    self._reply(200, json.dumps(payload).encode())
                elif self.path.startswith("/raw/"):
                    email_id = self.path.rsplit("/", 1)[1]
                    beh = fake.behaviors.get(email_id, {})
                    mode = beh.get("download", "ok")
                    raw = beh.get("raw", b"RAW fiscal sintetico\r\n")
                    if mode == "redirect":
                        self._reply(302, b"", extra=(
                            ("Location",
                             f"http://127.0.0.1:{fake.port}/raw-x/{email_id}"),))
                        return
                    if mode == "500":
                        self._reply(500, b"")
                        return
                    if mode == "slow":
                        time.sleep(beh.get("download_delay", 2.0))
                    if mode == "drip":
                        self.send_response(200)
                        self.send_header("Content-Length", str(len(raw)))
                        self.end_headers()
                        step = max(1, len(raw) // 4)
                        for i in range(0, len(raw), step):
                            self.wfile.write(raw[i:i + step])
                            self.wfile.flush()
                            time.sleep(beh.get("download_delay", 0.5))
                        return
                    self._reply(200, raw, ctype="message/rfc822")
                else:
                    self._reply(404, b"{}")

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self._server.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}"
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        daemon=True)
        self._thread.start()

    def close(self):
        self._server.shutdown()
        self._server.server_close()
