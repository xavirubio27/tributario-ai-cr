-- =============================================================================
-- Fiscal Data Access Boundary  (ADR-020)
-- =============================================================================
-- UNA sola transicion arquitectonica: establecer la frontera de acceso a datos
-- fiscales. Se aplica atomicamente -- PostgreSQL ejecuta cada migracion en una
-- transaccion -- de modo que no puede quedar un estado a medias.
--
-- PROBLEMA QUE RESUELVE
--   FastAPI asume `authenticated` para operar tenancy. Pero `authenticated` es
--   tambien el rol con el que la Supabase Data API atiende a los usuarios. Si una
--   tabla fiscal recibiera privilegios para `authenticated` en un schema expuesto,
--   existiria el camino  Frontend -> Data API -> datos fiscales, incumpliendo
--   ADR-001 aunque RLS siguiera aislando entre contribuyentes.
--
-- LO QUE ESTABLECE
--   schema `fiscal`      no expuesto por la Data API
--   rol `fiscal_backend` NOLOGIN, NOBYPASSRLS, rol de ejecucion fiscal
--   app_backend          puede ASUMIR ambos roles, sin heredar ninguno
--
-- LO QUE NO HACE
--   * no crea ninguna tabla fiscal: eso corresponde a un checkpoint posterior
--   * no concede privilegios anticipados sobre objetos inexistentes
--   * no usa ALTER DEFAULT PRIVILEGES: ADR-020 exige grants explicitos por objeto
--   * no toca la configuracion de Exposed Schemas: `fiscal` queda fuera por no
--     figurar en [api] schemas, que sigue siendo ["public", "graphql_public"]
--   * no modifica 20260828212056 ni ninguna migracion historica ya aplicada
--
-- SOBRE 20260828212056
--   Aquella migracion exigia memberships exactas {authenticated}. Era correcto
--   para Checkpoint B. D1 cambia deliberadamente el estado esperado a
--   {authenticated, fiscal_backend} mediante ESTA migracion nueva.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 1. Rol de ejecucion fiscal
-- -----------------------------------------------------------------------------
-- Sin LOGIN: no es una credencial, no se conecta. Solo se asume desde
-- `app_backend` mediante SET LOCAL ROLE dentro de una transaccion.
--
-- Sin contrasena. Sin BYPASSRLS: la separacion de schema NO sustituye a RLS.
do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'fiscal_backend') then
    create role fiscal_backend
      nologin
      noinherit
      nosuperuser
      nobypassrls
      nocreatedb
      nocreaterole
      noreplication;
  end if;
end
$$;

comment on role fiscal_backend is
  'Rol de ejecucion de datos fiscales (ADR-020). NOLOGIN, NOBYPASSRLS. Asumido por app_backend con SET LOCAL ROLE.';

-- -----------------------------------------------------------------------------
-- 2. Membership: app_backend puede ASUMIR fiscal_backend, sin heredarlo
-- -----------------------------------------------------------------------------
-- Sintaxis explicita de PostgreSQL 16+ verificada en la fase D0. Se declara aunque
-- los valores coincidan con los predeterminados: una propiedad de seguridad no
-- debe depender de un default que podria cambiar.
grant fiscal_backend to app_backend with inherit false, set true, admin false;

-- -----------------------------------------------------------------------------
-- 3. Schema fiscal
-- -----------------------------------------------------------------------------
create schema if not exists fiscal;

comment on schema fiscal is
  'Datos fiscales del contribuyente (ADR-020). NO expuesto por la Data API. No anadir a [api] schemas.';

-- Endurecimiento explicito. PostgreSQL no concede USAGE sobre un schema nuevo a
-- PUBLIC por defecto, pero se revoca de forma expresa para que la intencion quede
-- escrita y una concesion futura por descuido sea visible en el diff.
revoke all on schema fiscal from public;
revoke all on schema fiscal from anon;
revoke all on schema fiscal from authenticated;
revoke all on schema fiscal from app_backend;

-- Unico rol con acceso al schema. USAGE, no CREATE: `fiscal_backend` opera dentro
-- del schema, no lo modifica.
grant usage on schema fiscal to fiscal_backend;

-- Deliberadamente NO se ejecuta:
--     alter default privileges in schema fiscal grant ... to fiscal_backend;
-- Concederia privilegios sobre tablas que aun no existen. ADR-020 exige que cada
-- objeto fiscal declare los suyos.

-- -----------------------------------------------------------------------------
-- 4. Acceso al helper de RLS
-- -----------------------------------------------------------------------------
-- Las futuras politicas fiscales reutilizaran `private.is_company_member`, que es
-- SECURITY DEFINER propiedad de postgres: encapsula la lectura de
-- `company_memberships`, de modo que `fiscal_backend` NO necesita SELECT sobre esa
-- tabla. Solo se le concede lo imprescindible para invocarla.
grant usage   on schema   private                          to fiscal_backend;
grant execute on function private.is_company_member(uuid)  to fiscal_backend;

-- -----------------------------------------------------------------------------
-- 5. Verificacion de invariantes -- la migracion falla si el estado no coincide
-- -----------------------------------------------------------------------------
do $$
declare
  r record;
  m record;
  v_memberships text[];
begin
  -- 5.1 Atributos de fiscal_backend
  select rolcanlogin, rolsuper, rolbypassrls, rolinherit, rolcreaterole, rolcreatedb
    into r from pg_roles where rolname = 'fiscal_backend';
  if r is null                then raise exception 'fiscal_backend no existe'; end if;
  if r.rolcanlogin            then raise exception 'fiscal_backend NO debe tener LOGIN'; end if;
  if r.rolsuper               then raise exception 'fiscal_backend NO debe ser SUPERUSER'; end if;
  if r.rolbypassrls           then raise exception 'fiscal_backend NO debe tener BYPASSRLS'; end if;
  if r.rolinherit             then raise exception 'fiscal_backend debe ser NOINHERIT'; end if;
  if r.rolcreaterole          then raise exception 'fiscal_backend NO debe tener CREATEROLE'; end if;
  if r.rolcreatedb            then raise exception 'fiscal_backend NO debe tener CREATEDB'; end if;

  -- 5.2 fiscal_backend no alcanza roles privilegiados
  if pg_has_role('fiscal_backend', 'authenticated',  'MEMBER')
     or pg_has_role('fiscal_backend', 'service_role',   'MEMBER')
     or pg_has_role('fiscal_backend', 'postgres',       'MEMBER')
     or pg_has_role('fiscal_backend', 'supabase_admin', 'MEMBER') then
    raise exception 'fiscal_backend puede asumir un rol que no le corresponde';
  end if;

  -- 5.3 Atributos de app_backend, sin cambios
  select rolcanlogin, rolsuper, rolbypassrls, rolinherit, rolcreaterole, rolcreatedb
    into r from pg_roles where rolname = 'app_backend';
  if not r.rolcanlogin then raise exception 'app_backend debe tener LOGIN'; end if;
  if r.rolsuper or r.rolbypassrls or r.rolinherit or r.rolcreaterole or r.rolcreatedb then
    raise exception 'app_backend tiene atributos incorrectos';
  end if;

  -- 5.4 Memberships exactas de app_backend
  select coalesce(array_agg(mm.rolname order by mm.rolname), array[]::text[])
    into v_memberships
  from pg_auth_members am
  join pg_roles rr on rr.oid = am.member
  join pg_roles mm on mm.oid = am.roleid
  where rr.rolname = 'app_backend';

  if v_memberships is distinct from array['authenticated', 'fiscal_backend'] then
    raise exception 'app_backend tiene memberships inesperadas: %', v_memberships;
  end if;

  -- 5.5 Opciones de cada membership: asumible, no heredable, sin admin
  for m in
    select mm.rolname, am.inherit_option, am.set_option, am.admin_option
    from pg_auth_members am
    join pg_roles rr on rr.oid = am.member
    join pg_roles mm on mm.oid = am.roleid
    where rr.rolname = 'app_backend'
  loop
    if m.inherit_option then
      raise exception 'membership % -> app_backend no debe heredar privilegios', m.rolname;
    end if;
    if not m.set_option then
      raise exception 'membership % -> app_backend debe permitir SET ROLE', m.rolname;
    end if;
    if m.admin_option then
      raise exception 'membership % -> app_backend no debe tener ADMIN', m.rolname;
    end if;
  end loop;

  -- 5.6 Acceso al schema fiscal
  if has_schema_privilege('public',        'fiscal', 'USAGE') then raise exception 'PUBLIC no debe tener USAGE sobre fiscal'; end if;
  if has_schema_privilege('anon',          'fiscal', 'USAGE') then raise exception 'anon no debe tener USAGE sobre fiscal'; end if;
  if has_schema_privilege('authenticated', 'fiscal', 'USAGE') then raise exception 'authenticated no debe tener USAGE sobre fiscal'; end if;
  if has_schema_privilege('app_backend',   'fiscal', 'USAGE') then raise exception 'app_backend no debe tener USAGE directo sobre fiscal'; end if;
  if not has_schema_privilege('fiscal_backend', 'fiscal', 'USAGE') then raise exception 'fiscal_backend necesita USAGE sobre fiscal'; end if;
  if has_schema_privilege('fiscal_backend', 'fiscal', 'CREATE') then raise exception 'fiscal_backend no debe poder crear objetos en fiscal'; end if;

  -- 5.7 Helper de RLS
  if not has_schema_privilege('fiscal_backend', 'private', 'USAGE') then
    raise exception 'fiscal_backend necesita USAGE sobre private';
  end if;
  if not has_function_privilege('fiscal_backend', 'private.is_company_member(uuid)', 'EXECUTE') then
    raise exception 'fiscal_backend necesita EXECUTE sobre private.is_company_member';
  end if;
  if has_table_privilege('fiscal_backend', 'public.company_memberships', 'SELECT') then
    raise exception 'fiscal_backend NO debe tener SELECT directo sobre company_memberships';
  end if;

  -- 5.8 El schema fiscal nace vacio
  if exists (select 1 from information_schema.tables where table_schema = 'fiscal') then
    raise exception 'El schema fiscal no debe contener tablas en esta migracion';
  end if;
end
$$;
