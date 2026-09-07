"""Errores del parser fiscal.

Cada uno lleva un **código estable legible por máquina** y un mensaje seguro.
Ninguno incluye el XML de origen: son documentos fiscales de terceros, con
nombres, correos y direcciones, y no tienen por qué acabar en un log.
"""

from __future__ import annotations


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


class UnsupportedDocument(FiscalParseError):
    """La raíz o el namespace no corresponden a un comprobante soportado.

    Cubre tres situaciones distintas, todas deterministas:

    - raíz desconocida;
    - raíz conocida con **namespace equivocado** —una versión distinta del
      esquema no debe caer en el de 4.4—;
    - documento reconocido pero **sin soporte semántico probado** todavía, que
      hoy es el caso de la Nota de Débito.
    """

    code = "unsupported_document"


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
