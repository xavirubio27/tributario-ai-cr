"""Captura sincrona pre-ACK del RAW de Resend — nucleo testeable del spike.

Brazo Resend del experimento de decision C4-B3 (docs/design/C4-B3-experiment.md).
Implementa la Alternativa A del analisis C4B3-01: dentro del presupuesto del
webhook se descarga el MIME crudo via API de Resend, se hashea y se persiste
de forma durable ANTES de devolver 2xx. Cualquier fallo -> no-2xx (Svix
reintenta). SOLO stdlib. NO es produccion.

Garantias que este modulo hace cumplir (y que los tests fijan):
- Presupuesto total (deadline monotonico): API + descarga + fsync caben o se
  aborta; jamas se responde exito con captura a medias.
- Descarga en streaming con tope de bytes; superar el tope aborta y limpia.
- download_url: HTTPS obligatorio, host en allowlist por sufijo, redirects
  PROHIBIDOS (fail-closed). http plano solo para 127.0.0.1 (fakes de test).
- Durabilidad: blob y marker se escriben a temp + fsync + os.replace + fsync
  del directorio. El marker SOLO existe si el blob quedo durable.
- El marker por email_id es la identidad idempotente: quien llama debe
  consultar marker_path() antes de capturar de nuevo.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

CHUNK_BYTES = 64 * 1024
_SAFE_ID = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")


class CaptureError(Exception):
    """Fallo de captura; `reason` es metadata operacional sin PII."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Los redirects del download_url se rechazan (C4B3-07): fail-closed."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        raise CaptureError(f"redirect-prohibido:{code}")


_OPENER = urllib.request.build_opener(_NoRedirect)


class Config:
    """Configuracion inmutable de captura (sin leer env aqui: la recibe)."""

    def __init__(self, *, api_base: str, api_key: str, budget_seconds: float,
                 max_raw_bytes: int, allowed_host_suffixes: tuple[str, ...],
                 store_dir: str):
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.budget_seconds = float(budget_seconds)
        self.max_raw_bytes = int(max_raw_bytes)
        self.allowed_host_suffixes = tuple(
            s.lower().lstrip(".") for s in allowed_host_suffixes if s.strip())
        self.store_dir = store_dir


def safe_email_id(email_id: str) -> bool:
    """El email_id viaja en rutas de fichero y URL: alfabeto cerrado."""
    return bool(email_id) and len(email_id) <= 128 and set(email_id) <= _SAFE_ID


def marker_path(cfg: Config, email_id: str) -> str:
    return os.path.join(cfg.store_dir, "markers", f"{email_id}.json")


def blob_path(cfg: Config, sha256_hex: str) -> str:
    return os.path.join(cfg.store_dir, "blobs", f"{sha256_hex}.eml")


def _validate_download_url(cfg: Config, url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    host = (parsed.hostname or "").lower()
    if not host:
        raise CaptureError("download-url-sin-host")
    if parsed.scheme == "http":
        if host != "127.0.0.1":
            raise CaptureError("download-url-http-no-local")
    elif parsed.scheme != "https":
        raise CaptureError("download-url-esquema-invalido")
    if host == "127.0.0.1":
        return url
    for suffix in cfg.allowed_host_suffixes:
        if host == suffix or host.endswith("." + suffix):
            return url
    raise CaptureError("download-url-host-fuera-de-allowlist")


def _remaining(deadline: float) -> float:
    left = deadline - time.monotonic()
    if left <= 0:
        raise CaptureError("presupuesto-agotado")
    return left


def _cleanup(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def _fsync_dir(path: str) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _durable_write(directory: str, final_name: str, data: bytes) -> str:
    os.makedirs(directory, exist_ok=True)
    tmp = os.path.join(directory, f".tmp-{os.getpid()}-{final_name}")
    final = os.path.join(directory, final_name)
    with open(tmp, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, final)
    _fsync_dir(directory)
    return final


def _api_get(cfg: Config, url: str, timeout: float):
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {cfg.api_key}",
        "User-Agent": "tribuu-spike-c4b3-resend-sync-capture",
    })
    return _OPENER.open(req, timeout=timeout)


def capture_sync(cfg: Config, email_id: str, svix_id: str,
                 deadline: float) -> dict:
    """Captura durable del RAW de `email_id` antes del deadline monotonico.

    Devuelve el marker (dict) ya persistido. Lanza CaptureError ante cualquier
    fallo; en ese caso NO queda marker y no quedan temporales.
    """
    if not safe_email_id(email_id):
        raise CaptureError("email-id-invalido")
    t0 = time.monotonic()

    # 1. Metadata del email recibido -> raw.download_url
    api_url = f"{cfg.api_base}/emails/receiving/{email_id}"
    try:
        with _api_get(cfg, api_url, timeout=_remaining(deadline)) as resp:
            if resp.status != 200:
                raise CaptureError(f"api-status-{resp.status}")
            payload = json.loads(resp.read(1024 * 1024).decode("utf-8"))
    except CaptureError:
        raise
    except urllib.error.HTTPError as exc:
        raise CaptureError(f"api-status-{exc.code}") from exc
    except Exception as exc:  # red, timeout, JSON ilegible
        raise CaptureError(f"api-fallo:{type(exc).__name__}") from exc
    t_api = time.monotonic()

    raw = payload.get("raw") or {}
    download_url = raw.get("download_url")
    if not isinstance(download_url, str) or not download_url:
        raise CaptureError("sin-raw-download-url")
    download_url = _validate_download_url(cfg, download_url)

    # 2. Descarga en streaming A DISCO (memoria acotada a un chunk) con tope
    #    de bytes y deadline; ante cualquier fallo el temporal se elimina.
    blobs_dir = os.path.join(cfg.store_dir, "blobs")
    os.makedirs(blobs_dir, exist_ok=True)
    tmp_blob = os.path.join(blobs_dir, f".tmp-{os.getpid()}-{email_id}")
    hasher = hashlib.sha256()
    total = 0
    try:
        with open(tmp_blob, "wb") as out, _OPENER.open(
                urllib.request.Request(
                    download_url,
                    headers={"User-Agent":
                             "tribuu-spike-c4b3-resend-sync-capture"}),
                timeout=_remaining(deadline)) as resp:
            if resp.status != 200:
                raise CaptureError(f"descarga-status-{resp.status}")
            while True:
                _remaining(deadline)          # el deadline manda entre chunks
                chunk = resp.read(CHUNK_BYTES)
                if not chunk:
                    break
                total += len(chunk)
                if total > cfg.max_raw_bytes:
                    raise CaptureError("descarga-supera-tope")
                hasher.update(chunk)
                out.write(chunk)
            if total == 0:
                raise CaptureError("descarga-vacia")
            out.flush()
            os.fsync(out.fileno())
    except CaptureError:
        _cleanup(tmp_blob)
        raise
    except urllib.error.HTTPError as exc:
        _cleanup(tmp_blob)
        raise CaptureError(f"descarga-status-{exc.code}") from exc
    except Exception as exc:
        _cleanup(tmp_blob)
        raise CaptureError(f"descarga-fallo:{type(exc).__name__}") from exc
    t_down = time.monotonic()

    # 3. Blob durable primero; el marker solo si el blob quedo durable
    sha_hex = hasher.hexdigest()
    os.replace(tmp_blob, os.path.join(blobs_dir, f"{sha_hex}.eml"))
    _fsync_dir(blobs_dir)
    marker = {
        "schema": "spike-c4b3-resend/marker/v1",
        "email_id": email_id,
        "svix_id": svix_id,
        "sha256": sha_hex,
        "bytes": total,
        "download_url_host": urllib.parse.urlsplit(download_url).hostname,
        "raw_expires_at": raw.get("expires_at"),
        "timings_ms": {
            "api": round((t_api - t0) * 1000, 1),
            "download": round((t_down - t_api) * 1000, 1),
            "total": round((time.monotonic() - t0) * 1000, 1),
        },
        "captured_at_unix": round(time.time(), 3),
    }
    _durable_write(os.path.join(cfg.store_dir, "markers"), f"{email_id}.json",
                   json.dumps(marker, ensure_ascii=False,
                              sort_keys=True).encode("utf-8"))
    return marker
