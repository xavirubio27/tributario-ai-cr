#!/usr/bin/env python3
"""PoC C4-B3 / C2 — reconciliación (NEW-H3/H4).

S3 es la FUENTE DE VERDAD. Para cada RAW (`inbound-raw/<messageId>`) determina el estado por
CONJUNTO usando el MANIFEST inmutable:
  - terminal `rejected`/`quarantine` (clave exacta)      -> done
  - manifest presente: pending = expected - completed     -> complete | partial
  - sin manifest ni terminal                              -> orphan (sobre NO recuperable)

Evita prefijos ambiguos (abc vs abcd): markers de mensaje por CLAVE EXACTA; el conjunto
`completed` se lista con prefijo con DELIMITADOR final `completed/<messageId>/`.

NO lee el contenido del correo -> no revela datos personales. Inyectable para tests.
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
    refs = set()
    for obj in _list(ctx, prefix):
        name = obj["Key"][len(prefix):]
        if name.endswith(".json"):
            refs.add(name[:-len(".json")])
    return refs


def reconcile(ctx: W.Ctx, now: float | None = None) -> dict:
    now = now if now is not None else time.time()
    states = {"complete": 0, "partial": 0, "rejected": 0, "quarantine": 0, "orphan": 0}
    attention = []  # partial + orphan (requieren acción), sin PII
    total = 0
    for obj in _list(ctx, ctx.raw_prefix):
        message_id = obj["Key"][len(ctx.raw_prefix):]
        if not message_id or message_id.endswith("/"):
            continue
        total += 1
        age = int(now - obj["LastModified"].timestamp()) if hasattr(obj["LastModified"], "timestamp") else None

        if W._get_marker(ctx, W._marker_key(ctx, "rejected", message_id)) is not None:
            states["rejected"] += 1
            continue
        if W._get_marker(ctx, W._marker_key(ctx, "quarantine", message_id)) is not None:
            states["quarantine"] += 1
            continue
        manifest = W._get_marker(ctx, W._marker_key(ctx, "manifest", message_id))
        if manifest is None:
            states["orphan"] += 1
            attention.append({"message_id": message_id, "age_seconds": age,
                              "state": "orphan",
                              "reason": "no_manifest(notificacion perdida): sobre NO recuperable -> cuarentena manual, nunca MIME"})
            continue
        expected = set(manifest.get("expected_recipients", []))
        pending = expected - _completed_refs(ctx, message_id)
        if pending:
            states["partial"] += 1
            attention.append({"message_id": message_id, "age_seconds": age, "state": "partial",
                              "pending_count": len(pending), "expected_count": len(expected)})
        else:
            states["complete"] += 1

    return {"scanned_raw_objects": total, "states": states, "attention": attention,
            "note": "orphans/partials requieren accion; orphan sin manifest NO se enruta por MIME"}


def main() -> int:
    if boto3 is None:
        raise RuntimeError("boto3 no disponible; modo real requiere AWS")
    ctx = W.Ctx(s3=boto3.client("s3"), sqs=None, bucket=os.environ["RAW_BUCKET"],
                queue_url="", raw_prefix=os.environ.get("RAW_PREFIX", "inbound-raw/"),
                markers_prefix=os.environ.get("MARKERS_PREFIX", "markers/"))
    report = reconcile(ctx)
    print(json.dumps(report, indent=2))
    return 1 if (report["states"]["orphan"] or report["states"]["partial"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
