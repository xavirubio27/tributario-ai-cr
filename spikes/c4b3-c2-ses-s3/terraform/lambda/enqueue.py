"""PoC C4-B3 / C2 — acción Lambda de SES Email Receiving.

Lee los destinatarios del SOBRE (`receipt.recipients`), que es la autoridad de tenant
(NO las cabeceras MIME `To:`/`Cc:`, manipulables). Escribe un sidecar de enrutado y encola
en SQS un puntero durable. NO procesa evidencia ni la mueve: el objeto MIME crudo ya lo
escribió la acción S3 de SES.

PoC sintética — sin datos reales/PII. Stub para validar P2/P3/P4; a endurecer en implementación.
"""
from __future__ import annotations

import json
import os

import boto3  # disponible en el runtime de Lambda

_sqs = boto3.client("sqs")
_s3 = boto3.client("s3")

_QUEUE_URL = os.environ["INTAKE_QUEUE_URL"]
_BUCKET = os.environ["RAW_BUCKET"]
_PREFIX = os.environ.get("RAW_PREFIX", "inbound-raw/")


def handler(event, _context):
    """`event` es la notificación SES del receipt rule (una por mensaje aceptado)."""
    for record in event.get("Records", []):
        ses = record.get("ses", {})
        receipt = ses.get("receipt", {})
        mail = ses.get("mail", {})

        message_id = mail.get("messageId")
        # AUTORIDAD DE TENANT: destinatarios del sobre que SES aceptó para el dominio.
        envelope_recipients = receipt.get("recipients", [])
        timestamp = mail.get("timestamp")

        # SES escribe el objeto en <prefix><messageId>. Verificar convención real. # VERIFY
        s3_key = f"{_PREFIX}{message_id}"
        meta_key = f"{s3_key}.meta.json"

        # Sidecar de enrutado: hace que un objeto barrido conserve su sobre autoritativo
        # aunque se pierda la notificación SQS (reconciliación P3).
        meta = {
            "message_id": message_id,
            "envelope_recipients": envelope_recipients,
            "timestamp": timestamp,
            "s3_key": s3_key,
            "source": "ses.receipt.recipients",  # nunca cabeceras MIME
        }
        _s3.put_object(
            Bucket=_BUCKET,
            Key=meta_key,
            Body=json.dumps(meta).encode("utf-8"),
            ContentType="application/json",
        )

        _sqs.send_message(
            QueueUrl=_QUEUE_URL,
            MessageBody=json.dumps(meta),
        )

    return {"ok": True}
