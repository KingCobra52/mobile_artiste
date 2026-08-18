"""
Guards the verbatim copy of the pricing formula from artistev0/app.py.

These mirror the assertions in artistev0/tests/test_app.py, so if the two copies
of SIGNAL_WEIGHTS ever drift apart, one of the two suites fails.
"""
import math

import pytest

from api.pricing import (
    MOMENTUM,
    MOMENTUM_WINDOW_DAYS,
    PRICE_SCALE,
    SENSITIVITY,
    SIGNAL_WEIGHTS,
    compute_momentum,
    compute_price_per_share,
)

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
        "recent_videos_avg_likes": 32199.24,
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


# --- momentum ---------------------------------------------------------------
#
# Every test above passes a dict with no lookback columns, so they all price at
# zero growth. That is the point of the design: adding momentum changed no call
# site and no existing expectation.


def _with_growth(rate, days=MOMENTUM_WINDOW_DAYS):
    """A row whose Last.fm signals grew by `rate` over `days`."""
    return dict(
        TYPICAL_SIGNALS,
        past_listeners=TYPICAL_SIGNALS["listeners"] / (1 + rate),
        past_playcount=TYPICAL_SIGNALS["playcount"] / (1 + rate),
        past_days=days,
    )


@pytest.mark.parametrize("missing", ["past_days", "past_listeners", "past_playcount"])
def test_momentum_is_zero_without_a_full_lookback(missing):
    # A caller that didn't join the lookback, or an artist whose history is
    # shorter than the window, must score no growth rather than guess at one.
    row = _with_growth(0.05)
    row[missing] = None
    assert compute_momentum(row) == 0.0
    assert compute_price_per_share(row) == pytest.approx(PRICE_SCALE, rel=1e-9)


def test_momentum_is_exactly_zero_for_a_flat_artist():
    # Not approximately zero: an artist who didn't move must not drift, or every
    # price picks up noise from a term that should be silent.
    flat = dict(
        TYPICAL_SIGNALS,
        past_listeners=TYPICAL_SIGNALS["listeners"],
        past_playcount=TYPICAL_SIGNALS["playcount"],
        past_days=MOMENTUM_WINDOW_DAYS,
    )
    assert compute_momentum(flat) == 0.0


def test_momentum_normalizes_a_stale_lookback():
    """
    The lookback lands on the newest snapshot at or before the cutoff, so a gap in
    collection makes it older than the window. Growth must be scaled back to the
    window length: 5% over 28 days is half the momentum of 5% over 14, not the same.
    """
    over_window = compute_momentum(_with_growth(0.05, days=MOMENTUM_WINDOW_DAYS))
    over_double = compute_momentum(_with_growth(0.05, days=2 * MOMENTUM_WINDOW_DAYS))
    assert over_double == pytest.approx(over_window / 2, rel=1e-12)


def test_momentum_ignores_the_frozen_baseline():
    """
    Momentum is a difference of two levels, so the baselines cancel. This pins the
    v1.2 property: a rebase moves the price level and still cannot touch growth.
    """
    row = _with_growth(0.05)
    before = compute_momentum(row)

    original = dict(SIGNAL_WEIGHTS)
    SIGNAL_WEIGHTS.update({name: (w, b * 1.2) for name, (w, b) in original.items()})
    try:
        assert compute_momentum(row) == before
    finally:
        SIGNAL_WEIGHTS.update(original)


def test_momentum_ignores_youtube_signals():
    # The two reasons growth reads Last.fm only: half the roster has no comparable
    # YouTube history, and recent_videos_avg_views jumps 50%+ when a video drops.
    row = _with_growth(0.05)
    spiked = dict(row, recent_videos_avg_views=TYPICAL_SIGNALS["recent_videos_avg_views"] * 2)
    assert compute_momentum(spiked) == compute_momentum(row)


def test_growth_raises_price_over_a_flat_artist():
    """
    Golden value, so MOMENTUM and the window can't drift silently. A baseline
    artist growing 5% over 14 days sits at 216.10 rather than PRICE_SCALE: every
    level term is zero at the baseline, so the whole premium is momentum.
    """
    price = compute_price_per_share(_with_growth(0.05))
    assert price == pytest.approx(216.09695697, rel=1e-9)
    assert price > PRICE_SCALE


def test_growth_premium_matches_the_closed_form():
    """
    Separate from the golden above because the tolerance means something different.
    Growth of exactly 5% should lift price by exp(MOMENTUM * ln(1.05)), and it does
    to within 7.5e-7 - the residual is log1p vs log at signal magnitudes in the
    millions, not an error. Loose enough to be about the formula rather than that gap.
    """
    price = compute_price_per_share(_with_growth(0.05))
    assert price == pytest.approx(PRICE_SCALE * math.exp(MOMENTUM * math.log(1.05)), rel=1e-5)


def test_no_signals_stays_zero_even_with_growth():
    # The untradeable guard runs ahead of momentum: an artist with no price basis
    # must stay at 0.0, not be lifted off the floor by a growth term.
    row = {name: None for name in SIGNAL_WEIGHTS}
    row.update(past_listeners=1_000_000, past_playcount=1_000_000, past_days=14)
    assert compute_price_per_share(row) == 0.0
