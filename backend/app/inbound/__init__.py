"""Canal inbound: Buzón Tribuu (C4-B1) y adaptador Resend/Svix (C4-B2)."""

from app.inbound.errors import (
    EventParseError,
    InboundAdapterError,
    SignatureVerificationError,
)
from app.inbound.events import (
    PROVIDER_RESEND,
    EventOutcome,
    InboundAttachmentMeta,
    NormalizedInboundEvent,
    RecipientResolution,
    ResolvedRecipient,
)
from app.inbound.resend_adapter import (
    normalize_event,
    verify_and_normalize,
    verify_svix,
)
from app.inbound.routing import normalize_recipient, resolve_recipient, route_event
from app.inbound.tokens import ALFABETO_TOKEN, LONGITUD_TOKEN, generar_routing_token

__all__ = [
    "ALFABETO_TOKEN",
    "LONGITUD_TOKEN",
    "generar_routing_token",
    "PROVIDER_RESEND",
    "EventOutcome",
    "RecipientResolution",
    "NormalizedInboundEvent",
    "InboundAttachmentMeta",
    "ResolvedRecipient",
    "InboundAdapterError",
    "SignatureVerificationError",
    "EventParseError",
    "verify_svix",
    "normalize_event",
    "verify_and_normalize",
    "normalize_recipient",
    "resolve_recipient",
    "route_event",
]
