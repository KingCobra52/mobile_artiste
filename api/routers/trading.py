"""
Buy and sell.

Ported from artistev0/app.py:249-339. The Flask transaction logic was already
correct under concurrency, so it is reproduced rather than rewritten - see the
comments on each of the three properties that matter.

The one deliberate change is transaction scoping. The Flask routes relied on a
single db.commit() at the end of the handler; here each endpoint wraps its work
in an explicit `with conn.transaction()`, so a rejection can never leave a
debited balance with no matching holding, regardless of how the error surfaces.
"""
from fastapi import APIRouter, Depends, HTTPException

from api.auth import AuthenticatedUser, get_current_user
from api.db import get_db
from api.models import TradeRequest, TradeResult
from api.pricing import compute_price_per_share

router = APIRouter(tags=["trading"])

# Only the signals, keyed by id - the price has to be recomputed server-side from
# current data rather than trusted from the client, or shares can be bought at a
# price the buyer chose.
ARTIST_SIGNALS_QUERY = """
    SELECT
        a.listeners, a.playcount,
        y.subscribers, y.recent_videos_avg_views, y.recent_videos_like_ratio
    FROM artists
    LEFT JOIN LATERAL (
        SELECT listeners, playcount FROM artist_snapshots
        WHERE artist_snapshots.artist_id = artists.id
        ORDER BY date DESC LIMIT 1
    ) a ON true
    LEFT JOIN LATERAL (
        SELECT subscribers, recent_videos_avg_views, recent_videos_like_ratio
        FROM youtube_snapshots
        WHERE youtube_snapshots.artist_id = artists.id
        ORDER BY date DESC LIMIT 1
    ) y ON true
    WHERE artists.id = %s
"""

SHARES_OWNED_QUERY = """
    SELECT COALESCE(SUM(shares), 0) AS total
    FROM holdings WHERE user_id = %s AND artist_id = %s
"""


def _price_for(db, artist_id: int) -> float:
    """Current price, or a 400 explaining why this artist can't be traded."""
    signals = db.execute(ARTIST_SIGNALS_QUERY, (artist_id,)).fetchone()
    if signals is None:
        raise HTTPException(status_code=404, detail="Unknown artist")

    price = compute_price_per_share(signals)
    if price <= 0:
        # No snapshot data means no price basis. Without this guard, total_cost is
        # 0 and shares are free - kept verbatim from app.py:264-266.
        raise HTTPException(status_code=400, detail="This artist can't be traded yet")
    return price


def _shares_owned(db, user_id: str, artist_id: int) -> int:
    return db.execute(SHARES_OWNED_QUERY, (user_id, artist_id)).fetchone()["total"]


@router.post("/buy", response_model=TradeResult)
def buy(
    trade: TradeRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db),
):
    price = _price_for(db, trade.artist_id)
    total_cost = round(price * trade.shares, 2)

    with db.transaction():
        # Check and deduct in ONE statement. Splitting this into a read followed by
        # a write reopens the overdraft race: two concurrent buys could each see a
        # sufficient balance and both succeed. The WHERE clause is the lock.
        charged = db.execute(
            "UPDATE profiles SET bars = bars - %s WHERE id = %s AND bars >= %s RETURNING bars",
            (total_cost, user.id, total_cost),
        ).fetchone()
        if charged is None:
            raise HTTPException(status_code=400, detail="Not a sufficient amount of bars")

        db.execute(
            "INSERT INTO holdings (user_id, artist_id, shares, price_per_share, bought_at) "
            "VALUES (%s, %s, %s, %s, CURRENT_DATE)",
            (user.id, trade.artist_id, trade.shares, price),
        )

        return TradeResult(
            bars=charged["bars"],
            shares_owned=_shares_owned(db, user.id, trade.artist_id),
            price_per_share=price,
            total=total_cost,
        )


@router.post("/sell", response_model=TradeResult)
def sell(
    trade: TradeRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db),
):
    price = _price_for(db, trade.artist_id)

    with db.transaction():
        # FOR UPDATE locks these rows for the transaction, so two concurrent sells
        # can't both pay out against the same holdings. ORDER BY id ASC is the FIFO
        # ordering and also a consistent lock order, which avoids deadlocks.
        holdings = db.execute(
            "SELECT id, shares FROM holdings WHERE user_id = %s AND artist_id = %s "
            "ORDER BY id ASC FOR UPDATE",
            (user.id, trade.artist_id),
        ).fetchall()

        total_owned = sum(row["shares"] for row in holdings)
        if trade.shares > total_owned:
            raise HTTPException(status_code=400, detail="Invalid number of shares to sell")

        payout = round(price * trade.shares, 2)
        credited = db.execute(
            "UPDATE profiles SET bars = bars + %s WHERE id = %s RETURNING bars",
            (payout, user.id),
        ).fetchone()
        if credited is None:
            raise HTTPException(status_code=404, detail="No profile for this account")

        # FIFO: consume oldest holdings first, collecting fully-sold rows for one
        # batched DELETE and at most one partially-sold row for an UPDATE.
        remaining = trade.shares
        ids_to_delete: list[int] = []
        partial: tuple[int, int] | None = None
        for row in holdings:
            if remaining <= 0:
                break
            if row["shares"] <= remaining:
                ids_to_delete.append(row["id"])
                remaining -= row["shares"]
            else:
                partial = (remaining, row["id"])
                remaining = 0

        if ids_to_delete:
            db.execute("DELETE FROM holdings WHERE id = ANY(%s)", (ids_to_delete,))
        if partial:
            db.execute("UPDATE holdings SET shares = shares - %s WHERE id = %s", partial)

        return TradeResult(
            bars=credited["bars"],
            shares_owned=_shares_owned(db, user.id, trade.artist_id),
            price_per_share=price,
            total=payout,
        )
