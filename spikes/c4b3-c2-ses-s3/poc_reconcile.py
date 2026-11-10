#!/usr/bin/env python3
"""PoC C4-B3 / C2 — reconciliación (fix 4: cuarentena durable + alerta accionable).

S3 es la FUENTE DE VERDAD. Para cada RAW determina el estado por CONJUNTO vía el MANIFEST:
  terminal rejected/quarantine (clave exacta) -> done ; manifest -> complete|partial ;
  sin manifest ni terminal -> ORPHAN (sobre NO recuperable).

Acciones: los ORPHAN se ponen en CUARENTENA DURABLE (escritura condicional, idempotente) y se
emite una ALERTA ACCIONABLE; los PARTIAL emiten alerta de reproceso. `alert_sink` es inyectable
(en producción publica al SNS de alertas; en tests, recoge). Claves exactas con delimitador
(sin prefijos ambiguos). No lee el contenido del correo -> sin PII.
"""
from __future__ import annotations

import json
import os
import time

import poc_worker as W

try:
    import boto3
except Exception:  # noqa: BLE001
    boto3 = None


def _list(ctx: W.Ctx, prefix: str):
    token = None
    while True:
        kw = {"Bucket": ctx.bucket, "Prefix": prefix}
        if token:
            kw["ContinuationToken"] = token
        resp = ctx.s3.list_objects_v2(**kw)
        for obj in resp.get("Contents", []):
            yield obj
        if not resp.get("IsTruncated"):
            return
        token = resp.get("NextContinuationToken")


def _completed_refs(ctx: W.Ctx, message_id: str) -> set[str]:
    prefix = f"{ctx.markers_prefix}completed/{message_id}/"  # delimitador final -> sin ambigüedad
    return {obj["Key"][len(prefix):-len(".json")] for obj in _list(ctx, prefix)
            if obj["Key"].endswith(".json")}


def reconcile(ctx: W.Ctx, now: float | None = None, alert_sink=None, quarantine_orphans: bool = True) -> dict:
    now = now if now is not None else time.time()
    states = {"complete": 0, "partial": 0, "rejected": 0, "quarantine": 0, "orphan": 0}
    alerts = []

    def alert(a: dict):
        alerts.append(a)
        if alert_sink:
            alert_sink(a)

    total = 0
    for obj in _list(ctx, ctx.raw_prefix):
        message_id = obj["Key"][len(ctx.raw_prefix):]
        if not message_id or message_id.endswith("/"):
            continue
        total += 1
        lm = obj.get("LastModified")
        age = int(now - lm.timestamp()) if hasattr(lm, "timestamp") else None

        if W._get_marker(ctx, W._marker_key(ctx, "rejected", message_id)) is not None:
            states["rejected"] += 1
            continue
        if W._get_marker(ctx, W._marker_key(ctx, "quarantine", message_id)) is not None:
            states["quarantine"] += 1
            continue
        manifest = W._get_marker(ctx, W._marker_key(ctx, "manifest", message_id))
        if manifest is None:
            states["orphan"] += 1
            durable = False
            if quarantine_orphans:
                try:
                    W._put_marker_if_absent(ctx, W._marker_key(ctx, "quarantine", message_id), {
                        "schema": "quarantine/v2", "kind": "orphan_no_manifest",
                        "event_id": message_id, "age_seconds": age,
                        "reason": "notificacion perdida; sobre NO recuperable (nunca MIME)",
                        "ts": int(now)})
                    durable = True
                except Exception:  # noqa: BLE001
                    durable = False
            alert({"level": "action_required", "state": "orphan", "message_id": message_id,
                   "age_seconds": age, "quarantine_durable": durable,
                   "action": "revisión manual; el tenant NO se resuelve automáticamente; nunca MIME"})
            continue
        pending = set(manifest.get("expected_recipients", [])) - _completed_refs(ctx, message_id)
        if pending:
            states["partial"] += 1
            alert({"level": "action_required", "state": "partial", "message_id": message_id,
                   "age_seconds": age, "pending_count": len(pending),
                   "action": "reprocesar/investigar recipients pendientes"})
        else:
            states["complete"] += 1

    return {"scanned_raw_objects": total, "states": states, "alerts": alerts,
            "note": "orphan -> cuarentena durable + alerta; partial -> alerta; nunca MIME"}


def main() -> int:
    if boto3 is None:
        raise RuntimeError("boto3 no disponible; modo real requiere AWS")
    ctx = W.Ctx(s3=boto3.client("s3"), sqs=None, bucket=os.environ["RAW_BUCKET"],
                queue_url="", raw_prefix=os.environ.get("RAW_PREFIX", "inbound-raw/"),
                markers_prefix=os.environ.get("MARKERS_PREFIX", "markers/"))

    import boto3 as _b
    sns_arn = os.environ.get("ALERTS_TOPIC_ARN")
    sns = _b.client("sns") if sns_arn else None

    def sink(a):
        if sns:
            sns.publish(TopicArn=sns_arn, Subject="tribuu-poc reconcile alert",
                        Message=json.dumps(a))

    report = reconcile(ctx, alert_sink=sink if sns else None)
    print(json.dumps(report, indent=2))
    return 1 if (report["states"]["orphan"] or report["states"]["partial"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
