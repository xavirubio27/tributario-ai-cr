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

import uuid
from dataclasses import dataclass

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


@dataclass(frozen=True)
class AuthenticatedUser:
    """Identidad verificada. Es lo único que el backend acepta como usuario."""

    id: str
    email: str | None


class AuthError(Exception):
    """El token no pudo verificarse. El mensaje es seguro para el cliente."""


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
        return AuthenticatedUser(id=subject, email=email if isinstance(email, str) else None)


def extract_bearer_token(authorization_header: str | None) -> str:
    """Extrae el token de una cabecera `Authorization: Bearer <token>`."""
    if not authorization_header:
        raise AuthError("Falta la cabecera Authorization.")

    parts = authorization_header.split()
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        raise AuthError("Cabecera Authorization mal formada.")

    return parts[1]
