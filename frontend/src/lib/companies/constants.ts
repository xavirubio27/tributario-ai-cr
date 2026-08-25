/**
 * Tipos compartidos del módulo de empresas.
 * Separado de `actions.ts` porque un módulo `'use server'` solo puede exportar
 * funciones asíncronas.
 */

export type CompanyFormState = {
  /** Mensaje de error seguro para mostrar. */
  error?: string | null
  /** Confirmación tras una creación correcta. */
  notice?: string | null
}

export const EMPTY_COMPANY_FORM_STATE: CompanyFormState = {}
