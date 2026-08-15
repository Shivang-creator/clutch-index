# Clutch Index

**Every ball of every IPL run-chase, scored 0–1 for match pressure — then
batters re-ranked by how they perform specifically when the chase is on the
line, not by the situation-blind average and strike rate everyone already
quotes.**

Built for the AQX Sports Analytics Data Bowl 3.0.

---

## The problem

A batter who scores 30 off 30 balls chasing 180 with four wickets down in
the 18th over played a completely different innings from one who scores 30
off 30 at 60/0 in the 5th over. Every cricket player and fan knows this
instantly. The stat sheet doesn't — average and strike rate treat both
innings identically, because they're just runs divided by dismissals and
runs divided by balls, with no idea what the game situation was when those
runs were scored.

Clutch Index fixes that for one specific, well-defined slice of the game:
**batting in an IPL run-chase.** It scores every ball of every chase for how
much pressure the batter was actually under, splits each batter's own
career chase balls into low-pressure and high-pressure buckets using that
score, and reports the gap between a batter's normal numbers and their
numbers *specifically when it mattered most*. That gap — not the raw
average — is the headline output: it's a direct read on who the stat sheet
is over- or under-selling.

**This is a pure deterministic model. No LLM, no AI API of any kind, anywhere
in this codebase.** That's a deliberate choice, not a shortcut: an analytics
claim like "this player is underrated" needs to be auditable back to a
formula and a number, not to a model's internal weights. A judge (or a
player) can trace every score in `out/clutch.json` back through
`pressure.py` and `clutch.py` by hand. That kind of auditability is worth
more here than anything an LLM wrapper could add, and it's a pattern that's
paid off in this portfolio's past hackathon results specifically because
judges can verify it on the spot.

## How it works

```
pipeline/raw/ipl_json.zip          Cricsheet ball-by-ball IPL data (committed, offline)
        │
        ▼
pipeline/ingest_cricsheet.py       career/season aggregates  → out/player_stats.json
        │                          (the "conventional" numbers, for context)
        ▼
pipeline/pressure.py               scores every run-chase ball 0–1 for pressure
        │                          (in-memory; see formula below)
        ▼
pipeline/clutch.py                 splits each batter's chase balls into
        │                          low/high pressure tertiles, computes the
        │                          conventional vs. high-pressure delta,
        │                          applies Bayesian shrinkage
        ▼
out/clutch.json                    the full leaderboard
        │
        ▼
index.html                         sortable leaderboard, reads out/clutch.json directly
```

## The pressure formula

`pipeline/pressure.py` scores every ball of every run-chase (a second
innings batting to a target) from 0 (no pressure) to 1 (maximum pressure).
It only uses information a batter and a commentator could see in the
moment — nothing about how the match ends up.

**1. Required run rate minus current run rate — the gap, not the raw number
(50% of the score).** Every chasing batter feels this first. Needing 10 an
over sounds scary in the abstract, but it's nothing if you're already
scoring at 11; it's everything if you're stuck at 6. So the model scores
the *gap* between what's required and what's actually happening, not the
required rate on its own — that's the number that's actually chasing you
down, over after over.

**2. Wickets down relative to wickets in hand (30%).** A batter walking in
2 down with 8 wickets in the shed can play themselves in and take a risk or
two. A batter walking in 7 down with only 3 left has no margin at all —
literally every ball, one false shot can end the chase, not just the
innings. That's why the model uses `wickets_lost / wickets_in_hand` rather
than wickets lost on its own: losing your 3rd wicket with 7 in hand is a
shrug, losing your 8th with 2 in hand is the whole game, and that ratio
captures the difference much better than a flat wicket count does.

**3. How far into the innings we are (20%).** Pressure compounds late even
independent of the equation, because the number of balls left to recover
from one bad shot keeps shrinking. The same run-rate situation at 145/2 in
over 6 feels routine; at over 18 it doesn't, because there's no time left to
bat your way out of a mistake.

**4. A death-overs bonus (last 5 overs of the chase, ×1.15 multiplier).**
Fielders come inside the circle, bowling changes to different fields,
boundaries dry up, batters have to manufacture risk they wouldn't take
in the middle overs. This is applied as a multiplier on top of the three
factors above, not as a fourth additive term — it isn't really an
independent source of pressure, it's an amplifier on whatever pressure the
situation already has.

These four combine as a weighted sum (weights above), the death-overs
multiplier is applied, and the whole thing is clamped to `[0, 1]`. The exact
code is in `pipeline/pressure.py`; every constant (the weights, the
normalisation caps, the death-overs window) is named and commented there,
not buried in a config file.

**Sanity check on the real data:** the highest-scoring ball in the entire
dataset (score 1.000) was Sunrisers Hyderabad needing 52 off the last
2.2 overs with 8 wickets down chasing 208 — about as dead a chase as
exists. The lowest-scoring balls (score ~0.002) are all ball one of a
chase, 0 wickets down, no equation to speak of yet. Both match cricket
intuition exactly.

## The clutch delta and Bayesian shrinkage

`pipeline/clutch.py` takes those ball-level pressure scores and, once for
the whole dataset (not per player — see "how the tertiles work" below),
cuts them into thirds: the bottom third of all chase balls ever bowled are
"low pressure," the top third are "high pressure." For each qualifying
batter it then computes:

- **Conventional** strike rate/average — across *all* their career
  run-chase balls (all three buckets combined). This is deliberately the
  same kind of number ESPNcricinfo would show you, just scoped to chases.
- **High-pressure** strike rate/average — only their balls that landed in
  the top pressure tertile.
- **Δ (delta)** — high-pressure figure minus conventional figure. Positive
  means the player gets *better*, relative to their own normal numbers,
  exactly when the chase is tightest — genuinely underrated by the
  conventional stat. Negative means they fall away — the conventional
  number is flattering them.

**Why a shared tertile cutoff, not a per-player one:** if "high pressure"
meant "top third of *this player's own* balls," the definition of high
pressure would be different for every player, and a "high-pressure" ball
for someone who mostly bats in comfortable chases might be a genuinely
mid-tier situation for someone who's regularly sent in with the game on a
knife edge. A single, shared definition — computed once across all 137,517
chase balls faced in IPL history — means "high pressure" means the same
thing for every player in the table, which is the only way the comparison
across players is fair.

**Bayesian shrinkage** (the same technique as the source project's
`compute_ratings.py`, generalised to blend toward 0 instead of a rating
midpoint): a delta built on 20 high-pressure balls is much noisier than one
built on 400, so each delta is blended toward a neutral prior of 0 ("no
evidence this player is different under pressure") by a confidence factor
`min(1, high_pressure_balls / 60)`. A concrete example from the real
output: **TM Head's** raw delta is a dramatic −71.56 SR points, but it's
built on only 27 high-pressure balls (45% confidence) — the pipeline pulls
that back to a more defensible **−32.20** rather than letting a small,
possibly unlucky sample dominate the "most overrated" list. Players with 60+
high-pressure balls (94 of the 164 qualifying batters) get no shrink at all
— the model only distrusts thin samples, not everyone.

**Qualification:** a batter needs at least 60 career run-chase balls faced,
with at least 20 in *both* the low- and high-pressure bucket, to appear in
the table at all — 164 of the 671 batters who've faced at least one IPL
chase ball meet that bar. This isn't a comment on the other 507; it's an
honest statement that 671 batters don't all have enough run-chase data to
say anything reliable about their pressure performance.

## Real findings

Pulled straight from `out/clutch.json` after a full pipeline run — no
placeholders:

1. **AB de Villiers is the single most underrated batter in IPL run-chases
   by this model** — and it's not close. His conventional chase strike
   rate is 137.9; in the top pressure tertile it rises to **194.5** (Δ
   +56.60, full confidence off 451 high-pressure balls across 82 chase
   innings). His average follows the same shape: 32.8 conventionally,
   **43.9** under pressure (Δ +11.08). A reputation for being cricket's
   best death-overs finisher, confirmed by a model that has no idea who he
   is.

2. **KS Williamson tells the same story with a completely different
   style** — not a six-hitter, a batter who visibly raises his own bar when
   it counts: conventional SR 118.2 climbs to **166.0** under pressure (Δ
   +47.80, full confidence off 256 balls), average 34.7 to 38.6.

3. **Abhishek Sharma's big numbers turn out to be almost entirely a
   low-pressure phenomenon.** Conventional SR 168.1 collapses to **115.4**
   in the top pressure tertile (Δ −52.70), and the average drop is worse:
   28.5 down to **9.8** (Δ −18.69), both at full confidence off 136
   high-pressure balls. His low-pressure SR (193.8) is actually higher
   still — the aggression that built the reputation is real, but it's
   concentrated almost entirely in the situations that matter least.

4. **S Dhawan is the clearest "reputation vs. reality" case in the
   average column.** His conventional chase average of 36.5, built on a
   huge 2,242-ball, 94-innings sample, is a genuinely good career number.
   Under pressure it falls to **15.5** (Δ −21.00) — his strike rate barely
   moves (126.8 → 112.6), so this isn't a batter freezing up, it's a batter
   getting out cheaply more often once the equation tightens, which the
   average catches and the strike rate mostly doesn't.

5. **P Simran Singh posts the single largest strike-rate collapse in the
   qualifying pool:** conventional SR 157.3 down to **93.5** under
   pressure (Δ −63.74, full confidence off 62 balls) — a strike rate that
   drops below 100 in exactly the situations that decide games.

Full, sortable numbers for all 164 qualifying batters are in
`out/clutch.json` and in `index.html`.

## Honest limits

Publishing what this *doesn't* do is more useful than pretending it's
complete, so:

- **IPL only.** Cricsheet's IPL archive is the only data source. No
  international cricket, no other T20 leagues, no domestic cricket. A
  player's "true" clutch ability could look different across formats and
  oppositions this dataset never sees.
- **Batting only.** There's no bowling-under-pressure model here at all —
  a bowler defending 8 off the last over is under just as much pressure as
  the batter facing it, and that side of the ball is completely
  unaddressed.
- **No venue or pitch adjustment.** A required rate of 11 an over means
  something different on a Chepauk turner than at the Chinnaswamy. This
  model treats every ground identically.
- **Chase innings only — no defending-a-total pressure model.** Batting
  first has its own pressure (a top-order collapse while setting a total is
  absolutely a pressure situation), but there's no target/required-rate
  equation to hang a comparable score on, so it's out of scope entirely
  rather than approximated badly.
- **No opposition-quality adjustment.** A high-pressure ball against a
  weak death bowler and a high-pressure ball against Jasprit Bumrah score
  identically here. The model captures match-situation pressure, not
  opponent difficulty.
- **Small-sample players are shrunk, not excluded, below the qualification
  bar** — but even qualifying batters with exactly 20 high-pressure balls
  (the minimum) carry real uncertainty that a single confidence number
  can't fully convey. Treat the bottom of the confidence column as
  suggestive, not settled.
- **Tertile cutoffs are fixed for this dataset.** "High pressure" here
  means "top third of chase balls bowled in IPL history through this
  Cricsheet snapshot" — it is not a general, format-independent definition
  of high pressure, and would shift if more (or different) matches were
  added.

## How to run it

Fully offline, one command, no API key, no network access, no build step:

```bash
python3 pipeline/build.py
```

This parses `pipeline/raw/ipl_json.zip` (already committed — no download
needed), writes `out/player_stats.json` and `out/clutch.json`, and prints
the top underrated/overrated batters to the console. Then open
`index.html` directly in a browser — it reads `out/clutch.json` with a
relative path. (If it's opened as a bare `file://` path, Chrome in
particular blocks the local `fetch()` for security reasons; the page
detects this and shows a one-line fix — run `python3 -m http.server 8000`
in this folder and open `http://localhost:8000` instead, or use
Firefox/Safari which allow the direct file.)

Tests:

```bash
python3 -m pip install pytest   # only needed to run the tests, not the pipeline
python3 -m pytest tests/
```

**27 tests, all passing.** They cover the pressure formula directly
(required-rate-way-above-current scores high, a low target with wickets in
hand scores low, more wickets down never decreases pressure, the
death-overs multiplier actually multiplies, every component clamps to
`[0, 1]`, edge cases like zero balls remaining don't crash) and the clutch
computation (tertile cutoffs split the pool correctly, `shrink()` pulls a
low-volume delta much closer to zero than a high-volume one with the same
raw value, a synthetic batter built to do much better under pressure
produces a positive delta end-to-end, dismissals are credited to the right
player even when it's a non-striker run out on someone else's ball).

Runs with **zero API calls, zero cost, fully offline, deterministic** —
the same input always produces the exact same `out/clutch.json`, byte for
byte.

## No AI anywhere

This codebase makes zero calls to any LLM or AI API — no OpenAI, no
Anthropic, no Gemini, no API keys, no `import` of any AI SDK anywhere in
`pipeline/` or `index.html`. Every number in `out/clutch.json` is produced
by the arithmetic in `pressure.py` and `clutch.py`, which is why both files
are short enough to read end to end and check by hand.

## Repo layout

```
clutch-index/
├── pipeline/
│   ├── raw/ipl_json.zip       Cricsheet IPL ball-by-ball data (committed, offline)
│   ├── common.py              shared zip-reading / season-labelling helpers
│   ├── ingest_cricsheet.py    career/season aggregates -> out/player_stats.json
│   ├── pressure.py            the pressure formula + ball-by-ball chase scoring
│   ├── clutch.py              tertile split, delta computation, Bayesian shrinkage
│   └── build.py                one-shot pipeline entry point
├── out/
│   ├── player_stats.json      career aggregates (context data)
│   └── clutch.json            the full clutch leaderboard (what index.html reads)
├── tests/
│   ├── test_pressure.py
│   └── test_clutch.py
├── index.html                 single-file leaderboard UI, no build step, no framework
└── README.md
```

## Credit

The ball-by-ball ingestion approach (`pipeline/common.py`,
`pipeline/ingest_cricsheet.py`) and the Bayesian-shrinkage technique used in
`clutch.py`'s `shrink()` function are adapted from an earlier personal
project ("IPL Auction Game"). The raw Cricsheet data
(`pipeline/raw/ipl_json.zip`) was already downloaded locally for that
project and is reused here unchanged. Everything pressure- and
clutch-related — `pressure.py`, `clutch.py`'s tertile/delta logic,
`index.html`, and this README — is new for Clutch Index. This is a fresh
submission to AQX Data Bowl 3.0, not a resubmission of any previous
project or Data Bowl entry.
