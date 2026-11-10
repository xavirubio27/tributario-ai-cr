"""Pruebas locales deterministas de la PoC C4-B3/C2 (sin AWS, stdlib + fakes).

Ejecutar:  python3 tests/test_poc.py     (desde spikes/c4b3-c2-ses-s3/)
"""
from __future__ import annotations

import json
import os
import sys
import threading
import unittest

_HERE = os.path.dirname(__file__)
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.dirname(_HERE))

import poc_reconcile as R  # noqa: E402
import poc_worker as W  # noqa: E402
from fakes import CollectingSink, FakeS3, FakeSQS  # noqa: E402

BUCKET, RAWP = "tribuu-poc-bucket", "inbound-raw/"


def make_note(mid, recipients, bucket=BUCKET, rawp=RAWP, mail=True):
    body = {"notificationType": "Received", "receipt": {"recipients": recipients,
            "action": {"type": "S3", "bucketName": bucket, "objectKey": rawp + (mid or "")}}}
    if mail:
        body["mail"] = {"messageId": mid}
    return {"Body": json.dumps(body), "ReceiptHandle": "rh-" + (mid or "x"), "_now": 1000}


def ctx(s3, sqs=None, max_bytes=1024):
    return W.Ctx(s3=s3, sqs=sqs or FakeSQS(), bucket=BUCKET, queue_url="q",
                 raw_prefix=RAWP, markers_prefix="markers/", max_bytes=max_bytes)


def completed_keys(s3):
    return [k for k in s3.objects if k.startswith("markers/completed/")]


class PoCTests(unittest.TestCase):

    def test_01_two_workers_same_marker(self):
        s3 = FakeS3(); s3.seed_raw(RAWP + "m1", b"hello"); c = ctx(s3)
        self.assertTrue(W.process_message(make_note("m1", ["a@d"]), c))
        self.assertTrue(W.process_message(make_note("m1", ["a@d"]), c))
        self.assertEqual(len(completed_keys(s3)), 1)

    def test_02_conflict_full_locators(self):
        s3 = FakeS3(); s3.seed_raw(RAWP + "m2", b"body-v1"); c = ctx(s3)
        self.assertTrue(W.process_message(make_note("m2", ["a@d"]), c))
        ckey = completed_keys(s3)[0]; before = bytes(s3.objects[ckey]["versions"][s3.objects[ckey]["latest"]])
        s3.seed_raw(RAWP + "m2", b"body-v2-DIFERENTE")
        self.assertTrue(W.process_message(make_note("m2", ["a@d"]), c))
        conflicts = [k for k in s3.objects if k.startswith("markers/conflict/m2/")]
        self.assertEqual(len(conflicts), 1)
        conf = W._get_marker(c, conflicts[0])
        for side in ("canonical", "observed"):   # locators COMPLETOS de ambas evidencias
            for f in ("bucket", "key", "version_id", "sha256", "size_bytes"):
                self.assertIn(f, conf[side])
        self.assertNotEqual(conf["canonical"]["sha256"], conf["observed"]["sha256"])
        after = bytes(s3.objects[ckey]["versions"][s3.objects[ckey]["latest"]])
        self.assertEqual(before, after)  # completed NO sobrescrito

    def test_03_multi_recipient_only_A(self):
        s3 = FakeS3(); s3.seed_raw(RAWP + "m3", b"x"); c = ctx(s3)
        s3.fail_put_keys.add(f"markers/completed/m3/{W._rref('b@d')}.json")
        self.assertFalse(W.process_message(make_note("m3", ["a@d", "b@d"]), c))
        rep = R.reconcile(c, now=2000, quarantine_orphans=False)
        self.assertEqual(rep["states"]["partial"], 1)

    def test_04_id_collision_abc_abcd(self):
        s3 = FakeS3(); s3.seed_raw(RAWP + "abc", b"x"); s3.seed_raw(RAWP + "abcd", b"y"); c = ctx(s3)
        self.assertTrue(W.process_message(make_note("abc", ["a@d"]), c))
        self.assertTrue(W.process_message(make_note("abcd", ["a@d"]), c))
        self.assertEqual(R._completed_refs(c, "abc"), {W._rref("a@d")})
        self.assertEqual(R._completed_refs(c, "abcd"), {W._rref("a@d")})

    def test_05_sns_lost_orphan_quarantined_and_alerted(self):
        s3 = FakeS3(); s3.seed_raw(RAWP + "m5", b"x", lm_ts=1000.0); c = ctx(s3)
        sink = CollectingSink()
        rep = R.reconcile(c, now=4000, alert_sink=sink)
        self.assertEqual(rep["states"]["orphan"], 1)
        self.assertTrue(s3.exists("markers/quarantine/m5.json"))          # cuarentena DURABLE
        self.assertEqual(sink.alerts[0]["level"], "action_required")       # alerta accionable
        self.assertTrue(sink.alerts[0]["quarantine_durable"])
        rep2 = R.reconcile(c, now=4100, alert_sink=CollectingSink())       # ya no re-alerta orphan
        self.assertEqual(rep2["states"]["orphan"], 0)
        self.assertEqual(rep2["states"]["quarantine"], 1)

    def test_06_no_recipients_quarantine(self):
        s3 = FakeS3(); s3.seed_raw(RAWP + "m6", b"x"); c = ctx(s3)
        self.assertTrue(W.process_message(make_note("m6", []), c))
        self.assertTrue(s3.exists("markers/quarantine/m6.json"))

    def test_07_quarantine_write_fail(self):
        s3 = FakeS3(); s3.seed_raw(RAWP + "m7", b"x"); c = ctx(s3)
        s3.fail_put_keys.add("markers/quarantine/m7.json")
        self.assertFalse(W.process_message(make_note("m7", []), c))
        self.assertFalse(s3.exists("markers/quarantine/m7.json"))

    def test_08_heartbeat_already_failed(self):
        class DeadHB:
            def __init__(self, *a, **k):
                self.failed = threading.Event(); self.failed.set()
            def __enter__(self): return self
            def __exit__(self, *a): return False
        s3 = FakeS3(); s3.seed_raw(RAWP + "m8", b"abc"); c = ctx(s3)
        orig = W.Heartbeat; W.Heartbeat = DeadHB
        try:
            self.assertFalse(W.process_message(make_note("m8", ["a@d"]), c))
        finally:
            W.Heartbeat = orig
        self.assertEqual(completed_keys(s3), [])

    def test_08b_heartbeat_async_failure(self):
        # Fallo ASÍNCRONO real: el hilo de heartbeat falla durante una descarga lenta.
        s3 = FakeS3(); s3.seed_raw(RAWP + "ha", b"payload", slow_delay=0.05)
        c = ctx(s3, sqs=FakeSQS(fail_visibility=True), max_bytes=10_000)
        orig_every = W.HEARTBEAT_EVERY; W.HEARTBEAT_EVERY = 0.01
        try:
            self.assertFalse(W.process_message(make_note("ha", ["a@d"]), c))
        finally:
            W.HEARTBEAT_EVERY = orig_every
        self.assertEqual(completed_keys(s3), [])  # nada confirmado

    def test_09_oversize_download_error(self):
        s3 = FakeS3(); s3.seed_raw(RAWP + "big", b"Z" * 5000); c = ctx(s3)
        self.assertTrue(W.process_message(make_note("big", ["a@d"]), c))
        self.assertTrue(s3.exists("markers/rejected/big.json"))
        s3b = FakeS3(); s3b.seed_raw(RAWP + "derr", b"x"); s3b.fail_get_keys.add(RAWP + "derr")
        self.assertFalse(W.process_message(make_note("derr", ["a@d"]), ctx(s3b)))

    def test_10_restart_idempotent(self):
        s3 = FakeS3(); s3.seed_raw(RAWP + "m10", b"x"); c = ctx(s3)
        self.assertTrue(W.process_message(make_note("m10", ["a@d", "b@d"]), c))
        n = len(completed_keys(s3))
        self.assertTrue(W.process_message(make_note("m10", ["a@d", "b@d"]), c))
        self.assertEqual(len(completed_keys(s3)), n)

    def test_11_wrong_bucket(self):
        s3 = FakeS3(); s3.seed_raw(RAWP + "m11", b"x"); c = ctx(s3)
        self.assertTrue(W.process_message(make_note("m11", ["a@d"], bucket="otro-bucket"), c))
        self.assertTrue(s3.exists("markers/quarantine/m11.json"))
        self.assertEqual(completed_keys(s3), [])

    def test_12_version_pinned_no_race(self):
        # Head fija V1; aunque llegue V2, se lee EXACTAMENTE V1 (sin carrera Head/Get).
        s3 = FakeS3(); v1 = s3.seed_raw(RAWP + "mv", b"VERSION-UNO"); c = ctx(s3, max_bytes=1 << 20)
        orig_get = s3.get_object
        def racing_get(**kw):
            if kw.get("VersionId") is None and kw.get("Key") == RAWP + "mv":
                s3.seed_raw(RAWP + "mv", b"VERSION-DOS-distinta")  # cambia justo antes
            return orig_get(**kw)
        s3.get_object = racing_get
        self.assertTrue(W.process_message(make_note("mv", ["a@d"]), c))
        marker = W._get_marker(c, f"markers/completed/mv/{W._rref('a@d')}.json")
        self.assertEqual(marker["object"]["version_id"], v1)  # fijado a V1

    def test_13_manifest_mismatch(self):
        s3 = FakeS3(); s3.seed_raw(RAWP + "mm", b"x"); c = ctx(s3)
        self.assertTrue(W.process_message(make_note("mm", ["a@d"]), c))
        self.assertTrue(W.process_message(make_note("mm", ["a@d", "b@d"]), c))  # expected distinto
        q = W._get_marker(c, "markers/quarantine/mm.json")
        self.assertIsNotNone(q)
        self.assertEqual(q["kind"], "manifest_mismatch")

    def test_14_quarantine_independent_identity(self):
        # Dos notificaciones inválidas SIN messageId -> dos cuarentenas INDEPENDIENTES (no 'unknown').
        s3 = FakeS3(); c = ctx(s3)
        n1 = {"Body": json.dumps({"notificationType": "Received", "receipt": {}}), "ReceiptHandle": "r1", "_now": 1}
        n2 = {"Body": json.dumps({"notificationType": "Received", "receipt": {}, "x": 2}), "ReceiptHandle": "r2", "_now": 1}
        self.assertTrue(W.process_message(n1, c))
        self.assertTrue(W.process_message(n2, c))
        qk = [k for k in s3.objects if k.startswith("markers/quarantine/raw-")]
        self.assertEqual(len(qk), 2)
        self.assertFalse(s3.exists("markers/quarantine/unknown.json"))

    def test_15_concurrency_real_threads(self):
        # 8 hilos SIMULTÁNEOS procesando el MISMO mensaje: un único completed, sin duplicar.
        s3 = FakeS3(); s3.seed_raw(RAWP + "cc", b"x"); c = ctx(s3)
        results, barrier = [], threading.Barrier(8)
        def run():
            barrier.wait()
            results.append(W.process_message(make_note("cc", ["a@d"]), c))
        ths = [threading.Thread(target=run) for _ in range(8)]
        [t.start() for t in ths]; [t.join() for t in ths]
        self.assertTrue(all(results))
        self.assertEqual(len(completed_keys(s3)), 1)
        self.assertEqual(len([k for k in s3.objects if k == "markers/manifest/cc.json"]), 1)

    def test_16_raw_reference_fields(self):
        s3 = FakeS3(); s3.seed_raw(RAWP + "m16", b"payload"); c = ctx(s3)
        self.assertTrue(W.process_message(make_note("m16", ["a@d"]), c))
        o = W._get_marker(c, f"markers/completed/m16/{W._rref('a@d')}.json")["object"]
        for f in ("bucket", "key", "version_id", "sha256", "size_bytes"):
            self.assertIn(f, o)

    def test_17_acceptance_no_delete_without_durable(self):
        # Criterio de aceptación: True SOLO si hay terminal durable; False si no.
        cases_false = []
        # B-fail (incompleto)
        s3 = FakeS3(); s3.seed_raw(RAWP + "a1", b"x"); c = ctx(s3)
        s3.fail_put_keys.add(f"markers/completed/a1/{W._rref('b@d')}.json")
        cases_false.append(W.process_message(make_note("a1", ["a@d", "b@d"]), c))
        # manifest-fail
        s3 = FakeS3(); s3.seed_raw(RAWP + "a2", b"x"); c = ctx(s3); s3.fail_put_keys.add("markers/manifest/a2.json")
        cases_false.append(W.process_message(make_note("a2", ["a@d"]), c))
        # download-fail
        s3 = FakeS3(); s3.seed_raw(RAWP + "a3", b"x"); s3.fail_get_keys.add(RAWP + "a3"); c = ctx(s3)
        cases_false.append(W.process_message(make_note("a3", ["a@d"]), c))
        self.assertFalse(any(cases_false))
        # Durables -> True con marker presente
        s3 = FakeS3(); s3.seed_raw(RAWP + "ok", b"x"); c = ctx(s3)
        self.assertTrue(W.process_message(make_note("ok", ["a@d"]), c))
        self.assertTrue(s3.exists(f"markers/completed/ok/{W._rref('a@d')}.json"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
