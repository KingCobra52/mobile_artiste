"""
/portfolio and /leaderboard.

The leaderboard tests matter most. Its query returns one row per artist held, and
collapsing that back to one entry per user is the kind of arithmetic that goes
wrong quietly: a wrong balance still looks like a balance.
"""
import pytest
from conftest import (
    OTHER_USER_ID,
    PRICE,
    USER_ID,
    FakeDB,
    leaderboard_row,
    portfolio_row,
)

PORTFOLIO = "FROM holdings"
LEADERBOARD = "FROM profiles"
BALANCE = "SELECT bars FROM profiles"


# --- /portfolio ---------------------------------------------------------------

def test_portfolio_requires_authentication(client):
    db = FakeDB()
    assert client(db, authenticated=False).get("/portfolio").status_code == 401


def test_portfolio_values_each_lot_at_its_own_purchase_price(client):
    """
    Two lots of the same artist bought at different prices. Gain is measured per
    lot against what that lot cost, which is why the query returns one row per
    purchase rather than aggregating by artist - averaging them would report a
    single blended number that matches neither lot.
    """
    db = FakeDB(routes=[
        (BALANCE, [{"bars": 5000}]),
        (PORTFOLIO, [
            portfolio_row(holding_id=1, shares=2, price_per_share=100.0),
            portfolio_row(holding_id=2, shares=3, price_per_share=200.0),
        ]),
    ])
    body = client(db).get("/portfolio").json()

    cheap, dear = body["holdings"]
    assert cheap["gain_loss"] == pytest.approx((PRICE - 100.0) * 2)
    assert dear["gain_loss"] == pytest.approx((PRICE - 200.0) * 3)
    assert cheap["gain_loss"] != dear["gain_loss"], "lots must not be blended"


def test_portfolio_value_is_price_times_shares(client):
    db = FakeDB(routes=[
        (BALANCE, [{"bars": 5000}]),
        (PORTFOLIO, [portfolio_row(shares=4)]),
    ])
    holding = client(db).get("/portfolio").json()["holdings"][0]

    assert holding["current_price"] == pytest.approx(PRICE)
    assert holding["current_value"] == pytest.approx(PRICE * 4)


def test_portfolio_totals_sum_the_lots(client):
    db = FakeDB(routes=[
        (BALANCE, [{"bars": 5000}]),
        (PORTFOLIO, [
            portfolio_row(holding_id=1, shares=2, price_per_share=100.0),
            portfolio_row(holding_id=2, shares=3, price_per_share=200.0),
        ]),
    ])
    body = client(db).get("/portfolio").json()

    assert body["bars"] == "5000"
    assert body["holdings_value"] == pytest.approx(PRICE * 5)
    assert body["total_gain_loss"] == pytest.approx(
        (PRICE - 100.0) * 2 + (PRICE - 200.0) * 3
    )


def test_portfolio_with_no_holdings_is_empty_not_an_error(client):
    db = FakeDB(routes=[(BALANCE, [{"bars": 10000}]), (PORTFOLIO, [])])
    body = client(db).get("/portfolio").json()

    assert body["holdings"] == []
    assert body["holdings_value"] == 0
    assert body["bars"] == "10000"


# --- /leaderboard -------------------------------------------------------------

def test_leaderboard_counts_a_balance_once_per_user(client):
    """
    The regression this suite was written for.

    The query repeats user_id, username and bars on every artist held, so bars must
    be ASSIGNED per user. Accumulating it would multiply the balance by the number
    of artists held - three artists would report 30,000 bars against 10,000 held,
    and it would look entirely plausible on the screen.
    """
    db = FakeDB(routes=[(LEADERBOARD, [
        leaderboard_row(shares=1),
        leaderboard_row(shares=1),
        leaderboard_row(shares=1),
    ])])
    entry = client(db).get("/leaderboard").json()[0]

    assert entry["bars"] == 10000, "balance repeated per row must not be summed"
    assert entry["holdings_value"] == pytest.approx(PRICE * 3), "shares DO accumulate"
    assert entry["net_worth"] == pytest.approx(10000 + PRICE * 3)


def test_leaderboard_ranks_by_net_worth(client):
    """
    Flask ranked on holdings value alone, which rewarded spending rather than
    performance: converting bars into shares at fair value left net worth unchanged
    but moved a player from last to first.
    """
    db = FakeDB(routes=[(LEADERBOARD, [
        # Rich in cash, owns nothing
        leaderboard_row(user_id=USER_ID, username="saver", bars=90000, shares=None),
        # Poor in cash, owns one share
        leaderboard_row(user_id=OTHER_USER_ID, username="spender", bars=10, shares=1),
    ])])
    entries = client(db).get("/leaderboard").json()

    assert [e["username"] for e in entries] == ["saver", "spender"]
    assert entries[0]["holdings_value"] == 0, "the leader here holds no shares at all"


def test_leaderboard_includes_a_user_holding_nothing(client):
    # LEFT JOIN, so a signed-up account with no trades still appears rather than
    # being invisible until it buys something.
    db = FakeDB(routes=[(LEADERBOARD, [leaderboard_row(shares=None)])])
    entries = client(db).get("/leaderboard").json()

    assert len(entries) == 1
    assert entries[0]["holdings_value"] == 0
    assert entries[0]["net_worth"] == 10000


def test_leaderboard_flags_only_the_caller(client):
    db = FakeDB(routes=[(LEADERBOARD, [
        leaderboard_row(user_id=USER_ID, username="me", shares=1),
        leaderboard_row(user_id=OTHER_USER_ID, username="them", bars=99999, shares=1),
    ])])
    entries = client(db).get("/leaderboard").json()

    flagged = [e["username"] for e in entries if e["is_you"]]
    assert flagged == ["me"]


def test_leaderboard_flags_nobody_when_signed_out(client):
    db = FakeDB(routes=[(LEADERBOARD, [leaderboard_row(shares=1)])])
    entries = client(db, authenticated=False).get("/leaderboard").json()

    assert entries, "the board is public"
    assert not any(e["is_you"] for e in entries)
