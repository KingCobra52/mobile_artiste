"""
Guards the verbatim copy of the pricing formula from artistev0/app.py.

These mirror the assertions in artistev0/tests/test_app.py, so if the two copies
of SIGNAL_WEIGHTS ever drift apart, one of the two suites fails.
"""
import math

import pytest

from api.pricing import PRICE_SCALE, SENSITIVITY, SIGNAL_WEIGHTS, compute_price_per_share

# An artist sitting exactly on the roster median for every signal. Read straight
# out of SIGNAL_WEIGHTS rather than hardcoded, so recalibrating can't silently
# invalidate these.
TYPICAL_SIGNALS = {name: typical for name, (_weight, typical) in SIGNAL_WEIGHTS.items()}


def test_typical_artist_prices_at_price_scale():
    assert compute_price_per_share(TYPICAL_SIGNALS) == pytest.approx(PRICE_SCALE, rel=1e-9)


def test_missing_signals_renormalize():
    # Last.fm data only: the remaining weights renormalize so a typical artist still
    # prices at PRICE_SCALE instead of being penalised for absent YouTube data.
    # This is the path BunnaB takes, having no verified YouTube channel.
    partial = {
        "listeners": TYPICAL_SIGNALS["listeners"],
        "playcount": TYPICAL_SIGNALS["playcount"],
    }
    assert compute_price_per_share(partial) == pytest.approx(PRICE_SCALE, rel=1e-9)


def test_no_signals_is_zero():
    assert compute_price_per_share({name: None for name in SIGNAL_WEIGHTS}) == 0.0


def test_zero_is_not_treated_as_missing():
    # A literal 0 is a real measurement, not absent data - it scores far below par
    # rather than dropping out. This is the distinction the pipeline's NULL-vs-0
    # fix relies on, and the reason a missing signal must never be written as 0.
    zeroed = dict(TYPICAL_SIGNALS, subscribers=0)
    missing = dict(TYPICAL_SIGNALS, subscribers=None)
    assert compute_price_per_share(zeroed) < compute_price_per_share(TYPICAL_SIGNALS)
    assert compute_price_per_share(missing) == pytest.approx(PRICE_SCALE, rel=1e-9)


def test_price_tracks_relative_change():
    """
    The property the old formula lacked: a proportional rise in a signal should
    produce a proportional rise in price, not a damped one.

    Under log-ratio scoring a 5% listener gain moved the price ~0.4%. Here the
    same gain moves it by 5% * SENSITIVITY * (weight share), which for listeners
    at weight 0.4 of 1.0 total is a visible fraction rather than noise.
    """
    grown = dict(TYPICAL_SIGNALS, listeners=TYPICAL_SIGNALS["listeners"] * 1.05)
    ratio = compute_price_per_share(grown) / compute_price_per_share(TYPICAL_SIGNALS)

    weight_share = SIGNAL_WEIGHTS["listeners"][0] / sum(w for w, _ in SIGNAL_WEIGHTS.values())
    expected = math.exp(SENSITIVITY * weight_share * math.log(1.05))
    assert ratio == pytest.approx(expected, rel=1e-6)
    # And concretely: comfortably more than the ~1.0004 the old formula produced
    assert ratio > 1.009


def test_baseline_is_frozen():
    """
    Golden values. If this fails you have refreshed the baseline from the roster
    median, which is the one thing these numbers must never do.

    Refreshing reprices every open position (holdings.price_per_share is a cost
    basis frozen at purchase) and erases market-wide growth, while changing
    nothing about relative prices - the baseline only sets the price level.

    If a rebase is genuinely intended, it is safe only when every
    holdings.price_per_share is multiplied by the same factor in the same
    transaction. See the comment above SIGNAL_WEIGHTS. Then update these values.
    """
    assert {name: baseline for name, (_w, baseline) in SIGNAL_WEIGHTS.items()} == {
        "listeners": 1607645.5,
        "playcount": 134880889.5,
        "subscribers": 3310000.0,
        "recent_videos_avg_views": 2126874.5,
        "recent_videos_like_ratio": 32199.24,
    }


def test_baseline_only_moves_the_price_level():
    """
    The property the whole freeze rests on: changing the baseline multiplies every
    artist's price by one constant, so it cannot change who is expensive.
    """
    small = {"listeners": 50_000, "playcount": 240_000}
    large = {"listeners": 5_000_000, "playcount": 1_000_000_000}

    shifted = {name: (w, b * 1.2) for name, (w, b) in SIGNAL_WEIGHTS.items()}

    def price_under(signals, weights):
        total = weight_total = 0.0
        for name, (weight, baseline) in weights.items():
            value = signals.get(name)
            if value is None:
                continue
            total += weight * (math.log1p(value) - math.log1p(baseline))
            weight_total += weight
        return PRICE_SCALE * math.exp(SENSITIVITY * total / weight_total)

    ratios = [
        price_under(s, shifted) / price_under(s, SIGNAL_WEIGHTS) for s in (small, large)
    ]
    assert ratios[0] == pytest.approx(ratios[1], rel=1e-12)


def test_bigger_artist_prices_higher():
    small = {"listeners": 50_000, "playcount": 240_000}
    large = {"listeners": 5_000_000, "playcount": 1_000_000_000}
    assert compute_price_per_share(large) > compute_price_per_share(small) * 5
