# AI_INSTRUCTIONS — Reglas permanentes del proyecto

> **Este documento es la fuente de verdad de las reglas de desarrollo del proyecto.**
>
> Aplica a **cualquier agente de programación** que trabaje en este repositorio
> (Claude Code, Cursor, Copilot, Codex u otros) y también a desarrolladores humanos.
>
> [CLAUDE.md](CLAUDE.md) es un resumen operativo que apunta aquí. Ante cualquier
> discrepancia entre ambos, **prevalece este documento**.

---

## 0. Contexto mínimo indispensable

Estamos construyendo una **capa de inteligencia tributaria sobre los datos fiscales
reales de un contribuyente costarricense**.

No es un software contable, ni un sistema de facturación electrónica, ni un POS, ni un
ERP, ni un chatbot tributario, ni una interfaz de ChatGPT con legislación en el prompt.

El principio que gobierna todo el sistema:

```
LLM  ≠  Tax Engine
```

Documentos relacionados: [README.md](README.md) · [PRODUCT_SPEC.md](PRODUCT_SPEC.md) ·
[ARCHITECTURE.md](ARCHITECTURE.md) · [ROADMAP.md](ROADMAP.md) ·
[docs/DECISIONS.md](docs/DECISIONS.md) · [docs/GLOSSARY.md](docs/GLOSSARY.md)

---

## 1. Las reglas permanentes

### Regla 1 — No inventar APIs

Nunca inventes endpoints, rutas, estructuras de datos externas, formatos de respuesta,
nombres de campos de sistemas de terceros ni comportamientos de servicios externos.

Si necesitas conocer un contrato externo y no dispones de documentación verificada:
**decláralo explícitamente y detente**. No propongas una versión "probable".

Aplica especialmente a: APIs de la Administración Tributaria, servicios bancarios,
proveedores de facturación electrónica y cualquier integración de terceros.

### Regla 2 — No inventar legislación

Nunca inventes ni supongas:

- tasas impositivas
- artículos de ley, decretos o resoluciones
- fechas de vigencia
- clasificaciones fiscales
- obligaciones o plazos
- versiones del formato de comprobante electrónico

**Ninguna cifra ni referencia normativa entra al sistema sin fuente oficial verificada.**

Si un valor es necesario y no está verificado, deja el hueco marcado de forma
explícita. Un documento con huecos honestos es preferible a uno con cifras plausibles
e inventadas — y en materia tributaria, **una respuesta plausible y errónea es peor
que ninguna respuesta**.

### Regla 3 — LLM y Tax Engine permanecen separados

El LLM interpreta preguntas, selecciona herramientas, consulta datos, consulta
normativa, solicita cálculos y explica resultados.

El Tax Engine ejecuta cálculos deterministas con reglas versionadas.

**Nunca** se calcula un impuesto mediante el razonamiento de un LLM. **Nunca** se cita
normativa desde la memoria de un modelo. Toda cifra fiscal procede de una función
determinista y testeada; toda norma procede de la Knowledge Base.

Consecuencia práctica: el paquete `tax-engine/` no importa ningún SDK de IA, ni
FastAPI, ni cliente de base de datos.

### Regla 4 — Todo cálculo tributario crítico debe tener tests

Ningún cálculo tributario se considera terminado sin tests.

- Casos normales, límite y de error
- Casos de regresión histórica: un cálculo de un período pasado debe seguir
  produciendo el mismo resultado
- Los tests forman parte de la implementación, no de una fase posterior

### Regla 5 — Toda regla tributaria debe tener fuente y versionado temporal

Cada regla debe poder indicar:

```
fuente · documento o artículo · fecha · vigencia · versión
```

Todo cálculo debe contemplar `as_of_date` y persistir la versión de regla aplicada.

El motor nunca calcula "con las reglas actuales", sino con las vigentes en la fecha
correspondiente al hecho. Sin esto, el sistema deja de ser auditable.

### Regla 6 — Nunca colocar secretos en el código

Prohibido en el repositorio: API keys, tokens, contraseñas, credenciales de cualquier
servicio, secretos de firma, cadenas de conexión con credenciales.

- Se gestionan mediante variables de entorno
- Ninguna credencial privilegiada se expone al frontend
- Tampoco se versionan datos fiscales reales de contribuyentes; solo fixtures
  anonimizados y marcados como tales

Si detectas un secreto en el repositorio o en un cambio: **detente y avisa**.

### Regla 7 — La arquitectura debe ser multiempresa

El aislamiento entre empresas es un requisito crítico, no una característica.

- Todo dato fiscal pertenece a una empresa (tenant)
- El aislamiento se garantiza mediante Row Level Security en la base de datos, no
  solo mediante filtros en el código
- Las operaciones en contexto de usuario preservan su identidad y su tenant
- `service_role` y las claves privilegiadas **no son el mecanismo habitual** de acceso
  a datos fiscales de usuarios (ver ADR-002)

Ninguna consulta, endpoint o tool puede diseñarse asumiendo un único tenant.

### Regla 8 — Cada dato fiscal debe tener trazabilidad de su origen

Todo valor fiscal debe poder rastrearse hasta el documento del que proviene.

- El documento original se conserva íntegro e inmutable
- El modelo normalizado mantiene referencia hacia él
- Se distingue siempre `reported_*` (lo que dice el documento fuente) de `computed_*`
  (lo que calcula nuestro motor), y nunca se mezclan en un mismo campo

### Regla 9 — Construir incrementalmente

Cada capa funciona y se prueba antes de construir la siguiente. Se sigue el orden del
[ROADMAP.md](ROADMAP.md). Ninguna fase se adelanta porque "sería rápido".

### Regla 10 — No intentar desarrollar todo el producto simultáneamente

Un cambio, un propósito. No mezcles la implementación de una funcionalidad con la
preparación de otra futura. No crees abstracciones para necesidades que aún no existen.

### Regla 11 — Ciclo de trabajo de cada funcionalidad

```
arquitectura → implementación → tests → ejecución → corrección → documentación
```

Ninguna etapa se salta. En particular: la documentación es parte del ciclo, no un
añadido opcional al final.

### Regla 12 — No realizar refactors masivos innecesarios

Los refactors amplios se proponen y se acuerdan antes de ejecutarse. No se
reestructura código que funciona por preferencia estilística.

### Regla 13 — Preservar las funcionalidades existentes

Cada avance debe mantener funcionando lo ya construido. Ante la duda entre romper algo
existente y posponer una mejora: posponer la mejora.

### Regla 14 — Señalar decisiones arquitectónicas de riesgo antes de implementarlas

Si una decisión puede comprometer significativamente el proyecto, se explica **antes**
de implementarla, no después.

Requieren aviso previo, entre otras: cambios en el modelo de aislamiento o seguridad;
cambios en las fronteras entre los cuatro componentes; introducción de dependencias
relevantes; cambios en el modelo de datos fiscales; cualquier cosa que afecte a la
trazabilidad o a la reproducibilidad de los cálculos.

Las decisiones aceptadas se registran en [docs/DECISIONS.md](docs/DECISIONS.md).

### Regla 15 — Revisar el diff completo antes de aplicar configuración remota

`supabase config push` envía **todo** `config.toml`, no solo las líneas editadas. Los
valores por defecto de la CLI están pensados para desarrollo local y pueden degradar
ajustes del proyecto remoto sin que nadie lo pida.

**Nunca ejecutar `config push` contra staging o production sin revisar previamente el
diff completo de configuración.**

- El comando **no tiene `--dry-run`**: imprime el diff y aplica en el mismo acto.
- Antes de ejecutarlo, comprobar que local y remoto están sincronizados (un `config
  push` previo que devuelva `up_to_date` en todos los servicios). Con esa línea base,
  el diff remoto solo puede ser el delta de los cambios locales.
- Tras aplicar, contrastar el diff impreso contra los cambios previstos. Si aparece
  algo no previsto, **detenerse y avisar**.
- El mismo criterio vale para cualquier operación que sincronice configuración
  completa hacia un entorno remoto.

Precedente que originó la regla: un `config push` de desarrollo desactivó MFA TOTP y
redujo `otp_length` sin intención, porque el archivo local arrastraba los valores por
defecto de la CLI.

### Regla 16 — Continuidad entre sesiones

El proyecto no depende del historial de conversación. El estado vive en el repositorio.

**Al comenzar toda sesión de desarrollo:**

1. Leer [docs/PROJECT_STATE.md](docs/PROJECT_STATE.md).
2. Leer este documento (`AI_INSTRUCTIONS.md`).
3. Consultar [docs/DECISIONS.md](docs/DECISIONS.md) cuando sea relevante.
4. Ejecutar `git status`.
5. Revisar el último commit antes de modificar nada.

**Al cerrar cada checkpoint:**

- Actualizar `docs/PROJECT_STATE.md`.

**Al cerrar cada día de construcción:**

- Actualizar `docs/PROJECT_STATE.md`.
- Añadir la entrada correspondiente a `docs/SESSION_LOG.md`.
- Verificar que la documentación concuerda con Git, tests y migraciones.
- Hacer commit **solo tras revisión**.

#### Jerarquía de verdad

```
1. Git + tests + migraciones     ← estado técnico verificado
2. docs/DECISIONS.md
3. docs/PROJECT_STATE.md
4. docs/SESSION_LOG.md
5. contexto conversacional        ← el menos fiable
```

**Si la documentación contradice el estado técnico verificado, gana el estado técnico
verificado.** En ese caso, corregir la documentación — nunca al revés, y nunca en
silencio.

Antes de afirmar que algo existe o funciona, comprobarlo. Un documento describe lo que
era cierto cuando se escribió.

---

## 2. Fronteras entre componentes

Estas fronteras no son sugerencias de estilo. Son lo que hace el sistema auditable.

| Componente | Puede | No puede |
|---|---|---|
| **Tax Data Layer** | Almacenar, aislar, trazar datos fiscales | Calcular impuestos, interpretar normativa |
| **Tax Engine** | Calcular de forma determinista | Acceder a base de datos, red, LLM, FastAPI |
| **Knowledge Base** | Almacenar y servir normativa con fuente | Calcular, contener datos de contribuyentes |
| **AI Agent** | Interpretar, orquestar tools, explicar | Calcular impuestos, citar de memoria, acceder libremente a datos |
| **Frontend** | Presentar | Contener lógica tributaria, acceder a datos por vías alternativas |

### Reglas específicas del Tax Engine

El paquete `tax-engine/` debe ser: determinista · testeable · sin dependencia del LLM ·
sin FastAPI · sin acceso directo a base de datos · sin I/O innecesario.

Si una implementación exige romper alguna de estas condiciones, **no se rompe la
condición: se replantea la implementación** y se consulta antes.

### Reglas específicas del AI Agent

- Acceso a datos exclusivamente mediante un conjunto cerrado de tools
- Nunca SQL libre ni consultas arbitrarias
- Siempre dentro del tenant e identidad del usuario que pregunta
- Toda respuesta con cifra debe poder acompañarse de su desglose y sus fuentes
- Ante datos insuficientes: decirlo. Nunca estimar en silencio

---

## 3. Convenciones

### Idioma

- **Documentación explicativa:** español
- **Código, identificadores, nombres de variables, funciones, clases, ficheros y
  mensajes técnicos:** inglés
- **Mensajes de commit:** inglés

### Nomenclatura obligatoria de datos fiscales

```
reported_*    valor proveniente del comprobante o documento fuente
computed_*    valor producido por nuestro Tax Engine
```

Nunca se fusionan en un mismo campo. Su discrepancia es información valiosa del
producto, no un error a ocultar.

### Valores monetarios

- Representación **decimal exacta**; nunca coma flotante donde pueda producir errores
  de precisión
- Se conserva la moneda original y la información de conversión cuando aplique
- Las reglas de redondeo pertenecen a la regla tributaria, no al código de utilidad

### Tests

- Unitarios junto al módulo correspondiente
- `tests/` en la raíz para integración y end-to-end
- El aislamiento multiempresa se verifica con tests, no por revisión visual

---

## 4. Antes de modificar componentes importantes

Consulta la documentación correspondiente **antes** de tocar:

| Vas a modificar | Lee antes |
|---|---|
| Modelo de datos fiscales | ARCHITECTURE.md §6, §7 · docs/GLOSSARY.md |
| Tax Engine | ARCHITECTURE.md §8 · docs/DECISIONS.md ADR-004, ADR-005 |
| Seguridad, RLS, autenticación | ARCHITECTURE.md §6 · docs/DECISIONS.md ADR-001, ADR-002 |
| Pipeline de ingesta | ARCHITECTURE.md §5.2 · docs/DECISIONS.md ADR-006, ADR-007 |
| Knowledge Base o RAG | ARCHITECTURE.md §9 · docs/DECISIONS.md ADR-009 |
| AI Agent o tools | ARCHITECTURE.md §10 |
| Alcance o fases | PRODUCT_SPEC.md · ROADMAP.md |

---

## 5. Cuando algo no está verificado

Este proyecto opera bajo una norma sencilla:

> **Lo no verificado se declara como no verificado.**

Formas correctas de proceder:

- Marcar el hueco explícitamente y continuar con el resto del trabajo
- Registrar la incógnita como decisión pendiente en `docs/DECISIONS.md`
- Preguntar cuando la respuesta condicione el diseño

Formas incorrectas:

- Rellenar con un valor "razonable"
- Suponer un endpoint o un formato "estándar"
- Citar una norma de memoria
- Continuar en silencio esperando corregirlo después

---

## 6. Estado actual del repositorio

**El estado operativo vive en [docs/PROJECT_STATE.md](docs/PROJECT_STATE.md).** Este
documento contiene reglas permanentes; no duplica una fotografía del repositorio, que
volvería a quedar obsoleta.

Antes de asumir que algo existe, **verifícalo contra Git, los tests y las migraciones**
— la jerarquía de verdad de la Regla 16. Este documento describe reglas y diseño, no
código existente.
