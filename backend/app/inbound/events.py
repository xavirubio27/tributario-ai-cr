"""Modelo interno PROVIDER-NEUTRAL del canal inbound (C4-B2, ADR-049).

Representa un evento de correo entrante ya verificado y normalizado, sin rastro
del proveedor concreto (Resend hoy, otro mañana). La frontera C4-B2 termina
aquí: este modelo transporta SOLO lo necesario para enrutar al tenant y para
que C4-B3 capture evidencia más adelante.

Tres identidades que NUNCA se mezclan (ADR-049):
  - provider_event_id   : identidad del EVENTO del proveedor  (Resend: svix-id)
  - provider_email_id   : identidad del CORREO del proveedor  (Resend: data.email_id)
  - internet_message_id : Message-ID RFC del correo           (Resend: data.message_id)

Autoridad de tenant (ADR-049): SOLO los recipients de ENTREGA del proveedor,
que provienen EXCLUSIVAMENTE de `data.to`. `data.received_for` se conserva
como señal de TRAZA (`trace_received_for`) y NUNCA es autoridad: no alimenta
`recipients`, no abre transacción y no produce company/inbox. From, Reply-To,
Subject, cuerpo, nombres/bytes de adjuntos y dominio del remitente son NO
CONFIABLES. No hay fallback de `to` hacia `received_for`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

PROVIDER_RESEND = "resend"


class EventOutcome(StrEnum):
    """Desenlace de la normalización de un evento, antes de enrutar."""

    NORMALIZED = "normalized"              # email.received válido y normalizado
    IGNORED_EVENT_TYPE = "ignored_event_type"   # firmado pero no es email.received


class RecipientResolution(StrEnum):
    """Resultado de resolver UN recipient contra el registro C4-B1."""

    ACTIVE_RESOLVED = "active_resolved"    # buzón activo -> inbox_id + company_id
    UNKNOWN_RECIPIENT = "unknown_recipient"     # no hay buzón activo para esa dirección
    INVALID_RECIPIENT = "invalid_recipient"     # dirección vacía/sintácticamente inválida


@dataclass(frozen=True)
class InboundAttachmentMeta:
    """SOLO metadata declarada en email.received. C4-B2 NO descarga bytes."""

    provider_attachment_id: str | None
    filename: str | None            # NO CONFIABLE: nombre declarado por el remitente
    content_type: str | None        # NO CONFIABLE: tipo declarado
    content_disposition: str | None
    content_id: str | None


@dataclass(frozen=True)
class NormalizedInboundEvent:
    """Evento de correo entrante verificado y neutral al proveedor."""

    provider: str
    provider_event_id: str          # identidad del evento (idempotencia futura C4-B3)
    provider_email_id: str          # identidad del correo en el proveedor
    internet_message_id: str | None  # Message-ID RFC (opcional en el contrato real)
    event_type: str
    occurred_at: str | None          # instante del proveedor (ISO), fuente confiable
    recipients: tuple[str, ...]      # destinatarios de entrega del PROVEEDOR (data.to): ÚNICA autoridad de routing
    # ── señal de traza: informativa, JAMÁS autoridad de tenant (ADR-049) ──
    trace_received_for: tuple[str, ...] = ()
    # ── metadata NO CONFIABLE (jamás autoridad de tenant) ──
    untrusted_from: str | None = None
    untrusted_subject: str | None = None
    attachments: tuple[InboundAttachmentMeta, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ResolvedRecipient:
    """Un recipient tras pasar por el registro C4-B1 (aislado por transacción)."""

    recipient: str                   # la dirección normalizada tal como se resolvió
    resolution: RecipientResolution
    company_id: str | None = None    # solo si ACTIVE_RESOLVED
    inbox_id: str | None = None      # solo si ACTIVE_RESOLVED
