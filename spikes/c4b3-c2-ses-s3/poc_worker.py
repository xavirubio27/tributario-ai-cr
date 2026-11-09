#!/usr/bin/env python3
"""PoC C4-B3 / C2 — worker consumidor de SQS para la PoC SES -> S3.

SOLO PRUEBAS, SOLO EVIDENCIA SINTÉTICA. No es código productivo.

Flujo por mensaje (SES -> SNS -> SQS, raw_message_delivery=true: el cuerpo del mensaje SQS
ES la notificación de SES):
  1. Parsear la notificación SES; autoridad de tenant = receipt.recipients (SOBRE), NUNCA
     cabeceras MIME.  action.objectKey = clave S3; action.bucketName = bucket.
  2. Si no hay recipients autoritativos -> CUARENTENA (no enrutar; no usar MIME).
  3. HeadObject (confirmar que el objeto durable existe ANTES de procesar).
  4. GetObject en streaming -> SHA-256 de una pasada (SSE-KMS se descifra transparente con
     kms:Decrypt).  Rechazar si supera MAX_RAW_EMAIL_BYTES.
  5. Idempotencia por (messageId, recipient) en SQLite local; captura "simulada" (no hay DB
     real en la PoC).  DeleteMessage al terminar con éxito.
  6. Errores transitorios -> NO borrar: SQS re-entrega tras el visibility timeout; tras
     maxReceiveCount la cola lo manda a la DLQ.

Logging SEGURO: solo identificadores/medidas (messageId, nº de recipients, tamaño, prefijo del
sha256, outcome).  NUNCA cuerpo, remitente, asunto ni secretos.

Ejecutar en el sandbox con credenciales del usuario IAM worker (scoped):
  AWS_PROFILE=... INTAKE_QUEUE_URL=... python3 poc_worker.py
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import sys

import boto3  # instalar en el entorno de pruebas: pip install boto3

MAX_RAW_EMAIL_BYTES = 64 * 1024 * 1024  # política Tribuu (SES capa a 40 MB; cota defensiva)
HEAD_READ_CHUNK = 1024 * 1024

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("poc-worker")

_sqs = boto3.client("sqs")
_s3 = boto3.client("s3")

_QUEUE_URL = os.environ["INTAKE_QUEUE_URL"]
_IDEMPOTENCY_DB = os.environ.get("IDEMPOTENCY_DB", "poc_idempotency.sqlite")


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(_IDEMPOTENCY_DB)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS captured ("
        " message_id TEXT NOT NULL, recipient TEXT NOT NULL,"
        " sha256 TEXT NOT NULL, size_bytes INTEGER NOT NULL,"
        " PRIMARY KEY (message_id, recipient))"
    )
    return conn


def _already_captured(conn, message_id: str, recipient: str) -> tuple[str, int] | None:
    row = conn.execute(
        "SELECT sha256, size_bytes FROM captured WHERE message_id=? AND recipient=?",
        (message_id, recipient),
    ).fetchone()
    return (row[0], row[1]) if row else None


def _record_capture(conn, message_id, recipient, sha256_hex, size_bytes) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO captured VALUES (?,?,?,?)",
        (message_id, recipient, sha256_hex, size_bytes),
    )
    conn.commit()


def _stream_sha256_and_size(bucket: str, key: str) -> tuple[str, int]:
    """GetObject en streaming; SHA-256 de una pasada; aborta si supera MAX."""
    resp = _s3.get_object(Bucket=bucket, Key=key)
    body = resp["Body"]
    h = hashlib.sha256()
    total = 0
    for chunk in iter(lambda: body.read(HEAD_READ_CHUNK), b""):
        total += len(chunk)
        if total > MAX_RAW_EMAIL_BYTES:
            body.close()
            raise ValueError(f"oversize>{MAX_RAW_EMAIL_BYTES}")
        h.update(chunk)
    return h.hexdigest(), total


def _parse_ses_notification(raw_body: str) -> dict:
    msg = json.loads(raw_body)
    # Con raw_message_delivery=true el cuerpo es la notificación SES directa.
    # Defensa: si llegara envuelto por SNS (Type/Message), desenvolver.
    if "Message" in msg and "notificationType" not in msg:
        msg = json.loads(msg["Message"])
    return msg


def process_message(conn, sqs_msg) -> bool:
    """Devuelve True si debe borrarse de SQS (éxito/terminal), False para reintento."""
    try:
        note = _parse_ses_notification(sqs_msg["Body"])
    except (ValueError, KeyError, json.JSONDecodeError):
        log.error("notificacion ilegible -> DLQ via reintentos")
        return False

    receipt = note.get("receipt", {})
    mail = note.get("mail", {})
    action = receipt.get("action", {})

    message_id = mail.get("messageId")
    recipients = receipt.get("recipients", [])  # AUTORIDAD DE TENANT (sobre SES)
    bucket = action.get("bucketName")
    key = action.get("objectKey")

    if not recipients or not bucket or not key:
        # P3: sin recipients/objeto autoritativos -> CUARENTENA, nunca MIME.
        log.error("CUARENTENA message_id=%s (sin recipients/objeto autoritativos)", message_id)
        return True  # terminal: no reintentar; queda para revisión manual

    # Confirmar que el objeto durable existe ANTES de procesar.
    try:
        head = _s3.head_object(Bucket=bucket, Key=key)
    except Exception as exc:  # noqa: BLE001 (PoC)
        log.warning("HeadObject falló key=%s -> reintento (%s)", key, type(exc).__name__)
        return False

    declared_size = head.get("ContentLength", -1)

    try:
        sha256_hex, size_bytes = _stream_sha256_and_size(bucket, key)
    except ValueError as exc:
        log.error("message_id=%s key=%s RECHAZADO oversize (%s)", message_id, key, exc)
        return True  # terminal rejected: no reintentar
    except Exception as exc:  # noqa: BLE001
        log.warning("GetObject falló key=%s -> reintento (%s)", key, type(exc).__name__)
        return False

    if declared_size not in (-1, size_bytes):
        log.error("message_id=%s desajuste tamaño head=%s real=%s", message_id, declared_size, size_bytes)

    # Fan-out por destinatario; copia/captura POR TENANT (nunca compartir cross-tenant).
    for recipient in recipients:
        prev = _already_captured(conn, message_id, recipient)
        if prev is not None:
            prev_sha, _ = prev
            if prev_sha == sha256_hex:
                log.info("ALREADY_CAPTURED message_id=%s rcpt=%s", message_id, recipient)
                continue
            log.error("EVIDENCE_CONFLICT message_id=%s rcpt=%s (hash distinto)", message_id, recipient)
            # No sobrescribir; en el modelo real -> nuevo blob + observed_blob_id + alerta.
            continue
        _record_capture(conn, message_id, recipient, sha256_hex, size_bytes)
        log.info(
            "CAPTURED message_id=%s rcpt=%s size=%d sha256=%s…",
            message_id, recipient, size_bytes, sha256_hex[:12],
        )
    return True


def main() -> int:
    conn = _db()
    log.info("worker iniciado; polling %s", _QUEUE_URL.rsplit("/", 1)[-1])
    while True:
        resp = _sqs.receive_message(
            QueueUrl=_QUEUE_URL,
            MaxNumberOfMessages=10,
            WaitTimeSeconds=20,  # long polling
            VisibilityTimeout=300,
        )
        for sqs_msg in resp.get("Messages", []):
            delete = process_message(conn, sqs_msg)
            if delete:
                _sqs.delete_message(QueueUrl=_QUEUE_URL, ReceiptHandle=sqs_msg["ReceiptHandle"])
            # Si delete == False: no se borra; reaparece tras el visibility timeout -> DLQ.


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log.info("worker detenido")
