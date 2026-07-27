"""
Trading tests, ported from artistev0/tests/test_app.py.

The Flask originals used patch.object(app_module, "get_db"); FastAPI's
dependency_overrides is the direct equivalent and also lets the tests skip real
tokens by overriding get_current_user.

FakeDB and the client fixture live in conftest.py, shared with the read-endpoint
suites. Nothing below changed when they moved - these are the regression tests for
a real infinite-money exploit, and their passing untouched is what proves the
harness was generalised rather than reshaped to fit.
"""
import pytest

from api.pricing import SIGNAL_WEIGHTS

# Plain import, not relative: api/tests has no __init__.py, so pytest prepends this
# directory to sys.path and conftest is importable as a top-level module.
from conftest import PRICE, PRICED_SIGNALS, USER_ID, FakeDB  # noqa: F401


# --- share-count validation ---------------------------------------------------
# Regression coverage for the infinite-money exploit: negative shares made
# total_cost negative, which credited the account instead of charging it.

@pytest.mark.parametrize("shares", [-1000, -1, 0])
def test_buy_rejects_non_positive_shares(client, shares):
    db = FakeDB()
    response = client(db).post("/buy", json={"artist_id": 1, "shares": shares})
    assert response.status_code == 422
    assert not db.sql_matching("bars"), "no balance statement may run for an invalid order"


@pytest.mark.parametrize("shares", [-2, 0])
def test_sell_rejects_non_positive_shares(client, shares):
    db = FakeDB(holdings=[{"id": 1, "shares": 3}])
    response = client(db).post("/sell", json={"artist_id": 1, "shares": shares})
    assert response.status_code == 422
    assert not db.sql_matching("bars")


def test_buy_rejects_non_numeric_shares(client):
    db = FakeDB()
    response = client(db).post("/buy", json={"artist_id": 1, "shares": "abc"})
    assert response.status_code == 422


# --- artist and price guards --------------------------------------------------

def test_buy_rejects_unknown_artist(client):
    db = FakeDB(signals=None)
    response = client(db).post("/buy", json={"artist_id": 999999, "shares": 1})
    assert response.status_code == 404
    assert not db.sql_matching("bars")


def test_buy_rejects_artist_with_no_price_basis(client):
    # All signals missing -> price 0.0 -> shares must not be given away free
    db = FakeDB(signals={name: None for name in SIGNAL_WEIGHTS})
    response = client(db).post("/buy", json={"artist_id": 1, "shares": 10})
    assert response.status_code == 400
    assert not db.sql_matching("bars")


# --- buy ----------------------------------------------------------------------

def test_buy_charges_the_rounded_cost_atomically(client):
    db = FakeDB()
    response = client(db).post("/buy", json={"artist_id": 1, "shares": 2})
    assert response.status_code == 200

    charge = db.sql_matching("SET bars = bars -")
    assert len(charge) == 1, "the balance must be touched exactly once"
    query, params = charge[0]
    # The guard lives in the statement, not in Python - this is what closes the
    # overdraft race between two concurrent buys.
    assert "bars >= %s" in query
    assert params[0] == round(PRICE * 2, 2)
    assert db.committed


def test_buy_rejects_insufficient_balance_and_rolls_back(client):
    db = FakeDB(charge_succeeds=False)
    response = client(db).post("/buy", json={"artist_id": 1, "shares": 10})
    assert response.status_code == 400
    assert not db.sql_matching("INSERT INTO holdings"), "no holding on a failed charge"
    assert db.rolled_back and not db.committed


def test_buy_never_trusts_a_client_supplied_price(client):
    db = FakeDB()
    client(db).post("/buy", json={"artist_id": 1, "shares": 1, "price_per_share": 0.01})
    _, params = db.sql_matching("SET bars = bars -")[0]
    assert params[0] == round(PRICE, 2), "price must be recomputed server-side"


def test_buy_uses_the_token_subject_not_a_body_field(client):
    db = FakeDB()
    client(db).post("/buy", json={"artist_id": 1, "shares": 1, "user_id": "attacker"})
    _, params = db.sql_matching("SET bars = bars -")[0]
    assert params[1] == USER_ID


# --- sell ---------------------------------------------------------------------

def test_sell_rejects_more_shares_than_owned(client):
    db = FakeDB(holdings=[{"id": 1, "shares": 3}])
    response = client(db).post("/sell", json={"artist_id": 1, "shares": 5})
    assert response.status_code == 400
    assert not db.sql_matching("SET bars = bars +"), "no payout on an oversell"
    assert db.rolled_back


def test_sell_locks_holdings_rows(client):
    db = FakeDB(holdings=[{"id": 1, "shares": 3}])
    client(db).post("/sell", json={"artist_id": 1, "shares": 2})
    lookup = db.sql_matching("FROM holdings WHERE user_id")[0][0]
    # Without FOR UPDATE two concurrent sells can both pay out against these rows
    assert "FOR UPDATE" in lookup
    assert "ORDER BY id ASC" in lookup


def test_sell_consumes_holdings_fifo(client):
    # Selling 7 of 10 should clear the two oldest lots entirely and take 2 from the third
    db = FakeDB(holdings=[{"id": 1, "shares": 3}, {"id": 2, "shares": 2}, {"id": 3, "shares": 5}])
    response = client(db).post("/sell", json={"artist_id": 1, "shares": 7})
    assert response.status_code == 200

    _, delete_params = db.sql_matching("DELETE FROM holdings")[0]
    assert delete_params[0] == [1, 2], "oldest lots first"

    _, update_params = db.sql_matching("SET shares = shares -")[0]
    assert update_params == (2, 3), "remainder comes off the next lot"


def test_sell_exact_holdings_leaves_no_partial_update(client):
    db = FakeDB(holdings=[{"id": 1, "shares": 3}, {"id": 2, "shares": 2}])
    response = client(db).post("/sell", json={"artist_id": 1, "shares": 5})
    assert response.status_code == 200
    assert db.sql_matching("DELETE FROM holdings")[0][1][0] == [1, 2]
    assert not db.sql_matching("SET shares = shares -")


def test_sell_credits_the_current_price_not_the_purchase_price(client):
    db = FakeDB(holdings=[{"id": 1, "shares": 5}])
    client(db).post("/sell", json={"artist_id": 1, "shares": 2})
    _, params = db.sql_matching("SET bars = bars +")[0]
    assert params[0] == round(PRICE * 2, 2)


# --- auth ---------------------------------------------------------------------

def test_trading_requires_authentication(client):
    db = FakeDB()
    unauthenticated = client(db, authenticated=False)
    assert unauthenticated.post("/buy", json={"artist_id": 1, "shares": 1}).status_code == 401
    assert unauthenticated.post("/sell", json={"artist_id": 1, "shares": 1}).status_code == 401
    assert not db.sql_matching("bars")
