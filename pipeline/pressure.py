"""
pressure.py
-----------
Scores every ball of every IPL run-chase (second innings, batting to a
target) from 0 (no pressure) to 1 (maximum pressure), using only the match
state a player and commentator could see in the moment: the equation left
to solve, wickets in hand, and how far into the innings we are.

WHY THESE FOUR FACTORS (plain-English reasoning; mirrored in README.md):

1. Required run rate MINUS current run rate ("the gap").
   Every chaser feels this first. If you need 12 an over and you're
   scoring 7, that gap is the actual pressure — not the required rate on
   its own. Chasing 200 at 10-an-over required is nothing at 30 balls into
   the innings when you're scoring at 11; it's everything if you're only
   scoring at 6. So we score the GAP, not the raw required rate.

2. Wickets down relative to wickets in hand.
   A batter walking in at 2 down with 8 wickets in the shed can play
   themselves in. A batter walking in at 7 down with 3 left has no
   margin — every ball, a false shot can end the chase, not just the
   innings. We use wickets_lost / wickets_in_hand rather than wickets_lost
   alone, because losing your 3rd wicket with 7 in hand is a shrug; losing
   your 8th wicket with 2 in hand is the whole game.

3. How far into the innings we are (balls remaining).
   Pressure compounds late even independent of the equation, because the
   number of balls left to recover from a mistake shrinks. An over on 145/2
   in the 6th feels routine; the same run-rate situation in the 18th does
   not, because there's no more time to out-bat a bad over.

4. A death-overs bonus (last 5 overs of the chase).
   Fielders come inside the circle, bowlers bowl to different fields,
   boundaries dry up, and batters have to manufacture risk they wouldn't
   take in the middle overs. We apply this as a multiplier on top of the
   three factors above, rather than a separate additive term, because it's
   not really an independent source of pressure — it's an amplifier on
   whatever pressure the game situation already has.

The four are combined as a weighted sum (RRR gap weighted highest, since
it's the single number every chasing batter is actually tracking), then the
death-overs multiplier is applied and the whole thing is clamped to [0, 1].

This module only touches run-chases (an innings with a Cricsheet "target"
field). Innings batting first (setting a total) have no pressure score here
— see README.md "Honest limits".
"""
from common import iter_matches, phase_of

# ---- weights (must sum to 1.0) ----
W_RRR = 0.50   # required-rate-minus-current-rate: the number batters chase
W_WKT = 0.30   # wickets down / wickets in hand: how much margin for error
W_LATE = 0.20  # how far through the innings: shrinking recovery time

# ---- normalisation caps (chosen from plausible T20 extremes, not tuned to
# the data — see tests for the sanity checks these caps have to satisfy) ----
RRR_GAP_CAP = 15.0     # runs/over: needing 15 more an over than you're scoring is about as dire as it gets
WKT_RATIO_CAP = 4.0    # wickets_lost / wickets_in_hand of 4.0 (e.g. 8 down, 2 in hand) maxes this component out

DEATH_OVER_COUNT = 5      # last 5 overs of the chase (whatever the chase's own over limit is)
DEATH_MULTIPLIER = 1.15   # 15% amplification once in the death overs


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def required_run_rate(runs_needed, balls_remaining):
    """Runs per (6-ball) over required to win. If the innings has technically
    run out of balls (shouldn't happen mid-loop, but guard anyway) we return
    a large number so the pressure model still saturates rather than crashing."""
    if balls_remaining <= 0:
        return max(runs_needed, 0) * 6.0 + 36.0
    return max(runs_needed, 0) * 6.0 / balls_remaining


def current_run_rate(runs_scored, legal_balls_bowled):
    if legal_balls_bowled <= 0:
        return 0.0
    return runs_scored * 6.0 / legal_balls_bowled


def rrr_gap_component(rrr, crr):
    gap = rrr - crr
    return clamp(gap / RRR_GAP_CAP, 0.0, 1.0)


def wicket_component(wickets_down, wickets_in_hand):
    if wickets_in_hand <= 0:
        return 1.0
    ratio = wickets_down / wickets_in_hand
    return clamp(ratio / WKT_RATIO_CAP, 0.0, 1.0)


def lateness_component(legal_balls_bowled, total_balls):
    if total_balls <= 0:
        return 0.0
    return clamp(legal_balls_bowled / total_balls, 0.0, 1.0)


def is_death_over(over_idx, chase_overs):
    return over_idx >= (chase_overs - DEATH_OVER_COUNT)


def pressure_score(runs_needed, runs_scored, balls_remaining, legal_balls_bowled,
                    total_balls, wickets_down, over_idx, chase_overs):
    """Core formula. All inputs describe the situation a batter faces BEFORE
    this ball is bowled. Returns a float in [0, 1]."""
    wickets_in_hand = 10 - wickets_down
    rrr = required_run_rate(runs_needed, balls_remaining)
    crr = current_run_rate(runs_scored, legal_balls_bowled)

    base = (W_RRR * rrr_gap_component(rrr, crr)
            + W_WKT * wicket_component(wickets_down, wickets_in_hand)
            + W_LATE * lateness_component(legal_balls_bowled, total_balls))

    if is_death_over(over_idx, chase_overs):
        base *= DEATH_MULTIPLIER

    return clamp(base, 0.0, 1.0)


def chase_deliveries(zip_path=None):
    """Generator over every delivery bowled in every IPL run-chase.

    Yields one dict per delivery:
      match_id, over, batter, bowler, bat_runs, is_wide, is_out, faced,
      pressure, is_death_over, target_runs, chase_overs

    'faced' follows the standard scoring convention: a ball counts towards a
    batter's balls-faced (and therefore strike rate) unless it was a wide.
    No-balls DO count as faced, since the batter had a real delivery to play.
    Wickets are only ever charged to a legal delivery (a batter can't be out
    stumped/bowled/caught off a wide's extra run, but CAN be run out on a
    wide, which is handled below without incrementing 'faced').
    """
    kwargs = {} if zip_path is None else {"zip_path": zip_path}
    for match_id, data in iter_matches(**kwargs):
        info = data.get("info", {})
        innings = data.get("innings", [])
        for inn in innings:
            target = inn.get("target")
            if not target:
                continue  # first innings (no target yet) or a super over
            target_runs = target.get("runs")
            chase_overs = target.get("overs") or info.get("overs", 20) or 20
            if target_runs is None:
                continue
            total_balls = chase_overs * 6

            runs_scored = 0
            legal_balls_bowled = 0
            wickets_down = 0

            overs = sorted(inn.get("overs", []), key=lambda o: o.get("over", 0))
            for over in overs:
                over_idx = over.get("over", 0)
                for d in over.get("deliveries", []):
                    extras = d.get("extras", {}) or {}
                    wides = extras.get("wides", 0)
                    noballs = extras.get("noballs", 0)
                    is_wide = wides > 0
                    is_legal = not (is_wide or noballs > 0)
                    faced = not is_wide

                    runs = d.get("runs", {})
                    bat_runs = runs.get("batter", 0)
                    total_this_ball = runs.get("total", bat_runs + wides + noballs)

                    balls_remaining = max(total_balls - legal_balls_bowled, 0)
                    runs_needed = target_runs - runs_scored

                    score = pressure_score(
                        runs_needed=runs_needed,
                        runs_scored=runs_scored,
                        balls_remaining=balls_remaining,
                        legal_balls_bowled=legal_balls_bowled,
                        total_balls=total_balls,
                        wickets_down=wickets_down,
                        over_idx=over_idx,
                        chase_overs=chase_overs,
                    )

                    wickets_here = d.get("wickets", []) or []
                    batter = d.get("batter")
                    dismissed_players = [w.get("player_out") for w in wickets_here if w.get("player_out")]

                    yield {
                        "match_id": match_id,
                        "over": over_idx,
                        "batter": batter,
                        "bowler": d.get("bowler"),
                        "bat_runs": bat_runs,
                        "is_wide": is_wide,
                        "faced": faced,
                        # dismissed_players may include the non-striker (run
                        # out backing up) as well as/instead of 'batter' —
                        # clutch.py credits outs to whoever is actually named
                        # here, not blindly to the delivery's 'batter'.
                        "dismissed_players": dismissed_players,
                        "pressure": score,
                        "is_death_over": is_death_over(over_idx, chase_overs),
                        "target_runs": target_runs,
                        "chase_overs": chase_overs,
                        "runs_needed_before_ball": runs_needed,
                        "wickets_down_before_ball": wickets_down,
                    }

                    # advance match state AFTER scoring/yielding this ball
                    runs_scored += total_this_ball
                    if is_legal:
                        legal_balls_bowled += 1
                    wickets_down += len(wickets_here)


def main():
    """Standalone diagnostics: distribution of pressure scores across every
    chase ball in the dataset, and the tertile cutoffs clutch.py will use."""
    scores = [d["pressure"] for d in chase_deliveries() if d["faced"]]
    scores.sort()
    n = len(scores)
    if n == 0:
        print("No chase deliveries found.")
        return

    def pct(p):
        idx = min(n - 1, max(0, int(p * (n - 1))))
        return scores[idx]

    print(f"Chase deliveries (faced balls only): {n}")
    print(f"  min={scores[0]:.3f}  p10={pct(.10):.3f}  p33={pct(1/3):.3f}  "
          f"median={pct(.5):.3f}  p67={pct(2/3):.3f}  p90={pct(.9):.3f}  max={scores[-1]:.3f}")
    print(f"  tertile cutoffs -> low <= {pct(1/3):.3f}   high >= {pct(2/3):.3f}")


if __name__ == "__main__":
    main()
