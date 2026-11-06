"""Errores del adaptador inbound (C4-B2)."""


class InboundAdapterError(RuntimeError):
    """Base. Nunca transporta el secreto del webhook ni el cuerpo crudo."""


class SignatureVerificationError(InboundAdapterError):
    """La firma Svix no verificó sobre el RAW body (o faltan cabeceras)."""


class EventParseError(InboundAdapterError):
    """El cuerpo verificado no es un email.received con la forma esperada."""
