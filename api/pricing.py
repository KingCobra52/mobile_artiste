"""
Share pricing.

Price has two terms:

    price = PRICE_SCALE * exp(SENSITIVITY * level + MOMENTUM * growth)

LEVEL scores each signal by how far it sits from a baseline artist's, in log space,
then exponentiates the weighted average. The log DIFFERENCE is what makes this
respond to change: it is the log of the ratio, so a 5% rise in listeners moves the
score by ln(1.05) regardless of whether the artist has fifty thousand or six million.

The previous formula divided log1p(value) by log1p(baseline) - a ratio of logs,
which is nearly flat once both numbers are large. Kae's listeners grew 5.4% over
45 days and the price moved 0.47%; every artist was similarly damped, and the
largest price movement anywhere in 45 days of history was 0.185 bars. A market
that doesn't move has nothing to chart and nothing to play.

GROWTH is the trailing 14-day change in the artist's own Last.fm signals. Level
alone still did not move day to day - median daily price change was 0.020% - and
SENSITIVITY cannot fix that, because it scales the cross-artist spread and the size
of a daily move by the same factor. See the comment on MOMENTUM below.
"""
import math

# An artist sitting exactly on the baseline for every signal, with flat growth,
# prices here. Every log difference is 0, exp(0) is 1.

# How far apart artists sit. Modelled against the live roster:
#
#   value  cheapest -> dearest    spread   median daily move
#   0.25    13.83 -> 81.76         5.9x      0.010%
#   0.5      3.82 -> 133.69       35.0x      0.020%     <- here
#   0.75     1.06 -> 218.61      206.7x      0.030%
#   1.0      0.29 -> 357.48     1222.5x      0.040%
#
# LEAVE THIS ALONE. It looks like the knob for "how much does the market move",
# and it isn't - it scales the spread and the daily move by the same factor, so
# every setting that produces visible daily movement destroys the price scale.
# Measured over the 294 day-pairs in the database: a 0.2%/day median needs 4.9,
# where the spread is 1.14e+15x and the cheapest artist costs 6.45e-10 bars; a
# 0.5%/day median needs 12.2 and 3.82e+37x. Daily movement is four orders of
# magnitude smaller than the cross-artist spread in log space, and one constant
# cannot separate them. MOMENTUM below is the knob that does.


# How hard price reacts to growth. This is the free knob: it moves day-to-day
# feel without touching the spread, because growth and level are separate terms.
# Measured over the 294 day-pairs the history endpoint actually serves:
#
#   value  median daily   p90 daily   fast/slow premium   rank changes   cheapest -> dearest
#     0       0.020%        0.072%          1.00x              -          3.82 -> 133.69
#    30       0.302%        1.60%           1.51x             9/24        4.09 -> 147.50   <- here
#    50       0.508%        2.69%           1.99x            12/24        4.27 -> 157.48
#    95       0.974%        5.02%           3.68x            19/24        4.72 -> 182.49
#
# 30 gives 15x the movement of level alone while growth reorders 9 of 24 positions
# and size still decides the hierarchy - Kendrick stays first, Kai Ca$h last. Past
# about 50 growth starts outweighing size and the board stops reading as a ranking.
#
# Note the daily figures are damped by gaps in collection, and only by those: on
# 31% of day-pairs the lookback lands on the same row two days running, so momentum
# barely moves. The database currently holds 35 snapshots across 45 days. As the
# pipeline settles into a daily rhythm every day advances the lookback and these
# numbers rise on their own, without touching this constant.


# Growth is measured over a trailing window, and the window is what creates daily
# movement: each day it drops an old day and picks up a new one, so price moves
# even on a day when the signals themselves didn't. 7 days compresses the roster
# into a span too narrow to tell artists apart; 28 would leave only a handful of
# chartable points against 45 days of history. 14 currently spreads the roster
# from Kai Ca$h at +0.22% to Kae at +1.61%, with 22 points on the fullest charts.
#
# Counted in CALENDAR days, not in snapshots - see momentum_lookback_sql below.
# Collection has gaps, so the two differ: 14 rows back is presently about 18 days.

# Growth deliberately reads only the Last.fm signals, for two separate reasons:
#
# 1. Coverage. The YouTube history is comparable for 22 days on 14 artists but only
#    ONE day on the other 10, because the wrong-channel cleanup nulled their rows
#    before 2026-07-26. Differencing all five signals would leave nearly half the
#    roster with no growth term. listeners and playcount are complete - 24 artists
#    x 35 days, zero nulls - so every artist gets a real one.
#
# 2. Spikiness. recent_videos_avg_views produces 71% of all daily price movement
#    out of 3 days in 294, with a single-day maximum of 53.68%. That is a new video
#    re-rolling the "recent" window, not popularity moving. Differencing it would
#    make a release-schedule artifact the loudest signal in the market.
#
# Weighted toward listeners for the same reason SIGNAL_WEIGHTS is: playcount is
# cumulative, so its growth rate decays as the total grows and says less each year.

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
# The momentum term is unaffected by any of this: it is a difference of two levels,
# so the baselines cancel exactly and growth cannot be changed by rebasing.
#
# api/scripts/calibrate_pricing.py reports how far the roster has drifted from
# these. It is diagnostic; it deliberately emits nothing to paste back here.

PRICE_SCALE = 50
SENSITIVITY = 0.5
MOMENTUM = 30
MOMENTUM_WINDOW_DAYS = 14

MOMENTUM_WEIGHTS = {
    "listeners": 0.8,
    "playcount": 0.2,
}

SIGNAL_WEIGHTS = {
    "listeners": (0.4, 1607645.5),
    "playcount": (0.1, 134880889.5),
    "subscribers": (0.25, 3310000.0),
    "recent_videos_avg_views": (0.2, 2126874.5),
    "recent_videos_like_ratio": (0.05, 32199.24),
}


def momentum_lookback_sql(artist_id: str, anchor: str) -> str:
    """LATERAL join carrying the start of the momentum window onto a row. Every pricing query must use this same SQL, or it prices without growth."""
    return f"""
    LEFT JOIN LATERAL (
        SELECT listeners AS past_listeners, playcount AS past_playcount,
               {anchor} - date AS past_days
        FROM artist_snapshots
        WHERE artist_snapshots.artist_id = {artist_id}
          AND date <= {anchor} - {MOMENTUM_WINDOW_DAYS}
        ORDER BY date DESC LIMIT 1
    ) p ON true
    """


def _momentum_level(listeners, playcount):
    """Weighted log-level of the Last.fm signals, or None if either is missing."""
    if listeners is None or playcount is None:
        return None
    return (
        MOMENTUM_WEIGHTS["listeners"] * math.log1p(listeners)
        + MOMENTUM_WEIGHTS["playcount"] * math.log1p(playcount)
    ) / sum(MOMENTUM_WEIGHTS.values())


def compute_momentum(signals):
    """Trailing growth normalized to a MOMENTUM_WINDOW_DAYS window. Returns 0.0 if past_listeners/past_playcount/past_days (from momentum_lookback_sql) are missing."""
    past_days = signals.get("past_days")
    if not past_days:
        return 0.0
    now = _momentum_level(signals.get("listeners"), signals.get("playcount"))
    then = _momentum_level(signals.get("past_listeners"), signals.get("past_playcount"))
    if now is None or then is None:
        return 0.0
    return (now - then) * MOMENTUM_WINDOW_DAYS / past_days


def compute_price_per_share(signals):
    """Weighted price from signals (name -> raw value). Missing entries are skipped and remaining weights renormalized; missing growth columns score zero growth."""
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
        # No signals at all means no price basis, and no amount of growth makes
        # one. Ahead of the momentum term deliberately: this is what keeps an
        # artist with no snapshots untradeable rather than free.
        return 0.0
    level = weighted_sum / weight_total
    return PRICE_SCALE * math.exp(
        SENSITIVITY * level + MOMENTUM * compute_momentum(signals)
    )
