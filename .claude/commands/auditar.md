---
description: Lanza el subagente auditor sobre el trabajo pendiente (o el alcance indicado) y resume el veredicto.
argument-hint: "[alcance opcional, p. ej. C4-B3 o una ruta]"
---

Invoca el subagente `auditor` con el siguiente alcance:

- Si se indicó un alcance: **$ARGUMENTS**
- Si no: el diff pendiente respecto a `main` (`git diff main...HEAD` más los cambios sin
  commitear).

Pásale al auditor, además del alcance, la lista de hallazgos de la auditoría anterior si
esto es una reauditoría, para que los verifique uno por uno.

Cuando el auditor termine:

1. Muestra a Xavier el conteo por severidad y el veredicto **PASS / FAIL**.
2. Lista los hallazgos CRÍTICO y ALTO completos; los MEDIO/BAJO, en una línea cada uno.
3. **No corrijas nada todavía.** Propón el plan de remediación y espera su indicación.
