"""Dependencias compartidas de la frontera HTTP.

`require_user` vivía en `main.py` cuando solo existía un endpoint de
diagnóstico. Al aparecer la primera ruta de producto pasa aquí, para que el
router no tenga que importar la aplicación —lo que crearía un ciclo— y para
que la puerta de identidad sea una sola, visible y compartida.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Header, HTTPException, Request, status

from app.auth import AuthenticatedUser, AuthError, extract_bearer_token


def require_user(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> AuthenticatedUser:
    """Identidad verificada, o 401.

    Es la única puerta de entrada de identidad al backend. Ningún endpoint debe
    aceptar un identificador de usuario por parámetro.
    """
    try:
        token = extract_bearer_token(authorization)
        return request.app.state.verifier.verify(token)
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
