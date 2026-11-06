"""C4-B2 · Adaptador Resend + verificación Svix + enrutamiento (ADR-049).

Svix/parsing/identidades/normalización son unidad (sin DB). El enrutamiento
multi-tenant corre contra PostgreSQL real reutilizando el registro C4-B1.
Ningún test descarga adjuntos, invoca C2, captura evidencia durable ni expone
un ACK productivo: esa frontera pertenece a C4-B3.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

import pytest

from app.db import fiscal_transaction
from app.inbound import (
    EventOutcome,
    EventParseError,
    RecipientResolution,
    SignatureVerificationError,
    generar_routing_token,
    normalize_event,
    normalize_recipient,
    resolve_recipient,
    route_event,
    verify_and_normalize,
    verify_svix,
)

# ── secreto SINTÉTICO de prueba (jamás el real) ──
_SECRET_RAW = base64.b64encode(b"c4b2-synthetic-secret-32bytes!!!").decode()
_SECRET = "whsec_" + _SECRET_RAW


def _firmar(raw: bytes, msg_id="msg_2abc", ts=None):
    ts = ts or str(int(time.time()))
    firmado = f"{msg_id}.{ts}.".encode() + raw
    sig = base64.b64encode(
        hmac.new(base64.b64decode(_SECRET_RAW), firmado, hashlib.sha256).digest()
    ).decode()
    return {"svix-id": msg_id, "svix-timestamp": ts, "svix-signature": f"v1,{sig}"}


def _payload_received(email_id="4be2aa76", message_id="<abc@outlook.com>",
                      to=("pixdea-tok@inbox.tribuu.ai",),
                      received_for=None, **extra):
    # `to` es la autoridad de routing (ADR-049). `received_for` es traza:
    # si no se indica, por defecto refleja `to` (caso directo observado en C4-B0).
    data = {"email_id": email_id, "to": list(to),
            "received_for": list(received_for if received_for is not None else to),
            "from": "proveedor@ejemplo.com",
            "subject": "Factura de prueba", "attachments": [],
            "created_at": "2026-11-05T10:00:00.000Z"}
    if message_id is not None:
        data["message_id"] = message_id
    data.update(extra)
    return json.dumps({"type": "email.received", "created_at": "2026-11-05T10:00:00.000Z",
                       "data": data}).encode()


# ───────────────────────────────── Svix ──────────────────────────────────────

def test_firma_valida_pasa():
    raw = _payload_received()
    assert verify_svix(raw, _firmar(raw), _SECRET) == raw


def test_firma_invalida_falla():
    raw = _payload_received()
    cab = _firmar(raw)
    cab["svix-signature"] = "v1," + base64.b64encode(b"x" * 32).decode()
    with pytest.raises(SignatureVerificationError):
        verify_svix(raw, cab, _SECRET)


def test_cuerpo_alterado_tras_firmar_falla():
    raw = _payload_received()
    cab = _firmar(raw)
    with pytest.raises(SignatureVerificationError):
        verify_svix(raw + b" ", cab, _SECRET)


@pytest.mark.parametrize("falta", ["svix-id", "svix-timestamp", "svix-signature"])
def test_cabecera_svix_ausente_falla(falta):
    raw = _payload_received()
    cab = _firmar(raw)
    del cab[falta]
    with pytest.raises(SignatureVerificationError):
        verify_svix(raw, cab, _SECRET)


def test_timestamp_fuera_de_ventana_falla():
    raw = _payload_received()
    viejo = _firmar(raw, ts=str(int(time.time()) - 60 * 60))  # 1h: fuera de ventana Svix
    with pytest.raises(SignatureVerificationError):
        verify_svix(raw, viejo, _SECRET)


def test_secreto_no_configurado_falla_cerrado():
    raw = _payload_received()
    with pytest.raises(SignatureVerificationError):
        verify_svix(raw, _firmar(raw), "")


def test_el_secreto_no_aparece_en_errores_ni_repr():
    raw = _payload_received()
    cab = _firmar(raw)
    cab["svix-signature"] = "v1,malo"
    try:
        verify_svix(raw, cab, _SECRET)
        raise AssertionError("debió fallar")
    except SignatureVerificationError as exc:
        texto = f"{exc!r} {exc!s}"
        assert _SECRET not in texto
        assert _SECRET_RAW not in texto


# ─────────────────────────── parsing de evento ───────────────────────────────

def test_email_received_valido_se_normaliza():
    raw = _payload_received()
    outcome, ev = verify_and_normalize(raw, _firmar(raw, msg_id="msg_ev1"), _SECRET)
    assert outcome is EventOutcome.NORMALIZED
    assert ev.event_type == "email.received"
    assert ev.recipients == ("pixdea-tok@inbox.tribuu.ai",)


def test_otro_event_type_se_ignora():
    raw = json.dumps({"type": "email.delivered", "data": {"email_id": "x"}}).encode()
    outcome, ev = verify_and_normalize(raw, _firmar(raw), _SECRET)
    assert outcome is EventOutcome.IGNORED_EVENT_TYPE
    assert ev is None


def test_sin_email_id_falla():
    raw = json.dumps({"type": "email.received",
                      "data": {"received_for": ["a@inbox.tribuu.ai"]}}).encode()
    with pytest.raises(EventParseError):
        verify_and_normalize(raw, _firmar(raw), _SECRET)


def test_sin_to_falla():
    raw = json.dumps({"type": "email.received", "data": {"email_id": "e1"}}).encode()
    with pytest.raises(EventParseError):
        verify_and_normalize(raw, _firmar(raw), _SECRET)


def test_message_id_es_opcional():
    raw = _payload_received(message_id=None)
    outcome, ev = verify_and_normalize(raw, _firmar(raw), _SECRET)
    assert outcome is EventOutcome.NORMALIZED
    assert ev.internet_message_id is None


# ──────────────────────────── identidades separadas ──────────────────────────

def test_las_tres_identidades_no_se_intercambian():
    raw = _payload_received(email_id="EMAIL-123", message_id="<MID-456@x>")
    cab = _firmar(raw, msg_id="msg_EVENT789")
    _, ev = verify_and_normalize(raw, cab, _SECRET)
    assert ev.provider_event_id == "msg_EVENT789"       # svix-id (cabecera)
    assert ev.provider_email_id == "EMAIL-123"          # data.email_id
    assert ev.internet_message_id == "<MID-456@x>"      # data.message_id
    # distintos entre sí: no hay sustitución
    assert len({ev.provider_event_id, ev.provider_email_id, ev.internet_message_id}) == 3


def test_el_provider_event_id_viene_de_la_cabecera_no_del_cuerpo():
    raw = _payload_received(email_id="deberia-ser-email")
    _, ev = verify_and_normalize(raw, _firmar(raw, msg_id="msg_header"), _SECRET)
    assert ev.provider_event_id == "msg_header"
    assert ev.provider_event_id != ev.provider_email_id


# ────────────────────── metadata no confiable / adjuntos ──────────────────────

def test_metadata_no_confiable_se_marca_pero_no_enruta():
    raw = _payload_received()
    _, ev = verify_and_normalize(raw, _firmar(raw), _SECRET)
    assert ev.untrusted_from == "proveedor@ejemplo.com"
    assert ev.untrusted_subject == "Factura de prueba"
    # el routing usa data.to; from/subject no son autoridad
    assert ev.recipients == ("pixdea-tok@inbox.tribuu.ai",)


def test_recipients_vienen_de_data_to_no_de_received_for():
    raw = _payload_received(to=("autoridad@inbox.tribuu.ai",),
                            received_for=("traza-distinta@inbox.tribuu.ai",))
    _, ev = verify_and_normalize(raw, _firmar(raw), _SECRET)
    assert ev.recipients == ("autoridad@inbox.tribuu.ai",)
    assert ev.trace_received_for == ("traza-distinta@inbox.tribuu.ai",)
    # received_for NUNCA entra en recipients
    assert "traza-distinta@inbox.tribuu.ai" not in ev.recipients


def test_sin_to_no_hace_fallback_a_received_for():
    raw = json.dumps({"type": "email.received",
                      "data": {"email_id": "e1",
                               "received_for": ["a@inbox.tribuu.ai"]}}).encode()
    with pytest.raises(EventParseError):
        verify_and_normalize(raw, _firmar(raw), _SECRET)


def test_adjuntos_solo_metadata_sin_bytes():
    adj = [{"id": "att_1", "filename": "factura.pdf", "content_type": "application/pdf",
            "content_disposition": "attachment", "content_id": None}]
    raw = _payload_received(attachments=adj)
    _, ev = verify_and_normalize(raw, _firmar(raw), _SECRET)
    assert len(ev.attachments) == 1
    a = ev.attachments[0]
    assert a.filename == "factura.pdf" and a.provider_attachment_id == "att_1"
    # el modelo es SOLO metadata: ningún campo transporta bytes/contenido
    campos = set(a.__dataclass_fields__)
    assert not {"content", "data", "bytes", "payload", "body"} & campos
    assert not any("byte" in f for f in campos)


# ─────────────────────────── normalización recipient ─────────────────────────

@pytest.mark.parametrize(("entrada", "esperado"), [
    ("  px-tok@inbox.tribuu.ai  ", "px-tok@inbox.tribuu.ai"),        # trim
    ("px-tok@INBOX.TRIBUU.AI", "px-tok@inbox.tribuu.ai"),            # dominio a minúsculas
    ("PX-Tok@inbox.tribuu.ai", "PX-Tok@inbox.tribuu.ai"),           # local se respeta
])
def test_normalizacion_conservadora(entrada, esperado):
    assert normalize_recipient(entrada) == esperado


@pytest.mark.parametrize("malo", ["", "   ", "sinarroba", "a@@b", "@dominio.com",
                                   "local@", "dos@arrobas@x.com"])
def test_direcciones_invalidas_se_rechazan(malo):
    assert normalize_recipient(malo) is None


# ─────────────────────────── routing multi-tenant (DB) ───────────────────────

_CLI_TRANSITORIOS = ("unexpected status 401", "unexpected login role status 401",
                     "LegacyDbConfigConnectTempRoleError", "LegacyDbConfigLoginRoleStatusError",
                     "unexpected status 5", "cli_login_postgres")


def _limpiar_inboxes(admin_sql, company_ids, intentos=4):
    ids = ", ".join(f"'{c}'" for c in company_ids)
    sql = f"delete from inbound.company_inboxes where company_id in ({ids})"
    ultimo = None
    for i in range(intentos):
        try:
            admin_sql(sql)
            return
        except Exception as exc:            # noqa: BLE001
            if not any(t in str(exc) for t in _CLI_TRANSITORIOS):
                raise
            ultimo = str(exc)[:120]
            time.sleep(1 + i)
    raise AssertionError(f"cleanup de inboxes falló por transporte del CLI: {ultimo}")


@pytest.fixture
def limpio(admin_sql, user_a, user_b):
    # Limpieza determinista antes y después, resiliente a fallos transitorios
    # del CLI, para no dejar un active inbox que rompa el siguiente test.
    companies = (user_a.company_id, user_b.company_id)
    _limpiar_inboxes(admin_sql, companies)
    yield
    _limpiar_inboxes(admin_sql, companies)


def _buzon(pool, settings, user, prefijo="px"):
    with fiscal_transaction(pool, settings, user.identity) as conn:
        return conn.execute(
            "insert into inbound.company_inboxes (company_id, display_prefix, local_token) "
            "values (%s,%s,%s) returning address",
            (user.company_id, prefijo, generar_routing_token()),
        ).fetchone()["address"]


def test_recipient_activo_resuelve_company_correcta(pool, settings, user_a, limpio):
    addr = _buzon(pool, settings, user_a)
    r = resolve_recipient(pool, settings, addr)
    assert r.resolution is RecipientResolution.ACTIVE_RESOLVED
    assert r.company_id == user_a.company_id
    assert r.inbox_id


def test_recipient_desconocido_fail_closed(pool, settings):
    r = resolve_recipient(pool, settings, f"nadie-{'a'*20}@inbox.tribuu.ai")
    assert r.resolution is RecipientResolution.UNKNOWN_RECIPIENT
    assert r.company_id is None and r.inbox_id is None


def test_recipient_deshabilitado_fail_closed(pool, settings, user_a, limpio):
    addr = _buzon(pool, settings, user_a)
    with fiscal_transaction(pool, settings, user_a.identity) as conn:
        conn.execute("update inbound.company_inboxes set status='disabled', "
                     "disabled_at=now(), disabled_reason='revoked' where company_id=%s",
                     (user_a.company_id,))
    r = resolve_recipient(pool, settings, addr)
    # deshabilitado colapsa a UNKNOWN: no se filtra que existió
    assert r.resolution is RecipientResolution.UNKNOWN_RECIPIENT
    assert r.company_id is None


def test_recipient_invalido_no_consulta_base(pool, settings):
    r = resolve_recipient(pool, settings, "  ")
    assert r.resolution is RecipientResolution.INVALID_RECIPIENT
    assert r.company_id is None


def test_multi_recipient_dos_companies_aisladas(pool, settings, user_a, user_b, limpio):
    aa = _buzon(pool, settings, user_a, "empresaa")
    bb = _buzon(pool, settings, user_b, "empresab")
    ev_raw = _payload_received(to=(aa, bb))
    _, ev = verify_and_normalize(ev_raw, _firmar(ev_raw), _SECRET)
    res = route_event(pool, settings, ev)
    por_addr = {r.recipient: r for r in res}
    assert por_addr[aa].company_id == user_a.company_id
    assert por_addr[bb].company_id == user_b.company_id
    assert por_addr[aa].company_id != por_addr[bb].company_id


def test_valido_mas_desconocido_cada_uno_aislado(pool, settings, user_a, limpio):
    aa = _buzon(pool, settings, user_a)
    desconocido = f"nadie-{'z'*20}@inbox.tribuu.ai"
    ev_raw = _payload_received(to=(aa, desconocido))
    _, ev = verify_and_normalize(ev_raw, _firmar(ev_raw), _SECRET)
    res = route_event(pool, settings, ev)
    assert res[0].resolution is RecipientResolution.ACTIVE_RESOLVED
    assert res[0].company_id == user_a.company_id
    assert res[1].resolution is RecipientResolution.UNKNOWN_RECIPIENT


def test_lookup_fallido_no_hereda_contexto_previo(pool, settings, user_a, user_b, limpio):
    aa = _buzon(pool, settings, user_a)
    # resolver A (éxito), luego desconocido: el desconocido NO debe heredar A
    r_ok = resolve_recipient(pool, settings, aa)
    r_no = resolve_recipient(pool, settings, f"nadie-{'q'*20}@inbox.tribuu.ai")
    assert r_ok.company_id == user_a.company_id
    assert r_no.resolution is RecipientResolution.UNKNOWN_RECIPIENT
    assert r_no.company_id is None


# ─────────────────────────── seguridad / frontera B3 ─────────────────────────

def test_el_router_no_acepta_company_id_de_fuera():
    # la firma de resolve_recipient/route_event NO tiene parámetro company_id/inbox_id
    import inspect
    for fn in (resolve_recipient, route_event):
        params = set(inspect.signature(fn).parameters)
        assert "company_id" not in params
        assert "inbox_id" not in params


def test_el_adaptador_no_importa_c2_ni_storage():
    import ast
    import app.inbound.resend_adapter as mod
    import app.inbound.routing as rt
    for m in (mod, rt):
        arbol = ast.parse(open(m.__file__, encoding="utf-8").read())
        imports = set()
        for n in ast.walk(arbol):
            if isinstance(n, ast.ImportFrom) and n.module:
                imports.add(n.module)
            elif isinstance(n, ast.Import):
                imports.update(a.name for a in n.names)
        prohibidos = {"app.fiscal.ingestion", "app.fiscal.persistence",
                      "app.fiscal.parser", "boto3", "app.fiscal"}
        assert not (imports & prohibidos), f"{m.__name__} importa {imports & prohibidos}"


def test_c4b2_no_agrega_endpoint_http():
    import ast
    arbol = ast.parse(open("app/main.py", encoding="utf-8").read())
    fuente = open("app/main.py", encoding="utf-8").read().lower()
    assert "resend" not in fuente and "webhooks/" not in fuente
    assert "inbound" not in fuente


# ═════════════════════════════════════════════════════════════════════════════
# HIGH · autoridad de routing = data.to (received_for jamás autoriza, ADR-049)
# ═════════════════════════════════════════════════════════════════════════════

def test_attack_received_for_anade_tenant_ajeno(pool, settings, user_a, user_b, limpio):
    """to=[A], received_for=[A,B] con B de OTRO tenant.
    Solo A se rutea; B jamás se intenta; una sola transacción tenant."""
    aa = _buzon(pool, settings, user_a, "empresaa")
    bb = _buzon(pool, settings, user_b, "empresab")   # existe y es de B
    raw = _payload_received(to=(aa,), received_for=(aa, bb))
    _, ev = verify_and_normalize(raw, _firmar(raw), _SECRET)
    assert ev.recipients == (aa,)                     # B no entra en recipients
    assert bb in ev.trace_received_for                # B queda solo como traza
    res = route_event(pool, settings, ev)
    assert len(res) == 1                              # UNA sola resolución
    assert res[0].recipient == aa
    assert res[0].company_id == user_a.company_id
    # B jamás obtuvo contexto/company por este evento
    assert all(r.company_id != user_b.company_id for r in res)


def test_trace_only_victim_no_obtiene_contexto(pool, settings, user_a, user_b, limpio):
    """to=[A], received_for=[B]. Solo A se considera; B nunca se resuelve."""
    aa = _buzon(pool, settings, user_a, "empresaa")
    bb = _buzon(pool, settings, user_b, "empresab")
    raw = _payload_received(to=(aa,), received_for=(bb,))
    _, ev = verify_and_normalize(raw, _firmar(raw), _SECRET)
    assert ev.recipients == (aa,)
    res = route_event(pool, settings, ev)
    assert len(res) == 1 and res[0].company_id == user_a.company_id
    assert all(r.company_id != user_b.company_id for r in res)


def test_missing_to_con_received_for_poblado_fail_closed(pool, settings, user_a, limpio):
    """to=[] / ausente, received_for=[A]. FAIL CLOSED: A no se rutea, sin fallback."""
    aa = _buzon(pool, settings, user_a)
    raw = json.dumps({"type": "email.received",
                      "data": {"email_id": "e1", "to": [],
                               "received_for": [aa]}}).encode()
    with pytest.raises(EventParseError):
        verify_and_normalize(raw, _firmar(raw), _SECRET)


def test_multi_recipient_to_misma_company(pool, settings, user_a, user_b, limpio):
    """to=[A1, A2] de la MISMA company: ambos resuelven a esa company.
    (Un buzón activo por empresa, así que A2 = reenvío a la misma dirección.)"""
    aa = _buzon(pool, settings, user_a, "empresaa")
    raw = _payload_received(to=(aa, aa))
    _, ev = verify_and_normalize(raw, _firmar(raw), _SECRET)
    res = route_event(pool, settings, ev)
    assert len(res) == 2
    assert all(r.resolution is RecipientResolution.ACTIVE_RESOLVED for r in res)
    assert {r.company_id for r in res} == {user_a.company_id}


def test_matriz_malformed_mas_valido(pool, settings, user_a, limpio):
    """to=[inválido, A]: el inválido no consulta base, A resuelve; aislados."""
    aa = _buzon(pool, settings, user_a)
    raw = _payload_received(to=("no-es-direccion", aa))
    _, ev = verify_and_normalize(raw, _firmar(raw), _SECRET)
    res = route_event(pool, settings, ev)
    assert res[0].resolution is RecipientResolution.INVALID_RECIPIENT
    assert res[1].resolution is RecipientResolution.ACTIVE_RESOLVED
    assert res[1].company_id == user_a.company_id


def test_matriz_fallo_primero_luego_exito_sin_contaminar(pool, settings, user_a, limpio):
    """to=[desconocido, A]: el fallo previo no deja contexto que herede A."""
    aa = _buzon(pool, settings, user_a)
    raw = _payload_received(to=(f"nadie-{'k'*20}@inbox.tribuu.ai", aa))
    _, ev = verify_and_normalize(raw, _firmar(raw), _SECRET)
    res = route_event(pool, settings, ev)
    assert res[0].resolution is RecipientResolution.UNKNOWN_RECIPIENT
    assert res[0].company_id is None
    assert res[1].resolution is RecipientResolution.ACTIVE_RESOLVED
    assert res[1].company_id == user_a.company_id
