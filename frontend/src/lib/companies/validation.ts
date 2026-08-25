/**
 * Validación del nombre de empresa.
 *
 * Módulo PURO y SIN DEPENDENCIAS a propósito:
 *   - lo importa la Server Action (`actions.ts`)
 *   - lo importan los tests directamente, sin necesidad de E2E ni de invocar el
 *     protocolo HTTP de Server Actions
 *
 * No usa el alias `@/` para que sea importable desde el paquete de tests.
 *
 * ESPEJO DE LA RESTRICCIÓN DE BASE DE DATOS
 *   companies_name_length_check:
 *     CHECK (char_length(btrim(name)) BETWEEN 1 AND 200)
 *
 *   Esta validación es de conveniencia: da un mensaje legible antes de la llamada
 *   de red. La autoridad sigue siendo la base de datos y `create_company()`.
 */

export const COMPANY_NAME_MIN_LENGTH = 1
export const COMPANY_NAME_MAX_LENGTH = 200

export type CompanyNameValidation =
  | { ok: true; name: string }
  | { ok: false; error: string }

export function validateCompanyName(raw: unknown): CompanyNameValidation {
  const name = typeof raw === 'string' ? raw.trim() : ''

  if (name.length < COMPANY_NAME_MIN_LENGTH) {
    return { ok: false, error: 'El nombre de la empresa es obligatorio.' }
  }

  if (name.length > COMPANY_NAME_MAX_LENGTH) {
    return {
      ok: false,
      error: `El nombre no puede superar los ${COMPANY_NAME_MAX_LENGTH} caracteres.`,
    }
  }

  return { ok: true, name }
}
