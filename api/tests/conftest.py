"""
Shared test harness: a fake database connection, a client fixture, and row factories.

FakeDB stands in for a psycopg3 connection by matching queries on their SQL text.
That is crude, but it beats the alternatives here: a real Postgres would make the
suite need a server and a fixture database, and mocking psycopg itself would test
the mock rather than the routers. Matching on SQL means the tests exercise the real
query text, so a query that gets rewritten stops matching and the test says so.
"""
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from api.auth import (
    AuthenticatedUser,
    get_current_user,
    get_optional_user,
)
from api.db import get_db
from api.main import app
from api.pricing import compute_price_per_share

USER_ID = "11111111-1111-1111-1111-111111111111"
OTHER_USER_ID = "22222222-2222-2222-2222-222222222222"

# An artist with real signals, so compute_price_per_share returns something > 0.
#
# recent_videos_avg_views is a whole number because the column is an integer and
# the pipeline writes int(total / count) - a fractional value here would model a
# row Postgres cannot hold, and ArtistDetail rightly refuses to serialise it.
# recent_videos_like_ratio is genuinely a ratio and stays a float.
PRICED_SIGNALS = {
    "listeners": 1_539_763.0,
    "playcount": 109_573_276.0,
    "subscribers": 3_310_000.0,
    "recent_videos_avg_views": 2_126_874,
    "recent_videos_like_ratio": 32_199.24,
}
PRICE = compute_price_per_share(PRICED_SIGNALS)


class FakeDB:
    """
    Routes the routers' queries to canned results by matching on SQL text.

    Two rules make this survive being shared by four test modules:

    1. Every result is a LIST of rows, and both cursor accessors are derived from
       it - fetchall() gets the list, fetchone() gets the first row or None. The
       older version set one or the other per branch, so a caller that reached for
       the wrong accessor got a bare MagicMock and failed somewhere unhelpful.
       Deriving both also makes an empty result correct for free, which is exactly
       what the 404 paths check.

    2. `routes` is an ordered list of (sql_substring, rows) consulted before the
       built-in trading behaviour, so a test declares which query it is answering.
       Without it, dispatch depends on where an if/elif chain happens to land -
       MARKET_QUERY contains the substring "FROM artists" and would otherwise be
       answered by the branch meant for the trading price lookup.
    """

    def __init__(
        self,
        signals=PRICED_SIGNALS,
        holdings=None,
        charge_succeeds=True,
        routes=None,
    ):
        self.signals = signals
        self.holdings = holdings if holdings is not None else []
        self.charge_succeeds = charge_succeeds
        self.routes = routes or []
        self.executed: list[tuple[str, tuple | None]] = []
        self.committed = False
        self.rolled_back = False

    @staticmethod
    def _cursor(rows):
        cursor = MagicMock()
        cursor.fetchall.return_value = rows
        cursor.fetchone.return_value = rows[0] if rows else None
        return cursor

    def execute(self, query, vars=None):
        self.executed.append((query, vars))

        for needle, rows in self.routes:
            if needle in query:
                return self._cursor(list(rows))

        if "SET bars = bars -" in query:
            return self._cursor([{"bars": 9000}] if self.charge_succeeds else [])
        if "SET bars = bars +" in query:
            return self._cursor([{"bars": 11000}])
        if "COALESCE(SUM(shares), 0)" in query:
            return self._cursor([{"total": sum(h["shares"] for h in self.holdings)}])
        if "FROM holdings" in query:
            return self._cursor(self.holdings)
        if "FROM artists" in query:
            return self._cursor([self.signals] if self.signals is not None else [])
        return self._cursor([])

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
    """
    A TestClient with the database and the current user overridden.

    dependency_overrides is FastAPI's equivalent of the Flask suite's
    patch.object(app_module, "get_db"), and overriding the auth dependencies as
    well is what lets these tests run without minting real tokens.

    get_optional_user is overridden alongside get_current_user so the endpoints
    that accept either can be exercised signed in and signed out - passing
    authenticated=False is how a test asks for the anonymous path.
    """
    def _client(db: FakeDB, authenticated: bool = True, user_id: str = USER_ID):
        app.dependency_overrides[get_db] = lambda: db
        if authenticated:
            user = AuthenticatedUser(id=user_id, email="tester@example.com")
            app.dependency_overrides[get_current_user] = lambda: user
            app.dependency_overrides[get_optional_user] = lambda: user
        else:
            app.dependency_overrides[get_optional_user] = lambda: None
        return TestClient(app)

    yield _client
    app.dependency_overrides.clear()


# --- row factories ------------------------------------------------------------
#
# The response models validate, so a row missing a column surfaces as an opaque 500
# rather than a useful assertion failure. These build a complete row and take
# overrides, so a test can null one field and be read as a statement about that
# field.


def artist_row(**overrides):
    """A row shaped like MARKET_QUERY / ARTIST_QUERY select, priced at PRICE."""
    row = {
        "id": 1,
        "name": "Kendrick Lamar",
        "tier": "Established",
        "date": "2026-07-27",
        **PRICED_SIGNALS,
        # No momentum by default: most assertions are about the level term, and a
        # test that wants growth says so by passing these.
        "past_listeners": None,
        "past_playcount": None,
        "past_days": None,
    }
    row.update(overrides)
    return row


def history_row(date, **overrides):
    """A row shaped like HISTORY_QUERY select."""
    row = {
        "date": date,
        **PRICED_SIGNALS,
        "past_listeners": PRICED_SIGNALS["listeners"] / 1.01,
        "past_playcount": PRICED_SIGNALS["playcount"] / 1.01,
        "past_days": 14,
    }
    row.update(overrides)
    return row


def portfolio_row(**overrides):
    """A row shaped like PORTFOLIO_QUERY select - one purchase lot."""
    row = {
        "artist_id": 1,
        "name": "Kendrick Lamar",
        "tier": "Established",
        "holding_id": 1,
        "shares": 2,
        # What this lot cost when bought, deliberately not the current price
        "price_per_share": 100.0,
        "bought_at": "2026-07-01",
        **PRICED_SIGNALS,
        "past_listeners": None,
        "past_playcount": None,
        "past_days": None,
    }
    row.update(overrides)
    return row


def leaderboard_row(**overrides):
    """
    A row shaped like LEADERBOARD_QUERY select.

    Note the shape that makes the leaderboard tricky: one row PER ARTIST HELD, each
    repeating the same user_id, username and bars.
    """
    row = {
        "user_id": USER_ID,
        "username": "tester",
        "bars": 10000,
        "shares": 1,
        **PRICED_SIGNALS,
        "past_listeners": None,
        "past_playcount": None,
        "past_days": None,
    }
    row.update(overrides)
    return row
