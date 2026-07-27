/**
 * The one place that decides what "up", "down" and "flat" look like.
 *
 * Extracted from the portfolio screen when the artist screen needed the same
 * convention for 14-day growth. Two screens each picking their own green would
 * be a small thing to get wrong and a confusing one to read.
 */
export const GAIN = '#34d399';
export const LOSS = '#ef4444';

/**
 * Below this, a bars figure is rounding noise rather than a real move. Without
 * it, a lot bought at the current price renders as "-0.00" in red - a tiny
 * negative float presented to the user as a loss.
 */
export const FLAT_BARS = 0.005;

/**
 * Below this, a growth ratio is noise. Deliberately far smaller than FLAT_BARS
 * even though both are "0.5%-ish" numbers on their face: growth is a ratio, so
 * 0.005 would be half a percent, and half a percent of 14-day growth is a real
 * result here - it is roughly where Kai Ca$h sits. This threshold is a rounding
 * band for a figure shown to two decimal places as a percentage, nothing more.
 */
export const FLAT_RATIO = 0.00005;

/** Grey when flat, so a value that hasn't moved doesn't read as a loss. */
export function toneFor(value: number, flat: number, neutral: string) {
  if (Math.abs(value) < flat) return neutral;
  return value > 0 ? GAIN : LOSS;
}
