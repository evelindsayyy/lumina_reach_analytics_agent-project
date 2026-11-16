/**
 * Axis maths, kept out of the component so it can be reasoned about on its own.
 *
 * The chart is drawn at the width it is shown at: the SVG's user space is the
 * container's CSS pixels, so the 11px labels stay 11px on a phone instead of
 * shrinking with a fixed-size picture. Everything below takes that geometry.
 */

/** The width drawn before the container is measured (server render, first paint). */
export const DEFAULT_WIDTH = 640
/** Below this the plot has no room for its axes; the chart scales down instead. */
export const MIN_WIDTH = 200

/** Average glyph width as a share of the font size, for label widths. */
const GLYPH_WIDTH = 0.6

const MAX_HEIGHT = 300
const MIN_HEIGHT = 200
/** Height as a share of width on narrow screens, where 300px would be a tall strip. */
const HEIGHT_RATIO = 0.62

const PAD = { right: 12, top: 12, bottom: 40 } as const
/** Room between the y tick labels and the plot, and their font size. */
const TICK_GAP = 10
const TICK_LABEL_SIZE = 11

export interface Geometry {
  width: number
  height: number
  plotLeft: number
  plotRight: number
  plotTop: number
  plotBottom: number
  plotWidth: number
  plotHeight: number
}

/**
 * The geometry of a chart `width` CSS pixels wide whose longest y tick label
 * is `tickChars` characters: the left margin is sized to it, which on a phone
 * is the difference between a plot and a sliver.
 */
export function chartGeometry(width: number = DEFAULT_WIDTH, tickChars = 6): Geometry {
  const w = Number.isFinite(width) ? Math.max(MIN_WIDTH, Math.round(width)) : DEFAULT_WIDTH
  const height = Math.round(Math.min(MAX_HEIGHT, Math.max(MIN_HEIGHT, w * HEIGHT_RATIO)))
  const plotLeft = Math.round(tickChars * TICK_LABEL_SIZE * GLYPH_WIDTH + TICK_GAP)
  const plotRight = w - PAD.right
  const plotTop = PAD.top
  const plotBottom = height - PAD.bottom
  return {
    width: w,
    height,
    plotLeft,
    plotRight,
    plotTop,
    plotBottom,
    plotWidth: plotRight - plotLeft,
    plotHeight: plotBottom - plotTop,
  }
}

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
 *
 * A short plot gets fewer ticks, so their labels keep their spacing.
 */
export function buildYAxis(values: number[], geom: Geometry = chartGeometry()): YAxis {
  const targetTicks = geom.plotHeight < 200 ? 4 : 5
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

  const y = (value: number) => geom.plotBottom - ((value - min) / range) * geom.plotHeight

  return { min, max, ticks, y, zeroY: y(0) }
}

/** Trim float noise so 0.30000000000000004 prints as 0.3. */
export function formatTick(value: number): string {
  if (Number.isInteger(value)) return String(value)
  return String(Number(value.toFixed(4)))
}

/** Horizontal centre of a category slot. */
export function categoryCenter(index: number, count: number, geom: Geometry = chartGeometry()): number {
  const slot = geom.plotWidth / count
  return geom.plotLeft + slot * index + slot / 2
}

/** Font size of the category labels, in SVG user units (CSS pixels). */
export const CATEGORY_LABEL_SIZE = 11

/** The gap between neighbouring category labels. */
const LABEL_GAP = 6

/** Approximate rendered width of a category label, in SVG user units. */
function labelWidth(label: string): number {
  return label.length * CATEGORY_LABEL_SIZE * GLYPH_WIDTH
}

/**
 * Show every `step`-th category label: the smallest step at which no two
 * neighbouring shown labels overlap in a plot `plotWidth` wide.
 *
 * Found in a recorded answer: 21 daily labels such as "06-23" need about 33
 * units each and got about 27. A phone's narrower plot needs a larger step.
 * The hidden labels are still in the hover tooltip and the table view.
 */
export function categoryLabelStep(categories: readonly string[], plotWidth: number): number {
  const count = categories.length
  const slot = plotWidth / Math.max(count, 1)
  const fits = (step: number) => {
    for (let i = 0; i + step < count; i += step) {
      if ((labelWidth(categories[i]) + labelWidth(categories[i + step])) / 2 + LABEL_GAP > slot * step) return false
    }
    return true
  }
  let step = 1
  while (step < count && !fits(step)) step += 1
  return step
}
