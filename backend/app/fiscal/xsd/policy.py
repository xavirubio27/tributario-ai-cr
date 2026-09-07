"""Política de compatibilidad del validador con el paquete de esquemas.

Código de PRODUCCIÓN: el parser depende de esta puerta, no solo los tests.

╔══════════════════════════════════════════════════════════════════════════╗
║  MODIFICAR `APPROVED_VALIDATOR_BUNDLE_SHA256` SIGNIFICA:                 ║
║                                                                          ║
║      «Apruebo un paquete de esquemas XSD NUEVO para este validador.»     ║
║                                                                          ║
║  No es un valor que se actualice para que los tests vuelvan a pasar.     ║
╚══════════════════════════════════════════════════════════════════════════╝

## Por qué existe

El validador —`lxml` sobre libxml2— implementa **XSD 1.0**, mientras que los
cinco esquemas de Hacienda declaran `vc:minVersion="1.1"`. Hoy eso no es un
problema: se comprobó que el paquete no usa ninguna construcción exclusiva de
1.1, así que libxml2 lo cubre por completo.

Pero esa comprobación vale **para estos bytes concretos**, no para siempre. Un
esquema futuro podría introducir una construcción de 1.1 que libxml2 ignore
**en silencio**: compilaría, los fixtures actuales seguirían pasando, y
estaríamos validando menos de lo que creemos sin enterarnos.

Un escáner de construcciones conocidas no resuelve eso: sería incompleto por
definición y daría una falsa sensación de seguridad. La garantía real es otra,
y es deliberadamente tosca:

    CAMBIA UN BYTE DEL PAQUETE  →  FALLA  →  REVISIÓN HUMANA

## Qué obliga a revisar un cambio de paquete

- la versión de XSD que declara el esquema nuevo;
- si introduce construcciones que libxml2 no aplique;
- si `lxml`/libxml2 sigue siendo el validador adecuado;
- el grafo de dependencias, por si cambia o crece;
- los fixtures reales, por si dejan de ser representativos;
- la documentación y el `MANIFEST.json`.

Solo después de eso procede sustituir el digest de abajo.

## Algoritmo del fingerprint

Determinista y ajeno al sistema de ficheros. **No** depende de `mtime`, del
orden que devuelva el sistema, de rutas absolutas ni del orden del manifiesto:

1. SHA-256 de los bytes de cada artefacto;
2. entradas ordenadas por `artifact id` (orden lexicográfico);
3. se concatena `f"{artifact_id}:{sha256}\\n"` para cada una;
4. SHA-256 de esa secuencia, codificada en UTF-8.
"""

from __future__ import annotations

import hashlib
import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Mapping

# ─────────────────────────────────────────────────────────────────────────────
# El paquete aprobado. Revisado en A2-C y endurecido en A2-C-R1.
#
# Artefactos cubiertos (6):
#   cr.fe.v4_4    FacturaElectronica_V4.4.xsd        Hacienda / ATV
#   cr.te.v4_4    TiqueteElectronico_V4.4.xsd        Hacienda / ATV
#   cr.nc.v4_4    NotaCreditoElectronica_V4.4.xsd    Hacienda / ATV
#   cr.nd.v4_4    NotaDebitoElectronica_V4.4.xsd     Hacienda / ATV
#   cr.mh.v4_4    MensajeHacienda_V4.4.xsd           Hacienda / ATV
#   w3c.xmldsig   xmldsig-core-schema.xsd            W3C
# ─────────────────────────────────────────────────────────────────────────────
APPROVED_VALIDATOR_BUNDLE_SHA256 = (
    "c26196c3544eb69af7e6d6e102b2cca5414107ef43bbfea1ef6e89a89937ef58"
)

APPROVED_ARTIFACT_IDS = frozenset({
    "cr.fe.v4_4", "cr.te.v4_4", "cr.nc.v4_4",
    "cr.nd.v4_4", "cr.mh.v4_4", "w3c.xmldsig",
})

# ─────────────────────────────────────────────────────────────────────────────
# MEMBRESÍA FÍSICA EXACTA
#
# Modificar este mapeo significa: «apruebo un paquete de esquemas FÍSICAMENTE
# distinto» —otro conjunto, otra identidad o otra ubicación—.
#
# Rutas relativas a la raíz gobernada, en formato POSIX. La ruta forma parte de
# la aprobación: un fichero con los mismos bytes y el mismo id, pero movido o
# renombrado, **no** está aprobado. Cambiar dónde vive un esquema cambia cómo
# resuelven los imports relativos, y eso es exactamente lo que hay que revisar.
#
# El mapeo es POLÍTICA, no descubrimiento: no se deriva del `MANIFEST.json`.
# Si saliera de ahí, editar el manifiesto autorizaría el cambio por sí solo.
# ─────────────────────────────────────────────────────────────────────────────
APPROVED_SCHEMA_ARTIFACTS = {
    "cr.fe.v4_4":  "esquemas/v4_4/FacturaElectronica_V4.4.xsd",
    "cr.mh.v4_4":  "esquemas/v4_4/MensajeHacienda_V4.4.xsd",
    "cr.nc.v4_4":  "esquemas/v4_4/NotaCreditoElectronica_V4.4.xsd",
    "cr.nd.v4_4":  "esquemas/v4_4/NotaDebitoElectronica_V4.4.xsd",
    "cr.te.v4_4":  "esquemas/v4_4/TiqueteElectronico_V4.4.xsd",
    "w3c.xmldsig": "xmldsig-core-schema.xsd",
}

# La superficie gobernada es TODO `*.xsd` bajo la raíz del paquete, no solo lo
# que el manifiesto mencione. Un séptimo esquema sin declarar es un cambio de
# paquete, aunque nadie lo referencie: sigue estando ahí, y un import futuro
# podría alcanzarlo.
GOVERNED_SUFFIX = ".xsd"

MENSAJE_DE_FALLO = (
    "Schema bundle changed; validator compatibility review required.\n"
    "El paquete de esquemas ya no es el aprobado para este validador.\n"
    "Antes de tocar APPROVED_VALIDATOR_BUNDLE_SHA256, revisa la versión de XSD\n"
    "declarada, las construcciones nuevas, la idoneidad de lxml/libxml2, el\n"
    "grafo de dependencias, los fixtures y la documentacion. Ver ADR-040."
)


class BundleRechazado(AssertionError):
    """La puerta se cerró: el paquete no es el aprobado."""


# ─────────────────────────────────────────────────────────────────────────────
# NORMALIZACIÓN DE FALLOS ESPERADOS
#
# Un paquete mal desplegado —ilegible, con otra codificación, con el JSON roto
# o con un manifiesto de otra forma— es un estado de CONFIGURACIÓN esperado,
# no un defecto de programación. Debe salir por la misma puerta que el resto
# de rechazos: `BundleRechazado`.
#
# **Deliberadamente NO se captura `Exception`.** Un `AttributeError`, un
# `NameError` o un fallo de lógica nuestro siguen siendo bugs y tienen que
# poder verse como tales: etiquetarlos «paquete inválido» los escondería
# detrás de un diagnóstico falso y mandaría a revisar el despliegue en lugar
# del código.
#
# Cada categoría envuelve **una sola operación**, de modo que las clases
# capturadas solo puedan provenir del estado no confiable que esa operación
# toca. Ese acotamiento es lo que separa «manifiesto malformado» de «bug».
# ─────────────────────────────────────────────────────────────────────────────

#: Acceso al sistema de ficheros: no se puede abrir, leer o recorrer.
FALLOS_DE_LECTURA: tuple[type[BaseException], ...] = (OSError,)

#: Los bytes del manifiesto no son UTF-8. `UnicodeDecodeError` hereda de aquí.
FALLOS_DE_DECODIFICACION: tuple[type[BaseException], ...] = (UnicodeError,)

#: El manifiesto no es JSON. `JSONDecodeError` hereda de `ValueError`.
FALLOS_DE_SINTAXIS: tuple[type[BaseException], ...] = (json.JSONDecodeError,)

#: JSON válido, pero sin la forma acordada: falta una clave, o un campo no es
#: del tipo que el manifiesto declara. `KeyError` y `TypeError` se capturan
#: SOLO alrededor del acceso al documento no confiable, nunca en general.
FALLOS_DE_ESTRUCTURA: tuple[type[BaseException], ...] = (KeyError, TypeError)

#: Rutas del paquete inconsistentes entre sí —una entrada que, ya resuelta,
#: cae fuera de la raíz gobernada— además del acceso al disco.
FALLOS_DE_RUTA: tuple[type[BaseException], ...] = (OSError, ValueError)

#: Todo lo que puede fallar al leer y consumir el manifiesto.
FALLOS_DEL_MANIFIESTO: tuple[type[BaseException], ...] = (
    FALLOS_DE_LECTURA + FALLOS_DE_DECODIFICACION
    + FALLOS_DE_SINTAXIS + FALLOS_DE_ESTRUCTURA
)

# Motivos canónicos. Son texto FIJO: ni rutas absolutas, ni contenido del
# manifiesto, ni el mensaje de la excepción original. La causa concreta queda
# encadenada en `__cause__` para quien depure el servidor.
RAZON_ARBOL_ILEGIBLE = "No se pudo inspeccionar el árbol del paquete gobernado."
RAZON_MANIFIESTO_ILEGIBLE = "No se pudo leer MANIFEST.json."
RAZON_MANIFIESTO_NO_UTF8 = "MANIFEST.json no está codificado en UTF-8."
RAZON_MANIFIESTO_NO_JSON = "MANIFEST.json no es JSON válido."
RAZON_MANIFIESTO_INCOMPLETO = "MANIFEST.json no tiene la estructura acordada."
RAZON_ESQUEMA_ILEGIBLE = "No se pudo leer un esquema del paquete gobernado."


@contextmanager
def rechazar_si_falla(
    razon: str, clases: tuple[type[BaseException], ...]
) -> Iterator[None]:
    """Convierte fallos ESPERADOS del paquete en `BundleRechazado`.

    `razon` es un motivo canónico de los de arriba: texto fijo y seguro. La
    excepción original se encadena con `from`, así que sigue disponible en
    `__cause__` sin viajar en el texto.

    `BundleRechazado` hereda de `AssertionError` y por tanto **no** está en
    ninguna de las tuplas de arriba: un rechazo que ya venía formado atraviesa
    este gestor intacto y no se vuelve a envolver.
    """
    try:
        yield
    except clases as exc:
        raise BundleRechazado(f"{razon}\n{MENSAJE_DE_FALLO}") from exc


def rechazar_symlinks(schema_root: Path) -> None:
    """Recorre el árbol COMPLETO y rechaza cualquier enlace simbólico.

    **Por qué el árbol entero y no solo los `*.xsd`.** Un `rglob("*.xsd")` no
    ve un directorio enlazado cuyo nombre no acabe en `.xsd`, y tampoco
    desciende por él: `linked_dir -> /fuera/` quedaba invisible y el paquete
    pasaba la puerta con un esquema oculto dentro. Por eso se inspecciona toda
    entrada visible, sea cual sea su extensión o su tipo.

    Se usa `os.walk(followlinks=False)` y se miran **explícitamente** los
    nombres de directorio antes de descender: no basta con que `os.walk` decida
    no seguirlos, la puerta tiene que *ver* el enlace para poder rechazarlo.

    La política es deliberadamente simple: **ningún symlink**, apunte donde
    apunte. No se distingue interno de externo.
    """
    with rechazar_si_falla(RAZON_ARBOL_ILEGIBLE, FALLOS_DE_LECTURA):
        _rechazar_symlinks(Path(schema_root))


def _rechazar_symlinks(raiz: Path) -> None:
    """El recorrido en sí. Separado para que el gestor de arriba acote qué
    operaciones pueden fallar por disco sin envolver nada más."""
    if raiz.is_symlink():
        raise BundleRechazado(
            f"governed schema root must not be a symlink: {raiz}\n"
            f"{MENSAJE_DE_FALLO}"
        )

    for dirpath, dirnames, filenames in os.walk(raiz, followlinks=False):
        actual = Path(dirpath)
        for nombre in sorted(dirnames) + sorted(filenames):
            entrada = actual / nombre
            if entrada.is_symlink():
                raise BundleRechazado(
                    f"Enlace simbólico prohibido en el paquete: "
                    f"{entrada.relative_to(raiz)} -> {os.readlink(entrada)}\n"
                    f"{MENSAJE_DE_FALLO}"
                )


def descubrir_xsd(schema_root: Path) -> dict[str, Path]:
    """Descubre **físicamente** todo `*.xsd` bajo la raíz gobernada.

    Devuelve `{ruta_relativa_posix: ruta_absoluta}`. No consulta el manifiesto:
    lo que existe en disco es lo que existe, lo declare alguien o no.

    Presupone que `rechazar_symlinks` ya se ejecutó: aquí no quedan enlaces.
    """
    # `BundleRechazado` hereda de `AssertionError`: los rechazos de política
    # que se levantan aquí dentro atraviesan el gestor sin re-envolverse.
    with rechazar_si_falla(RAZON_ARBOL_ILEGIBLE, FALLOS_DE_RUTA):
        raiz = schema_root.resolve()
        encontrados: dict[str, Path] = {}
        for ruta in sorted(raiz.rglob(f"*{GOVERNED_SUFFIX}")):
            if not ruta.is_file():
                raise BundleRechazado(
                    f"Un esquema no es un fichero regular: {ruta}\n{MENSAJE_DE_FALLO}"
                )
            real = ruta.resolve()
            encontrados[real.relative_to(raiz).as_posix()] = real
    return encontrados


def verify_approved_schema_bundle(schema_root: Path) -> str:
    """Puerta única y real. Devuelve el fingerprint si todo encaja.

    Comprueba, en este orden y **antes** de mirar bytes:

    1. **membresía física exacta** — el conjunto de `*.xsd` en disco coincide
       con el aprobado; ni sobra ni falta ni está renombrado o movido;
    2. **identidad** — el manifiesto asocia cada `artifact_id` a la misma ruta
       que la política, de modo que editarlo no autoriza un renombrado;
    3. **bytes** — el fingerprint canónico coincide con el aprobado.

    Opera sobre una raíz *cualquiera*, para que las pruebas de mutación
    ejerciten exactamente este mismo mecanismo sobre una copia temporal.
    """
    # 0 · Ningún enlace simbólico, empezando por la propia raíz. Se comprueba
    #     ANTES de resolver nada: resolver primero y aceptar después sería
    #     tratar un enlace como si fuera una raíz normal.
    rechazar_symlinks(Path(schema_root))

    raiz = Path(schema_root).resolve()

    # 1 · Membresía física exacta.
    fisicos = descubrir_xsd(raiz)
    aprobadas = set(APPROVED_SCHEMA_ARTIFACTS.values())
    presentes = set(fisicos)
    if presentes != aprobadas:
        sobran = sorted(presentes - aprobadas)
        faltan = sorted(aprobadas - presentes)
        raise BundleRechazado(
            "El conjunto físico de esquemas no es el aprobado.\n"
            + (f"  sobran : {sobran}\n" if sobran else "")
            + (f"  faltan : {faltan}\n" if faltan else "")
            + MENSAJE_DE_FALLO
        )

    # 2 · Identidad: el manifiesto no puede remapear id -> ruta.
    ruta_manifiesto = raiz / "MANIFEST.json"
    if ruta_manifiesto.is_symlink():
        raise BundleRechazado(
            f"MANIFEST.json no puede ser un enlace simbólico\n{MENSAJE_DE_FALLO}"
        )
    if not ruta_manifiesto.is_file():
        raise BundleRechazado(
            f"Falta MANIFEST.json o no es un fichero regular\n{MENSAJE_DE_FALLO}"
        )
    # Leer, decodificar, parsear y consumir son cuatro fallos DISTINTOS sobre
    # un fichero no confiable. Se separan para que cada uno capture exactamente
    # sus clases y ninguna de más: `read_text` mezclaría OSError y
    # UnicodeDecodeError en una sola operación.
    with rechazar_si_falla(RAZON_MANIFIESTO_ILEGIBLE, FALLOS_DE_LECTURA):
        crudo = ruta_manifiesto.read_bytes()
    with rechazar_si_falla(RAZON_MANIFIESTO_NO_UTF8, FALLOS_DE_DECODIFICACION):
        texto = crudo.decode("utf-8")
    with rechazar_si_falla(RAZON_MANIFIESTO_NO_JSON, FALLOS_DE_SINTAXIS):
        manifiesto = json.loads(texto)
    with rechazar_si_falla(RAZON_MANIFIESTO_INCOMPLETO, FALLOS_DE_ESTRUCTURA):
        del_manifiesto = {e["id"]: e["path"] for e in manifiesto["schemas"]}
    if del_manifiesto != APPROVED_SCHEMA_ARTIFACTS:
        raise BundleRechazado(
            "El manifiesto y la política aprobada discrepan en artifact_id -> ruta.\n"
            f"  política   : {APPROVED_SCHEMA_ARTIFACTS}\n"
            f"  manifiesto : {del_manifiesto}\n" + MENSAJE_DE_FALLO
        )

    # 3 · Bytes.
    with rechazar_si_falla(RAZON_ESQUEMA_ILEGIBLE, FALLOS_DE_LECTURA):
        digests = {
            aid: hashlib.sha256((raiz / ruta).read_bytes()).hexdigest()
            for aid, ruta in APPROVED_SCHEMA_ARTIFACTS.items()
        }
    obtenido = fingerprint(digests)
    if obtenido != APPROVED_VALIDATOR_BUNDLE_SHA256:
        raise BundleRechazado(
            f"{MENSAJE_DE_FALLO}\n"
            f"  esperado {APPROVED_VALIDATOR_BUNDLE_SHA256}\n"
            f"  obtenido {obtenido}\n{describe(digests)}"
        )
    return obtenido


def fingerprint(digests: Mapping[str, str]) -> str:
    """Fingerprint canónico a partir de `{artifact_id: sha256}`.

    Es una función pura: recibe los digests ya calculados, de modo que puede
    ejercitarse con valores simulados sin tocar ningún fichero real.
    """
    secuencia = "".join(f"{aid}:{digests[aid]}\n" for aid in sorted(digests))
    return hashlib.sha256(secuencia.encode("utf-8")).hexdigest()


def describe(digests: Mapping[str, str]) -> str:
    """Representación legible, para que un fallo diga qué cambió."""
    return "".join(f"  {aid}: {digests[aid]}\n" for aid in sorted(digests))
