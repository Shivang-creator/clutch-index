"""
clutch.py
---------
Turns the ball-level pressure scores from pressure.py into one row per
batter: their conventional (all run-chase balls) strike-rate/average versus
their high-pressure-only strike-rate/average, and the DELTA between the two
— the headline "underrated / overrated" number.

Method
------
1. Pull every faced ball of every IPL run-chase, each already tagged with a
   pressure score in [0, 1] by pressure.py.
2. Cut the WHOLE POOL of pressure scores into tertiles once (not per player
   — see README.md "How the tertiles work" for why a shared cutoff is the
   fairer definition of "high pressure"). Bottom third = low-pressure balls,
   top third = high-pressure balls.
3. For each batter, split their own balls into those same low/mid/high
   buckets and compute strike rate (runs/balls) and average (runs/dismissals)
   in each bucket, plus the "conventional" figure across ALL their chase
   balls (all three buckets combined).
4. delta = high-pressure figure minus conventional figure. Positive delta =
   this player is BETTER than their own conventional numbers suggest when
   the game is tightest ("underrated"); negative = they fall away
   ("overrated" relative to reputation).
5. Bayesian shrinkage (same technique as the source project's
   compute_ratings.py: blend toward a neutral prior by confidence = how much
   volume backs the number) pulls deltas built on very few high-pressure
   balls back toward 0 — the assumption "we have no evidence this player is
   different under pressure" — so a player with 20 high-pressure balls and
   one lucky six doesn't rank above someone with 300.

Output: pipeline/out/clutch.json
"""
import json
import os
from collections import defaultdict

from common import OUT_DIR
from pressure import chase_deliveries

OUT_FILE = os.path.join(OUT_DIR, "clutch.json")
PLAYER_STATS_FILE = os.path.join(OUT_DIR, "player_stats.json")

# ---- qualification thresholds (chosen by inspecting the real distribution:
# 671 batters face at least one chase ball; these cuts keep the leaderboard
# to batters with a genuine, repeated body of run-chase work) ----
MIN_CHASE_BALLS = 60     # total career balls faced in a run-chase
MIN_BUCKET_BALLS = 20    # need at least this many balls in BOTH the low and high bucket

# ---- shrinkage targets: volume needed for full confidence (no shrink) ----
TARGET_SR_BALLS = 60     # high-pressure balls faced, for the strike-rate delta
TARGET_AVG_OUTS = 8      # high-pressure dismissals, for the average delta
POOL_MEAN_DELTA = 0.0    # neutral prior: "no evidence this player differs under pressure"


def sr(runs, balls):
    return round(100.0 * runs / balls, 2) if balls > 0 else None


def avg(runs, outs):
    return round(runs / outs, 2) if outs > 0 else None


def shrink(value, volume, target, pool_mean=POOL_MEAN_DELTA):
    """Blend `value` toward `pool_mean` by confidence = min(1, volume/target).
    Ported directly from compute_ratings.py's shrink() in the source project,
    generalised to blend toward 0 instead of a fixed rating midpoint."""
    if value is None:
        return None
    conf = min(1.0, volume / target) if target > 0 else 1.0
    return round(conf * value + (1 - conf) * pool_mean, 2)


def compute_tertile_cutoffs(scores):
    """Given a flat list of pressure scores, return (low_max, high_min) so
    that the bottom third of ALL chase balls in the dataset are <= low_max
    and the top third are >= high_min."""
    s = sorted(scores)
    n = len(s)
    if n == 0:
        return 0.0, 1.0
    low_max = s[n // 3]
    high_min = s[(2 * n) // 3]
    return low_max, high_min


def bucket_of(pressure, low_max, high_min):
    if pressure >= high_min:
        return "hi"
    if pressure <= low_max:
        return "lo"
    return "mid"


def aggregate(records, low_max, high_min):
    """records: iterable of pressure.chase_deliveries() dicts.
    Returns (runs_balls, outs, match_ids) keyed by player name."""
    runs_balls = defaultdict(lambda: {"all": [0, 0], "hi": [0, 0], "lo": [0, 0], "mid": [0, 0]})
    outs = defaultdict(lambda: {"all": 0, "hi": 0, "lo": 0, "mid": 0})
    match_ids = defaultdict(set)

    for d in records:
        bucket = bucket_of(d["pressure"], low_max, high_min)

        if d["faced"]:
            name = d["batter"]
            rb = runs_balls[name]
            rb["all"][0] += d["bat_runs"]
            rb["all"][1] += 1
            rb[bucket][0] += d["bat_runs"]
            rb[bucket][1] += 1
            match_ids[name].add(d["match_id"])

        # Dismissals are credited to whoever was actually out, which is not
        # always the delivery's 'batter' (a non-striker can be run out) —
        # matches the convention already used in ingest_cricsheet.py, where
        # outs are counted independently of whether the ball was "faced".
        for victim in d["dismissed_players"]:
            o = outs[victim]
            o["all"] += 1
            o[bucket] += 1

    return runs_balls, outs, match_ids


def load_career_context():
    """Optional enrichment from ingest_cricsheet.py's output: career matches
    and runs across BOTH innings (not just chases), for context in the UI.
    Falls back to empty context if player_stats.json hasn't been built yet."""
    if not os.path.exists(PLAYER_STATS_FILE):
        return {}
    with open(PLAYER_STATS_FILE) as f:
        stats = json.load(f)
    ctx = {}
    for name, pdata in stats.items():
        seasons = pdata.get("seasons", {})
        matches = sum(s.get("matches", 0) for s in seasons.values())
        runs = sum(s.get("bat", {}).get("runs", 0) for s in seasons.values())
        ctx[name] = {"career_matches": matches, "career_runs": runs}
    return ctx


def build():
    records = list(chase_deliveries())
    faced_scores = [d["pressure"] for d in records if d["faced"]]
    low_max, high_min = compute_tertile_cutoffs(faced_scores)

    runs_balls, outs, match_ids = aggregate(records, low_max, high_min)
    career_ctx = load_career_context()

    players = []
    for name, rb in runs_balls.items():
        balls_all = rb["all"][1]
        if balls_all < MIN_CHASE_BALLS:
            continue
        balls_hi = rb["hi"][1]
        balls_lo = rb["lo"][1]
        if balls_hi < MIN_BUCKET_BALLS or balls_lo < MIN_BUCKET_BALLS:
            continue

        o = outs[name]
        conv_sr, conv_avg = sr(rb["all"][0], balls_all), avg(rb["all"][0], o["all"])
        hi_sr, hi_avg = sr(rb["hi"][0], balls_hi), avg(rb["hi"][0], o["hi"])
        lo_sr, lo_avg = sr(rb["lo"][0], balls_lo), avg(rb["lo"][0], o["lo"])

        delta_sr_raw = round(hi_sr - conv_sr, 2) if (hi_sr is not None and conv_sr is not None) else None
        delta_avg_raw = round(hi_avg - conv_avg, 2) if (hi_avg is not None and conv_avg is not None) else None

        delta_sr_shrunk = shrink(delta_sr_raw, balls_hi, TARGET_SR_BALLS)
        delta_avg_shrunk = shrink(delta_avg_raw, o["hi"], TARGET_AVG_OUTS)

        confidence = round(min(1.0, balls_hi / TARGET_SR_BALLS), 2)
        ctx = career_ctx.get(name, {})

        players.append({
            "name": name,
            "chase_balls": balls_all,
            "chase_innings": len(match_ids[name]),
            "career_matches": ctx.get("career_matches"),
            "career_runs": ctx.get("career_runs"),
            "conventional": {"sr": conv_sr, "avg": conv_avg, "balls": balls_all, "outs": o["all"]},
            "high_pressure": {"sr": hi_sr, "avg": hi_avg, "balls": balls_hi, "outs": o["hi"]},
            "low_pressure": {"sr": lo_sr, "avg": lo_avg, "balls": balls_lo, "outs": o["lo"]},
            "delta_sr_raw": delta_sr_raw,
            "delta_sr": delta_sr_shrunk,
            "delta_avg_raw": delta_avg_raw,
            "delta_avg": delta_avg_shrunk,
            "confidence": confidence,
        })

    players.sort(key=lambda p: (p["delta_sr"] is not None, p["delta_sr"]), reverse=True)

    out = {
        "methodology": {
            "scope": "IPL run-chases only (second innings batting to a target); batting only",
            "pressure_weights": {"required_run_rate_gap": 0.50, "wickets_ratio": 0.30, "lateness": 0.20,
                                  "death_over_multiplier": 1.15},
            "tertile_cutoffs": {"low_max": round(low_max, 4), "high_min": round(high_min, 4)},
            "qualification": {"min_chase_balls": MIN_CHASE_BALLS, "min_bucket_balls": MIN_BUCKET_BALLS},
            "shrinkage": {"target_sr_balls": TARGET_SR_BALLS, "target_avg_outs": TARGET_AVG_OUTS,
                          "pool_mean_delta": POOL_MEAN_DELTA},
        },
        "n_qualifying_players": len(players),
        "n_chase_deliveries_faced": len(faced_scores),
        "players": players,
    }

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OUT_FILE, "w") as f:
        json.dump(out, f, indent=1)

    print(f"Wrote {len(players)} qualifying batters -> {OUT_FILE}")
    print(f"Tertile cutoffs: low<={low_max:.3f}  high>={high_min:.3f}")
    top_under = sorted(players, key=lambda p: p["delta_sr"] or -999, reverse=True)[:5]
    top_over = sorted(players, key=lambda p: p["delta_sr"] or 999)[:5]
    print("\nMost underrated (SR delta, shrunk):")
    for p in top_under:
        print(f"  {p['name']:20s} conv_sr={p['conventional']['sr']:6.1f}  hi_sr={p['high_pressure']['sr']:6.1f}  "
              f"delta={p['delta_sr']:+6.2f}  (raw {p['delta_sr_raw']:+6.2f}, conf={p['confidence']:.2f}, hi_balls={p['high_pressure']['balls']})")
    print("\nMost overrated (SR delta, shrunk):")
    for p in top_over:
        print(f"  {p['name']:20s} conv_sr={p['conventional']['sr']:6.1f}  hi_sr={p['high_pressure']['sr']:6.1f}  "
              f"delta={p['delta_sr']:+6.2f}  (raw {p['delta_sr_raw']:+6.2f}, conf={p['confidence']:.2f}, hi_balls={p['high_pressure']['balls']})")


if __name__ == "__main__":
    build()
