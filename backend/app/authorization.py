"""Roles de membresía y consulta de autorización.

FUENTE DE VERDAD — `public.company_memberships`

    El JWT identifica al usuario y nada más. La pertenencia a una empresa y el rol
    dentro de ella se consultan SIEMPRE en la base de datos, dentro del contexto
    transaccional de Checkpoint B.

    No se acepta como autoridad ningún `role`, `company_id` o `user_id` que llegue
    del navegador, de una cookie, del cuerpo de la petición, de la query string ni
    de un claim del token.

    Razón (ADR-015): un token es una fotografía firmada en el momento de su
    emisión. Si el rol viajara dentro, revocar un acceso o degradar a `viewer` no
    surtiría efecto hasta que el token expirase.

ALCANCE — deliberadamente pequeño

    Aquí solo se responde a dos preguntas:

        ¿pertenece este usuario a esta empresa?
        ¿con qué rol?

    NO hay matriz de permisos, ni motor de políticas, ni decoradores, ni ACLs, ni
    acciones tipo `invoice.delete`. No existen tablas fiscales todavía, así que
    cualquier permiso concreto sería inventado.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from psycopg import Connection


class CompanyRole(StrEnum):
    """Roles del MVP. Reflejan exactamente el CHECK de la base de datos.

    Semántica aprobada en ADR-015. Lo que cada rol podrá hacer sobre datos
    fiscales se concretará cuando esas tablas existan; hoy solo se establece el
    conjunto de roles.
    """

    OWNER = "owner"
    """Operaciones normales de la empresa; datos fiscales y administración de
    memberships cuando esa funcionalidad exista. No implica poder alterar datos
    que la arquitectura define como inmutables."""

    EDITOR = "editor"
    """Operar datos fiscales cuando existan. No administra propiedad de la empresa
    ni memberships sensibles."""

    VIEWER = "viewer"
    """Consultar datos fiscales y resultados cuando existan. No modifica datos
    fiscales ni administra memberships."""


@dataclass(frozen=True)
class CompanyMembership:
    """Pertenencia verificada contra la base de datos."""

    company_id: str
    user_id: str
    role: CompanyRole


def get_company_membership(conn: Connection, company_id: str) -> CompanyMembership | None:
    """Membresía del usuario **de esta conexión** en la empresa indicada.

    NO RECIBE `user_id` — DELIBERADAMENTE

        La identidad ya está establecida en la transacción que abrió el llamante
        (`user_transaction`, con una `AuthenticatedUser` verificada). Este helper
        no puede cambiarla, ni suplantar a otro usuario, porque no tiene por dónde
        recibir una identidad distinta.

        La fila que devuelve la elige RLS a partir de `auth.uid()`.

    `None` significa **sin autorización**. No existe rol por defecto: un usuario
    sin fila en `company_memberships` no es `viewer`, es nadie.
    """
    row = conn.execute(
        """
        select company_id::text as company_id,
               user_id::text    as user_id,
               role
        from public.company_memberships
        where company_id = %s
        """,
        (company_id,),
    ).fetchone()

    if row is None:
        return None

    return CompanyMembership(
        company_id=row["company_id"],
        user_id=row["user_id"],
        role=CompanyRole(row["role"]),
    )


def list_company_memberships(conn: Connection) -> list[CompanyMembership]:
    """Membresías visibles para el usuario de esta conexión. RLS decide cuáles.

    Tampoco recibe `user_id`: la identidad es la de la transacción.

    Permite que un mismo usuario tenga roles distintos en empresas distintas sin
    ningún tratamiento especial: son filas independientes.
    """
    rows = conn.execute(
        """
        select company_id::text as company_id,
               user_id::text    as user_id,
               role
        from public.company_memberships
        order by company_id
        """
    ).fetchall()

    return [
        CompanyMembership(
            company_id=r["company_id"], user_id=r["user_id"], role=CompanyRole(r["role"])
        )
        for r in rows
    ]
