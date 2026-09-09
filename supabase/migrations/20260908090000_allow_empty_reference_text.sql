-- ============================================================================
-- Numero y Razon de la referencia pueden venir PRESENTES Y VACIOS
--
-- HALLAZGO (fase E4-B, subfase B2, ronda R1). Al implementar el parser del
-- cuerpo de la transaccion se comparo el esquema fisico con los XSD oficiales
-- versionados, y aparecio otra restriccion nuestra MAS ESTRICTA que la fuente.
--
-- EVIDENCIA, leida de los cuatro XSD versionados en
-- backend/resources/fiscal/xsd/cr/esquemas/v4_4:
--
--     esquema   elemento   minOccurs   minLength   maxLength
--     FE        Numero     0           (ninguno)   50
--     FE        Razon      0           (ninguno)   180
--     TE        Numero     0           (ninguno)   50
--     TE        Razon      0           (ninguno)   180
--     NC        Numero     0           (ninguno)   50
--     NC        Razon      0           (ninguno)   180
--     ND        Numero     0           (ninguno)   50
--     ND        Razon      0           (ninguno)   180
--
-- Al no declarar `minLength`, el tipo admite la cadena vacia. Es decir, la
-- fuente distingue TRES estados, no dos:
--
--     elemento ausente          ->  NULL
--     elemento presente vacio   ->  ''
--     elemento con texto        ->  el texto reportado
--
-- Los CHECK actuales exigen `char_length >= 1`, de modo que HOY rechazariamos
-- un comprobante XSD-valido que trajera `<Numero></Numero>` o `<Razon></Razon>`.
-- Verificado contra el validador oficial: ambos casos validan.
--
-- NULL NO ES LO MISMO QUE ''. La distincion es deliberada y se conserva:
-- NULL significa que el emisor no incluyo el elemento; '' significa que lo
-- incluyo vacio. No se normaliza '' a NULL ni al reves, ni en el parser ni
-- aqui: eso destruiria un estado que la fuente si expresa.
--
-- ALCANCE. Se sustituyen UNICAMENTE los dos CHECK de longitud. No se tocan:
-- la nulabilidad, la clave primaria, la clave foranea compuesta por tenant, la
-- clave foranea de resolucion, el UNIQUE por secuencia, los CHECK de fecha,
-- desplazamiento, secuencia y codigos, los indices, RLS ni las politicas.
--
-- `reference_code` y `referenced_document_type_code` NO se relajan: sus tipos
-- (`CodigoReferenciaType`, `TipoDocReferenciaType`) declaran
-- minLength=maxLength=2, asi que para ellos el vacio no es un estado legal.
--
-- Las migraciones anteriores permanecen historicamente intactas.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- Verificacion PREVIA: abortar ante deriva
-- ---------------------------------------------------------------------------
do $$
declare
    v_def text;
begin
    -- Estado de partida exacto de los dos CHECK que se van a sustituir.
    select pg_get_constraintdef(con.oid) into v_def
    from pg_constraint con
    join pg_class c on c.oid = con.conrelid
    join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'fiscal' and c.relname = 'document_references'
      and con.conname = 'document_references_number_check';
    if v_def is null then
        raise exception 'Deriva: falta document_references_number_check';
    end if;
    if v_def not like '%char_length(reported_number) >= 1%' then
        raise exception 'Deriva: document_references_number_check no es el esperado: %', v_def;
    end if;

    select pg_get_constraintdef(con.oid) into v_def
    from pg_constraint con
    join pg_class c on c.oid = con.conrelid
    join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'fiscal' and c.relname = 'document_references'
      and con.conname = 'document_references_reason_check';
    if v_def is null then
        raise exception 'Deriva: falta document_references_reason_check';
    end if;
    if v_def not like '%char_length(reason) >= 1%' then
        raise exception 'Deriva: document_references_reason_check no es el esperado: %', v_def;
    end if;

    -- Ambas columnas deben seguir siendo text nullable: esta migracion no
    -- toca la nulabilidad y no debe encontrarsela ya cambiada.
    if not exists (
        select 1 from information_schema.columns
        where table_schema='fiscal' and table_name='document_references'
          and column_name in ('reported_number','reason')
          and data_type='text' and is_nullable='YES'
        having count(*) = 2
    ) then
        raise exception 'Deriva: reported_number/reason no son text nullable';
    end if;

    -- Toda fila valida bajo el CHECK viejo debe seguir siendolo bajo el nuevo.
    -- El nuevo es estrictamente MAS PERMISIVO -solo baja el minimo de 1 a 0-,
    -- asi que la comprobacion no puede fallar; se hace igual, porque apoyarse
    -- en que DEV este vacio no es una justificacion de diseno.
    if exists (
        select 1 from fiscal.document_references
        where (reported_number is not null
               and char_length(reported_number) not between 0 and 50)
           or (reason is not null
               and char_length(reason) not between 0 and 180)
    ) then
        raise exception 'Hay filas que no cumplirian los CHECK nuevos';
    end if;
end $$;

-- ---------------------------------------------------------------------------
-- El cambio: solo el limite inferior de longitud, de 1 a 0
-- ---------------------------------------------------------------------------
alter table fiscal.document_references
    drop constraint document_references_number_check,
    drop constraint document_references_reason_check;

alter table fiscal.document_references
    add constraint document_references_number_check
        check (char_length(reported_number) between 0 and 50),
    add constraint document_references_reason_check
        check (char_length(reason) between 0 and 180);

comment on constraint document_references_number_check
    on fiscal.document_references is
    'Numero es 0..1 y xs:string SIN minLength en los cuatro XSD oficiales: la cadena vacia es un valor legal. NULL = el emisor no incluyo el elemento; cadena vacia = lo incluyo vacio. No se normaliza uno en otro.';
comment on constraint document_references_reason_check
    on fiscal.document_references is
    'Razon es 0..1 y xs:string SIN minLength en los cuatro XSD oficiales: la cadena vacia es un valor legal. NULL = elemento ausente; cadena vacia = elemento presente y vacio.';

comment on column fiscal.document_references.reported_number is
    'Numero REPORTADO del documento referido. NULL si el elemento no viene; cadena vacia si viene vacio. Tres estados distintos, conservados tal cual.';
comment on column fiscal.document_references.reason is
    'Razon REPORTADA de la referencia. NULL si el elemento no viene; cadena vacia si viene vacio. No se recorta ni se normaliza el texto del contribuyente.';

-- ---------------------------------------------------------------------------
-- Verificacion POSTERIOR
-- ---------------------------------------------------------------------------
do $$
declare
    v_n integer;
    v_def text;
begin
    -- 1. Los CHECK nuevos existen y admiten longitud 0.
    select pg_get_constraintdef(con.oid) into v_def
    from pg_constraint con join pg_class c on c.oid=con.conrelid
    join pg_namespace n on n.oid=c.relnamespace
    where n.nspname='fiscal' and c.relname='document_references'
      and con.conname='document_references_number_check';
    if v_def is null or v_def not like '%>= 0%' then
        raise exception 'document_references_number_check no admite longitud 0: %', v_def;
    end if;

    select pg_get_constraintdef(con.oid) into v_def
    from pg_constraint con join pg_class c on c.oid=con.conrelid
    join pg_namespace n on n.oid=c.relnamespace
    where n.nspname='fiscal' and c.relname='document_references'
      and con.conname='document_references_reason_check';
    if v_def is null or v_def not like '%>= 0%' then
        raise exception 'document_references_reason_check no admite longitud 0: %', v_def;
    end if;

    -- 2. La nulabilidad NO cambio.
    if not exists (
        select 1 from information_schema.columns
        where table_schema='fiscal' and table_name='document_references'
          and column_name in ('reported_number','reason') and is_nullable='YES'
        having count(*) = 2
    ) then
        raise exception 'Cambio la nulabilidad de reported_number/reason';
    end if;

    -- 3. Sobreviven las 12 restricciones de la tabla: se sustituyeron dos por
    --    otras dos del mismo nombre, no se perdio ninguna.
    select count(*) into v_n
    from pg_constraint con join pg_class c on c.oid=con.conrelid
    join pg_namespace n on n.oid=c.relnamespace
    where n.nspname='fiscal' and c.relname='document_references'
      and con.conname in (
        'document_references_pkey',
        'document_references_document_fkey',
        'document_references_resolved_fkey',
        'document_references_document_sequence_key',
        'document_references_sequence_check',
        'document_references_type_code_check',
        'document_references_reference_code_check',
        'document_references_offset_check',
        'document_references_date_instant_check',
        'document_references_date_coherence_check',
        'document_references_number_check',
        'document_references_reason_check'
      );
    if v_n <> 12 then
        raise exception 'Se perdieron restricciones: quedan % de 12', v_n;
    end if;

    -- 4. Los codigos de longitud fija NO se relajaron.
    select pg_get_constraintdef(con.oid) into v_def
    from pg_constraint con join pg_class c on c.oid=con.conrelid
    join pg_namespace n on n.oid=c.relnamespace
    where n.nspname='fiscal' and c.relname='document_references'
      and con.conname='document_references_reference_code_check';
    if v_def not like '%[0-9]{2}%' then
        raise exception 'Se relajo reference_code, que exige exactamente 2 digitos';
    end if;

    -- 5. Indices intactos.
    if not exists (select 1 from pg_indexes where schemaname='fiscal'
                   and indexname='dref_company_resolved_idx')
    or not exists (select 1 from pg_indexes where schemaname='fiscal'
                   and indexname='dref_company_unresolved_idx')
    or not exists (select 1 from pg_indexes where schemaname='fiscal'
                   and indexname='document_references_document_sequence_key') then
        raise exception 'Desaparecio un indice de document_references';
    end if;

    -- 6. RLS y sus tres politicas siguen en pie.
    if not (select c.relrowsecurity from pg_class c
            join pg_namespace n on n.oid=c.relnamespace
            where n.nspname='fiscal' and c.relname='document_references') then
        raise exception 'RLS quedo desactivada en document_references';
    end if;
    select count(*) into v_n
    from pg_policy pol join pg_class c on c.oid=pol.polrelid
    join pg_namespace n on n.oid=c.relnamespace
    where n.nspname='fiscal' and c.relname='document_references';
    if v_n <> 3 then
        raise exception 'document_references quedo con % politicas RLS, se esperaban 3', v_n;
    end if;
end $$;
