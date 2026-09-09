-- ============================================================================
-- Identificacion/Numero puede venir PRESENTE Y VACIO
--
-- HALLAZGO (fase E4-B, subfase B2, ronda R3). Tercera restriccion nuestra mas
-- estricta que la fuente que aparece al implementar el parser, y del mismo
-- patron que la de B2-R1: un elemento OBLIGATORIO cuyo TEXTO puede ser vacio.
--
-- EVIDENCIA, leida de los cuatro XSD versionados en
-- backend/resources/fiscal/xsd/cr/esquemas/v4_4:
--
--     esquema  parte      Identificacion   Tipo                  Numero
--     FE       Emisor     1..1             1..1 enum(01..06)     1..1 maxLength=20
--     FE       Receptor   1..1             1..1 enum(01..06)     1..1 maxLength=20
--     TE       Emisor     1..1             1..1 enum(01..06)     1..1 maxLength=20
--     TE       Receptor   0..1             1..1 enum(01..06)     1..1 maxLength=20
--     NC       Emisor     1..1             1..1 enum(01..06)     1..1 maxLength=20
--     NC       Receptor   0..1             1..1 enum(01..06)     1..1 maxLength=20
--     ND       Emisor     1..1             1..1 enum(01..06)     1..1 maxLength=20
--     ND       Receptor   0..1             1..1 enum(01..06)     1..1 maxLength=20
--
-- `Numero` NO declara `minLength` en ningun esquema. Al no haber minimo, la
-- cadena vacia es un valor lexico legal. Verificado contra el validador
-- oficial: `<Numero></Numero>` valida, para emisor y para receptor.
--
-- El CHECK actual exige `char_length >= 1`, de modo que HOY rechazariamos ese
-- comprobante XSD-valido.
--
-- LA ASIMETRIA CON `Tipo` ES DE LA FUENTE. `Tipo` es `xs:string` con SEIS
-- enumeraciones (01..06); la cadena vacia no esta entre ellas, asi que para el
-- no es un estado legal y su CHECK de formato NO se toca.
--
-- TRES ESTADOS, NO DOS. La distincion que importa no es vacio/no vacio:
--
--     Identificacion ausente           ->  ambas columnas NULL
--     Identificacion con Numero=''     ->  tipo NOT NULL, numero = ''
--     Identificacion con Numero='...'  ->  tipo NOT NULL, numero = texto
--
-- Colapsar el segundo en el primero diria que el emisor no identifico a la
-- parte, cuando si la identifico: con un numero vacio.
--
-- LA REGLA DE SOLIDARIDAD DE B0.1 NO SE DEBILITA. En PostgreSQL '' es NOT
-- NULL, asi que un receptor con `tipo` valido y `numero = ''` sigue estando en
-- el estado "ambos presentes" y satisface
-- `document_parties_identification_presence_check` sin cambiarlo. El emisor
-- sigue obligado a traer los dos.
--
-- ALCANCE. Se sustituye UNICAMENTE el CHECK de longitud de
-- `identification_number`. No se tocan: la nulabilidad, el CHECK de presencia
-- por rol, el CHECK de formato de `identification_type_code`, los CHECK de
-- `legal_name`, `trade_name` y `role`, la clave primaria, la clave foranea
-- compuesta por tenant, el UNIQUE por rol, los indices, RLS ni las politicas.
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
    select pg_get_constraintdef(con.oid) into v_def
    from pg_constraint con
    join pg_class c on c.oid = con.conrelid
    join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'fiscal' and c.relname = 'document_parties'
      and con.conname = 'document_parties_identification_number_check';
    if v_def is null then
        raise exception 'Deriva: falta document_parties_identification_number_check';
    end if;
    if v_def not like '%char_length(identification_number) >= 1%' then
        raise exception 'Deriva: el CHECK de longitud no es el esperado: %', v_def;
    end if;

    -- La regla de presencia por rol de B0.1 debe existir y no se toca.
    if not exists (
        select 1 from pg_constraint con
        join pg_class c on c.oid = con.conrelid
        join pg_namespace n on n.oid = c.relnamespace
        where n.nspname='fiscal' and c.relname='document_parties'
          and con.conname='document_parties_identification_presence_check'
    ) then
        raise exception 'Deriva: falta el CHECK de presencia por rol de B0.1';
    end if;

    -- Ambas columnas siguen siendo text nullable (estado que dejo B0.1).
    if not exists (
        select 1 from information_schema.columns
        where table_schema='fiscal' and table_name='document_parties'
          and column_name in ('identification_type_code','identification_number')
          and data_type='text' and is_nullable='YES'
        having count(*) = 2
    ) then
        raise exception 'Deriva: las columnas de identificacion no son text nullable';
    end if;

    -- Toda fila valida bajo el CHECK viejo debe seguir siendolo bajo el nuevo.
    -- El nuevo es estrictamente MAS PERMISIVO; se comprueba igual, porque
    -- apoyarse en que DEV este vacio no es una justificacion de diseno.
    if exists (
        select 1 from fiscal.document_parties
        where identification_number is not null
          and char_length(identification_number) not between 0 and 20
    ) then
        raise exception 'Hay filas que no cumplirian el CHECK nuevo';
    end if;
end $$;

-- ---------------------------------------------------------------------------
-- El cambio: solo el limite inferior de longitud, de 1 a 0
-- ---------------------------------------------------------------------------
alter table fiscal.document_parties
    drop constraint document_parties_identification_number_check;

alter table fiscal.document_parties
    add constraint document_parties_identification_number_check
        check (char_length(identification_number) between 0 and 20);

comment on constraint document_parties_identification_number_check
    on fiscal.document_parties is
    'Numero es minOccurs=1 y xs:string SIN minLength en los cuatro XSD oficiales: el elemento es obligatorio, su texto puede ser vacio. NULL = Identificacion ausente (solo receptor de TE/NC/ND); cadena vacia = Identificacion presente con Numero vacio. La regla de solidaridad sigue cumpliendose porque en PostgreSQL la cadena vacia es NOT NULL.';

comment on column fiscal.document_parties.identification_number is
    'Numero de identificacion REPORTADO. NULL solo si el comprobante no trae el nodo Identificacion. Cadena vacia si lo trae con Numero vacio: son estados distintos. Nunca se sintetiza.';

-- ---------------------------------------------------------------------------
-- Verificacion POSTERIOR
-- ---------------------------------------------------------------------------
do $$
declare
    v_n integer;
    v_def text;
begin
    -- 1. El CHECK nuevo admite longitud 0.
    select pg_get_constraintdef(con.oid) into v_def
    from pg_constraint con join pg_class c on c.oid=con.conrelid
    join pg_namespace n on n.oid=c.relnamespace
    where n.nspname='fiscal' and c.relname='document_parties'
      and con.conname='document_parties_identification_number_check';
    if v_def is null or v_def not like '%>= 0%' then
        raise exception 'El CHECK de longitud no admite 0: %', v_def;
    end if;

    -- 2. `Tipo` NO se relajo: sigue exigiendo exactamente dos digitos.
    select pg_get_constraintdef(con.oid) into v_def
    from pg_constraint con join pg_class c on c.oid=con.conrelid
    join pg_namespace n on n.oid=c.relnamespace
    where n.nspname='fiscal' and c.relname='document_parties'
      and con.conname='document_parties_identification_type_check';
    if v_def not like '%[0-9]{2}%' then
        raise exception 'Se relajo identification_type_code, que exige 2 digitos';
    end if;

    -- 3. La nulabilidad no cambio.
    if not exists (
        select 1 from information_schema.columns
        where table_schema='fiscal' and table_name='document_parties'
          and column_name in ('identification_type_code','identification_number')
          and is_nullable='YES'
        having count(*) = 2
    ) then
        raise exception 'Cambio la nulabilidad de las columnas de identificacion';
    end if;

    -- 4. Sobreviven las 9 restricciones de la tabla.
    select count(*) into v_n
    from pg_constraint con join pg_class c on c.oid=con.conrelid
    join pg_namespace n on n.oid=c.relnamespace
    where n.nspname='fiscal' and c.relname='document_parties'
      and con.conname in (
        'document_parties_pkey',
        'document_parties_document_fkey',
        'document_parties_document_role_key',
        'document_parties_role_check',
        'document_parties_legal_name_check',
        'document_parties_trade_name_check',
        'document_parties_identification_type_check',
        'document_parties_identification_number_check',
        'document_parties_identification_presence_check'
      );
    if v_n <> 9 then
        raise exception 'Se perdieron restricciones: quedan % de 9', v_n;
    end if;

    -- 5. La regla de solidaridad de B0.1 sigue EXACTAMENTE igual.
    select pg_get_constraintdef(con.oid) into v_def
    from pg_constraint con join pg_class c on c.oid=con.conrelid
    join pg_namespace n on n.oid=c.relnamespace
    where n.nspname='fiscal' and c.relname='document_parties'
      and con.conname='document_parties_identification_presence_check';
    if v_def not like '%issuer%' or v_def not like '%receiver%' then
        raise exception 'Se altero el CHECK de presencia por rol: %', v_def;
    end if;

    -- 6. Indices intactos.
    if not exists (select 1 from pg_indexes where schemaname='fiscal'
                   and indexname='dparty_company_ident_idx')
    or not exists (select 1 from pg_indexes where schemaname='fiscal'
                   and indexname='document_parties_document_role_key') then
        raise exception 'Desaparecio un indice de document_parties';
    end if;

    -- 7. RLS y sus tres politicas siguen en pie.
    if not (select c.relrowsecurity from pg_class c
            join pg_namespace n on n.oid=c.relnamespace
            where n.nspname='fiscal' and c.relname='document_parties') then
        raise exception 'RLS quedo desactivada en document_parties';
    end if;
    select count(*) into v_n
    from pg_policy pol join pg_class c on c.oid=pol.polrelid
    join pg_namespace n on n.oid=c.relnamespace
    where n.nspname='fiscal' and c.relname='document_parties';
    if v_n <> 3 then
        raise exception 'document_parties quedo con % politicas RLS, se esperaban 3', v_n;
    end if;
end $$;
