"""Errores del parser fiscal.

Cada uno lleva un **código estable legible por máquina** y un mensaje seguro.
Ninguno incluye el XML de origen: son documentos fiscales de terceros, con
nombres, correos y direcciones, y no tienen por qué acabar en un log.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class FiscalParseError(Exception):
    """Raíz de todo fallo del parser. Nada de lxml cruza la frontera pública."""

    code = "fiscal_parse_error"

    def __init__(self, message: str, **contexto: object) -> None:
        super().__init__(message)
        self.message = message
        self.contexto = {k: v for k, v in contexto.items() if v is not None}

    def __str__(self) -> str:  # pragma: no cover - representación
        if not self.contexto:
            return self.message
        extra = " · ".join(f"{k}={v!r}" for k, v in sorted(self.contexto.items()))
        return f"{self.message} ({extra})"


class MalformedXML(FiscalParseError):
    """Los bytes no son XML bien formado, o declaran DOCTYPE/entidades."""

    code = "malformed_xml"


@dataclass(frozen=True, slots=True)
class DocumentDetection:
    """Lo que el parser llegó a IDENTIFICAR antes de decidir o de fallar.

    Existe para que la ingesta pueda registrar qué documento era sin volver a
    mirar el XML ni leer el texto de un mensaje de error. El parser sigue
    siendo el único dueño de la detección; esto solo la hace legible.

    No lleva ningún dato del contribuyente: tipo canónico y versión
    estructural del esquema, ambos de nuestro vocabulario.
    """

    document_type: str
    schema_version: str


class UnsupportedDocumentReason(StrEnum):
    """Por qué un documento no se procesa. Discriminador ESTABLE.

    Sin él, las tres rutas que levantan `UnsupportedDocument` solo se
    distinguían leyendo el mensaje — el mismo antipatrón que ya se corrigió en
    el parser (B2-R2) y en la traducción de errores de la persistencia
    (C1-B-R2).

    Los tres valores corresponden exactamente a las tres condiciones reales
    del código, ni una más:
    """

    #: Ni la raíz ni el namespace corresponden a ningún esquema del paquete.
    UNKNOWN_DOCUMENT = "unknown_document"
    #: Esquema reconocido, pero el documento no es un comprobante —
    #: `MensajeHacienda` no tiene líneas ni totales.
    OUTSIDE_PIPELINE = "outside_pipeline"
    #: Comprobante reconocido sin soporte semántico probado — hoy, la Nota de
    #: Débito: existe el esquema, no existe un comprobante real con el que
    #: probar la extracción.
    UNSUPPORTED_TYPE = "unsupported_type"


class UnsupportedDocument(FiscalParseError):
    """El documento no entra en el pipeline de comprobantes normalizados.

    `reason` es obligatorio y tipado: quien lo reciba decide por dato, no por
    texto. `detection` existe cuando el esquema SÍ se identificó — es decir,
    en todo caso salvo `UNKNOWN_DOCUMENT`.
    """

    code = "unsupported_document"

    def __init__(
        self,
        message: str,
        *,
        reason: UnsupportedDocumentReason,
        detection: DocumentDetection | None = None,
        **contexto: object,
    ) -> None:
        super().__init__(message, reason=reason.value, **contexto)
        self.reason = reason
        self.detection = detection


class XSDValidationError(FiscalParseError):
    """El documento no es conforme a su esquema oficial.

    **El diagnóstico se construye solo con metadatos estructurales** —tipo de
    error de libxml2, línea y columna—, nunca con el texto del mensaje.

    Recortar el mensaje no bastaba: libxml2 escribe el valor infractor al
    principio, así que los primeros caracteres son precisamente los que hay
    que no publicar. Un `<Clave>` inválido llegaba a exponer el identificador
    completo del contribuyente. Truncar no es redactar.
    """

    code = "xsd_validation_error"

    def __init__(
        self, message: str, *, detection: "DocumentDetection | None" = None,
        **contexto: object,
    ) -> None:
        super().__init__(message, **contexto)
        #: El esquema SÍ se identificó antes de este fallo.
        self.detection = detection


class ValidatorConfigurationError(FiscalParseError):
    """El paquete de esquemas del servidor no es el aprobado.

    **No es un problema del documento del usuario.** Que la puerta
    *fail-closed* rechace el paquete significa que la instalación está
    comprometida o mal desplegada — un esquema de más, uno modificado, un
    enlace simbólico—, y clasificarlo como «XML inválido» culparía al
    contribuyente de un fallo nuestro y ocultaría el incidente real.

    El mensaje público no revela rutas del sistema de ficheros.
    """

    code = "validator_bundle_invalid"


class SemanticParseError(FiscalParseError):
    """El documento es XSD-válido pero no se puede mapear al dominio.

    En la práctica solo debería ocurrir si el esquema oficial cambia y deja
    de garantizar algo que el modelo da por seguro.
    """

    code = "semantic_parse_error"

    def __init__(
        self, message: str, *, detection: "DocumentDetection | None" = None,
        **contexto: object,
    ) -> None:
        super().__init__(message, **contexto)
        #: El esquema SÍ se identificó antes de este fallo.
        self.detection = detection


# ─────────────────────────────────────────────────────────────────────────────
# Persistencia (C1)
#
# Errores de la capa que guarda un `ParsedFiscalDocument` en PostgreSQL. Misma
# regla que arriba: nada del motor cruza la frontera pública. Ni SQL, ni
# diagnóstico de PostgreSQL, ni datos del contribuyente.
#
# El contexto seguro es estructural —`stage`, tipo de entidad, UUID internos—,
# nunca `clave`, nombres, identificaciones ni descripciones de línea.
# ─────────────────────────────────────────────────────────────────────────────


class FiscalPersistenceError(Exception):
    """Raíz de todo fallo de persistencia fiscal.

    No hereda de `FiscalParseError`: parsear y guardar son fases distintas y
    confundirlas haría que un fallo de base de datos pareciera un documento
    inválido.
    """

    code = "fiscal_persistence_error"

    def __init__(self, message: str, **contexto: object) -> None:
        super().__init__(message)
        self.message = message
        self.contexto = {k: v for k, v in contexto.items() if v is not None}

    def __str__(self) -> str:  # pragma: no cover - representación
        if not self.contexto:
            return self.message
        extra = " · ".join(f"{k}={v!r}" for k, v in sorted(self.contexto.items()))
        return f"{self.message} ({extra})"


class SourceDocumentNotFound(FiscalPersistenceError):
    """El artefacto de origen no es visible por el camino aprobado.

    **Agrupa a propósito tres situaciones**: no existe, es de otra empresa, o
    quien pregunta no es miembro. Distinguirlas convertiría el identificador en
    un oráculo de existencia entre tenants — se podría averiguar qué documentos
    tiene otra empresa probando UUID—. No enumerable es una propiedad, no una
    imprecisión.
    """

    code = "source_document_not_found"


class FiscalWriteForbidden(FiscalPersistenceError):
    """El usuario ve el artefacto pero RLS no le concede la escritura.

    Es el `viewer` de [ADR-038]. Se detecta **observando el comportamiento de
    RLS**, no consultando `company_memberships`: PostgreSQL sigue siendo la
    única autoridad de autorización y Python no reproduce su lógica de roles.
    """

    code = "fiscal_write_forbidden"


class SourceDocumentStateConflict(FiscalPersistenceError):
    """El artefacto ya está normalizado como OTRO documento.

    No se reenlaza jamás: el enlace es la traza de cómo llegó esa copia, y
    reescribirlo en silencio destruiría la evidencia de la discrepancia.
    """

    code = "source_document_state_conflict"


class ClaveConflict(FiscalPersistenceError):
    """Misma empresa, misma clave, sin evidencia de equivalencia.

    **No afirma que el contenido fiscal difiera** — afirma que el MVP no puede
    probar la equivalencia automáticamente ([ADR-042]). Hasta que exista un
    componente de equivalencia canónica, esto exige que alguien lo mire.
    """

    code = "clave_conflict"


class PersistenceMappingError(FiscalPersistenceError):
    """Un estado válido del dominio no cupo en el modelo físico.

    **Es un defecto NUESTRO, no un documento inválido del contribuyente.** Si
    el XML pasó el XSD oficial y el parser, y aun así la base lo rechaza, quien
    se equivocó fue nuestro mapeo. Es la lección de las tres rondas de B2:
    culpar al contribuyente de un fallo propio esconde el fallo propio.
    """

    code = "persistence_mapping_error"


class PersistenceUnavailable(FiscalPersistenceError):
    """Fallo de infraestructura. A diferencia del resto, **es reintentable**."""

    code = "persistence_unavailable"


class PersistenceDatabaseError(FiscalPersistenceError):
    """Fallo de base de datos **inesperado** dentro de la persistencia.

    No es un defecto de mapeo, ni una denegación de autorización, ni un fallo
    de infraestructura reintentable, ni una rama de deduplicación. Cubre lo que
    no encaja en ninguna categoría aprobada: SQL mal formado, columna o tabla
    inexistente, estado de protocolo inesperado — es decir, **defectos de
    programación nuestros**.

    Se separa de `PersistenceMappingError` a propósito. Ese nombre significa
    algo concreto: «la representación aprobada del dominio no cupo en el modelo
    físico». Meter ahí un `UndefinedColumn` diría que el documento del
    contribuyente no encaja, cuando lo que pasa es que escribimos mal una
    consulta. Confundirlos mandaría a revisar los datos en lugar del código.

    **No es reintentable**: reintentar un bug da el mismo bug.
    """

    code = "persistence_database_error"


# ─────────────────────────────────────────────────────────────────────────────
# Ingesta (C2)
#
# Errores de la frontera que RECIBE la evidencia. Son de entrada y de recurso:
# no hablan del contenido fiscal, porque en este punto todavía no se ha mirado
# ningún XML. Por eso no se reutilizan `MalformedXML` ni `XSDValidationError`:
# dirían que el XML está mal cuando ni siquiera se ha intentado leerlo.
#
# Todo lo demás —parseo y persistencia— la ingesta lo reutiliza tal cual.
# ─────────────────────────────────────────────────────────────────────────────


class FiscalIngestionError(Exception):
    """Raíz de los fallos de la capa de ingesta."""

    code = "fiscal_ingestion_error"

    def __init__(self, message: str, **contexto: object) -> None:
        super().__init__(message)
        self.message = message
        self.contexto = {k: v for k, v in contexto.items() if v is not None}

    def __str__(self) -> str:  # pragma: no cover - representación
        if not self.contexto:
            return self.message
        extra = " · ".join(f"{k}={v!r}" for k, v in sorted(self.contexto.items()))
        return f"{self.message} ({extra})"


class SourceDocumentTooLarge(FiscalIngestionError):
    """El artefacto supera el máximo admitido por la frontera de dominio.

    C3 pondrá además su límite de transporte, pero la frontera del dominio no
    puede depender de que el canal se comporte: un llamante directo de la API
    llegaría hasta `bytea` sin tope.
    """

    code = "source_document_too_large"


class EmptySourceDocument(FiscalIngestionError):
    """Cero bytes no son evidencia de nada.

    No hay artefacto que preservar, así que se rechaza **antes** de insertar.
    Guardarlo crearía una fila que jamás podrá procesarse —y que además pasa el
    CHECK, porque `sha256(b'')` es un hash válido— sin representar ningún
    hecho.
    """

    code = "empty_source_document"
