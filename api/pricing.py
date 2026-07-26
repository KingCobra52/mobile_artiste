"""
Share pricing. Ported verbatim from artistev0/app.py so the FastAPI and Flask
apps price identically during the migration - any change here must be mirrored
there until Flask is retired.

Note that artistev0/scripts/calibrate_pricing.py prints a SIGNAL_WEIGHTS block
aimed at app.py. Once this module is the authoritative one, paste its output
here instead.
"""
import math

PRICE_SCALE = 50

# weight: relative importance, chosen for now (not yet calibrated against real data)
# typical_value: a "typical" artist's value for this signal, used to scale log1p(value) to ~1
#
# Recalibrated 2026-07-26 via scripts/calibrate_pricing.py. The previous YouTube
# divisors were computed while 11 of 25 artists were matched to the wrong channel,
# which held those three medians 6-20x too low; the two Last.fm divisors barely moved.
SIGNAL_WEIGHTS = {
    "listeners": (0.4, math.log1p(1539763.0)),
    "playcount": (0.1, math.log1p(109573276.0)),
    "subscribers": (0.25, math.log1p(3310000.0)),
    "recent_videos_avg_views": (0.2, math.log1p(2126874.5)),
    "recent_videos_like_ratio": (0.05, math.log1p(32199.24)),
}


def compute_price_per_share(signals):
    """
    signals: dict-like mapping of signal name -> raw value, missing/None entries are
    skipped and the remaining weights are renormalized so price stays on a consistent
    scale whether or not YouTube data is available for this artist.
    """
    weighted_sum = 0.0
    weight_total = 0.0
    for name, (weight, divisor) in SIGNAL_WEIGHTS.items():
        value = signals.get(name)
        if value is None:
            continue
        weighted_sum += weight * math.log1p(value) / divisor
        weight_total += weight
    if weight_total == 0:
        return 0.0
    return PRICE_SCALE * weighted_sum / weight_total
