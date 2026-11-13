"""Verificacion de firma Svix (Resend) — COPIA del spike C4-B0.

Procedencia: spikes/c4b0-email-providers/firmas.py (esquema CONFIRMADO en vivo
el 2026-10-16 durante T1 del C4-B0). Se copia para mantener el spike
autocontenido; se elimina la parte Mailgun (fuera del experimento por decision
del 2026-11-13). Ante discrepancia manda la documentacion oficial de Svix.
"""


from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import time

TOLERANCIA_SEGUNDOS = 5 * 60


def _iguales(a: str | bytes, b: str | bytes) -> bool:
    if isinstance(a, str):
        a = a.encode()
    if isinstance(b, str):
        b = b.encode()
    return hmac.compare_digest(a, b)


def secreto_resend_valido(secreto: str) -> bool:
    """Formato EXIGIDO: prefijo `whsec_` + base64 estricto. Sin excepciones."""
    return _clave_svix(secreto) is not None


def _clave_svix(secreto: str) -> bytes | None:
    """El contrato real usa `whsec_<base64>`. El prefijo es OBLIGATORIO: un
    secreto sin `whsec_` es configuracion invalida. Base64 SIEMPRE estricto."""
    if not secreto.startswith("whsec_"):
        return None
    try:
        return base64.b64decode(secreto[len("whsec_"):], validate=True)
    except (binascii.Error, ValueError):
        return None


def verificar_resend(secreto: str, cabeceras: dict[str, str], cuerpo: bytes,
                     ahora: float | None = None) -> tuple[bool, str]:
    """(ok, motivo). Cabeceras en minuscula."""
    sid = cabeceras.get("svix-id")
    sts = cabeceras.get("svix-timestamp")
    sfirma = cabeceras.get("svix-signature")
    if not sid or not sts or not sfirma:
        return False, "faltan cabeceras svix"
    try:
        marca = int(sts)
    except ValueError:
        return False, "timestamp ilegible"
    momento = ahora if ahora is not None else time.time()
    if abs(momento - marca) > TOLERANCIA_SEGUNDOS:
        return False, "timestamp fuera de tolerancia"

    clave = _clave_svix(secreto)
    if clave is None:
        return False, "secreto invalido (se exige whsec_ + base64 estricto)"
    base = f"{sid}.{sts}.".encode() + cuerpo
    esperada = base64.b64encode(
        hmac.new(clave, base, hashlib.sha256).digest()).decode()

    alguna_v1 = False
    for candidata in sfirma.split(" "):
        version, _, valor = candidata.partition(",")
        if version != "v1" or not valor:
            continue                      # etiquetas distintas: rechazadas
        alguna_v1 = True
        try:
            base64.b64decode(valor, validate=True)
        except (binascii.Error, ValueError):
            continue                      # base64 invalido: no es candidata
        if _iguales(valor, esperada):
            return True, "ok"
    if not alguna_v1:
        return False, "sin firma v1 (version desconocida)"
    return False, "firma no coincide"
