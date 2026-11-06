"""Adaptador provider-specific de Resend (C4-B2, ADR-049).

Convierte un webhook HTTP de Resend en un NormalizedInboundEvent, en este orden
INQUEBRANTABLE:

    RAW body bytes + cabeceras svix
        -> verificación Svix (HMAC sobre el RAW, con la librería oficial)
        -> SOLO entonces json.loads del MISMO raw
        -> normalización a modelo neutral

Nunca se parsea-y-reserializa para verificar: se verifica el byte-stream que
llegó y se parsea ese mismo byte-stream. El secreto del webhook jamás se
registra, ni se devuelve en errores, ni aparece en repr.

Este módulo NO tiene capa HTTP, NO descarga adjuntos, NO llama a C2 y NO captura
evidencia durable. Es una función pura de frontera; C4-B3 lo conectará a la
captura durable y recién entonces habrá endpoint productivo.
"""

from __future__ import annotations

import json

from svix.webhooks import Webhook, WebhookVerificationError

from app.inbound.errors import EventParseError, SignatureVerificationError
from app.inbound.events import (
    PROVIDER_RESEND,
    EventOutcome,
    InboundAttachmentMeta,
    NormalizedInboundEvent,
)

_EVENT_RECEIVED = "email.received"


def verify_svix(raw_body: bytes, headers: dict[str, str], secret: str) -> bytes:
    """Verifica la firma Svix sobre el RAW body. Devuelve el mismo raw si pasa.

    `headers` debe traer svix-id / svix-timestamp / svix-signature (cualquier
    casing). La librería valida HMAC y la ventana temporal (anti-replay). Si
    algo falla —cabeceras ausentes, firma inválida, cuerpo alterado, timestamp
    fuera de ventana— se levanta SignatureVerificationError SIN detalle que
    revele el secreto.
    """
    bajos = {k.lower(): v for k, v in headers.items()}
    faltan = [h for h in ("svix-id", "svix-timestamp", "svix-signature")
              if not bajos.get(h)]
    if faltan:
        raise SignatureVerificationError(
            f"faltan cabeceras de firma: {', '.join(faltan)}"
        )
    if not secret:
        # Config ausente: fail-closed. No es un fallo del remitente.
        raise SignatureVerificationError("webhook secret no configurado")

    texto = raw_body.decode("utf-8", "strict") if isinstance(raw_body, bytes) else raw_body
    try:
        Webhook(secret).verify(texto, {
            "svix-id": bajos["svix-id"],
            "svix-timestamp": bajos["svix-timestamp"],
            "svix-signature": bajos["svix-signature"],
        })
    except WebhookVerificationError as exc:
        # Mensaje genérico: nunca el secreto ni el cuerpo.
        raise SignatureVerificationError(f"firma Svix inválida: {exc}") from None
    return raw_body


def _parse_verificado(raw_body: bytes) -> dict:
    """json.loads del RAW ya verificado. No reserializa nada."""
    try:
        payload = json.loads(raw_body)
    except (ValueError, TypeError) as exc:
        raise EventParseError(f"cuerpo verificado no es JSON: {exc}") from None
    if not isinstance(payload, dict):
        raise EventParseError("el cuerpo verificado no es un objeto JSON")
    return payload


def _normalizar_adjuntos(data: dict) -> tuple[InboundAttachmentMeta, ...]:
    crudos = data.get("attachments") or []
    if not isinstance(crudos, list):
        return ()
    salida = []
    for a in crudos:
        if not isinstance(a, dict):
            continue
        salida.append(InboundAttachmentMeta(
            provider_attachment_id=a.get("id"),
            filename=a.get("filename"),
            content_type=a.get("content_type"),
            content_disposition=a.get("content_disposition"),
            content_id=a.get("content_id"),
        ))
    return tuple(salida)


def _lista_str(valor: object) -> tuple[str, ...]:
    if isinstance(valor, list):
        return tuple(str(x) for x in valor if isinstance(x, str) and x.strip())
    if isinstance(valor, str) and valor.strip():
        return (valor,)
    return ()


def normalize_event(
    payload: dict, provider_event_id: str
) -> tuple[EventOutcome, NormalizedInboundEvent | None]:
    """Normaliza un payload de Resend ya verificado a modelo neutral.

    `provider_event_id` es el svix-id (identidad del EVENTO), que viaja en la
    cabecera, no en el cuerpo. Un evento firmado pero de otro tipo devuelve
    (IGNORED_EVENT_TYPE, None): reconocido, no enrutado, sin tocar contenido.
    """
    tipo = payload.get("type")
    if tipo != _EVENT_RECEIVED:
        return EventOutcome.IGNORED_EVENT_TYPE, None

    data = payload.get("data")
    if not isinstance(data, dict):
        raise EventParseError("email.received sin objeto data")

    email_id = data.get("email_id")
    if not isinstance(email_id, str) or not email_id.strip():
        raise EventParseError("email.received sin email_id")

    # AUTORIDAD DE ROUTING = data.to EXCLUSIVAMENTE (ADR-049). Sin fallback a
    # received_for: si no hay `to` válido, el evento es inválido (fail-closed).
    recipients = _lista_str(data.get("to"))
    if not recipients:
        raise EventParseError("email.received sin data.to (destinatarios de entrega)")

    message_id = data.get("message_id")   # opcional en el contrato real
    evento = NormalizedInboundEvent(
        provider=PROVIDER_RESEND,
        provider_event_id=provider_event_id,
        provider_email_id=email_id,
        internet_message_id=message_id if isinstance(message_id, str) and message_id else None,
        event_type=_EVENT_RECEIVED,
        occurred_at=payload.get("created_at") if isinstance(payload.get("created_at"), str) else None,
        recipients=recipients,
        # received_for se conserva SOLO como traza; nunca autoridad de tenant.
        trace_received_for=_lista_str(data.get("received_for")),
        untrusted_from=data.get("from") if isinstance(data.get("from"), str) else None,
        untrusted_subject=data.get("subject") if isinstance(data.get("subject"), str) else None,
        attachments=_normalizar_adjuntos(data),
    )
    return EventOutcome.NORMALIZED, evento


def verify_and_normalize(
    raw_body: bytes, headers: dict[str, str], secret: str
) -> tuple[EventOutcome, NormalizedInboundEvent | None]:
    """Frontera completa: verifica Svix sobre el RAW, luego parsea y normaliza.

    El svix-id verificado ES la identidad del evento. Jamás se usa email_id ni
    message_id como sustituto de esa identidad.
    """
    verify_svix(raw_body, headers, secret)
    bajos = {k.lower(): v for k, v in headers.items()}
    payload = _parse_verificado(raw_body)
    return normalize_event(payload, provider_event_id=bajos["svix-id"])
