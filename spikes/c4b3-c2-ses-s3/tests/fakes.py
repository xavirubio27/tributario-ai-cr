"""Stubs AWS en memoria para las pruebas locales (sin boto3/moto, solo stdlib).

Implementan lo justo que usan poc_worker/poc_reconcile: S3 con escritura CONDICIONAL
(If-None-Match:*), versionado, get/head/list; y SQS con change_message_visibility.
Fallos inyectables para cubrir los escenarios obligatorios.
"""
from __future__ import annotations

import io


class FakeClientError(Exception):
    def __init__(self, code: str, http: int = 400):
        super().__init__(code)
        self.response = {"Error": {"Code": code}, "ResponseMetadata": {"HTTPStatusCode": http}}


class _LastModified:
    def __init__(self, ts: float):
        self._ts = ts

    def timestamp(self) -> float:
        return self._ts


class FakeS3:
    def __init__(self):
        self.objects: dict[str, dict] = {}           # key -> {body, version_id, lm}
        self._ver = 0
        self.fail_put_keys: set[str] = set()         # lanza AccessDenied en PutObject
        self.fail_get_keys: set[str] = set()         # lanza error en GetObject (RAW)
        self.put_calls: list[str] = []

    # --- helpers de siembra para tests ---
    def seed_raw(self, key: str, body: bytes, lm_ts: float = 1000.0):
        self._ver += 1
        self.objects[key] = {"body": body, "version_id": f"v{self._ver}", "lm": _LastModified(lm_ts)}

    def exists(self, key: str) -> bool:
        return key in self.objects

    # --- API estilo boto3 ---
    def put_object(self, Bucket=None, Key=None, Body=b"", ContentType=None, IfNoneMatch=None, **_):
        self.put_calls.append(Key)
        if Key in self.fail_put_keys:
            raise FakeClientError("AccessDenied", 403)
        if IfNoneMatch == "*" and Key in self.objects:
            raise FakeClientError("PreconditionFailed", 412)
        self._ver += 1
        body = Body if isinstance(Body, (bytes, bytearray)) else bytes(Body)
        self.objects[Key] = {"body": bytes(body), "version_id": f"v{self._ver}", "lm": _LastModified(1000.0)}
        return {"VersionId": self.objects[Key]["version_id"], "ETag": f'"{self._ver}"'}

    def get_object(self, Bucket=None, Key=None, **_):
        if Key in self.fail_get_keys:
            raise FakeClientError("InternalError", 500)
        if Key not in self.objects:
            raise FakeClientError("NoSuchKey", 404)
        o = self.objects[Key]
        return {"Body": io.BytesIO(o["body"]), "VersionId": o["version_id"]}

    def head_object(self, Bucket=None, Key=None, **_):
        if Key not in self.objects:
            raise FakeClientError("NotFound", 404)
        o = self.objects[Key]
        return {"VersionId": o["version_id"], "ContentLength": len(o["body"])}

    def list_objects_v2(self, Bucket=None, Prefix="", ContinuationToken=None, **_):
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

    def receive_message(self, **_):
        return {"Messages": []}
