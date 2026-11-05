-- ============================================================================
-- C4-B1 · Registro de Buzones Tribuu e identidad de maquina inbound (ADR-048)
--
-- Crea:
--   * private.current_user_id()      helper de procedencia (SECURITY DEFINER)
--   * schema inbound                 backend-only, fuera de la Data API
--   * inbound.company_inboxes        Buzon Tribuu provider-agnostic
--   * triggers de guardia (lifecycle monotonico) y de linaje de rotacion
--   * rol inbound_backend            NOLOGIN/NOBYPASSRLS/NOINHERIT (ADR-020)
--   * contexto de maquina            enter_inbound_context + getters fail-closed
--   * politicas humanas (fiscal_backend) y de maquina (inbound_backend)
--   * grants minimos medidos sobre el C2 real, por columna donde aplica
--
-- No toca ninguna politica existente de fiscal_backend. C2 sigue canonico.
-- ============================================================================

-- ─────────────────────────────────────────────────────────────────────────────
-- 1 · Helper de procedencia. ANTES de la tabla: su DEFAULT lo referencia.
--     Encapsula auth.uid() para que fiscal_backend NO reciba acceso a auth.*.
-- ─────────────────────────────────────────────────────────────────────────────
create or replace function private.current_user_id()
returns uuid
language sql
stable
security definer
set search_path = ''
as $$ select auth.uid() $$;

comment on function private.current_user_id() is
  'Usuario autenticado actual (auth.uid()) encapsulado: procedencia real sin ampliar acceso a auth.* (ADR-048).';

revoke all on function private.current_user_id() from public;
revoke all on function private.current_user_id() from anon;
revoke all on function private.current_user_id() from authenticated;
revoke all on function private.current_user_id() from service_role;
revoke all on function private.current_user_id() from app_backend;
grant execute on function private.current_user_id() to fiscal_backend;

-- ─────────────────────────────────────────────────────────────────────────────
-- 2 · Rol de maquina. Mismo patron que fiscal_backend (ADR-020).
-- ─────────────────────────────────────────────────────────────────────────────
do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'inbound_backend') then
    create role inbound_backend
      nologin
      noinherit
      nosuperuser
      nobypassrls
      nocreatedb
      nocreaterole
      noreplication;
  else
    alter role inbound_backend
      nologin noinherit nosuperuser nobypassrls nocreatedb nocreaterole noreplication;
  end if;
end $$;

comment on role inbound_backend is
  'Rol de ejecucion del canal inbound (ADR-048). NOLOGIN, NOBYPASSRLS, NOINHERIT. Asumido por app_backend con SET LOCAL ROLE; contexto resuelto por private.enter_inbound_context.';

grant inbound_backend to app_backend with inherit false, set true, admin false;

-- ─────────────────────────────────────────────────────────────────────────────
-- 3 · Schema inbound: backend-only, fuera de la Data API.
-- ─────────────────────────────────────────────────────────────────────────────
create schema if not exists inbound;

revoke all on schema inbound from public;
revoke all on schema inbound from anon;
revoke all on schema inbound from authenticated;
revoke all on schema inbound from app_backend;
revoke all on schema inbound from service_role;
grant usage on schema inbound to fiscal_backend;
grant usage on schema inbound to inbound_backend;

-- ─────────────────────────────────────────────────────────────────────────────
-- 4 · Registro de Buzones Tribuu (ADR-048).
-- ─────────────────────────────────────────────────────────────────────────────
create table inbound.company_inboxes (
    id               uuid        not null default gen_random_uuid(),
    company_id       uuid        not null,
    display_prefix   text        not null,
    local_token      text        not null,
    -- UNA sola fuente de verdad: direccion CANONICA generada por la base.
    address          text generated always as
                       (display_prefix || '-' || local_token || '@inbox.tribuu.ai') stored,
    status           text        not null default 'active',
    rotated_from_id  uuid        null,
    disabled_reason  text        null,
    created_by       uuid        not null default private.current_user_id(),
    created_at       timestamptz not null default now(),
    activated_at     timestamptz not null default now(),
    disabled_at      timestamptz null,
    updated_at       timestamptz not null default now(),

    constraint company_inboxes_pkey primary key (id),
    -- objetivo de la FK compuesta tenant-safe (patron fiscal existente):
    constraint company_inboxes_company_id_id_key unique (company_id, id),
    constraint company_inboxes_company_fkey
        foreign key (company_id) references public.companies (id)
        on delete restrict,
    -- linaje tenant-safe: imposible apuntar a un buzon de otra empresa.
    constraint company_inboxes_rotated_from_fkey
        foreign key (company_id, rotated_from_id)
        references inbound.company_inboxes (company_id, id),

    -- Los CHECK validan FORMA; la entropia la garantiza el CSPRNG del backend.
    constraint company_inboxes_prefix_format
        check (display_prefix ~ '^[a-z0-9]{1,30}$'),
    constraint company_inboxes_token_format
        check (local_token ~ '^[a-z2-7]{16,}$'),
    constraint company_inboxes_local_part_length
        check (char_length(display_prefix) + 1 + char_length(local_token) <= 64),
    constraint company_inboxes_status_check
        check (status in ('active', 'disabled')),
    constraint company_inboxes_disabled_coherence check (
        (status = 'active'   and disabled_at is null     and disabled_reason is null) or
        (status = 'disabled' and disabled_at is not null and disabled_reason is not null)),
    constraint company_inboxes_disabled_reason_check
        check (disabled_reason is null
               or disabled_reason in ('rotated', 'revoked', 'company_disabled'))
);

comment on table inbound.company_inboxes is
  'Buzon Tribuu por empresa (ADR-048). Provider-agnostic: la infraestructura de entrega vive en la capa de intake. Lifecycle monotonico; direccion canonica generada; sin DELETE fisico.';

create unique index company_inboxes_token_key   on inbound.company_inboxes (local_token);
create unique index company_inboxes_address_key on inbound.company_inboxes (address);
create unique index company_inboxes_one_active
    on inbound.company_inboxes (company_id) where status = 'active';
create unique index company_inboxes_lineage_key
    on inbound.company_inboxes (rotated_from_id) where rotated_from_id is not null;
create index company_inboxes_resolve_idx
    on inbound.company_inboxes (address) where status = 'active';

-- ─────────────────────────────────────────────────────────────────────────────
-- 5 · Guardia de lifecycle: fila disabled CONGELADA; sin reactivacion;
--     identidad inmutable. Trigger invoker (opera sobre OLD/NEW; no necesita
--     DEFINER). No es frontera frente a superusers: es respaldo de integridad.
-- ─────────────────────────────────────────────────────────────────────────────
create function inbound.company_inboxes_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
    if old.status = 'disabled' then
        raise exception 'un buzon deshabilitado es inmutable (lifecycle monotonico, ADR-048)'
            using errcode = 'check_violation';
    end if;
    if new.company_id      is distinct from old.company_id
       or new.display_prefix  is distinct from old.display_prefix
       or new.local_token     is distinct from old.local_token
       or new.rotated_from_id is distinct from old.rotated_from_id
       or new.created_by      is distinct from old.created_by
       or new.created_at      is distinct from old.created_at
       or new.activated_at    is distinct from old.activated_at then
        raise exception 'las columnas de identidad del buzon son inmutables (ADR-048)'
            using errcode = 'check_violation';
    end if;
    new.updated_at := now();
    return new;
end $$;

revoke all on function inbound.company_inboxes_guard() from public;

create trigger company_inboxes_guard
    before update on inbound.company_inboxes
    for each row execute function inbound.company_inboxes_guard();

-- Linaje: el predecesor debe existir deshabilitado POR ROTACION. La FK compuesta
-- ya garantiza misma empresa; el indice parcial unico garantiza un solo sucesor.
create function inbound.company_inboxes_lineage()
returns trigger
language plpgsql
set search_path = ''
as $$
declare pred record;
begin
    if new.rotated_from_id is null then
        return new;
    end if;
    select status, disabled_reason into pred
      from inbound.company_inboxes
     where id = new.rotated_from_id and company_id = new.company_id;
    if pred is null
       or pred.status <> 'disabled'
       or pred.disabled_reason <> 'rotated' then
        raise exception 'rotated_from_id debe apuntar a un predecesor deshabilitado por rotacion (ADR-048)'
            using errcode = 'check_violation';
    end if;
    return new;
end $$;

revoke all on function inbound.company_inboxes_lineage() from public;

create trigger company_inboxes_lineage
    before insert on inbound.company_inboxes
    for each row execute function inbound.company_inboxes_lineage();

-- ─────────────────────────────────────────────────────────────────────────────
-- 6 · Contexto de maquina (ADR-048). Fail-closed por construccion.
-- ─────────────────────────────────────────────────────────────────────────────
create function private.enter_inbound_context(p_recipient text)
returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_inbox   uuid;
    v_company uuid;
begin
    -- 0 · LIMPIAR SIEMPRE antes de resolver: un contexto previo jamas sobrevive.
    perform set_config('request.inbound_context', '', true);

    begin
        select i.id, i.company_id
          into strict v_inbox, v_company
          from inbound.company_inboxes i
         where i.address = lower(btrim(p_recipient))
           and i.status = 'active';
    exception
        when no_data_found then
            return null;                       -- contexto queda VACIO
        when too_many_rows then
            -- imposible por unicidad de address; defensa doble, fail-closed
            raise exception 'invariante violada: multiples buzones activos para una direccion (ADR-048)';
    end;

    perform set_config('request.inbound_context',
        json_build_object('inbox_id', v_inbox, 'company_id', v_company)::text,
        true);
    return v_company;
end $$;

comment on function private.enter_inbound_context(text) is
  'Entra al contexto de maquina inbound resolviendo recipient -> buzon ACTIVO -> company (ADR-048). Limpia el contexto antes de resolver; fail-closed.';

create function private.inbound_company_id()
returns uuid
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    crudo     text;
    v_inbox   uuid;
    v_company uuid;
begin
    crudo := nullif(current_setting('request.inbound_context', true), '');
    if crudo is null then
        return null;
    end if;
    begin
        v_inbox   := (crudo::json ->> 'inbox_id')::uuid;
        v_company := (crudo::json ->> 'company_id')::uuid;
    exception when others then
        return null;                            -- GUC malformado: fail-closed
    end;
    if v_inbox is null or v_company is null then
        return null;
    end if;
    -- Revalidacion: el par debe corresponder a un buzon ACTIVO real, AHORA.
    if not exists (
        select 1 from inbound.company_inboxes i
         where i.id = v_inbox and i.company_id = v_company and i.status = 'active'
    ) then
        return null;
    end if;
    return v_company;
end $$;

create function private.inbound_inbox_id()
returns uuid
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    crudo     text;
    v_inbox   uuid;
    v_company uuid;
begin
    crudo := nullif(current_setting('request.inbound_context', true), '');
    if crudo is null then
        return null;
    end if;
    begin
        v_inbox   := (crudo::json ->> 'inbox_id')::uuid;
        v_company := (crudo::json ->> 'company_id')::uuid;
    exception when others then
        return null;
    end;
    if v_inbox is null or v_company is null then
        return null;
    end if;
    if not exists (
        select 1 from inbound.company_inboxes i
         where i.id = v_inbox and i.company_id = v_company and i.status = 'active'
    ) then
        return null;
    end if;
    return v_inbox;
end $$;

do $$
declare f text;
begin
  foreach f in array array[
      'private.enter_inbound_context(text)',
      'private.inbound_company_id()',
      'private.inbound_inbox_id()']
  loop
    execute format('revoke all on function %s from public', f);
    execute format('revoke all on function %s from anon', f);
    execute format('revoke all on function %s from authenticated', f);
    execute format('revoke all on function %s from service_role', f);
    execute format('revoke all on function %s from app_backend', f);
    execute format('revoke all on function %s from fiscal_backend', f);
    execute format('grant execute on function %s to inbound_backend', f);
  end loop;
end $$;

-- ─────────────────────────────────────────────────────────────────────────────
-- 7 · RLS del registro: humanos via fiscal_backend; la maquina NO lo administra
--     ni lo lee directamente (solo via enter_inbound_context).
-- ─────────────────────────────────────────────────────────────────────────────
alter table inbound.company_inboxes enable row level security;

create policy company_inboxes_select on inbound.company_inboxes
    for select to fiscal_backend
    using (private.is_company_member(company_id));

create policy company_inboxes_insert on inbound.company_inboxes
    for insert to fiscal_backend
    with check (
        private.can_write_company(company_id)
        and created_by = private.current_user_id()
    );

create policy company_inboxes_update on inbound.company_inboxes
    for update to fiscal_backend
    using (private.can_write_company(company_id))
    with check (private.can_write_company(company_id));

-- Sin politica DELETE y sin privilegio DELETE: el borrado fisico no existe.

grant select on inbound.company_inboxes to fiscal_backend;
grant insert on inbound.company_inboxes to fiscal_backend;
grant update (status, disabled_at, disabled_reason, updated_at)
    on inbound.company_inboxes to fiscal_backend;

-- ─────────────────────────────────────────────────────────────────────────────
-- 8 · Grants de maquina sobre fiscal: EXACTAMENTE lo que C2 ejecuta.
--     (RETURNING exige SELECT de las columnas devueltas: por eso
--      document_lines recibe SELECT(id) — persistence.py:289 `returning id`.)
-- ─────────────────────────────────────────────────────────────────────────────
grant usage on schema fiscal  to inbound_backend;
grant usage on schema private to inbound_backend;

grant select (id, company_id, raw_xml, content_sha256, parse_status,
              parse_attempt_count, schema_detection_status, electronic_document_id)
    on fiscal.source_documents to inbound_backend;
grant insert on fiscal.source_documents to inbound_backend;
grant update (parse_status, parse_error, parse_attempt_count, parse_attempted_at,
              schema_detection_status, detected_document_type,
              detected_schema_version, electronic_document_id, updated_at)
    on fiscal.source_documents to inbound_backend;

grant select (id, company_id, clave) on fiscal.electronic_documents to inbound_backend;
grant insert on fiscal.electronic_documents to inbound_backend;

grant insert on fiscal.document_parties    to inbound_backend;
grant insert on fiscal.document_lines      to inbound_backend;
grant select (id) on fiscal.document_lines to inbound_backend;   -- RETURNING id
grant insert on fiscal.line_discounts      to inbound_backend;
grant insert on fiscal.line_taxes          to inbound_backend;
grant insert on fiscal.document_references to inbound_backend;

-- ─────────────────────────────────────────────────────────────────────────────
-- 9 · Politicas de maquina sobre fiscal: SOLO operaciones concedidas, todas
--     ancladas al contexto resuelto. Las politicas de fiscal_backend quedan
--     intactas.
-- ─────────────────────────────────────────────────────────────────────────────
create policy sdoc_inbound_select on fiscal.source_documents
    for select to inbound_backend
    using (company_id = private.inbound_company_id());
create policy sdoc_inbound_insert on fiscal.source_documents
    for insert to inbound_backend
    with check (company_id = private.inbound_company_id());
create policy sdoc_inbound_update on fiscal.source_documents
    for update to inbound_backend
    using (company_id = private.inbound_company_id())
    with check (company_id = private.inbound_company_id());

create policy edoc_inbound_select on fiscal.electronic_documents
    for select to inbound_backend
    using (company_id = private.inbound_company_id());
create policy edoc_inbound_insert on fiscal.electronic_documents
    for insert to inbound_backend
    with check (company_id = private.inbound_company_id());

create policy dline_inbound_select on fiscal.document_lines
    for select to inbound_backend
    using (company_id = private.inbound_company_id());        -- RETURNING id
create policy dline_inbound_insert on fiscal.document_lines
    for insert to inbound_backend
    with check (company_id = private.inbound_company_id());

create policy dparty_inbound_insert on fiscal.document_parties
    for insert to inbound_backend
    with check (company_id = private.inbound_company_id());
create policy ldisc_inbound_insert on fiscal.line_discounts
    for insert to inbound_backend
    with check (company_id = private.inbound_company_id());
create policy ltax_inbound_insert on fiscal.line_taxes
    for insert to inbound_backend
    with check (company_id = private.inbound_company_id());
create policy dref_inbound_insert on fiscal.document_references
    for insert to inbound_backend
    with check (company_id = private.inbound_company_id());

-- ─────────────────────────────────────────────────────────────────────────────
-- 10 · Asserts de topologia (fail-fast en la propia migracion).
-- ─────────────────────────────────────────────────────────────────────────────
do $$
declare r record;
begin
  select rolcanlogin, rolsuper, rolbypassrls, rolinherit, rolcreaterole, rolcreatedb
    into r from pg_roles where rolname = 'inbound_backend';
  if r is null              then raise exception 'inbound_backend no existe'; end if;
  if r.rolcanlogin          then raise exception 'inbound_backend NO debe tener LOGIN'; end if;
  if r.rolsuper             then raise exception 'inbound_backend NO debe ser SUPERUSER'; end if;
  if r.rolbypassrls         then raise exception 'inbound_backend NO debe tener BYPASSRLS'; end if;
  if r.rolinherit           then raise exception 'inbound_backend debe ser NOINHERIT'; end if;
  if r.rolcreaterole or r.rolcreatedb then raise exception 'inbound_backend sin create'; end if;

  if not exists (
      select 1 from pg_auth_members am
      join pg_roles g on g.oid = am.roleid
      join pg_roles m on m.oid = am.member
      where g.rolname = 'inbound_backend' and m.rolname = 'app_backend'
        and am.set_option and not am.inherit_option and not am.admin_option
  ) then
      raise exception 'app_backend debe poder SET ROLE inbound_backend (set, sin inherit/admin)';
  end if;

  if not has_function_privilege('inbound_backend', 'private.enter_inbound_context(text)', 'EXECUTE') then
      raise exception 'inbound_backend necesita EXECUTE sobre enter_inbound_context';
  end if;
  if has_function_privilege('fiscal_backend', 'private.enter_inbound_context(text)', 'EXECUTE') then
      raise exception 'fiscal_backend NO debe poder entrar al contexto de maquina';
  end if;
  if has_function_privilege('authenticated', 'private.enter_inbound_context(text)', 'EXECUTE') then
      raise exception 'authenticated NO debe poder entrar al contexto de maquina';
  end if;
  if not has_function_privilege('fiscal_backend', 'private.current_user_id()', 'EXECUTE') then
      raise exception 'fiscal_backend necesita EXECUTE sobre current_user_id';
  end if;
  if has_table_privilege('inbound_backend', 'inbound.company_inboxes', 'SELECT') then
      raise exception 'inbound_backend NO debe leer el registro directamente';
  end if;
  if has_table_privilege('inbound_backend', 'fiscal.source_documents', 'DELETE')
     or has_table_privilege('fiscal_backend', 'inbound.company_inboxes', 'DELETE') then
      raise exception 'DELETE no existe en esta frontera';
  end if;
  if has_column_privilege('inbound_backend', 'fiscal.source_documents', 'raw_xml', 'UPDATE') then
      raise exception 'raw_xml debe ser inmutable para la maquina';
  end if;
end $$;
