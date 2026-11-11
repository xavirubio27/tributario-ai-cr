#!/usr/bin/env python3
"""PoC C4-B3 / C2 — reconciliación (remediación final HIGH alertas durables + estado conflict).

S3 es la FUENTE DE VERDAD. Por cada RAW: terminal rejected/quarantine (clave exacta) -> done;
manifest -> complete|conflict|partial; sin manifest -> ORPHAN (sobre NO recuperable).

Alertas DURABLES (fix 1):
  - Se persiste `alerts/pending/<id>` ANTES de intentar publicar.
  - Se registra `alerts/sent/<id>` SOLO tras confirmación de publicación.
  - Si la publicación falla, el pending permanece y se REINTENTA en ejecuciones posteriores
    (incluso si el RAW ya está en cuarentena). `alert_sink(alert) -> bool` (True = publicado).
  - No hay ejecución automática: esta reconciliación es MANUAL y reproducible (ver README §Reconcile).

Estado `conflict` separado (fix 3): un mensaje con markers de conflicto NO se clasifica como
complete; genera alerta accionable por el mismo mecanismo durable.
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
    prefix = f"{ctx.markers_prefix}completed/{message_id}/"
    return {o["Key"][len(prefix):-len(".json")] for o in _list(ctx, prefix) if o["Key"].endswith(".json")}


def _has_conflict(ctx: W.Ctx, message_id: str) -> bool:
    prefix = f"{ctx.markers_prefix}conflict/{message_id}/"
    return any(True for _ in _list(ctx, prefix))


# ---------- ledger durable de alertas ----------
def _pending_key(ctx, aid):
    return f"{ctx.markers_prefix}alerts/pending/{aid}.json"


def _sent_key(ctx, aid):
    return f"{ctx.markers_prefix}alerts/sent/{aid}.json"


def _emit_durable_alert(ctx: W.Ctx, alert: dict, sink, now: int) -> str:
    aid = alert["id"]
    if W._get_marker(ctx, _sent_key(ctx, aid)) is not None:
        return "sent"
    # 1) persistir pending ANTES de publicar (idempotente).
    try:
        W._put_marker_if_absent(ctx, _pending_key(ctx, aid), {"schema": "alert/v1", **alert, "ts": now})
    except Exception:  # noqa: BLE001
        return "pending_write_failed"
    # 2) intentar publicar; 3) sent SOLO tras confirmación.
    if sink is not None:
        try:
            if bool(sink(alert)):
                try:
                    W._put_marker_if_absent(ctx, _sent_key(ctx, aid), {"schema": "alert-sent/v1", "id": aid, "ts": now})
                    return "sent"
                except Exception:  # noqa: BLE001
                    return "pending"
        except Exception:  # noqa: BLE001
            return "pending"
    return "pending"


def _retry_pending_alerts(ctx: W.Ctx, sink, now: int) -> int:
    """Reintenta pendientes sin `sent` (backlog), aunque el RAW ya esté en cuarentena."""
    if sink is None:
        return 0
    sent = 0
    prefix = f"{ctx.markers_prefix}alerts/pending/"
    for o in _list(ctx, prefix):
        if not o["Key"].endswith(".json"):
            continue
        aid = o["Key"][len(prefix):-len(".json")]
        if W._get_marker(ctx, _sent_key(ctx, aid)) is not None:
            continue
        alert = W._get_marker(ctx, o["Key"]) or {"id": aid}
        try:
            if bool(sink(alert)):
                W._put_marker_if_absent(ctx, _sent_key(ctx, aid), {"schema": "alert-sent/v1", "id": aid, "ts": now})
                sent += 1
        except Exception:  # noqa: BLE001
            pass
    return sent


def reconcile(ctx: W.Ctx, now: float | None = None, alert_sink=None, quarantine_orphans: bool = True) -> dict:
    now = int(now if now is not None else time.time())
    states = {"complete": 0, "partial": 0, "conflict": 0, "rejected": 0, "quarantine": 0, "orphan": 0}
    alerts = []
    retried = _retry_pending_alerts(ctx, alert_sink, now)   # backlog primero

    def act(alert):
        status = _emit_durable_alert(ctx, alert, alert_sink, now)
        alerts.append({**alert, "status": status})

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
            if quarantine_orphans:
                try:
                    W._put_marker_if_absent(ctx, W._marker_key(ctx, "quarantine", message_id), {
                        "schema": "quarantine/v2", "kind": "orphan_no_manifest", "event_id": message_id,
                        "age_seconds": age, "reason": "notificacion perdida; sobre NO recuperable (nunca MIME)",
                        "ts": now})
                except Exception:  # noqa: BLE001
                    pass
            act({"id": f"orphan-{message_id}", "level": "action_required", "state": "orphan",
                 "message_id": message_id, "age_seconds": age,
                 "action": "revisión manual; el tenant NO se resuelve automáticamente; nunca MIME"})
            continue
        pending = set(manifest.get("expected_recipients", [])) - _completed_refs(ctx, message_id)
        if pending:
            states["partial"] += 1
            act({"id": f"partial-{message_id}", "level": "action_required", "state": "partial",
                 "message_id": message_id, "pending_count": len(pending),
                 "action": "reprocesar/investigar recipients pendientes"})
        elif _has_conflict(ctx, message_id):
            states["conflict"] += 1   # NO se clasifica como complete
            act({"id": f"conflict-{message_id}", "level": "action_required", "state": "conflict",
                 "message_id": message_id, "action": "revisar evidencia en conflicto (canonical vs observed)"})
        else:
            states["complete"] += 1

    return {"scanned_raw_objects": total, "states": states, "alerts": alerts,
            "pending_retried_sent": retried,
            "note": "alertas durables (pending->sent); conflict != complete; orphan->cuarentena; nunca MIME"}


def main() -> int:
    if boto3 is None:
        raise RuntimeError("boto3 no disponible; modo real requiere AWS")
    ctx = W.Ctx(s3=boto3.client("s3"), sqs=None, bucket=os.environ["RAW_BUCKET"], queue_url="",
                raw_prefix=os.environ.get("RAW_PREFIX", "inbound-raw/"),
                markers_prefix=os.environ.get("MARKERS_PREFIX", "markers/"))
    sns_arn = os.environ.get("ALERTS_TOPIC_ARN")
    sns = boto3.client("sns") if sns_arn else None

    def sink(a) -> bool:
        if not sns:
            return False
        sns.publish(TopicArn=sns_arn, Subject="tribuu-poc reconcile alert", Message=json.dumps(a))
        return True  # solo si publish no lanzó

    report = reconcile(ctx, alert_sink=sink if sns else None)
    print(json.dumps(report, indent=2))
    return 1 if (report["states"]["orphan"] or report["states"]["partial"] or report["states"]["conflict"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
