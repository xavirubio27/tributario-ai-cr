# Backend — foundation de identidad y RLS

Implementa [ADR-012](../docs/DECISIONS.md#adr-012). **No sirve producto**: existe para
demostrar una propiedad de seguridad.

```
JWT de Supabase Auth → FastAPI → verificación (JWKS, ES256)
    → conexión como `app_backend` → SET LOCAL ROLE authenticated
    → identidad transaction-scoped → RLS → company_memberships
```

## Dependencias y por qué

| Dependencia | Problema que resuelve | Por qué no algo más simple |
|---|---|---|
| `fastapi` | Framework HTTP; el alcance del checkpoint lo exige | — |
| `uvicorn` | Servidor ASGI para ejecutar FastAPI | — |
| `psycopg[binary,pool]` | Driver PostgreSQL **y** pool de conexiones | El pool es imprescindible: la reutilización de conexiones es justo el escenario que hay que probar. `psycopg3` permite controlar los límites de transacción con SQL literal, que es lo que `SET LOCAL` requiere |
| `pyjwt[crypto]` | Verificación ES256 con cliente JWKS incorporado (`PyJWKClient`) | Escribir verificación de JWT a mano es exactamente lo que la documentación desaconseja |
| `python-dotenv` | Carga `.env.local` fuera de Git | — |

**Deliberadamente ausentes:** ORM y SQLAlchemy —ADR-012 no decide ORM y aquí hace falta
control literal de la transacción—, Celery, Redis, workers y SDK de IA.

## Puesta en marcha (DESARROLLO)

### 1. Aplicar la migración del rol

```bash
npx supabase db push        # crea el rol app_backend (sin contraseña)
```

### 2. Establecer la contraseña del rol — fuera de Git

Una contraseña es una **credencial**, no esquema: ponerla en una migración la
publicaría en Git y violaría la Regla 6. Se establece por separado:

```sql
ALTER ROLE app_backend PASSWORD '<contraseña generada>';
```

Guárdala en tu gestor de contraseñas. **Nunca** en el repositorio.

### 3. Configurar el entorno

```bash
cp .env.example .env.local   # y rellenar; .env.local está ignorado por Git
```

`DATABASE_URL` debe apuntar a `app_backend`, **nunca** a `postgres` ni a
`service_role`: ambos tienen `BYPASSRLS` y anularían el aislamiento. `config.py`
rechaza esas cadenas explícitamente, parseando el usuario —el pooler usa el formato
`<rol>.<project-ref>`, así que una comprobación por subcadena dejaría pasar
`postgres.<ref>`—.

Formato esperado con el Session Pooler:

```
postgresql://app_backend.<project-ref>:<password>@<pooler-host>:5432/postgres?sslmode=require
```

**TLS obligatorio.** Sin `sslmode`, libpq usa `prefer`: intenta TLS y cae a texto plano
en silencio si el servidor lo rechaza. El backend inyecta `sslmode=require` cuando falta
y **se niega a arrancar** si encuentra `disable`, `allow` o `prefer`. `verify-ca` y
`verify-full` se respetan por ser más estrictos.

### 4. Instalar dependencias

La ruta del repositorio contiene `:`, y **`python -m venv` se niega a crear un entorno
ahí**. Se instala con `--target`:

```bash
python3 -m pip install --target ./.pydeps -e ".[dev]"
```

`.pydeps/` está ignorado por Git. La solución de fondo sería renombrar el directorio
padre para eliminar los dos puntos.

### 5. Ejecutar

```bash
PYTHONPATH=./.pydeps:. python3 -m uvicorn app.main:app --reload
PYTHONPATH=./.pydeps:. python3 -m pytest -q
```

## Nota sobre el modo de conexión

En **DESARROLLO** se usa el *session pooler*: mantiene una conexión estable, lo que
permite forzar de forma determinista la reutilización de la misma conexión física y
hacer concluyente el test de fuga de identidad.

La estrategia de conexión para **producción** —Supavisor, tipo de pooler, hosting—
queda expresamente sin decidir en ADR-012.

## Qué NO hay aquí

Facturas · XML · Tax Engine · IVA · Knowledge Base · IA · CRUD de empresas · gestión de
usuarios o memberships. Ver [ROADMAP.md](../ROADMAP.md).


## Alcance real de los privilegios de `app_backend`

Medido con `has_table_privilege` / `has_schema_privilege` / `has_function_privilege`,
que reflejan lo efectivo —incluido lo que llega vía `PUBLIC`— y no solo las filas de
`information_schema`:

| Recurso | ¿Alcanzable sin `SET LOCAL ROLE authenticated`? |
|---|---|
| `public.companies`, `public.company_memberships` | **No** (ni SELECT, INSERT, UPDATE, DELETE ni TRUNCATE) |
| Schemas `auth` y `private` | **No** |
| `create_company`, `create_company_impl`, `is_company_member` | **No** |
| `USAGE` sobre el schema `public` | **Sí**, concedido a `PUBLIC` |

**Precisión deliberada:** no se afirma "cero acceso ambiental". `USAGE` sobre `public`
llega vía `PUBLIC` y no se revoca, porque hacerlo afectaría a `anon`, `authenticated` y
al propio PostgREST. Lo que sí se garantiza —y se prueba— es que las tablas de tenancy y
las funciones sensibles son inalcanzables sin asumir el rol.

## Verificación en runtime

`create_pool()` llama a `verify_backend_role()` antes de devolver el pool. Comprueba
contra PostgreSQL —no contra la migración— que `session_user` es `app_backend`, que sus
atributos son los exigidos, que su única pertenencia es `authenticated` y que no puede
asumir `service_role`, `postgres` ni `supabase_admin`. Si algo no coincide, **el backend
no arranca**.
