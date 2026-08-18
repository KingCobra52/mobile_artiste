"""
Portfolio and leaderboard.

Ported from artistev0/app.py:343-440. Pricing stays in Python via
compute_price_per_share() rather than being reimplemented in SQL, so the formula
has exactly one definition - the reasoning at app.py:392-395 still holds.
"""
from fastapi import APIRouter, Depends

from api.auth import AuthenticatedUser, get_current_user, get_optional_user
from api.db import get_db
from api.models import LeaderboardEntry, PortfolioHolding, PortfolioResponse
from api.pricing import compute_price_per_share, momentum_lookback_sql

router = APIRouter(tags=["portfolio"])

# One row per holding lot, not per artist: each purchase keeps its own buy price
# and date, which is what makes per-lot gain/loss meaningful. Matches the Flask
# portfolio table.
PORTFOLIO_QUERY = f"""
    SELECT
        artists.id AS artist_id,
        artists.name,
        artists.tier,
        holdings.id AS holding_id,
        holdings.shares,
        holdings.price_per_share,
        holdings.bought_at,
        a.listeners, a.playcount,
        y.subscribers, y.recent_videos_avg_views, y.recent_videos_avg_likes,
        p.past_listeners, p.past_playcount, p.past_days
    FROM holdings
    JOIN artists ON artists.id = holdings.artist_id
    LEFT JOIN LATERAL (
        SELECT listeners, playcount, date FROM artist_snapshots
        WHERE artist_snapshots.artist_id = artists.id
        ORDER BY date DESC LIMIT 1
    ) a ON true
    LEFT JOIN LATERAL (
        SELECT subscribers, recent_videos_avg_views, recent_videos_avg_likes
        FROM youtube_snapshots
        WHERE youtube_snapshots.artist_id = artists.id
        ORDER BY date DESC LIMIT 1
    ) y ON true
    {momentum_lookback_sql("artists.id", "a.date")}
    WHERE holdings.user_id = %s
    ORDER BY artists.name, holdings.id
"""

# Holdings are summed per (user, artist) first, so the latest-snapshot lookups and
# the pricing loop run once per artist held rather than once per purchase.
# profiles.bars comes along because the ranking is net worth, not holdings alone -
# see the comment in leaderboard() below.
LEADERBOARD_QUERY = f"""
    SELECT
        profiles.id AS user_id,
        profiles.username,
        profiles.bars,
        h.shares,
        a.listeners, a.playcount,
        y.subscribers, y.recent_videos_avg_views, y.recent_videos_avg_likes,
        p.past_listeners, p.past_playcount, p.past_days
    FROM profiles
    LEFT JOIN (
        SELECT user_id, artist_id, SUM(shares) AS shares
        FROM holdings
        GROUP BY user_id, artist_id
    ) h ON h.user_id = profiles.id
    LEFT JOIN LATERAL (
        SELECT listeners, playcount, date FROM artist_snapshots
        WHERE artist_snapshots.artist_id = h.artist_id
        ORDER BY date DESC LIMIT 1
    ) a ON true
    LEFT JOIN LATERAL (
        SELECT subscribers, recent_videos_avg_views, recent_videos_avg_likes
        FROM youtube_snapshots
        WHERE youtube_snapshots.artist_id = h.artist_id
        ORDER BY date DESC LIMIT 1
    ) y ON true
    {momentum_lookback_sql("h.artist_id", "a.date")}
"""

BALANCE_QUERY = "SELECT bars FROM profiles WHERE id = %s"


@router.get("/portfolio", response_model=PortfolioResponse)
def portfolio(user: AuthenticatedUser = Depends(get_current_user), db=Depends(get_db)):
    rows = db.execute(PORTFOLIO_QUERY, (user.id,)).fetchall()
    balance = db.execute(BALANCE_QUERY, (user.id,)).fetchone()

    holdings = []
    for row in rows:
        current_price = compute_price_per_share(row)
        holdings.append(
            PortfolioHolding(
                **row,
                current_price=current_price,
                current_value=current_price * row["shares"],
                # Against the price actually paid for this lot, which is why the
                # rows aren't aggregated by artist
                gain_loss=(current_price - row["price_per_share"]) * row["shares"],
            )
        )

    bars = balance["bars"] if balance else 0
    return PortfolioResponse(
        bars=bars,
        holdings_value=sum(h.current_value for h in holdings),
        total_gain_loss=sum(h.gain_loss for h in holdings),
        holdings=holdings,
    )


@router.get("/leaderboard", response_model=list[LeaderboardEntry])
def leaderboard(
    user: AuthenticatedUser | None = Depends(get_optional_user),
    db=Depends(get_db),
):
    rows = db.execute(LEADERBOARD_QUERY).fetchall()

    usernames: dict[str, str | None] = {}
    bars: dict[str, float] = {}
    holdings_value: dict[str, float] = {}

    for row in rows:
        user_id = row["user_id"]
        usernames[user_id] = row["username"]
        # Same row repeated per artist held, so bars must be assigned rather than
        # accumulated - adding it per row would multiply the balance by the number
        # of artists held.
        bars[user_id] = float(row["bars"] or 0)
        running = holdings_value.setdefault(user_id, 0.0)
        if row["shares"]:
            holdings_value[user_id] = running + compute_price_per_share(row) * row["shares"]

    # Ranked by net worth rather than the Flask version's holdings-only total.
    # Holdings alone rewarded spending: converting bars into shares at fair value
    # left net worth unchanged but moved a player from 0 to the top of the board,
    # so on day one anyone who bought anything outranked anyone who hadn't.
    entries = [
        LeaderboardEntry(
            username=usernames[user_id],
            bars=bars[user_id],
            holdings_value=holdings_value[user_id],
            net_worth=bars[user_id] + holdings_value[user_id],
            is_you=user is not None and user.id == str(user_id),
        )
        for user_id in usernames
    ]
    entries.sort(key=lambda entry: entry.net_worth, reverse=True)
    return entries
