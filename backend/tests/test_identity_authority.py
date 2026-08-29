"""La identidad no puede sustituirse por un UUID arbitrario.

HALLAZGO CORREGIDO (auditoría de Checkpoint C, severidad HIGH)

    Antes:   user_transaction(pool, settings, "<cualquier uuid>")
             → request.jwt.claims.sub = ese uuid
             → RLS operaba como ese usuario

    Un llamante interno podía —por accidente— pasar el UUID de otro usuario y
    convertirse en él. La corrección no confía en que nadie se equivoque: cambia
    el contrato para que el error no sea expresable.

    Ahora:   AuthenticatedUser verificada
             → user_transaction(pool, settings, user)
             → conexión contextualizada
             → helpers(conn, ...)   ← sin identidad como parámetro
"""

from __future__ import annotations

import inspect
import uuid

import pytest

from app.auth import AuthenticatedUser, AuthError, JwtVerifier
from app.authorization import get_company_membership, list_company_memberships
from app.db import DatabaseError, current_identity, user_transaction


# ── La identidad solo nace de un JWT verificado ───────────────────────────────

def test_authenticated_user_cannot_be_constructed_by_hand():
    """Fabricar una identidad a partir de un UUID debe ser imposible."""
    with pytest.raises(AuthError):
        AuthenticatedUser(id=str(uuid.uuid4()), email=None)


def test_authenticated_user_cannot_be_forged_with_wrong_proof():
    for bogus in (None, "cualquier cosa", b"", b"x" * 32, object()):
        with pytest.raises(AuthError):
            AuthenticatedUser(id=str(uuid.uuid4()), email=None, proof=bogus)


def test_verifier_is_the_only_source_of_identity(settings, user_a):
    """El camino legítimo produce exactamente la identidad del token."""
    identity = JwtVerifier(settings).verify(user_a.token)
    assert isinstance(identity, AuthenticatedUser)
    assert identity.id == user_a.id


# ── `user_transaction` rechaza identidades no verificadas ─────────────────────

@pytest.mark.parametrize(
    "impostor",
    [
        "11111111-1111-1111-1111-111111111111",   # UUID como str
        uuid.UUID("22222222-2222-2222-2222-222222222222"),
        None,
        42,
        {"id": "33333333-3333-3333-3333-333333333333"},
    ],
)
def test_user_transaction_rejects_unverified_identity(pool, settings, impostor):
    """Un UUID de request body/query/header NO satisface el contrato."""
    with pytest.raises((DatabaseError, AuthError, TypeError)):
        with user_transaction(pool, settings, impostor) as conn:  # type: ignore[arg-type]
            conn.execute("select 1")


def test_user_transaction_signature_requires_authenticated_user():
    """Comprobación estructural del contrato."""
    params = inspect.signature(user_transaction).parameters
    annotation = params["user"].annotation
    assert "AuthenticatedUser" in str(annotation)
    assert "str" != str(annotation)


# ── Los helpers no ofrecen interfaz de suplantación ───────────────────────────

def test_authorization_helpers_take_no_user_identity():
    """No hay parámetro por el que colar la identidad de otro usuario.

    Es la propiedad arquitectónica: aunque un llamante futuro quisiera suplantar,
    la API no tiene por dónde.
    """
    for fn in (get_company_membership, list_company_memberships):
        params = set(inspect.signature(fn).parameters)
        assert "user_id" not in params, f"{fn.__name__} acepta user_id"
        assert "user" not in params, f"{fn.__name__} acepta user"
        assert "sub" not in params
        assert "conn" in params, f"{fn.__name__} debe recibir la conexión contextualizada"


def test_helper_reads_identity_from_connection_not_from_arguments(
    pool, settings, user_a, user_b
):
    """El mismo helper, la misma empresa, distinta transacción → distinto resultado.

    Con la identidad de A ve su membresía; con la de B, `None`. La diferencia la
    marca la conexión, no ningún argumento.
    """
    with user_transaction(pool, settings, user_a.identity) as conn:
        assert current_identity(conn)["user_id"] == user_a.id
        como_a = get_company_membership(conn, user_a.company_id)

    with user_transaction(pool, settings, user_b.identity) as conn:
        assert current_identity(conn)["user_id"] == user_b.id
        como_b = get_company_membership(conn, user_a.company_id)

    assert como_a is not None and como_a.user_id == user_a.id
    assert como_b is None, "B obtuvo la membresía de A"


def test_b_identity_cannot_reach_company_of_a(pool, settings, user_a, user_b):
    """Aislamiento con la nueva API: B no alcanza la empresa de A."""
    with user_transaction(pool, settings, user_b.identity) as conn:
        rows = conn.execute("select id::text as id from public.companies").fetchall()
        ids = {r["id"] for r in rows}
    assert user_b.company_id in ids
    assert user_a.company_id not in ids


# ── Suplantación por HTTP ─────────────────────────────────────────────────────

def test_http_user_id_spoofing_is_ignored(settings, user_a, user_b):
    """Suplantación por QUERY, CABECERAS **y CUERPO**.

    HALLAZGO CORREGIDO (segunda reauditoría, severidad LOW)
        La versión anterior afirmaba cubrir el cuerpo pero solo enviaba query y
        cabeceras. Ahora se envían bytes de cuerpo reales: aunque el endpoint sea
        GET y no declare campos de identidad, se demuestra que esos bytes no se
        convierten en autoridad.
    """
    import json

    from fastapi.testclient import TestClient

    from app.main import app

    cuerpo = json.dumps(
        {"user_id": user_b.id, "sub": user_b.id, "role": "owner", "company_id": user_b.company_id}
    ).encode("utf-8")

    with TestClient(app) as client:
        response = client.request(
            "GET",
            "/diagnostics/identity",
            params={"user_id": user_b.id, "sub": user_b.id, "role": "owner"},
            headers={
                "Authorization": f"Bearer {user_a.token}",
                "X-User-Id": user_b.id,
                "X-Sub": user_b.id,
                "X-Role": "owner",
                "Content-Type": "application/json",
            },
            content=cuerpo,
        )

    assert response.status_code == 200, f"El cuerpo rompió la petición: {response.text[:200]}"
    body = response.json()

    # La identidad sigue siendo la de A, pese a los tres vectores.
    assert body["token_user_id"] == user_a.id
    assert body["db_user_id"] == user_a.id, "La identidad de la DB fue suplantada"
    assert body["db_user_id"] != user_b.id

    companies = {c["id"] for c in body["companies"]}
    assert user_a.company_id in companies
    assert user_b.company_id not in companies

    roles = {m["company_id"]: m["role"] for m in body["memberships"]}
    assert user_b.company_id not in roles


def test_http_spoofing_vectors_are_actually_exercised():
    """Deja constancia de QUÉ vectores ejecuta la suite.

    Evita volver a afirmar cobertura que el test no ejerce.
    """
    import inspect

    source = inspect.getsource(test_http_user_id_spoofing_is_ignored)
    assert "params=" in source, "query string no ejercitada"
    assert "headers=" in source, "cabeceras no ejercitadas"
    assert "content=" in source, "cuerpo no ejercitado"


# ── Evidencia ligada al subject (HIGH de la segunda reauditoría) ──────────────
#
# HALLAZGO CORREGIDO
#     La evidencia era un sentinel GLOBAL: demostraba "alguna identidad se creó
#     por el camino autorizado", no "este UUID fue el subject verificado". Era
#     transferible, así que la prueba de A servía para fabricar una identidad B.
#
#     Ahora es un HMAC sobre el propio subject: la de A no vale para B.

def _proof_for(subject: str) -> bytes:
    """Evidencia legítima para un subject. API interna, solo para tests."""
    from app.auth import _bind_subject

    return _bind_subject(subject)


def test_proof_of_a_is_not_valid_for_b():
    """`proof_for_A + A` vale; `proof_for_A + B` no. La evidencia está ligada."""
    a, b = str(uuid.uuid4()), str(uuid.uuid4())

    valida = AuthenticatedUser(id=a, email=None, proof=_proof_for(a))
    assert valida.id == a
    assert valida.has_valid_binding()

    with pytest.raises(AuthError):
        AuthenticatedUser(id=b, email=None, proof=_proof_for(a))


def test_stolen_proof_from_legitimate_identity_cannot_mint_another(settings, user_a):
    """La evidencia de una identidad REAL no sirve para fabricar otra."""
    real = JwtVerifier(settings).verify(user_a.token)
    robada = real._proof  # acceso interno, solo para demostrar la propiedad

    with pytest.raises(AuthError):
        AuthenticatedUser(id=str(uuid.uuid4()), email=None, proof=robada)


def test_dataclasses_replace_is_not_applicable(settings, user_a):
    """`AuthenticatedUser` ya no es dataclass: el vector deja de existir."""
    import dataclasses

    real = JwtVerifier(settings).verify(user_a.token)
    assert not dataclasses.is_dataclass(real)
    with pytest.raises(TypeError):
        dataclasses.replace(real, id=str(uuid.uuid4()))  # type: ignore[call-overload]


def test_identity_is_immutable(settings, user_a):
    """No se puede cambiar el subject de una identidad ya emitida."""
    real = JwtVerifier(settings).verify(user_a.token)
    for attr in ("_id", "id", "_email", "_proof"):
        with pytest.raises(AttributeError):
            setattr(real, attr, "otro-valor")
    with pytest.raises(AttributeError):
        del real._id


def test_identity_has_no_dict_for_arbitrary_attributes(settings, user_a):
    """`__slots__`: no se pueden inyectar atributos nuevos."""
    real = JwtVerifier(settings).verify(user_a.token)
    assert not hasattr(real, "__dict__")
    with pytest.raises(AttributeError):
        real.suplantado = True  # type: ignore[attr-defined]


def test_legitimate_jwt_of_b_produces_valid_identity_of_b(settings, user_a, user_b):
    """Distingue una B legítima de una B forjada a partir de A."""
    verifier = JwtVerifier(settings)
    identidad_b = verifier.verify(user_b.token)

    assert identidad_b.id == user_b.id
    assert identidad_b.has_valid_binding()
    assert identidad_b.id != verifier.verify(user_a.token).id


def test_user_transaction_rejects_identity_with_broken_binding(pool, settings, user_a):
    """FAIL CLOSED: si la evidencia no corresponde al id, no se ejecuta SQL.

    Se fuerza la incoherencia por una vía fuera de la API normal —precisamente lo
    que la comprobación redundante de `user_transaction` debe atrapar—.
    """
    real = JwtVerifier(settings).verify(user_a.token)
    incoherente = object.__new__(AuthenticatedUser)
    object.__setattr__(incoherente, "_id", str(uuid.uuid4()))
    object.__setattr__(incoherente, "_email", None)
    object.__setattr__(incoherente, "_proof", real._proof)

    assert not incoherente.has_valid_binding()
    with pytest.raises(DatabaseError, match="evidencia"):
        with user_transaction(pool, settings, incoherente) as conn:
            conn.execute("select 1")


def test_repr_never_reveals_the_proof(settings, user_a):
    real = JwtVerifier(settings).verify(user_a.token)
    text = repr(real)
    assert user_a.id in text
    assert "proof" not in text.lower()
    assert real._proof.hex()[:8] not in text
