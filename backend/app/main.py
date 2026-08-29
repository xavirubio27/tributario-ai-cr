"""Aplicación FastAPI — foundation de identidad y RLS (ADR-012).

ALCANCE DELIBERADAMENTE MÍNIMO
    Este backend existe para demostrar una propiedad de seguridad, no para servir
    producto. No hay API de facturas, ni de impuestos, ni CRUD de empresas.

    El único endpoint es de diagnóstico: recorre el camino completo
    JWT -> FastAPI -> PostgreSQL -> RLS y devuelve lo que RLS deja ver.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from pydantic import BaseModel

from app.auth import AuthenticatedUser, AuthError, JwtVerifier, extract_bearer_token
from app.authorization import list_company_memberships
from app.config import get_settings
from app.db import create_pool, current_identity, user_transaction


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.settings = settings
    app.state.pool = create_pool(settings)
    app.state.verifier = JwtVerifier(settings)
    try:
        yield
    finally:
        app.state.pool.close()


app = FastAPI(
    title="Asistente Tributario IA — backend foundation",
    version="0.1.0",
    lifespan=lifespan,
)


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


class CompanyRef(BaseModel):
    id: str
    name: str


class MembershipRef(BaseModel):
    """Pertenencia resuelta por la base de datos, nunca por el cliente."""

    company_id: str
    role: str


class IdentityResponse(BaseModel):
    """Lo que PostgreSQL ve, no lo que el cliente afirma."""

    token_user_id: str
    db_user_id: str | None
    db_role: str
    companies: list[CompanyRef]
    memberships: list[MembershipRef]


@app.get("/health")
def health() -> dict[str, str]:
    """Sonda sin autenticación. No revela configuración ni identidad."""
    return {"status": "ok"}


@app.get("/diagnostics/identity", response_model=IdentityResponse)
def diagnostics_identity(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_user)],
) -> IdentityResponse:
    """Recorre JWT -> FastAPI -> PostgreSQL -> RLS y devuelve el resultado.

    `companies` no se filtra en la aplicación: se emite un SELECT sin cláusula de
    tenant y es RLS quien decide qué filas existen para este usuario. Esa es
    justamente la propiedad que este endpoint demuestra.

    `memberships` se resuelve consultando `public.company_memberships` (ADR-015).
    El endpoint NO acepta `role` ni `company_id` del cliente: no existe parámetro
    para ello, así que no hay forma de que el navegador se auto-declare `owner`.
    """
    settings = request.app.state.settings
    pool = request.app.state.pool

    # UNA sola transacción por request. La identidad se establece aquí, desde la
    # `AuthenticatedUser` verificada, y los helpers reciben la conexión ya
    # contextualizada: no pueden redefinirla ni suplantar a nadie.
    with user_transaction(pool, settings, user) as conn:
        identity = current_identity(conn)
        rows = conn.execute(
            "select id::text as id, name from public.companies order by created_at desc"
        ).fetchall()
        memberships = list_company_memberships(conn)

    return IdentityResponse(
        token_user_id=user.id,
        db_user_id=identity["user_id"],
        db_role=identity["db_role"],
        companies=[CompanyRef(id=r["id"], name=r["name"]) for r in rows],
        memberships=[
            MembershipRef(company_id=m.company_id, role=m.role.value) for m in memberships
        ],
    )
