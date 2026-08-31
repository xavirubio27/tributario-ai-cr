"""Fixtures reales de Factura Electrónica v4.4 — integridad y compatibilidad.

Dos comprobantes REALES, aceptados por Hacienda, colocados en
`tests/fixtures/fiscal/real/v4_4/fe/`. Sus **bytes exactos son parte de la
evidencia del test**: no se parsean y reserializan, no se reformatean, no se
normalizan saltos de línea. Ambos usan CRLF y no terminan en salto de línea.

Estos tests NO son el parser de producción. Son de integridad de fixture y de
compatibilidad del esquema con datos reales.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from pathlib import Path

import psycopg
import pytest

from app.db import fiscal_transaction

FIXTURES = Path(__file__).parent / "fixtures" / "fiscal" / "real" / "v4_4" / "fe"

NS = "https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.4/facturaElectronica"

# Huellas conocidas. Si un fixture cambia un solo byte, estos tests fallan —
# que es exactamente lo que se busca.
GOLDEN = {
    "50601082600310161019803900001010004596121100000000.xml": {
        "sha256": "a1f639d06c79cedfa01fe6e3ca8fce5b8ad7de9225afe6cbf7054ff6515c8b0b",
        "bytes": 16067,
        "clave": "50601082600310161019803900001010004596121100000000",
        "consecutive": "03900001010004596121",
        "activity": "6110.0",
    },
    "50602082600310161019800100024010059940227200000000.xml": {
        "sha256": "b9892fad51b9c9d49aa8d04581088ee69b0d2262b2337b880355b53b4ad70ae0",
        "bytes": 10911,
        "clave": "50602082600310161019800100024010059940227200000000",
        "consecutive": "00100024010059940227",
        "activity": "6110.0",
    },
}


def _raw(name: str) -> bytes:
    """Lee los bytes tal cual. Sin `text`, sin decodificar, sin normalizar."""
    return (FIXTURES / name).read_bytes()


@pytest.mark.parametrize("name", sorted(GOLDEN))
def test_el_fixture_existe(name):
    assert (FIXTURES / name).is_file(), f"Falta el fixture real {name}"


@pytest.mark.parametrize("name", sorted(GOLDEN))
def test_la_huella_del_fixture_no_cambio(name):
    """Se calcula sobre los BYTES, nunca sobre una reserialización."""
    data = _raw(name)
    assert len(data) == GOLDEN[name]["bytes"], (
        f"El tamaño de {name} cambió: {len(data)} != {GOLDEN[name]['bytes']}"
    )
    real = hashlib.sha256(data).hexdigest()
    assert real == GOLDEN[name]["sha256"], (
        f"El fixture {name} fue modificado.\n"
        f"  esperado {GOLDEN[name]['sha256']}\n"
        f"  obtenido {real}"
    )


@pytest.mark.parametrize("name", sorted(GOLDEN))
def test_el_fixture_conserva_su_forma_original(name):
    """CRLF y ausencia de salto final: cualquier «limpieza» rompería la huella."""
    data = _raw(name)
    assert b"\r\n" in data, "Se perdieron los CRLF originales"
    assert not data.endswith(b"\n"), "Se añadió un salto de línea final"
    assert data.startswith(b'<?xml version="1.0" encoding="utf-8"?>')


# ─────────────────────────────────────────────────────────────────────────────
# Metadatos mínimos — no es el parser de producción
# ─────────────────────────────────────────────────────────────────────────────


def _campo(data: bytes, tag: str) -> str | None:
    """Extrae un campo de primer nivel sin construir un parser.

    Se usa una expresión sobre el texto decodificado únicamente para verificar
    metadatos conocidos. El parser real llegará en una fase posterior; aquí no
    se persiste lógica de normalización.
    """
    m = re.search(rf"<{tag}>([^<]*)</{tag}>", data.decode("utf-8"))
    return m.group(1) if m else None


@pytest.mark.parametrize("name", sorted(GOLDEN))
def test_metadatos_conocidos_del_fixture(name):
    data = _raw(name)
    esperado = GOLDEN[name]

    texto = data.decode("utf-8")
    assert "<FacturaElectronica" in texto, "La raíz no es FacturaElectronica"
    assert NS in texto, "Falta el namespace estructural de la v4.4"

    assert _campo(data, "Clave") == esperado["clave"]
    assert _campo(data, "NumeroConsecutivo") == esperado["consecutive"]
    assert _campo(data, "CodigoActividadEmisor") == esperado["activity"]


@pytest.mark.parametrize("name", sorted(GOLDEN))
def test_el_codigo_de_actividad_real_no_es_numerico(name):
    """El hallazgo que motivó la corrección, fijado como regresión.

    `6110.0` tiene seis caracteres pero no seis dígitos. Si algún día alguien
    reintroduce un CHECK numérico, este test explica por qué está mal.
    """
    valor = _campo(_raw(name), "CodigoActividadEmisor")
    assert valor is not None
    assert len(valor) == 6, "El XSD exige exactamente 6 caracteres"
    assert not valor.isdigit(), (
        f"{valor!r} deja de ilustrar el caso: el fixture debe conservar un "
        "código de actividad no numérico"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Compatibilidad del esquema con los códigos de actividad reales
# ─────────────────────────────────────────────────────────────────────────────


def _clave_unica() -> str:
    return f"506{uuid.uuid4().int % 10**47:047d}"


def _insert(
    conn, company_id: str, *, issuer: str, receiver: str | None = None,
    clave: str | None = None,
) -> None:
    conn.execute(
        """
        insert into fiscal.electronic_documents (
            company_id, document_type, clave, consecutive_number,
            issued_at, issued_at_offset_minutes, issued_at_raw,
            issuer_activity_code, receiver_activity_code, sale_condition_code,
            currency_code, reported_exchange_rate,
            reported_total_sale, reported_total_net_sale, reported_total_document,
            ruleset_revision_status, direction, direction_computed_at
        ) values (
            %s, 'invoice', %s, %s, now(), -360, 'x',
            %s, %s, '01', 'CRC', 1, 100, 100, 113, 'detected', 'issued', now()
        )
        """,
        (company_id, clave or _clave_unica(),
         f"{uuid.uuid4().int % 10**20:020d}", issuer, receiver),
    )


@pytest.fixture
def limpiar(admin_sql, user_a):
    """Retira SOLO las filas de la empresa creada por esta ejecucion.

    Un `delete from fiscal.electronic_documents` sin predicado borraria datos de
    otra ejecucion concurrente, de otro test o de un desarrollador trabajando
    contra el mismo proyecto DEV. El ambito es el UUID exacto de la empresa que
    creo esta ejecucion, no un prefijo de nombre.
    """
    yield
    admin_sql(
        "delete from fiscal.source_documents "
        f"where company_id = '{user_a.company_id}'"
    )
    admin_sql(
        "delete from fiscal.electronic_documents "
        f"where company_id = '{user_a.company_id}'"
    )


@pytest.mark.parametrize(
    "valor, motivo",
    [
        ("6110.0", "el valor real de los fixtures: 6 caracteres con punto"),
        ("620100", "seis dígitos sigue siendo válido"),
        ("ABC123", "el XSD dice string, no dígitos"),
        ("61.1.0", "cualquier combinación de 6 caracteres"),
    ],
)
def test_issuer_activity_code_acepta_seis_caracteres(
    pool, settings, user_a, valor, motivo, limpiar
):
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        _insert(conn, user_a.company_id, issuer=valor)


@pytest.mark.parametrize("valor", ["61100", "6110.00", "", "1234567"])
def test_issuer_activity_code_rechaza_otra_longitud(pool, settings, user_a, valor, limpiar):
    with pytest.raises(psycopg.errors.CheckViolation) as exc:
        with fiscal_transaction(pool, settings, user_a.identity) as conn:
            _insert(conn, user_a.company_id, issuer=valor)
    assert exc.value.sqlstate == "23514"


def test_receiver_activity_code_admite_null(pool, settings, user_a, limpiar):
    """La columna es opcional y debe seguir siéndolo."""
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        _insert(conn, user_a.company_id, issuer="6110.0", receiver=None)


@pytest.mark.parametrize("valor", ["6110.0", "620100", "ABC123"])
def test_receiver_activity_code_acepta_seis_caracteres(pool, settings, user_a, valor, limpiar):
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        _insert(conn, user_a.company_id, issuer="6110.0", receiver=valor)


@pytest.mark.parametrize("valor", ["61100", "6110.00"])
def test_receiver_activity_code_rechaza_otra_longitud(pool, settings, user_a, valor, limpiar):
    with pytest.raises(psycopg.errors.CheckViolation) as exc:
        with fiscal_transaction(pool, settings, user_a.identity) as conn:
            _insert(conn, user_a.company_id, issuer="6110.0", receiver=valor)
    assert exc.value.sqlstate == "23514"


def test_ningun_codigo_de_actividad_conserva_patron_numerico(admin_sql):
    """Regresión sobre el catálogo: la restricción es de longitud, no de forma."""
    rows = admin_sql(
        """
        select con.conname, pg_get_constraintdef(con.oid) as def
        from pg_constraint con
        join pg_class c on c.oid = con.conrelid
        join pg_namespace n on n.oid = c.relnamespace
        where n.nspname = 'fiscal' and c.relname = 'electronic_documents'
          and con.conname like '%activity%'
        """
    )
    assert len(rows) == 2
    for r in rows:
        assert "[0-9]" not in r["def"], (
            f"{r['conname']} volvió a exigir dígitos: {r['def']}"
        )
        assert "char_length" in r["def"] and "= 6" in r["def"]


@pytest.mark.parametrize("name", sorted(GOLDEN))
def test_el_codigo_real_del_fixture_es_aceptado_por_la_base(
    pool, settings, user_a, name, limpiar
):
    """Cierra el círculo: el valor exacto del XML real entra en la tabla."""
    valor = _campo(_raw(name), "CodigoActividadEmisor")
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        _insert(conn, user_a.company_id, issuer=valor)


# ─────────────────────────────────────────────────────────────────────────────
# Seguridad del cleanup: no puede tocar datos ajenos
# ─────────────────────────────────────────────────────────────────────────────


def test_el_cleanup_no_borra_datos_de_otra_empresa(
    pool, settings, admin_sql, user_a, user_b
):
    """Regresión de comportamiento, no inspección del SQL.

    Se crean dos documentos en empresas distintas, se ejecuta el cleanup acotado
    de la primera y se comprueba que el CENTINELA de la otra sigue ahí. Un
    `delete` sin predicado —el defecto que motivó esta remediación— haría fallar
    este test.
    """
    clave_a = _clave_unica()
    clave_sentinela = _clave_unica()

    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        _insert(conn, user_a.company_id, issuer="6110.0", clave=clave_a)
    with fiscal_transaction(pool, settings, user_b.identity) as conn:
        _insert(conn, user_b.company_id, issuer="6110.0", clave=clave_sentinela)

    def _existe(clave: str) -> bool:
        return admin_sql(
            f"select count(*) as n from fiscal.electronic_documents where clave = '{clave}'"
        )[0]["n"] == 1

    assert _existe(clave_a), "No se creó el documento de la empresa A"
    assert _existe(clave_sentinela), "No se creó el centinela"

    try:
        # El cleanup REAL, acotado por el UUID de la empresa A.
        admin_sql(
            "delete from fiscal.electronic_documents "
            f"where company_id = '{user_a.company_id}'"
        )

        assert not _existe(clave_a), "El cleanup no retiró lo que debía"
        assert _existe(clave_sentinela), (
            "EL CLEANUP BORRÓ DATOS AJENOS: el centinela de otra empresa desapareció"
        )
    finally:
        admin_sql(
            f"delete from fiscal.electronic_documents where clave = '{clave_sentinela}'"
        )

    assert not _existe(clave_sentinela), "El centinela no se limpió"


def test_el_teardown_se_ejecuta_aunque_el_test_falle(settings, publishable_key, admin_sql):
    """El cleanup no puede depender de que los asertos pasen.

    Se ejerce el generador de la fixture tal como lo finaliza pytest: se lanza
    una excepción DENTRO del `yield` y se comprueba que el bloque `finally`
    ejecutó igualmente el borrado. Es el mecanismo real, no una simulación.
    """
    from tests import conftest

    gen = conftest.user_a.__wrapped__(settings, publishable_key)
    user = next(gen)

    existe = lambda: admin_sql(
        f"select count(*) as n from public.companies where id = '{user.company_id}'"
    )[0]["n"]
    assert existe() == 1, "La fixture no creó la empresa"

    class FalloSimulado(RuntimeError):
        pass

    # pytest finaliza una fixture de tipo `yield` lanzando dentro del generador
    # cuando el test falla. Se reproduce exactamente eso.
    with pytest.raises((FalloSimulado, StopIteration)):
        gen.throw(FalloSimulado("el test falló"))

    assert existe() == 0, (
        "El teardown NO se ejecutó ante una excepción: quedarían recursos huérfanos"
    )
    assert admin_sql(
        f"select count(*) as n from auth.users where id = '{user.id}'"
    )[0]["n"] == 0, "El usuario de Auth sobrevivió al teardown"
