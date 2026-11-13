---
description: Ejecuta un checkpoint completo de Tribuu - estado, diseño, GO de Xavier, implementación, tests, auditoría independiente, remediación y cierre documental.
argument-hint: "<checkpoint o tarea, p. ej. C4-B3>"
---

Vas a ejecutar el checkpoint **$ARGUMENTS** siguiendo el ciclo de la Regla 11
(`arquitectura → implementación → tests → ejecución → corrección → documentación`).
Este comando sustituye el flujo manual ChatGPT → Claude Code → Codex.

Lleva una lista de tareas visible con estas fases y márcalas conforme avances.

## Fase 1 — Orientación (sin escribir nada)

1. Lee `docs/PROJECT_STATE.md` (*Current Phase*, *Next Action*), `AI_INSTRUCTIONS.md`
   y los ADR relevantes de `docs/DECISIONS.md`.
2. `git status` y `git log -5`. Si hay cambios sin commitear que no son tuyos, avisa.
3. Confirma que **$ARGUMENTS** es el siguiente paso del ROADMAP. Si no lo es, detente y
   explica por qué (Regla 9).
4. Lista las decisiones pendientes (ADR en DRAFT o ⏳) que bloqueen este checkpoint.

## Fase 2 — Diseño y GO

1. Si el diseño ya existe y está ACCEPTED, resúmelo en 10 líneas y pasa a la Fase 3.
2. Si no existe o está en DRAFT, redacta el diseño: alcance, qué queda fuera, archivos
   que se tocan, migraciones, contrato de tests y criterios de aceptación, y los riesgos
   de la Regla 14.
3. Opcional pero recomendado en cambios de seguridad o de modelo de datos: pide al
   subagente `auditor` que revise **el diseño** antes de implementarlo.
4. **DETENTE.** Presenta el diseño a Xavier y espera un **GO explícito**. No interpretes
   silencio ni un "ok" ambiguo como GO para cambios de esquema o seguridad; pregunta.
5. Con el GO, registra la decisión (ADR → ACCEPTED o documento de diseño) antes de
   escribir código.

## Fase 3 — Implementación y tests

1. Una rama por checkpoint: `feat/<checkpoint-en-minúsculas>` desde `main`.
2. Implementa con cambios pequeños y de un solo propósito (Regla 10). Los tests son parte
   de la implementación.
3. Ejecuta los tests **focalizados** y captura el exit code real. No avances con rojos.
4. Migraciones: nunca `supabase db push` ni `config push` contra un entorno remoto sin
   mostrar antes el diff completo a Xavier y tener su visto bueno (Regla 15).

## Fase 4 — Auditoría independiente

1. Invoca el subagente `auditor` con el alcance de este checkpoint y los criterios de
   aceptación de la Fase 2. Tú no te autoevalúas.
2. Si el veredicto es FAIL: corrige los CRÍTICO/ALTO (y los MEDIO razonables), vuelve a
   correr los tests y pide **reauditoría** pasando la lista de hallazgos anteriores.
3. Máximo tres rondas. Si después sigue en FAIL, detente y explícale a Xavier qué bloquea.

## Fase 5 — Cierre

1. Suite completa del backend (o, si Xavier prefiere no esperar ~1 h, dilo explícitamente
   en el estado como NO EJECUTADA). Regresión del frontend y typecheck.
2. Actualiza `docs/PROJECT_STATE.md`, `docs/DECISIONS.md` y `ROADMAP.md` con conteos
   factuales; añade entrada a `docs/SESSION_LOG.md` si cierra un día de trabajo.
3. Presenta a Xavier: resumen de qué se hizo, veredicto del auditor, resultado de tests y
   el mensaje de commit propuesto (en inglés).
4. **Commit solo con su visto bueno. Push solo si él lo pide.**
