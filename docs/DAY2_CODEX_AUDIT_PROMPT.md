# DAY2_CODEX_AUDIT_PROMPT

> Prompt de auditoría externa del Día 2. Copiar íntegro a Codex.

---

## INSTRUCCIÓN PRINCIPAL

**NO modifiques ningún archivo.**
**Devuelve únicamente un reporte de auditoría priorizado por severidad.**

No apliques correcciones, no reescribas código, no crees archivos, no ejecutes
migraciones. Solo lee, analiza y reporta.

---

## CONTEXTO DEL PROYECTO

**Asistente Tributario IA para Costa Rica** — capa de inteligencia tributaria sobre los
datos fiscales reales de un contribuyente. No es un software contable, ni un sistema de
facturación, ni un chatbot.

Principio rector: **`LLM ≠ Tax Engine`**. El LLM interpreta y explica; el Tax Engine
calcula de forma determinista. Ninguna cifra fiscal procede del razonamiento de un
modelo.

**Estado:** Día 2 completado. Existen infraestructura, tenancy con RLS, autenticación y
una UI mínima de empresas. **No existe todavía** ningún dato fiscal: ni facturas, ni
XML, ni Tax Engine, ni FastAPI, ni IA.

Antes de auditar, lee en este orden:

1. `docs/PROJECT_STATE.md` — fotografía del estado actual
2. `AI_INSTRUCTIONS.md` — las 16 reglas permanentes del proyecto
3. `docs/DECISIONS.md` — ADR-001 a ADR-019
4. `ARCHITECTURE.md` — arquitectura prevista
5. `docs/SESSION_LOG.md` — historial

## ALCANCE

Todo lo construido durante el Día 2:

```
supabase/migrations/     5 migraciones
supabase/config.toml     configuración del proyecto DEV
frontend/src/            aplicación Next.js 16 (App Router, src/)
tests/                   3 suites, 30 casos
docs/                    documentación
```

Stack: Next.js 16.3.2 · React 19.2.8 · TypeScript 5.9.3 · Tailwind 4 ·
`@supabase/ssr` 0.12.4 · `@supabase/supabase-js` 2.112.3 · PostgreSQL 17.6.

---

## QUÉ AUDITAR

### 1. Arquitectura
- ¿Respeta el código las fronteras de `ARCHITECTURE.md`?
- ¿Hay lógica que pertenezca a otra capa?
- ¿Contradice algo el principio `LLM ≠ Tax Engine`?
- ¿Se ha introducido algo fuera del alcance del Día 2?

### 2. Seguridad
- Secretos en código, configuración, build o historial
- Uso de `service_role`, `sb_secret_` o Admin API en operaciones normales
- `.env.local` correctamente ignorado; `.env.example` sin valores reales
- Superficie expuesta por la Data API
- Cabeceras de caché en respuestas con `Set-Cookie`

### 3. RLS y tenancy
- `20260822230620_create_private_schema_and_rls.sql`
- ¿Puede un usuario ver o modificar datos de otra empresa?
- ¿Es correcto que `rls_forced = false`? (se apoya en el bypass del propietario para
  la función `security definer`, evitando recursión)
- ¿Son mínimos los privilegios? `anon` sin acceso; `authenticated` solo `SELECT`
- ¿Puede alguien concederse una membership?
- Recursión de políticas, `search_path`, escalada de privilegios

### 4. `create_company`
- `20260822230621` y `20260823213730`
- Patrón: `public.create_company` (SECURITY INVOKER) → `private.create_company_impl`
  (SECURITY DEFINER, schema no expuesto)
- ¿Aporta seguridad real o es solo supresión del linter 0029?
- ¿Puede el `user_id` proceder del cliente por alguna vía?
- ¿Es realmente atómica? ¿Qué ocurre si falla la segunda inserción?
- ¿Son mínimos los `GRANT`/`REVOKE`?

### 5. Autenticación y sesión
- `frontend/src/proxy.ts` — refresco de sesión
- `frontend/src/lib/auth/` — `session.ts`, `actions.ts`, `constants.ts`
- ¿Se usa `getClaims()` y nunca `getSession()` para autorizar?
- ¿El `matcher` deja alguna ruta sin cubrir? ¿Importa, dado que no autoriza?
- ¿Se manejan bien las tres formas de retorno de `getClaims()`, incluida
  `{data: null, error: null}`?
- ¿Permiten los mensajes de error enumerar cuentas?
- ¿Qué ocurre si `signUp` no devuelve sesión (producción con confirmación activa)?

### 6. Server Actions
- `lib/auth/actions.ts` y `lib/companies/actions.ts`
- ¿Verifica cada una la identidad, sin depender del proxy?
- ¿Se valida toda entrada procedente del cliente?
- ¿Hay riesgo de CSRF, de acción invocable sin sesión, o de fuga de detalle interno?
- ¿Es correcta la revalidación tras crear una empresa?

### 7. Acceso a datos
- `lib/companies/queries.ts`
- ¿Se apoya el aislamiento en RLS y no en filtros de la aplicación?
- ¿Se expone algo innecesario al cliente?

### 8. Tests
- `tests/rls/`, `tests/auth/`, `tests/companies/`, `tests/support/harness.ts`
- ¿Prueban lo que dicen probar, o pueden pasar por el motivo equivocado?
- ¿Distinguen correctamente **RLS filtra** (0 filas, sin error) de **falta de
  privilegio** (error `42501`)?
- ¿Son suficientes los autotests de los detectores estáticos?
- ¿Qué casos límite faltan?
- **Límite declarado:** no se invoca el protocolo HTTP de Server Actions de Next.js
  (depende de un identificador que cambia en cada build). ¿Es aceptable esa cobertura?

### 9. Dependencias e inconsistencias
- Dependencias no utilizadas o innecesarias
- Imports inconsistentes, código muerto, duplicación
- Contradicciones con `AI_INSTRUCTIONS.md` o con ADRs aceptados
- Documentación que no concuerde con el código

### 10. Edge cases
- Sesión expirada durante una Server Action
- Refresco concurrente de token
- Nombre de empresa con Unicode, emojis o espacios en blanco
- Usuario eliminado con empresas creadas (`ON DELETE RESTRICT`)
- Fallo de red a mitad de una operación
- Múltiples pestañas del navegador

---

## PROBLEMAS YA CONOCIDOS

No hace falta que los redescubras. Confírmalos o refútalos, y di si son más graves de
lo que creemos:

1. **`requiredEnv` duplicado** en `lib/supabase/client.ts` y `server.ts`.
2. **El paquete `tests/` no puede ejecutar `tsc`** por falta de `@types/node`.
3. **Límite de tasa de Supabase Auth**: `sign_in_sign_ups = 30` por 5 min e IP.
   Confirmado y reproducido. Mitigado con serialización y fallo rápido, **no eliminado**.
4. **`npm run` falla con exit 127**: anomalía de PATH del entorno de desarrollo, no del
   proyecto. Los binarios directos funcionan.
5. **Leaked Password Protection desactivada**: limitación del plan Free, pendiente para
   producción.
6. **82 usuarios de prueba acumulados** en el proyecto DEV, sin vía de limpieza que no
   use `service_role`.

---

## FORMATO DEL REPORTE

Priorizado por severidad. Para cada hallazgo:

```
[CRÍTICO | ALTO | MEDIO | BAJO | INFORMATIVO]

Título breve
Archivo:línea
Qué está mal
Por qué importa — con un escenario concreto de fallo o explotación
Corrección sugerida (descrita, NO aplicada)
Confianza: alta | media | baja
```

**Criterios de severidad**

- **CRÍTICO** — un usuario puede acceder a datos de otro, o hay un secreto expuesto
- **ALTO** — fallo de seguridad o corrección explotable bajo condiciones realistas
- **MEDIO** — defecto real sin explotación directa
- **BAJO** — mantenibilidad, consistencia
- **INFORMATIVO** — observación, sin acción requerida

**Termina con:**

- ¿Es el aislamiento multiempresa sólido? Sí/No, con razones.
- ¿Hay algún bloqueante para dejar el Día 2 como versión estable en Git?
- Las tres cosas que corregirías primero.

**Si no encuentras nada en alguna categoría, dilo explícitamente.** Un reporte que
declara "sin hallazgos" en un área es más útil que uno que la omite.

No inventes vulnerabilidades para llenar el reporte. Si algo te parece correcto,
confírmalo.
