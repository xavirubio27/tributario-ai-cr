-- =============================================================================
-- RPC: create_company
-- =============================================================================
-- PROBLEMA QUE RESUELVE
--   Al crear una empresa todavia no existe membership, luego ninguna politica RLS
--   puede autorizar la insercion. Es un huevo-y-gallina inherente al modelo.
--
-- SOLUCION
--   Un unico punto de entrada atomico que crea empresa + membership de owner en
--   la misma transaccion.
--
-- POR QUE ESTA FUNCION SI VIVE EN `public`
--   Debe ser invocable por el cliente a traves de la Data API (supabase.rpc()),
--   lo que exige un schema expuesto. Es lo contrario del helper de RLS
--   (private.is_company_member), al que el cliente nunca debe poder llamar.
--
-- CONFORMIDAD CON ADR-002
--   Esto NO es service_role. Es una elevacion acotada, server-side y auditable,
--   que sigue derivando la identidad del usuario autenticado. Es exactamente el
--   "camino separado, estrictamente controlado" que ADR-002 contempla.
--
-- CONTROLES DE SEGURIDAD
--   * search_path = ''            -> sin resolucion de nombres manipulable
--   * nombres schema-qualified    -> consecuencia obligatoria de lo anterior
--   * user_id desde auth.uid()    -> NUNCA desde un parametro del cliente:
--                                    es imposible crear una empresa a nombre de otro
--   * falla si no hay sesion      -> anon no puede llegar ni por accidente
--   * revoke a public y anon      -> solo `authenticated` puede ejecutarla
--   * atomica                     -> una sola transaccion; si falla la membership,
--                                    la empresa no queda huerfana
-- =============================================================================

create or replace function public.create_company(p_name text)
returns public.companies
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  v_user_id uuid := (select auth.uid());
  v_name    text := btrim(coalesce(p_name, ''));
  v_company public.companies;
begin
  -- Identidad: exclusivamente del contexto autenticado.
  if v_user_id is null then
    raise exception 'authentication required'
      using errcode = '28000';
  end if;

  -- Validacion de entrada (espejo del CHECK de la tabla, con error legible).
  if char_length(v_name) < 1 or char_length(v_name) > 200 then
    raise exception 'company name must be between 1 and 200 characters'
      using errcode = '22023';
  end if;

  insert into public.companies (name, created_by)
  values (v_name, v_user_id)
  returning * into v_company;

  insert into public.company_memberships (company_id, user_id, role)
  values (v_company.id, v_user_id, 'owner');

  return v_company;
end;
$$;

comment on function public.create_company(text) is
  'Crea una empresa y la membership de owner del usuario autenticado, atomicamente. Identidad derivada de auth.uid().';

-- Permisos minimos.
revoke all     on function public.create_company(text) from public;
revoke all     on function public.create_company(text) from anon;
grant  execute on function public.create_company(text) to   authenticated;
