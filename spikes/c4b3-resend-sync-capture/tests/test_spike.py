"""Tests locales del spike brazo Resend (stdlib unittest; sin red externa).

Fijan las garantias de captura.py y receiver.py sobre fakes:
firma-antes-que-nada, 2xx solo con RAW durable, no-2xx limpia residuos,
idempotencia por marker, tope de bytes, deadline, redirects y allowlist
fail-closed, fallos inducidos tras firma, y el ledger de intentos.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import captura                                      # noqa: E402
import receiver                                     # noqa: E402
from tests import fakes                             # noqa: E402


def _post(base: str, path: str, body: bytes, headers: dict[str, str]):
    req = urllib.request.Request(base + path, data=body, headers={
        "Content-Type": "application/json", **headers}, method="POST")
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode() or "{}")


def _get(base: str, path: str, token: str | None = None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    req = urllib.request.Request(base + path, headers=headers)
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


class SpikeTestBase(unittest.TestCase):
    fail_mode = "none"

    def setUp(self):
        self.fake = fakes.FakeResend()
        self.store = tempfile.mkdtemp(prefix="spike-c4b3-")
        env = {
            "RESEND_WEBHOOK_SECRET": fakes.SECRET,
            "RESEND_API_KEY": "re_test_key",
            "RESEND_API_BASE": self.fake.base,
            "SPIKE_READ_TOKEN": "tok",
            "SPIKE_STORE_DIR": self.store,
            "SPIKE_SYNC_BUDGET_SECONDS": "5",
            "SPIKE_MAX_RAW_BYTES": str(1024 * 1024),
            "SPIKE_ALLOWED_DOWNLOAD_HOSTS": "cloudfront.net",
            "SPIKE_FAIL_MODE": self.fail_mode,
            "SPIKE_HANG_SECONDS": "0.2",
        }
        self.settings = receiver.Settings(env)
        self.server = receiver.build_server(self.settings)
        self.base = "http://127.0.0.1:%d" % self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.fake.close()
        shutil.rmtree(self.store, ignore_errors=True)

    # helpers
    def deliver(self, email_id: str, svix_id: str = "msg_1",
                event_type: str = "email.received", **sign_kw):
        body = fakes.event_body(email_id, event_type)
        return _post(self.base, "/webhooks/resend", body,
                     fakes.sign(body, svix_id, **sign_kw))

    def ledger_rows(self):
        path = os.path.join(self.store, "attempts.jsonl")
        if not os.path.exists(path):
            return []
        with open(path, "rb") as fh:
            return [json.loads(line) for line in fh if line.strip()]

    def residues(self):
        found = []
        for root, _dirs, files in os.walk(self.store):
            found += [f for f in files if f.startswith(".tmp-")]
        return found


class TestCaptura(SpikeTestBase):
    def test_01_capture_ok_durable_and_hash(self):
        raw = b"X" * 5000 + b"cuerpo"
        self.fake.behaviors["em1"] = {"raw": raw}
        status, payload = self.deliver("em1")
        self.assertEqual(status, 200)
        self.assertEqual(payload["outcome"], "capturado")
        sha = hashlib.sha256(raw).hexdigest()
        self.assertEqual(payload["sha256"], sha)
        blob = captura.blob_path(self.settings.capture, sha)
        with open(blob, "rb") as fh:
            self.assertEqual(fh.read(), raw)
        marker = json.loads(open(
            captura.marker_path(self.settings.capture, "em1")).read())
        self.assertEqual(marker["bytes"], len(raw))
        self.assertEqual(marker["svix_id"], "msg_1")
        self.assertEqual(self.residues(), [])

    def test_02_invalid_signature_401_no_capture_no_ledger(self):
        body = fakes.event_body("em2")
        headers = fakes.sign(body)
        headers["svix-signature"] = "v1,AAAA"
        status, _ = _post(self.base, "/webhooks/resend", body, headers)
        self.assertEqual(status, 401)
        self.assertEqual(self.fake.api_calls, [])      # ni una llamada API
        self.assertEqual(self.ledger_rows(), [])

    def test_03_stale_timestamp_rejected(self):
        status, _ = self.deliver("em3", ts=int(time.time()) - 3600)
        self.assertEqual(status, 401)

    def test_04_duplicate_no_refetch(self):
        self.fake.behaviors["em4"] = {}
        s1, p1 = self.deliver("em4", "msg_a")
        s2, p2 = self.deliver("em4", "msg_b")          # reintento Svix
        self.assertEqual((s1, s2), (200, 200))
        self.assertEqual(p2["outcome"], "duplicado")
        self.assertEqual(self.fake.api_calls.count("em4"), 1)
        outcomes = [r["outcome"] for r in self.ledger_rows()]
        self.assertEqual(outcomes, ["capturado", "duplicado"])

    def test_05_oversize_500_no_marker_no_residue(self):
        self.fake.behaviors["em5"] = {"raw": b"Z" * (1024 * 1024 + 1)}
        status, payload = self.deliver("em5")
        self.assertEqual(status, 500)
        self.assertEqual(payload["motivo"], "descarga-supera-tope")
        self.assertFalse(os.path.exists(
            captura.marker_path(self.settings.capture, "em5")))
        self.assertEqual(self.residues(), [])
        self.assertEqual(os.listdir(
            os.path.join(self.store, "blobs")), [])

    def test_06_slow_download_budget_exhausted(self):
        self.fake.behaviors["em6"] = {"download": "drip", "raw": b"q" * 400,
                                      "download_delay": 2.0}
        t0 = time.monotonic()
        status, payload = self.deliver("em6")
        self.assertEqual(status, 500)
        self.assertIn(payload["motivo"],
                      ("presupuesto-agotado", "descarga-fallo:TimeoutError",
                       "descarga-fallo:timeout"))
        self.assertLess(time.monotonic() - t0, 10)      # presupuesto de 5 s
        self.assertEqual(self.residues(), [])

    def test_07_redirect_refused(self):
        self.fake.behaviors["em7"] = {"download": "redirect"}
        status, payload = self.deliver("em7")
        self.assertEqual(status, 500)
        self.assertTrue(payload["motivo"].startswith("redirect-prohibido")
                        or payload["motivo"].startswith("descarga-fallo"),
                        payload["motivo"])
        self.assertEqual(self.residues(), [])

    def test_08_allowlist_refuses_public_host(self):
        cfg = captura.Config(api_base=self.fake.base, api_key="k",
                             budget_seconds=5, max_raw_bytes=1024,
                             allowed_host_suffixes=("cloudfront.net",),
                             store_dir=self.store)
        with self.assertRaises(captura.CaptureError) as ctx:
            captura._validate_download_url(cfg, "https://evil.example.com/x")
        self.assertEqual(ctx.exception.reason,
                         "download-url-host-fuera-de-allowlist")
        ok = captura._validate_download_url(
            cfg, "https://d123.cloudfront.net/x")
        self.assertTrue(ok)
        with self.assertRaises(captura.CaptureError):
            captura._validate_download_url(
                cfg, "https://evilcloudfront.net.example.com/x")
        with self.assertRaises(captura.CaptureError):
            captura._validate_download_url(cfg, "http://10.0.0.1/x")

    def test_09_api_404_is_500_for_svix_retry(self):
        self.fake.behaviors["em9"] = {"api": "404"}
        status, payload = self.deliver("em9")
        self.assertEqual(status, 500)
        self.assertEqual(payload["motivo"], "api-status-404")

    def test_10_missing_raw_field(self):
        self.fake.behaviors["em10"] = {"no_raw_field": True}
        status, payload = self.deliver("em10")
        self.assertEqual(status, 500)
        self.assertEqual(payload["motivo"], "sin-raw-download-url")

    def test_11_ignored_event_type_200_without_api_call(self):
        status, payload = self.deliver("em11", event_type="email.delivered")
        self.assertEqual(status, 200)
        self.assertEqual(payload["outcome"], "ignorado")
        self.assertEqual(self.fake.api_calls, [])

    def test_12_evidence_endpoints_require_token(self):
        self.fake.behaviors["em12"] = {"raw": b"abc"}
        _, payload = self.deliver("em12")
        sha = payload["sha256"]
        self.assertEqual(_get(self.base, "/capturas/attempts.jsonl")[0], 401)
        status, data = _get(self.base, f"/capturas/blobs/{sha}.eml", "tok")
        self.assertEqual((status, data), (200, b"abc"))
        status, data = _get(self.base, "/capturas/markers/em12.json", "tok")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(data)["sha256"], sha)

    def test_13_transfer_encoding_and_lengths_rejected(self):
        body = fakes.event_body("em13")
        req = urllib.request.Request(
            self.base + "/webhooks/resend", data=body,
            headers={**fakes.sign(body), "Transfer-Encoding": "chunked"},
            method="POST")
        try:
            resp = urllib.request.urlopen(req, timeout=10)
            status = resp.status
        except urllib.error.HTTPError as exc:
            status = exc.code
        self.assertEqual(status, 400)


class TestFailModes(SpikeTestBase):
    fail_mode = "http500"

    def test_14_induced_500_after_valid_signature_logged(self):
        status, payload = self.deliver("em14")
        self.assertEqual(status, 500)
        self.assertEqual(payload["outcome"], "fallo-inducido")
        rows = self.ledger_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["outcome"], "fallo-inducido-500")
        self.assertEqual(rows[0]["svix_id"], "msg_1")
        self.assertEqual(self.fake.api_calls, [])       # no captura nada

    def test_15_induced_500_still_401_on_bad_signature(self):
        body = fakes.event_body("em15")
        headers = fakes.sign(body)
        headers["svix-signature"] = "v1,AAAA"
        status, _ = _post(self.base, "/webhooks/resend", body, headers)
        self.assertEqual(status, 401)
        self.assertEqual(self.ledger_rows(), [])


class TestHangMode(SpikeTestBase):
    fail_mode = "hang200"

    def test_16_hang200_sleeps_then_200_and_ledger(self):
        t0 = time.monotonic()
        status, payload = self.deliver("em16")
        self.assertEqual(status, 200)
        self.assertEqual(payload["outcome"], "hang200")
        self.assertGreaterEqual(time.monotonic() - t0, 0.2)
        rows = self.ledger_rows()
        self.assertEqual(rows[0]["outcome"], "hang200")
        self.assertEqual(rows[0]["slept_s"], 0.2)


class TestSettings(unittest.TestCase):
    def test_17_public_validation_fail_closed(self):
        problems = receiver.Settings({}).validate_public()
        joined = " ".join(problems)
        self.assertIn("RESEND_WEBHOOK_SECRET", joined)
        self.assertIn("RESEND_API_KEY", joined)
        self.assertIn("SPIKE_READ_TOKEN", joined)
        bad = receiver.Settings({
            "RESEND_WEBHOOK_SECRET": fakes.SECRET,
            "RESEND_API_KEY": "k", "SPIKE_READ_TOKEN": "t",
            "SPIKE_FAIL_MODE": "explota"})
        self.assertTrue(any("SPIKE_FAIL_MODE" in p
                            for p in bad.validate_public()))

    def test_18_email_id_alphabet_closed(self):
        self.assertTrue(captura.safe_email_id("abc-123_XY"))
        for bad in ("", "a/../b", "a b", "x" * 129, "a\n", "../etc"):
            self.assertFalse(captura.safe_email_id(bad), bad)


if __name__ == "__main__":
    unittest.main(verbosity=2)
