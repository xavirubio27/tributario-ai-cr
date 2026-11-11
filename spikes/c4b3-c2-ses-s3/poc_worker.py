#!/usr/bin/env python3
"""PoC C4-B3 / C2 — worker consumidor de SQS (remediación final de bloqueantes).

SOLO PRUEBAS, SOLO EVIDENCIA SINTÉTICA. No es código productivo.

Fixes de esta ronda:
  1. Sin carrera Head/Get: se FIJA el VersionId del HeadObject y se lee ESA versión.
  2. Conflictos con locators COMPLETOS de ambas evidencias (canonical vs observed); nunca se
     confunde `conflict` con `completed` ni se sobrescribe el canónico (append-only).
  3. Sin clave global `quarantine/unknown.json`: cada notificación inválida tiene identidad
     propia (messageId válido, o digest del cuerpo) y cuarentena independiente.
  5. Comparación ÍNTEGRA del manifest existente con la nueva notificación (mismatch -> durable).
  6. Heartbeat: cierre con join y VERIFICACIÓN final (si falló, no se confirma SQS).

Invariante de aceptación: NUNCA se devuelve True (=> DeleteMessage) sin un resultado terminal
DURABLE y verificado (completed/rejected/quarantine/conflict-preservado).
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

try:
    import boto3
except Exception:  # noqa: BLE001
    boto3 = None

DEFAULT_MAX_BYTES = 64 * 1024 * 1024
READ_CHUNK = 1024 * 1024
HEARTBEAT_EVERY = 60
HEARTBEAT_VISIBILITY = 300
HEARTBEAT_JOIN_TIMEOUT = 5
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


def _redact(value: str | None) -> str:
    return "-" if not value else hmac.new(_LOG_SALT, value.encode(), hashlib.sha256).hexdigest()[:10]


def _rref(recipient: str) -> str:
    return hashlib.sha256(recipient.encode()).hexdigest()


def _error_code(exc: Exception) -> str | None:
    resp = getattr(exc, "response", None)
    if isinstance(resp, dict):
        return resp.get("Error", {}).get("Code")
    return getattr(exc, "code", None)


_ABSENT = {"NoSuchKey", "NoSuchVersion", "404", "NotFound"}
_EXISTS = {"PreconditionFailed", "412"}


def _canonical(payload: dict) -> bytes:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()


def _marker_key(ctx: Ctx, kind: str, message_id: str, *parts: str) -> str:
    if not parts:
        return f"{ctx.markers_prefix}{kind}/{message_id}.json"
    tail = "".join(f"{p}/" for p in parts[:-1]) + parts[-1]
    return f"{ctx.markers_prefix}{kind}/{message_id}/{tail}.json"


def _get_marker(ctx: Ctx, key: str) -> dict | None:
    try:
        obj = ctx.s3.get_object(Bucket=ctx.bucket, Key=key)
        return json.loads(obj["Body"].read())
    except Exception as exc:  # noqa: BLE001
        if _error_code(exc) in _ABSENT:
            return None
        raise


def _put_marker_if_absent(ctx: Ctx, key: str, payload: dict) -> tuple[str, dict]:
    """Escritura CONDICIONAL If-None-Match:*. 'created' se VERIFICA releyendo el contenido."""
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
    readback = _get_marker(ctx, key)
    if readback is None or _canonical(readback) != body:
        raise RuntimeError(f"marker no verificable: {key}")
    return "created", readback


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
                self.failed.set()
                return

    def __enter__(self):
        self._t.start()
        return self

    def stop_and_check(self) -> bool:
        """FAIL-CLOSED. Devuelve True si el heartbeat NO es seguro para confirmar SQS:
        - señala stop y hace join con timeout;
        - si el hilo SIGUE VIVO tras el join (p. ej. una renovación bloqueada), NO conocemos el
          resultado -> se considera INSEGURO (True);
        - si el hilo terminó, devuelve el estado de `failed`.
        Semántica inequívoca: True = inseguro/fallo (prohibir DeleteMessage); False = seguro.
        Idempotente."""
        self._stop.set()
        self._t.join(timeout=HEARTBEAT_JOIN_TIMEOUT)
        if self._t.is_alive():
            return True  # renovación en curso/indeterminada -> fail-closed
        return self.failed.is_set()

    def __exit__(self, *_):
        self.stop_and_check()


def validate_notification(note: dict, ctx: Ctx) -> dict:
    if not isinstance(note, dict) or note.get("notificationType") != "Received":
        raise SchemaError("notificationType!=Received")
    receipt, mail = note.get("receipt"), note.get("mail")
    if not isinstance(receipt, dict) or not isinstance(mail, dict):
        raise SchemaError("receipt/mail ausente")
    if receipt.get("action", {}).get("type") != "S3":
        raise SchemaError("action.type!=S3")
    message_id = mail.get("messageId")
    bucket = receipt["action"].get("bucketName")
    key = receipt["action"].get("objectKey")
    recipients = receipt.get("recipients")
    if not isinstance(message_id, str) or not message_id or "/" in message_id or "\n" in message_id:
        raise SchemaError("messageId invalido")
    if bucket != ctx.bucket:
        raise SchemaError("bucketName no coincide con el bucket configurado")
    if not isinstance(key, str) or key != f"{ctx.raw_prefix}{message_id}":
        raise SchemaError("objectKey no corresponde al messageId/prefijo")
    if not isinstance(recipients, list) or not recipients or not all(isinstance(r, str) and r for r in recipients):
        raise SchemaError("recipients invalido")
    return {"message_id": message_id, "bucket": bucket, "key": key, "recipients": recipients}


def _validate_manifest(existing: dict, message_id: str, bucket: str, key: str,
                       expected: list[str], recipients: list[str]) -> tuple[bool, str | None]:
    """Valida ESTRICTAMENTE un manifest reutilizado (sin coerción de tipos). No se reutiliza un
    manifest parcialmente válido: cualquier fallo -> cuarentena durable."""
    if not isinstance(existing, dict):
        return False, "corrupt"
    if existing.get("schema") != "manifest/v2":              # schema EXACTO
        return False, "schema"
    if not isinstance(existing.get("event_id"), str) or existing["event_id"] != message_id:
        return False, "event_id"
    obj = existing.get("object")
    if not isinstance(obj, dict):
        return False, "object_type"
    if not isinstance(obj.get("bucket"), str) or obj["bucket"] != bucket:
        return False, "object_bucket"
    if not isinstance(obj.get("key"), str) or obj["key"] != key:
        return False, "object_key"
    if not isinstance(obj.get("version_id"), (str, type(None))):  # contrato: str | None
        return False, "version_id_type"
    exp = existing.get("expected_recipients")
    if not isinstance(exp, list) or not exp or not all(isinstance(e, str) and e for e in exp):
        return False, "expected_type"                        # strings válidos, SIN coerción
    if sorted(set(exp)) != expected:
        return False, "recipients"
    clear = existing.get("recipients_clear")
    if not isinstance(clear, list) or not clear or not all(isinstance(r, str) and r for r in clear):
        return False, "recipients_clear_type"
    if sorted({_rref(r) for r in clear}) != sorted(set(exp)):
        return False, "recipients_clear_incoherent"
    return True, None


def _stream_sha256_size(ctx: Ctx, key: str, version_id: str | None, hb: Heartbeat) -> tuple[str, int]:
    # VersionId FIJADO: se lee exactamente la versión validada (sin carrera Head/Get).
    kwargs = {"Bucket": ctx.bucket, "Key": key}
    if version_id:
        kwargs["VersionId"] = version_id
    body = ctx.s3.get_object(**kwargs)["Body"]
    h, total = hashlib.sha256(), 0
    for chunk in iter(lambda: body.read(READ_CHUNK), b""):
        if hb.failed.is_set():
            raise RuntimeError("heartbeat_failed")
        total += len(chunk)
        if total > ctx.max_bytes:
            body.close()
            raise ValueError("oversize")
        h.update(chunk)
    return h.hexdigest(), total


def _quarantine(ctx: Ctx, qid: str, payload: dict) -> bool:
    try:
        _put_marker_if_absent(ctx, _marker_key(ctx, "quarantine", qid), payload)
        return True
    except Exception:  # noqa: BLE001
        return False


def process_message(sqs_msg: dict, ctx: Ctx) -> bool:
    raw_body = sqs_msg.get("Body", "")
    raw_digest = hashlib.sha256(raw_body.encode() if isinstance(raw_body, str) else bytes(raw_body)).hexdigest()
    now = int(sqs_msg.get("_now", time.time()))
    try:
        note = json.loads(raw_body)
        if "Message" in note and "notificationType" not in note:
            note = json.loads(note["Message"])
    except Exception:  # noqa: BLE001
        log.error("notificacion ilegible -> no borrar")
        return False

    try:
        v = validate_notification(note, ctx)
    except SchemaError as exc:
        mid = note.get("mail", {}).get("messageId") if isinstance(note, dict) else None
        # Identidad INDEPENDIENTE por notificación inválida: messageId válido o digest del cuerpo.
        qid = mid if (isinstance(mid, str) and mid and "/" not in mid) else f"raw-{raw_digest}"
        ok = _quarantine(ctx, qid, {"schema": "quarantine/v2", "kind": "schema_invalid",
                                    "event_id": mid, "raw_digest": raw_digest,
                                    "reason": str(exc), "ts": now})
        log.error("QUARANTINE schema qid=%s reason=%s durable=%s", _redact(qid), exc, ok)
        return ok

    message_id, bucket, key, recipients = v["message_id"], v["bucket"], v["key"], v["recipients"]
    expected = sorted({_rref(r) for r in recipients})

    with Heartbeat(ctx, sqs_msg.get("ReceiptHandle", "")) as hb:
        try:
            head = ctx.s3.head_object(Bucket=ctx.bucket, Key=key)
        except Exception:  # noqa: BLE001
            log.warning("HeadObject fallo key=%s -> reintento", _redact(key))
            return False
        version_id = head.get("VersionId")  # FIJADO

        # MANIFEST inmutable + comparación íntegra si ya existe (fix 5).
        manifest_key = _marker_key(ctx, "manifest", message_id)
        manifest = {"schema": "manifest/v2", "event_id": message_id,
                    "object": {"bucket": bucket, "key": key, "version_id": version_id},
                    "expected_recipients": expected, "recipients_clear": recipients, "ts": now}
        try:
            status, existing = _put_marker_if_absent(ctx, manifest_key, manifest)
        except Exception:  # noqa: BLE001
            log.error("manifest no durable msg=%s -> reintento", _redact(message_id))
            return False
        if status == "exists":
            # Validación ÍNTEGRA del manifest reutilizado (fix 4): schema/tipos, identidad y
            # coherencia recipients_clear <-> expected_recipients. VersionId NO se reutiliza
            # (la versión se toma del HEAD de esta invocación para poder detectar conflictos;
            # la mera existencia del manifest NO es idempotencia — eso lo da el marker completed).
            ok_m, reason = _validate_manifest(existing, message_id, bucket, key, expected, recipients)
            if not ok_m:
                okq = _quarantine(ctx, f"{message_id}", {
                    "schema": "quarantine/v2", "kind": f"manifest_{reason}", "event_id": message_id,
                    "existing": {"expected": existing.get("expected_recipients"),
                                 "object": existing.get("object")},
                    "incoming": {"expected": expected, "object": manifest["object"]}, "ts": now})
                log.error("MANIFEST_INCONSISTENTE msg=%s reason=%s durable=%s",
                          _redact(message_id), reason, okq)
                return okq
            manifest = existing
        expected = sorted(set(manifest["expected_recipients"]))

        try:
            sha_hex, size = _stream_sha256_size(ctx, key, version_id, hb)
        except ValueError:
            rkey = _marker_key(ctx, "rejected", message_id)
            ok = _quarantine_like_rejected(ctx, rkey, message_id, bucket, key, version_id, ctx.max_bytes, now)
            log.error("REJECTED oversize msg=%s durable=%s", _redact(message_id), ok)
            return ok
        except RuntimeError:
            log.warning("heartbeat fallo (descarga) msg=%s -> abortar", _redact(message_id))
            return False
        except Exception:  # noqa: BLE001
            log.warning("GetObject fallo key=%s -> reintento", _redact(key))
            return False

        observed_locator = {"bucket": bucket, "key": key, "version_id": version_id,
                            "sha256": sha_hex, "size_bytes": size}
        completed: set[str] = set()
        for recipient in recipients:
            if hb.failed.is_set():
                log.warning("heartbeat fallo (fan-out) msg=%s -> abortar", _redact(message_id))
                return False
            rref = _rref(recipient)
            ckey = _marker_key(ctx, "completed", message_id, rref)
            payload = {"schema": "completed/v2", "result": "captured", "event_id": message_id,
                       "recipient_ref": rref, "object": observed_locator, "ts": now}
            try:
                st, durable = _put_marker_if_absent(ctx, ckey, payload)
            except Exception:  # noqa: BLE001
                log.warning("completed no durable msg=%s rcpt=%s -> reintento",
                            _redact(message_id), _redact(recipient))
                return False
            if st == "exists" and durable.get("object", {}).get("sha256") != sha_hex:
                # CONFLICTO append-only con locators COMPLETOS de AMBAS evidencias (fix 2).
                conflict_key = _marker_key(ctx, "conflict", message_id, rref, sha_hex)
                try:
                    _put_marker_if_absent(ctx, conflict_key, {
                        "schema": "conflict/v2", "event_id": message_id, "recipient_ref": rref,
                        "canonical": durable.get("object"), "observed": observed_locator, "ts": now})
                    log.error("EVIDENCE_CONFLICT msg=%s rcpt=%s durable=yes",
                              _redact(message_id), _redact(recipient))
                except Exception:  # noqa: BLE001
                    return False
            completed.add(rref)

        if set(expected) - completed:
            log.warning("INCOMPLETO msg=%s -> no borrar", _redact(message_id))
            return False
        # VERIFICACIÓN FINAL (fix 6): stop_and_check detiene+join y evalúa el resultado;
        # un fallo de renovación (incluido durante el CIERRE) impide confirmar SQS.
        if hb.stop_and_check():
            log.warning("heartbeat fallo (cierre) msg=%s -> no confirmar", _redact(message_id))
            return False
        log.info("COMPLETO msg=%s recipients=%d size=%d sha=%s…",
                 _redact(message_id), len(expected), size, sha_hex[:12])
        return True


def _quarantine_like_rejected(ctx, rkey, message_id, bucket, key, version_id, limit, now) -> bool:
    try:
        _put_marker_if_absent(ctx, rkey, {
            "schema": "rejected/v2", "event_id": message_id, "reason": "oversize",
            "object": {"bucket": bucket, "key": key, "version_id": version_id},
            "limit_bytes": limit, "ts": now})
        return True
    except Exception:  # noqa: BLE001
        return False


def make_ctx() -> Ctx:
    if boto3 is None:
        raise RuntimeError("boto3 no disponible (solo ejecución real)")
    return Ctx(s3=boto3.client("s3"), sqs=boto3.client("sqs"),
               bucket=os.environ["RAW_BUCKET"], queue_url=os.environ["INTAKE_QUEUE_URL"],
               raw_prefix=os.environ.get("RAW_PREFIX", "inbound-raw/"),
               markers_prefix=os.environ.get("MARKERS_PREFIX", "markers/"))


def main() -> int:
    ctx = make_ctx()
    log.info("worker iniciado")
    while True:
        resp = ctx.sqs.receive_message(QueueUrl=ctx.queue_url, MaxNumberOfMessages=10,
                                       WaitTimeSeconds=20, VisibilityTimeout=HEARTBEAT_VISIBILITY)
        for sqs_msg in resp.get("Messages", []):
            if process_message(sqs_msg, ctx):
                ctx.sqs.delete_message(QueueUrl=ctx.queue_url, ReceiptHandle=sqs_msg["ReceiptHandle"])


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        log.info("worker detenido")
