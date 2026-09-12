"""Registro de esquemas verificados — la única vía de producción.

**Por qué existe.** Hasta R1, el parser compilaba esquemas directamente y la
puerta *fail-closed* del paquete solo la ejercitaban los tests. Es decir: CI
comprobaba la membresía física, la identidad, las rutas, los bytes, el
fingerprint y los enlaces simbólicos… y el punto de entrada real de
producción no dependía de nada de eso.

Aquí se cierra ese hueco. La inicialización:

1. verifica el paquete aprobado —conjunto físico, identidad, rutas, bytes,
   fingerprint y ausencia de symlinks—;
2. **solo si la verificación pasa**, compila los esquemas;
3. devuelve el registro compilado y lo cachea.

**Vínculo bytes verificados → esquemas consumidos.** El registro guarda los
objetos `XMLSchema` **ya compilados a partir de los bytes verificados**. Las
llamadas posteriores reutilizan esos objetos y **no vuelven a abrir el
paquete**: si se releyeran los ficheros en cada parseo, lo verificado y lo
consumido podrían divergir entre una comprobación y la siguiente.

**Taxonomía (R2).** El fingerprint cubre los bytes de los `*.xsd`, **no** los
del `MANIFEST.json`. Por eso un manifiesto puede pasar la puerta —el mapeo
`id -> ruta` es el aprobado y los bytes de los esquemas cuadran— y aun así no
describir los campos que el catálogo consume (`namespace`, `sha256`, `bytes`).
Ese consumo se somete a la misma taxonomía de `policy`, de modo que un
manifiesto incompleto sale por `BundleRechazado` y no como un `KeyError` a
medio camino. Los defectos de programación **no** se normalizan: siguen
propagándose tal cual.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from lxml import etree

from app.fiscal.errors import ValidatorConfigurationError
# Se importa el MÓDULO, no `BUNDLE` por valor: importarlo por valor fijaría
# la raíz verificada en tiempo de import, y lo verificado dejaría de poder
# coincidir con lo que el módulo considera su paquete.
from app.fiscal.xsd import bundle, policy
from app.fiscal.xsd.bundle import PoliticaDeRecursos, SchemaEntry


@dataclass(frozen=True, slots=True)
class VerifiedSchemaRegistry:
    """Esquemas compilados a partir de un paquete ya verificado."""

    fingerprint: str
    _por_clave: dict[tuple[str, str], tuple[SchemaEntry, etree.XMLSchema]]

    def para(self, raiz: str, namespace: str) -> tuple[SchemaEntry, etree.XMLSchema] | None:
        """Esquema compilado para `(raíz, namespace)`, o `None`.

        La identidad es el par completo: una raíz conocida con el namespace de
        otra versión no encuentra esquema.
        """
        return self._por_clave.get((raiz, namespace))

    def entradas(self) -> tuple[SchemaEntry, ...]:
        """Entradas de los esquemas VERIFICADOS que son documento raíz.

        Existe para que un consumidor pueda leer metadatos del paquete
        aprobado —hoy, la versión estructural que la ingesta registra en
        `detected_schema_version`— sin alcanzar el mapa interno ni volver a
        interpretar el manifiesto, el identificador o el namespace.

        Devuelve una tupla de `SchemaEntry`, que es `frozen`: es lectura, no
        el mapa. `_por_clave` sigue siendo detalle de implementación, y el
        enrutado sigue siendo exclusivamente de `para()`.

        Se excluyen las dependencias —las que no tienen raíz—: no son
        documentos y no se enrutan.
        """
        return tuple(
            entrada
            for entrada, _esquema in self._por_clave.values()
            if entrada.root is not None
        )


#: Motivo canónico del rechazo por clave de enrutado repetida. Texto fijo: no
#: nombra el esquema ni el namespace en conflicto, porque el mensaje viaja
#: encadenado hasta la frontera pública.
RAZON_RUTA_DUPLICADA = (
    "Dos esquemas del catálogo comparten la misma clave de enrutado "
    "(raíz, namespace)."
)


def _catalogo_del_paquete() -> tuple[SchemaEntry, ...]:
    """Catálogo del manifiesto, en la taxonomía de `policy`.

    `verify_approved_schema_bundle` comprueba el mapeo `id -> ruta` y los bytes
    de los esquemas, pero **no** los demás campos del manifiesto: no entran en
    el fingerprint. Aquí se consume el resto —`namespace`, `sha256`, `bytes`—,
    así que aquí es donde un manifiesto incompleto se convierte en un rechazo
    de paquete en lugar de en un `KeyError`.

    **Unicidad de la clave de enrutado (R3).** El reparto de responsabilidades
    es explícito: la política aprueba *qué ficheros* son el paquete —membresía
    física, identidad, rutas, bytes, symlinks—; el registro responde de *cómo
    se elige* un esquema. Un manifiesto puede conservar ids, rutas y bytes
    aprobados —y pasar la puerta— y aun así asignar la misma
    `(raíz, namespace)` a dos esquemas. Insertándolos en un diccionario, el
    segundo pisaba al primero **en silencio**: el registro se quedaba con
    cuatro rutas en vez de cinco y los comprobantes de un tipo pasaban a
    validarse contra el esquema de otro. Aquí se rechaza, antes de compilar.
    """
    with policy.rechazar_si_falla(
        policy.RAZON_MANIFIESTO_INCOMPLETO, policy.FALLOS_DEL_MANIFIESTO
    ):
        catalogo = bundle.entries()

    # 1 · Los campos que forman la clave del registro tienen que ser texto: si
    #     no, el fallo aparecería como un `TypeError` de clave no hashable al
    #     insertar. Se comprueban TODOS antes de formar ninguna clave.
    for entrada in catalogo:
        if not (
            isinstance(entrada.id, str)
            and isinstance(entrada.path, str)
            and isinstance(entrada.namespace, str)
            and (entrada.root is None or isinstance(entrada.root, str))
        ):
            raise policy.BundleRechazado(
                f"{policy.RAZON_MANIFIESTO_INCOMPLETO}\n{policy.MENSAJE_DE_FALLO}"
            )

    # 2 · Unicidad de la clave de enrutado.
    vistas: dict[tuple[str, str], str] = {}
    for entrada in catalogo:
        if entrada.root is None:
            continue                      # dependencia: no enruta comprobantes
        clave = (entrada.root, entrada.namespace)
        if clave in vistas:
            # Se detecta ANTES de insertar en ningún diccionario: comparar
            # longitudes después habría perdido ya cuál de los dos ganó.
            raise policy.BundleRechazado(
                f"{RAZON_RUTA_DUPLICADA}\n{policy.MENSAJE_DE_FALLO}"
            )
        vistas[clave] = entrada.id

    return catalogo


@lru_cache(maxsize=1)
def get_verified_schema_registry() -> VerifiedSchemaRegistry:
    """Inicializa —una vez— el registro verificado de producción.

    `lru_cache` da la semántica que hace falta sin sincronización a medida:
    bajo el GIL, una carrera entre hilos podría ejecutar la inicialización dos
    veces, pero ambas verifican el mismo paquete y compilan los mismos bytes,
    así que el resultado es equivalente y solo uno queda cacheado.

    Falla **cerrado**: si el paquete no es el aprobado, no se compila nada.
    """
    # Único punto de traducción: taxonomía de política -> taxonomía pública.
    try:
        fingerprint = policy.verify_approved_schema_bundle(bundle.BUNDLE)
        catalogo = _catalogo_del_paquete()
    except policy.BundleRechazado as exc:
        # Mensaje público deliberadamente escueto: el detalle puede citar
        # rutas del sistema de ficheros del servidor. La causa concreta queda
        # en `__cause__`, no en el texto.
        raise ValidatorConfigurationError(
            "El paquete de esquemas oficiales no es el aprobado para este validador"
        ) from exc

    compilados: dict[tuple[str, str], tuple[SchemaEntry, etree.XMLSchema]] = {}
    politica = PoliticaDeRecursos()
    for entrada in catalogo:
        if entrada.root is None:
            continue                      # dependencia: entra vía sus importadores
        try:
            compilados[(entrada.root, entrada.namespace)] = (
                entrada,
                bundle.compilar(entrada.id, politica),
            )
        except (etree.XMLSchemaParseError, etree.XMLSyntaxError, OSError) as exc:
            # Un esquema ya verificado que no compila o no se puede abrir es
            # un fallo de despliegue, no del documento del contribuyente.
            raise ValidatorConfigurationError(
                "Un esquema oficial del paquete no compila", esquema=entrada.id
            ) from exc

    if politica.rechazados:
        raise ValidatorConfigurationError(
            "La compilación intentó resolver un recurso fuera del paquete"
        )

    return VerifiedSchemaRegistry(fingerprint=fingerprint, _por_clave=compilados)
