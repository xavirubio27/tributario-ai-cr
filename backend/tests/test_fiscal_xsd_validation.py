"""Validación XSD reproducible contra los esquemas oficiales v4.4 (A2-C).

El criterio de aceptación de esta fase es que **todo esto funcione desde un
clon limpio del repositorio**, sin red y sin ficheros fuera del repo. Los
esquemas están versionados en `backend/resources/fiscal/xsd/cr/` con su
manifiesto de procedencia y sus huellas.

Estos tests NO son el parser de producción: no extraen Clave, ni partes, ni
líneas, ni impuestos. Solo comprueban que los documentos reales son
estructuralmente conformes al esquema oficial que les corresponde.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import socket
from collections import Counter
from contextlib import contextmanager
from pathlib import Path

import pytest
from lxml import etree

from tests.support import fiscal_xsd as fx
from tests.support import xsd_bundle_policy as policy

FIXTURES = Path(__file__).parent / "fixtures" / "fiscal" / "real" / "v4_4"

NS_CR = "https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.4"

# Expectativa declarada aparte del manifiesto: si ambos salieran de la misma
# fuente, el test no detectaría una edición del manifiesto.
ESQUEMAS_ESPERADOS = {
    "cr.fe.v4_4": ("FacturaElectronica",     f"{NS_CR}/facturaElectronica"),
    "cr.te.v4_4": ("TiqueteElectronico",     f"{NS_CR}/tiqueteElectronico"),
    "cr.nc.v4_4": ("NotaCreditoElectronica", f"{NS_CR}/notaCreditoElectronica"),
    "cr.nd.v4_4": ("NotaDebitoElectronica",  f"{NS_CR}/notaDebitoElectronica"),
    "cr.mh.v4_4": ("MensajeHacienda",        f"{NS_CR}/mensajeHacienda"),
    "w3c.xmldsig": (None, "http://www.w3.org/2000/09/xmldsig#"),
}


def _todos_los_fixtures() -> list[str]:
    return sorted(str(p.relative_to(FIXTURES)) for p in FIXTURES.rglob("*.xml"))


# ─────────────────────────────────────────────────────────────────────────────
# A · B — Manifiesto e integridad de bytes
# ─────────────────────────────────────────────────────────────────────────────

def test_el_manifiesto_existe_y_es_json_valido():
    doc = fx.manifest()
    assert doc["manifest_version"] == 1
    assert len(doc["schemas"]) == len(ESQUEMAS_ESPERADOS)


def test_el_manifiesto_declara_los_esquemas_esperados():
    declarado = {e.id: (e.root, e.namespace) for e in fx.entries()}
    assert declarado == ESQUEMAS_ESPERADOS


@pytest.mark.parametrize("entry", fx.entries(), ids=lambda e: e.id)
def test_cada_xsd_coincide_con_su_huella_del_manifiesto(entry):
    """Si un esquema cambia un byte, el manifiesto deja de cuadrar.

    Es la misma disciplina que los fixtures golden: la procedencia solo vale
    si podemos demostrar que el fichero no se ha tocado.
    """
    ruta = fx.BUNDLE / entry.path
    assert ruta.is_file(), f"Falta el esquema {entry.path}"
    datos = ruta.read_bytes()
    assert len(datos) == entry.bytes
    assert hashlib.sha256(datos).hexdigest() == entry.sha256


def test_las_huellas_de_hacienda_coinciden_con_las_registradas_en_e0():
    """Ancla de procedencia independiente.

    E0 registró estas huellas el 2026-08-29 desde una descarga distinta. Que
    coincidan demuestra que el paquete versionado hoy es el mismo artefacto
    oficial, no una copia de origen incierto.
    """
    e0 = {
        "cr.fe.v4_4": "d384afef665573606f6499b2182d6070",
        "cr.nc.v4_4": "9af7dff4ee0c2787f8fc30cb63aef37b",
        "cr.nd.v4_4": "ac2c63f93602502af22980a81f26032c",
        "cr.te.v4_4": "cda1c7dd97f9a235111c29948f05d789",
        "cr.mh.v4_4": "411d858b0e2e293322910a0d4204243d",
    }
    por_id = {e.id: e for e in fx.entries()}
    for schema_id, prefijo in e0.items():
        assert por_id[schema_id].sha256.startswith(prefijo), (
            f"{schema_id} ya no coincide con la huella verificada en E0"
        )


# ─────────────────────────────────────────────────────────────────────────────
# C · D — Cierre de dependencias y compilación
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("entry", fx.entries(), ids=lambda e: e.id)
def test_toda_dependencia_declarada_existe_en_el_paquete(entry):
    conocidos = {e.id for e in fx.entries()}
    for dep in entry.dependencies:
        assert dep in conocidos, f"{entry.id} depende de {dep}, que no está"


@pytest.mark.parametrize("entry", fx.entries(), ids=lambda e: e.id)
def test_los_imports_del_xsd_resuelven_dentro_del_repositorio(entry):
    """Ningún `schemaLocation` puede quedar sin resolver localmente.

    Los esquemas de Hacienda importan `../../xmldsig-core-schema.xsd`; el
    paquete reproduce esa profundidad para que resuelva sin editar los
    ficheros oficiales ni instalar un resolutor a medida.
    """
    ruta = fx.BUNDLE / entry.path
    doc = etree.parse(str(ruta), parser=etree.XMLParser(
        no_network=True, resolve_entities=False, load_dtd=False))
    XS = "{http://www.w3.org/2001/XMLSchema}"
    for etiqueta in (f"{XS}import", f"{XS}include"):
        for nodo in doc.getroot().iter(etiqueta):
            loc = nodo.get("schemaLocation")
            if loc is None:
                continue
            assert not loc.startswith(("http://", "https://")), (
                f"{entry.id} importa por red: {loc}"
            )
            destino = (ruta.parent / loc).resolve()
            assert destino.is_file(), f"{entry.id}: no resuelve {loc}"
            assert fx.BUNDLE.resolve() in destino.parents, (
                f"{entry.id}: {loc} escapa del paquete"
            )


@pytest.mark.parametrize("entry", fx.entries(), ids=lambda e: e.id)
def test_cada_esquema_compila_en_solitario(entry):
    """Los SEIS artefactos compilan por sí solos, dependencia incluida.

    En la primera versión de A2-C el XMLDSIG se saltaba «porque se compila a
    través de quien lo importa». Era una excusa, no una razón: compila solo
    perfectamente, y saltarlo dejaba sin cubrir la única dependencia externa
    del paquete.
    """
    schema = fx.compilar(entry.id)
    assert isinstance(schema, etree.XMLSchema)


def test_el_xmldsig_tiene_contrato_propio():
    """La dependencia del W3C se verifica de forma directa, sin intermediarios."""
    dsig = next((e for e in fx.entries() if e.id == "w3c.xmldsig"), None)
    assert dsig is not None, "El manifiesto no declara el XMLDSIG"

    assert dsig.namespace == "http://www.w3.org/2000/09/xmldsig#"
    assert dsig.root is None, "No es un documento raíz, es una dependencia"

    datos = (fx.BUNDLE / dsig.path).read_bytes()
    assert len(datos) == dsig.bytes
    assert hashlib.sha256(datos).hexdigest() == dsig.sha256

    entrada_manifiesto = next(
        e for e in fx.manifest()["schemas"] if e["id"] == "w3c.xmldsig"
    )
    assert "w3.org" in entrada_manifiesto["source_url"]
    assert "W3C" in entrada_manifiesto["source_authority"], (
        "La autoridad del XMLDSIG es el W3C, no Hacienda"
    )

    # Compila en solitario…
    assert isinstance(fx.compilar("w3c.xmldsig"), etree.XMLSchema)

    # …y no arrastra ningún import sin resolver.
    doc = etree.parse(str(fx.BUNDLE / dsig.path), parser=fx._parser())
    XS = "{http://www.w3.org/2001/XMLSchema}"
    pendientes = [
        n.get("schemaLocation")
        for etiqueta in (f"{XS}import", f"{XS}include")
        for n in doc.getroot().iter(etiqueta)
        if n.get("schemaLocation")
    ]
    assert pendientes == [], f"El XMLDSIG importa {pendientes}"


def test_los_cinco_esquemas_de_hacienda_dependen_del_xmldsig():
    hacienda = [e for e in fx.entries() if e.id.startswith("cr.")]
    assert len(hacienda) == 5
    for e in hacienda:
        assert "w3c.xmldsig" in e.dependencies


# ─────────────────────────────────────────────────────────────────────────────
# E — Selección determinista
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "schema_id,raiz_ns",
    [(k, v) for k, v in ESQUEMAS_ESPERADOS.items() if v[0] is not None],
)
def test_la_seleccion_por_raiz_y_namespace_es_correcta(schema_id, raiz_ns):
    raiz, ns = raiz_ns
    assert fx.esquema_para(raiz, ns).id == schema_id


def test_una_raiz_desconocida_no_selecciona_ningun_esquema():
    """Preferimos no elegir a elegir mal."""
    assert fx.esquema_para("FacturaElectronica", "urn:inventado") is None
    assert fx.esquema_para("DocumentoInexistente", f"{NS_CR}/facturaElectronica") is None


def test_el_namespace_debe_coincidir_exactamente():
    """Una versión distinta del namespace no debe caer en el esquema de 4.4."""
    ns_43 = NS_CR.replace("v4.4", "v4.3")
    assert fx.esquema_para("FacturaElectronica", ns_43) is None


# ─────────────────────────────────────────────────────────────────────────────
# F — Los 24 fixtures reales contra su esquema oficial
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("rel", _todos_los_fixtures())
def test_cada_fixture_real_valida_contra_su_esquema_oficial(rel):
    datos = (FIXTURES / rel).read_bytes()
    valido, error, entrada = fx.validar(datos)
    assert entrada is not None, f"{rel}: sin esquema para su raíz"
    assert valido, f"{rel} no valida contra {entrada.id}:\n  {error}"


def test_el_reparto_de_fixtures_por_esquema_es_el_esperado():
    from collections import Counter
    reparto = Counter()
    for rel in _todos_los_fixtures():
        _, _, entrada = fx.validar((FIXTURES / rel).read_bytes())
        reparto[entrada.id] += 1
    assert dict(reparto) == {
        "cr.fe.v4_4": 11,
        "cr.te.v4_4": 1,
        "cr.nc.v4_4": 1,
        "cr.mh.v4_4": 11,
    }


def test_no_hay_fixture_de_nota_de_debito_todavia():
    """El esquema ND está incorporado y compila, pero **no hay comprobante
    real**. Se fija para que el hueco no se dé por cerrado sin fixture."""
    assert fx.esquema_para(
        "NotaDebitoElectronica", f"{NS_CR}/notaDebitoElectronica"
    ) is not None
    claves = {fx.raiz_de((FIXTURES / r).read_bytes())[0]
              for r in _todos_los_fixtures()}
    assert "NotaDebitoElectronica" not in claves, (
        "Ya existe una Nota de Débito real: cierra el hueco y reescribe este test"
    )


# ─────────────────────────────────────────────────────────────────────────────
# G · H — Sin red, sin entidades externas
# ─────────────────────────────────────────────────────────────────────────────

def test_el_paquete_no_referencia_rutas_absolutas_de_maquina():
    """Un clon limpio no tiene `/Users/...` ni `~/Downloads`."""
    for entry in fx.entries():
        texto = (fx.BUNDLE / entry.path).read_text(encoding="utf-8", errors="replace")
        for veneno in ("/Users/", "/home/", "C:\\\\", "Downloads", "scratchpad"):
            assert veneno not in texto, f"{entry.id} referencia {veneno}"
    crudo = fx.MANIFEST.read_text(encoding="utf-8")
    for veneno in ("/Users/", "/home/", "Downloads", "scratchpad"):
        assert veneno not in crudo, f"El manifiesto referencia {veneno}"


def test_la_validacion_no_expande_entidades_externas():
    """XXE: la entidad queda SIN expandir y el fichero jamás se lee.

    Comprobado por comportamiento: `resolve_entities=False` no lanza error,
    deja la referencia como nodo `_Entity`. Lo que importa no es que falle,
    sino que **el contenido del disco no aparezca en el árbol**.
    """
    ataque = (
        b'<?xml version="1.0"?>'
        b'<!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
        b'<r>&x;</r>'
    )
    doc = etree.fromstring(ataque, parser=fx._parser())
    serializado = etree.tostring(doc, encoding="unicode")

    assert doc.text is None, "La entidad se expandió"
    assert "&x;" in serializado, "Se esperaba la referencia sin resolver"
    assert "root:" not in serializado and "/bin/" not in serializado, (
        "Se filtró contenido del sistema de ficheros"
    )


def test_la_validacion_no_expande_entidades_internas():
    """Misma defensa frente a la expansión exponencial de entidades."""
    bomba = (
        b'<?xml version="1.0"?>'
        b'<!DOCTYPE l [<!ENTITY a "AA"><!ENTITY b "&a;&a;&a;&a;">]>'
        b'<l>&b;</l>'
    )
    doc = etree.fromstring(bomba, parser=fx._parser())
    assert "&b;" in etree.tostring(doc, encoding="unicode")
    assert "AA" not in etree.tostring(doc, encoding="unicode")


@contextmanager
def _red_bloqueada():
    """Corta la red **en Python** y registra cualquier intento.

    `no_network=True` vive dentro de libxml2 y no deja rastro. Esto intercepta
    las tres puertas de salida de Python —`socket.socket.connect`,
    `socket.create_connection` y `socket.getaddrinfo`— para poder afirmar, con
    evidencia y no por confianza, que no se intentó salir a la red.
    """
    intentos: list[str] = []
    orig_connect = socket.socket.connect
    orig_create = socket.create_connection
    orig_addr = socket.getaddrinfo

    def _connect(self, address, *a, **k):
        intentos.append(f"socket.connect{address}")
        raise OSError("RED BLOQUEADA por el test")

    def _create(address, *a, **k):
        intentos.append(f"create_connection{address}")
        raise OSError("RED BLOQUEADA por el test")

    def _addr(host, port, *a, **k):
        intentos.append(f"getaddrinfo({host}:{port})")
        raise socket.gaierror("RED BLOQUEADA por el test")

    socket.socket.connect = _connect
    socket.create_connection = _create
    socket.getaddrinfo = _addr
    try:
        yield intentos
    finally:
        socket.socket.connect = orig_connect
        socket.create_connection = orig_create
        socket.getaddrinfo = orig_addr


def test_todo_funciona_desde_cero_con_la_red_cortada():
    """La prueba central de A2-C, y la única que demuestra el criterio.

    Se parte de estado **limpio** —sin esquemas compilados en caché— y con la
    red interceptada: se lee el manifiesto, se compilan los seis esquemas, se
    resuelve la dependencia local del XMLDSIG y se validan los 24
    comprobantes reales. Reutilizar una caché previa invalidaría la prueba.
    """
    fx.limpiar_cache()
    politica = fx.PoliticaDeRecursos()

    with _red_bloqueada() as intentos:
        assert fx.manifest()["manifest_version"] == 1
        for entrada in fx.entries():
            assert isinstance(fx.compilar(entrada.id, politica), etree.XMLSchema)

        reparto = Counter()
        for rel in _todos_los_fixtures():
            valido, error, e = fx.validar((FIXTURES / rel).read_bytes(), politica)
            assert valido, f"{rel} falló sin red: {error}"
            reparto[e.id] += 1

    assert intentos == [], f"Se intentó salir a la red: {intentos}"
    assert politica.rechazados == [], f"Recursos rechazados: {politica.rechazados}"
    assert dict(reparto) == {
        "cr.fe.v4_4": 11, "cr.te.v4_4": 1, "cr.nc.v4_4": 1, "cr.mh.v4_4": 11,
    }
    # El XMLDSIG se resolvió localmente, desde el paquete.
    assert any("xmldsig-core-schema.xsd" in x for x in politica.permitidos)
    assert all(str(fx.BUNDLE.resolve()) in x for x in politica.permitidos)

    fx.limpiar_cache()


@pytest.mark.parametrize(
    "url",
    [
        "https://example.invalid/schema.xsd",
        "http://example.invalid/schema.xsd",
        "ftp://example.invalid/schema.xsd",
    ],
)
def test_la_politica_rechaza_recursos_remotos_antes_de_la_red(url):
    """Rechazo **local**, sin depender de que el DNS falle.

    Si la prueba se apoyara en que el host no existe, en otra red podría
    resolver y el test dejaría de probar nada.
    """
    politica = fx.PoliticaDeRecursos()
    with _red_bloqueada() as intentos:
        with pytest.raises(fx.ResolucionRechazada):
            politica.resolve(url, None, None)
    assert intentos == [], "Se tocó la red antes de rechazar"
    assert politica.rechazados == [url]


def test_la_politica_rechaza_rutas_fuera_del_paquete():
    """Ni siquiera un fichero local vale si está fuera del paquete."""
    politica = fx.PoliticaDeRecursos()
    for ruta in ("/etc/passwd", str(FIXTURES / "fe"), "../../../../etc/hosts"):
        with pytest.raises(fx.ResolucionRechazada):
            politica.resolve(ruta, None, None)
    assert len(politica.rechazados) == 3


def test_la_politica_permite_el_xmldsig_del_paquete():
    """El rechazo no puede ser indiscriminado: la dependencia legítima pasa."""
    politica = fx.PoliticaDeRecursos()
    destino = fx.BUNDLE / "xmldsig-core-schema.xsd"
    politica.resolve(str(destino), None, None)
    assert politica.rechazados == []
    assert len(politica.permitidos) == 1


def test_un_schemalocation_remoto_no_selecciona_ningun_esquema():
    """Complementa al bloqueo: un documento ajeno no se valida contra nada."""
    remoto = (
        '<?xml version="1.0"?>'
        '<r xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        '   xsi:noNamespaceSchemaLocation="https://example.invalid/x.xsd"/>'
    ).encode()
    with _red_bloqueada() as intentos:
        valido, motivo, entrada = fx.validar(remoto)
    assert entrada is None and not valido
    assert "Sin esquema" in motivo
    assert intentos == []


def test_ningun_esquema_importa_por_red():
    for entry in fx.entries():
        texto = (fx.BUNDLE / entry.path).read_text(encoding="utf-8", errors="replace")
        assert 'schemaLocation="http' not in texto, (
            f"{entry.id} declara un schemaLocation remoto"
        )


# ─────────────────────────────────────────────────────────────────────────────
# I — El hallazgo temporal, ahora reproducible desde el repositorio
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "schema_id", ["cr.fe.v4_4", "cr.te.v4_4", "cr.nc.v4_4", "cr.nd.v4_4"]
)
def test_fecha_emision_es_xs_datetime_sin_restriccion_de_huso(schema_id):
    """Reproduce en un clon limpio la evidencia que sostiene ADR-039.

    Hasta A2-C esta afirmación descansaba en una inspección que ya no podía
    repetirse. Ahora se comprueba contra el esquema oficial versionado.
    """
    entrada = next(e for e in fx.entries() if e.id == schema_id)
    doc = etree.parse(str(fx.BUNDLE / entrada.path), parser=fx._parser())
    XS = "{http://www.w3.org/2001/XMLSchema}"

    encontrados = 0
    for el in doc.getroot().iter(f"{XS}element"):
        if el.get("name") not in ("FechaEmision", "FechaEmisionIR"):
            continue
        encontrados += 1
        # 1. El tipo es directamente xs:dateTime, sin indirección.
        assert el.get("type") == "xs:dateTime", (
            f"{el.get('name')} dejó de ser xs:dateTime en {schema_id}"
        )
        # 2. Ninguna restricción local lo estrecha.
        hijos = [c.tag.split("}")[-1] for c in el.iter() if c is not el]
        assert "simpleType" not in hijos and "restriction" not in hijos
        assert "pattern" not in hijos
    assert encontrados >= 2, f"{schema_id}: no se hallaron ambas fechas"
    # 3. En XSD 1.0, el huso de xs:dateTime es opcional por definición del
    #    tipo. Es lo que aplica aquí: no se apoya en `explicitTimezone`, que
    #    es faceta de 1.1 y este validador no interpretaría.


def test_hacienda_declara_minversion_1_1_sin_usarla():
    """Se fija el hecho para que el día que cambie salte una alarma."""
    hacienda = [e for e in fx.entries() if e.id.startswith("cr.")]
    for entry in hacienda:
        texto = (fx.BUNDLE / entry.path).read_text(encoding="utf-8", errors="replace")
        assert 'vc:minVersion="1.1"' in texto, f"{entry.id} ya no lo declara"
        # `vc:` no aparece fuera del elemento <xs:schema>.
        cabecera = texto[: texto.index(">", texto.index("<xs:schema")) + 1]
        assert texto.count("vc:") == cabecera.count("vc:"), (
            f"{entry.id} usa el namespace de versionado fuera de <xs:schema>"
        )


def test_los_comprobantes_sin_desplazamiento_validan():
    """La prueba decisiva: conductual, bajo el validador que de verdad usamos.

    Cuatro comprobantes reales no declaran desplazamiento **y aun así validan**
    contra el esquema oficial versionado. Bajo la validación efectiva que
    realizamos —XSD 1.0 sobre libxml2—, el huso es OPCIONAL.

    Esto es más fuerte que leer el esquema: no depende de interpretar facetas
    ni de razonar sobre `explicitTimezone`. Es el respaldo empírico de
    ADR-039, y no reabre esa decisión.
    """
    import re
    sin_offset = []
    for rel in _todos_los_fixtures():
        datos = (FIXTURES / rel).read_bytes()
        local, _ = fx.raiz_de(datos)
        if local == "MensajeHacienda":
            continue
        m = re.search(r"<FechaEmision>([^<]*)</FechaEmision>", datos.decode("utf-8"))
        assert m, f"{rel}: sin FechaEmision"
        if not re.search(r"([+-]\d{2}:\d{2}|Z)$", m.group(1)):
            sin_offset.append(rel)

    assert len(sin_offset) == 4, (
        f"Se esperaban 4 comprobantes sin desplazamiento, hay {len(sin_offset)}"
    )
    for rel in sin_offset:
        valido, error, _ = fx.validar((FIXTURES / rel).read_bytes())
        assert valido, f"{rel} no valida pese a no declarar desplazamiento:\n  {error}"


# ─────────────────────────────────────────────────────────────────────────────
# Validación XSD ≠ verificación criptográfica
# ─────────────────────────────────────────────────────────────────────────────

def test_la_firma_se_valida_en_estructura_no_criptograficamente():
    """Un documento firmado valida su `ds:Signature` **como estructura**.

    Que el XSD acepte la firma NO significa que la firma sea criptográficamente
    válida: eso exige verificar digest y certificado, y A2-C no lo hace.
    Se fija la distinción para que nadie la confunda más adelante.
    """
    rel = next(r for r in _todos_los_fixtures() if r.startswith("fe/"))
    datos = (FIXTURES / rel).read_bytes()
    assert b"Signature" in datos, "El fixture perdió su firma"
    valido, error, entrada = fx.validar(datos)
    assert valido, error
    # El esquema de firma se resolvió localmente para poder llegar hasta aquí.
    assert "w3c.xmldsig" in entrada.dependencies


# ─────────────────────────────────────────────────────────────────────────────
# Puerta de compatibilidad: el paquete de esquemas está anclado (A2-C-R2)
#
# El validador es de XSD 1.0 y los esquemas declaran `vc:minVersion="1.1"`.
# Hoy encaja, pero eso vale para ESTOS bytes. La garantía frente al futuro no
# es un escáner de construcciones —sería incompleto y daría falsa seguridad—
# sino esta puerta: si el paquete cambia, falla y obliga a revisar.
# ─────────────────────────────────────────────────────────────────────────────

def _digests_reales() -> dict[str, str]:
    """SHA-256 recalculado desde los BYTES, no leído del manifiesto."""
    return {
        e.id: hashlib.sha256((fx.BUNDLE / e.path).read_bytes()).hexdigest()
        for e in fx.entries()
    }


def test_el_paquete_de_esquemas_es_el_aprobado_para_este_validador():
    """La comprobación central, a través de la puerta REAL.

    `verify_approved_schema_bundle` es la misma función que ejercitan las
    pruebas de mutación: membresía física, identidad y bytes. Si el test
    llamara a otra cosa, estaría validando un mecanismo distinto del que
    gobierna el paquete.
    """
    obtenido = policy.verify_approved_schema_bundle(fx.BUNDLE)
    assert obtenido == policy.APPROVED_VALIDATOR_BUNDLE_SHA256


def test_el_descubrimiento_fisico_coincide_con_el_mapeo_aprobado():
    """Todo `*.xsd` bajo la raíz gobernada está explícitamente aprobado.

    La superficie no es «lo que el manifiesto mencione»: es lo que hay en
    disco. Un séptimo esquema sin declarar seguiría estando ahí.
    """
    fisicos = set(policy.descubrir_xsd(fx.BUNDLE))
    assert fisicos == set(policy.APPROVED_SCHEMA_ARTIFACTS.values())
    assert len(fisicos) == 6


def test_el_manifiesto_concuerda_con_el_mapeo_aprobado():
    """Las tres vistas —política, manifiesto y disco— deben coincidir."""
    del_manifiesto = {e["id"]: e["path"] for e in fx.manifest()["schemas"]}
    assert del_manifiesto == policy.APPROVED_SCHEMA_ARTIFACTS
    for ruta in policy.APPROVED_SCHEMA_ARTIFACTS.values():
        assert (fx.BUNDLE / ruta).is_file()


def test_el_paquete_no_contiene_enlaces_simbolicos():
    """Un symlink podría apuntar fuera y burlar la política sin cambiar bytes."""
    assert [p for p in fx.BUNDLE.rglob("*") if p.is_symlink()] == []


def test_el_fingerprint_no_depende_del_orden_de_entrada():
    """Canónico de verdad: mismo conjunto, mismo digest, venga como venga."""
    d = _digests_reales()
    invertido = dict(reversed(list(d.items())))
    assert policy.fingerprint(invertido) == policy.fingerprint(d)


def test_el_fingerprint_no_sale_del_manifiesto():
    """El digest aprobado no puede estar escondido en los metadatos.

    Si el manifiesto lo contuviera, alguien podría regenerarlo junto con los
    esquemas y la puerta se abriría sola.
    """
    crudo = fx.MANIFEST.read_text(encoding="utf-8")
    assert policy.APPROVED_VALIDATOR_BUNDLE_SHA256 not in crudo
    assert "APPROVED_VALIDATOR_BUNDLE" not in crudo


# ── Pruebas de mutación: se ejercita la puerta SIN tocar los ficheros ───────

def test_mutar_un_esquema_de_hacienda_invalida_el_paquete():
    """Caso A — un byte distinto en un XSD de Hacienda y la puerta cierra."""
    digests = _digests_reales()
    mutado = dict(digests)
    mutado["cr.fe.v4_4"] = hashlib.sha256(b"factura manipulada").hexdigest()

    assert policy.fingerprint(mutado) != policy.APPROVED_VALIDATOR_BUNDLE_SHA256
    # Y los ficheros reales siguen intactos: la mutación fue solo en memoria.
    assert _digests_reales() == digests


def test_mutar_el_xmldsig_invalida_el_paquete():
    """Caso B — la dependencia del W3C está igual de protegida.

    Es la que más fácilmente se cambiaría sin pensar, por venir de fuera de
    Hacienda.
    """
    digests = _digests_reales()
    mutado = dict(digests)
    mutado["w3c.xmldsig"] = hashlib.sha256(b"xmldsig manipulado").hexdigest()

    assert policy.fingerprint(mutado) != policy.APPROVED_VALIDATOR_BUNDLE_SHA256
    assert _digests_reales() == digests


def test_anadir_o_quitar_un_artefacto_invalida_el_paquete():
    """Un esquema nuevo tampoco entra en silencio."""
    digests = _digests_reales()

    ampliado = dict(digests)
    ampliado["cr.fec.v4_4"] = hashlib.sha256(b"factura de compra").hexdigest()
    assert policy.fingerprint(ampliado) != policy.APPROVED_VALIDATOR_BUNDLE_SHA256
    assert set(ampliado) != policy.APPROVED_ARTIFACT_IDS

    reducido = {k: v for k, v in digests.items() if k != "cr.nd.v4_4"}
    assert policy.fingerprint(reducido) != policy.APPROVED_VALIDATOR_BUNDLE_SHA256
    assert set(reducido) != policy.APPROVED_ARTIFACT_IDS


def test_un_paquete_que_compila_y_valida_igual_tambien_falla():
    """El punto que justifica la puerta.

    Un esquema futuro podría compilar, no contener ninguna construcción que
    nuestro escáner conozca, y dejar pasar los 24 fixtures actuales — y aun
    así validar menos de lo que creemos. El fingerprint falla igualmente,
    porque la aprobación es de BYTES, no de comportamiento observado.
    """
    digests = _digests_reales()
    # Un cambio cosmético e inocuo basta para cerrar la puerta.
    plausible = dict(digests)
    plausible["cr.mh.v4_4"] = hashlib.sha256(
        (fx.BUNDLE / "esquemas/v4_4/MensajeHacienda_V4.4.xsd").read_bytes()
        + b"\n<!-- revision 2027 -->"
    ).hexdigest()
    assert policy.fingerprint(plausible) != policy.APPROVED_VALIDATOR_BUNDLE_SHA256


def test_la_politica_declara_los_seis_artefactos():
    assert len(policy.APPROVED_ARTIFACT_IDS) == 6
    assert set(_digests_reales()) == policy.APPROVED_ARTIFACT_IDS


def test_el_mensaje_de_fallo_pide_revision_de_compatibilidad():
    """Un fallo tiene que decir qué hacer, no solo que algo cambió."""
    assert "compatibility review required" in policy.MENSAJE_DE_FALLO
    assert "ADR-040" in policy.MENSAJE_DE_FALLO


# ── El escáner sigue existiendo, pero degradado a diagnóstico ───────────────

def test_el_escaner_de_construcciones_1_1_es_solo_diagnostico():
    """Se documenta su límite en el propio test, para que nadie lo confunda
    con la garantía.

    La lista es de construcciones **conocidas**. No cubre todas las
    diferencias entre XSD 1.0 y 1.1, y ampliarla no la haría exhaustiva. La
    seguridad frente a un paquete futuro la da el fingerprint, no esto.
    """
    conocidas = {
        "xs:assert", "xs:assertion", "xs:alternative", "xs:openContent",
        "xs:defaultOpenContent", "xs:override", "xs:error", "explicitTimezone",
        "notQName", "notNamespace", "defaultAttributes", "inheritable",
        "xpathDefaultNamespace",
    }
    for entry in fx.entries():
        texto = (fx.BUNDLE / entry.path).read_text(encoding="utf-8", errors="replace")
        for c in conocidas:
            assert c not in texto, f"{entry.id} usa {c}, exclusiva de XSD 1.1"


# ─────────────────────────────────────────────────────────────────────────────
# Mutación sobre un paquete TEMPORAL, con la puerta real (A2-C-R3)
#
# Nada de diccionarios en memoria: se copia el paquete a un directorio
# temporal, se muta el sistema de ficheros y se ejecuta exactamente
# `verify_approved_schema_bundle` sobre esa copia. Los ficheros del
# repositorio no se tocan en ningún momento.
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def paquete_temporal(tmp_path):
    """Copia fiel del paquete gobernado, sobre la que sí se puede mutar."""
    destino = tmp_path / "cr"
    shutil.copytree(fx.BUNDLE, destino, symlinks=False)
    # La copia, sin tocar, debe pasar la puerta: si no, la prueba no valdría.
    assert policy.verify_approved_schema_bundle(destino) == (
        policy.APPROVED_VALIDATOR_BUNDLE_SHA256
    )
    return destino


def _huellas_del_repositorio() -> dict[str, str]:
    return {
        aid: hashlib.sha256((fx.BUNDLE / ruta).read_bytes()).hexdigest()
        for aid, ruta in policy.APPROVED_SCHEMA_ARTIFACTS.items()
    }


def test_mutacion_anadir_un_septimo_xsd(paquete_temporal):
    """Caso A — un `.xsd` de más, aunque nadie lo referencie."""
    antes = _huellas_del_repositorio()
    (paquete_temporal / "esquemas" / "v4_4" / "unexpected.xsd").write_bytes(
        b'<?xml version="1.0"?><xs:schema xmlns:xs='
        b'"http://www.w3.org/2001/XMLSchema"/>'
    )
    with pytest.raises(policy.BundleRechazado) as exc:
        policy.verify_approved_schema_bundle(paquete_temporal)
    assert "sobran" in str(exc.value)
    assert "unexpected.xsd" in str(exc.value)
    assert _huellas_del_repositorio() == antes, "Se tocó el repositorio"


def test_mutacion_eliminar_un_xsd_aprobado(paquete_temporal):
    """Caso B — falta uno de los seis."""
    (paquete_temporal / "esquemas" / "v4_4" / "NotaDebitoElectronica_V4.4.xsd").unlink()
    with pytest.raises(policy.BundleRechazado) as exc:
        policy.verify_approved_schema_bundle(paquete_temporal)
    assert "faltan" in str(exc.value)


def test_mutacion_renombrar_conservando_los_bytes(paquete_temporal):
    """Caso C — el hallazgo que R3 cierra.

    Mismos bytes, mismo `artifact_id`, **otro nombre**. Antes de R3 esto
    sobrevivía porque el fingerprint solo miraba id + contenido.
    """
    v4 = paquete_temporal / "esquemas" / "v4_4"
    origen = v4 / "FacturaElectronica_V4.4.xsd"
    bytes_originales = origen.read_bytes()
    origen.rename(v4 / "FacturaElectronica_V4.4_renombrada.xsd")

    # Los bytes se conservan intactos: lo único que cambió es la ruta.
    assert (v4 / "FacturaElectronica_V4.4_renombrada.xsd").read_bytes() == bytes_originales

    with pytest.raises(policy.BundleRechazado) as exc:
        policy.verify_approved_schema_bundle(paquete_temporal)
    assert "renombrada" in str(exc.value)


def test_mutacion_mover_a_otra_carpeta(paquete_temporal):
    """Caso D — misma identidad y bytes, otra ubicación.

    Distinto del renombrado: aquí el nombre se conserva. Importa porque la
    ubicación determina cómo resuelve `../../xmldsig-core-schema.xsd`.
    """
    v4 = paquete_temporal / "esquemas" / "v4_4"
    otra = paquete_temporal / "esquemas" / "otra_carpeta"
    otra.mkdir()
    shutil.move(str(v4 / "TiqueteElectronico_V4.4.xsd"),
                str(otra / "TiqueteElectronico_V4.4.xsd"))
    with pytest.raises(policy.BundleRechazado) as exc:
        policy.verify_approved_schema_bundle(paquete_temporal)
    assert "otra_carpeta" in str(exc.value)


def test_mutacion_cambiar_bytes_conservando_la_ruta(paquete_temporal):
    """Caso E — la ruta encaja, los bytes no."""
    objetivo = paquete_temporal / "esquemas" / "v4_4" / "NotaCreditoElectronica_V4.4.xsd"
    objetivo.write_bytes(objetivo.read_bytes() + b"\n<!-- revision futura -->")
    with pytest.raises(policy.BundleRechazado) as exc:
        policy.verify_approved_schema_bundle(paquete_temporal)
    assert policy.APPROVED_VALIDATOR_BUNDLE_SHA256 in str(exc.value)


def test_mutacion_cambiar_bytes_del_xmldsig(paquete_temporal):
    """Caso F — la dependencia del W3C, igual de protegida."""
    objetivo = paquete_temporal / "xmldsig-core-schema.xsd"
    objetivo.write_bytes(objetivo.read_bytes() + b"\n<!-- otra edicion -->")
    with pytest.raises(policy.BundleRechazado):
        policy.verify_approved_schema_bundle(paquete_temporal)


def test_renombrar_y_actualizar_el_manifiesto_tampoco_pasa(paquete_temporal):
    """El escenario decisivo: manifiesto coherente, y aun así FALLA.

    Se renombra un esquema, se actualiza el manifiesto temporal para que
    apunte a la ruta nueva con el mismo `artifact_id`, y se conservan los
    bytes exactos. El paquete queda internamente consistente — pero la
    política aprobada, que vive **fuera** del manifiesto, no lo autoriza.

    Es exactamente la vía de escape que R3 cierra.
    """
    v4 = paquete_temporal / "esquemas" / "v4_4"
    nueva_ruta = "esquemas/v4_4/MensajeHacienda_V4.4_renombrado.xsd"
    (v4 / "MensajeHacienda_V4.4.xsd").rename(paquete_temporal / nueva_ruta)

    manifiesto_path = paquete_temporal / "MANIFEST.json"
    doc = json.loads(manifiesto_path.read_text(encoding="utf-8"))
    for e in doc["schemas"]:
        if e["id"] == "cr.mh.v4_4":
            e["path"] = nueva_ruta
    manifiesto_path.write_text(json.dumps(doc, indent=2), encoding="utf-8")

    with pytest.raises(policy.BundleRechazado) as exc:
        policy.verify_approved_schema_bundle(paquete_temporal)
    # Falla ya en la membresía física, antes incluso de mirar el manifiesto.
    assert "conjunto físico" in str(exc.value)


def test_anadir_un_artefacto_y_declararlo_en_el_manifiesto_tampoco_pasa(
    paquete_temporal,
):
    """Un manifiesto perfectamente coherente no autoriza un artefacto nuevo."""
    nueva = "esquemas/v4_4/FacturaElectronicaCompra_V4.4.xsd"
    contenido = (
        b'<?xml version="1.0"?><xs:schema xmlns:xs='
        b'"http://www.w3.org/2001/XMLSchema"/>'
    )
    (paquete_temporal / nueva).write_bytes(contenido)

    manifiesto_path = paquete_temporal / "MANIFEST.json"
    doc = json.loads(manifiesto_path.read_text(encoding="utf-8"))
    doc["schemas"].append({
        "id": "cr.fec.v4_4", "root": "FacturaElectronicaCompra",
        "path": nueva, "namespace": "urn:ejemplo", "version": "4.4",
        "bytes": len(contenido),
        "sha256": hashlib.sha256(contenido).hexdigest(),
        "dependencies": [],
    })
    manifiesto_path.write_text(json.dumps(doc, indent=2), encoding="utf-8")

    with pytest.raises(policy.BundleRechazado) as exc:
        policy.verify_approved_schema_bundle(paquete_temporal)
    assert "sobran" in str(exc.value)


# ─────────────────────────────────────────────────────────────────────────────
# Política de enlaces simbólicos (A2-C-R4)
#
# Ningún symlink dentro del paquete gobernado, apunte donde apunte. La
# política no distingue interno de externo: la sola presencia de un enlace es
# motivo de rechazo.
#
# El fallo que motivó R4: `rglob("*.xsd")` no ve un directorio enlazado cuyo
# nombre no acabe en `.xsd`, ni desciende por él. Un `linked_dir -> /fuera/`
# con un esquema dentro quedaba invisible y el paquete pasaba la puerta.
# ─────────────────────────────────────────────────────────────────────────────

def test_symlink_de_directorio_a_un_arbol_externo(paquete_temporal, tmp_path):
    """El caso exacto que destapó Codex.

    Un directorio enlazado a un árbol externo que contiene un `.xsd` oculto.
    Antes de R4 la puerta devolvía el fingerprint aprobado: el enlace no
    terminaba en `.xsd`, así que `rglob` ni lo veía ni bajaba por él.
    """
    externo = tmp_path / "arbol_externo"
    externo.mkdir()
    (externo / "hidden.xsd").write_bytes(b'<?xml version="1.0"?><x/>')
    (paquete_temporal / "linked_dir").symlink_to(externo, target_is_directory=True)

    with pytest.raises(policy.BundleRechazado) as exc:
        policy.verify_approved_schema_bundle(paquete_temporal)

    mensaje = str(exc.value)
    assert "simbólico" in mensaje
    assert "linked_dir" in mensaje, "El fallo debe identificar el enlace"
    # Falla POR el symlink, no porque descubriera el esquema oculto después.
    assert "hidden.xsd" not in mensaje


def test_symlink_de_directorio_a_un_directorio_interno(paquete_temporal):
    """La política no depende del destino: también se rechaza hacia dentro."""
    (paquete_temporal / "atajo").symlink_to(
        paquete_temporal / "esquemas", target_is_directory=True
    )
    with pytest.raises(policy.BundleRechazado) as exc:
        policy.verify_approved_schema_bundle(paquete_temporal)
    assert "atajo" in str(exc.value)


def test_symlink_de_fichero_aunque_apunte_dentro_del_paquete(paquete_temporal):
    """Un enlace a un XSD aprobado del propio paquete tampoco vale."""
    destino = paquete_temporal / "esquemas" / "v4_4" / "FacturaElectronica_V4.4.xsd"
    (paquete_temporal / "esquemas" / "v4_4" / "enlace.xsd").symlink_to(destino)
    with pytest.raises(policy.BundleRechazado) as exc:
        policy.verify_approved_schema_bundle(paquete_temporal)
    assert "enlace.xsd" in str(exc.value)


def test_symlink_de_fichero_a_algo_externo(paquete_temporal, tmp_path):
    externo = tmp_path / "externo.xsd"
    externo.write_bytes(b'<?xml version="1.0"?><x/>')
    (paquete_temporal / "esquemas" / "v4_4" / "enlace.xsd").symlink_to(externo)
    with pytest.raises(policy.BundleRechazado) as exc:
        policy.verify_approved_schema_bundle(paquete_temporal)
    assert "simbólico" in str(exc.value)


def test_el_manifiesto_no_puede_ser_un_symlink(paquete_temporal, tmp_path):
    """Aunque apunte a un manifiesto de contenido idéntico."""
    real = tmp_path / "MANIFEST_real.json"
    manifiesto = paquete_temporal / "MANIFEST.json"
    shutil.copy2(manifiesto, real)
    manifiesto.unlink()
    manifiesto.symlink_to(real)

    with pytest.raises(policy.BundleRechazado) as exc:
        policy.verify_approved_schema_bundle(paquete_temporal)
    assert "simbólico" in str(exc.value)


def test_la_raiz_del_paquete_no_puede_ser_un_symlink(paquete_temporal, tmp_path):
    """Un enlace no se resuelve primero y se acepta después como raíz normal."""
    enlace_raiz = tmp_path / "bundle_link"
    enlace_raiz.symlink_to(paquete_temporal, target_is_directory=True)

    # El paquete real sigue pasando…
    assert policy.verify_approved_schema_bundle(paquete_temporal) == (
        policy.APPROVED_VALIDATOR_BUNDLE_SHA256
    )
    # …y el enlace a él, no.
    with pytest.raises(policy.BundleRechazado) as exc:
        policy.verify_approved_schema_bundle(enlace_raiz)
    assert "must not be a symlink" in str(exc.value)


def test_el_paquete_temporal_sin_enlaces_sigue_pasando(paquete_temporal):
    """Guarda contra falsos positivos: sin mutar, la copia pasa.

    Si esto fallara, las pruebas de arriba no probarían la política sino un
    problema de preparación.
    """
    assert policy.verify_approved_schema_bundle(paquete_temporal) == (
        policy.APPROVED_VALIDATOR_BUNDLE_SHA256
    )


def test_el_recorrido_no_sigue_los_enlaces_de_directorio(paquete_temporal, tmp_path):
    """Se comprueba el mecanismo, no solo el resultado.

    Un bucle de enlaces terminaría en recursión infinita si el recorrido los
    siguiera. Que falle limpiamente demuestra que no desciende.
    """
    (paquete_temporal / "bucle").symlink_to(
        paquete_temporal, target_is_directory=True
    )
    with pytest.raises(policy.BundleRechazado) as exc:
        policy.rechazar_symlinks(paquete_temporal)
    assert "bucle" in str(exc.value)
