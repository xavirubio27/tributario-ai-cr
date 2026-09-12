"""Frontera HTTP de producto.

Separada de `app/fiscal/`, que es el dominio. Aquí solo vive transporte:
recibir bytes, autenticar, traducir desenlaces tipados a HTTP. **Ninguna
regla fiscal.**
"""
