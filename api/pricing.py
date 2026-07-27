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
# baseline: a FIXED reference point, not a live median. An artist sitting exactly
#           on these figures prices at PRICE_SCALE. Raw values, not logs - the
#           pricing function takes log1p itself.
#
# DO NOT REFRESH THESE FROM THE CURRENT ROSTER. They were seeded from the roster
# median on 2026-07-26 and are frozen there deliberately. Three reasons:
#
# 1. They cannot improve the market. The baseline term factors out of the formula
#    as a global constant - price_i = [PRICE_SCALE * exp(-k*C)] * exp(k*A_i) - so
#    it only sets the price LEVEL and has no effect on relative prices. Measured:
#    a 20% move in the listeners baseline shifted every artist by exactly
#    -3.5807%, with 0.000000 percentage points of variation.
#
# 2. Refreshing erases market-wide growth. A median grows with the roster, so if
#    every artist's signals rise 10% and the baseline is then refreshed, every
#    price returns to exactly where it started. The market could only ever express
#    relative performance: if everyone doubles, nobody gains.
#
# 3. Refreshing reprices open positions. The 2026-07-26 refresh moved every artist
#    -1.88%. holdings.price_per_share is a cost basis frozen at purchase, so a
#    level shift hands every holder a gain or loss they did not earn.
#
# If the level ever genuinely needs rebasing - years of growth leaving everything
# far from PRICE_SCALE - it can be done without harming anyone, and that follows
# from point 1. A baseline change multiplies every price by the same constant f,
# so multiplying every holdings.price_per_share by that same f in the SAME
# transaction leaves every position's gain and loss exactly unchanged. Do it that
# way or not at all.
#
# api/scripts/calibrate_pricing.py reports how far the roster has drifted from
# these. It is diagnostic; it deliberately emits nothing to paste back here.
SIGNAL_WEIGHTS = {
    "listeners": (0.4, 1607645.5),
    "playcount": (0.1, 134880889.5),
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
    for name, (weight, baseline) in SIGNAL_WEIGHTS.items():
        value = signals.get(name)
        if value is None:
            continue
        # log1p rather than log so a genuine zero is representable: it scores as
        # -log1p(baseline), far below par, rather than blowing up.
        weighted_sum += weight * (math.log1p(value) - math.log1p(baseline))
        weight_total += weight
    if weight_total == 0:
        return 0.0
    return PRICE_SCALE * math.exp(SENSITIVITY * weighted_sum / weight_total)
