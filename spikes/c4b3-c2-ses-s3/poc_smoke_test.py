#!/usr/bin/env python3
"""PoC C4-B3 / C2 — smoke test local (sin AWS, con fakes).

Demuestra de punta a punta, en memoria:
  1) captura feliz multi-recipient (A y B) -> markers completed + manifest,
  2) objeto huérfano (notificación perdida) -> reconciliación lo marca orphan,
  3) sin recipients autoritativos -> cuarentena durable,
y corre la reconciliación final. No toca AWS. Ejecutar:  python3 poc_smoke_test.py
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "tests"))
sys.path.insert(0, os.path.dirname(__file__))

import poc_reconcile as R  # noqa: E402
import poc_worker as W  # noqa: E402
from fakes import FakeS3, FakeSQS  # noqa: E402

BUCKET, RAWP = "tribuu-poc-bucket", "inbound-raw/"


def note(mid, recipients, bucket=BUCKET):
    return {"Body": json.dumps({
        "notificationType": "Received", "mail": {"messageId": mid},
        "receipt": {"recipients": recipients,
                    "action": {"type": "S3", "bucketName": bucket, "objectKey": RAWP + mid}}}),
        "ReceiptHandle": "rh-" + mid, "_now": 1000}


def main() -> int:
    s3 = FakeS3()
    ctx = W.Ctx(s3=s3, sqs=FakeSQS(), bucket=BUCKET, queue_url="q", max_bytes=64 * 1024 * 1024)

    # 1) feliz multi-recipient
    s3.seed_raw(RAWP + "happy", b"factura-xml-sintetica")
    ok = W.process_message(note("happy", ["emp-a@inbox", "emp-b@inbox"]), ctx)
    print(f"[1] happy A&B -> durable={ok}")

    # 2) huérfano: RAW sin procesar (notificación perdida)
    s3.seed_raw(RAWP + "orphan", b"recibo-sin-notificacion", lm_ts=900.0)

    # 3) sin recipients autoritativos -> cuarentena
    s3.seed_raw(RAWP + "noauth", b"x")
    okq = W.process_message(note("noauth", []), ctx)
    print(f"[3] sin recipients -> quarantine durable={okq}")

    print("\nmarkers S3:")
    for k in sorted(s3.objects):
        if k.startswith("markers/"):
            print("  ", k)

    print("\nreconciliación:")
    print(json.dumps(R.reconcile(ctx, now=5000), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
