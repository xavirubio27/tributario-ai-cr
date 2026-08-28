-- =============================================================================
-- Rol PostgreSQL dedicado al backend FastAPI
-- =============================================================================
-- Implementa el requisito de rol de ADR-012:
--   "FastAPI accede a PostgreSQL con un rol backend dedicado y de minimo
--    privilegio, que NO tiene BYPASSRLS, NO es service_role y NO puede
--    convertirse en credencial accesible desde el frontend."
--
-- MODELO DE ACCESO
--
--   app_backend  ----LOGIN---->  conexion
--        |
--        |  SET LOCAL ROLE authenticated   (dentro de cada transaccion)
--        v
--   authenticated  ---->  politicas RLS del Dia 2, sin cambios
--
--   Es el mismo patron que usa PostgREST con el rol `authenticator`, pero con un
--   rol propio: `authenticator` puede ademas asumir `service_role`, que tiene
--   BYPASSRLS. `app_backend` NO recibe esa pertenencia, de modo que le resulta
--   imposible escalar a un rol que ignore RLS.
--
-- POR QUE NOINHERIT
--   Sin herencia, `app_backend` no arrastra privilegio alguno de forma ambiental:
--   solo obtiene los de `authenticated` cuando lo asume EXPLICITAMENTE, y esa
--   asuncion se hace con SET LOCAL, luego expira con la transaccion.
--
-- SIN CONTRASENA AQUI -- DELIBERADO
--   Una contrasena es una credencial, no un elemento de esquema. Ponerla en una
--   migracion la publicaria en Git y violaria la Regla 6. Debe establecerse
--   fuera de banda:
--
--     ALTER ROLE app_backend PASSWORD '<generada, fuera de Git>';
--
--   Hasta entonces el rol existe pero no puede autenticarse.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 1. Rol
-- -----------------------------------------------------------------------------
do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'app_backend') then
    create role app_backend
      login
      noinherit        -- sin privilegios ambientales; debe asumir rol explicitamente
      nosuperuser
      nobypassrls      -- requisito de ADR-012
      nocreatedb
      nocreaterole
      noreplication;
  else
    -- Idempotente: reafirma los atributos aunque el rol ya existiera.
    alter role app_backend
      login noinherit nosuperuser nobypassrls nocreatedb nocreaterole noreplication;
  end if;
end
$$;

comment on role app_backend is
  'Rol de conexion del backend FastAPI. NOINHERIT y NOBYPASSRLS. Asume `authenticated` por transaccion (ADR-012).';

-- -----------------------------------------------------------------------------
-- 2. Unica pertenencia concedida
-- -----------------------------------------------------------------------------
-- Permite `SET LOCAL ROLE authenticated`. Es lo minimo imprescindible para que
-- las politicas del Dia 2 -- definidas `TO authenticated` -- se apliquen.
--
-- Deliberadamente NO se concede `anon` ni `service_role`.
grant authenticated to app_backend;

-- -----------------------------------------------------------------------------
-- 3. Privilegios propios: ninguno
-- -----------------------------------------------------------------------------
-- `app_backend` no recibe GRANT alguno sobre tablas, schemas ni funciones. Todo
-- acceso a datos ocurre despues de asumir `authenticated`, bajo RLS.
--
-- Se revoca explicitamente lo que PostgreSQL concede por defecto a PUBLIC, para
-- que el rol no pueda crear objetos ni inspeccionar el schema publico por su
-- cuenta antes de asumir `authenticated`.
revoke all on schema public from app_backend;

-- No se conceden privilegios preventivos sobre tablas futuras: las tablas
-- fiscales definiran los suyos cuando existan.
