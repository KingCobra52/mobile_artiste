"""
Tests for the backtest harness.

Nothing here touches the database - load() does that and is exercised by running
the script. What is tested is the part that could quietly corrupt the running
application: score() swaps api.pricing's module-level constants to price history
under a candidate config, and if it ever failed to put them back, every subsequent
call to compute_price_per_share in the same process would use the candidate.
"""
import pytest
from conftest import artist_row, history_row

from api import pricing
from api.routers.artists import _coverage
from api.scripts.backtest import comparable_tail, coverage, score

SHIPPED = (pricing.SENSITIVITY, pricing.MOMENTUM, pricing.MOMENTUM_WINDOW_DAYS)


def test_scoring_restores_the_shipped_constants():
    series = {"A": [history_row("2026-07-20"), history_row("2026-07-21")]}
    score(series, sensitivity=99.0, momentum=999.0, window=3)

    assert (pricing.SENSITIVITY, pricing.MOMENTUM, pricing.MOMENTUM_WINDOW_DAYS) == SHIPPED


def test_constants_are_restored_even_when_scoring_raises():
    # The try/finally is the whole protection here. Without it a crash mid-score
    # leaves the live pricing module holding a candidate config, and every price
    # the process serves afterwards is wrong with nothing to indicate it.
    with pytest.raises(Exception):
        score({"A": "not a list of rows"}, sensitivity=99.0, momentum=999.0, window=3)

    assert (pricing.SENSITIVITY, pricing.MOMENTUM, pricing.MOMENTUM_WINDOW_DAYS) == SHIPPED


def test_coverage_matches_the_endpoint():
    """
    The harness has its own copy of the comparability rule so it can run over raw
    rows. If the endpoint's rule changes and this one doesn't, the harness scores a
    market nobody is served - which is the exact class of error it exists to catch.
    """
    rows = [
        history_row("2026-07-20"),
        history_row("2026-07-21", subscribers=None),
        history_row("2026-07-22", past_days=None),
        artist_row(),
    ]
    for row in rows:
        assert coverage(row) == _coverage(row)


def test_comparable_tail_stops_at_a_gap():
    rows = [
        history_row("2026-07-18"),
        history_row("2026-07-19", subscribers=None),
        history_row("2026-07-20"),
        history_row("2026-07-21"),
    ]
    assert [r["date"] for r in comparable_tail(rows)] == ["2026-07-20", "2026-07-21"]


def test_more_momentum_moves_prices_more():
    """The property the whole tool is used to compare: turning MOMENTUM up raises
    day-to-day movement. If this ever inverts, the metric is measuring nothing."""
    series = {
        "A": [
            history_row("2026-07-20", past_listeners=1_000_000, past_playcount=50_000_000),
            history_row("2026-07-21", past_listeners=1_100_000, past_playcount=55_000_000),
            history_row("2026-07-22", past_listeners=1_200_000, past_playcount=60_000_000),
        ]
    }
    quiet = score(series, 0.5, 10, 14)
    loud = score(series, 0.5, 60, 14)
    assert loud["median_daily"] > quiet["median_daily"]
