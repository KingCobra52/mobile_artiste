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


def test_bigger_artist_prices_higher():
    small = {"listeners": 50_000, "playcount": 240_000}
    large = {"listeners": 5_000_000, "playcount": 1_000_000_000}
    assert compute_price_per_share(large) > compute_price_per_share(small) * 5
