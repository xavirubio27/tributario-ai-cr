-- =============================================================================
-- Roles de membership: owner -> owner | editor | viewer
-- =============================================================================
-- Materializa la parte ya aprobada de ADR-015. NO introduce RBAC granular, ni
-- permisos por accion, ni roles personalizados, ni invitaciones.
--
-- QUE CAMBIA
--   Unicamente la restriccion CHECK de `company_memberships.role`.
--
--     antes:  CHECK (role = 'owner')
--     ahora:  CHECK (role IN ('owner','editor','viewer'))
--
-- QUE NO CAMBIA
--   * el tipo sigue siendo `text` + CHECK, no un enum -- ampliar un CHECK es DDL
--     corriente, mientras que ALTER TYPE ... ADD VALUE tiene restricciones dentro
--     de transacciones de migracion (decision del Dia 2, confirmada en ADR-015)
--   * el DEFAULT sigue siendo 'owner': quien crea una empresa la posee
--   * la relacion N:M user <-> company
--   * `user_id` y `company_id` de ninguna fila
--   * las politicas RLS existentes
--
-- QUE NO HACE
--   * no reasigna ningun rol: las 95 memberships existentes siguen siendo `owner`
--   * no crea memberships
--   * no crea invitaciones ni endpoints de administracion
--
-- La ampliacion es hacia arriba: todo valor que era valido lo sigue siendo, de
-- modo que ninguna fila existente puede violar la nueva restriccion.
-- =============================================================================

alter table public.company_memberships
  drop constraint if exists company_memberships_role_check;

alter table public.company_memberships
  add constraint company_memberships_role_check
  check (role in ('owner', 'editor', 'viewer'));

comment on column public.company_memberships.role is
  'Rol del usuario en la empresa: owner | editor | viewer (ADR-015). Fuente de verdad de la autorizacion; NUNCA se lee del JWT.';

-- -----------------------------------------------------------------------------
-- Comprobacion: la migracion falla si el estado no es el esperado.
-- -----------------------------------------------------------------------------
do $$
declare
  v_def text;
  v_invalidas bigint;
begin
  select pg_get_constraintdef(con.oid) into v_def
  from pg_constraint con
  join pg_class rel on rel.oid = con.conrelid
  where rel.relname = 'company_memberships'
    and con.conname = 'company_memberships_role_check';

  if v_def is null then
    raise exception 'No existe company_memberships_role_check tras la migracion';
  end if;

  foreach v_def in array array[v_def] loop
    if v_def not like '%owner%' or v_def not like '%editor%' or v_def not like '%viewer%' then
      raise exception 'El CHECK no admite los tres roles del MVP: %', v_def;
    end if;
  end loop;

  select count(*) into v_invalidas
  from public.company_memberships
  where role not in ('owner', 'editor', 'viewer');

  if v_invalidas > 0 then
    raise exception 'Hay % memberships con rol fuera del conjunto permitido', v_invalidas;
  end if;
end
$$;
