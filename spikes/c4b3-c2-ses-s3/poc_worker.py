#!/usr/bin/env python3
"""PoC C4-B3 / C2 — worker consumidor de SQS (remediado INFRA-H1..H8/M/L).

SOLO PRUEBAS, SOLO EVIDENCIA SINTÉTICA. No es código productivo.

Garantías implementadas para la PoC:
  - Autoridad de tenant = `receipt.recipients` del SOBRE SES; NUNCA cabeceras MIME To/Cc.
  - Ledger DURABLE en S3 bajo `markers/` (processed/quarantine/rejected). El worker NO borra
    de SQS hasta escribir y VERIFICAR (HeadObject) el resultado durable (INFRA-H2).
  - Idempotencia durable por (messageId, recipient) vía existencia del marker processed en S3
    (sobrevive a reinicios; SQLite es solo caché opcional) (INFRA-M1).
  - Cuarentena DURABLE para evidencia sin destinatarios autoritativos / conflictos (INFRA-H1).
    La cuarentena NO es recuperación automática del tenant: queda para resolución manual.
  - Heartbeat: extiende el visibility timeout durante descargas largas (INFRA-M2).
  - Logging SEGURO: identificadores redactados, sin PII, sin claves completas, sin cuerpo (M3).

Ejecutar en el sandbox con credenciales TEMPORALES (STS AssumeRole) del rol/usuario worker:
  INTAKE_QUEUE_URL=... RAW_BUCKET=... python3 poc_worker.py
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import threading
import time

import boto3
from botocore.exceptions import ClientError

MAX_RAW_EMAIL_BYTES = 64 * 1024 * 1024  # política Tribuu (SES capa a 40 MB; cota defensiva)
READ_CHUNK = 1024 * 1024
HEARTBEAT_EVERY_SECONDS = 60           # extiende visibilidad durante descargas largas
HEARTBEAT_VISIBILITY = 300
# Sal efímera para redactar identificadores en logs (NO para seguridad; solo anti-PII en logs).
_LOG_SALT = os.urandom(16)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("poc-worker")

_sqs = boto3.client("sqs")
_s3 = boto3.client("s3")

_QUEUE_URL = os.environ["INTAKE_QUEUE_URL"]
_MARKERS_PREFIX = os.environ.get("MARKERS_PREFIX", "markers/")


def _redact(value: str | None) -> str:
    """Token corto, estable dentro del proceso, para correlacionar sin revelar PII."""
    if not value:
        return "-"
    return hmac.new(_LOG_SALT, value.encode(), hashlib.sha256).hexdigest()[:10]


# ---------- ledger durable en S3 ----------
def _marker_key(kind: str, message_id: str, recipient: str | None = None) -> str:
    base = f"{_MARKERS_PREFIX}{kind}/{message_id}"
    if recipient is not None:
        base += "/" + hashlib.sha256(recipient.encode()).hexdigest()[:32]
    return base + ".json"


def _marker_exists(bucket: str, key: str) -> dict | None:
    try:
        obj = _s3.get_object(Bucket=bucket, Key=key)
        return json.loads(obj["Body"].read())
    except ClientError as exc:
        if exc.response["Error"]["Code"] in ("NoSuchKey", "404", "NotFound"):
            return None
        raise


def _write_marker_verified(bucket: str, key: str, payload: dict) -> bool:
    """Escribe el marker durable y VERIFICA con HeadObject. True solo si quedó durable."""
    body = json.dumps(payload, separators=(",", ":")).encode()
    _s3.put_object(Bucket=bucket, Key=key, Body=body, ContentType="application/json")
    try:
        _s3.head_object(Bucket=bucket, Key=key)  # verificación de durabilidad
        return True
    except ClientError:
        return False


# ---------- heartbeat de visibilidad ----------
class _Heartbeat:
    def __init__(self, receipt_handle: str):
        self._rh = receipt_handle
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        while not self._stop.wait(HEARTBEAT_EVERY_SECONDS):
            try:
                _sqs.change_message_visibility(
                    QueueUrl=_QUEUE_URL, ReceiptHandle=self._rh,
                    VisibilityTimeout=HEARTBEAT_VISIBILITY,
                )
            except ClientError:
                return

    def __enter__(self):
        self._t.start()
        return self

    def __exit__(self, *_):
        self._stop.set()


def _stream_sha256_and_size(bucket: str, key: str) -> tuple[str, int]:
    resp = _s3.get_object(Bucket=bucket, Key=key)  # SSE-KMS se descifra transparente
    body = resp["Body"]
    h = hashlib.sha256()
    total = 0
    for chunk in iter(lambda: body.read(READ_CHUNK), b""):
        total += len(chunk)
        if total > MAX_RAW_EMAIL_BYTES:
            body.close()
            raise ValueError("oversize")
        h.update(chunk)
    return h.hexdigest(), total


def _parse_ses_notification(raw_body: str) -> dict:
    msg = json.loads(raw_body)
    if "Message" in msg and "notificationType" not in msg:  # por si no es raw delivery
        msg = json.loads(msg["Message"])
    return msg


def process_message(sqs_msg) -> bool:
    """True si el resultado quedó DURABLE y puede borrarse de SQS; False para reintento."""
    bucket = os.environ["RAW_BUCKET"]
    try:
        note = _parse_ses_notification(sqs_msg["Body"])
    except (ValueError, KeyError, json.JSONDecodeError):
        log.error("notificacion ilegible -> no borrar (DLQ via reintentos)")
        return False

    receipt = note.get("receipt", {})
    mail = note.get("mail", {})
    action = receipt.get("action", {})
    message_id = mail.get("messageId")
    recipients = receipt.get("recipients", [])  # AUTORIDAD DE TENANT (sobre SES)
    obj_bucket = action.get("bucketName")
    key = action.get("objectKey")

    # H1: sin recipients/objeto autoritativos -> CUARENTENA DURABLE (nunca MIME).
    if not recipients or not obj_bucket or not key:
        qkey = _marker_key("quarantine", message_id or "unknown")
        ok = _write_marker_verified(bucket, qkey, {
            "message_id": message_id, "reason": "missing_authoritative_recipients_or_object",
            "ts": int(time.time()),  # antigüedad
            "note": "quarantine != auto tenant recovery",
        })
        log.error("QUARANTINE msg=%s reason=missing_authority durable=%s", _redact(message_id), ok)
        return ok  # solo borrar si la cuarentena quedó durable

    # Confirmar que el objeto durable existe ANTES de procesar.
    try:
        _s3.head_object(Bucket=obj_bucket, Key=key)
    except ClientError:
        log.warning("HeadObject raw fallo key=%s -> reintento", _redact(key))
        return False

    with _Heartbeat(sqs_msg["ReceiptHandle"]):
        try:
            sha256_hex, size_bytes = _stream_sha256_and_size(obj_bucket, key)
        except ValueError:
            rkey = _marker_key("rejected", message_id)
            ok = _write_marker_verified(bucket, rkey, {
                "message_id": message_id, "reason": "oversize",
                "limit_bytes": MAX_RAW_EMAIL_BYTES, "ts": int(time.time()),
            })
            log.error("REJECTED oversize msg=%s durable=%s", _redact(message_id), ok)
            return ok
        except ClientError:
            log.warning("GetObject fallo key=%s -> reintento", _redact(key))
            return False

    # Fan-out por destinatario; captura POR TENANT (nunca compartir cross-tenant).
    all_durable = True
    for recipient in recipients:
        pkey = _marker_key("processed", message_id, recipient)
        existing = _marker_exists(bucket, pkey)
        if existing is not None:
            if existing.get("sha256") == sha256_hex:
                log.info("ALREADY_CAPTURED msg=%s rcpt=%s", _redact(message_id), _redact(recipient))
                continue
            # EVIDENCE_CONFLICT: no sobrescribir; cuarentena durable del conflicto.
            ckey = _marker_key("quarantine", message_id, recipient)
            ok = _write_marker_verified(bucket, ckey, {
                "message_id": message_id, "recipient_hash": _redact(recipient),
                "reason": "evidence_conflict", "ts": int(time.time()),
            })
            log.error("EVIDENCE_CONFLICT msg=%s rcpt=%s durable=%s", _redact(message_id), _redact(recipient), ok)
            all_durable = all_durable and ok
            continue
        ok = _write_marker_verified(bucket, pkey, {
            "message_id": message_id, "recipient": recipient,  # cifrado en reposo (SSE-KMS)
            "sha256": sha256_hex, "size_bytes": size_bytes, "ts": int(time.time()),
        })
        if ok:
            log.info("CAPTURED msg=%s rcpt=%s size=%d sha=%s…",
                     _redact(message_id), _redact(recipient), size_bytes, sha256_hex[:12])
        all_durable = all_durable and ok

    return all_durable  # H2: solo borrar si TODOS los resultados quedaron durables


def main() -> int:
    log.info("worker iniciado; polling %s", _redact(_QUEUE_URL))
    while True:
        resp = _sqs.receive_message(
            QueueUrl=_QUEUE_URL, MaxNumberOfMessages=10, WaitTimeSeconds=20,
            VisibilityTimeout=HEARTBEAT_VISIBILITY,
        )
        for sqs_msg in resp.get("Messages", []):
            if process_message(sqs_msg):
                _sqs.delete_message(QueueUrl=_QUEUE_URL, ReceiptHandle=sqs_msg["ReceiptHandle"])
            # delete solo si hubo resultado DURABLE; si no, SQS re-entrega tras visibility -> DLQ.


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        log.info("worker detenido")
