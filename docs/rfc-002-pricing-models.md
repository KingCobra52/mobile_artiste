# RFC 002 — Better pricing and momentum models

**Status:** draft, pending data. No decision is being asked for yet.

Document only. This proposes nothing be merged into `api/pricing.py` today, because
the honest position is that there is not enough data to choose between the options
below. What it does is write down what the data actually supports, which candidates
are worth testing, and what evidence would settle each — so the work happens against
measurements rather than intuition.

Companion PRs: [collect Last.fm top tracks](https://github.com/KingCobra52/artiste/pull/4)
starts banking a signal we don't have, and the
[backtest harness](https://github.com/KingCobra52/mobile_artiste/pull/1) is how any
candidate here gets scored.

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
| `total_views` | **0.0000%** | 98.2% | 135,863% | no |
| `recent_videos_avg_views` | 0.1059% | 0.404% | 53.68% | yes, w=0.2 |

Two of those numbers are findings, not noise.

### 1a. `total_views` is unusable — do not price it

It was the obvious candidate: already collected since 2026-06-30, never priced, so
history is banked for free. It does not survive inspection.

Kendrick Lamar's series:

```
2026-06-30      12,445,064,981     <- correct channel
2026-07-02         344,025,662     <- a different channel
2026-07-04       3,037,058,630     <- a third channel
2026-07-11      12,569,854,151     <- correct again
2026-07-12 .. 2026-07-27   unchanged, all 15 days
```

Two separate problems.

**Before 07-11 it is contaminated**, and in a way the wrong-channel cleanup did not
address. That cleanup nulled the 10 artists known to be on wrong channels — and it
did so correctly and completely, `total_views` included (332 non-null rows for both
`subscribers` and `total_views`, zero rows with one set and the other not). But
Kendrick was never on that list; it had 22 days of comparable history and looked
healthy. The series above shows the resolution was **unstable day to day** for
artists nobody flagged. The bug was broader than "11 artists matched to squatters":
handle resolution returned different channels on different days.

**After 07-12 it is frozen.** Not slow — identical. YouTube's channel-level
`viewCount` stops refreshing for large channels, so median daily change across all
24 artists is 0.0000% and the p90 is 0.0000% too. Pricing it would add a constant.

**Recommendation: leave `total_views` out of `SIGNAL_WEIGHTS`, and treat the
pre-07-12 rows as suspect for any model.** Worth a follow-up to null the
contaminated span the way the corrected artists' rows were nulled.

### 1b. `subscribers` is rounded, and carries a quarter of the price weight

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

Every priced signal is cumulative or near-cumulative — `playcount`, `subscribers`,
and (were it working) `total_views`. Cumulative quantities only rise. The level term
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

From `lastfm_track_snapshots` (PR #4). The share of an artist's listening sitting in
their biggest track:

```
concentration = top_track_listeners / sum(top_10_track_listeners)
```

A ratio, so it is bounded, and it genuinely falls when a catalogue broadens.
Measured today it already separates the roster:

| artist | #1 | #2 | ratio |
| --- | --- | --- | --- |
| Kendrick Lamar | 2,322,854 | 2,177,651 | 1.07× |
| Kai Ca\$h | 31,200 | 9,151 | 3.41× |

**Evidence needed:** roughly 60 days of `lastfm_track_snapshots`, so PR #4 must merge
first. Then: does concentration move more than 0.0343%/day (the `listeners` bar)?
Is it correlated with what's already priced, or genuinely new information? A signal
that tracks `listeners` at 0.9 adds nothing but weight.

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

### 3e. Rejected: `total_views`

See §1a. Contaminated before 2026-07-12, frozen after.

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

1. Merge PR #4 so `lastfm_track_snapshots` starts filling. It changes no price.
2. Let the scheduled pipeline run. The gap rate was 22% while runs were manual; with
   collection automated the history should be clean from 2026-07-27 on, which also
   raises daily price movement on its own — 31% of day-pairs currently resolve their
   momentum lookback to the same row because of gaps.
3. Revisit around 60 days of track history, and score 3a first through the harness.
4. Separately and sooner: decide whether to null the contaminated `total_views` span.

Nothing here argues for changing `api/pricing.py` now. The model is not obviously
wrong; the data is thin, and two of five priced signals move less than the market
implies. Collecting is worth more than tuning until that changes.
