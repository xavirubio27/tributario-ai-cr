-- ============================================================================
-- Vocabulario EXACTO de document_type: se instala la definicion canonica
--
-- POR QUE EXISTE. La migracion anterior
-- `20260831181600_assert_fiscal_document_type_vocabulary` YA FUE APLICADA y no
-- se edita. Intentaba demostrar la exactitud del vocabulario probando un
-- universo FINITO de candidatos contra la restriccion vigente.
--
-- Esa tecnica es util como deteccion de deriva, pero NO demuestra el dominio:
-- `document_type` es `text`, su dominio es infinito, y ninguna lista de
-- ejemplos negativos —por larga que sea— prueba que no exista un quinto valor
-- aceptado. La exactitud no puede venir de enumerar lo que se rechaza.
--
-- DE DONDE VIENE AQUI LA EXACTITUD. De la DEFINICION, no de las pruebas. Se
-- reemplaza la restriccion por una pertenencia a conjunto cerrado:
--
--     CHECK (document_type in ('invoice','ticket','credit_note','debit_note'))
--
-- Un `IN` sobre un conjunto literal es un predicado de pertenencia: acepta un
-- valor si y solo si es igual a uno de los cuatro. Con la columna declarada
-- `NOT NULL`, el dominio efectivo de la columna es EXACTAMENTE esos cuatro
-- valores, por construccion y no por muestreo. Las pruebas de comportamiento
-- pasan a ser corroboracion, no fundamento.
--
-- El vocabulario NO cambia: son los mismos cuatro valores que ya admitia la
-- migracion de A2-B0. Lo que cambia es de donde procede la garantia.
--
-- HISTORIA, que no se reescribe:
--
--     E3       vocabulario original: invoice, credit_note, debit_note
--     A2-B0    anade `ticket` al aparecer un TiqueteElectronico real
--     A2-B1    intenta asegurar exactitud por universo de candidatos
--     A2-B2    instala la definicion canonica: la exactitud viene del CHECK
--
-- Se mantiene `text` + `CHECK`. NO se convierte a `enum`: el modelo fisico §11
-- eligio `text` para que anadir un tipo sea una migracion de restriccion y no
-- una de tipo, y esa decision sigue vigente.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- Verificacion PREVIA
-- ---------------------------------------------------------------------------
do $$
declare
    v_n           integer;
    v_incompat    text;
begin
    -- 1. La tabla y la columna, con la forma esperada.
    if not exists (
        select 1 from information_schema.columns
        where table_schema = 'fiscal'
          and table_name   = 'electronic_documents'
          and column_name  = 'document_type'
          and data_type    = 'text'
          and is_nullable  = 'NO'
    ) then
        raise exception
            'Deriva: fiscal.electronic_documents.document_type no es text NOT NULL';
    end if;

    -- 2. RLS intacta antes de tocar nada.
    if not (
        select c.relrowsecurity from pg_class c
        join pg_namespace n on n.oid = c.relnamespace
        where n.nspname = 'fiscal' and c.relname = 'electronic_documents'
    ) then
        raise exception 'Deriva: RLS desactivada en fiscal.electronic_documents';
    end if;

    -- 3. Debe existir exactamente UNA restriccion de document_type. Si hubiera
    --    varias, reemplazar una sola dejaria la otra gobernando en silencio.
    select count(*) into v_n
    from pg_constraint con
    join pg_class c on c.oid = con.conrelid
    join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'fiscal'
      and c.relname = 'electronic_documents'
      and con.contype = 'c'
      and pg_get_constraintdef(con.oid) like '%document_type%';

    if v_n <> 1 then
        raise exception
            'Deriva: se esperaba 1 restriccion CHECK sobre document_type, hay %', v_n;
    end if;

    -- 4. Ningun dato existente puede quedar fuera del vocabulario. Una
    --    migracion que invalidaria filas debe ABORTAR, no forzar el cambio.
    select string_agg(distinct document_type, ', ') into v_incompat
    from fiscal.electronic_documents
    where document_type not in ('invoice', 'ticket', 'credit_note', 'debit_note');

    if v_incompat is not null then
        raise exception
            'Hay filas con document_type fuera del vocabulario: %', v_incompat;
    end if;
end $$;

-- ---------------------------------------------------------------------------
-- El cambio: se instala la definicion canonica. Nada mas.
-- ---------------------------------------------------------------------------
alter table fiscal.electronic_documents
    drop constraint electronic_documents_document_type_check;

alter table fiscal.electronic_documents
    add constraint electronic_documents_document_type_check
        check (
            document_type in (
                'invoice',
                'ticket',
                'credit_note',
                'debit_note'
            )
        );

comment on constraint electronic_documents_document_type_check
    on fiscal.electronic_documents is
    'Vocabulario propio y CERRADO. La exactitud viene de esta definicion: pertenencia a conjunto literal sobre una columna NOT NULL, no de enumerar valores rechazados. FacturaElectronica -> invoice (01), TiqueteElectronico -> ticket (04), NotaCreditoElectronica -> credit_note (03), NotaDebitoElectronica -> debit_note (02). "receipt" queda reservado para el Recibo Electronico de Pago (10).';

-- ---------------------------------------------------------------------------
-- Verificacion POSTERIOR
-- ---------------------------------------------------------------------------
do $$
declare
    v_n     integer;
    v_def   text;
    v_valor text;
begin
    -- 1. Sigue habiendo exactamente una restriccion de document_type.
    select count(*) into v_n
    from pg_constraint con
    join pg_class c on c.oid = con.conrelid
    join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'fiscal'
      and c.relname = 'electronic_documents'
      and con.contype = 'c'
      and pg_get_constraintdef(con.oid) like '%document_type%';

    if v_n <> 1 then
        raise exception
            'Quedaron % restricciones sobre document_type; debe haber exactamente 1', v_n;
    end if;

    select pg_get_constraintdef(con.oid) into v_def
    from pg_constraint con
    join pg_class c on c.oid = con.conrelid
    join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'fiscal'
      and c.relname = 'electronic_documents'
      and con.conname = 'electronic_documents_document_type_check';

    if v_def is null then
        raise exception 'La restriccion canonica no quedo instalada';
    end if;

    -- 2. Corroboracion por comportamiento. NO es de donde viene la garantia
    --    —esa la da la definicion de arriba—, pero confirma que el motor la
    --    interpreta como se espera.
    create temporary table _dt_probe (document_type text) on commit drop;
    execute format(
        'alter table _dt_probe add constraint _dt_chk %s', v_def
    );

    foreach v_valor in array array['invoice', 'ticket', 'credit_note', 'debit_note'] loop
        begin
            insert into _dt_probe (document_type) values (v_valor);
        exception when check_violation then
            raise exception 'La restriccion canonica rechaza %, que debe aceptar', v_valor;
        end;
    end loop;

    foreach v_valor in array array['receipt', 'unknown', 'TICKET', 'ticket ', ''] loop
        begin
            insert into _dt_probe (document_type) values (v_valor);
            raise exception 'La restriccion canonica acepta %, que debe rechazar', v_valor;
        exception when check_violation then
            null;
        end;
    end loop;

    drop table _dt_probe;

    -- 3. La columna no cambio.
    if not exists (
        select 1 from information_schema.columns
        where table_schema = 'fiscal'
          and table_name   = 'electronic_documents'
          and column_name  = 'document_type'
          and data_type    = 'text'
          and is_nullable  = 'NO'
    ) then
        raise exception 'document_type dejo de ser text NOT NULL';
    end if;

    -- 4. RLS y el indice que usa la columna siguen en pie.
    if not (
        select c.relrowsecurity from pg_class c
        join pg_namespace n on n.oid = c.relnamespace
        where n.nspname = 'fiscal' and c.relname = 'electronic_documents'
    ) then
        raise exception 'RLS quedo desactivada';
    end if;

    if not exists (
        select 1 from pg_indexes
        where schemaname = 'fiscal'
          and indexname  = 'edoc_company_type_issued_idx'
    ) then
        raise exception 'Desaparecio edoc_company_type_issued_idx';
    end if;
end $$;
