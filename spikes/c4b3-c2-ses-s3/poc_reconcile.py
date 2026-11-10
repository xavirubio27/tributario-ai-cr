#!/usr/bin/env python3
"""PoC C4-B3 / C2 — reconciliación (INFRA-H3).

S3 es la FUENTE DE VERDAD. Compara los objetos RAW (`inbound-raw/`) con el ledger durable de
resultados (`markers/{processed,quarantine,rejected}/`). Reporta HUÉRFANOS: RAW sin ningún
marker de resultado. Para cada huérfano registra identificador (messageId = clave S3, no PII),
antigüedad y motivo. NO lee el contenido del correo → no revela datos personales.

SOLO PRUEBAS. Ejecutar con credenciales temporales scoped:
  RAW_BUCKET=... RAW_PREFIX=inbound-raw/ MARKERS_PREFIX=markers/ python3 poc_reconcile.py
"""
from __future__ import annotations

import json
import os
import time

import boto3

_s3 = boto3.client("s3")
_BUCKET = os.environ["RAW_BUCKET"]
_RAW_PREFIX = os.environ.get("RAW_PREFIX", "inbound-raw/")
_MARKERS_PREFIX = os.environ.get("MARKERS_PREFIX", "markers/")


def _list_keys(prefix: str):
    paginator = _s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=_BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []):
            yield obj["Key"], obj["LastModified"]


def _has_marker(message_id: str) -> str | None:
    """Devuelve el tipo de marker si existe alguno para el messageId; si no, None."""
    for kind in ("processed", "quarantine", "rejected"):
        prefix = f"{_MARKERS_PREFIX}{kind}/{message_id}"
        resp = _s3.list_objects_v2(Bucket=_BUCKET, Prefix=prefix, MaxKeys=1)
        if resp.get("KeyCount", 0) > 0:
            return kind
    return None


def main() -> int:
    now = time.time()
    orphans = []
    total = 0
    for key, last_modified in _list_keys(_RAW_PREFIX):
        message_id = key[len(_RAW_PREFIX):]
        if not message_id or message_id.endswith("/"):
            continue
        total += 1
        marker = _has_marker(message_id)
        if marker is None:
            age_s = int(now - last_modified.timestamp())
            orphans.append({
                "message_id": message_id,        # id de SES, no PII
                "age_seconds": age_s,
                "reason": "no_result_marker(processed/quarantine/rejected absent)",
            })
    report = {
        "scanned_raw_objects": total,
        "orphans": len(orphans),
        "detail": orphans,
        "note": "orphans sin recipients autoritativos NO se enrutan por MIME -> cuarentena manual",
    }
    print(json.dumps(report, indent=2))
    return 1 if orphans else 0


if __name__ == "__main__":
    raise SystemExit(main())
