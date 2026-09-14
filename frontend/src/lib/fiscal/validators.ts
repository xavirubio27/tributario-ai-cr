/**
 * Validadores léxicos del contrato de lectura.
 *
 * Módulo PURO Y SIN DEPENDENCIAS. Cada uno comprueba la FORMA de un tipo
 * semántico; aceptar «cualquier cadena no vacía» dejaba pasar `"hello"` como
 * identificador o como fecha, y lo que se renderiza después ya no tiene
 * arreglo.
 */

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i

/** UUID canónico. `gen_random_uuid()` produce versión 4. */
export function isUuid(v: unknown): v is string {
  return typeof v === 'string' && UUID.test(v)
}

/**
 * Instante CON huso, en ISO-8601.
 *
 * `receivedAt` es tiempo DEL SISTEMA —cuándo llegó la evidencia—, así que un
 * valor sin huso es ambiguo. No confundir con la fecha del comprobante, que
 * sigue la semántica de reloj de pared de ADR-039 y se valida aparte.
 */
const INSTANTE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$/

export function isInstant(v: unknown): v is string {
  if (typeof v !== 'string' || !INSTANTE.test(v)) return false
  return !Number.isNaN(Date.parse(v))
}

/**
 * Fecha y hora LOCAL del documento, sin huso, tal y como la declaró la fuente.
 *
 * No se convierte a `Date` ni se normaliza: hacerlo la reinterpretaría en el
 * huso del navegador y cambiaría el reloj de pared que ADR-039 obliga a
 * conservar. La validación es de CALENDARIO, no solo de forma: la gramática
 * sola aceptaba imposibles como `2026-99-99T25:61:61`. El calendario —meses,
 * días por mes, años bisiestos— se comprueba con aritmética entera pura
 * sobre los componentes léxicos; el valor jamás se transforma.
 *
 * La forma es la que emite el backend (`datetime.isoformat()` de un
 * `timestamp without time zone`): segundos siempre presentes y fracción
 * opcional de hasta seis dígitos.
 */
const LOCAL = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(\.\d{1,6})?$/

const DIAS_POR_MES = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]

function esBisiesto(anio: number): boolean {
  return (anio % 4 === 0 && anio % 100 !== 0) || anio % 400 === 0
}

export function isLocalDateTime(v: unknown): v is string {
  if (typeof v !== 'string') return false
  const m = LOCAL.exec(v)
  if (!m) return false
  const [anio, mes, dia, hora, minuto, segundo] = [1, 2, 3, 4, 5, 6].map(
    (i) => parseInt(m[i], 10),
  )
  if (mes < 1 || mes > 12) return false
  const tope = mes === 2 && esBisiesto(anio) ? 29 : DIAS_POR_MES[mes - 1]
  if (dia < 1 || dia > tope) return false
  return hora <= 23 && minuto <= 59 && segundo <= 59
}

/**
 * Desplazamiento horario en minutos.
 *
 * Los husos reales van de -12:00 a +14:00. Se exige entero: un
 * desplazamiento fraccionario no existe, y `NaN` o `Infinity` tampoco.
 */
export const OFFSET_MIN = -12 * 60
export const OFFSET_MAX = 14 * 60

export function isOffsetMinutes(v: unknown): v is number {
  return (
    typeof v === 'number' &&
    Number.isInteger(v) &&
    v >= OFFSET_MIN &&
    v <= OFFSET_MAX
  )
}

/**
 * Importe decimal exacto, en su forma léxica.
 *
 * Se valida la GRAMÁTICA, nunca con `Number()` ni `parseFloat`: convertirlo
 * para comprobarlo destruiría la precisión que se intenta preservar.
 *
 * Los totales de un comprobante no son negativos, así que no se admite signo.
 * Tampoco notación exponencial: PostgreSQL no la emite para `numeric` y
 * aceptarla abriría formas que el backend nunca produce.
 */
const DECIMAL = /^\d+(\.\d+)?$/

export function isExactDecimal(v: unknown): v is string {
  return typeof v === 'string' && DECIMAL.test(v)
}

/** Cursor: estado opaco del backend. No se decodifica en el cliente. */
export function isOpaqueCursor(v: unknown): v is string {
  return typeof v === 'string' && v.length > 0
}
