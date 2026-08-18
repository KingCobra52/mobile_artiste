"""
The read endpoints: /market, /artists/{id} and /artists/{id}/history.

The history tests carry the weight here. Its coverage walk-back is the subtlest
logic in the codebase and existed untested until now - it is what stops a chart
drawing a 40% crash on the day an artist's YouTube data first landed.
"""
import math

import pytest
from conftest import PRICE, PRICED_SIGNALS, FakeDB, artist_row, history_row

from api.pricing import SIGNAL_WEIGHTS, compute_momentum, compute_price_per_share

MARKET = "FROM artists"
HISTORY = "FROM artist_snapshots s"
SHARES_OWNED = "COALESCE(SUM(shares), 0)"


# --- /market ------------------------------------------------------------------

def test_market_prices_every_row(client):
    db = FakeDB(routes=[(MARKET, [
        artist_row(id=1, name="Kendrick Lamar"),
        artist_row(id=2, name="Kae"),
    ])])
    response = client(db).get("/market")
    assert response.status_code == 200

    rows = response.json()
    assert [r["name"] for r in rows] == ["Kendrick Lamar", "Kae"]
    assert all(r["price_per_share"] == pytest.approx(PRICE) for r in rows)


def test_market_keeps_an_artist_with_no_snapshots(client):
    """
    The LEFT JOIN intent. Flask used an inner join, so an artist with no snapshot
    row silently vanished from the market rather than showing up unpriced - which
    is a much harder thing to notice than a 0.00.
    """
    blank = artist_row(id=7, name="Brand New", date=None,
                       **{name: None for name in SIGNAL_WEIGHTS})
    db = FakeDB(routes=[(MARKET, [blank])])
    rows = client(db).get("/market").json()

    assert len(rows) == 1, "an artist without snapshots must still be listed"
    assert rows[0]["price_per_share"] == 0.0


def test_market_applies_momentum(client):
    """A growing artist prices above the identical artist with no growth history."""
    flat = artist_row(id=1)
    growing = artist_row(
        id=2,
        past_listeners=PRICED_SIGNALS["listeners"] / 1.05,
        past_playcount=PRICED_SIGNALS["playcount"] / 1.05,
        past_days=14,
    )
    db = FakeDB(routes=[(MARKET, [flat, growing])])
    rows = client(db).get("/market").json()

    assert rows[1]["price_per_share"] > rows[0]["price_per_share"]
    assert rows[0]["price_per_share"] == pytest.approx(PRICE)


# --- /artists/{id} ------------------------------------------------------------

def test_artist_returns_404_for_an_unknown_id(client):
    db = FakeDB(routes=[(MARKET, [])])
    assert client(db).get("/artists/999999").status_code == 404


def test_artist_reports_shares_owned_for_a_signed_in_caller(client):
    db = FakeDB(routes=[(SHARES_OWNED, [{"total": 12}]), (MARKET, [artist_row()])])
    assert client(db).get("/artists/1").json()["shares_owned"] == 12


def test_artist_reports_no_shares_when_signed_out(client):
    # The page is public; a signed-out viewer gets the price and owns nothing. The
    # sell control keys off this, so 0 has to mean 0 rather than absent.
    db = FakeDB(routes=[(SHARES_OWNED, [{"total": 12}]), (MARKET, [artist_row()])])
    response = client(db, authenticated=False).get("/artists/1")

    assert response.json()["shares_owned"] == 0
    assert not db.sql_matching(SHARES_OWNED), "no holdings lookup for an anonymous caller"


def test_artist_growth_matches_the_pricing_formula(client):
    """
    growth_14d must be the same number the price is built from, only expressed as a
    ratio - not a second calculation that can drift from it.
    """
    row = artist_row(
        past_listeners=PRICED_SIGNALS["listeners"] / 1.05,
        past_playcount=PRICED_SIGNALS["playcount"] / 1.05,
        past_days=14,
    )
    db = FakeDB(routes=[(SHARES_OWNED, [{"total": 0}]), (MARKET, [row])])
    body = client(db).get("/artists/1").json()

    assert body["growth_14d"] == pytest.approx(math.expm1(compute_momentum(row)))
    assert body["growth_14d"] > 0


def test_artist_growth_is_zero_without_a_lookback(client):
    db = FakeDB(routes=[(SHARES_OWNED, [{"total": 0}]), (MARKET, [artist_row()])])
    assert client(db).get("/artists/1").json()["growth_14d"] == 0.0


# --- /artists/{id}/history ----------------------------------------------------

def test_history_of_an_artist_with_no_snapshots_is_empty(client):
    db = FakeDB(routes=[(HISTORY, [])])
    response = client(db).get("/artists/1/history")
    assert response.status_code == 200
    assert response.json() == []


def test_history_returns_a_point_per_comparable_day(client):
    rows = [history_row(f"2026-07-{day:02d}") for day in (20, 21, 22)]
    db = FakeDB(routes=[(HISTORY, rows)])
    points = client(db).get("/artists/1/history").json()

    assert [p["date"] for p in points] == ["2026-07-20", "2026-07-21", "2026-07-22"]


def test_history_drops_days_before_a_coverage_change(client):
    """
    The artefact this filter exists for. Renormalisation keeps a Last.fm-only price
    on the same scale as a full-signal price, but they are not the same
    measurement, so charting across the change draws a cliff where nothing
    happened - Kae fell 3.52 bars in a day when its YouTube data first landed.
    """
    rows = [
        history_row("2026-07-18", subscribers=None, recent_videos_avg_views=None,
                    recent_videos_avg_likes=None),
        history_row("2026-07-19", subscribers=None, recent_videos_avg_views=None,
                    recent_videos_avg_likes=None),
        history_row("2026-07-20"),
        history_row("2026-07-21"),
    ]
    db = FakeDB(routes=[(HISTORY, rows)])
    points = client(db).get("/artists/1/history").json()

    assert [p["date"] for p in points] == ["2026-07-20", "2026-07-21"]


def test_history_drops_days_with_no_momentum_window(client):
    """
    The first days of any history have nothing to measure growth against, so they
    price with no momentum term. Charting them beside days that have one would step
    on the day the term switches on.
    """
    rows = [
        history_row("2026-07-18", past_listeners=None, past_playcount=None, past_days=None),
        history_row("2026-07-19"),
        history_row("2026-07-20"),
    ]
    db = FakeDB(routes=[(HISTORY, rows)])
    points = client(db).get("/artists/1/history").json()

    assert [p["date"] for p in points] == ["2026-07-19", "2026-07-20"]


def test_history_truncates_at_a_flicker_rather_than_reaching_past_it(client):
    """
    A single missing day mid-history stops the walk-back - it does not skip the gap
    and carry on collecting older days. That is the difference between this and a
    filter that simply drops non-matching rows: splicing 07-18 onto 07-20 would
    join two series that aren't comparable while looking perfectly continuous.
    """
    rows = [
        history_row("2026-07-18"),
        history_row("2026-07-19", subscribers=None),
        history_row("2026-07-20"),
        history_row("2026-07-21"),
    ]
    db = FakeDB(routes=[(HISTORY, rows)])
    points = client(db).get("/artists/1/history").json()

    assert [p["date"] for p in points] == ["2026-07-20", "2026-07-21"]
    assert "2026-07-18" not in [p["date"] for p in points], "must not reach past the gap"


def test_history_right_edge_equals_the_live_price(client):
    """
    The chart's last point and the price on the same screen come from different
    queries anchored on different date columns - a.date for the live price, s.date
    for history. If those disagree the chart ends somewhere the price isn't.
    """
    latest = history_row("2026-07-21")
    db = FakeDB(routes=[(HISTORY, [history_row("2026-07-20"), latest])])
    points = client(db).get("/artists/1/history").json()

    assert points[-1]["price"] == pytest.approx(compute_price_per_share(latest))
