-- ============================================================================
-- Correccion de compatibilidad: codigos de actividad economica
--
-- HALLAZGO (fase E4-A). Dos Facturas Electronicas v4.4 REALES, aceptadas por
-- Hacienda, declaran:
--
--     CodigoActividadEmisor = "6110.0"
--
-- Seis caracteres, pero con un punto. La migracion
-- `20260830132124_create_fiscal_domain_tables` exige `^[0-9]{6}$` en ambos
-- codigos de actividad, de modo que RECHAZARIA esos comprobantes.
--
-- FUENTE OFICIAL. El campo NO es numerico:
--
--     XSD v4.4      xs:string, minLength = 6, maxLength = 6   (sin patron)
--     Anexos v4.4   "String 6"; la validacion es que el codigo exista en el
--                   padron del RUT, no que tenga una forma numerica
--
-- Verificado que `CodigoActividadEmisor` y `CodigoActividadReceptor` comparten
-- exactamente la misma regla estructural, en el XSD y en los Anexos: la
-- correccion se aplica a los dos por evidencia, no por simetria supuesta.
--
-- SEPARACION DE CAPAS (ADR-030). Lo que aqui se impone es una restriccion de
-- CAPA 1, puramente estructural:
--
--     exactamente 6 caracteres          <-- lo que dice el esquema oficial
--     NO "seis digitos"                 <-- eso lo inventamos nosotros
--
-- Que el codigo EXISTA y sea valido contra el padron del RUT es validacion
-- semantica de CAPA 2 y NO se implementa aqui. No se introduce catalogo alguno.
--
-- Los valores de origen no se tocan: no se normaliza, no se elimina el punto,
-- no se convierte a numeric. `reported` sigue siendo lo que dijo el documento.
--
-- La migracion E3 permanece historicamente intacta: esto es una migracion
-- NUEVA, no una edicion de la anterior.
-- ============================================================================

alter table fiscal.electronic_documents
    drop constraint electronic_documents_issuer_activity_check,
    drop constraint electronic_documents_receiver_activity_check;

-- Emisor: la columna es NOT NULL, asi que basta la longitud.
alter table fiscal.electronic_documents
    add constraint electronic_documents_issuer_activity_check
        check (char_length(issuer_activity_code) = 6);

-- Receptor: la columna es NULLABLE y debe seguir admitiendo NULL.
-- `char_length(NULL) = 6` ya se evalua a NULL y un CHECK con resultado NULL
-- se satisface, pero se escribe explicito para que la intencion se lea sola.
alter table fiscal.electronic_documents
    add constraint electronic_documents_receiver_activity_check
        check (
            receiver_activity_code is null
            or char_length(receiver_activity_code) = 6
        );

comment on constraint electronic_documents_issuer_activity_check
    on fiscal.electronic_documents is
    'Capa 1: exactamente 6 caracteres, conforme al XSD v4.4 (xs:string 6). NO seis digitos: existen codigos reales como "6110.0". La validacion contra el padron del RUT es capa 2.';

comment on constraint electronic_documents_receiver_activity_check
    on fiscal.electronic_documents is
    'Capa 1: NULL, o exactamente 6 caracteres. Misma regla estructural que el codigo del emisor, verificada en XSD y Anexos v4.4.';

-- ---------------------------------------------------------------------------
-- Verificacion de invariantes
-- ---------------------------------------------------------------------------
do $$
declare
    v_def text;
begin
    -- 1. Ninguno de los dos conserva un patron numerico.
    if exists (
        select 1 from pg_constraint con
        join pg_class c on c.oid = con.conrelid
        join pg_namespace n on n.oid = c.relnamespace
        where n.nspname = 'fiscal' and c.relname = 'electronic_documents'
          and con.conname in ('electronic_documents_issuer_activity_check',
                              'electronic_documents_receiver_activity_check')
          and pg_get_constraintdef(con.oid) like '%[0-9]%'
    ) then
        raise exception 'Un codigo de actividad conserva un patron numerico';
    end if;

    -- 2. Ambos existen y comprueban longitud 6.
    foreach v_def in array array['issuer', 'receiver'] loop
        if not exists (
            select 1 from pg_constraint con
            join pg_class c on c.oid = con.conrelid
            join pg_namespace n on n.oid = c.relnamespace
            where n.nspname = 'fiscal' and c.relname = 'electronic_documents'
              and con.conname = 'electronic_documents_' || v_def || '_activity_check'
              and pg_get_constraintdef(con.oid) like '%char_length%= 6%'
        ) then
            raise exception 'Falta la restriccion de longitud 6 para %', v_def;
        end if;
    end loop;

    -- 3. La nullability de las columnas NO cambia.
    if (select is_nullable from information_schema.columns
        where table_schema = 'fiscal' and table_name = 'electronic_documents'
          and column_name = 'issuer_activity_code') <> 'NO' then
        raise exception 'issuer_activity_code dejo de ser NOT NULL';
    end if;
    if (select is_nullable from information_schema.columns
        where table_schema = 'fiscal' and table_name = 'electronic_documents'
          and column_name = 'receiver_activity_code') <> 'YES' then
        raise exception 'receiver_activity_code dejo de ser nullable';
    end if;

    -- 4. Los tipos siguen siendo texto: no se convirtio a numeric.
    if exists (
        select 1 from information_schema.columns
        where table_schema = 'fiscal' and table_name = 'electronic_documents'
          and column_name in ('issuer_activity_code', 'receiver_activity_code')
          and data_type <> 'text'
    ) then
        raise exception 'Un codigo de actividad dejo de ser text';
    end if;
end $$;
