-- ============================================================================
-- El receptor puede no estar identificado (fuente oficial v4.4)
--
-- HALLAZGO (fase E4-B, subfase B0). Al disenar el contrato del parser se
-- comparo el esquema fisico con los XSD oficiales versionados, y aparecio una
-- restriccion nuestra MAS ESTRICTA que la fuente.
--
-- EVIDENCIA, leida de los XSD versionados en backend/resources/fiscal/xsd/cr:
--
--     tipo   parte      elemento    Nombre   Identificacion
--     FE     Receptor   min=1       min=1    min=1
--     TE     Receptor   min=0       min=1    min=0     <-- opcional
--     NC     Receptor   min=0       min=1    min=0     <-- opcional
--     ND     Receptor   min=0       min=1    min=0     <-- opcional
--
-- Es decir: en Tiquete, Nota de Credito y Nota de Debito un `Receptor` puede
-- venir con `Nombre` y SIN `Identificacion`, y eso es XSD-valido. Tiene
-- sentido: el tiquete es el comprobante del consumidor final, que puede
-- quedar nombrado sin identificar.
--
-- `document_parties.identification_type_code` e `identification_number` son
-- NOT NULL, de modo que HOY rechazariamos esos comprobantes.
--
-- ESTADOS LEGALES, exactamente dos. `IdentificacionType` declara `Tipo` y
-- `Numero` ambos con min=1, asi que si el nodo existe, existen los dos:
--
--     Identificacion ausente   ->  ambas columnas NULL
--     Identificacion presente  ->  ambas columnas NOT NULL
--
-- Un estado PARCIAL -tipo sin numero, o numero sin tipo- es imposible en la
-- fuente, y el CHECK nuevo lo impide tambien aqui.
--
-- EL EMISOR NO CAMBIA. En los cuatro tipos su `Identificacion` es min=1: sigue
-- siendo obligatoria, y el CHECK lo exige explicitamente.
--
-- NUNCA SE INVENTA UNA IDENTIFICACION. La ausencia en la fuente se representa
-- como NULL. No se sintetiza un "consumidor final", ni ceros, ni cadena vacia,
-- ni se hereda la del emisor o la de la empresa-tenant. ABSENT != EMPTY.
--
-- ALCANCE. Solo se relaja la nulabilidad de esas dos columnas y se anade el
-- CHECK que preserva las reglas. No se tocan: clave primaria, clave foranea
-- compuesta por tenant, UNIQUE por rol, los CHECK de formato, los indices, RLS
-- ni las politicas. Los CHECK de formato ya toleran NULL -un CHECK solo falla
-- si evalua FALSE; con NULL evalua UNKNOWN y pasa-, verificado contra el motor.
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
    -- Estado de partida exacto.
    for v_col in
        select * from (values
            ('identification_type_code', 'NO'),
            ('identification_number',    'NO'),
            ('role',                     'NO'),
            ('legal_name',               'NO')
        ) as t(columna, nul)
    loop
        if not exists (
            select 1 from information_schema.columns
            where table_schema = 'fiscal'
              and table_name   = 'document_parties'
              and column_name  = v_col.columna
              and data_type    = 'text'
              and is_nullable  = v_col.nul
        ) then
            raise exception 'Deriva: fiscal.document_parties.% no es text nullable=%',
                v_col.columna, v_col.nul;
        end if;
    end loop;

    if exists (
        select 1 from pg_constraint con
        join pg_class c on c.oid = con.conrelid
        join pg_namespace n on n.oid = c.relnamespace
        where n.nspname = 'fiscal' and c.relname = 'document_parties'
          and con.conname = 'document_parties_identification_presence_check'
    ) then
        raise exception 'Deriva: esta migracion ya se aplico';
    end if;

    -- Ninguna fila existente puede violar la regla nueva. Hoy DEV esta vacio,
    -- pero la migracion NO se apoya en eso: si hubiera filas, deben cumplirla.
    if exists (
        select 1 from fiscal.document_parties
        where not (
            (role = 'issuer'
             and identification_type_code is not null
             and identification_number is not null)
            or
            (role = 'receiver'
             and (identification_type_code is null) = (identification_number is null))
        )
    ) then
        raise exception
            'Hay filas que no cumplirian la regla nueva de identificacion';
    end if;
end $$;

-- ---------------------------------------------------------------------------
-- El cambio
-- ---------------------------------------------------------------------------
alter table fiscal.document_parties
    alter column identification_type_code drop not null,
    alter column identification_number    drop not null;

-- El emisor sigue obligado; el receptor puede no traer identificacion, pero
-- nunca a medias.
alter table fiscal.document_parties
    add constraint document_parties_identification_presence_check
        check (
            (role = 'issuer'
             and identification_type_code is not null
             and identification_number is not null)
            or
            (role = 'receiver'
             and (identification_type_code is null)
               = (identification_number is null))
        );

comment on constraint document_parties_identification_presence_check
    on fiscal.document_parties is
    'Emisor: identificacion obligatoria en los cuatro tipos (XSD min=1). Receptor: puede faltar por completo en TE/NC/ND (XSD min=0), pero nunca a medias, porque IdentificacionType exige Tipo y Numero juntos. La ausencia se representa NULL; jamas un valor sintetico.';

comment on column fiscal.document_parties.identification_type_code is
    'Tipo de identificacion REPORTADO. NULL solo si el comprobante no trae el nodo Identificacion, posible en el receptor de TE/NC/ND.';
comment on column fiscal.document_parties.identification_number is
    'Numero de identificacion REPORTADO. NULL solo si el comprobante no trae el nodo Identificacion. Nunca se sintetiza.';

-- ---------------------------------------------------------------------------
-- Verificacion POSTERIOR
-- ---------------------------------------------------------------------------
do $$
declare
    v_n integer;
begin
    -- 1. Nulabilidad final.
    if not exists (
        select 1 from information_schema.columns
        where table_schema='fiscal' and table_name='document_parties'
          and column_name='identification_type_code' and is_nullable='YES'
    ) or not exists (
        select 1 from information_schema.columns
        where table_schema='fiscal' and table_name='document_parties'
          and column_name='identification_number' and is_nullable='YES'
    ) then
        raise exception 'Las columnas de identificacion no quedaron nullable';
    end if;

    -- 2. `legal_name` y `role` NO se relajaron: el nombre es obligatorio en
    --    los cuatro tipos, para ambas partes.
    if exists (
        select 1 from information_schema.columns
        where table_schema='fiscal' and table_name='document_parties'
          and column_name in ('legal_name','role') and is_nullable <> 'NO'
    ) then
        raise exception 'Se relajo legal_name o role, que deben seguir NOT NULL';
    end if;

    -- 3. El CHECK nuevo existe.
    if not exists (
        select 1 from pg_constraint con
        join pg_class c on c.oid = con.conrelid
        join pg_namespace n on n.oid = c.relnamespace
        where n.nspname='fiscal' and c.relname='document_parties'
          and con.conname='document_parties_identification_presence_check'
    ) then
        raise exception 'No se instalo el CHECK de presencia de identificacion';
    end if;

    -- 4. Sobreviven las restricciones que NO debian tocarse.
    select count(*) into v_n
    from pg_constraint con
    join pg_class c on c.oid = con.conrelid
    join pg_namespace n on n.oid = c.relnamespace
    where n.nspname='fiscal' and c.relname='document_parties'
      and con.conname in (
        'document_parties_pkey',
        'document_parties_document_fkey',
        'document_parties_document_role_key',
        'document_parties_role_check',
        'document_parties_legal_name_check',
        'document_parties_trade_name_check',
        'document_parties_identification_type_check',
        'document_parties_identification_number_check'
      );
    if v_n <> 8 then
        raise exception 'Se perdieron restricciones preexistentes: quedan % de 8', v_n;
    end if;

    -- 5. Indices intactos.
    if not exists (select 1 from pg_indexes where schemaname='fiscal'
                   and indexname='dparty_company_ident_idx')
    or not exists (select 1 from pg_indexes where schemaname='fiscal'
                   and indexname='document_parties_document_role_key') then
        raise exception 'Desaparecio un indice de document_parties';
    end if;

    -- 6. RLS y sus tres politicas siguen en pie.
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
