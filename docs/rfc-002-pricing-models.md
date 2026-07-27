# RFC 002 — Better pricing and momentum models

**Status:** draft, pending data. No decision is being asked for yet.

Document only. This proposes nothing be merged into `api/pricing.py` today, because
the honest position is that there is not enough data to choose between the options
below. What it does is write down what the data actually supports, which candidates
are worth testing, and what evidence would settle each — so the work happens against
measurements rather than intuition.

Both things this depends on are already in place. `lastfm_track_snapshots` has been
collecting since 2026-07-27, and `api/scripts/backtest.py` is how any candidate here
gets scored. What is missing is time.

---

## 1. The binding constraint is data, and two thirds of it doesn't move

24 artists, 46 days, 864 Last.fm snapshots. That is far too little to fit anything;
any parameter search over it would find whatever overfits this particular month.

Worse, auditing the stored columns for this RFC turned up that **most of what is
collected barely moves**. Median absolute daily change, per signal:

| signal | median daily | p90 | max | priced today |
| --- | --- | --- | --- | --- |
| `listeners` | 0.0343% | 0.116% | 0.76% | yes, w=0.4 |
| `playcount` | 0.0469% | 0.159% | 1.24% | yes, w=0.1 |
| `subscribers` | **0.0000%** | 0.111% | 0.70% | yes, w=0.25 |
| `recent_videos_avg_views` | 0.1059% | 0.404% | 53.68% | yes, w=0.2 |

One of those numbers is a finding, not noise. (`total_views` is excluded from this
RFC's candidates entirely — see the note in §6.)

### 1a. `subscribers` is rounded, and carries a quarter of the price weight

YouTube publishes subscriber counts to three significant figures: Kendrick went
20,200,000 → 20,300,000 with nothing in between. So `subscribers` cannot move less
than roughly 1%, which means on almost every day it moves 0% exactly, and
occasionally jumps.

It carries `w = 0.25` — the second-largest weight in the model. A quarter of the
price level rests on a signal with two digits of real resolution.

That is not necessarily wrong for the *level* term, where it's a fine proxy for
audience size. It is wrong for anything that differences it, which is why
`MOMENTUM_WEIGHTS` uses Last.fm signals only. Worth stating explicitly so nobody
later "improves" momentum by adding subscribers to it.

---

## 2. What the market cannot currently express

Every priced signal is cumulative or near-cumulative — `playcount` and
`subscribers` both only ever rise. The level term
therefore drifts upward forever and says less about an artist each year: a decade-old
catalogue outranks a current one indefinitely.

The momentum term added in v1.3 lets price fall, but only via *decelerating growth*.
Nothing in the model responds to an artist actually becoming less popular, because
nothing collected can fall.

This is the gap the candidates below are aimed at.

---

## 3. Candidates

Each is stated with the evidence that would settle it. None should ship without
being scored through the harness.

### 3a. Catalogue concentration — most promising

From `lastfm_track_snapshots`, collecting since 2026-07-27. The share of an artist's
listening sitting in their biggest track:

```
concentration = top_track_listeners / sum(top_10_track_listeners)
```

A ratio, so it is bounded, and it genuinely falls when a catalogue broadens. The
first day of collection already separates the roster:

| artist | concentration |
| --- | --- |
| Kai Ca\$h | 0.575 |
| JELEEL! | 0.402 |
| Zeddy Will | 0.290 |
| Kae | 0.245 |
| 21 Savage | 0.140 |
| Playboi Carti | 0.137 |
| Kendrick Lamar | 0.124 |

Kai Ca\$h has one song holding 57% of its top-ten listening; Kendrick's biggest holds
12%. Nothing currently priced can tell those two apart.

**Evidence needed:** roughly 60 days, so around **2026-09-25**. A single day shows the
spread exists; it says nothing about whether the number MOVES, which is the part that
matters. Then two questions, either of which can sink it: does concentration change
more than 0.0343%/day, the bar `listeners` sets? And is it correlated with what is
already priced, or genuinely new? A signal tracking `listeners` at 0.9 adds weight and
no information.

### 3b. Multi-window momentum

One 14-day window forces a single choice between responsiveness and stability. Two
terms — say 7-day and 28-day — would let a fast-and-slowing artist price differently
from a slow-and-accelerating one, which is the actual difference between a spike and
a trend.

**Evidence needed:** compare `--compare` runs at several windows through the harness.
The specific thing to check is whether the two windows are distinguishable at all on
this roster: over 46 days, 7-day and 28-day growth may be correlated highly enough
that the second term is decoration.

### 3c. Per-artist volatility scaling

Kae's price moves several times more than Kendrick's, because small artists have
noisier signals. That is arguably correct — small caps *are* volatile — or arguably
just measurement noise being priced.

**Evidence needed:** is per-artist daily variance explained by artist size, and is
the relationship tight enough to normalise against? If the small artists' extra
movement is noise, normalising helps; if it is real, normalising destroys the most
interesting part of the market.

### 3d. Mean reversion

Momentum alone is trend-following, so a spike prices in and stays. A reversion term
would pull price back toward the level as a growth burst ages.

**Evidence needed:** do growth bursts in this data actually revert? Requires enough
history to contain several. **This is the candidate furthest from having evidence
and should be considered last.**

---

## 4. How any of this gets decided

Through `api/scripts/backtest.py`, on five metrics: spread, median daily move, p90
daily move, rank churn against a level-only ranking, and the floor in bars. The
harness prices through `compute_price_per_share` over endpoint-shaped rows, so a
config scored there is the config that would ship — verified to 1e-12 against live
`/market`.

Two rules worth writing down, because both were learned the hard way:

**Score, do not eyeball.** The `MOMENTUM = 30` decision was made against a table
quoting 0.925% median daily movement; the shipped figure is 0.302%. The throwaway
model stepped back 14 *rows* where the implementation steps back 14 *calendar days*,
and with gaps in collection those differ. The harness exists so that cannot recur.

**Adding a signal reprices the market.** Any change here moves every open position.
There is one account holding zero shares today, so it is free — and it stops being
free the moment anyone trades. Same argument that applied to freezing the baseline
and to shipping momentum, and it will eventually expire.

---

## 5. Recommendation

**Wait, and collect.** Specifically:

1. **Done.** Track collection started 2026-07-27 and runs daily with the rest of the
   pipeline.
2. **Let it run.** The gap rate was 22% while collection was manual, and the history
   should be unbroken from 2026-07-27 on now that it is scheduled. That alone raises
   daily price movement without touching a constant: 31% of day-pairs currently
   resolve their momentum lookback to the same row purely because of gaps, and each
   closed gap removes one.
3. **Revisit around 2026-09-25**, roughly 60 days of track history, and score 3a
   through `api/scripts/backtest.py` before it goes anywhere near `SIGNAL_WEIGHTS`.

Worth separating from all of the above: `MOMENTUM` is already tunable today and does
not need new data. Its current value was chosen against a figure that turned out to be
wrong by 3x, so it is worth re-scoring through the harness on its own schedule rather
than waiting on concentration.

Nothing here argues for changing `api/pricing.py` now. The model is not obviously
wrong; the data is thin, and one of four priced signals moves less than the market
implies. Collecting is worth more than tuning until that changes.

---

## 6. Note: `total_views`, and a bug it exposed

Not a candidate. It is a lifetime cumulative counter, so it can only rise, and it
would tell the model roughly what `subscribers` already does — the correlation
between the two in log space is 0.68. It is recorded here only because
investigating it turned up a real defect, which is now fixed in the data.

**The bug.** Between 2026-07-02 and 2026-07-10, `total_views` was not the channel's
lifetime view count at all. It was being written as the **sum of the recent
videos' views** — `recent_videos_avg_views × video_count`. The ratio of the two
columns is *exactly* 50.0 on 87 of the 98 affected rows, and exactly 8.0 on the
remainder, those being artists with only 8 recent uploads.

It looked at first like the wrong-channel bug recurring, because the values swing
by orders of magnitude across the window. It was not. `subscribers` holds a single
distinct value across the entire period for every affected artist, which it could
not do if the pipeline had been reading a different channel. The channel was right
throughout; only this one column was wrong, so `subscribers` and the
`recent_videos_*` columns from that window are sound and remain usable.

126 rows across 14 artists have been nulled. Detection used two independent rules
that agreed exactly: rows below 50% of the artist's current value, and rows inside
the 07-02..07-10 window. Neither found anything the other missed.

**After 2026-07-12 the column is also frozen** — identical for 15 consecutive days,
0.0000% median daily change, because YouTube stops refreshing channel-level
`viewCount` for large channels. So even the clean data would price as a constant.

Two things worth carrying forward:

- A signal being *collected* is not evidence it is *correct*. This column was
  written for four weeks before anyone looked at it closely.
- Cross-column consistency is the cheap check that caught it. A wrong channel moves
  every column together; a wrong calculation moves one. That distinction is what
  separated a code bug from a repeat of the wrong-channel incident, and it took one
  query.
