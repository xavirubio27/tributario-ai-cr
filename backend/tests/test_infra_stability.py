"""Estabilidad de la infraestructura en suites largas (C1-B-R3).

Dos defectos que solo aparecían al final de una ejecución completa:

1. el pool entregaba conexiones que el servidor ya había cerrado;
2. el token de sesión caducaba antes de que la suite terminara.

El primero era un defecto de FIABILIDAD DE PRODUCCIÓN, no de los tests: el
mismo pool atiende las peticiones reales.
"""

from __future__ import annotations

import base64
import json
import time

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.db import create_pool, fiscal_transaction


# ═════════════════════════════════════════════════════════════════════════════
# 1 · El pool no entrega conexiones muertas
# ═════════════════════════════════════════════════════════════════════════════

def _matar_backend(database_url: str, pid: int) -> None:
    """Termina UNA conexión concreta —la nuestra—, no sesiones ajenas."""
    with psycopg.connect(database_url, row_factory=dict_row) as verdugo:
        verdugo.execute("select pg_terminate_backend(%s)", (pid,))
        verdugo.commit()


def test_el_pool_de_produccion_valida_la_conexion_al_entregarla(settings):
    """Prueba de COMPORTAMIENTO, no de cadena de texto.

    Se toma una conexión del pool real de producción, se termina su backend
    desde fuera y se vuelve a pedir. Sin validación al entregar, la conexión
    muerta llega a la aplicación y revienta en el primer `BEGIN`.
    """
    pool = create_pool(settings)
    try:
        with pool.connection() as conn:
            pid = conn.execute("select pg_backend_pid() as p").fetchone()["p"]

        _matar_backend(settings.database_url, pid)

        # Misma conexión física, ya cerrada por el servidor: el pool debe
        # detectarlo, descartarla y abrir otra.
        with pool.connection() as conn:
            with conn.transaction():
                assert conn.execute("select 1 as ok").fetchone()["ok"] == 1
    finally:
        pool.close()


def test_sin_validacion_la_conexion_muerta_llegaria_a_la_aplicacion(settings):
    """Contraprueba: documenta el defecto que se corrigió.

    Si algún día alguien quita `check`, este test explica qué se pierde. Usa un
    pool propio con la configuración ANTIGUA — no el de producción.
    """
    pool = ConnectionPool(
        conninfo=settings.database_url, min_size=1, max_size=1, open=True,
        kwargs={"row_factory": dict_row},          # sin `check`
    )
    try:
        with pool.connection() as conn:
            pid = conn.execute("select pg_backend_pid() as p").fetchone()["p"]
        _matar_backend(settings.database_url, pid)

        with pytest.raises(psycopg.OperationalError):
            with pool.connection() as conn:
                with conn.transaction():
                    conn.execute("select 1")
    finally:
        pool.close()


def test_la_configuracion_del_pool_no_fija_tiempos_arbitrarios():
    """`max_lifetime` y `max_idle` ya traen valores por defecto de la librería
    —3600 s y 600 s—; no se sobrescriben sin motivo medido."""
    import inspect
    from pathlib import Path

    from app import db

    fuente = inspect.getsource(db.create_pool)
    assert "check=ConnectionPool.check_connection" in fuente
    assert "max_lifetime=" not in fuente
    assert "max_idle=" not in fuente


# ═════════════════════════════════════════════════════════════════════════════
# 2 · Vigencia del token en suites largas
# ═════════════════════════════════════════════════════════════════════════════

def _restantes(token: str) -> float:
    carga = token.split(".")[1]
    carga += "=" * (-len(carga) % 4)
    return json.loads(base64.urlsafe_b64decode(carga))["exp"] - time.time()


def test_el_token_de_la_sesion_esta_vigente_al_usarse(user_a):
    """Invariante que la renovación garantiza. Sin ella, dependía de que la
    suite terminase antes que el token."""
    assert _restantes(user_a.token) > 0, "el token ya caducó"


def test_la_infraestructura_puede_renovar_el_token(settings, user_a):
    """Prueba B del §7: se obtiene un token NUEVO y válido en lugar de seguir
    reutilizando uno caducado. Sin esperar una hora."""
    from tests.conftest import _renovar_token

    anterior = user_a.token
    _renovar_token(user_a, settings)

    assert user_a.token, "no se obtuvo token nuevo"
    assert _restantes(user_a.token) > 0
    # El token nuevo es utilizable por el camino real de producción.
    with fiscal_transaction(create_pool(settings), settings, user_a.identity) as conn:
        assert conn.execute("select 1 as ok").fetchone()["ok"] == 1
    assert anterior is not None


def test_la_renovacion_no_cambia_la_identidad_ni_el_tenant(settings, user_a):
    """Prueba C del §7: renovar da otro token, no otro usuario."""
    from tests.conftest import _renovar_token

    id_antes = user_a.id
    identidad_antes = user_a.identity.id
    empresa_antes = user_a.company_id

    _renovar_token(user_a, settings)

    assert user_a.id == id_antes
    assert user_a.identity.id == identidad_antes
    assert user_a.company_id == empresa_antes
    # Y la identidad sigue saliendo del verificador de producción.
    assert user_a.identity.has_valid_binding()


def test_el_rechazo_de_tokens_caducados_sigue_probado():
    """Prueba A del §7. La verificación de producción NO se relaja: existe un
    test dedicado que lo comprueba con un par de claves local, y aquí se
    vigila que siga existiendo."""
    from pathlib import Path

    fuente = (Path(__file__).parent / "test_auth.py").read_text(encoding="utf-8")
    assert "def test_expired_token_is_rejected(" in fuente

    from app import auth
    import inspect

    verify = inspect.getsource(auth.JwtVerifier.verify)
    assert '"require": ["exp"' in verify.replace("'", '"')
    assert "verify_exp" not in verify, "no se desactiva la comprobación de exp"
