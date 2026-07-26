"""
Trading tests, ported from artistev0/tests/test_app.py.

The Flask originals used patch.object(app_module, "get_db"); FastAPI's
dependency_overrides is the direct equivalent and also lets the tests skip real
tokens by overriding get_current_user.

The FakeDB below is simpler than the psycopg2 version because psycopg3's
conn.execute() returns the cursor directly - there's no DBWrapper to imitate.
"""
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from api.auth import AuthenticatedUser, get_current_user
from api.db import get_db
from api.main import app
from api.pricing import SIGNAL_WEIGHTS, compute_price_per_share

USER_ID = "11111111-1111-1111-1111-111111111111"

# An artist with real signals, so compute_price_per_share returns something > 0
PRICED_SIGNALS = {
    "listeners": 1_539_763.0,
    "playcount": 109_573_276.0,
    "subscribers": 3_310_000.0,
    "recent_videos_avg_views": 2_126_874.5,
    "recent_videos_like_ratio": 32_199.24,
}
PRICE = compute_price_per_share(PRICED_SIGNALS)


class FakeDB:
    """Routes the routers' queries to canned results by matching on SQL text."""

    def __init__(self, signals=PRICED_SIGNALS, holdings=None, charge_succeeds=True):
        self.signals = signals
        self.holdings = holdings if holdings is not None else []
        self.charge_succeeds = charge_succeeds
        self.executed: list[tuple[str, tuple | None]] = []
        self.committed = False
        self.rolled_back = False

    def execute(self, query, vars=None):
        self.executed.append((query, vars))
        cursor = MagicMock()

        if "SET bars = bars -" in query:
            cursor.fetchone.return_value = {"bars": 9000} if self.charge_succeeds else None
        elif "SET bars = bars +" in query:
            cursor.fetchone.return_value = {"bars": 11000}
        elif "COALESCE(SUM(shares), 0)" in query:
            cursor.fetchone.return_value = {"total": sum(h["shares"] for h in self.holdings)}
        elif "FROM holdings" in query:
            cursor.fetchall.return_value = self.holdings
        elif "FROM artists" in query:
            cursor.fetchone.return_value = self.signals
        return cursor

    def transaction(self):
        # Mimics psycopg3's conn.transaction(): commit on clean exit, roll back if
        # the block raises. The tests assert on which one happened.
        db = self

        class _Txn:
            def __enter__(self):
                return db

            def __exit__(self, exc_type, exc, tb):
                if exc_type is None:
                    db.committed = True
                else:
                    db.rolled_back = True
                return False

        return _Txn()

    def sql_matching(self, needle: str) -> list[tuple[str, tuple | None]]:
        return [(q, v) for q, v in self.executed if needle in q]


@pytest.fixture
def client():
    def _client(db: FakeDB, authenticated: bool = True):
        app.dependency_overrides[get_db] = lambda: db
        if authenticated:
            app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
                id=USER_ID, email="tester@example.com"
            )
        return TestClient(app)

    yield _client
    app.dependency_overrides.clear()


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
