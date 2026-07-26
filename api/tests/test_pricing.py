"""
Guards the verbatim copy of the pricing formula from artistev0/app.py.

These mirror the assertions in artistev0/tests/test_app.py, so if the two copies
of SIGNAL_WEIGHTS ever drift apart, one of the two suites fails.
"""
import math

import pytest

from api.pricing import PRICE_SCALE, SIGNAL_WEIGHTS, compute_price_per_share

# The raw "typical" values the divisors were calibrated from - an artist with
# exactly these signals should price at exactly PRICE_SCALE. Derived from
# SIGNAL_WEIGHTS (each divisor is log1p(typical)) rather than hardcoded, so
# recalibrating can't silently invalidate these.
TYPICAL_SIGNALS = {
    name: math.expm1(divisor) for name, (_weight, divisor) in SIGNAL_WEIGHTS.items()
}


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
    # A literal 0 is a real measurement, not absent data - log1p(0) = 0 drags the
    # price down. This is the distinction the pipeline's NULL-vs-0 fix relies on.
    zeroed = dict(TYPICAL_SIGNALS, subscribers=0)
    assert compute_price_per_share(zeroed) < compute_price_per_share(TYPICAL_SIGNALS)
