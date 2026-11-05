"""Token de enrutamiento del Buzon Tribuu (ADR-048).

CSPRNG puro. El alfabeto coincide EXACTAMENTE con el CHECK de la base
(`[a-z2-7]`, base32 minuscula) y la longitud fija de 20 caracteres da
20 x 5 = 100 bits efectivos de entropia — por encima del minimo de 80 bits
que ADR-046/048 exigen.

El token JAMAS deriva de company_id, del nombre de la empresa ni de ningun
hash determinista: cada llamada es aleatoriedad criptografica fresca
(`secrets`). La direccion canonica la genera la BASE DE DATOS
(columna generated); aqui solo nace el token.
"""

import secrets

#: Debe coincidir con company_inboxes_token_format: '^[a-z2-7]{16,}$'.
ALFABETO_TOKEN = "abcdefghijklmnopqrstuvwxyz234567"

#: 20 caracteres x 5 bits = 100 bits efectivos.
LONGITUD_TOKEN = 20


def generar_routing_token() -> str:
    """Token CSPRNG para la parte local del Buzon Tribuu."""
    return "".join(secrets.choice(ALFABETO_TOKEN) for _ in range(LONGITUD_TOKEN))
