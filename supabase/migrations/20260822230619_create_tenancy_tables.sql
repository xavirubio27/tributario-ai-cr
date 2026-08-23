-- =============================================================================
-- Tenancy model: companies and company_memberships
-- =============================================================================
-- Estos datos son de IDENTIDAD, TENANCY y AUTORIZACION de la aplicacion.
-- NO son datos fiscales. Ver docs/DECISIONS.md, ADR-017.
--
-- Los datos fiscales futuros (invoices, tax_profiles, tax_calculations, ...)
-- quedan sujetos a ADR-001 y NO se modelan aqui.
--
-- Deliberadamente ausente en esta migracion: cualquier campo fiscal
-- (identificacion tributaria, regimen, etc.). Su formato y validacion exigen
-- fuente oficial verificada -> AI_INSTRUCTIONS.md, Regla 2.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- companies
-- -----------------------------------------------------------------------------
create table public.companies (
  id          uuid        primary key default gen_random_uuid(),
  name        text        not null,
  created_by  uuid        not null references auth.users (id) on delete restrict,
  created_at  timestamptz not null default now(),

  constraint companies_name_length_check
    check (char_length(btrim(name)) between 1 and 200)
);

comment on table public.companies is
  'Empresa (tenant). Unidad de aislamiento del sistema. Dato de identidad, no fiscal (ADR-017).';

comment on column public.companies.created_by is
  'Usuario que creo la empresa. ON DELETE RESTRICT: preserva la trazabilidad de creacion.';

-- -----------------------------------------------------------------------------
-- company_memberships
-- -----------------------------------------------------------------------------
-- Relacion N:M entre usuarios y empresas:
--   un usuario  -> varias empresas
--   una empresa -> varios usuarios
--
-- `role` se modela como text + CHECK en lugar de enum: ampliar un CHECK es DDL
-- corriente, mientras que ALTER TYPE ... ADD VALUE tiene restricciones dentro de
-- transacciones de migracion. Preparado para roles futuros sin construir todavia
-- un sistema de permisos complejo (ADR-015, parcialmente resuelto).
-- -----------------------------------------------------------------------------
create table public.company_memberships (
  id          uuid        primary key default gen_random_uuid(),
  company_id  uuid        not null references public.companies (id) on delete cascade,
  user_id     uuid        not null references auth.users (id)       on delete cascade,
  role        text        not null default 'owner',
  created_at  timestamptz not null default now(),

  constraint company_memberships_role_check
    check (role in ('owner')),

  constraint company_memberships_company_user_key
    unique (company_id, user_id)
);

comment on table public.company_memberships is
  'Pertenencia de un usuario a una empresa. Fuente de verdad de la autorizacion por tenant.';

-- -----------------------------------------------------------------------------
-- Indices para RLS
-- -----------------------------------------------------------------------------
-- La documentacion de Supabase es explicita: toda columna sobre la que filtre una
-- politica debe estar indexada, o la lectura degenera en sequential scan.
-- Solo la columna lider de un indice btree cuenta como indexada para el filtrado.
--
--   * company_memberships_company_user_key -> indice con company_id  como lider
--   * company_memberships_user_company_idx -> indice con user_id     como lider
--
-- Ambos ordenes quedan cubiertos.
-- -----------------------------------------------------------------------------
create index company_memberships_user_company_idx
  on public.company_memberships (user_id, company_id);
