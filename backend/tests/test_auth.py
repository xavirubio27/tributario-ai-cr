"""Verificación del JWT.

DOS NIVELES
    [UNIT]  Clave EC generada en el propio test. Permite construir tokens
            expirados, con issuer o audience equivocados y con firma ajena de
            forma determinista, sin depender de Supabase ni consumir cuota.
            Ninguna clave real interviene.
    [REAL]  Tokens auténticos de Supabase Auth, verificados contra el JWKS
            público del proyecto.
"""

from __future__ import annotations

import datetime as dt
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from app.auth import ALLOWED_JWT_ALGORITHMS, AuthError, JwtVerifier, extract_bearer_token
from app.config import Settings

ISSUER = "https://example-project.supabase.co/auth/v1"
AUDIENCE = "authenticated"


class _StubJwkClient:
    """Sustituye a PyJWKClient devolviendo siempre la clave pública indicada."""

    def __init__(self, public_key) -> None:
        self._public_key = public_key

    def get_signing_key_from_jwt(self, token: str):  # noqa: ARG002
        return type("Key", (), {"key": self._public_key})()


@pytest.fixture(scope="module")
def keypair():
    private_key = ec.generate_private_key(ec.SECP256R1())
    return private_key, private_key.public_key()


@pytest.fixture(scope="module")
def unit_settings() -> Settings:
    return Settings(
        supabase_url="https://example-project.supabase.co",
        database_url="postgresql://app_backend:x@localhost:5432/postgres",
        jwks_url="https://example-project.supabase.co/auth/v1/.well-known/jwks.json",
        jwt_issuer=ISSUER,
    )


@pytest.fixture(scope="module")
def verifier(unit_settings, keypair) -> JwtVerifier:
    _, public_key = keypair
    return JwtVerifier(unit_settings, jwk_client=_StubJwkClient(public_key))


def _make_token(private_key, **overrides) -> str:
    now = dt.datetime.now(tz=dt.UTC)
    claims = {
        "sub": str(uuid.uuid4()),
        "iss": ISSUER,
        "aud": AUDIENCE,
        "role": "authenticated",
        "email": "user@example.com",
        "iat": int(now.timestamp()),
        "exp": int((now + dt.timedelta(hours=1)).timestamp()),
    }
    claims.update(overrides)
    return jwt.encode(claims, private_key, algorithm="ES256")


# ── Cabecera Authorization ────────────────────────────────────────────────────

def test_missing_authorization_header_is_rejected():
    with pytest.raises(AuthError):
        extract_bearer_token(None)


@pytest.mark.parametrize(
    "header",
    ["", "Bearer", "Bearer ", "Token abc.def.ghi", "abc.def.ghi", "Bearer a b c"],
)
def test_malformed_bearer_header_is_rejected(header):
    with pytest.raises(AuthError):
        extract_bearer_token(header)


def test_wellformed_bearer_header_is_accepted():
    assert extract_bearer_token("Bearer abc.def.ghi") == "abc.def.ghi"


# ── Verificación del token ────────────────────────────────────────────────────

def test_valid_token_yields_identity(verifier, keypair):
    private_key, _ = keypair
    subject = str(uuid.uuid4())
    user = verifier.verify(_make_token(private_key, sub=subject, email="a@example.com"))
    assert user.id == subject
    assert user.email == "a@example.com"


def test_expired_token_is_rejected(verifier, keypair):
    private_key, _ = keypair
    past = dt.datetime.now(tz=dt.UTC) - dt.timedelta(hours=2)
    token = _make_token(
        private_key,
        iat=int(past.timestamp()),
        exp=int((past + dt.timedelta(hours=1)).timestamp()),
    )
    with pytest.raises(AuthError, match="expirado"):
        verifier.verify(token)


def test_token_signed_by_another_key_is_rejected(verifier):
    intruder_key = ec.generate_private_key(ec.SECP256R1())
    with pytest.raises(AuthError):
        verifier.verify(_make_token(intruder_key))


def test_wrong_issuer_is_rejected(verifier, keypair):
    private_key, _ = keypair
    with pytest.raises(AuthError):
        verifier.verify(_make_token(private_key, iss="https://atacante.example/auth/v1"))


def test_wrong_audience_is_rejected(verifier, keypair):
    private_key, _ = keypair
    with pytest.raises(AuthError):
        verifier.verify(_make_token(private_key, aud="otra-audiencia"))


def test_missing_sub_is_rejected(verifier, keypair):
    private_key, _ = keypair
    now = dt.datetime.now(tz=dt.UTC)
    token = jwt.encode(
        {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "iat": int(now.timestamp()),
            "exp": int((now + dt.timedelta(hours=1)).timestamp()),
        },
        private_key,
        algorithm="ES256",
    )
    with pytest.raises(AuthError):
        verifier.verify(token)


def test_non_uuid_sub_is_rejected(verifier, keypair):
    private_key, _ = keypair
    with pytest.raises(AuthError):
        verifier.verify(_make_token(private_key, sub="no-es-un-uuid"))


@pytest.mark.parametrize("garbage", ["", "   ", "no-es-un-jwt", "a.b", "a.b.c.d"])
def test_garbage_tokens_are_rejected(verifier, garbage):
    with pytest.raises(AuthError):
        verifier.verify(garbage)


def test_error_messages_do_not_leak_internals(verifier, keypair):
    """Los mensajes no deben revelar qué comprobación concreta falló."""
    private_key, _ = keypair
    for token in (
        _make_token(private_key, iss="https://atacante.example/auth/v1"),
        _make_token(private_key, aud="otra"),
        _make_token(private_key, sub="no-es-un-uuid"),
    ):
        with pytest.raises(AuthError) as excinfo:
            verifier.verify(token)
        assert str(excinfo.value) == "Token inválido."


# ── Restricción de algoritmo ──────────────────────────────────────────────────

def test_only_es256_is_allowed():
    assert ALLOWED_JWT_ALGORITHMS == ("ES256",)
    assert "RS256" not in ALLOWED_JWT_ALGORITHMS
    assert "HS256" not in ALLOWED_JWT_ALGORITHMS


def test_rs256_token_is_rejected(verifier):
    """Un JWT RS256 válidamente firmado NO debe aceptarse.

    Se firma con una clave RSA propia y se inyecta su pública en el verificador,
    de modo que la firma es correcta: lo único que falla es el algoritmo. Sin
    esta separación el test pasaría por el motivo equivocado.
    """
    from cryptography.hazmat.primitives.asymmetric import rsa

    rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = dt.datetime.now(tz=dt.UTC)
    token = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "iss": ISSUER,
            "aud": AUDIENCE,
            "iat": int(now.timestamp()),
            "exp": int((now + dt.timedelta(hours=1)).timestamp()),
        },
        rsa_key,
        algorithm="RS256",
    )

    rsa_verifier = JwtVerifier(
        Settings(
            supabase_url="https://example-project.supabase.co",
            database_url="postgresql://app_backend:x@localhost:5432/postgres",
            jwks_url="https://example-project.supabase.co/auth/v1/.well-known/jwks.json",
            jwt_issuer=ISSUER,
        ),
        jwk_client=_StubJwkClient(rsa_key.public_key()),
    )
    with pytest.raises(AuthError):
        rsa_verifier.verify(token)


def test_hs256_token_is_rejected(verifier, keypair):
    """Tampoco un secreto simétrico: la doc de Supabase lo desaconseja."""
    now = dt.datetime.now(tz=dt.UTC)
    token = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "iss": ISSUER,
            "aud": AUDIENCE,
            "iat": int(now.timestamp()),
            "exp": int((now + dt.timedelta(hours=1)).timestamp()),
        },
        "un-secreto-compartido-cualquiera",
        algorithm="HS256",
    )
    with pytest.raises(AuthError):
        verifier.verify(token)


def test_real_supabase_token_uses_es256(user_a):
    """[REAL] Confirma que el proyecto efectivamente firma con ES256."""
    header = jwt.get_unverified_header(user_a.token)
    assert header["alg"] == "ES256"


# ── Tokens reales de Supabase ─────────────────────────────────────────────────

def test_real_supabase_token_verifies_against_live_jwks(settings, user_a):
    """[REAL] Un token auténtico se verifica con el JWKS público del proyecto."""
    verifier = JwtVerifier(settings)
    user = verifier.verify(user_a.token)
    assert user.id == user_a.id
    assert user.email == user_a.email


def test_real_tokens_of_two_users_yield_different_identities(settings, user_a, user_b):
    """[REAL] Cada token produce su propia identidad, no una compartida."""
    verifier = JwtVerifier(settings)
    assert verifier.verify(user_a.token).id == user_a.id
    assert verifier.verify(user_b.token).id == user_b.id
    assert user_a.id != user_b.id
