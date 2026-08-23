-- =============================================================================
-- create_company: separacion API publica / implementacion privada
-- =============================================================================
-- MOTIVO
--   El Security Advisor de Supabase (lint 0029,
--   authenticated_security_definer_function_executable) senala que
--   public.create_company era SECURITY DEFINER en un schema expuesto y
--   ejecutable por `authenticated`, es decir invocable via
--   POST /rest/v1/rpc/create_company.
--
--   La documentacion admite tres remediaciones: revocar EXECUTE, pasar a
--   SECURITY INVOKER, o aceptarlo como intencional. Ninguna encajaba: el cliente
--   DEBE poder crear empresas, y la insercion DEBE ocurrir con privilegios
--   elevados porque no existe politica de INSERT (por diseno: nadie puede
--   concederse una membership).
--
-- PATRON APLICADO
--
--     PUBLIC API                       PRIVATE IMPLEMENTATION
--     public.create_company(text)  ->  private.create_company_impl(text)
--     SECURITY INVOKER                 SECURITY DEFINER
--     expuesto por Data API            NO expuesto por Data API
--     corre como el usuario            corre como el propietario
--
-- QUE MEJORA REALMENTE
--   La superficie expuesta (parseo de argumentos y cualquier validacion que se
--   anada despues al wrapper) pasa a ejecutarse SIN privilegios. Solo el nucleo
--   minimo, que no es direccionable desde fuera, corre como propietario.
--
--   Lo que NO cambia: un usuario autenticado sigue pudiendo provocar la ejecucion
--   de la logica privilegiada llamando al wrapper. Eso es inherente al caso de
--   uso y no es un defecto.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 1. Implementacion privada (SECURITY DEFINER)
-- -----------------------------------------------------------------------------
-- Conserva integramente las validaciones y garantias de la version anterior:
--   * identidad exclusivamente desde auth.uid()
--   * p_name es el UNICO parametro; jamas se acepta user_id del cliente
--   * company + membership de owner en una sola transaccion
--   * search_path vacio y nombres totalmente schema-qualified
-- -----------------------------------------------------------------------------
create or replace function private.create_company_impl(p_name text)
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

comment on function private.create_company_impl(text) is
  'Implementacion privilegiada de create_company. NO expuesta por la Data API. Identidad derivada de auth.uid().';

-- Permisos minimos.
--
-- POR QUE `authenticated` NECESITA EXECUTE AQUI:
--   El wrapper publico es SECURITY INVOKER, luego se ejecuta como el rol que
--   llama (`authenticated`). Para que pueda invocar esta funcion, ese rol
--   necesita EXECUTE sobre ella y USAGE sobre el schema `private` (concedido en
--   20260822230620). Es el minimo imprescindible para que el patron funcione.
--
--   Esto NO la hace alcanzable desde fuera: PostgREST solo enruta RPC hacia los
--   schemas expuestos, y `private` no figura en [api] schemas.
revoke all     on function private.create_company_impl(text) from public;
revoke all     on function private.create_company_impl(text) from anon;
grant  execute on function private.create_company_impl(text) to   authenticated;

-- -----------------------------------------------------------------------------
-- 2. API publica (SECURITY INVOKER)
-- -----------------------------------------------------------------------------
-- Unico RPC que el cliente invoca. Acepta solo p_name y delega.
-- Sin logica propia: cualquier validacion vive en la implementacion privada.
--
-- Se usa plpgsql en lugar de sql para devolver el tipo compuesto sin ambiguedad.
-- search_path = '' evita ademas el lint `function_search_path_mutable`.
-- -----------------------------------------------------------------------------
create or replace function public.create_company(p_name text)
returns public.companies
language plpgsql
volatile
security invoker
set search_path = ''
as $$
begin
  return private.create_company_impl(p_name);
end;
$$;

comment on function public.create_company(text) is
  'API publica para crear una empresa. SECURITY INVOKER: delega en private.create_company_impl().';

-- Se reafirman los permisos: create or replace conserva la ACL previa, pero la
-- intencion debe quedar declarada en la migracion.
revoke all     on function public.create_company(text) from public;
revoke all     on function public.create_company(text) from anon;
grant  execute on function public.create_company(text) to   authenticated;
