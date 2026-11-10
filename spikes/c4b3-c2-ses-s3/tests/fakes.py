"""Stubs AWS en memoria para pruebas locales (stdlib, sin boto3/moto).

S3 con escritura CONDICIONAL (If-None-Match:*), HISTORIAL DE VERSIONES (para fijar y verificar
VersionId y descartar carreras Head/Get), thread-safe (concurrencia real), y fallos inyectables.
SQS con change_message_visibility (fallo inyectable). Body opcionalmente "lento" para ejercitar
el heartbeat de forma asíncrona.
"""
from __future__ import annotations

import io
import threading
import time


class FakeClientError(Exception):
    def __init__(self, code: str, http: int = 400):
        super().__init__(code)
        self.response = {"Error": {"Code": code}, "ResponseMetadata": {"HTTPStatusCode": http}}


class _LastModified:
    def __init__(self, ts: float):
        self._ts = ts

    def timestamp(self) -> float:
        return self._ts


class _SlowBody(io.BytesIO):
    def __init__(self, data: bytes, delay: float):
        super().__init__(data)
        self._delay = delay

    def read(self, n=-1):
        time.sleep(self._delay)
        return super().read(n)


class FakeS3:
    def __init__(self):
        self._lock = threading.RLock()
        self.objects: dict[str, dict] = {}   # key -> {versions:{vid:bytes}, latest:vid, lm}
        self._ver = 0
        self.fail_put_keys: set[str] = set()
        self.fail_get_keys: set[str] = set()
        self.slow_keys: dict[str, float] = {}   # key -> delay por read (body lento)
        self.put_calls: list[str] = []

    def _next_vid(self) -> str:
        self._ver += 1
        return f"v{self._ver}"

    # --- siembra para tests ---
    def seed_raw(self, key: str, body: bytes, lm_ts: float = 1000.0, slow_delay: float | None = None):
        with self._lock:
            vid = self._next_vid()
            rec = self.objects.setdefault(key, {"versions": {}, "latest": None, "lm": _LastModified(lm_ts)})
            rec["versions"][vid] = bytes(body)
            rec["latest"] = vid
            rec["lm"] = _LastModified(lm_ts)
            if slow_delay is not None:
                self.slow_keys[key] = slow_delay
            return vid

    def exists(self, key: str) -> bool:
        return key in self.objects

    # --- API estilo boto3 ---
    def put_object(self, Bucket=None, Key=None, Body=b"", ContentType=None, IfNoneMatch=None, **_):
        with self._lock:
            self.put_calls.append(Key)
            if Key in self.fail_put_keys:
                raise FakeClientError("AccessDenied", 403)
            if IfNoneMatch == "*" and Key in self.objects:
                raise FakeClientError("PreconditionFailed", 412)
            vid = self._next_vid()
            data = bytes(Body) if not isinstance(Body, (bytes, bytearray)) else bytes(Body)
            rec = self.objects.setdefault(Key, {"versions": {}, "latest": None, "lm": _LastModified(1000.0)})
            rec["versions"][vid] = data
            rec["latest"] = vid
            return {"VersionId": vid, "ETag": f'"{vid}"'}

    def _resolve(self, Key, VersionId):
        if Key in self.fail_get_keys:
            raise FakeClientError("InternalError", 500)
        rec = self.objects.get(Key)
        if rec is None:
            raise FakeClientError("NoSuchKey", 404)
        vid = VersionId or rec["latest"]
        if vid not in rec["versions"]:
            raise FakeClientError("NoSuchVersion", 404)
        return vid, rec["versions"][vid]

    def get_object(self, Bucket=None, Key=None, VersionId=None, **_):
        with self._lock:
            vid, data = self._resolve(Key, VersionId)
            delay = self.slow_keys.get(Key)
        body = _SlowBody(data, delay) if delay else io.BytesIO(data)
        return {"Body": body, "VersionId": vid}

    def head_object(self, Bucket=None, Key=None, VersionId=None, **_):
        with self._lock:
            vid, data = self._resolve(Key, VersionId)
            return {"VersionId": vid, "ContentLength": len(data)}

    def list_objects_v2(self, Bucket=None, Prefix="", ContinuationToken=None, **_):
        with self._lock:
            keys = sorted(k for k in self.objects if k.startswith(Prefix))
            contents = [{"Key": k, "LastModified": self.objects[k]["lm"]} for k in keys]
        return {"Contents": contents, "IsTruncated": False}


class FakeSQS:
    def __init__(self, fail_visibility: bool = False):
        self.fail_visibility = fail_visibility
        self.visibility_calls = 0
        self.deleted: list[str] = []

    def change_message_visibility(self, QueueUrl=None, ReceiptHandle=None, VisibilityTimeout=None, **_):
        self.visibility_calls += 1
        if self.fail_visibility:
            raise FakeClientError("ReceiptHandleIsInvalid", 400)
        return {}

    def delete_message(self, QueueUrl=None, ReceiptHandle=None, **_):
        self.deleted.append(ReceiptHandle)
        return {}


class CollectingSink:
    """Sink de alertas para tests: recoge y confirma publicación (True)."""
    def __init__(self):
        self.alerts: list[dict] = []

    def __call__(self, alert: dict) -> bool:
        self.alerts.append(alert)
        return True


class FlakySink:
    """Falla las primeras `fail_times` publicaciones y luego confirma (para probar reintento)."""
    def __init__(self, fail_times: int = 1, mode: str = "raise"):
        self.fail_times, self.mode, self.calls = fail_times, mode, 0
        self.alerts: list[dict] = []

    def __call__(self, alert: dict) -> bool:
        self.calls += 1
        self.alerts.append(alert)
        if self.calls <= self.fail_times:
            if self.mode == "raise":
                raise FakeClientError("InternalError", 500)
            return False
        return True
