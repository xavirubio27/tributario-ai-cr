/**
 * Lectura de empresas.
 *
 * EL FILTRADO LO HACE RLS, NO ESTE CÓDIGO
 *
 *   authenticated session -> SELECT companies -> RLS -> solo filas con membership
 *
 * Deliberadamente NO se añade un `.eq('...', userId)`. Enviar el identificador de
 * usuario como filtro de seguridad desde la aplicación convertiría el aislamiento
 * en una cuestión de disciplina del programador, que es exactamente lo que
 * ADR-002 rechaza. La política `companies_select_members` es la autoridad.
 */
import { createClient } from '@/lib/supabase/server'

export type Company = {
  id: string
  name: string
  created_at: string
}

export type CompanyListResult = {
  companies: Company[]
  error: string | null
}

export async function listCompanies(): Promise<CompanyListResult> {
  const supabase = await createClient()

  const { data, error } = await supabase
    .from('companies')
    .select('id, name, created_at')
    .order('created_at', { ascending: false })

  if (error) {
    // Mensaje seguro: no se filtra detalle interno del error a la interfaz.
    return { companies: [], error: 'No se pudieron cargar las empresas. Inténtalo de nuevo.' }
  }

  return { companies: (data ?? []) as Company[], error: null }
}
