/**
 * Sobre de transporte de los Server Actions (C3-B0).
 *
 * POR QUÉ EXISTE
 *   El valor por defecto de Next.js es 1 MiB. Con él, cualquier comprobante
 *   por encima de ese tamaño se rechaza en el framework ANTES de ejecutar
 *   nuestro código: sin evidencia capturada y sin un código de error estable
 *   que mostrar al usuario. El fallo sería silencioso para quien lea el
 *   código de la aplicación, porque no aparece en ninguna parte de ella.
 *
 * QUÉ AFIRMA
 *   El valor EFECTIVO que el framework leerá, importando la configuración
 *   real -- no que cierto texto exista en un fichero.
 *
 * LO QUE ESTE FICHERO NO DICE
 *   9 MiB no es el tamaño máximo de un documento fiscal. Es el sobre de
 *   transporte. La autoridad del dominio es `MAX_SOURCE_XML_BYTES`, en
 *   `backend/app/fiscal/ingestion.py`, y son 8 MiB.
 */
import { describe, it, expect } from 'vitest'
import nextConfig from '../../frontend/next.config'

/** Autoridad del dominio, reflejada aquí solo para expresar la relación. */
const MAX_SOURCE_XML_BYTES = 8 * 1024 * 1024

describe('sobre de transporte de los Server Actions', () => {
  const sobre = nextConfig.experimental?.serverActions?.bodySizeLimit

  it('está configurado explícitamente', () => {
    // Sin esto Next aplica 1 MiB, que es menor que el límite fiscal.
    expect(sobre).toBeDefined()
  })

  it('vale exactamente 9 MiB', () => {
    expect(sobre).toBe(9 * 1024 * 1024)
  })

  it('es un número, no una cadena con sufijo', () => {
    // `bytes.parse` usa unidades binarias: '9mb' son 9 * 1024 * 1024. Fijarlo
    // como número elimina la duda sobre si el sufijo es 10^6 o 2^20.
    expect(typeof sobre).toBe('number')
  })

  it('deja holgura sobre el límite fiscal para el marco multipart', () => {
    expect(sobre as number).toBeGreaterThan(MAX_SOURCE_XML_BYTES)
    expect((sobre as number) - MAX_SOURCE_XML_BYTES).toBe(1024 * 1024)
  })

  it('cabe bajo el límite de cuerpo del proxy, que por defecto son 10 MiB', () => {
    expect(sobre as number).toBeLessThan(10 * 1024 * 1024)
  })
})
