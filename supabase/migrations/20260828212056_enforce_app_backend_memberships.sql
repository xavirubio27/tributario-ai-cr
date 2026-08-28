-- =============================================================================
-- Garantiza mecanicamente las memberships de app_backend
-- =============================================================================
-- HALLAZGO (auditoria de Checkpoint B, severidad MEDIUM)
--
--   20260825041622_create_app_backend_role.sql hace:
--
--       grant authenticated to app_backend;
--
--   Eso ANADE una pertenencia, pero no elimina ninguna otra. Si `app_backend`
--   recibiera -- por error, por un script externo o por una migracion futura --
--   la pertenencia a `service_role`, el estado seguiria pareciendo correcto
--   porque `authenticated` estaria presente.
--
--   Esta migracion convierte la intencion en garantia: revoca toda pertenencia
--   que no este en la lista permitida y despues asegura la que si lo esta.
--
-- POR QUE UNA MIGRACION NUEVA Y NO UNA EDICION
--   20260825041622 YA ESTA APLICADA en el proyecto de desarrollo (verificado con
--   `supabase migration list --linked`). Editarla fingiria que siempre tuvo esta
--   correccion y dejaria el historial mintiendo.
--
-- ALCANCE ACOTADO
--   Solo se tocan las pertenencias DE `app_backend`. No se revoca nada a PUBLIC
--   ni a ningun otro rol: eso podria romper `anon`, `authenticated` o el propio
--   PostgREST.
-- =============================================================================

do $$
declare
  v_allowed  constant text[] := array['authenticated'];
  v_role     constant text   := 'app_backend';
  v_extra    text;
begin
  if not exists (select 1 from pg_roles where rolname = v_role) then
    raise exception 'El rol % no existe; aplica antes 20260825041622.', v_role;
  end if;

  -- 1. Revocar toda pertenencia no permitida.
  for v_extra in
    select m.rolname
    from pg_auth_members am
    join pg_roles r on r.oid = am.member
    join pg_roles m on m.oid = am.roleid
    where r.rolname = v_role
      and m.rolname <> all (v_allowed)
  loop
    raise notice 'Revocando pertenencia inesperada %  ->  %', v_extra, v_role;
    execute format('revoke %I from %I', v_extra, v_role);
  end loop;

  -- 2. Asegurar la pertenencia deliberada (idempotente).
  if not exists (
    select 1
    from pg_auth_members am
    join pg_roles r on r.oid = am.member
    join pg_roles m on m.oid = am.roleid
    where r.rolname = v_role and m.rolname = 'authenticated'
  ) then
    execute format('grant authenticated to %I', v_role);
  end if;

  -- 3. VERIFICAR los atributos exigidos por ADR-012.
  --
  --    No se usa `alter role ... nosuperuser nobypassrls`: PostgreSQL exige el
  --    atributo SUPERUSER para modificar SUPERUSER o BYPASSRLS, y el rol que
  --    ejecuta las migraciones no lo tiene. Un intento falla con SQLSTATE 42501.
  --
  --    Estos atributos son invariantes de seguridad, no algo que una migracion
  --    deba poder "arreglar" en silencio: si estuvieran mal, alguien los cambio
  --    fuera de este flujo y hay que enterarse. Por eso se comprueban y se falla.
  perform 1;
end
$$;

do $$
declare
  r record;
begin
  select rolcanlogin, rolsuper, rolbypassrls, rolinherit, rolcreaterole, rolcreatedb
    into r
  from pg_roles where rolname = 'app_backend';

  if not r.rolcanlogin then raise exception 'app_backend debe tener LOGIN'; end if;
  if r.rolsuper       then raise exception 'app_backend NO debe ser SUPERUSER'; end if;
  if r.rolbypassrls   then raise exception 'app_backend NO debe tener BYPASSRLS'; end if;
  if r.rolinherit     then raise exception 'app_backend debe ser NOINHERIT'; end if;
  if r.rolcreaterole  then raise exception 'app_backend NO debe tener CREATEROLE'; end if;
  if r.rolcreatedb    then raise exception 'app_backend NO debe tener CREATEDB'; end if;
end
$$;

-- -----------------------------------------------------------------------------
-- Comprobacion final: la migracion falla si el estado no es el esperado.
-- -----------------------------------------------------------------------------
do $$
declare
  v_memberships text[];
begin
  select coalesce(array_agg(m.rolname order by m.rolname), array[]::text[])
    into v_memberships
  from pg_auth_members am
  join pg_roles r on r.oid = am.member
  join pg_roles m on m.oid = am.roleid
  where r.rolname = 'app_backend';

  if v_memberships is distinct from array['authenticated'] then
    raise exception 'app_backend tiene pertenencias inesperadas: %', v_memberships;
  end if;

  if pg_has_role('app_backend', 'service_role', 'MEMBER')
     or pg_has_role('app_backend', 'postgres', 'MEMBER')
     or pg_has_role('app_backend', 'supabase_admin', 'MEMBER') then
    raise exception 'app_backend puede asumir un rol privilegiado';
  end if;
end
$$;

comment on role app_backend is
  'Rol de conexion del backend FastAPI. NOINHERIT, NOBYPASSRLS, unica pertenencia: authenticated. Asume `authenticated` por transaccion (ADR-012).';
