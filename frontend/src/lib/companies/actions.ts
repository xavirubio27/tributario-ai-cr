'use server'

/**
 * Server Actions de empresas.
 *
 * VÍA ÚNICA DE ESCRITURA
 *   La creación pasa exclusivamente por `public.create_company(p_name)`, que ya
 *   está protegida: wrapper SECURITY INVOKER en `public` que delega en
 *   `private.create_company_impl` (SECURITY DEFINER, schema no expuesto).
 *
 *   NO se inserta directamente en `companies` ni en `company_memberships`. De
 *   hecho no sería posible: `authenticated` solo tiene SELECT sobre esas tablas
 *   y no existe política de INSERT.
 *
 * IDENTIDAD
 *   `p_name` es el ÚNICO parámetro. El `user_id` jamás viaja desde el navegador:
 *   lo deriva `auth.uid()` dentro de la implementación privada.
 */
import { revalidatePath } from 'next/cache'
import { createClient } from '@/lib/supabase/server'
import { requireUser } from '@/lib/auth/session'
import { validateCompanyName } from '@/lib/companies/validation'
import type { CompanyFormState } from '@/lib/companies/constants'

export async function createCompanyAction(
  _prevState: CompanyFormState,
  formData: FormData,
): Promise<CompanyFormState> {
  // Verificación explícita de identidad. No se delega en proxy.ts: un cambio de
  // `matcher` no debe poder dejar esta acción sin protección.
  await requireUser()

  const validation = validateCompanyName(formData.get('name'))
  if (!validation.ok) {
    return { error: validation.error }
  }

  const supabase = await createClient()
  const { error } = await supabase.rpc('create_company', { p_name: validation.name })

  if (error) {
    // Mensaje seguro. La autorización real ya la aplicaron el RPC y RLS; aquí no
    // se duplica esa lógica ni se expone el detalle del error.
    return { error: 'No se pudo crear la empresa. Inténtalo de nuevo.' }
  }

  // Refresca la vista para que la empresa recién creada aparezca en el listado.
  revalidatePath('/app')

  return { error: null, notice: `Empresa «${validation.name}» creada.` }
}
