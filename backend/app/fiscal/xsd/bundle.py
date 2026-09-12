"""Carga y compilación de los esquemas oficiales v4.4 — código de producción.

Resuelve tres cosas:

1. localizar el paquete de esquemas versionado en el repositorio;
2. elegir el esquema correcto a partir de `(raíz, namespace)` del XML;
3. compilar **sin red, sin DTD y sin entidades externas**.

**No se usa directamente desde el parser.** La vía de producción es
`app.fiscal.xsd.registry.get_verified_schema_registry()`, que primero somete
el paquete a la puerta *fail-closed* de `policy` y solo entonces compila. Usar
`compilar()` por su cuenta saltaría esa verificación.

El mapeo a nuestro vocabulario interno y la extracción de campos viven en
`app.fiscal.parser`.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from lxml import etree

# El paquete vive en `backend/resources/`: son recursos de dominio, no material
# de prueba. Este módulo es el ÚNICO validador del proyecto — los tests
# consumen esta misma implementación, para que no puedan divergir.
BUNDLE = (
    Path(__file__).resolve().parents[3]
    / "resources" / "fiscal" / "xsd" / "cr"
)
MANIFEST = BUNDLE / "MANIFEST.json"


class ResolucionRechazada(Exception):
    """Un recurso quedó fuera de la política: no se resuelve, se rechaza."""


class PoliticaDeRecursos(etree.Resolver):
    """Solo se resuelve lo que vive dentro del paquete versionado.

    `no_network=True` ya corta la red, pero se apoya en libxml2 y no deja
    rastro de lo que se intentó. Este resolutor actúa **por encima**: registra
    cada intento y rechaza explícitamente todo lo que no sea un fichero del
    paquete —URLs `http`/`https`/`ftp`, y también rutas locales fuera de él—.

    Se guardan los intentos para poder afirmar, con evidencia, que durante una
    ejecución no se pidió ningún recurso remoto.
    """

    def __init__(self) -> None:
        super().__init__()
        self.permitidos: list[str] = []
        self.rechazados: list[str] = []

    def resolve(self, system_url, public_id, context):  # noqa: D102
        url = system_url or ""
        esquema_url = url.split(":", 1)[0].lower() if ":" in url else ""
        if esquema_url in ("http", "https", "ftp", "ftps"):
            self.rechazados.append(url)
            raise ResolucionRechazada(f"Recurso remoto rechazado: {url}")

        ruta = Path(url[7:] if url.startswith("file://") else url)
        try:
            destino = (ruta if ruta.is_absolute() else Path.cwd() / ruta).resolve()
        except OSError:
            self.rechazados.append(url)
            raise ResolucionRechazada(f"Ruta irresoluble: {url}")

        raiz = BUNDLE.resolve()
        if destino != raiz and raiz not in destino.parents:
            self.rechazados.append(url)
            raise ResolucionRechazada(f"Ruta fuera del paquete: {destino}")

        self.permitidos.append(str(destino))
        return self.resolve_filename(str(destino), context)


def _parser(politica: "PoliticaDeRecursos | None" = None) -> etree.XMLParser:
    """Parser endurecido, idéntico para esquemas y para documentos.

    `no_network` corta cualquier resolución remota; `load_dtd` y
    `resolve_entities` desactivados impiden la expansión de entidades y la
    carga de DTD externa. El `xmldsig-core-schema.xsd` del W3C declara un
    subconjunto DTD interno, pero sus entidades no se usan en el cuerpo, así
    que el esquema compila igualmente.

    Con `politica`, además, toda resolución pasa por `PoliticaDeRecursos`.
    """
    p = etree.XMLParser(
        no_network=True,
        resolve_entities=False,
        load_dtd=False,
        dtd_validation=False,
        huge_tree=False,
    )
    if politica is not None:
        p.resolvers.add(politica)
    return p


@dataclass(frozen=True)
class SchemaEntry:
    id: str
    root: str | None
    namespace: str
    #: Versión estructural declarada en el manifiesto —«4.4»—. La consume la
    #: ingesta para registrar `detected_schema_version` sin deducirla del
    #: identificador ni del namespace.
    version: str
    path: str
    sha256: str
    bytes: int
    dependencies: tuple[str, ...]


@lru_cache(maxsize=1)
def manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def entries() -> tuple[SchemaEntry, ...]:
    return tuple(
        SchemaEntry(
            id=e["id"], root=e.get("root"), namespace=e["namespace"],
            version=e["version"],
            path=e["path"], sha256=e["sha256"], bytes=e["bytes"],
            dependencies=tuple(e.get("dependencies", ())),
        )
        for e in manifest()["schemas"]
    )


@lru_cache(maxsize=1)
def _por_clave() -> dict[tuple[str, str], SchemaEntry]:
    """`(raíz, namespace)` → esquema. Determinista y sin ambigüedad."""
    tabla: dict[tuple[str, str], SchemaEntry] = {}
    for e in entries():
        if e.root is None:      # dependencia, no documento raíz
            continue
        clave = (e.root, e.namespace)
        if clave in tabla:
            raise AssertionError(f"El manifiesto asocia {clave} a dos esquemas")
        tabla[clave] = e
    return tabla


def sha256_de(entry: SchemaEntry) -> str:
    return hashlib.sha256((BUNDLE / entry.path).read_bytes()).hexdigest()


def raiz_de(data: bytes, politica: "PoliticaDeRecursos | None" = None) -> tuple[str, str]:
    """Devuelve `(local-name, namespace)` de la raíz del documento."""
    root = etree.fromstring(data, parser=_parser(politica))
    tag = root.tag
    local = tag.split("}")[-1] if "}" in tag else tag
    ns = tag[1:].split("}")[0] if tag.startswith("{") else ""
    return local, ns


def esquema_para(local: str, ns: str) -> SchemaEntry | None:
    return _por_clave().get((local, ns))


def limpiar_cache() -> None:
    """Vacía todo estado compilado. Imprescindible para probar que una
    ejecución *desde cero* no necesita la red."""
    compilar.cache_clear()
    manifest.cache_clear()
    entries.cache_clear()
    _por_clave.cache_clear()


@lru_cache(maxsize=8)
def compilar(schema_id: str, politica: "PoliticaDeRecursos | None" = None) -> etree.XMLSchema:
    """Compila un esquema resolviendo sus imports dentro del paquete.

    Los ficheros oficiales importan `../../xmldsig-core-schema.xsd`. La
    disposición del paquete reproduce esa profundidad, así que el import
    resuelve localmente sin tocar los ficheros ni instalar un resolutor a
    medida.

    **Sin `os.chdir`.** El directorio de trabajo es estado global del proceso:
    cambiarlo aunque sea un instante corrompe cualquier otro hilo que esté
    resolviendo rutas, y un servidor concurrente los tiene. Se pasa la **ruta
    absoluta** a `etree.parse`, con lo que libxml2 fija la URI base del
    documento y resuelve los imports relativos contra ella.
    """
    entrada = next(e for e in entries() if e.id == schema_id)
    destino = (BUNDLE / entrada.path).resolve()
    doc = etree.parse(str(destino), parser=_parser(politica))
    return etree.XMLSchema(doc)


def validar(data: bytes, politica: "PoliticaDeRecursos | None" = None) -> tuple[bool, str | None, SchemaEntry | None]:
    """Valida los BYTES de un documento contra su esquema oficial.

    Devuelve `(válido, primer_error, esquema)`. Si no hay esquema para esa
    raíz, devuelve `(False, motivo, None)` en lugar de adivinar uno.
    """
    local, ns = raiz_de(data, politica)
    entrada = esquema_para(local, ns)
    if entrada is None:
        return False, f"Sin esquema para ({local}, {ns})", None
    schema = compilar(entrada.id, politica)
    doc = etree.fromstring(data, parser=_parser(politica))
    if schema.validate(doc.getroottree()):
        return True, None, entrada
    return False, str(schema.error_log[0]), entrada
