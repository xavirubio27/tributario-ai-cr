"""Aplicación FastAPI — identidad, RLS (ADR-012) y frontera fiscal.

ALCANCE
    Nació para demostrar una propiedad de seguridad: el camino completo
    JWT -> FastAPI -> PostgreSQL -> RLS, expuesto en `/diagnostics/identity`.

    Desde C3-B1 sirve además la primera API de producto —la subida manual de
    un comprobante—, que vive en `app/api/` y se monta aquí. Sigue sin haber
    API de impuestos ni CRUD de empresas.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from pydantic import BaseModel

from app.api.dependencies import require_user
from app.api.fiscal_documents import router as fiscal_documents_router
from app.auth import AuthenticatedUser, JwtVerifier
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
    title="Tribuu.ai — backend",
    version="0.1.0",
    lifespan=lifespan,
)

# Primera API de producto. El router no conoce esta aplicación: recibe el pool
# y los ajustes por `request.app.state`, igual que el endpoint de diagnóstico.
app.include_router(fiscal_documents_router)


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
