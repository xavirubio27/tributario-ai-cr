-- ============================================================================
-- La fecha de emision puede no declarar desplazamiento (ADR-039)
--
-- HALLAZGO (fase E4-A2, subfase A2-B1). De 13 comprobantes v4.4 REALES
-- aceptados por Hacienda, CUATRO declaran FechaEmision sin desplazamiento:
-- tres Facturas Electronicas y el Tiquete Electronico.
--
--     con desplazamiento    2026-08-31T08:55:48-06:00     9 de 13
--     sin desplazamiento    2026-06-19T14:05:50           4 de 13
--
-- FUENTE ESTRUCTURAL. Los XSD v4.4 declaran el campo como tipo primitivo puro,
-- sin restriccion, sin patron y sin simpleType propio:
--
--     <xs:element name="FechaEmision" type="xs:dateTime"/>
--
-- En XML Schema el huso de `xs:dateTime` es OPCIONAL. Que Hacienda aceptara
-- esos cuatro documentos corrobora la lectura, pero la prueba es el esquema.
--
-- EL PROBLEMA. E2/E3 fijaron `issued_at timestamptz NOT NULL` junto a
-- `issued_at_offset_minutes NOT NULL`. Eso NO puede representar un datetime
-- civil sin huso sin inventar uno.
--
-- LO QUE ESTA MIGRACION NO HACE, EN NINGUN CASO:
--
--     no asume UTC                 no asume UTC-6
--     no asume zona de Costa Rica  no usa la zona del servidor
--     no infiere desplazamiento    no convierte naive -> instante
--
-- LA SEPARACION. Reloj de pared e instante absoluto dejan de ser lo mismo:
--
--     issued_at_local            timestamp     NOT NULL   siempre existe
--     issued_at                  timestamptz   NULL       solo si la fuente lo permite
--     issued_at_offset_minutes   smallint      NULL       solo el DECLARADO
--     issued_at_raw              text          NOT NULL   sin cambios
--
-- `FechaEmisionIR` recibe el mismo tratamiento en `document_references`: es el
-- mismo `xs:dateTime` sin restriccion, y el modelo fisico §17.1 ya exigia esa
-- paridad. Dejar ahi la misma asuncion seria dejar el mismo defecto.
--
-- Las migraciones anteriores permanecen historicamente intactas.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- Verificacion PREVIA: abortar ante deriva
-- ---------------------------------------------------------------------------
do $$
declare
    v_col record;
begin
    -- El estado de partida debe ser EXACTAMENTE el que dejo E3.
    for v_col in
        select * from (values
            ('electronic_documents', 'issued_at',                        'timestamp with time zone', 'NO'),
            ('electronic_documents', 'issued_at_offset_minutes',         'smallint',                 'NO'),
            ('electronic_documents', 'issued_at_raw',                    'text',                     'NO'),
            ('document_references',  'reported_reference_date',          'timestamp with time zone', 'NO'),
            ('document_references',  'reported_reference_offset_minutes','smallint',                 'NO'),
            ('document_references',  'reported_reference_date_raw',      'text',                     'NO')
        ) as t(tabla, columna, tipo, nul)
    loop
        if not exists (
            select 1 from information_schema.columns
            where table_schema = 'fiscal'
              and table_name   = v_col.tabla
              and column_name  = v_col.columna
              and data_type    = v_col.tipo
              and is_nullable  = v_col.nul
        ) then
            raise exception 'Deriva: fiscal.%.% no es % / nullable=%',
                v_col.tabla, v_col.columna, v_col.tipo, v_col.nul;
        end if;
    end loop;

    if exists (
        select 1 from information_schema.columns
        where table_schema = 'fiscal' and table_name = 'electronic_documents'
          and column_name = 'issued_at_local'
    ) then
        raise exception 'Deriva: issued_at_local ya existe; esta migracion ya se aplico';
    end if;

    -- Ninguna fila puede tener instante sin desplazamiento declarado: seria
    -- imposible derivar su reloj de pared sin inferir. Hoy ambas columnas son
    -- NOT NULL, asi que no deberia ocurrir; se comprueba porque una migracion
    -- que no puede convertir una fila debe ABORTAR, no rellenar a ojo.
    if exists (
        select 1 from fiscal.electronic_documents
        where issued_at is not null and issued_at_offset_minutes is null
    ) then
        raise exception
            'Hay filas con issued_at sin desplazamiento: no se puede derivar el reloj de pared sin inferir';
    end if;
    if exists (
        select 1 from fiscal.document_references
        where reported_reference_date is not null
          and reported_reference_offset_minutes is null
    ) then
        raise exception
            'Hay referencias con fecha sin desplazamiento: no se puede derivar el reloj de pared sin inferir';
    end if;
end $$;

-- ---------------------------------------------------------------------------
-- fiscal.electronic_documents
-- ---------------------------------------------------------------------------

alter table fiscal.electronic_documents
    add column issued_at_local timestamp without time zone null;

-- Backfill de filas preexistentes. El reloj de pared se deriva del instante y
-- del desplazamiento EXPLICITAMENTE ALMACENADO, nunca de la zona del servidor.
-- Comprobado empiricamente contra el motor:
--
--     instante 2026-08-31T14:55:48+00, offset -360
--       -> (instante at time zone 'UTC') + make_interval(mins => -360)
--       =  2026-08-31 08:55:48
--
-- `AT TIME ZONE 'UTC'` sobre timestamptz devuelve el reloj de pared en UTC de
-- forma determinista, sin consultar el `TimeZone` de la sesion.
update fiscal.electronic_documents
   set issued_at_local =
           (issued_at at time zone 'UTC')
           + make_interval(mins => issued_at_offset_minutes)
 where issued_at_local is null;

-- Si el backfill hubiese dejado algun nulo, este ALTER falla y la migracion
-- entera se revierte. No hay ruta silenciosa hacia un dato inventado.
alter table fiscal.electronic_documents
    alter column issued_at_local set not null;

alter table fiscal.electronic_documents
    alter column issued_at                drop not null,
    alter column issued_at_offset_minutes drop not null;

-- Coherencia: instante y desplazamiento van juntos o no van.
alter table fiscal.electronic_documents
    add constraint electronic_documents_issued_instant_check
        check ((issued_at is null) = (issued_at_offset_minutes is null));

-- Coherencia: cuando el instante existe, DEBE ser exactamente el reloj de
-- pared desplazado. Impide que ambas representaciones se contradigan.
-- `make_interval` y `timezone(text, timestamp)` son IMMUTABLE: verificado en
-- pg_proc antes de usarlas en un CHECK.
alter table fiscal.electronic_documents
    add constraint electronic_documents_issued_coherence_check
        check (
            issued_at is null
            or issued_at = (
                (issued_at_local - make_interval(mins => issued_at_offset_minutes))
                at time zone 'UTC'
            )
        );

comment on column fiscal.electronic_documents.issued_at_local is
    'Reloj de pared declarado por el documento. Existe SIEMPRE. No lleva huso: el documento puede no declararlo (ADR-039).';
comment on column fiscal.electronic_documents.issued_at is
    'Instante absoluto. NULL cuando la fuente no declara desplazamiento; nunca se infiere una zona horaria (ADR-039).';
comment on column fiscal.electronic_documents.issued_at_offset_minutes is
    'Desplazamiento DECLARADO por la fuente, en minutos. NULL si el documento no lo declara. Nunca inferido (ADR-039).';

-- ---------------------------------------------------------------------------
-- fiscal.document_references — misma regla, mismo `xs:dateTime` (§17.1)
-- ---------------------------------------------------------------------------

alter table fiscal.document_references
    add column reported_reference_date_local timestamp without time zone null;

update fiscal.document_references
   set reported_reference_date_local =
           (reported_reference_date at time zone 'UTC')
           + make_interval(mins => reported_reference_offset_minutes)
 where reported_reference_date_local is null;

alter table fiscal.document_references
    alter column reported_reference_date_local set not null;

alter table fiscal.document_references
    alter column reported_reference_date           drop not null,
    alter column reported_reference_offset_minutes drop not null;

alter table fiscal.document_references
    add constraint document_references_date_instant_check
        check (
            (reported_reference_date is null)
            = (reported_reference_offset_minutes is null)
        );

alter table fiscal.document_references
    add constraint document_references_date_coherence_check
        check (
            reported_reference_date is null
            or reported_reference_date = (
                (reported_reference_date_local
                 - make_interval(mins => reported_reference_offset_minutes))
                at time zone 'UTC'
            )
        );

comment on column fiscal.document_references.reported_reference_date_local is
    'Reloj de pared declarado por la referencia. Existe SIEMPRE (ADR-039).';

-- ---------------------------------------------------------------------------
-- Verificacion POSTERIOR de invariantes
-- ---------------------------------------------------------------------------
do $$
declare
    v_col record;
begin
    -- 1. Nulabilidad final exacta.
    for v_col in
        select * from (values
            ('electronic_documents', 'issued_at_local',                  'NO'),
            ('electronic_documents', 'issued_at',                        'YES'),
            ('electronic_documents', 'issued_at_offset_minutes',         'YES'),
            ('electronic_documents', 'issued_at_raw',                    'NO'),
            ('document_references',  'reported_reference_date_local',    'NO'),
            ('document_references',  'reported_reference_date',          'YES'),
            ('document_references',  'reported_reference_offset_minutes','YES'),
            ('document_references',  'reported_reference_date_raw',      'NO')
        ) as t(tabla, columna, nul)
    loop
        if not exists (
            select 1 from information_schema.columns
            where table_schema = 'fiscal'
              and table_name   = v_col.tabla
              and column_name  = v_col.columna
              and is_nullable  = v_col.nul
        ) then
            raise exception 'fiscal.%.% no quedo con nullable=%',
                v_col.tabla, v_col.columna, v_col.nul;
        end if;
    end loop;

    -- 2. Las columnas locales NO llevan huso: si fueran timestamptz habriamos
    --    reintroducido exactamente el problema que esto corrige.
    if exists (
        select 1 from information_schema.columns
        where table_schema = 'fiscal'
          and column_name in ('issued_at_local', 'reported_reference_date_local')
          and data_type <> 'timestamp without time zone'
    ) then
        raise exception 'Una columna local quedo con huso horario';
    end if;

    -- 3. El rango del desplazamiento sobrevive: XML Schema limita a +-840.
    if not exists (
        select 1 from pg_constraint con
        join pg_class c on c.oid = con.conrelid
        join pg_namespace n on n.oid = c.relnamespace
        where n.nspname = 'fiscal' and c.relname = 'electronic_documents'
          and con.conname = 'electronic_documents_offset_check'
    ) then
        raise exception 'Desaparecio el rango del desplazamiento en electronic_documents';
    end if;
    if not exists (
        select 1 from pg_constraint con
        join pg_class c on c.oid = con.conrelid
        join pg_namespace n on n.oid = c.relnamespace
        where n.nspname = 'fiscal' and c.relname = 'document_references'
          and con.conname = 'document_references_offset_check'
    ) then
        raise exception 'Desaparecio el rango del desplazamiento en document_references';
    end if;

    -- 4. Las cuatro restricciones nuevas existen.
    for v_col in
        select * from (values
            ('electronic_documents', 'electronic_documents_issued_instant_check'),
            ('electronic_documents', 'electronic_documents_issued_coherence_check'),
            ('document_references',  'document_references_date_instant_check'),
            ('document_references',  'document_references_date_coherence_check')
        ) as t(tabla, nombre)
    loop
        if not exists (
            select 1 from pg_constraint con
            join pg_class c on c.oid = con.conrelid
            join pg_namespace n on n.oid = c.relnamespace
            where n.nspname = 'fiscal' and c.relname = v_col.tabla
              and con.conname = v_col.nombre
        ) then
            raise exception 'Falta la restriccion %', v_col.nombre;
        end if;
    end loop;

    -- 5. RLS sigue activa en ambas tablas.
    if exists (
        select 1 from pg_class c join pg_namespace n on n.oid = c.relnamespace
        where n.nspname = 'fiscal'
          and c.relname in ('electronic_documents', 'document_references')
          and not c.relrowsecurity
    ) then
        raise exception 'RLS quedo desactivada en alguna tabla fiscal';
    end if;

    -- 6. Los indices que ordenan por issued_at siguen existiendo. Ahora la
    --    columna admite nulos: los documentos sin instante quedan agrupados en
    --    un extremo del indice en lugar de desaparecer (ver ADR-039).
    for v_col in
        select * from (values
            ('edoc_company_issued_idx'),
            ('edoc_company_type_issued_idx'),
            ('edoc_company_direction_issued_idx')
        ) as t(nombre)
    loop
        if not exists (
            select 1 from pg_indexes
            where schemaname = 'fiscal' and indexname = v_col.nombre
        ) then
            raise exception 'Desaparecio el indice %', v_col.nombre;
        end if;
    end loop;

    -- 7. Ninguna fila quedo en un estado que las nuevas reglas prohiben.
    if exists (
        select 1 from fiscal.electronic_documents
        where (issued_at is null) <> (issued_at_offset_minutes is null)
    ) then
        raise exception 'Hay filas con instante y desplazamiento descoordinados';
    end if;
end $$;
