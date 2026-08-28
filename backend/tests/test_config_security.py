"""Guardas de configuración del backend.

Dos propiedades que deben cumplirse ANTES de que la aplicación pueda arrancar:

1. No conectarse nunca con un rol privilegiado (BYPASSRLS anularía el aislamiento).
2. No conectarse nunca sin TLS explícito.

Todas las cadenas de este archivo son SINTÉTICAS. Ninguna credencial real.
"""

from __future__ import annotations

import pytest

from app.config import (
    BACKEND_DB_ROLE,
    DEFAULT_SSL_MODE,
    ConfigError,
    _enforce_tls,
    _require_backend_role,
    parse_login_role,
)

BASE = "postgresql://app_backend.abcdefghijklmnop:fake-password@pooler.example.com:5432/postgres"


# ── Rol de login: validación POSITIVA ─────────────────────────────────────────

@pytest.mark.parametrize(
    "role",
    [
        "postgres",
        "service_role",
        "supabase_admin",
        "authenticated",
        "anon",
        "some_random_role",
        "future_privileged_role",
        # Nombres que se parecen al aprobado pero no lo son.
        "app_backend_evil",
        "my_app_backend",
        "App_Backend",
    ],
)
def test_only_app_backend_is_accepted(role):
    """Validación positiva: cualquier rol distinto se rechaza.

    Incluye roles que no parecen peligrosos. Una lista negra los dejaría pasar.
    """
    with pytest.raises(ConfigError):
        _require_backend_role(f"postgresql://{role}:pw@host.example.com:5432/postgres")


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://app_backend:pw@host.example.com:5432/postgres",
        # Formato del pooler: `<rol>.<project-ref>`
        "postgresql://app_backend.abcdefghijklmnop:pw@pooler.example.com:5432/postgres",
    ],
)
def test_backend_role_is_accepted(url):
    _require_backend_role(url)  # no debe lanzar


def test_connection_string_without_user_is_rejected():
    with pytest.raises(ConfigError):
        _require_backend_role("postgresql://host.example.com:5432/postgres")


def test_parse_login_role_strips_pooler_suffix():
    assert (
        parse_login_role(
            "postgresql://app_backend.abcdefghijklmnop:pw@pooler.example.com:5432/postgres"
        )
        == "app_backend"
    )


def test_backend_role_constant_matches_adr():
    assert BACKEND_DB_ROLE == "app_backend"


# ── TLS ───────────────────────────────────────────────────────────────────────

def test_missing_sslmode_is_upgraded_to_require():
    """Sin `sslmode`, libpq usaría `prefer` y caería a texto plano en silencio."""
    result = _enforce_tls(BASE)
    assert f"sslmode={DEFAULT_SSL_MODE}" in result


@pytest.mark.parametrize("mode", ["disable", "allow", "prefer", "PREFER", " Disable "])
def test_insecure_sslmode_is_rejected(mode):
    with pytest.raises(ConfigError, match="cifrado"):
        _enforce_tls(f"{BASE}?sslmode={mode.strip()}")


@pytest.mark.parametrize("mode", ["require", "verify-ca", "verify-full"])
def test_secure_sslmode_is_preserved(mode):
    """`verify-*` es más estricto que `require`: no debe degradarse."""
    result = _enforce_tls(f"{BASE}?sslmode={mode}")
    assert f"sslmode={mode}" in result


def test_unknown_sslmode_is_rejected():
    with pytest.raises(ConfigError, match="desconocido"):
        _enforce_tls(f"{BASE}?sslmode=inventado")


def test_other_query_parameters_are_preserved():
    result = _enforce_tls(f"{BASE}?application_name=tributario&connect_timeout=10")
    assert "application_name=tributario" in result
    assert "connect_timeout=10" in result
    assert f"sslmode={DEFAULT_SSL_MODE}" in result


def test_enforced_url_is_parseable_by_psycopg():
    """La URL resultante debe seguir siendo una cadena de conexión válida."""
    import psycopg

    info = psycopg.conninfo.conninfo_to_dict(_enforce_tls(BASE))
    assert info["sslmode"] == DEFAULT_SSL_MODE
    assert info["user"].startswith("app_backend")


# ── Verificación en runtime ───────────────────────────────────────────────────

def test_live_connection_is_actually_encrypted(pool):
    """La conexión real del backend debe estar cifrada.

    INSTRUMENTO CORRECTO — `pgconn.ssl_in_use`, no `pg_stat_ssl`.

        Se conecta a través de Supavisor (pooler). `pg_stat_ssl` describe la
        conexión que PostgreSQL ve, que es la de SUPAVISOR, no la nuestra:
        reporta `ssl=false` porque ese tramo interno de la infraestructura de
        Supabase no usa TLS y está fuera de nuestro control.

        El tramo que sí controlamos es cliente -> Supavisor. `PQsslInUse`, que
        libpq expone como `pgconn.ssl_in_use`, informa precisamente de ese.

        Refuerzo independiente: la conexión lleva `sslmode=require`, con el que
        libpq SE NIEGA a conectar si no logra negociar TLS. Haber conectado es,
        por sí solo, evidencia de cifrado.
    """
    with pool.connection() as conn:
        assert conn.pgconn.ssl_in_use is True, (
            "La conexión cliente -> pooler NO está cifrada"
        )


def test_pooler_internal_leg_is_documented_not_asserted(pool):
    """Deja constancia del tramo interno, sin afirmar sobre él.

    No se exige TLS aquí porque no depende de nosotros. Se registra para que
    nadie interprete el `ssl=false` de `pg_stat_ssl` como un fallo del backend.
    """
    with pool.connection() as conn:
        row = conn.execute(
            "select ssl from pg_stat_ssl where pid = pg_backend_pid()"
        ).fetchone()
    assert row is not None
    assert isinstance(row["ssl"], bool)


# ── Marcadores sin sustituir ──────────────────────────────────────────────────

@pytest.mark.parametrize(
    "url",
    [
        "postgresql://app_backend.abc:pw@<pooler-host>:5432/postgres",
        "postgresql://app_backend.abc:<password>@host.example.com:5432/postgres",
        "postgresql://<db-user>:pw@host.example.com:5432/postgres",
    ],
)
def test_template_placeholders_are_rejected(url):
    """Debe fallar de inmediato y con mensaje accionable, no colgarse en DNS."""
    from app.config import _reject_placeholders

    with pytest.raises(ConfigError, match="marcador"):
        _reject_placeholders(url)


def test_real_looking_values_pass_placeholder_check():
    from app.config import _reject_placeholders

    _reject_placeholders(
        "postgresql://app_backend.abcdefghijklmnop:fake-password"
        "@aws-1-us-west-2.pooler.example.com:5432/postgres?sslmode=require"
    )
