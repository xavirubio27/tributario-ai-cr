#!/usr/bin/env python3
"""PoC C4-B3 / C2 — worker consumidor de SQS (remediación NEW-H1..H5, NEW-M1/M2).

SOLO PRUEBAS, SOLO EVIDENCIA SINTÉTICA. No es código productivo.

Diseño: SES -> S3 (MIME crudo, SSE-KMS) + notificación SNS nativa -> SQS -> este worker.
Autoridad de tenant = `receipt.recipients` del SOBRE SES; NUNCA cabeceras MIME To/Cc.

Garantías (verificadas por tests/ con fakes AWS; comportamiento real pendiente de PoC):
  NEW-H1  Escritura de markers CONDICIONAL (If-None-Match:*). 412 -> se lee el existente y se
          compara; conflictos en markers APPEND-ONLY (clave por sha observado), sin sobrescribir.
          Verificación de CONTENIDO del marker (GetObject + comparación), no solo HeadObject.
  NEW-H2..H4  MANIFEST inmutable de recipients esperados; completitud por CONJUNTO
          (expected - completed); estados completo/parcial/rechazado/cuarentena; claves EXACTAS
          con delimitador (sin prefijos ambiguos abc/abcd).
  NEW-M1/M2  Cada marker referencia inequívocamente la evidencia (bucket, key, VersionId, sha256,
          size, tipo, event_id, recipientRef). Schema SES validado estrictamente; incoherente ->
          cuarentena. Nunca MIME como autoridad.
  NEW-H5  Heartbeat durante TODO el procesamiento (incl. fan-out); si falla la renovación de
          visibilidad, se aborta sin borrar. NUNCA DeleteMessage sin resultado durable.

Inyectable para tests: `process_message(sqs_msg, ctx)` recibe clientes/stubs en `ctx`.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import threading
import time
from dataclasses import dataclass

try:  # import-safe: los tests usan fakes, no requieren boto3
    import boto3
except Exception:  # noqa: BLE001
    boto3 = None

DEFAULT_MAX_BYTES = 64 * 1024 * 1024
READ_CHUNK = 1024 * 1024
HEARTBEAT_EVERY = 60
HEARTBEAT_VISIBILITY = 300
_LOG_SALT = os.urandom(16)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("poc-worker")


@dataclass
class Ctx:
    s3: object
    sqs: object
    bucket: str
    queue_url: str
    raw_prefix: str = "inbound-raw/"
    markers_prefix: str = "markers/"
    max_bytes: int = DEFAULT_MAX_BYTES


class SchemaError(Exception):
    pass


# ---------- utilidades ----------
def _redact(value: str | None) -> str:
    if not value:
        return "-"
    return hmac.new(_LOG_SALT, value.encode(), hashlib.sha256).hexdigest()[:10]


def _rref(recipient: str) -> str:
    """Referencia segura (no PII) y estable de la identidad del destinatario."""
    return hashlib.sha256(recipient.encode()).hexdigest()


def _error_code(exc: Exception) -> str | None:
    resp = getattr(exc, "response", None)
    if isinstance(resp, dict):
        return resp.get("Error", {}).get("Code")
    return getattr(exc, "code", None)


_ABSENT = {"NoSuchKey", "404", "NotFound"}
_EXISTS = {"PreconditionFailed", "412"}


def _canonical(payload: dict) -> bytes:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()


# ---------- markers durables (escritura condicional + verificación de contenido) ----------
def _marker_key(ctx: Ctx, kind: str, message_id: str, *parts: str) -> str:
    # Claves EXACTAS con delimitador '/'; evita colisiones de prefijo (abc vs abcd).
    tail = "".join(f"{p}/" for p in parts[:-1]) + (parts[-1] if parts else "")
    base = f"{ctx.markers_prefix}{kind}/{message_id}/"
    return base + tail + ".json" if parts else f"{ctx.markers_prefix}{kind}/{message_id}.json"


def _get_marker(ctx: Ctx, key: str) -> dict | None:
    try:
        obj = ctx.s3.get_object(Bucket=ctx.bucket, Key=key)
        return json.loads(obj["Body"].read())
    except Exception as exc:  # noqa: BLE001
        if _error_code(exc) in _ABSENT:
            return None
        raise


def _put_marker_if_absent(ctx: Ctx, key: str, payload: dict) -> tuple[str, dict]:
    """Escritura CONDICIONAL If-None-Match:*. Devuelve ('created'|'exists', contenido_durable).

    'created' se VERIFICA releyendo el contenido (NEW-H1). 'exists' devuelve el contenido previo.
    """
    body = _canonical(payload)
    try:
        ctx.s3.put_object(Bucket=ctx.bucket, Key=key, Body=body,
                          ContentType="application/json", IfNoneMatch="*")
    except Exception as exc:  # noqa: BLE001
        if _error_code(exc) in _EXISTS:
            existing = _get_marker(ctx, key)
            if existing is None:
                raise
            return "exists", existing
        raise
    # Verificación de CONTENIDO (no solo HeadObject): releer y comparar canónico.
    readback = _get_marker(ctx, key)
    if readback is None or _canonical(readback) != body:
        raise RuntimeError(f"marker no verificable tras escritura: {key}")
    return "created", readback


# ---------- heartbeat (NEW-H5) ----------
class Heartbeat:
    def __init__(self, ctx: Ctx, receipt_handle: str):
        self._ctx, self._rh = ctx, receipt_handle
        self._stop = threading.Event()
        self.failed = threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        while not self._stop.wait(HEARTBEAT_EVERY):
            try:
                self._ctx.sqs.change_message_visibility(
                    QueueUrl=self._ctx.queue_url, ReceiptHandle=self._rh,
                    VisibilityTimeout=HEARTBEAT_VISIBILITY)
            except Exception:  # noqa: BLE001
                self.failed.set()  # no se puede garantizar exclusividad -> abortar
                return

    def __enter__(self):
        self._t.start()
        return self

    def __exit__(self, *_):
        self._stop.set()


# ---------- validación estricta del schema SES (NEW-M2) ----------
def validate_notification(note: dict, ctx: Ctx) -> dict:
    if not isinstance(note, dict) or note.get("notificationType") != "Received":
        raise SchemaError("notificationType!=Received")
    receipt, mail = note.get("receipt"), note.get("mail")
    if not isinstance(receipt, dict) or not isinstance(mail, dict):
        raise SchemaError("receipt/mail ausente")
    action = receipt.get("action", {})
    if action.get("type") != "S3":
        raise SchemaError("action.type!=S3")
    message_id = mail.get("messageId")
    bucket = action.get("bucketName")
    key = action.get("objectKey")
    recipients = receipt.get("recipients")
    if not isinstance(message_id, str) or not message_id or "/" in message_id or "\n" in message_id:
        raise SchemaError("messageId invalido")
    if bucket != ctx.bucket:  # NEW-M2 / escenario 11: bucket ajeno/incorrecto
        raise SchemaError("bucketName no coincide con el bucket configurado")
    if not isinstance(key, str) or not key.startswith(ctx.raw_prefix):
        raise SchemaError("objectKey fuera del prefijo RAW")
    if key != f"{ctx.raw_prefix}{message_id}":  # SES: objectKey == messageId
        raise SchemaError("objectKey no corresponde al messageId")
    if not isinstance(recipients, list) or not recipients or not all(isinstance(r, str) and r for r in recipients):
        raise SchemaError("recipients invalido")
    return {"message_id": message_id, "bucket": bucket, "key": key, "recipients": recipients}


def _stream_sha256_size(ctx: Ctx, key: str, hb: Heartbeat) -> tuple[str, int, str | None]:
    resp = ctx.s3.get_object(Bucket=ctx.bucket, Key=key)
    version_id = resp.get("VersionId")
    body = resp["Body"]
    h, total = hashlib.sha256(), 0
    for chunk in iter(lambda: body.read(READ_CHUNK), b""):
        if hb.failed.is_set():
            raise RuntimeError("heartbeat_failed")
        total += len(chunk)
        if total > ctx.max_bytes:
            body.close()
            raise ValueError("oversize")
        h.update(chunk)
    return h.hexdigest(), total, version_id


# ---------- procesamiento ----------
def process_message(sqs_msg: dict, ctx: Ctx) -> bool:
    """True SOLO si el resultado completo quedó DURABLE (se puede DeleteMessage)."""
    raw_body = sqs_msg.get("Body", "")
    try:
        note = json.loads(raw_body)
        if "Message" in note and "notificationType" not in note:
            note = json.loads(note["Message"])  # por si no es raw delivery
    except Exception:  # noqa: BLE001
        log.error("notificacion ilegible -> no borrar (reintento/DLQ)")
        return False

    # Validación estricta -> incoherente => cuarentena durable del mensaje (NEW-M2).
    try:
        v = validate_notification(note, ctx)
    except SchemaError as exc:
        mid = (note.get("mail", {}) or {}).get("messageId") if isinstance(note, dict) else None
        qkey = _marker_key(ctx, "quarantine", mid or "unknown")
        try:
            _put_marker_if_absent(ctx, qkey, {
                "schema": "quarantine/v1", "event_id": mid, "reason": f"schema:{exc}",
                "ts": int(sqs_msg.get("_now", time.time()))})
            log.error("QUARANTINE schema msg=%s reason=%s durable=yes", _redact(mid), exc)
            return True
        except Exception:  # noqa: BLE001
            log.error("QUARANTINE no durable msg=%s -> reintento", _redact(mid))
            return False

    message_id, bucket, key, recipients = v["message_id"], v["bucket"], v["key"], v["recipients"]
    expected = sorted({_rref(r) for r in recipients})

    with Heartbeat(ctx, sqs_msg.get("ReceiptHandle", "")) as hb:
        # Confirmar objeto durable + capturar VersionId/sha/size.
        try:
            head = ctx.s3.head_object(Bucket=ctx.bucket, Key=key)
        except Exception:  # noqa: BLE001
            log.warning("HeadObject raw fallo key=%s -> reintento", _redact(key))
            return False

        # MANIFEST inmutable de recipients esperados (NEW-H2). First-writer-wins.
        manifest_key = _marker_key(ctx, "manifest", message_id)
        manifest = {
            "schema": "manifest/v1", "event_id": message_id,
            "object": {"bucket": bucket, "key": key, "version_id": head.get("VersionId")},
            "expected_recipients": expected,
            "recipients_clear": recipients,  # cifrado en reposo (SSE-KMS); autoridad del sobre
            "ts": int(sqs_msg.get("_now", time.time())),
        }
        try:
            _, manifest = _put_marker_if_absent(ctx, manifest_key, manifest)
        except Exception:  # noqa: BLE001
            log.error("manifest no durable msg=%s -> reintento", _redact(message_id))
            return False
        expected = sorted(set(manifest["expected_recipients"]))

        try:
            sha_hex, size, version_id = _stream_sha256_size(ctx, key, hb)
        except ValueError:  # oversize -> rechazo terminal (todos los expected)
            rkey = _marker_key(ctx, "rejected", message_id)
            try:
                _put_marker_if_absent(ctx, rkey, {
                    "schema": "rejected/v1", "event_id": message_id, "reason": "oversize",
                    "object": {"bucket": bucket, "key": key, "version_id": head.get("VersionId")},
                    "limit_bytes": ctx.max_bytes, "ts": int(sqs_msg.get("_now", time.time()))})
                log.error("REJECTED oversize msg=%s durable=yes", _redact(message_id))
                return True
            except Exception:  # noqa: BLE001
                return False
        except RuntimeError:  # heartbeat_failed
            log.warning("heartbeat fallo msg=%s -> abortar sin borrar", _redact(message_id))
            return False
        except Exception:  # noqa: BLE001
            log.warning("GetObject fallo key=%s -> reintento", _redact(key))
            return False

        # Fan-out por destinatario (bajo heartbeat). Completitud por CONJUNTO.
        completed: set[str] = set()
        for recipient in recipients:
            if hb.failed.is_set():
                log.warning("heartbeat fallo en fan-out msg=%s -> abortar", _redact(message_id))
                return False
            rref = _rref(recipient)
            ckey = _marker_key(ctx, "completed", message_id, rref)
            payload = {
                "schema": "completed/v1", "result": "captured", "event_id": message_id,
                "recipient_ref": rref,
                "object": {"bucket": bucket, "key": key, "version_id": version_id,
                           "sha256": sha_hex, "size_bytes": size},
                "ts": int(sqs_msg.get("_now", time.time())),
            }
            try:
                status, durable = _put_marker_if_absent(ctx, ckey, payload)
            except Exception:  # noqa: BLE001
                log.warning("completed no durable msg=%s rcpt=%s -> reintento",
                            _redact(message_id), _redact(recipient))
                return False
            if status == "exists" and durable.get("object", {}).get("sha256") != sha_hex:
                # CONFLICTO: append-only, no sobrescribe el canónico (NEW-H1).
                conflict_key = _marker_key(ctx, "conflict", message_id, rref, sha_hex)
                try:
                    _put_marker_if_absent(ctx, conflict_key, {
                        "schema": "conflict/v1", "event_id": message_id, "recipient_ref": rref,
                        "canonical_sha256": durable.get("object", {}).get("sha256"),
                        "observed_sha256": sha_hex, "size_bytes": size,
                        "ts": int(sqs_msg.get("_now", time.time()))})
                    log.error("EVIDENCE_CONFLICT msg=%s rcpt=%s durable=yes",
                              _redact(message_id), _redact(recipient))
                except Exception:  # noqa: BLE001
                    return False
            completed.add(rref)

        pending = set(expected) - completed
        if pending:
            log.warning("INCOMPLETO msg=%s pendientes=%d -> no borrar", _redact(message_id), len(pending))
            return False
        log.info("COMPLETO msg=%s recipients=%d size=%d sha=%s…",
                 _redact(message_id), len(expected), size, sha_hex[:12])
        return True


# ---------- loop ----------
def make_ctx() -> Ctx:
    if boto3 is None:
        raise RuntimeError("boto3 no disponible; este modo requiere AWS (solo para ejecución real)")
    return Ctx(s3=boto3.client("s3"), sqs=boto3.client("sqs"),
               bucket=os.environ["RAW_BUCKET"], queue_url=os.environ["INTAKE_QUEUE_URL"],
               raw_prefix=os.environ.get("RAW_PREFIX", "inbound-raw/"),
               markers_prefix=os.environ.get("MARKERS_PREFIX", "markers/"))


def main() -> int:
    ctx = make_ctx()
    log.info("worker iniciado; polling %s", _redact(ctx.queue_url))
    while True:
        resp = ctx.sqs.receive_message(QueueUrl=ctx.queue_url, MaxNumberOfMessages=10,
                                       WaitTimeSeconds=20, VisibilityTimeout=HEARTBEAT_VISIBILITY)
        for sqs_msg in resp.get("Messages", []):
            if process_message(sqs_msg, ctx):
                ctx.sqs.delete_message(QueueUrl=ctx.queue_url, ReceiptHandle=sqs_msg["ReceiptHandle"])
            # delete SOLO con resultado DURABLE completo; si no, SQS re-entrega -> DLQ.


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        log.info("worker detenido")
