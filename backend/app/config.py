"""Configuración del backend, leída del entorno.

Regla 6: ningún secreto vive en el repositorio. Todo valor sensible llega por
variable de entorno; `backend/.env.local` está ignorado por Git.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from dotenv import load_dotenv

_ENV_FILE = Path(__file__).resolve().parent.parent / ".env.local"


class ConfigError(RuntimeError):
    """Falta configuración obligatoria, o es inconsistente."""


@dataclass(frozen=True)
class Settings:
    supabase_url: str
    database_url: str
    jwks_url: str
    jwt_issuer: str
    jwt_audience: str = "authenticated"

    # Rol que el backend asume dentro de cada transacción. Debe coincidir con el
    # rol al que apuntan las políticas RLS del Día 2 (`TO authenticated`).
    db_role: str = "authenticated"


# ÚNICO rol de login aprobado para el backend (ADR-012).
#
# La validación es POSITIVA: se exige exactamente este rol, en lugar de rechazar
# una lista de nombres peligrosos. Una lista negra no protege frente a roles que
# nadie previó -- un `future_privileged_role`, o un `app_backend_evil` que se le
# parece -- y obliga a mantenerla al día para siempre.
BACKEND_DB_ROLE = "app_backend"


def _reject_placeholders(database_url: str) -> None:
    """Rechaza una cadena que aún contenga marcadores de la plantilla.

    Sin esto, un `<pooler-host>` sin sustituir produce un `gaierror` opaco tras
    agotar el tiempo de conexión, y los tests aparecen como fallos de seguridad
    cuando en realidad falta configuración.
    """
    parts = urlsplit(database_url)
    for label, value in (
        ("host", parts.hostname),
        ("contraseña", parts.password),
        ("usuario", parts.username),
    ):
        if value and value.startswith("<") and value.endswith(">"):
            raise ConfigError(
                f"DATABASE_URL contiene un marcador sin sustituir en {label}. "
                "Reemplaza los valores entre ángulos por los reales del Dashboard "
                "(Project Settings → Database → Session pooler)."
            )


def parse_login_role(database_url: str) -> str:
    """Extrae el rol base del usuario de la cadena de conexión.

    Supavisor usa el formato `<rol>.<project-ref>`; el rol es lo anterior al
    primer punto. Una conexión directa usa solo `<rol>`.
    """
    try:
        username = urlsplit(database_url).username or ""
    except ValueError as exc:
        raise ConfigError("DATABASE_URL no es una URL válida.") from exc

    if not username:
        raise ConfigError("DATABASE_URL no indica usuario de base de datos.")

    return username.split(".", 1)[0]


def _require_backend_role(database_url: str) -> None:
    """Exige que el login sea EXACTAMENTE el rol aprobado.

    Validación positiva: cualquier otro rol se rechaza, incluidos los que no
    parezcan peligrosos. `postgres`, `service_role`, `authenticated`, `anon`,
    `app_backend_evil` y `my_app_backend` fallan todos por igual.
    """
    role = parse_login_role(database_url)
    if role != BACKEND_DB_ROLE:
        raise ConfigError(
            f"DATABASE_URL usa el rol {role!r}. El backend solo admite "
            f"{BACKEND_DB_ROLE!r} (ADR-012), opcionalmente con el sufijo "
            f"'.<project-ref>' que exige el pooler."
        )


# Modos de `sslmode` que NO garantizan cifrado.
#   disable -> sin TLS
#   allow   -> TLS solo si el servidor lo exige
#   prefer  -> intenta TLS y CAE EN TEXTO PLANO en silencio  <- valor por defecto de libpq
_INSECURE_SSL_MODES = frozenset({"disable", "allow", "prefer"})

# Modos que sí exigen cifrado. `require` cifra; `verify-ca` y `verify-full` añaden
# validación del certificado y son aceptables por ser más estrictos.
_SECURE_SSL_MODES = frozenset({"require", "verify-ca", "verify-full"})

DEFAULT_SSL_MODE = "require"


def _enforce_tls(database_url: str) -> str:
    """Devuelve la URL garantizando TLS explícito.

    Sin `sslmode`, libpq usa `prefer`: intenta TLS y, si el servidor lo rechaza,
    continúa EN TEXTO PLANO sin error ni aviso. Un backend que transporta
    identidad de usuario no puede depender de un modo con retroceso silencioso.

        - sin `sslmode`              -> se inyecta `sslmode=require`
        - `disable`/`allow`/`prefer` -> ERROR: alguien lo debilitó a propósito
        - `require`/`verify-*`       -> se respeta (verify-* es más estricto)
        - cualquier otro valor       -> ERROR
    """
    try:
        parts = urlsplit(database_url)
    except ValueError as exc:
        raise ConfigError("DATABASE_URL no es una URL válida.") from exc

    query = parse_qsl(parts.query, keep_blank_values=True)
    modes = [value.strip().lower() for key, value in query if key.lower() == "sslmode"]

    if not modes:
        query.append(("sslmode", DEFAULT_SSL_MODE))
        return urlunsplit(parts._replace(query=urlencode(query)))

    mode = modes[-1]
    if mode in _INSECURE_SSL_MODES:
        raise ConfigError(
            f"DATABASE_URL usa sslmode={mode!r}, que no garantiza cifrado. "
            f"El backend exige sslmode={DEFAULT_SSL_MODE!r} o más estricto."
        )
    if mode not in _SECURE_SSL_MODES:
        raise ConfigError(
            f"DATABASE_URL usa un sslmode desconocido: {mode!r}. "
            f"Valores admitidos: {', '.join(sorted(_SECURE_SSL_MODES))}."
        )
    return database_url


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(
            f"Falta la variable de entorno {name}. "
            "Copia backend/.env.example a backend/.env.local y rellénala."
        )
    return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    if _ENV_FILE.exists():
        load_dotenv(_ENV_FILE)

    supabase_url = _require("SUPABASE_URL").rstrip("/")
    database_url = _require("DATABASE_URL")

    _reject_placeholders(database_url)
    _require_backend_role(database_url)
    database_url = _enforce_tls(database_url)

    return Settings(
        supabase_url=supabase_url,
        database_url=database_url,
        jwks_url=os.environ.get("SUPABASE_JWKS_URL")
        or f"{supabase_url}/auth/v1/.well-known/jwks.json",
        jwt_issuer=os.environ.get("SUPABASE_JWT_ISSUER") or f"{supabase_url}/auth/v1",
    )
