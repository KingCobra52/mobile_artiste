"""
Share pricing.

Scores each signal by how far it sits from a typical artist's, in log space, then
exponentiates the weighted average. The log DIFFERENCE is what makes this respond
to change: it is the log of the ratio, so a 5% rise in listeners moves the score
by ln(1.05) regardless of whether the artist has fifty thousand or six million.

The previous formula divided log1p(value) by log1p(typical) - a ratio of logs,
which is nearly flat once both numbers are large. Kae's listeners grew 5.4% over
45 days and the price moved 0.47%; every artist was similarly damped, and the
largest price movement anywhere in 45 days of history was 0.185 bars. A market
that doesn't move has nothing to chart and nothing to play.
"""
import math

# A typical artist - one sitting exactly at the roster median on every signal -
# prices here. Every ratio is 1, every log difference is 0, exp(0) is 1.
PRICE_SCALE = 50

# How hard price reacts. One constant governs both how far apart artists sit and
# how much a single artist moves, because they're the same quantity: price is a
# function of distance-from-typical either way. Modelled against the live roster:
#
#   value  cheapest -> dearest   spread   Kae's 45-day move
#   0.25    13.96 -> 82.54        5.9x      1.37%
#   0.5      3.90 -> 136.26      35.0x      2.76%     <- here
#   0.75     1.09 -> 224.94     206.7x      4.16%
#   1.0      0.30 -> 371.34    1222.5x      5.59%
#
# 0.5 keeps a spread that reads like a real market with everything still buyable.
# At 1.0 movement is faithfully proportional but the floor collapses to 0.30 bars,
# where 10,000 bars buys 33,000 shares and integer share counts stop meaning much.
SENSITIVITY = 0.5

# weight: relative importance, chosen for now (not yet calibrated against real data)
# typical: the roster median for this signal, the point that prices at PRICE_SCALE
#
# Recalibrated 2026-07-26 via api/scripts/calibrate_pricing.py. These are raw
# values, not logs - the pricing function takes log1p itself.
SIGNAL_WEIGHTS = {
    "listeners": (0.4, 1539763.0),
    "playcount": (0.1, 109573276.0),
    "subscribers": (0.25, 3310000.0),
    "recent_videos_avg_views": (0.2, 2126874.5),
    "recent_videos_like_ratio": (0.05, 32199.24),
}


def compute_price_per_share(signals):
    """
    signals: dict-like mapping of signal name -> raw value. Missing/None entries
    are skipped and the remaining weights are renormalized, so price stays on a
    consistent scale whether or not YouTube data is available for this artist.
    """
    weighted_sum = 0.0
    weight_total = 0.0
    for name, (weight, typical) in SIGNAL_WEIGHTS.items():
        value = signals.get(name)
        if value is None:
            continue
        # log1p rather than log so a genuine zero is representable: it scores as
        # -log1p(typical), far below par, rather than blowing up.
        weighted_sum += weight * (math.log1p(value) - math.log1p(typical))
        weight_total += weight
    if weight_total == 0:
        return 0.0
    return PRICE_SCALE * math.exp(SENSITIVITY * weighted_sum / weight_total)
