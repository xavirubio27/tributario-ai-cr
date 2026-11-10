"""Pruebas locales deterministas de la PoC C4-B3/C2 (sin AWS, stdlib + fakes).

Ejecutar:  python3 -m unittest discover -s tests   (desde spikes/c4b3-c2-ses-s3/)
Cubre los 12 escenarios obligatorios + fallo de escritura de manifest + concurrencia.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import unittest

_HERE = os.path.dirname(__file__)
sys.path.insert(0, _HERE)                      # fakes
sys.path.insert(0, os.path.dirname(_HERE))     # poc_worker / poc_reconcile

import poc_reconcile as R  # noqa: E402
import poc_worker as W  # noqa: E402
from fakes import FakeS3, FakeSQS  # noqa: E402

BUCKET = "tribuu-poc-bucket"
RAWP = "inbound-raw/"


def make_note(mid, recipients, bucket=BUCKET, rawp=RAWP):
    return {
        "Body": json.dumps({
            "notificationType": "Received",
            "mail": {"messageId": mid},
            "receipt": {"recipients": recipients,
                        "action": {"type": "S3", "bucketName": bucket, "objectKey": rawp + mid}},
        }),
        "ReceiptHandle": "rh-" + mid, "_now": 1000,
    }


def ctx(s3, sqs=None, max_bytes=1024):
    return W.Ctx(s3=s3, sqs=sqs or FakeSQS(), bucket=BUCKET, queue_url="q",
                 raw_prefix=RAWP, markers_prefix="markers/", max_bytes=max_bytes)


def completed_keys(s3):
    return [k for k in s3.objects if k.startswith("markers/completed/")]


class PoCTests(unittest.TestCase):

    def test_01_two_workers_same_marker(self):
        s3 = FakeS3(); s3.seed_raw(RAWP + "m1", b"hello")
        c = ctx(s3)
        self.assertTrue(W.process_message(make_note("m1", ["a@d"]), c))
        self.assertTrue(W.process_message(make_note("m1", ["a@d"]), c))  # segundo worker / reintento
        self.assertEqual(len(completed_keys(s3)), 1)  # un único marker (condicional)

    def test_02_existing_marker_diff_hash_conflict(self):
        s3 = FakeS3(); s3.seed_raw(RAWP + "m2", b"body-v1")
        c = ctx(s3)
        self.assertTrue(W.process_message(make_note("m2", ["a@d"]), c))
        before = dict(s3.objects[[k for k in completed_keys(s3)][0]])
        s3.seed_raw(RAWP + "m2", b"body-v2-DIFERENTE")  # misma clave, contenido distinto
        self.assertTrue(W.process_message(make_note("m2", ["a@d"]), c))
        conflicts = [k for k in s3.objects if k.startswith("markers/conflict/m2/")]
        self.assertEqual(len(conflicts), 1)  # append-only
        after = s3.objects[[k for k in completed_keys(s3)][0]]
        self.assertEqual(before["body"], after["body"])  # canónico NO sobrescrito

    def test_03_multi_recipient_only_A(self):
        s3 = FakeS3(); s3.seed_raw(RAWP + "m3", b"x")
        c = ctx(s3)
        rref_b = W._rref("b@d")
        s3.fail_put_keys.add(f"markers/completed/m3/{rref_b}.json")
        self.assertFalse(W.process_message(make_note("m3", ["a@d", "b@d"]), c))  # no durable completo
        self.assertTrue(s3.exists(f"markers/completed/m3/{W._rref('a@d')}.json"))
        rep = R.reconcile(c, now=2000)
        self.assertEqual(rep["states"]["partial"], 1)
        self.assertEqual(rep["attention"][0]["pending_count"], 1)

    def test_04_id_collision_abc_abcd(self):
        s3 = FakeS3(); s3.seed_raw(RAWP + "abc", b"x"); s3.seed_raw(RAWP + "abcd", b"y")
        c = ctx(s3)
        self.assertTrue(W.process_message(make_note("abc", ["a@d"]), c))
        self.assertTrue(W.process_message(make_note("abcd", ["a@d"]), c))
        self.assertEqual(R._completed_refs(c, "abc"), {W._rref("a@d")})
        self.assertEqual(R._completed_refs(c, "abcd"), {W._rref("a@d")})  # no se mezclan
        rep = R.reconcile(c, now=2000)
        self.assertEqual(rep["states"]["complete"], 2)

    def test_05_sns_lost_orphan(self):
        s3 = FakeS3(); s3.seed_raw(RAWP + "m5", b"x", lm_ts=1000.0)
        c = ctx(s3)
        rep = R.reconcile(c, now=4000)
        self.assertEqual(rep["states"]["orphan"], 1)
        self.assertEqual(rep["attention"][0]["state"], "orphan")
        self.assertIn("no_manifest", rep["attention"][0]["reason"])

    def test_06_no_recipients_quarantine(self):
        s3 = FakeS3(); s3.seed_raw(RAWP + "m6", b"x")
        c = ctx(s3)
        self.assertTrue(W.process_message(make_note("m6", []), c))  # recipients vacío -> schema
        self.assertTrue(s3.exists("markers/quarantine/m6.json"))

    def test_07_quarantine_write_fail(self):
        s3 = FakeS3(); s3.seed_raw(RAWP + "m7", b"x")
        c = ctx(s3)
        s3.fail_put_keys.add("markers/quarantine/m7.json")
        self.assertFalse(W.process_message(make_note("m7", []), c))  # no durable -> no borrar
        self.assertFalse(s3.exists("markers/quarantine/m7.json"))

    def test_08_heartbeat_failure(self):
        class DeadHB:
            def __init__(self, *a, **k):
                self.failed = threading.Event(); self.failed.set()
            def __enter__(self): return self
            def __exit__(self, *a): return False
        s3 = FakeS3(); s3.seed_raw(RAWP + "m8", b"abc")
        c = ctx(s3)
        orig = W.Heartbeat
        W.Heartbeat = DeadHB
        try:
            self.assertFalse(W.process_message(make_note("m8", ["a@d"]), c))
        finally:
            W.Heartbeat = orig
        self.assertEqual(completed_keys(s3), [])  # nada capturado

    def test_09_oversize_download_error(self):
        # oversize -> rejected durable
        s3 = FakeS3(); s3.seed_raw(RAWP + "big", b"Z" * 5000)  # > max_bytes(1024)
        c = ctx(s3)
        self.assertTrue(W.process_message(make_note("big", ["a@d"]), c))
        self.assertTrue(s3.exists("markers/rejected/big.json"))
        self.assertEqual(completed_keys(s3), [])
        # error de descarga -> no durable
        s3b = FakeS3(); s3b.seed_raw(RAWP + "derr", b"x"); s3b.fail_get_keys.add(RAWP + "derr")
        cb = ctx(s3b)
        self.assertFalse(W.process_message(make_note("derr", ["a@d"]), cb))

    def test_10_restart_redelivery_idempotent(self):
        s3 = FakeS3(); s3.seed_raw(RAWP + "m10", b"x")
        c = ctx(s3)
        self.assertTrue(W.process_message(make_note("m10", ["a@d", "b@d"]), c))
        n_completed = len(completed_keys(s3))
        self.assertTrue(W.process_message(make_note("m10", ["a@d", "b@d"]), c))  # reentrega
        self.assertEqual(len(completed_keys(s3)), n_completed)  # sin duplicar

    def test_11_wrong_bucket(self):
        s3 = FakeS3(); s3.seed_raw(RAWP + "m11", b"x")
        c = ctx(s3)
        note = make_note("m11", ["a@d"], bucket="otro-bucket-ajeno")
        self.assertTrue(W.process_message(note, c))  # terminal via cuarentena
        self.assertTrue(s3.exists("markers/quarantine/m11.json"))
        self.assertEqual(completed_keys(s3), [])

    def test_12_no_delete_without_durable(self):
        # Reúne casos no-durables: deben devolver False (=> no DeleteMessage).
        # B-fail
        s3 = FakeS3(); s3.seed_raw(RAWP + "c1", b"x"); c = ctx(s3)
        s3.fail_put_keys.add(f"markers/completed/c1/{W._rref('b@d')}.json")
        self.assertFalse(W.process_message(make_note("c1", ["a@d", "b@d"]), c))
        # manifest-fail
        s3 = FakeS3(); s3.seed_raw(RAWP + "c2", b"x"); c = ctx(s3)
        s3.fail_put_keys.add("markers/manifest/c2.json")
        self.assertFalse(W.process_message(make_note("c2", ["a@d"]), c))
        # download-fail
        s3 = FakeS3(); s3.seed_raw(RAWP + "c3", b"x"); s3.fail_get_keys.add(RAWP + "c3"); c = ctx(s3)
        self.assertFalse(W.process_message(make_note("c3", ["a@d"]), c))

    def test_13_manifest_write_failure(self):
        s3 = FakeS3(); s3.seed_raw(RAWP + "m13", b"x")
        c = ctx(s3)
        s3.fail_put_keys.add("markers/manifest/m13.json")
        self.assertFalse(W.process_message(make_note("m13", ["a@d"]), c))
        self.assertFalse(s3.exists("markers/manifest/m13.json"))
        self.assertEqual(completed_keys(s3), [])

    def test_14_manifest_concurrency_shared_store(self):
        # Dos "workers" sobre el mismo store: el segundo reutiliza el manifest del primero.
        s3 = FakeS3(); s3.seed_raw(RAWP + "m14", b"x")
        c = ctx(s3)
        self.assertTrue(W.process_message(make_note("m14", ["a@d"]), c))
        manifest = W._get_marker(c, "markers/manifest/m14.json")
        self.assertEqual(set(manifest["expected_recipients"]), {W._rref("a@d")})
        # un segundo evento con el MISMO messageId no crea un manifest nuevo (condicional)
        puts_before = list(s3.put_calls)
        self.assertTrue(W.process_message(make_note("m14", ["a@d"]), c))
        self.assertEqual(s3.put_calls.count("markers/manifest/m14.json"), 2)  # intentos
        self.assertEqual(len([k for k in s3.objects if k == "markers/manifest/m14.json"]), 1)  # objeto único
        _ = puts_before

    def test_15_raw_reference_fields_present(self):
        # NEW-M1: el marker referencia inequívocamente la evidencia.
        s3 = FakeS3(); s3.seed_raw(RAWP + "m15", b"payload")
        c = ctx(s3)
        self.assertTrue(W.process_message(make_note("m15", ["a@d"]), c))
        marker = W._get_marker(c, f"markers/completed/m15/{W._rref('a@d')}.json")
        obj = marker["object"]
        for field in ("bucket", "key", "version_id", "sha256", "size_bytes"):
            self.assertIn(field, obj)
        self.assertEqual(marker["event_id"], "m15")
        self.assertEqual(marker["recipient_ref"], W._rref("a@d"))
        self.assertNotIn("a@d", json.dumps(marker))  # sin PII en claro (solo ref)


if __name__ == "__main__":
    unittest.main(verbosity=2)
