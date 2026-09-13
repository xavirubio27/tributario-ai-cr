/**
 * Regla de visibilidad del resultado.
 *
 * Módulo PURO —extraído del componente para poder probarlo sin un renderizador
 * de React, que este repositorio no tiene configurado—.
 *
 * EL PROBLEMA QUE RESUELVE
 *   `useActionState` conserva el último resultado hasta el envío siguiente. Si
 *   el usuario sube A, ve «Procesado correctamente» y luego elige B, ese aviso
 *   seguía en pantalla: describía a A pero, junto al nombre de B recién
 *   seleccionado, parecía hablar de B.
 */

import type { UploadFiscalDocumentActionResult } from './contract'

/**
 * Decide si el resultado que guarda el formulario describe lo que el usuario
 * ve ahora mismo.
 *
 * DOS CONDICIONES, Y LAS DOS HACEN FALTA
 *
 *   `frescoParaEsteEnvio` — se pone a `false` al elegir otro archivo, así que
 *   un resultado anterior deja de mostrarse en cuanto la selección cambia.
 *
 *   `enviando` — mientras hay un envío en curso NO se muestra nada. Sin esta
 *   condición quedaba un hueco: al enviar B, `frescoParaEsteEnvio` vuelve a
 *   `true` de inmediato, pero `useActionState` conserva el resultado de A
 *   hasta que la acción termina. Durante esa espera reaparecía el aviso de A
 *   describiendo el envío de B.
 *
 * Un resultado solo se muestra, por tanto, si pertenece al último envío
 * COMPLETADO y no hay otro más reciente en marcha.
 */
export function resultadoVisible(
  resultado: UploadFiscalDocumentActionResult | null,
  frescoParaEsteEnvio: boolean,
  enviando: boolean,
): UploadFiscalDocumentActionResult | null {
  if (!resultado || !frescoParaEsteEnvio || enviando) {
    return null
  }
  return resultado
}
