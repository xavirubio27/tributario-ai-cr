"""Sonda de retencion del correo entrante en Resend. NO es produccion.

Mide dos cosas que la documentacion publica NO establece (NO VERIFICADO,
2026-11-13): cuanto tiempo sigue recuperable un correo recibido, y si el
`raw.download_url` caducado es re-emitible con una nueva llamada a la API.

Uso (manual, una vez al dia por email sondeado):
  RESEND_API_KEY=... python3 probe_retention.py --email-id <id> \
      [--ledger retention.jsonl] [--full]

Cada corrida anade UNA fila JSONL: fecha, email_id, status de la API, si vino
download_url y su expires_at, status de un GET Range bytes=0-0 a esa URL, y
(con --full) el sha256 del RAW completo para detectar mutacion del contenido.
La serie temporal de filas ES la medicion: el primer dia en que la API deje de
devolver el correo acota la retencion efectiva. SOLO stdlib.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request

API_BASE = os.environ.get("RESEND_API_BASE", "https://api.resend.com")


def _get(url: str, headers: dict[str, str], timeout: float = 30.0):
    req = urllib.request.Request(url, headers={
        "User-Agent": "tribuu-spike-c4b3-retention-probe", **headers})
    return urllib.request.urlopen(req, timeout=timeout)


def probe(email_id: str, api_key: str, full: bool) -> dict:
    row: dict = {"schema": "spike-c4b3-resend/retention/v1",
                 "probed_at_unix": round(time.time(), 3),
                 "email_id": email_id}
    try:
        with _get(f"{API_BASE}/emails/receiving/{email_id}",
                  {"Authorization": f"Bearer {api_key}"}) as resp:
            row["api_status"] = resp.status
            payload = json.loads(resp.read(1024 * 1024).decode("utf-8"))
    except urllib.error.HTTPError as exc:
        row["api_status"] = exc.code          # 404 = ya no recuperable
        return row
    except Exception as exc:
        row["api_error"] = type(exc).__name__
        return row

    raw = payload.get("raw") or {}
    url = raw.get("download_url")
    row["url_present"] = bool(url)
    row["raw_expires_at"] = raw.get("expires_at")
    if not url:
        return row
    try:
        if full:
            hasher = hashlib.sha256()
            total = 0
            with _get(url, {}) as resp:
                row["download_status"] = resp.status
                while chunk := resp.read(64 * 1024):
                    hasher.update(chunk)
                    total += len(chunk)
            row["download_bytes"] = total
            row["download_sha256"] = hasher.hexdigest()
        else:
            with _get(url, {"Range": "bytes=0-0"}) as resp:
                row["download_status"] = resp.status      # 206 o 200
    except urllib.error.HTTPError as exc:
        row["download_status"] = exc.code
    except Exception as exc:
        row["download_error"] = type(exc).__name__
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email-id", required=True)
    parser.add_argument("--ledger", default="retention.jsonl")
    parser.add_argument("--full", action="store_true",
                        help="descarga completa + sha256 (mas trafico)")
    args = parser.parse_args()
    api_key = os.environ.get("RESEND_API_KEY", "")
    if not api_key:
        print("[config] RESEND_API_KEY ausente", file=sys.stderr)
        return 2
    row = probe(args.email_id, api_key, args.full)
    with open(args.ledger, "ab") as fh:
        fh.write((json.dumps(row, ensure_ascii=False, sort_keys=True) +
                  "\n").encode("utf-8"))
        fh.flush()
        os.fsync(fh.fileno())
    print(json.dumps(row, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
