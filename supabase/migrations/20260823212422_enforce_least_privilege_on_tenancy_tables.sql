-- =============================================================================
-- Principio de minimo privilegio sobre las tablas de tenancy
-- =============================================================================
-- MOTIVO
--   La migracion 20260822230620 revoco unicamente INSERT, UPDATE y DELETE de
--   `authenticated`. Los privilegios por defecto de Supabase conceden ALL, que
--   incluye ademas TRUNCATE, TRIGGER y REFERENCES. La verificacion posterior
--   confirmo que `authenticated` conservaba:
--
--     REFERENCES, SELECT, TRIGGER, TRUNCATE
--
--   TRUNCATE es el privilegio relevante: **no esta sujeto a RLS**. TRIGGER
--   permitiria adjuntar codigo a la tabla. Ninguno de los dos es alcanzable hoy
--   a traves de la Data API -- PostgREST solo emite SELECT/INSERT/UPDATE/DELETE
--   y llamadas RPC -- pero son privilegio excedente sobre las tablas que
--   sostienen el aislamiento multiempresa.
--
-- ENFOQUE
--   En lugar de revocar caso por caso, se expresa el ESTADO DESEADO completo:
--   revocar todo y volver a conceder unicamente lo necesario. Asi el resultado
--   no depende de que privilegios existieran antes, y la migracion es legible
--   como declaracion de intencion.
--
-- ESTADO OBJETIVO
--   anon           -> ningun privilegio
--   authenticated  -> SELECT, y nada mas
--
--   Toda escritura sigue pasando exclusivamente por public.create_company(),
--   que es SECURITY DEFINER y por tanto no depende de estos GRANT.
--
--   Los privilegios de service_role NO se modifican aqui: el diseno no lo
--   utiliza en ningun punto (ADR-002), y alterarlo excederia el alcance de esta
--   remediacion.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 1. Estado limpio
-- -----------------------------------------------------------------------------
revoke all on table public.companies           from anon, authenticated;
revoke all on table public.company_memberships from anon, authenticated;

-- -----------------------------------------------------------------------------
-- 2. Unicamente lo estrictamente necesario
-- -----------------------------------------------------------------------------
-- `authenticated` necesita SELECT para que PostgREST pueda leer; que filas ve
-- lo deciden las politicas RLS, no este GRANT. Ambas barreras deben permitir el
-- acceso: GRANT *y* politica.
--
-- `anon` no recibe nada: los datos de tenancy no son publicos.
-- -----------------------------------------------------------------------------
grant select on table public.companies           to authenticated;
grant select on table public.company_memberships to authenticated;
