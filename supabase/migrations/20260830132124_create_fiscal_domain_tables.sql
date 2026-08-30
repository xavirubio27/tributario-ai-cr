-- ============================================================================
-- Primera base fisica del dominio fiscal (Checkpoint E, fase E3)
--
-- Implementa el diseno aprobado en docs/FISCAL_PHYSICAL_MODEL.md, conforme a
-- ADR-020 (frontera fiscal), ADR-022..ADR-038.
--
-- NO incluye: parser XML, Tax Engine, catalogos externos (H-3), ni reglas
-- semanticas condicionales (H-4). Solo estructura, integridad y autorizacion.
--
-- Las siete tablas viven en el schema `fiscal`, que la Data API no expone.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- 1. fiscal.electronic_documents  --  el comprobante normalizado
--
-- Se crea primero porque es destino de las claves foraneas compuestas de las
-- demas tablas, incluida `source_documents`.
-- ---------------------------------------------------------------------------
create table fiscal.electronic_documents (
    id                         uuid        not null default gen_random_uuid(),
    company_id                 uuid        not null,

    -- Identificacion oficial. Texto: los ceros a la izquierda son significativos.
    document_type              text        not null,
    clave                      text        not null,
    consecutive_number         text        not null,

    -- Fecha de emision en sus tres representaciones (ADR-034):
    -- instante, desplazamiento reportado y valor literal del XML.
    issued_at                  timestamptz not null,
    issued_at_offset_minutes   smallint    not null,
    issued_at_raw              text        not null,

    -- Contexto y condiciones comerciales
    issuer_activity_code       text        not null,
    receiver_activity_code     text        null,
    sale_condition_code        text        not null,
    credit_term                integer     null,

    -- Moneda
    currency_code              text        not null,
    reported_exchange_rate     numeric(18,5) not null,

    -- Totales reportados. Los opcionales NO llevan DEFAULT: ausente != cero.
    reported_total_taxed       numeric(18,5) null,
    reported_total_exempt      numeric(18,5) null,
    reported_total_exonerated  numeric(18,5) null,
    reported_total_not_subject numeric(18,5) null,
    reported_total_sale        numeric(18,5) not null,
    reported_total_discount    numeric(18,5) null,
    reported_total_net_sale    numeric(18,5) not null,
    reported_total_tax         numeric(18,5) null,
    reported_total_document    numeric(18,5) not null,

    -- Interpretacion (ADR-026). La revision puede no ser determinable.
    ruleset_revision           text        null,
    ruleset_revision_status    text        not null,

    -- Metadato derivado del tenant, recomputable (ADR-027).
    direction                  text        not null,
    direction_computed_at      timestamptz not null,

    created_at                 timestamptz not null default now(),
    updated_at                 timestamptz not null default now(),

    constraint electronic_documents_pkey primary key (id),

    -- Habilita las FK compuestas de las hijas (ADR-032).
    constraint electronic_documents_company_id_key unique (company_id, id),

    -- Identidad logica por tenant, nunca global (ADR-035).
    constraint electronic_documents_company_clave_key unique (company_id, clave),

    constraint electronic_documents_company_fkey
        foreign key (company_id) references public.companies (id)
        on delete restrict,

    -- Vocabulario propio: aqui si se valida el valor.
    constraint electronic_documents_document_type_check
        check (document_type in ('invoice', 'credit_note', 'debit_note')),
    constraint electronic_documents_ruleset_status_check
        check (ruleset_revision_status in ('detected', 'ambiguous', 'resolved')),
    constraint electronic_documents_direction_check
        check (direction in ('issued', 'received', 'unknown')),

    -- Forma oficial de los identificadores.
    constraint electronic_documents_clave_check
        check (clave ~ '^[0-9]{50}$'),
    constraint electronic_documents_consecutive_check
        check (consecutive_number ~ '^[0-9]{20}$'),

    -- xs:dateTime admite desplazamientos de -14:00 a +14:00 (ADR-034).
    constraint electronic_documents_offset_check
        check (issued_at_offset_minutes between -840 and 840),

    -- Codigos de catalogo oficial: se valida la FORMA, nunca el valor (ADR-029).
    constraint electronic_documents_issuer_activity_check
        check (issuer_activity_code ~ '^[0-9]{6}$'),
    constraint electronic_documents_receiver_activity_check
        check (receiver_activity_code ~ '^[0-9]{6}$'),
    constraint electronic_documents_sale_condition_check
        check (sale_condition_code ~ '^[0-9]{2}$'),
    constraint electronic_documents_currency_check
        check (char_length(currency_code) between 1 and 3),
    constraint electronic_documents_credit_term_check
        check (credit_term between 0 and 99999),

    -- El XSD declara minInclusive=0 en DecimalDineroType: ningun importe es
    -- negativo, tampoco en notas de credito (ADR-036).
    constraint electronic_documents_amounts_non_negative_check
        check (
            reported_exchange_rate     >= 0
            and reported_total_sale        >= 0
            and reported_total_net_sale    >= 0
            and reported_total_document    >= 0
            and (reported_total_taxed       is null or reported_total_taxed       >= 0)
            and (reported_total_exempt      is null or reported_total_exempt      >= 0)
            and (reported_total_exonerated  is null or reported_total_exonerated  >= 0)
            and (reported_total_not_subject is null or reported_total_not_subject >= 0)
            and (reported_total_discount    is null or reported_total_discount    >= 0)
            and (reported_total_tax         is null or reported_total_tax         >= 0)
        )
);

comment on table fiscal.electronic_documents is
    'Comprobante electronico normalizado. Todo su contenido fiscal es reportado; ningun valor es calculado por nosotros (ADR-023).';

-- ---------------------------------------------------------------------------
-- 2. fiscal.source_documents  --  el artefacto original
--
-- Debe poder existir SIN interpretacion valida: un XML corrupto sigue siendo
-- evidencia de que algo llego (ADR-027).
-- ---------------------------------------------------------------------------
create table fiscal.source_documents (
    id                       uuid        not null default gen_random_uuid(),
    company_id               uuid        not null,

    -- Hechos de origen: inmutables tras el INSERT (ADR-036, ADR-037).
    raw_xml                  bytea       not null,
    content_sha256           bytea       not null,
    ingested_at              timestamptz not null default now(),
    ingestion_source         text        not null,

    -- Metadatos de interpretacion: mutables por definicion.
    parse_status             text        not null default 'pending',
    parse_error              text        null,
    parse_attempted_at       timestamptz null,
    parse_attempt_count      integer     not null default 0,
    schema_detection_status  text        not null default 'pending',
    detected_document_type   text        null,
    detected_schema_version  text        null,

    -- Enlace 0..1 hacia el documento normalizado.
    electronic_document_id   uuid        null,

    updated_at               timestamptz not null default now(),

    constraint source_documents_pkey primary key (id),

    constraint source_documents_company_fkey
        foreign key (company_id) references public.companies (id)
        on delete restrict,

    -- FK compuesta: imposible enlazar con un documento de otra empresa.
    -- La accion de borrado se acota a la columna opcional; sin acotar
    -- intentaria anular company_id, que es NOT NULL (ADR-036).
    constraint source_documents_electronic_document_fkey
        foreign key (company_id, electronic_document_id)
        references fiscal.electronic_documents (company_id, id)
        on delete set null (electronic_document_id),

    -- Catalogos internos: vocabulario propio, se valida el valor.
    constraint source_documents_ingestion_source_check
        check (ingestion_source in ('manual_upload', 'email', 'api')),
    constraint source_documents_parse_status_check
        check (parse_status in ('pending', 'parsed', 'failed')),
    constraint source_documents_schema_detection_check
        check (schema_detection_status in ('pending', 'detected', 'unknown', 'unsupported', 'failed')),
    constraint source_documents_parse_attempt_count_check
        check (parse_attempt_count >= 0),

    -- Huella: 32 bytes y correspondiente a los bytes almacenados.
    -- Funcion NATIVA de pg_catalog: no pgcrypto, no digest() (ADR-037).
    constraint source_documents_sha256_length_check
        check (octet_length(content_sha256) = 32),
    constraint source_documents_sha256_matches_check
        check (content_sha256 = pg_catalog.sha256(raw_xml))
);

comment on table fiscal.source_documents is
    'Artefacto original recibido, interpretable o no. raw_xml y content_sha256 son inmutables (ADR-022, ADR-037).';

-- ---------------------------------------------------------------------------
-- 3. fiscal.document_parties  --  instantanea historica de emisor y receptor
-- ---------------------------------------------------------------------------
create table fiscal.document_parties (
    id                        uuid not null default gen_random_uuid(),
    company_id                uuid not null,
    electronic_document_id    uuid not null,

    role                      text not null,
    legal_name                text not null,
    identification_type_code  text not null,
    identification_number     text not null,
    trade_name                text null,

    constraint document_parties_pkey primary key (id),

    constraint document_parties_document_fkey
        foreign key (company_id, electronic_document_id)
        references fiscal.electronic_documents (company_id, id)
        on delete cascade,

    -- Impide dos emisores o dos receptores. El minimo (>= 1 emisor) es
    -- completitud del documento y corresponde a la capa 2 (ADR-030).
    constraint document_parties_document_role_key
        unique (company_id, electronic_document_id, role),

    constraint document_parties_role_check
        check (role in ('issuer', 'receiver')),
    constraint document_parties_identification_type_check
        check (identification_type_code ~ '^[0-9]{2}$'),
    -- Texto, nunca numero: la revision 2026 admite alfanumericos.
    constraint document_parties_identification_number_check
        check (char_length(identification_number) between 1 and 20),
    constraint document_parties_legal_name_check
        check (char_length(legal_name) between 1 and 100),
    constraint document_parties_trade_name_check
        check (char_length(trade_name) between 1 and 80)
);

comment on table fiscal.document_parties is
    'Instantanea historica de lo que el comprobante decia sobre cada parte. No es clave foranea a un maestro mutable (ADR-024).';

-- ---------------------------------------------------------------------------
-- 4. fiscal.document_lines
-- ---------------------------------------------------------------------------
create table fiscal.document_lines (
    id                      uuid not null default gen_random_uuid(),
    company_id              uuid not null,
    electronic_document_id  uuid not null,

    line_number             integer       not null,
    cabys_code              text          not null,
    description             text          not null,
    unit_of_measure_code    text          not null,
    reported_quantity       numeric(16,3) not null,
    reported_unit_price     numeric(18,5) not null,
    reported_gross_amount   numeric(18,5) not null,
    reported_subtotal       numeric(18,5) not null,
    reported_taxable_base   numeric(18,5) not null,
    reported_net_tax        numeric(18,5) not null,
    reported_line_total     numeric(18,5) not null,

    constraint document_lines_pkey primary key (id),

    -- Destino de las FK compuestas de line_discounts y line_taxes (ADR-032).
    constraint document_lines_company_id_key unique (company_id, id),

    constraint document_lines_document_fkey
        foreign key (company_id, electronic_document_id)
        references fiscal.electronic_documents (company_id, id)
        on delete cascade,

    constraint document_lines_document_line_number_key
        unique (company_id, electronic_document_id, line_number),

    constraint document_lines_line_number_check
        check (line_number between 1 and 1000),
    -- CABYS: longitud oficial. Sin clave foranea a catalogo local (ADR-029).
    constraint document_lines_cabys_check
        check (cabys_code ~ '^[0-9]{13}$'),
    constraint document_lines_description_check
        check (char_length(description) between 1 and 200),
    constraint document_lines_unit_check
        check (char_length(unit_of_measure_code) between 1 and 15),
    constraint document_lines_amounts_non_negative_check
        check (
            reported_quantity     >= 0
            and reported_unit_price   >= 0
            and reported_gross_amount >= 0
            and reported_subtotal     >= 0
            and reported_taxable_base >= 0
            and reported_net_tax      >= 0
            and reported_line_total   >= 0
        )
);

-- ---------------------------------------------------------------------------
-- 5. fiscal.line_discounts  --  0..5 por linea
-- ---------------------------------------------------------------------------
create table fiscal.line_discounts (
    id                uuid not null default gen_random_uuid(),
    company_id        uuid not null,
    document_line_id  uuid not null,

    sequence          integer       not null,
    reported_amount   numeric(18,5) not null,
    discount_code     text          not null,

    constraint line_discounts_pkey primary key (id),

    constraint line_discounts_line_fkey
        foreign key (company_id, document_line_id)
        references fiscal.document_lines (company_id, id)
        on delete cascade,

    constraint line_discounts_line_sequence_key
        unique (company_id, document_line_id, sequence),

    constraint line_discounts_sequence_check
        check (sequence between 1 and 5),
    constraint line_discounts_code_check
        check (discount_code ~ '^[0-9]{2}$'),
    constraint line_discounts_amount_non_negative_check
        check (reported_amount >= 0)
);

-- ---------------------------------------------------------------------------
-- 6. fiscal.line_taxes  --  1..1000 por linea
--
-- El minimo de un impuesto por linea es completitud del documento y se
-- garantiza en la transaccion de normalizacion, no con un trigger (ADR-030).
-- ---------------------------------------------------------------------------
create table fiscal.line_taxes (
    id                uuid not null default gen_random_uuid(),
    company_id        uuid not null,
    document_line_id  uuid not null,

    sequence          integer       not null,
    tax_code          text          not null,
    vat_rate_code     text          null,
    reported_rate     numeric(4,2)  null,
    reported_amount   numeric(18,5) not null,

    constraint line_taxes_pkey primary key (id),

    constraint line_taxes_line_fkey
        foreign key (company_id, document_line_id)
        references fiscal.document_lines (company_id, id)
        on delete cascade,

    constraint line_taxes_line_sequence_key
        unique (company_id, document_line_id, sequence),

    constraint line_taxes_sequence_check
        check (sequence between 1 and 1000),
    constraint line_taxes_tax_code_check
        check (tax_code ~ '^[0-9]{2}$'),
    constraint line_taxes_vat_rate_code_check
        check (vat_rate_code ~ '^[0-9]{2}$'),
    constraint line_taxes_amounts_non_negative_check
        check (reported_amount >= 0 and (reported_rate is null or reported_rate >= 0))
);

-- ---------------------------------------------------------------------------
-- 7. fiscal.document_references  --  0..10 por documento
--
-- `reported_number` es OPCIONAL en el XSD: por eso no puede existir una clave
-- foranea obligatoria hacia otro comprobante (ADR-028).
-- ---------------------------------------------------------------------------
create table fiscal.document_references (
    id                      uuid not null default gen_random_uuid(),
    company_id              uuid not null,
    electronic_document_id  uuid not null,

    sequence                integer     not null,

    -- Lo que el documento dice: inmutable.
    referenced_document_type_code      text        not null,
    reported_number                    text        null,
    reported_reference_date            timestamptz not null,
    reported_reference_offset_minutes  smallint    not null,
    reported_reference_date_raw        text        not null,
    reference_code                     text        null,
    reason                             text        null,

    -- Nuestra conclusion: opcional, diferida y reintentable.
    resolved_document_id    uuid        null,

    constraint document_references_pkey primary key (id),

    constraint document_references_document_fkey
        foreign key (company_id, electronic_document_id)
        references fiscal.electronic_documents (company_id, id)
        on delete cascade,

    -- La resolucion JAMAS cruza empresas, aunque la clave coincida (ADR-028).
    constraint document_references_resolved_fkey
        foreign key (company_id, resolved_document_id)
        references fiscal.electronic_documents (company_id, id)
        on delete set null (resolved_document_id),

    constraint document_references_document_sequence_key
        unique (company_id, electronic_document_id, sequence),

    constraint document_references_sequence_check
        check (sequence between 1 and 10),
    constraint document_references_type_code_check
        check (referenced_document_type_code ~ '^[0-9]{2}$'),
    constraint document_references_reference_code_check
        check (reference_code ~ '^[0-9]{2}$'),
    constraint document_references_number_check
        check (char_length(reported_number) between 1 and 50),
    constraint document_references_reason_check
        check (char_length(reason) between 1 and 180),
    constraint document_references_offset_check
        check (reported_reference_offset_minutes between -840 and 840)
);

comment on table fiscal.document_references is
    'Referencia reportada por el comprobante. `resolved_document_id` es nuestra resolucion diferida, siempre dentro del mismo tenant (ADR-028).';

-- ---------------------------------------------------------------------------
-- 8. Indices  --  solo los aprobados; cada uno con una consulta que lo motiva
-- ---------------------------------------------------------------------------

-- La consulta mas frecuente del producto: documentos por fecha.
create index edoc_company_issued_idx
    on fiscal.electronic_documents (company_id, issued_at desc);

-- Filtrado por tipo (p. ej. "mis notas de credito de agosto").
create index edoc_company_type_issued_idx
    on fiscal.electronic_documents (company_id, document_type, issued_at desc);

-- Separacion ventas / compras.
create index edoc_company_direction_issued_idx
    on fiscal.electronic_documents (company_id, direction, issued_at desc);

-- Agregacion por contraparte sin catalogo maestro.
create index dparty_company_ident_idx
    on fiscal.document_parties (company_id, identification_type_code, identification_number);

-- Deduplicacion previa a insertar. NO unico: los mismos bytes pueden
-- corresponder a dos eventos de ingesta legitimos (ADR-037).
create index sdoc_company_hash_idx
    on fiscal.source_documents (company_id, content_sha256);

-- Artefactos pendientes o fallidos, para reproceso.
create index sdoc_company_status_idx
    on fiscal.source_documents (company_id, parse_status)
    where parse_status <> 'parsed';

-- Lado REFERENTE de la FK opcional: PostgreSQL no lo indexa solo, y sin el
-- cada borrado del padre recorreria la tabla entera.
create index sdoc_company_edoc_idx
    on fiscal.source_documents (company_id, electronic_document_id);

-- Referencias pendientes de resolver. Indice parcial: se vacia al resolverse.
create index dref_company_unresolved_idx
    on fiscal.document_references (company_id, reported_reference_date)
    where resolved_document_id is null;

-- Lado referente de la otra FK opcional.
create index dref_company_resolved_idx
    on fiscal.document_references (company_id, resolved_document_id);

-- ---------------------------------------------------------------------------
-- 9. private.can_write_company  --  autoridad de escritura fiscal (ADR-038)
--
-- SECURITY DEFINER: encapsula la autoridad para poder responder la pregunta
-- SIN repartir acceso a las tablas que la sustentan. `fiscal_backend` sigue
-- sin USAGE sobre `auth` y sin SELECT sobre public.company_memberships.
--
-- `set search_path = ''` es obligatorio: sin el, un objeto en un schema
-- anterior del search_path podria suplantar a public.company_memberships.
-- Por eso todas las referencias van calificadas.
--
-- No acepta user_id ni role del llamante: la identidad se resuelve dentro y
-- el rol se lee de la tabla, nunca de la peticion (ADR-012, ADR-038).
-- ---------------------------------------------------------------------------
create function private.can_write_company(p_company_id uuid)
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
          and m.role       in ('owner', 'editor')
    );
$$;

comment on function private.can_write_company(uuid) is
    'Capacidad de ESCRITURA fiscal: pertenencia + rol owner/editor. Distinta de private.is_company_member, que solo demuestra pertenencia (ADR-038).';

revoke all on function private.can_write_company(uuid) from public;
revoke all on function private.can_write_company(uuid) from anon;
revoke all on function private.can_write_company(uuid) from authenticated;
revoke all on function private.can_write_company(uuid) from service_role;
revoke all on function private.can_write_company(uuid) from app_backend;
grant execute on function private.can_write_company(uuid) to fiscal_backend;

-- ---------------------------------------------------------------------------
-- 10. RLS  --  habilitada en las siete tablas
--
-- SELECT  -> pertenencia
-- INSERT  -> WITH CHECK(capacidad de escritura)
-- UPDATE  -> USING + WITH CHECK: sin WITH CHECK, una actualizacion podria
--            mover la fila a otra empresa (ADR-038).
-- DELETE  -> sin politica y sin privilegio.
-- ---------------------------------------------------------------------------
do $$
declare
    t text;
begin
    foreach t in array array[
        'source_documents', 'electronic_documents', 'document_parties',
        'document_lines', 'line_discounts', 'line_taxes', 'document_references'
    ]
    loop
        execute format('alter table fiscal.%I enable row level security', t);

        execute format(
            'create policy %I on fiscal.%I for select to fiscal_backend '
            'using (private.is_company_member(company_id))',
            t || '_select', t);

        execute format(
            'create policy %I on fiscal.%I for insert to fiscal_backend '
            'with check (private.can_write_company(company_id))',
            t || '_insert', t);

        execute format(
            'create policy %I on fiscal.%I for update to fiscal_backend '
            'using (private.can_write_company(company_id)) '
            'with check (private.can_write_company(company_id))',
            t || '_update', t);
    end loop;
end $$;

-- ---------------------------------------------------------------------------
-- 11. Privilegios  --  minimo necesario, y UPDATE solo por columna
--
-- NUNCA `grant update on table`: un privilegio de tabla autoriza TODAS las
-- columnas, y revocar columnas despues no lo reduce. La unica forma correcta
-- es conceder exclusivamente la lista de columnas mutables (ADR-036).
--
-- Sin DELETE en ninguna tabla: la evidencia fiscal no desaparece por el flujo
-- normal de la aplicacion.
-- ---------------------------------------------------------------------------
do $$
declare
    t text;
begin
    foreach t in array array[
        'source_documents', 'electronic_documents', 'document_parties',
        'document_lines', 'line_discounts', 'line_taxes', 'document_references'
    ]
    loop
        execute format('revoke all on fiscal.%I from public', t);
        execute format('revoke all on fiscal.%I from anon', t);
        execute format('revoke all on fiscal.%I from authenticated', t);
        execute format('revoke all on fiscal.%I from service_role', t);
        execute format('revoke all on fiscal.%I from app_backend', t);
        execute format('grant select, insert on fiscal.%I to fiscal_backend', t);
    end loop;
end $$;

-- 9 columnas de metadato operativo del artefacto.
grant update (
    parse_status,
    parse_error,
    parse_attempted_at,
    parse_attempt_count,
    schema_detection_status,
    detected_document_type,
    detected_schema_version,
    electronic_document_id,
    updated_at
) on fiscal.source_documents to fiscal_backend;

-- 5 columnas de interpretacion y metadato derivado.
grant update (
    ruleset_revision,
    ruleset_revision_status,
    direction,
    direction_computed_at,
    updated_at
) on fiscal.electronic_documents to fiscal_backend;

-- 1 columna: la resolucion diferida de la referencia.
grant update (
    resolved_document_id
) on fiscal.document_references to fiscal_backend;

-- document_parties, document_lines, line_discounts y line_taxes NO reciben
-- ningun UPDATE: toda su informacion nace por INSERT y es reportada.

-- ---------------------------------------------------------------------------
-- 12. Verificacion de invariantes  --  falla la migracion si algo no cuadra
--
-- No basta con que las sentencias no den error: se comprueba que el estado
-- resultante sea el que el diseno exige.
-- ---------------------------------------------------------------------------
do $$
declare
    v_expected text[] := array[
        'source_documents', 'electronic_documents', 'document_parties',
        'document_lines', 'line_discounts', 'line_taxes', 'document_references'
    ];
    v_count int;
    v_name  text;
begin
    -- 12.1  Las siete tablas existen.
    select count(*) into v_count
    from information_schema.tables
    where table_schema = 'fiscal' and table_name = any(v_expected);
    if v_count <> 7 then
        raise exception 'Se esperaban 7 tablas fiscales, existen %', v_count;
    end if;

    -- 12.2  RLS habilitada en las siete.
    select count(*) into v_count
    from pg_class c join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'fiscal' and c.relname = any(v_expected) and c.relrowsecurity;
    if v_count <> 7 then
        raise exception 'RLS habilitada solo en % de 7 tablas', v_count;
    end if;

    -- 12.3  Tres politicas por tabla: select, insert, update. Ninguna de delete.
    select count(*) into v_count
    from pg_policies where schemaname = 'fiscal';
    if v_count <> 21 then
        raise exception 'Se esperaban 21 politicas (7x3), existen %', v_count;
    end if;
    if exists (select 1 from pg_policies where schemaname = 'fiscal' and cmd = 'DELETE') then
        raise exception 'Existe una politica de DELETE: el flujo normal no debe borrar';
    end if;

    -- 12.4  fiscal_backend NO tiene DELETE en ninguna tabla.
    foreach v_name in array v_expected loop
        if has_table_privilege('fiscal_backend', 'fiscal.' || v_name, 'DELETE') then
            raise exception 'fiscal_backend tiene DELETE sobre %', v_name;
        end if;
    end loop;

    -- 12.5  Ningun UPDATE a nivel de TABLA. Se consulta el ACL directamente:
    --       has_table_privilege devuelve cierto si hay privilegio de columna.
    select count(*) into v_count
    from pg_class c
    join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'fiscal' and c.relname = any(v_expected)
      and array_to_string(coalesce(c.relacl, '{}'), ',') like '%fiscal_backend=%w%';
    if v_count <> 0 then
        raise exception 'Hay % tabla(s) con UPDATE a nivel de tabla para fiscal_backend', v_count;
    end if;

    -- 12.6  Exactamente 15 privilegios UPDATE de columna, en 3 tablas.
    select count(*) into v_count
    from information_schema.column_privileges
    where table_schema = 'fiscal' and privilege_type = 'UPDATE' and grantee = 'fiscal_backend';
    if v_count <> 15 then
        raise exception 'Se esperaban 15 columnas con UPDATE, hay %', v_count;
    end if;

    -- 12.7  Las cuatro tablas sin metadato mutable no tienen ningun UPDATE.
    select count(*) into v_count
    from information_schema.column_privileges
    where table_schema = 'fiscal' and privilege_type = 'UPDATE' and grantee = 'fiscal_backend'
      and table_name in ('document_parties', 'document_lines', 'line_discounts', 'line_taxes');
    if v_count <> 0 then
        raise exception 'Hay % columnas con UPDATE en tablas que no deben tener ninguna', v_count;
    end if;

    -- 12.8  Ningun rol ajeno tiene acceso a las tablas fiscales.
    foreach v_name in array v_expected loop
        if has_table_privilege('authenticated', 'fiscal.' || v_name, 'SELECT')
        or has_table_privilege('anon',          'fiscal.' || v_name, 'SELECT')
        or has_table_privilege('service_role',  'fiscal.' || v_name, 'SELECT')
        or has_table_privilege('app_backend',   'fiscal.' || v_name, 'SELECT') then
            raise exception 'Un rol no autorizado tiene SELECT sobre %', v_name;
        end if;
    end loop;

    -- 12.9  El helper solo es ejecutable por fiscal_backend.
    if not has_function_privilege('fiscal_backend', 'private.can_write_company(uuid)', 'EXECUTE') then
        raise exception 'fiscal_backend no puede ejecutar private.can_write_company';
    end if;
    if has_function_privilege('authenticated', 'private.can_write_company(uuid)', 'EXECUTE')
    or has_function_privilege('anon',          'private.can_write_company(uuid)', 'EXECUTE')
    or has_function_privilege('service_role',  'private.can_write_company(uuid)', 'EXECUTE')
    or has_function_privilege('app_backend',   'private.can_write_company(uuid)', 'EXECUTE') then
        raise exception 'Un rol no autorizado puede ejecutar private.can_write_company';
    end if;

    -- 12.10  El helper es STABLE, SECURITY DEFINER y con search_path vacio.
    --        PostgreSQL almacena el ajuste como search_path="" (entrecomillado),
    --        verificado contra el catalogo; no como search_path= a secas.
    if not exists (
        select 1 from pg_proc p join pg_namespace n on n.oid = p.pronamespace
        where n.nspname = 'private' and p.proname = 'can_write_company'
          and p.prosecdef and p.provolatile = 's'
          and p.proconfig @> array['search_path=""']
    ) then
        raise exception 'private.can_write_company no cumple STABLE + SECURITY DEFINER + search_path vacio';
    end if;

    -- 12.11  fiscal_backend sigue SIN acceso directo a auth ni a memberships.
    if has_schema_privilege('fiscal_backend', 'auth', 'USAGE') then
        raise exception 'fiscal_backend obtuvo USAGE sobre auth: violacion de ADR-020';
    end if;
    if has_table_privilege('fiscal_backend', 'public.company_memberships', 'SELECT') then
        raise exception 'fiscal_backend obtuvo SELECT sobre company_memberships';
    end if;

    -- 12.12  UNIQUE (company_id, id) solo en las dos tablas que lo requieren.
    select count(*) into v_count
    from pg_constraint con
    join pg_class c on c.oid = con.conrelid
    join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'fiscal' and con.contype = 'u'
      and pg_get_constraintdef(con.oid) = 'UNIQUE (company_id, id)';
    if v_count <> 2 then
        raise exception 'Se esperaban 2 UNIQUE (company_id, id), hay %', v_count;
    end if;

    -- 12.13  Los dos SET NULL acotan la columna, no anulan company_id.
    select count(*) into v_count
    from pg_constraint con
    join pg_class c on c.oid = con.conrelid
    join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'fiscal' and con.contype = 'f' and con.confdeltype = 'n';
    if v_count <> 2 then
        raise exception 'Se esperaban 2 FK con ON DELETE SET NULL, hay %', v_count;
    end if;
    if exists (
        select 1 from pg_constraint con
        join pg_class c on c.oid = con.conrelid
        join pg_namespace n on n.oid = c.relnamespace
        where n.nspname = 'fiscal' and con.contype = 'f' and con.confdeltype = 'n'
          and pg_get_constraintdef(con.oid) not like '%SET NULL (%'
    ) then
        raise exception 'Hay una FK con SET NULL sin columna acotada: anularia company_id';
    end if;
end $$;
