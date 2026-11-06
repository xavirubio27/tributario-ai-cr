"""Enrutamiento multi-tenant del canal inbound (C4-B2, ADR-049).

Cada recipient de ENTREGA se resuelve de forma AISLADA contra el registro
C4-B1 mediante inbound_transaction(): una transacción por recipient, nunca una
que abarque dos empresas. El contexto es transaction-local (garantía de
C4-B1), así que un recipient desconocido jamás conserva el contexto del
anterior y un tenant A nunca contamina a B.

La autoridad de tenant es EXCLUSIVAMENTE el registro: aquí no se acepta
company_id ni inbox_id de ninguna fuente externa; el único insumo es la
dirección normalizada.
"""

from __future__ import annotations

import re

from app.db import InboundContextError, inbound_transaction
from app.inbound.events import (
    NormalizedInboundEvent,
    RecipientResolution,
    ResolvedRecipient,
)

# Forma mínima y conservadora de una dirección de correo: algo@algo.tld. No
# pretende validar el RFC 5321 entero; solo descarta lo vacío/sintácticamente
# imposible antes de tocar la base. La resolución REAL la hace el registro.
_DIRECCION = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_recipient(crudo: str) -> str | None:
    """Normalización CONSERVADORA de un recipient antes de resolverlo.

    - recorta espacios externos;
    - baja a minúsculas SOLO el dominio (la parte local se respeta: en teoría
      es case-sensitive, y bajarla podría convertir una dirección en otra);
    - rechaza vacío o sintácticamente inválido devolviendo None.

    No inventa alias, no quita caracteres significativos, no hace fuzzy match.
    """
    if not isinstance(crudo, str):
        return None
    valor = crudo.strip()
    if not valor or valor.count("@") != 1:
        return None
    local, _, dominio = valor.partition("@")
    if not local or not dominio:
        return None
    candidato = f"{local}@{dominio.lower()}"
    if not _DIRECCION.match(candidato):
        return None
    return candidato


def resolve_recipient(pool, settings, recipient_crudo: str) -> ResolvedRecipient:
    """Resuelve UN recipient en su propia transacción aislada.

    Normaliza → inbound_transaction (que invoca private.enter_inbound_context) →
    ACTIVE_RESOLVED con inbox/company, o fail-closed:
      - dirección inválida/vacía → INVALID_RECIPIENT (ni se consulta la base);
      - sin buzón activo (inexistente o deshabilitado) → UNKNOWN_RECIPIENT.

    No se distingue hacia fuera "desconocido" de "deshabilitado": ambos son un
    buzón no-activo y colapsan a UNKNOWN_RECIPIENT para no permitir enumerar
    qué direcciones existen. La resolución nunca abre trabajo si no hay buzón.
    """
    normalizado = normalize_recipient(recipient_crudo)
    if normalizado is None:
        return ResolvedRecipient(
            recipient=recipient_crudo, resolution=RecipientResolution.INVALID_RECIPIENT
        )
    try:
        with inbound_transaction(pool, settings, normalizado) as conn:
            fila = conn.execute(
                "select private.inbound_inbox_id() as inbox, "
                "private.inbound_company_id() as company"
            ).fetchone()
            return ResolvedRecipient(
                recipient=normalizado,
                resolution=RecipientResolution.ACTIVE_RESOLVED,
                inbox_id=str(fila["inbox"]),
                company_id=str(fila["company"]),
            )
    except InboundContextError:
        # fail-closed: no hay buzón activo para esa dirección.
        return ResolvedRecipient(
            recipient=normalizado, resolution=RecipientResolution.UNKNOWN_RECIPIENT
        )


def route_event(pool, settings, event: NormalizedInboundEvent) -> list[ResolvedRecipient]:
    """Resuelve TODOS los recipients de entrega del evento, cada uno aislado.

    Devuelve una resolución por recipient, en orden. Varias empresas en un
    mismo evento producen varias resoluciones independientes; ninguna
    transacción contiene dos empresas.
    """
    return [resolve_recipient(pool, settings, r) for r in event.recipients]
