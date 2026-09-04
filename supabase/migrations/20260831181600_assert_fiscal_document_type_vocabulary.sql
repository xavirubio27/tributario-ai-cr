-- ============================================================================
-- Guardia de vocabulario: document_type admite EXACTAMENTE cuatro valores
--
-- POR QUE EXISTE. La migracion `20260831154210_add_ticket_fiscal_document_type`
-- YA FUE APLICADA y no se edita: su historia se preserva. Sus comprobaciones
-- usaban `pg_get_constraintdef(...) LIKE '%ticket%'`, y esa tecnica es fragil:
--
--     - depende del orden textual de los valores en el ARRAY;
--     - depende de como el motor imprima los casts (`'invoice'::text`);
--     - depende del formato de pg_get_constraintdef, que no es un contrato;
--     - una subcadena no distingue `ticket` de `ticket_borrador`;
--     - y, sobre todo, NO demuestra que el conjunto sea EXACTO: un valor de mas
--       pasaria inadvertido.
--
-- COMO SE VERIFICA AQUI. No se lee el texto de la restriccion: se EJECUTA.
-- Se toma la definicion efectiva del CHECK, se re-adjunta a una tabla temporal
-- y se prueba el comportamiento real valor a valor. Asi el resultado es
-- inmune al orden, a los casts y al formato de impresion.
--
-- ALCANCE DE LA GARANTIA, dicho con precision. Una restriccion sobre `text` no
-- puede probarse exhaustivamente: el dominio es infinito. Lo que aqui se
-- demuestra es que, sobre un UNIVERSO DE CANDIDATOS explicito -que incluye los
-- cuatro tipos validos, los tipos de comprobante del catalogo v4.4 aun no
-- incorporados, y las variantes de forma que un error tipico produciria-, el
-- conjunto aceptado es EXACTAMENTE el esperado. No se afirma mas que eso.
--
-- Esta migracion NO cambia el esquema, NO toca datos y NO amplia el
-- vocabulario. Solo detiene el despliegue ante una deriva.
-- ============================================================================

do $$
declare
    v_def        text;
    v_valor      text;
    v_aceptados  text[] := '{}';
    v_esperados  text[] := array['invoice', 'ticket', 'credit_note', 'debit_note'];
    v_candidatos text[] := array[
        -- Los cuatro que deben aceptarse.
        'invoice', 'ticket', 'credit_note', 'debit_note',
        -- Tipos del catalogo oficial v4.4 que NO se han incorporado todavia.
        -- Si alguno empezara a aceptarse sin decision, es deriva.
        'receipt', 'purchase_invoice', 'export_invoice', 'payment_receipt',
        'receiver_message', 'treasury_message',
        -- Codigos oficiales: la columna usa vocabulario propio, no codigos.
        '01', '02', '03', '04', '08', '09', '10',
        -- Nombres de la raiz XML: tampoco son el vocabulario interno.
        'FacturaElectronica', 'TiqueteElectronico',
        'NotaCreditoElectronica', 'NotaDebitoElectronica',
        -- Variantes de forma que un error tipico produciria.
        'Invoice', 'INVOICE', 'TICKET', 'Ticket',
        ' invoice', 'invoice ', ' ticket', 'ticket ',
        'invoices', 'tickets', 'ticket_borrador', 'credit_notes',
        'credit note', 'creditnote', 'debit-note',
        '', ' ', 'unknown_document_type', 'null', 'NULL'
    ];
begin
    -- 1. La restriccion debe existir sobre la tabla y columna esperadas.
    select pg_get_constraintdef(con.oid) into v_def
    from pg_constraint con
    join pg_class c on c.oid = con.conrelid
    join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'fiscal'
      and c.relname = 'electronic_documents'
      and con.conname = 'electronic_documents_document_type_check';

    if v_def is null then
        raise exception
            'Deriva: no existe fiscal.electronic_documents_document_type_check';
    end if;

    -- 2. La columna sigue siendo text NOT NULL: si fuese nullable, un NULL
    --    esquivaria el CHECK y el vocabulario dejaria de ser exhaustivo.
    if not exists (
        select 1 from information_schema.columns
        where table_schema = 'fiscal'
          and table_name   = 'electronic_documents'
          and column_name  = 'document_type'
          and data_type    = 'text'
          and is_nullable  = 'NO'
    ) then
        raise exception 'Deriva: document_type no es text NOT NULL';
    end if;

    -- 3. Se re-adjunta la restriccion REAL a una tabla temporal y se prueba su
    --    comportamiento. No se interpreta su texto en ningun momento.
    create temporary table _vocabulario_probe (document_type text) on commit drop;
    execute format(
        'alter table _vocabulario_probe add constraint _probe_chk %s', v_def
    );

    foreach v_valor in array v_candidatos loop
        begin
            insert into _vocabulario_probe (document_type) values (v_valor);
            v_aceptados := v_aceptados || v_valor;
        exception
            when check_violation then
                null;  -- rechazado: es lo esperado para los no validos
        end;
    end loop;

    -- 4. El conjunto aceptado debe coincidir EXACTAMENTE con el esperado.
    --    Se comparan como conjuntos: el orden no importa.
    if not (v_aceptados @> v_esperados and v_esperados @> v_aceptados) then
        raise exception
            'Deriva del vocabulario de document_type.  esperado=%  aceptado=%  definicion=%',
            v_esperados, v_aceptados, v_def;
    end if;

    drop table _vocabulario_probe;
end $$;
