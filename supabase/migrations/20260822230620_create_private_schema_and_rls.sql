-- =============================================================================
-- Schema privado, helper de autorizacion y politicas RLS
-- =============================================================================
-- ADR-002: RLS es EL mecanismo de aislamiento multiempresa.
-- ADR-017: companies / company_memberships son datos de identidad y tenancy.
--
-- service_role NO se utiliza en ningun punto de este diseno.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 1. Schema privado
-- -----------------------------------------------------------------------------
-- El helper de autorizacion NO vive en `public`.
--
-- Motivo (documentacion oficial de Supabase sobre RLS):
--   "Never create security definer functions in exposed schemas, as they're
--    callable via the Data API with creator privileges."
--
-- `private` no figura entre los schemas expuestos por la Data API, de modo que
-- PostgREST no puede invocar esta funcion. La documentacion confirma que esto no
-- impide su uso desde una politica:
--   "You do not need to add your 'security definer' Functions to [exposed schemas
--    or search path] if you are using them in your Policies ... as long as you
--    explicitly use the schema inside RLS."
-- -----------------------------------------------------------------------------
create schema if not exists private;

comment on schema private is
  'Helpers internos de autorizacion. NO expuesto por la Data API. No anadir a exposed schemas.';

-- Permisos minimos sobre el schema.
revoke all   on schema private from public;
revoke all   on schema private from anon;
grant  usage on schema private to   authenticated;

-- -----------------------------------------------------------------------------
-- 2. Helper de pertenencia
-- -----------------------------------------------------------------------------
-- POR QUE SECURITY DEFINER:
--   Una politica sobre `companies` necesita consultar `company_memberships`.
--   Evaluar esa consulta bajo RLS dispararia la evaluacion de las politicas de
--   `company_memberships`, y de ahi recursion infinita. Una funcion SECURITY
--   DEFINER se ejecuta con los privilegios de su propietario, que no esta sujeto
--   a RLS, y rompe el ciclo.
--
--   IMPORTANTE: por ese mismo motivo NO debe activarse FORCE ROW LEVEL SECURITY
--   sobre company_memberships; anularia el bypass del propietario y devolveria la
--   recursion.
--
-- BUENAS PRACTICAS APLICADAS:
--   * search_path = ''      -> exigido por la documentacion oficial: sin fijarlo,
--                              un llamante puede redirigir nombres no cualificados
--                              a objetos maliciosos (escalada de privilegios).
--   * nombres schema-qualified en todo el cuerpo (consecuencia obligatoria).
--   * identidad derivada de auth.uid(), nunca de un parametro del cliente.
--   * stable  -> permite al planificador reutilizar el resultado por sentencia.
--   * permisos minimos -> solo `authenticated`.
-- -----------------------------------------------------------------------------
create or replace function private.is_company_member(p_company_id uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1
    from public.company_memberships m
    where m.company_id = p_company_id
      and m.user_id    = (select auth.uid())
  );
$$;

comment on function private.is_company_member(uuid) is
  'True si el usuario autenticado tiene membership en la empresa indicada. SECURITY DEFINER para evitar recursion RLS.';

revoke all     on function private.is_company_member(uuid) from public;
revoke all     on function private.is_company_member(uuid) from anon;
grant  execute on function private.is_company_member(uuid) to   authenticated;

-- -----------------------------------------------------------------------------
-- 3. Activacion de RLS
-- -----------------------------------------------------------------------------
alter table public.companies           enable row level security;
alter table public.company_memberships enable row level security;

-- -----------------------------------------------------------------------------
-- 4. Permisos de tabla (defensa en profundidad)
-- -----------------------------------------------------------------------------
-- Un acceso requiere GRANT *y* politica RLS que lo permita. Retiramos los GRANT
-- de escritura para que la denegacion no dependa unicamente de la ausencia de
-- politica.
--
-- La escritura ocurre exclusivamente a traves de public.create_company(), que es
-- SECURITY DEFINER y por tanto no se ve afectada por estos revoke.
-- -----------------------------------------------------------------------------
revoke all on table public.companies           from anon;
revoke all on table public.company_memberships from anon;

revoke insert, update, delete on table public.companies           from authenticated;
revoke insert, update, delete on table public.company_memberships from authenticated;

-- -----------------------------------------------------------------------------
-- 5. Politicas
-- -----------------------------------------------------------------------------
-- Solo SELECT. No existe politica de INSERT / UPDATE / DELETE en ninguna de las
-- dos tablas: RLS deniega por defecto, de modo que ningun cliente puede escribir
-- directamente y -- lo mas importante -- ningun usuario puede concederse a si
-- mismo una membership.
--
-- `(select auth.uid())` en subconsulta es el patron de rendimiento documentado:
-- el planificador ejecuta un initPlan y cachea el resultado por sentencia en
-- lugar de invocar la funcion una vez por fila.
-- -----------------------------------------------------------------------------

-- Una empresa es visible si el usuario tiene membership en ella.
create policy companies_select_members
  on public.companies
  for select
  to authenticated
  using ( private.is_company_member(id) );

-- Un usuario ve unicamente sus propias filas de membership.
-- Sin subconsulta a company_memberships: no hay recursion posible.
create policy company_memberships_select_own
  on public.company_memberships
  for select
  to authenticated
  using ( user_id = (select auth.uid()) );
