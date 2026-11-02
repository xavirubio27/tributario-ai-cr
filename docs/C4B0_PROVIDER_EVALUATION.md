# C4-B0 — Evaluación de proveedores del canal de correo

**Estado: COMPLETADO (2026-11-02)** — batería experimental completa contra el
receptor estable en Render, con correos reales y evidencia descargada.
**Decisión aprobada: RESEND = proveedor entrante primario del MVP · MAILGUN =
fallback documentado y validado.** Resultados: **T1 PASS · T3 PASS · T4 PASS ·
T5 PASS · T6 PASS/observado · T7 PASS en recuperación/re-entrega · T8 PASS ·
T9 PASS.** Ambos proveedores demostraron: webhook real · firmas válidas ·
forwarding real de Gmail · routing por recipient · catch-all · fidelidad
byte-perfecta de XML/PDF/imagen · múltiples documentos en un correo ·
cuerpo-como-evidencia · adjuntos K1/K5/K10 · reintentos · recuperación tras
fallo. Matiz de T7: la retención de inbound ≥17 días y el `raw.download_url`
son hechos OBSERVADOS, no garantías contractuales (sin fuente contractual
localizada).

Decisiones que esta evaluación alimentaba (abiertas AL INICIAR C4-B0) y su
desenlace: **RESUELTAS por [ADR-047](DECISIONS.md#adr-047)** — proveedor de
correo entrante (Resend MVP · Mailgun fallback validado) y frontera de ACK
(captura durable síncrona antes del 2xx; procesamiento durable posterior).
**Siguen abiertas para C4-B / ADR-011**: vendor concreto de almacenamiento de
objetos · hosting definitivo (ADR-011) · mecanismo físico durable post-ACK ·
identidad/RLS de máquina y demás detalles físicos del canal. Marco:
[ADR-046](DECISIONS.md#adr-046).

Candidatos en cabeza a cabeza: **Resend** y **Mailgun**. SES, SendGrid y
Postmark quedan como alternativas documentadas, fuera de este spike.

---

## 1. Infraestructura del spike

El receptor/spike AUDITADO Y CANÓNICO (PASS de Codex) vive en el repositorio
desechable **`xavirubio27/tribuu-spike-inbound`**, commit
`5bed1b9b69368f720bdb05759c5c8325c42b3eb0`. Los helpers y la evidencia LOCALES
no canónicos pueden permanecer temporalmente fuera de Git hasta el teardown:
en particular, `spikes/c4b0-email-providers/token_de_prueba.py` es un **helper
local no canónico utilizado durante la experimentación** (no existe en el repo
desechable ni forma parte de su fuente de verdad); permanece local
temporalmente y se decidirá borrarlo o archivarlo durante el teardown. La
copia de trabajo local completa está ignorada por Git
(`/spikes/c4b0-email-providers/`). Aislado, solo stdlib, jamás importado por
producción. Dominios de prueba:
`rs-inbound.tribuu.ai` (Resend) y `mg-inbound.tribuu.ai` (Mailgun);
`inbox.tribuu.ai` NO se configura en este spike. Direcciones de prueba:
`pixdea-<token>@…` con token CSPRNG ≥ 80 bits generado localmente
(`token_de_prueba.py`); el token no se versiona.

Secretos SOLO en `spikes/c4b0-email-providers/.env.local` (ignorado):
`RESEND_API_KEY`, `RESEND_WEBHOOK_SECRET`, `MAILGUN_API_KEY`,
`MAILGUN_WEBHOOK_SIGNING_KEY`.

## 2. Acciones manuales de Xavier (prerequisito de todo lo demás)

1. Crear cuenta/proyecto en Resend y en Mailgun (planes de evaluación).
2. Registrar los subdominios de recepción en cada dashboard:
   `rs-inbound.tribuu.ai` y `mg-inbound.tribuu.ai`.
3. Configurar en el DNS de `tribuu.ai` los registros MX/TXT **exactamente como
   los dicte cada dashboard** (no se inventan valores; cada proveedor genera
   los suyos). Anotarlos aquí cuando existan.
4. Copiar `.env.example` → `.env.local` en el spike y rellenar las 4 claves.
5. Levantar `receiver.py` + un túnel público (p. ej.
   `cloudflared tunnel --url http://localhost:8787`) y registrar la URL del
   túnel como destino de ruta/webhook en cada dashboard:
   `<túnel>/webhooks/resend` y `<túnel>/webhooks/mailgun`.
6. Tener a mano un buzón personal real para el test de REENVÍO automático.

## 3. Matriz de correos (generada por `generar_fixtures.py`)

| # | Fixture | Contenido |
|---|---|---|
| A | `A-texto-plano.eml` | solo texto |
| B | `B-html.eml` | HTML + alternativa de texto |
| C | `C-cargo-html.eml` | cargo estilo SaaS SOLO en HTML, sin adjuntos |
| D | `D-xml.eml` | 1 XML |
| E | `E-xml-y-pdf.eml` | XML + PDF pareja |
| F | `F-pdf.eml` | solo PDF |
| G | `G-imagen.eml` | solo imagen |
| H | `H-xml-pdf-logo-inline.eml` | XML + PDF + logo inline (Content-ID) |
| I | `I-multiples.eml` | 2 XML + 2 PDF |
| J | `J-mime-enganoso.eml` | XML con nombre y MIME de PDF |
| K | `K1/K5/K10-*.eml` | adjuntos ~1 / ~5 / ~10 MB |

Todo sintético; `fixtures/MANIFEST.sha256` guarda la huella de cada adjunto
original para el test de fidelidad.

## 4. Tests y criterios PASS/FAIL

### T1 · Enrutamiento de tenant / destinatario del sobre — **CRITERIO DE CORTE**

Enviar un correo a un buzón personal normal y **reenviarlo automáticamente** a
`pixdea-<token>@<dominio-prueba>`. Registrar qué campo reporta el proveedor
como destinatario de la ENTREGA (semántica RCPT TO), si sobrevive al reenvío,
si es distinto de To/Cc visibles, y si es estable con catch-all.

- PASS: el destinatario del sobre reenviado es la dirección Tribuu, siempre.
- FAIL → **DESCALIFICADO**, sea cual sea su puntuación.

| Evidencia | Resend | Mailgun |
|---|---|---|
| Campo que representa la entrega real | `received_for` — **LISTA**: bajo reenvío trajo `[buzón, gmail]`; el enrutamiento debe seleccionar por dominio propio | `recipient` — escalar, confirmado en directo Y bajo reenvío |
| ¿Semántica RCPT TO? | **SÍ** — ambos saltos `Received` llevan `for <pixdea-…@eudelaepie.resend.app>` (el borde KumoMTA de Resend y la salida de Gmail) | **SÍ** — `Received[1]` de Gmail lleva `for <pixdea-…@sandbox….mailgun.org>` y el envelope-from llega reescrito por el reenviador (`…+caf_=…@gmail.com`) |
| ¿Sobrevive al reenvío automático? | **SÍ** — reenvío real Gmail→Resend, 2026-10-22 21:50 | **SÍ** — reenvío real Gmail→Mailgun, 2026-10-02 19:28 |
| ¿Distinto de To/Cc visibles? | **SÍ** — `headers.to` conservó `xavirubio27@gmail.com`; el buzón solo aparece en `received_for`/`Received` (nota: el campo `to` del OBJETO de la API vino normalizado al buzón, ≠ del header RFC `to`) | **SÍ** — `To` conservó `xavirubio27@gmail.com`; `recipient` = buzón |
| ¿Estable con catch-all? | **PASS** — T9 (ver «Evidencia T9 — CERRADO», final de §4) | **PASS** — T9 (misma sección; Route `catch_all()`) |
| **Veredicto T1 (reenvío/envelope-recipient)** | **PASS** ✅ (matiz de LISTA documentado arriba) | **PASS** ✅ |

**Evidencia T1-reenvío REAL Resend (2026-10-22 21:50, `email_id 2b8da95d-…`):**
el webhook NO llegó (el quick tunnel llevaba 6 días caducado — fallo nuestro,
tercero del mismo tipo), pero el correo quedó ALMACENADO en Resend y se
recuperó completo por API (`GET /emails/receiving` lista + `GET
/emails/receiving/{id}`): eso ya es evidencia fuerte de T7 — y en el listado
sigue visible el «T1 directo» perdido del 2026-10-05, es decir, **retención
≥ 17 días** del correo recibido. Evidencia del reenvío, toda independiente
del nombre del campo: `delivered-to: xavirubio27@gmail.com` (entró primero a
Gmail) · `x-forwarded-to`/`x-forwarded-for` presentes (listan ambos buzones
de reenvío configurados: Resend Y el sandbox de Mailgun) · cadena `Received`
con saltos google.com y entrega final `from mail-….google.com … by
receive.forge.rmta.net (KumoMTA) … for <pixdea-…@eudelaepie.resend.app>` ·
`headers.to` = el Gmail original · `from`/`return-path` = `xavier@pixdea.com`
· `message_id` de Outlook preservado · `authentication` spf/dkim/dmarc =
pass · `raw.download_url` presente (sin tratarlo aún como garantía
permanente). **Matiz importante para C4-B:** `received_for` es una LISTA y
bajo reenvío contenía también la dirección de Gmail; el enrutamiento de
Tribuu debe seleccionar la(s) dirección(es) del dominio de recepción propio
(o anclar en el `for <>` del borde), nunca «el primer elemento» a ciegas.
Pendiente del lado webhook: `svix-id`/firma de ESTE evento (podrían llegar
por reintento de Svix al actualizar la URL del endpoint). Sin evidencia del
envelope-from reescrito en las cabeceras parseadas de Resend (no expone
`x-envelope-from`; irrelevante para el veredicto, que es de destinatario).

**Comparación directa de los dos PASS:** ambos proveedores conservan el
destinatario del sobre bajo reenvío real de Gmail y conservan el `To`
original intacto — la invariante de ADR-046 es viable con los dos. Difieren
en forma: Mailgun lo entrega como escalar `recipient` dentro de un POST
autocontenido (mensaje completo inline, sin segunda llamada); Resend lo
entrega como lista `received_for` en una notificación mínima + objeto rico
por API (cabeceras completas, raw descargable, retención demostrada de
semanas). El fallo repetido de nuestros túneles favoreció accidentalmente a
Mailgun en T1 (su evidencia llegó por webhook) y a Resend en T7 (su
almacenamiento nos rescató dos veces).

**Evidencia T1-reenvío REAL Mailgun (2026-10-02 19:28, 29 732 bytes):**
`xavier@pixdea.com` (Outlook) → `xavirubio27@gmail.com` → filtro de Gmail →
buzón Mailgun. Cadena `Received` de 6 saltos: Outlook interno ×2 → recibido
**por `mx.google.com`** → interno de Google → `mail-dy2-f41.google.com …
for <pixdea-<test-token>@sandbox….mailgun.org>` → host de Mailgun.
`Delivered-To: xavirubio27@gmail.com` (entró primero al Gmail) ·
`X-Forwarded-To: <buzón>` · `X-Forwarded-For: <gmail> <buzón>` ·
`Return-Path: <xavier@pixdea.com>` (header original conservado) ·
`X-Envelope-From`/`sender` = `xavirubio27+caf_=pixdea-…=….mailgun.org@gmail.com`
— el sobre SMTP que llegó a Mailgun lo construyó el reenviador de Gmail ·
`To` original intacto (`xavirubio27@gmail.com`) · `From` = `xavier@pixdea.com`
· **firma HMAC VÁLIDA** · `Message-Id` original de Outlook preservado ·
`token` de Mailgun como id de entrega. Conclusión: **el enrutamiento de Tribuu
puede depender del `recipient` de Mailgun** — nunca del `To` ni del remitente,
que aquí apuntan a dos buzones distintos del de entrega.

**Intento de T1-directo Resend (2026-10-05) — NO RECIBIDO por fallo de NUESTRO
endpoint, no de Resend:** el correo «T1 Resend directo» se envió, pero el
quick tunnel de cloudflared había caducado tras ~3 días («Unauthorized:
Tunnel not found» en el log; la URL efímera no es recuperable), así que el
webhook `email.received` apuntaba a un endpoint muerto. Cero capturas de
Resend con contenido real hasta la fecha. Lección operativa ya evidenciada:
los quick tunnels no sirven ni para una evaluación multi-día — el hosting
real (C4-B0) es también un prerequisito del canal por esto mismo. Queda
pendiente: actualizar la URL del endpoint en el dashboard de Resend al túnel
nuevo y comprobar si los reintentos/el reenvío manual del evento entregan el
correo original — lo cual, de paso, se convierte en la primera evidencia real
de T7 (recuperación tras fallo del webhook) para Resend.

**Evidencia T1-directo Resend (2026-10-16 16:37, 471 bytes):** `email.received`
recibido en el túnel renovado. **Firma Svix VÁLIDA en vivo** con el `whsec_`
real (cabeceras `svix-id`/`svix-timestamp`/`svix-signature`; user-agent
`Svix-Webhooks`) — contrato Svix confirmado. Identificadores: `svix-id`
(`msg_3KnPDWVm…`, id de entrega para idempotencia) + `data.email_id` (UUID del
correo almacenado en Resend) + `data.message_id` (el RFC Message-Id original
de Outlook, preservado). Payload: JSON mínimo `{created_at, type, data}` con
`data` = {attachments[], bcc[], cc[], created_at, email_id, from, message_id,
**received_for[]**, subject, to[]} — en este envío directo `received_for` y
`to` coinciden por construcción (`pixdea-…@eudelaepie.resend.app`); el nombre
`received_for` apunta a semántica de sobre, pero SOLO el test de reenvío lo
demuestra. **El webhook NO trae cuerpo ni cabeceras del mensaje**: ni
body-plain/html ni `Received`/`Delivered-To`/`X-Forwarded-To` — recuperar
contenido exige llamada posterior a la API de Resend con `email_id` (la vida
útil de esa recuperación pasa a ser dato crítico de T7/T14 y pesa en la
decisión síncrono-vs-asíncrono). `attachments` llegó vacío (el correo no
traía); su representación con adjuntos reales queda para T4. **Diferencia
estructural frente a Mailgun:** Mailgun entrega el mensaje COMPLETO parseado
en el propio POST (formulario autocontenido, firma plana HMAC); Resend
entrega una notificación JSON mínima firmada por Svix que obliga a una
segunda llamada para el contenido — más ligera para capturar-antes-del-ACK,
pero añade una dependencia de recuperación posterior.

**Evidencia T5-API Resend (2026-10-16 17:59, correo de verificación de Gmail):**
la recuperación del contenido por API **funciona**: `GET
https://api.resend.com/emails/receiving/{email_id}` → 200 (descubierto
empíricamente; los otros candidatos probados devuelven error). Dos escollos
operativos reales documentados: (1) el WAF de Cloudflare delante de
`api.resend.com` bloquea el User-Agent por defecto de `urllib` con
`error code: 1010` — hace falta User-Agent propio; (2) el objeto devuelto es
RICO: `text`, `html`, `headers` (cabeceras COMPLETAS del mensaje:
`return-path`, `received`, `received-spf`, `authentication-results`, y
`x-ses-spam-verdict`/`x-ses-virus-verdict` — la recepción de Resend corre
sobre infraestructura AWS SES), `authentication` ya evaluada
(spf/dkim/dmarc = pass), `attachments`, `received_for`, `message_id`, y
**`raw.download_url`** en `cdn.resend.app` para el **MIME crudo completo** —
la garantía de fidelidad fuerte de ADR-046 parece alcanzable con Resend; la
VIDA ÚTIL de ese download_url y del propio email almacenado es ahora dato
crítico pendiente (T7/T14). Nota: el webhook notifica, la API entrega — las
cabeceras `Received`/`Delivered-To` ausentes del webhook SÍ están aquí.

**Intento de T1-reenvío Mailgun (2026-10-02 19:14) — INCONCLUSO, no es un FAIL
del proveedor:** el mensaje «T1 reenvío» capturado NO pasó por Gmail. Las
cabeceras lo demuestran: `From`/`sender`/`X-Envelope-From` =
`xavier@pixdea.com`, cadena `Received` 100 % Outlook/Exchange (3 saltos, cero
google.com), sin `Delivered-To` ni `X-Forwarded-To`, y `To` = la propia
dirección del buzón Mailgun — es decir, fue un envío DIRECTO desde Outlook al
buzón, que por construcción no puede separar sobre y cabecera. Lo que sí
aporta: segunda entrega directa real desde un dominio externo distinto
(pixdea.com), `recipient` de nuevo = buzón, firma HMAC VÁLIDA, y el `token`
de Mailgun como identificador de entrega junto al `Message-Id` original. El
criterio de corte sigue PENDIENTE: hay que enviar el correo **a
xavirubio27@gmail.com** (no al buzón) con el filtro de reenvío activo, y que
sea Gmail quien lo reenvíe.

**Evidencia T1-directo Mailgun (2026-10-02):** entrega real desde Gmail a
`pixdea-<token>@sandbox….mailgun.org` (NOTA: la ruta se montó sobre el dominio
sandbox de Mailgun, no sobre `mg-inbound.tribuu.ai` — válido para el spike,
anotar en escala/precio si el sandbox impone límites). Payload: formulario
`application/x-www-form-urlencoded` totalmente parseado (`recipient`, `sender`,
`from`, `subject`, `body-plain`, `body-html`, `stripped-*`,
`message-headers`, firma plana `timestamp/token/signature`). **Firma HMAC
verificada VÁLIDA en vivo** con la signing key real (desfase 48 s) — el
contrato publicado quedó confirmado para la variante de Routes. Falta el
test decisivo de reenvío automático y el de catch-all.

### T2 · Autenticación del webhook

Confirmar contra la documentación oficial (y en vivo): entradas de la firma,
algoritmo, marca temporal, protección de repetición, identificador de evento,
orden de verificación. Probar: firma válida · inválida · payload manipulado ·
marca temporal caducada. El spike ya verifica ambos esquemas en seco
(`firmas.py`); el contrato exacto se CONFIRMA en vivo antes de puntuar.

### T3 · Reintentos / idempotencia

Con `SPIKE_FAIL_MODE=1`: recibir, devolver 500, observar reintentos. Registrar
si el event-id se conserva entre reintentos, cadencia y número de intentos, y
si adjuntos/cuerpo siguen recuperables. Confirmar que reintento-de-la-misma-
entrega es distinguible de una entrega genuina nueva.

**Evidencia T3 — CERRADO (reintentos y recuperación, 2026-11-02):** un solo
correo real «TEST T3» con `SPIKE_FAIL_MODE=1` (500 intencional) y recuperación
a `0` sin tocar código.

*Resend/Svix:* 5 intentos del MISMO `svix-id` con el MISMO sha de cuerpo —
cadencia observada +4 s → +4.6 min → +26 min → +2 h 20 min; firma VÁLIDA en
todos; el receptor marcó `replay=true` en los reintentos (salvo tras el
reinicio, que vació el índice efímero: documentado). **HTTP 200 demostrado
DIRECTAMENTE por el proveedor**: `GET /webhooks/{id}/events` muestra el
mensaje pasando de `attempting` a **`success`** justo cuando la captura de
las 20:19:25 UTC registró la entrega. Identidad de evento ESTABLE entre
reintentos → el `svix-id` sirve como clave de idempotencia.

*Mailgun:* 6 intentos del MISMO correo — cadencia +10 → +10 → +15 → +30 →
+60 min; firma VÁLIDA en todos; **cada intento es un POST criptográficamente
fresco** (token/timestamp/firma nuevos → sha del POST distinto) mientras
`Message-Id`, subject, recipient y el sha del CONTENIDO permanecen idénticos
en los 6. **HTTP 200 demostrado DIRECTAMENTE por el proveedor**: su Events
API registra `attempt 1..5 · failed · code=500` y **`attempt 6 · delivered ·
code=200 · OK` (19:33:07 UTC)**. Conclusión FIRME:
**token/timestamp/firma cambian entre reintentos — el token identifica el
INTENTO y NO puede utilizarse como clave de idempotencia de mensaje.** La
correlación observacional CANDIDATA para Mailgun es `Message-Id` + recipient,
reforzada con procedencia y hash/contenido; C4-B debe definir el tratamiento
de `Message-Id` ausente, duplicado, repetido o no confiable. El experimento
demuestra estabilidad durante los reintentos observados, no una garantía
contractual de unicidad. (Refina, con evidencia, la regla genérica «mismo
provider_event_id = reintento» de ADR-046 para el caso Mailgun; la estrategia
y constraint físicas finales pertenecen a C4-B.)

*Detención de cadenas (complementaria):* tras los 200, cero intentos
posteriores en capturas y en los logs de ambos proveedores (ventana ≥ 47 min
en Mailgun; estado terminal `success` en Svix).

*T7 observado de regalo:* el cambio de variable reinició Render y **borró el
disco efímero** (las capturas de los intentos previos desaparecieron del
servidor); la evidencia sobrevivió porque se había descargado antes — la
regla «descargar antes de restart/deploy/teardown» queda demostrada en vivo,
no teórica. Ambos proveedores retuvieron y re-entregaron el mensaje completo
durante >2 h de fallo del receptor: la ventana de recuperación real supera
con holgura cualquier reinicio operativo razonable.

*Nota de seguridad del spike:* durante la exploración de la API de Resend se
volcó por error el `signing_secret` del webhook a la salida de sesión —
**rotarlo al cerrar el spike** (dashboard → webhook → nuevo secreto →
actualizar `RESEND_WEBHOOK_SECRET` en Render y `.env.local`).

### T4 · Fidelidad de adjuntos

SHA-256 del adjunto original (manifiesto) vs SHA-256 de los bytes tal y como
los entrega el proveedor, sin decode/re-encode. XML, PDF e imagen como mínimo.
MATCH/MISMATCH por pieza y por proveedor.

**Evidencia T4 en vivo (TEST D y TEST E, 2026-10-28, contra el receptor en
Render):** `factura.xml` (D) y `factura.xml`+`factura.pdf` (E), enviados desde
Outlook a ambos buzones. Resultado: **fidelidad byte a byte PERFECTA en los
cuatro casos** — Mailgun entrega los bytes dentro de su POST multipart (el
payload de cada parte coincide con el original y con `MANIFEST.sha256`);
Resend entrega metadata en el webhook y los bytes por `raw.download_url`
(MIME crudo; los adjuntos extraídos coinciden byte a byte y con el
manifiesto). Ni el orden ni el empaquetado del transporte (base64 del MIME en
Resend, multipart binario en Mailgun) alteraron el contenido; el MIME
DECLARADO sí varía entre proveedores (`application/xml` vs `text/xml`, y un
`.png` declarado `image/gif` por Resend) — más evidencia de que el router de
C4 debe clasificar por bytes, nunca por MIME declarado. **TEST E queda
registrado como DOS representaciones de UNA misma factura**: `factura.xml` +
`factura.pdf` llegaron en el mismo correo y NO deben interpretarse como dos
documentos económicos distintos — es exactamente el caso canónico de
conciliación de ADR-046; aquí solo se observa y documenta, sin implementar
conciliación ni lógica de producto. Regalo observacional para T6: la firma de
Outlook viajó como tercer adjunto (`image.png`, 1.1 MB) y **Resend la
discrimina limpiamente** (`content_disposition: inline` + `content_id`
presente, frente a `attachment`/`cid=None` en los adjuntos de negocio);
Mailgun la lista como una parte más del multipart.

**Evidencia T4 en vivo (TEST F, G y J, 2026-10-29/30):** `factura.pdf` (F),
`recibo.png` (G) y `disfrazado.pdf` (J — un XML con nombre y MIME de PDF)
llegaron **idénticos byte a byte** en ambos proveedores, con SHA igual al
manifiesto, sin modificación, normalización ni truncamiento. T6 quedó
observado de gratis: la firma de Outlook (`image.png`, 1.1 MB, PNG) y el
`recibo.png` de negocio (PNG, 73 B) son el mismo tipo físico y **Resend los
discrimina por `content_disposition` + `content_id`** (inline+cid la firma;
attachment+cid=null el negocio) — jamás por tipo de archivo; en el POST
multipart de Mailgun la disposición original no viaja en la parte (todo llega
como `form-data`) y la distinción habrá que buscarla en otros campos del
Route o en el raw. **Conclusión arquitectónica del TEST J, registrada como
vinculante para el router de C4:** ambos proveedores transportaron el archivo
disfrazado INTACTO declarándolo `application/pdf` mientras sus bytes son XML
(`<?xml…`), y ninguno lo «corrigió», reinterpretó ni transformó — por tanto
**ni el filename, ni la extensión, ni el MIME declarado son autoridad: la
clasificación física se basa en inspección/olfateo seguro de bytes**, que es
exactamente lo que ADR-046 ya congeló para el enrutador.

### T5 · Cuerpo / MIME

Qué expone realmente cada proveedor: ¿RFC822/MIME crudo? ¿HTML crudo o
normalizado? ¿texto plano? ¿estructura parseada? ¿endpoint de recuperación del
mensaje crudo y de adjuntos? Registrar la garantía de fidelidad que Tribuu
puede afirmar con verdad (ADR-046: «representación exacta entregada por el
proveedor»).

**Evidencia T5 en vivo (TEST C, solo cuerpo, 2026-10-30):** un cargo estilo
SaaS sin adjuntos (Proveedor=AWS · Referencia=SPK-001 · Total=USD 200.00 ·
Concepto=Servicio mensual) llegó con firma VÁLIDA a ambos y **los 4 datos de
negocio están presentes 4/4 en TODAS las representaciones**: Mailgun entrega
`body-plain`, `body-html` y además `stripped-text`/`stripped-html` (variantes
propias ya des-ruidadas) dentro del POST; Resend entrega `text` y `html` por
API más el RAW MIME completo descargable. Transformaciones observadas, que
confirman la redacción de ADR-046 («representación exacta entregada por el
proveedor», con procedencia): el `html` de Resend llegó EXPANDIDO a 1.48 MB
(materializa la imagen inline dentro del HTML) mientras el `body-html` de
Mailgun pesa 2 KB y referencia la imagen por cid — es decir, las
representaciones procesadas DIFIEREN entre proveedores y la fidelidad fuerte
vive en el raw; el texto plano varió solo en wrapping (175 vs 166 chars) sin
pérdida de datos. La firma de Outlook viajó como `image.png` inline y queda
conceptualmente separada del cuerpo de negocio (en Resend por
disposición/cid; en Mailgun por ser parte de archivo + por sus variantes
stripped). **Conclusión arquitectónica registrada:** Email Message ≠ Evidence
Item ≠ Economic/Fiscal Document — **el cuerpo puede ser evidencia aunque no
existan adjuntos**, y la premisa de ADR-046 de cuerpo-como-evidencia-de-
primera-clase queda TÉCNICAMENTE VALIDADA con ambos proveedores. Ningún valor
se convierte aún en gasto/ingreso/deducibilidad/tratamiento (capas 2 y 3
intactas); cero extracción productiva, cero IA — solo observación.

**Evidencia T4-multi (TEST I, 4 adjuntos, 2026-10-30):** `factura.xml` +
`factura.pdf` + `factura-b.xml` + `factura-b.pdf` en UN correo → **8/8 cruces
proveedor×archivo idénticos byte a byte** y con SHA igual al manifiesto.
Hallazgo sobre el ORDEN: ambos proveedores entregaron el mismo orden
(`b.pdf, b.xml, a.pdf, a.xml` tras la firma inline) pero DISTINTO del orden de
adjuntado — la reordenación vino del MIME de origen (Outlook), no de los
proveedores; conclusión registrada: **el orden de adjuntos NO es señal fiable
de conciliación**. Lectura conceptual del caso, sin implementar nada:
**1 Email Message → 5 Evidence Items** (4 de negocio + 1 inline de firma) →
**potencialmente 2 Economic Documents** (factura A = XML+PDF; factura B =
XML+PDF); 4 adjuntos ≠ 4 documentos económicos. Señales FUTURAS candidatas
para conciliar cada XML con su PDF (ninguna cerrada aún): la `Clave` reportada
del XML contra la clave extraída del PDF (canónica, alta confianza) ·
coincidencia emisor/fecha/moneda/total entre `reported_*` del XML y candidatos
extraídos del PDF · co-llegada en el mismo mensaje (acota candidatos, no
demuestra pareja) · afinidad de nombre de archivo (pista débil: el TEST J
demostró que los nombres mienten — jamás autoridad).

### T6 · Activos inline

Con el fixture H: cómo distingue cada proveedor adjunto de negocio, adjunto
inline (Content-ID/Content-Disposition) y contenido del cuerpo.

### T7 · Recuperación tras fallo del webhook

Con el receptor caído o en fallo: ¿se retiene el mensaje? ¿cuánto? ¿se puede
recuperar después (mensaje, cuerpo, adjuntos)? ¿reenvía solo?

### T8 · Tamaños y límites

Con K1/K5/K10: límite de mensaje entrante, de adjunto, comportamiento del
payload del webhook (¿inline o por referencia?) y de la descarga. Sin payloads
abusivos. La cota fiscal de C2 (8 MiB por XML) no se toca.

**Evidencia T8 — CERRADO (K1/K5/K10 contra Render, 2026-10-30):** fidelidad
byte a byte y SHA=manifiesto en los 6 cruces; firma VÁLIDA siempre; cero
truncamientos, cero rechazos del proveedor, cero 413 del receptor, cero
timeouts, cero errores de parsing, cero reintentos inesperados.

| Tamaño | Original | POST Mailgun | Webhook Resend | RAW Resend | Descargas |
|---|---|---|---|---|---|
| K1 | 1 048 769 B | 2 181 938 B | 854 B | 2 963 630 B | 0.8 / 0.9 s |
| K5 | 5 243 073 B | 6 376 280 B | 806 B | 8 703 205 B | 1.9 / 2.0 s |
| K10 | 10 481 857 B | 11 615 061 B | 809 B | 15 872 072 B | 2.6 / 3.1 s |

Overhead fijo del POST de Mailgun (firma Outlook 1.1 MB + campos):
**1 133 169–1 133 207 B, estable al byte** en los tres tamaños — tan estable
que la extrapolación K5→K10 acertó con error < 0.1 %. Margen real de K10
frente a `SPIKE_MAX_BODY_BYTES=16777216`: **5 162 155 B (~31 %)**. El webhook
de Resend es INSENSIBLE al tamaño (806–854 B constantes); su RAW crece ~4/3
por el base64 pero lo descargamos nosotros, no golpea al receptor.

**Conclusión sobre el límite de 16 MiB: SUFICIENTE para el MVP.** La cota
fiscal de C2 es 8 MiB por XML, y un adjunto de 10.5 MB —mayor que cualquier
comprobante real— deja 31 % de margen en el peor camino (el push completo de
Mailgun). Frontera conocida y registrada, no un defecto: VARIOS adjuntos
grandes en UN correo pueden exceder el tope por SUMA (p. ej. 2×10 MB ≈
22.7 MB → 413); para C4-B ya existe el desenlace de mensaje
`too_large`/`too_many_attachments` en el diseño. No se revisa el límite antes
de C4-B. Tiempos: crecimiento sublineal de descarga (3.1 s el RAW de 15.9 MB);
el receptor en Render Starter procesó K10 en-request sin inmutarse.

**Diferencia operativa consolidada tras T4/T5/T8:** Mailgun EMPUJA el
contenido completo al webhook (POST = adjuntos binarios + cuerpo + firma
plana; autocontenido, cero llamadas extra, pero el canal carga con los
bytes); Resend NOTIFICA con payload mínimo firmado por Svix (~800 B constante)
y exige recuperación posterior (objeto API + `raw.download_url`) — más liviano
para capturar-antes-del-ACK, con dependencia de una segunda llamada cuya vida
útil sigue pendiente (T7/T14).

### T9 · Catch-all / muchas direcciones virtuales

Un dominio, muchas direcciones `empresa-token@…` SIN buzón físico de pago por
empresa. Registrar límites de rutas/direcciones, restricciones de plan y
precio.

**Evidencia T9 — CERRADO (catch-all, 2026-10-30 18:38):** un correo a DOS
direcciones jamás aprovisionadas (`pixdea-<test-token-2>@…`) llegó a
AMBOS proveedores con firma VÁLIDA, replay false y el recipient/envelope
EXACTO de la dirección nueva. **Resend acepta cualquier parte local del
dominio entrante de forma NATIVA, sin configuración previa alguna** —
registrado explícitamente. **Mailgun también entregó sin configuración por
dirección, y la inspección de la Route por API explica por qué: la expresión
es `catch_all()`** con `forward(<receptor>) + stop()` — una sola Route de
dominio cubre todas las direcciones; no hubo que tocarla. Significado para el
modelo del Buzón Tribuu, registrado: **un dominio inbound → muchas
direcciones → una por empresa, SIN crear cuentas/buzones de correo por
empresa y sin aprovisionamiento por dirección en el proveedor** — crear un
Buzón Tribuu es solo generar el token y guardar el mapeo en nuestra base; la
«existencia» de la dirección es lógica, no física. Invariante reafirmada: la
dirección inbound es SOLO enrutamiento hacia la empresa — jamás autentica al
remitente (ADR-046). Límites de plan/precio por volumen de rutas quedan para
la columna de precio del scorecard.

## 5. Scorecard (total 100 %)

| Criterio | Peso | Resend | Mailgun | Ventaja |
|---|---|---|---|---|
| Enrutamiento de tenant / sobre (**CORTE**) | 25 % | **PASS** — `received_for` bajo reenvío real + `for <>`; matiz: es LISTA (seleccionar por dominio propio) | **PASS** — `recipient` escalar bajo reenvío real | empate (ambos PASS) |
| Seguridad del webhook | 15 % | Svix VÁLIDA en vivo en TODAS las entregas; v1 estricto | HMAC VÁLIDA en vivo en TODAS; **material de firma nuevo por intento** | Resend (identidad firmada estable) |
| Durabilidad / recuperación / reintentos | 15 % | T3: 5 intentos mismo `svix-id`, 200 directo vía API (`attempting→success`); retención inbound ≥17 días OBSERVADA; re-entrega tras >2 h de fallo | T3: 6 intentos, Events API con `code=500×5 → 200`, escalera 10/10/15/30/60 min; re-entrega tras >2 h | empate técnico; Resend + simple |
| Fidelidad de adjuntos + cuerpo | 15 % | **Byte-perfecta** en D/E/F/G/J/I/K1/K5/K10 vía RAW MIME; `text`/`html`/`headers` por API (html llega PROCESADO/expandido) | **Byte-perfecta** en los mismos tests, inline en el POST; `body-*` + `stripped-*` | empate en fidelidad; formas distintas |
| Escalabilidad / modelo de direcciones | 10 % | **Catch-all NATIVO** del dominio (T9, cero config) | Catch-all vía Route `catch_all()` (T9, una Route de dominio) | Resend (sin pieza de config) |
| Experiencia de desarrollo | 5 % | Notificación mínima + API rica; WAF exige User-Agent propio; endpoints descubiertos empíricamente | POST autocontenido trivial de consumir; formato formulario legacy | gusto; leve Resend por contrato JSON |
| Precio | 5 % | favorable HOY — **hecho externo sujeto a cambio, no puntuado experimentalmente** | plan free solo test; sandbox limitado | sin puntuar (externo) |
| Privacidad / región / datos | 5 % | inbound sobre AWS SES (observado); resto documental | — | sin concluir |
| Límites / encaje operativo | 5 % | webhook ~800 B CONSTANTE hasta K10; RAW hasta 15.9 MB bajado en 3.1 s | POST crece con el contenido (11.6 MB en K10); overhead fijo 1.13 MB estable al byte | Resend (el canal no carga los bytes) |
| **VEREDICTO** | | **GANADOR MVP** | **FALLBACK VALIDADO** | |

**Por qué Resend (decisión aprobada):** (1) misma fidelidad byte-perfecta que
Mailgun; (2) catch-all nativo sin configuración; (3) `svix-id` ESTABLE entre
reintentos; (4) idempotencia más simple (la identidad del mensaje viene del
proveedor); (5) webhook ~800 B aun con adjuntos de 10 MB; (6) metadata limpia
attachment-vs-inline (`content_disposition` + `content_id`); (7) menor
complejidad operativa; (8) reintentos y recuperación comprobados con 200
directo; (9) precio/retención actuales favorables — marcados como hechos
externos sujetos a cambio.

**Mailgun como fallback válido y probado.** Ventajas registradas: POST
autocontenido con adjuntos (cero segunda llamada) · `stripped-text`/
`stripped-html` · Events API con observabilidad excelente (nos dio el 200
directo) · routing por Routes potente. Costes arquitectónicos registrados:
el multipart grande llega AL webhook (el canal carga los bytes) ·
token/timestamp/firma cambian en cada retry · **el token NO es identidad del
mensaje y jamás sirve como clave de idempotencia de mensaje** · la correlación
observacional candidata es `Message-Id` + recipient reforzada con procedencia
y hash/contenido (estrategia final y tratamiento de `Message-Id`
ausente/duplicado/no confiable: C4-B) · el catch-all depende de una Route.

### Reglas registradas tras T1 (vinculantes para C4-B)

1. **`received_for` de Resend es una LISTA** y bajo reenvío puede contener
   tanto el buzón de Resend como la dirección Gmail del usuario. **Producción
   NO puede tomar `received_for[0]`**: el enrutamiento futuro debe
   seleccionar únicamente una dirección perteneciente al dominio de recepción
   controlado por Tribuu y resolverla contra un Buzón Tribuu ACTIVO; todo lo
   demás se ignora.
2. **Recuperación tardía observada en Resend**: un inbound de ≥17 días de
   antigüedad seguía listado y recuperable por API (hecho observado el
   2026-10-22; **no es todavía una garantía contractual** — el plazo real de
   retención queda para T7/T14).
3. **`raw.download_url` es capacidad observada**, no garantía: su
   expiración/vida útil queda pendiente de T7/T14.
4. **Los Quick Tunnels de Cloudflare quedan descartados** para esta
   evaluación: caducaron tres veces (2026-10-05, 2026-10-16, 2026-10-22),
   costaron dos entregas de webhook y no son adecuados para una evaluación
   multi-día. T3/T4/T5/T8/T9 requieren un endpoint estable ANTES de
   continuar.

## 6. Evaluación de almacenamiento de objetos (plan de seguimiento)

Hipótesis primaria del MVP: **Supabase Storage** (ya hay proyecto DEV);
comparación operativa contra Cloudflare R2 y AWS S3 sin aprovisionarlos.
A evaluar: buckets privados · APIs de subida/descarga · controles de acceso ·
URLs firmadas · límites de tamaño · precio y egreso · preservación de huella
(¿los bytes vuelven idénticos?) · patrón de acceso desde el backend ·
implicaciones de aislamiento por tenant. La elección NO se cierra en C4-B0-A.

## 7. Evaluación de hosting de FastAPI (plan de seguimiento)

Hipótesis primaria: **Render (Oregón), ~1 CPU / 2 GB** para el MVP; notas
comparativas de Railway y Google Cloud Run. A evaluar: webhook HTTPS público ·
always-on real · timeout de petición · límites de payload · región · modelo de
despliegue · health checks · réplicas/autoscaling · coste · secretos · logs ·
conectividad saliente a PostgreSQL (pooler de Supabase). Este punto desbloquea
además el ADR-011 (pendiente desde el Día 1). No se despliega nada todavía.

## 8. Matriz de decisión síncrono vs asíncrono — RESUELTO por ADR-047

> Desenlace: la regla quedó congelada en [ADR-047](DECISIONS.md#adr-047) —
> captura durable síncrona antes del ACK, procesamiento durable después; el
> mecanismo FÍSICO post-ACK queda para C4-B. La matriz siguiente se conserva
> como el método con el que se evaluó.

| Insumo (de T2/T3/T7/T8 y hosting) | Opción A (procesar → ACK) favorecida si… | Opción B (ACK → worker) favorecida si… |
|---|---|---|
| Timeout del webhook del proveedor | holgado (≥ ~30 s) | corto |
| Contrato de reintentos | reintentos generosos y espaciados | escasos o agresivos |
| Recuperación posterior del mensaje | limitada (hay que procesarlo ya) | robusta y larga |
| Vida de recuperación de adjuntos | corta | larga |
| Payload máximo vs coste de parseo | XML ≤ 8 MiB parsea en ms | adjuntos grandes/lentos |
| Requisito de recuperación ante caída | reintento del proveedor basta | exige cola propia |

Invariantes ya congeladas (ADR-046): captura durable ANTES del ACK; el
reintento del proveedor NO es la cola de Tribuu. Si la evidencia pide la
opción B, la cola/worker se declara explícitamente como infraestructura nueva.

## 9. Cuestiones que esta evaluación debía cerrar (desenlace al cierre)

CERRADAS: proveedor (Resend, ADR-047) · destinatario del sobre
(`received_for`/`recipient`, T1) · contrato de firma/reintentos/event-id (T3)
· fidelidad de adjuntos y cuerpo (T4/T5) · límites probados (T8) ·
síncrono-vs-asíncrono (regla en ADR-047). ABIERTAS para C4-B/ADR-011: almacén
de objetos · hosting · mecanismo físico de cola/worker post-ACK · precio a
escala pyme (hecho externo).

## 10. Endpoint estable del spike (propuesta — SIN desplegar, pendiente de aprobación)

**Qué se despliega:** únicamente el receptor del spike (`receiver.py` +
`firmas.py`) — stdlib puro, sin framework, sin base de datos, sin ningún
import de `backend/app`. Nada más del repositorio.

**Dónde:** Render, región **Oregón**, plan **Starter** (instancia pequeña
SIEMPRE ENCENDIDA, ~7 USD/mes, cancelable al cerrar C4-B0). El free tier se
descarta a conciencia: hiberna en reposo y el arranque en frío distorsionaría
exactamente lo que T3 quiere medir (cadencia de reintentos). La hipótesis de
~1 CPU / 2 GB sigue siendo para el MVP de PRODUCCIÓN (ADR-011), no para este
spike: el receptor sirve webhooks de KB con una fracción de eso.

**Aislamiento de producción (cómo NO se convierte en producción por accidente):**

- se despliega desde un **repositorio desechable separado** (p. ej.
  `tribuu-spike-inbound`, copia de `spikes/c4b0-email-providers/`), de modo
  que el repositorio del producto jamás adquiere cableado de despliegue;
- el servicio se llama explícitamente `tribuu-spike-inbound` y NO recibe
  ningún dominio de Tribuu: se usa la URL de Render tal cual;
- el servidor NO lleva `RESEND_API_KEY` ni `MAILGUN_API_KEY` (la
  recuperación por API sigue ejecutándose en local): en la nube solo viven
  los secretos de VERIFICACIÓN de webhooks;
- cero acceso a Supabase, al dominio fiscal o a cualquier dato real;
- desmantelamiento registrado como paso del cierre de C4-B0.

**Variables de entorno (en el dashboard de Render, jamás en Git):**
`RESEND_WEBHOOK_SECRET` · `MAILGUN_WEBHOOK_SIGNING_KEY` · `SPIKE_FAIL_MODE`
(para T3) · `SPIKE_READ_TOKEN` (para leer evidencia) ·
**`SPIKE_MAX_CONCURRENT_REQUESTS=2` (obligatorio: medición de auditoría —
~351 MB RSS con 2 slots de 16 MiB; Starter = 512 MB)** · `SPIKE_BIND_PUBLIC=1`
· `PORT` (lo inyecta Render).

**URLs estables esperadas:**

```
https://tribuu-spike-inbound.onrender.com/webhooks/resend
https://tribuu-spike-inbound.onrender.com/webhooks/mailgun
```

(el subdominio exacto lo confirma Render al crear el servicio).

**Logs/capturas:** el sistema de archivos de Render es efímero. stdout (logs
de Render) conserva ÚNICAMENTE metadata operacional — jamás el JSONL
completo, raw body, MIME ni adjuntos. La evidencia completa se descarga
autenticada vía `GET /capturas/<proveedor>.jsonl` y
`GET /cuerpos/<sha256>.bin` (Bearer `SPIKE_READ_TOKEN`, tiempo constante)
**antes de cualquier restart/deploy/teardown**.

**Cambios al receptor (implementados):** (1) host/puerto desde entorno
(`PORT` de Render, bind `0.0.0.0` solo cuando se define `SPIKE_BIND_PUBLIC=1`;
en local sigue `127.0.0.1:8787`); (2) una línea de **metadata operacional**
por entrega a stdout — stdout NO conserva el JSONL completo, raw body, MIME
ni adjuntos; (3) endpoints de lectura con token (`/capturas`, `/cuerpos`) +
`GET /salud` para el health check de Render.

**Coste/riesgo:** ~7 USD/mes temporales; superficie expuesta mínima (recibe
POSTs, verifica firmas, no ejecuta contenido, fixtures sintéticos); el riesgo
real es el olvido — por eso el desmantelamiento queda como paso de cierre.

**¿Sigue siendo Render la mejor opción para ESTE spike?** Sí, con una
**corrección registrada a la comparación inicial**: a octubre de 2026 Cloud
Run ya ofrece instancias continuas («Cloud Run instances»), así que NO debe
descartarse por scale-to-zero como se escribió al principio — esa objeción
era incorrecta como incapacidad técnica. Render se mantiene para ESTE spike
por **menor fricción operativa** (sin contenedor, sin gcloud, un script de
stdlib con start command directo), no porque Cloud Run no pueda permanecer
activo. Railway serviría igual pero no añade información. Render además
**duplica como evidencia temprana de la hipótesis de hosting de producción**
(ADR-011): timeout real de petición, límites de payload y comportamiento de
logs se observarán de gratis durante T3/T8. El estado del endpoint estable:
**aprobado y preparado; AÚN SIN DESPLEGAR — el deploy queda bloqueado hasta el
PASS de la re-auditoría de Codex.**

**Remediación post-auditoría (receptor v3, 2026-10-22):** Codex auditó el
receptor público (0 CRITICAL / 4 HIGH / 1 MEDIUM / 3 LOW — FAIL) y los ocho
hallazgos quedaron corregidos: firmas **fail-closed** (solo lo auténtico se
persiste; inválida → 401 con metadata mínima; en modo público el servicio no
arranca sin secretos) · soporte real de **multipart/form-data** de Mailgun
con stdlib y verificación previa a la persistencia · **límites HTTP
endurecidos** (`ThreadingHTTPServer`, timeout de socket, Content-Length
obligatorio con 411/400/413, `SPIKE_MAX_BODY_BYTES` default 16 MiB probado
contra K10 = 14 160 243 B) · `.gitignore` del spike **autosuficiente** y
demostrado con repo desechable real + escaneo de secretos sobre lo staged
(limpio) · **`GET /cuerpos/<sha256>.bin`** autenticado y allowlisted para
recuperar la evidencia cruda del disco efímero · **replay marking** efímero
por `svix-id`/token (observa, no descarta; no es idempotencia de producción)
· **access logs saneados** (sin query strings, sin Authorization; probado con
un secreto plantado en query) · **Svix endurecido** (solo etiqueta `v1`,
base64 estricto `validate=True`, formato `whsec_` validado, tiempo
constante). Batería local reproducible: **`tests_locales.py` — 35/35 OK**,
con secretos sintéticos y verificación de que nada sensible llega a stdout.

**Remediación 2.ª auditoría (receptor v4, 2026-10-27; 0C/0H/2M/4L — FAIL):**
los seis hallazgos restantes quedaron cerrados: **M1** — semáforo global
`SPIKE_MAX_CONCURRENT_REQUESTS` (exceso → 503 inmediato sin leer ni parsear;
`/salud` fuera del semáforo; el default inicial de 8 fue corregido a **2** en
la ronda final por la medición de memoria) y, para Mailgun,
extracción PRE-autenticación limitada a `timestamp/token/signature` (sin
hashear adjuntos ni extraer su metadata hasta firma válida); **M2** —
allowlist exacta de media types parseados (urlencoded y multipart/form-data;
`application/json` → 415 al no estar confirmado por la Route real), boundary
obligatorio y válido, terminador final exigido, MIME sin defectos,
exactamente UN timestamp/token/signature (duplicados o truncado → 400);
**L1** — `Transfer-Encoding` rechazado y `Content-Length` único obligatorio,
antes de leer el cuerpo; **L2** — formato `whsec_` estricto (verificación lo
exige; en modo público el arranque aborta si no cumple); **L3** — identidad
de replay = SHA-256 del token completo (en logs solo `mg:<12 hex del hash>`;
probado que dos tokens con el mismo prefijo de 8 no colisionan y que stdout
no contiene caracteres del token); **L4** — documentación corregida: stdout
= solo metadata operacional, la evidencia completa se descarga vía
`/capturas` y `/cuerpos` antes de restart/deploy/teardown. Batería:
**`tests_locales.py` — 57/57 OK**. El deploy sigue bloqueado hasta el PASS
de Codex.

**Remediación final (gate de memoria + 2 LOW, 2026-10-28):** Codex midió el
RSS real por slot de 16 MiB (1→231 MB, 2→351 MB, 3→490 MB, 4→567 MB,
8→953 MB; Render Starter = 512 MB) → **default de concurrencia corregido a
2** y el deployment en Render DEBE configurar `SPIKE_MAX_CONCURRENT_REQUESTS=2`
explícitamente (documentado en README/.env.example; jamás 3 ni 4). **LOW** —
Mailgun rechaza (400) `timestamp`/`token`/`signature` VACÍOS antes de
verificar el HMAC, y exige a la `signature` el formato del contrato
confirmado en vivo: exactamente 64 caracteres hexadecimales. **LOW** — las
frases residuales «cada registro va también a stdout»/«espejo a stdout»
fueron eliminadas: stdout contiene SOLO metadata operacional, y la evidencia
completa (JSONL, raw, adjuntos) se descarga vía `/capturas/...` y
`/cuerpos/...` antes de restart/deploy/teardown. Batería ampliada:
**65/65 OK**.

## 11. CIERRE DE C4-B0 (2026-11-02)

**Decisión de proveedor (aprobada por el arquitecto):** RESEND primario del
MVP · MAILGUN fallback documentado y validado — ver scorecard final (§5).

**Decisión síncrono-vs-asíncrono — REGLA CONGELADA:** *«Captura síncrona antes
del ACK; procesamiento asíncrono después del ACK.»* Tubería para Resend:

```
webhook verificado (Svix)
→ resolver recipient bajo el dominio entrante controlado por Tribuu
→ resolver Buzón Tribuu ACTIVO → company_id
→ idempotencia por identidad estable del evento (svix-id)
→ recuperar RAW/evidencia entregada por el proveedor
→ persistir intake/evidencia DURABLEMENTE en el ámbito de la empresa
→ COMMIT
→ solo entonces HTTP 2xx
```

Si la captura durable falla antes del commit → responder no-2xx y apoyarse en
el reintento del proveedor (cadencias y ventana >2 h medidas en T3). Tras la
captura durable, NADA de parseo/clasificación/conciliación/inteligencia
documental/procesamiento fiscal puede condicionar el ACK. No se introduce
Redis/SQS/etc. solo para recuperación de transporte en el MVP. **Prohibido**
usar BackgroundTasks no-durables de FastAPI como único mecanismo post-ACK: el
trabajo post-ACK debe tener estado durable y poder reanudarse tras un
reinicio. El worker/cola concreto queda para el diseño físico de C4-B.

**Invariantes de ADR-046 reafirmadas:** Email Message ≠ Evidence Item ≠
Economic/Fiscal Document · la dirección entrante es SOLO capacidad de
enrutamiento y JAMÁS autentica al remitente · el tenant deriva únicamente de
evento Resend verificado → recipient bajo dominio controlado → Buzón Tribuu
activo → company_id · From/Reply-To/subject/body siguen siendo NO confiables ·
el XML CR válido sigue yendo por la ingesta C2 existente (ningún segundo
parser/persistencia fiscal) · PDF/imagen/cuerpo siguen siendo evidencia que
alimentará D1-A/D2-A/D3-A tal como está diseñado · LLM ≠ Tax Engine.

**Aprovisionamiento del Buzón Tribuu (resultado T9):** un dominio entrante →
muchas direcciones lógicas → una por empresa → **cero buzones/cuentas físicas
por empresa**. Formato conceptual: `<prefijo-saneado>-<token>@inbox.tribuu.ai`
con token ≥80 bits CSPRNG, estable/rotable/desactivable. **No se adopta el
producto «Inboxes» de Resend como modelo de tenencia**: nuestro modelo es
enrutamiento a nivel de aplicación sobre el dominio entrante.

**Frontera de abstracción de proveedor para C4-B:** nada específico de Resend
esparcido por tablas del dominio fiscal/producto. Una frontera delgada que
preserve al menos: provider · provider_event_id · provider_message_id (si
existe) · recipient del sobre · marca temporal de recepción · procedencia ·
localizador del raw/evidencia · resultado/auditoría de la verificación de
firma. Sin sobre-generalizar a framework: Resend es la implementación
concreta del MVP; la portabilidad a Mailgun es beneficio secundario.

**Seguridad / limpieza pendiente del spike (explícito):**
- el `RESEND_WEBHOOK_SECRET` usado por el spike quedó EXPUESTO durante la
  experimentación y **NO puede reutilizarse en producción**;
- antes de dejar el webhook experimental activo a largo plazo: rotarlo o
  borrarlo;
- las credenciales de producción se generan NUEVAS y limpias (API keys,
  signing secrets, `SPIKE_READ_TOKEN` muere con el spike);
- el filesystem de Render quedó CONFIRMADO EMPÍRICAMENTE como efímero (el
  reinicio por cambio de variable borró las capturas): **ninguna evidencia de
  negocio aceptada puede depender de disco local** — almacenamiento durable
  obligatorio (ADR-046);
- teardown del spike (servicio Render + repo desechable + webhooks/Routes)
  sigue siendo paso obligatorio al terminar su utilidad.

**Hosting — evidencia, no selección:** el ADR-011 sigue ABIERTO. Lo que el
spike aporta es solo evidencia: el receptor estable en Render funcionó
durante toda la batería, el plan Starter soportó la carga probada (K10
incluido), y el filesystem quedó confirmado como efímero. Nada de esto
equivale a seleccionar Render para producción.

**Formalización:** las decisiones de este cierre quedaron congeladas en
[ADR-047](DECISIONS.md#adr-047) (Resend MVP + captura durable antes del ACK +
claves de idempotencia por proveedor + durabilidad).

**Abierto antes de C4-B (no bloquea este cierre):** rotación/borrado del
webhook del spike · dominio de producción `inbox.tribuu.ai` (DNS/MX en
Resend) · decisión de hosting de producción (ADR-011, con la evidencia de
Render ya recogida) ·
elección de almacenamiento de objetos (hipótesis Supabase Storage, evaluación
corta pendiente) · TTL contractual de `raw.download_url` y retención de
inbound (hoy solo OBSERVADOS) · implementación de la identidad/RLS de máquina
(ADR-046 → C4-B1) · mecanismo durable concreto del trabajo post-ACK.
