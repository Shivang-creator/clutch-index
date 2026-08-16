# Clutch Index — Impact Forge submission

## Project name
```
Clutch Index
```

## Elevator pitch
```
Cricket's batting stats are situation-blind — 30 off 30 chasing 180 with four down isn't the same innings as 30 off 30 at 60/0, but average and strike rate treat them identically. Clutch Index scores 137,517 real IPL deliveries for match pressure and re-ranks 164 batters by who actually performs when it matters. 27 tests, zero AI, fully offline.
```

## Built With
```
python, cricsheet, bayesian-statistics, pytest, html, javascript
```

---

## About the project

### What I built this weekend

I've played cricket at national level, and there's a gap every player knows and no stat sheet shows: a batter scoring 30 off 30 chasing 180 with four wickets down played a completely different innings from one scoring 30 off 30 at 60/0 with five overs gone. Average and strike rate are just runs divided by dismissals and runs divided by balls — they carry no memory of the situation the runs came in.

Clutch Index puts a number on that gap. It scores every ball of every IPL run-chase for how much pressure the batter was under, splits each batter's own career chase balls into low- and high-pressure buckets, and reports the delta between their normal numbers and their numbers when the game was actually on the line. That delta — not the raw average — is the headline: a direct read on who the stat sheet is over- or under-selling.

### The pressure model, in plain terms

Every ball in a chase gets a 0–1 score from four things a batter actually feels:

- **Required run rate gap** (50% weight) — how far ahead the ask has got
- **Wickets in hand** (30%) — two down is a different game from six down
- **Lateness** (20%) — the same equation is heavier in over 17 than over 7
- **Death-over multiplier** (1.15×) — pressure compounds at the end

Chase balls are then split into tertiles per batter: top third high pressure, bottom third low, and the gap between them is the finding.

### What it actually found — real numbers, run offline in front of you

- **AB de Villiers is the most underrated batter in IPL chases.** SR **137.9 → 194.5** under pressure (**+56.60**), off 451 high-pressure balls — full confidence, not noise.
- **Kane Williamson**, thought of as an accumulator: SR **118.2 → 166.0** (**+47.80**).
- **Abhishek Sharma's numbers are largely a low-pressure phenomenon.** SR **168.1 → 115.4** (**−52.70**).

### Small samples don't get to shout

A batter with 27 high-pressure balls shouldn't outrank one with 451. Every delta is Bayesian-shrunk toward zero in proportion to sample size, and both the raw and shrunk numbers publish side by side with a confidence figure — Travis Head's raw −71.56 off 27 balls (45% confidence) is visibly pulled to a defensible **−32.20**, so you can watch the model correct itself rather than trusting it blind.

### No AI anywhere, on purpose

No LLM, no API call, no network access anywhere in this codebase. A claim like "this player is underrated" needs to trace back to a formula and a number, not a model's weights — every score in `out/clutch.json` is auditable by hand through `pressure.py` and `clutch.py`.

```bash
python3 pipeline/build.py    # one command, offline, ~3 seconds
```

### 27 tests

`pytest tests/` — covering the pressure formula (monotonicity, clamping, death-over boundaries, division-by-zero edges) and the clutch computation (tertile cutoffs, shrinkage pulling low-volume deltas toward zero, a synthetic batter with a built-in improvement producing a correctly-signed positive delta).

### Honest limits

- IPL only — no internationals, no other T20 leagues
- Batting only — no bowling-pressure model
- Chase innings only — batting first has real pressure this says nothing about
- No venue or pitch adjustment
- Pressure weights are my own judgement as a player, documented so you can disagree with them precisely rather than take them on faith

---

## Try it out
```
https://github.com/Shivang-creator/clutch-index
```
