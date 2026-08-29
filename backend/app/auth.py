"""Verificación de la identidad del usuario a partir del JWT de Supabase Auth.

MECANISMO — verificado contra la documentación oficial y contra el propio proyecto
    El proyecto firma con claves ASIMÉTRICAS: su endpoint JWKS publica una clave
    EC y los tokens llegan con `alg: ES256`. La verificación es OFFLINE, con la
    clave pública obtenida del JWKS. El backend NO necesita ningún secreto
    compartido para validar un token, lo que elimina toda una clase de riesgo.

    La documentación de Supabase desaconseja el secreto simétrico compartido:
    quien lo posea puede suplantar a cualquier usuario.

QUÉ SE VERIFICA
    firma (ES256 con la clave pública del JWKS) · `exp` · `iss` · `aud`
    y presencia de un `sub` con forma de UUID.

QUÉ NO SE CONFÍA DEL TOKEN
    Ni pertenencia a empresa, ni rol dentro de ella. El JWT identifica al
    usuario; la membresía y el rol se consultan en `company_memberships`
    (ADR-015). Tampoco se acepta ningún `user_id`, `company_id` o `role`
    enviado por el cliente fuera del token.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid

import jwt
from jwt import PyJWKClient

from app.config import Settings


# Algoritmo UNICO admitido.
#
# El JWKS de este proyecto publica una clave EC y los tokens llegan con
# `alg: ES256`. No se acepta RS256 "por si acaso": cada algoritmo admitido es
# superficie de ataque adicional, y aceptar uno que no se usa solo sirve para
# que una rotacion no anunciada pase inadvertida.
#
# Si Supabase rotara deliberadamente a otro algoritmo, ampliar esta lista debe
# ser un cambio consciente y con test, no un silencio.
ALLOWED_JWT_ALGORITHMS = ("ES256",)


class AuthError(Exception):
    """El token no pudo verificarse. El mensaje es seguro para el cliente."""


# Clave privada del proceso. Se genera al importar el módulo: vive solo en
# memoria, no es configuración, no se persiste, no se expone y nunca se imprime.
# Su única función es hacer que la evidencia emitida por el verificador quede
# LIGADA a un subject concreto.
_PROCESS_KEY = secrets.token_bytes(32)


def _bind_subject(subject: str) -> bytes:
    """Evidencia ligada a un subject concreto.

    Un HMAC sobre el `sub` ya verificado. Como la clave solo existe dentro del
    proceso, la evidencia no puede fabricarse desde fuera; y como depende del
    subject, la evidencia de A **no vale** para B.
    """
    return hmac.new(_PROCESS_KEY, subject.encode("utf-8"), hashlib.sha256).digest()


def _proof_matches(subject: str, proof: object) -> bool:
    """True si `proof` es la evidencia correspondiente exactamente a `subject`."""
    if not isinstance(proof, bytes):
        return False
    return hmac.compare_digest(proof, _bind_subject(subject))


class AuthenticatedUser:
    """Identidad verificada, inmutable y ligada a su subject.

    POR QUÉ NO ES UN `dataclass`

        Lo era, con una prueba que consistía en un sentinel global. Ese diseño
        demostraba "alguna identidad se creó por el camino autorizado", no "este
        UUID fue el subject que verificó el JWT". La evidencia era TRANSFERIBLE:

            dataclasses.replace(usuario_a, id=B)     -> identidad B "válida"
            AuthenticatedUser(id=B, _proof=usuario_a._proof)  -> también

        Ahora la evidencia es un HMAC sobre el propio subject, así que la de A no
        vale para B. Y al no ser un dataclass, `dataclasses.replace` ni siquiera
        es aplicable.

    ALCANCE DE LA BARRERA

        Protege frente al uso NORMAL de Python: constructor público,
        `dataclasses.replace`, copia con cambio de `id`, reutilización de una
        prueba ajena, o pasar un `str`/`UUID` directamente.

        No pretende resistir código deliberadamente hostil dentro del proceso
        (`object.__setattr__`, monkeypatching, lectura de `_PROCESS_KEY`). Quien
        ejecuta código arbitrario en el backend ya controla el backend.
    """

    __slots__ = ("_id", "_email", "_proof")

    def __init__(self, *, id: str, email: str | None = None, proof: object = None) -> None:
        if not isinstance(id, str) or not id:
            raise AuthError("Identidad inválida.")
        if not _proof_matches(id, proof):
            raise AuthError(
                "AuthenticatedUser solo puede obtenerse verificando un JWT cuyo "
                "`sub` sea exactamente este identificador. La evidencia de otro "
                "usuario no es reutilizable."
            )
        object.__setattr__(self, "_id", id)
        object.__setattr__(self, "_email", email)
        object.__setattr__(self, "_proof", proof)

    # ── Inmutabilidad ─────────────────────────────────────────────────────────

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("AuthenticatedUser es inmutable.")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("AuthenticatedUser es inmutable.")

    # ── Lectura ───────────────────────────────────────────────────────────────

    @property
    def id(self) -> str:
        return self._id

    @property
    def email(self) -> str | None:
        return self._email

    def has_valid_binding(self) -> bool:
        """True si la evidencia sigue correspondiendo a este `id`.

        `user_transaction` lo comprueba antes de usar la identidad: si alguien
        alterase el `id` por una vía fuera de la API normal, la evidencia dejaría
        de corresponder y la transacción fallaría cerrada.
        """
        return _proof_matches(self._id, self._proof)

    def __repr__(self) -> str:
        # Nunca revela la evidencia.
        return f"AuthenticatedUser(id={self._id!r})"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, AuthenticatedUser) and other._id == self._id

    def __hash__(self) -> int:
        return hash(self._id)


class JwtVerifier:
    """Verifica tokens de Supabase Auth con la clave pública del JWKS."""

    def __init__(self, settings: Settings, jwk_client: PyJWKClient | None = None) -> None:
        self._settings = settings
        # PyJWKClient cachea las claves; el JWKS de Supabase se sirve con caché de
        # 10 minutos en el edge, así que no conviene pedirlo en cada petición.
        self._jwks = jwk_client or PyJWKClient(settings.jwks_url, cache_keys=True)

    def verify(self, token: str) -> AuthenticatedUser:
        if not token or not token.strip():
            raise AuthError("Token ausente.")

        try:
            signing_key = self._jwks.get_signing_key_from_jwt(token)
        except Exception as exc:  # noqa: BLE001 — cualquier fallo aquí es token inválido
            raise AuthError("No se pudo resolver la clave de firma del token.") from exc

        try:
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=list(ALLOWED_JWT_ALGORITHMS),
                audience=self._settings.jwt_audience,
                issuer=self._settings.jwt_issuer,
                options={"require": ["exp", "iss", "aud", "sub"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise AuthError("El token ha expirado.") from exc
        except jwt.InvalidTokenError as exc:
            # Cubre firma inválida, issuer/audience incorrectos y claims faltantes.
            # Mensaje deliberadamente genérico: no revela qué parte falló.
            raise AuthError("Token inválido.") from exc

        subject = claims.get("sub")
        if not isinstance(subject, str):
            raise AuthError("Token inválido.")
        try:
            # El identificador debe ser un UUID: se interpolará como identidad en
            # PostgreSQL, y `auth.uid()` lo castea a uuid.
            uuid.UUID(subject)
        except ValueError as exc:
            raise AuthError("Token inválido.") from exc

        email = claims.get("email")
        # La evidencia se deriva del `sub` YA VERIFICADO, después de comprobar
        # firma, algoritmo, issuer, audience y expiración.
        return AuthenticatedUser(
            id=subject,
            email=email if isinstance(email, str) else None,
            proof=_bind_subject(subject),
        )


def extract_bearer_token(authorization_header: str | None) -> str:
    """Extrae el token de una cabecera `Authorization: Bearer <token>`."""
    if not authorization_header:
        raise AuthError("Falta la cabecera Authorization.")

    parts = authorization_header.split()
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        raise AuthError("Cabecera Authorization mal formada.")

    return parts[1]
