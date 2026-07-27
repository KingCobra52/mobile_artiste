"""
Score a candidate pricing configuration against the real history.

Why this exists: every constant in api/pricing.py so far was chosen by writing a
one-off script, eyeballing a table, and picking a row. That went wrong exactly
once and it was expensive. The MOMENTUM=30 table quoted a median daily move of
0.925%; the shipped number is 0.302%, because the throwaway script stepped back 14
ROWS while the implementation steps back 14 CALENDAR DAYS, and with gaps in
collection those are not the same window. The decision was made on a number that
was wrong by 3x.

The fix isn't more care, it's not using a throwaway script. This reads prices the
same way the endpoints do - through compute_price_per_share, over rows shaped by
the same LATERAL joins - so a config scored here is the config that would ship.

    app_artiste/bin/python -m api.scripts.backtest
    app_artiste/bin/python -m api.scripts.backtest --momentum 50
    app_artiste/bin/python -m api.scripts.backtest --sensitivity 0.75 --momentum 20
    app_artiste/bin/python -m api.scripts.backtest --compare 0,20,30,50,95

What the metrics mean, and why these five:

  spread          dearest / cheapest today. Reads as "does this look like a
                  market" - too flat and every artist costs the same, too wide and
                  the floor collapses below a buyable price.
  median daily    the typical day's price move. This is what makes a chart worth
                  opening. Measured over the day-pairs the history endpoint
                  actually serves, not every pair in the table.
  p90 daily       the exciting days. A market with a good median and no tail feels
                  mechanical.
  rank churn      how many of the 24 positions differ from a level-only ranking.
                  Momentum should reorder the board without deciding it - past
                  about half, size stops mattering and it stops reading as a
                  ranking of artists.
  cheapest        the floor in bars. Below about 1, a 10,000-bar balance buys tens
                  of thousands of shares and integer share counts stop meaning
                  anything.

Not a fitting tool. It scores a config you propose; it does not search for one.
With 24 artists and 46 days there is nowhere near enough data to fit anything, and
a search would find whatever overfits this particular month.
"""
import argparse
import math
import os
from collections import defaultdict

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

from api import pricing
from api.pricing import MOMENTUM_WEIGHTS, SIGNAL_WEIGHTS

load_dotenv()

# Every artist's full history with the momentum lookback resolved per date, which
# is the shape api/routers/artists.py builds for the chart. Anchored on s.date and
# reaching back MOMENTUM_WINDOW_DAYS in CALENDAR days - the distinction that made
# the original hand-rolled model wrong.
HISTORY_QUERY = """
    SELECT
        ar.name,
        s.date,
        s.listeners, s.playcount,
        y.subscribers, y.recent_videos_avg_views, y.recent_videos_like_ratio,
        p.listeners AS past_listeners, p.playcount AS past_playcount,
        s.date - p.date AS past_days
    FROM artists ar
    JOIN artist_snapshots s ON s.artist_id = ar.id
    LEFT JOIN LATERAL (
        SELECT subscribers, recent_videos_avg_views, recent_videos_like_ratio
        FROM youtube_snapshots y
        WHERE y.artist_id = ar.id AND y.date <= s.date
        ORDER BY y.date DESC LIMIT 1
    ) y ON true
    LEFT JOIN LATERAL (
        SELECT listeners, playcount, date FROM artist_snapshots
        WHERE artist_id = ar.id AND date <= s.date - %s
        ORDER BY date DESC LIMIT 1
    ) p ON true
    ORDER BY ar.name, s.date
"""


def coverage(row):
    """The same comparability rule the history endpoint applies."""
    return tuple(row[name] is not None for name in SIGNAL_WEIGHTS) + (
        row["past_days"] is not None,
    )


def comparable_tail(rows):
    """Walk back from today while coverage holds - api/routers/artists.py:141."""
    current = coverage(rows[-1])
    tail = []
    for row in reversed(rows):
        if coverage(row) != current:
            break
        tail.append(row)
    tail.reverse()
    return tail


def score(series, sensitivity, momentum, window):
    """
    Price every artist's history under one config and reduce it to five numbers.

    Prices come from pricing.compute_price_per_share with the module constants
    temporarily swapped, rather than from a formula reimplemented here. A second
    copy of the formula in the tool meant to validate the first is how you end up
    confidently measuring something you aren't shipping.
    """
    original = (pricing.SENSITIVITY, pricing.MOMENTUM, pricing.MOMENTUM_WINDOW_DAYS)
    pricing.SENSITIVITY, pricing.MOMENTUM, pricing.MOMENTUM_WINDOW_DAYS = (
        sensitivity, momentum, window,
    )
    try:
        daily = []
        latest = {}
        level_only = {}
        for name, rows in series.items():
            prices = [pricing.compute_price_per_share(r) for r in rows]
            daily += [abs(b / a - 1) for a, b in zip(prices, prices[1:]) if a > 0]
            latest[name] = prices[-1]
            # The same artist priced with no growth term, so rank churn measures
            # what momentum did rather than what the level already said.
            pricing.MOMENTUM = 0
            level_only[name] = pricing.compute_price_per_share(rows[-1])
            pricing.MOMENTUM = momentum
    finally:
        pricing.SENSITIVITY, pricing.MOMENTUM, pricing.MOMENTUM_WINDOW_DAYS = original

    daily.sort()
    by_price = [n for n, _ in sorted(latest.items(), key=lambda kv: -kv[1])]
    by_level = [n for n, _ in sorted(level_only.items(), key=lambda kv: -kv[1])]

    lo, hi = min(latest.values()), max(latest.values())
    return {
        "spread": hi / lo if lo > 0 else float("inf"),
        "median_daily": daily[len(daily) // 2] if daily else 0.0,
        "p90_daily": daily[int(0.9 * (len(daily) - 1))] if daily else 0.0,
        "churn": sum(1 for i, n in enumerate(by_price) if by_level[i] != n),
        "cheapest": lo,
        "dearest": hi,
        "artists": len(latest),
        "day_pairs": len(daily),
    }


def load(window):
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise SystemExit("DATABASE_URL is not set")
    with psycopg.connect(db_url, row_factory=dict_row) as conn:
        rows = conn.execute(HISTORY_QUERY, (window,)).fetchall()

    by_artist = defaultdict(list)
    for row in rows:
        by_artist[row["name"]].append(row)

    series = {}
    for name, artist_rows in by_artist.items():
        tail = comparable_tail(artist_rows)
        # One point can't produce a daily move, but it still carries a price and
        # belongs in the spread and the ranking.
        if tail:
            series[name] = tail
    return series


HEADER = (f"{'SENS':>6}{'MOM':>6}{'W':>4}{'spread':>10}{'cheapest':>10}{'dearest':>10}"
          f"{'med daily':>11}{'p90 daily':>11}{'churn':>8}")


def row_for(sensitivity, momentum, window, s, marker=""):
    return (f"{sensitivity:>6}{momentum:>6}{window:>4}{s['spread']:>9.1f}x"
            f"{s['cheapest']:>10.2f}{s['dearest']:>10.2f}"
            f"{100 * s['median_daily']:>10.3f}%{100 * s['p90_daily']:>10.3f}%"
            f"{s['churn']:>5}/{s['artists']}{marker}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sensitivity", type=float, default=pricing.SENSITIVITY)
    parser.add_argument("--momentum", type=float, default=pricing.MOMENTUM)
    parser.add_argument("--window", type=int, default=pricing.MOMENTUM_WINDOW_DAYS)
    parser.add_argument("--compare", type=str,
                        help="comma-separated MOMENTUM values to score side by side")
    args = parser.parse_args()

    series = load(args.window)
    if not series:
        raise SystemExit("no comparable history - has the pipeline run?")

    shipped = score(series, pricing.SENSITIVITY, pricing.MOMENTUM,
                    pricing.MOMENTUM_WINDOW_DAYS)
    print(f"{shipped['artists']} artists, {shipped['day_pairs']} comparable day-pairs, "
          f"{args.window}-day momentum window\n")
    print(HEADER)
    print("-" * len(HEADER))

    if args.compare:
        for value in [float(v) for v in args.compare.split(",")]:
            s = score(series, args.sensitivity, value, args.window)
            marker = "   <- shipped" if (
                args.sensitivity == pricing.SENSITIVITY
                and value == pricing.MOMENTUM
                and args.window == pricing.MOMENTUM_WINDOW_DAYS
            ) else ""
            print(row_for(args.sensitivity, value, args.window, s, marker))
    else:
        print(row_for(pricing.SENSITIVITY, pricing.MOMENTUM,
                      pricing.MOMENTUM_WINDOW_DAYS, shipped, "   <- shipped"))
        candidate = (args.sensitivity, args.momentum, args.window)
        if candidate != (pricing.SENSITIVITY, pricing.MOMENTUM,
                         pricing.MOMENTUM_WINDOW_DAYS):
            print(row_for(*candidate, score(series, *candidate), "   <- candidate"))

    print()
    print("Scored on the history the chart actually serves, so these are the numbers")
    print("a player would see. Nothing here is fitted - 24 artists over 46 days is")
    print("far too little to fit, and a search would find whatever overfits this month.")


if __name__ == "__main__":
    main()
