/**
 * Axis maths, kept out of the component so it can be reasoned about on its own.
 */

/** SVG user-space geometry. The chart scales with CSS; these stay constant. */
export const GEOM = {
  width: 640,
  height: 300,
  padLeft: 52,
  padRight: 16,
  padTop: 12,
  padBottom: 40,
} as const

export const plotLeft = GEOM.padLeft
export const plotRight = GEOM.width - GEOM.padRight
export const plotTop = GEOM.padTop
export const plotBottom = GEOM.height - GEOM.padBottom
export const plotWidth = plotRight - plotLeft
export const plotHeight = plotBottom - plotTop

/**
 * Round a raw step up to a "nice" one so tick labels read as round numbers.
 */
function niceStep(rough: number): number {
  const mag = Math.pow(10, Math.floor(Math.log10(rough)))
  const norm = rough / mag
  const step = norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 2.5 ? 2.5 : norm <= 5 ? 5 : 10
  return step * mag
}

export interface YAxis {
  min: number
  max: number
  ticks: number[]
  /** Maps a data value to an SVG y coordinate. */
  y: (value: number) => number
  /** SVG y of the zero line, which is where bars are anchored. */
  zeroY: number
}

/**
 * Build a y axis that always includes zero.
 *
 * Including zero is not negotiable for bars: a bar chart whose baseline is not
 * zero exaggerates differences, which is the most common way a chart lies.
 * Negative values matter in this domain (a pricing gap can be negative), so the
 * axis grows downward from zero when it needs to.
 */
export function buildYAxis(values: number[], targetTicks = 5): YAxis {
  const lo = Math.min(0, ...values)
  const hi = Math.max(0, ...values)

  // A flat all-zero series still needs a usable axis.
  const span = hi - lo || 1
  const step = niceStep(span / targetTicks)

  const min = Math.floor(lo / step) * step
  const max = Math.ceil(hi / step) * step
  const range = max - min || 1

  const ticks: number[] = []
  // Accumulate with a guard rather than `for (v = min; v <= max; v += step)`,
  // because repeated float addition drifts and can drop the last tick.
  const count = Math.round(range / step)
  for (let i = 0; i <= count; i++) ticks.push(min + i * step)

  const y = (value: number) => plotBottom - ((value - min) / range) * plotHeight

  return { min, max, ticks, y, zeroY: y(0) }
}

/** Trim float noise so 0.30000000000000004 prints as 0.3. */
export function formatTick(value: number): string {
  if (Number.isInteger(value)) return String(value)
  return String(Number(value.toFixed(4)))
}

/** Horizontal centre of a category slot. */
export function categoryCenter(index: number, count: number): number {
  const slot = plotWidth / count
  return plotLeft + slot * index + slot / 2
}

/** Font size of the category labels, in SVG user units. */
export const CATEGORY_LABEL_SIZE = 11

/** Average glyph width as a share of the font size, and the gap between labels. */
const GLYPH_WIDTH = 0.6
const LABEL_GAP = 6

/** Approximate rendered width of a category label, in SVG user units. */
function labelWidth(label: string): number {
  return label.length * CATEGORY_LABEL_SIZE * GLYPH_WIDTH
}

/**
 * Show every `step`-th category label: the smallest step at which no two
 * neighbouring shown labels overlap.
 *
 * The SVG scales as a whole, so whether labels collide is decided here in
 * user units, not by the screen: 21 daily labels such as "06-23" need about
 * 33 units each and get about 27, at any width. The hidden ones are still in
 * the hover tooltip and the table view.
 */
export function categoryLabelStep(categories: readonly string[]): number {
  const count = categories.length
  const slot = plotWidth / Math.max(count, 1)
  const fits = (step: number) => {
    for (let i = 0; i + step < count; i += step) {
      const apart = slot * step
      if ((labelWidth(categories[i]) + labelWidth(categories[i + step])) / 2 + LABEL_GAP > apart) return false
    }
    return true
  }
  let step = 1
  while (step < count && !fits(step)) step += 1
  return step
}
