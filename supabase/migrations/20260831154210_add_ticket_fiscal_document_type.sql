-- ============================================================================
-- Ampliacion del vocabulario interno: TiqueteElectronico -> 'ticket'
--
-- HALLAZGO (fase E4-A2, subfase A2-B). Un TiqueteElectronico v4.4 REAL,
-- aceptado por Hacienda, entro en el corpus de fixtures. La migracion
-- `20260830132124_create_fiscal_domain_tables` restringe:
--
--     document_type in ('invoice', 'credit_note', 'debit_note')
--
-- de modo que ese comprobante NO TIENE representacion valida. No es un fallo
-- de diseno: el modelo fisico (§11) eligio deliberadamente `text` + `CHECK`
-- en lugar de `enum` para que anadir un tipo fuese una migracion de
-- restriccion trivial, y ADR-025 ya situaba el Tiquete como el siguiente tipo.
-- Esta migracion es exactamente esa evolucion prevista.
--
-- VOCABULARIO. `document_type` es vocabulario PROPIO, no un catalogo de
-- Hacienda (modelo fisico §11): por eso aqui si procede validar el valor.
-- El mapeo entre el tipo fuente y el tipo normalizado queda:
--
--     FacturaElectronica       codigo 01  ->  invoice
--     NotaDebitoElectronica    codigo 02  ->  debit_note
--     NotaCreditoElectronica   codigo 03  ->  credit_note
--     TiqueteElectronico       codigo 04  ->  ticket        <-- se anade
--
-- POR QUE 'ticket' Y NO OTRO VALOR:
--
--   - Registro coherente con el vocabulario existente: ingles normalizado,
--     minusculas, snake_case, singular ('invoice', 'credit_note').
--   - NO se reutiliza 'invoice': eso borraria la distincion entre Factura y
--     Tiquete, que son tipos fiscales distintos con codigo oficial distinto.
--   - NO se usa el codigo oficial '04' como valor interno: la columna usa
--     vocabulario propio precisamente porque el catalogo oficial puede crecer,
--     y ya lo hizo en 2026.
--   - NO se usa 'receipt': queda RESERVADO para el Recibo Electronico de Pago
--     (codigo 10), que es un tipo distinto en la hoja de ruta de ADR-025.
--
-- ALCANCE. Se reemplaza UNICAMENTE el CHECK de `document_type`. No se tocan
-- datos, ni el tipo de la columna, ni su nullability, ni RLS, ni privilegios,
-- ni indices, ni ninguna otra restriccion. No se anaden tipos hipoteticos
-- (Factura de Compra, de Exportacion, Recibo de Pago): entraran cuando exista
-- evidencia real, como ha ocurrido aqui.
--
-- La migracion E3 permanece historicamente intacta: esto es una migracion
-- NUEVA, no una edicion de la anterior.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- Verificacion PREVIA: abortar ante cualquier deriva inesperada
-- ---------------------------------------------------------------------------
do $$
declare
    v_def text;
begin
    -- La tabla y la columna deben existir con la forma esperada.
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

    -- El CHECK previo debe ser exactamente el que dejo E3. Si alguien ya lo
    -- modifico, esta migracion no sabe sobre que esta actuando: se detiene.
    select pg_get_constraintdef(con.oid) into v_def
    from pg_constraint con
    join pg_class c on c.oid = con.conrelid
    join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'fiscal'
      and c.relname = 'electronic_documents'
      and con.conname = 'electronic_documents_document_type_check';

    if v_def is null then
        raise exception
            'Deriva: no existe electronic_documents_document_type_check';
    end if;

    if v_def not like '%invoice%'
       or v_def not like '%credit_note%'
       or v_def not like '%debit_note%' then
        raise exception
            'Deriva: el CHECK previo no admite los tres tipos esperados: %', v_def;
    end if;

    if v_def like '%ticket%' then
        raise exception
            'Deriva: el CHECK previo ya admite ticket; esta migracion ya se aplico';
    end if;

    -- Ninguna fila puede quedar fuera del vocabulario nuevo. El vocabulario
    -- solo crece, asi que esto no deberia fallar nunca; se comprueba porque
    -- una migracion que invalida datos existentes debe abortar, no truncar.
    if exists (
        select 1 from fiscal.electronic_documents
        where document_type not in ('invoice', 'ticket', 'credit_note', 'debit_note')
    ) then
        raise exception
            'Hay filas con un document_type fuera del vocabulario nuevo';
    end if;
end $$;

-- ---------------------------------------------------------------------------
-- El cambio: se reemplaza el CHECK, nada mas
-- ---------------------------------------------------------------------------
alter table fiscal.electronic_documents
    drop constraint electronic_documents_document_type_check;

alter table fiscal.electronic_documents
    add constraint electronic_documents_document_type_check
        check (document_type in ('invoice', 'ticket', 'credit_note', 'debit_note'));

comment on constraint electronic_documents_document_type_check
    on fiscal.electronic_documents is
    'Vocabulario propio, no catalogo de Hacienda. FacturaElectronica -> invoice (01), TiqueteElectronico -> ticket (04), NotaCreditoElectronica -> credit_note (03), NotaDebitoElectronica -> debit_note (02). "receipt" queda reservado para el Recibo Electronico de Pago (10).';

-- ---------------------------------------------------------------------------
-- Verificacion POSTERIOR de invariantes
-- ---------------------------------------------------------------------------
do $$
declare
    v_def  text;
    v_tipo text;
begin
    select pg_get_constraintdef(con.oid) into v_def
    from pg_constraint con
    join pg_class c on c.oid = con.conrelid
    join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'fiscal'
      and c.relname = 'electronic_documents'
      and con.conname = 'electronic_documents_document_type_check';

    -- 1. El CHECK existe y admite los cuatro tipos.
    if v_def is null then
        raise exception 'El CHECK de document_type desaparecio';
    end if;
    foreach v_tipo in array array['invoice', 'ticket', 'credit_note', 'debit_note'] loop
        if v_def not like '%' || v_tipo || '%' then
            raise exception 'El CHECK no admite %: %', v_tipo, v_def;
        end if;
    end loop;

    -- 2. No se colaron tipos que nadie ha decidido todavia.
    foreach v_tipo in array array['receipt', 'purchase_invoice', 'export_invoice'] loop
        if v_def like '%' || v_tipo || '%' then
            raise exception 'El CHECK admite un tipo no decidido: %', v_tipo;
        end if;
    end loop;

    -- 3. La columna no cambio de tipo ni de nullability.
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

    -- 4. RLS sigue activa sobre la tabla.
    if not (select relrowsecurity from pg_class c
            join pg_namespace n on n.oid = c.relnamespace
            where n.nspname = 'fiscal' and c.relname = 'electronic_documents') then
        raise exception 'RLS quedo desactivada en electronic_documents';
    end if;

    -- 5. El indice que usa document_type sigue existiendo.
    if not exists (
        select 1 from pg_indexes
        where schemaname = 'fiscal'
          and tablename  = 'electronic_documents'
          and indexname  = 'edoc_company_type_issued_idx'
    ) then
        raise exception 'Desaparecio edoc_company_type_issued_idx';
    end if;
end $$;
