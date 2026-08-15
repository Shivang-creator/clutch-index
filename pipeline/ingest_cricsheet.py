"""
ingest_cricsheet.py
--------------------
Parse Cricsheet IPL ball-by-ball JSON (pipeline/raw/ipl_json.zip) into
per-player, per-season aggregate career stats: runs, balls, dismissals,
boundaries, powerplay/death splits, batting position, and basic bowling /
fielding totals.

This produces the *conventional, situation-blind* numbers Clutch Index sets
out to compare against (out/player_stats.json). It is deliberately not the
place where pressure is computed — see pressure.py for the ball-level,
match-state-aware model.

Adapted from the ball-by-ball ingestion pipeline of an earlier personal
project ("IPL Auction Game"). Trimmed for this project: dropped the
vs-pace/vs-spin bowler-type splits, since those depended on a large curated
player-metadata file (players_meta.py) that is specific to that project and
irrelevant to a pressure/clutch model. Everything else here is derived
straight from Cricsheet's ball-by-ball data, no external metadata needed —
so this repo is fully self-contained.

Output: pipeline/out/player_stats.json
Phases (T20, 0-indexed overs): powerplay 0-5, middle 6-14, death 15-19.
"""
import json
import os
import sys
from collections import defaultdict

from common import OUT_DIR, RAW_ZIP, iter_matches, phase_of, season_of

OUT_FILE = os.path.join(OUT_DIR, "player_stats.json")

BOWLER_WICKETS = {"caught", "bowled", "lbw", "stumped", "caught and bowled", "hit wicket"}


def new_bat():
    return {"runs": 0, "balls": 0, "outs": 0, "fours": 0, "sixes": 0, "dots": 0,
            "pp_runs": 0, "pp_balls": 0,
            "death_runs": 0, "death_balls": 0, "death_outs": 0,
            "pos_sum": 0, "innings": 0}


def new_bowl():
    return {"balls": 0, "runs": 0, "wkts": 0, "dots": 0,
            "pp_balls": 0, "pp_runs": 0, "pp_wkts": 0,
            "death_balls": 0, "death_runs": 0, "death_wkts": 0}


def new_field():
    return {"catches": 0, "stumpings": 0, "runouts": 0}


def process_match(data, players):
    info = data.get("info", {})
    season = season_of(info)
    total_overs = info.get("overs", 20) or 20
    appeared = set()

    for inn in data.get("innings", []):
        order = {}
        next_pos = 1

        def see(name):
            nonlocal next_pos
            if name not in order:
                order[name] = next_pos
                next_pos += 1

        for over in inn.get("overs", []):
            over_idx = over.get("over", 0)
            ph = phase_of(over_idx, total_overs)
            for d in over.get("deliveries", []):
                batter = d.get("batter")
                bowler = d.get("bowler")
                non_striker = d.get("non_striker")
                see(batter); see(non_striker)
                appeared.add(batter); appeared.add(bowler)

                runs = d.get("runs", {})
                bat_runs = runs.get("batter", 0)
                extras = d.get("extras", {}) or {}
                wides = extras.get("wides", 0)
                noballs = extras.get("noballs", 0)
                is_wide = wides > 0
                legal_ball = not (is_wide or noballs > 0)

                b = players[batter]["bat"]
                faced = not is_wide
                if faced:
                    b["balls"] += 1
                    if ph == "pp":
                        b["pp_balls"] += 1
                    elif ph == "death":
                        b["death_balls"] += 1
                    if bat_runs == 0 and extras == {}:
                        b["dots"] += 1
                b["runs"] += bat_runs
                if ph == "pp":
                    b["pp_runs"] += bat_runs
                elif ph == "death":
                    b["death_runs"] += bat_runs
                if bat_runs == 4:
                    b["fours"] += 1
                elif bat_runs == 6:
                    b["sixes"] += 1

                bw = players[bowler]["bowl"]
                charged = bat_runs + wides + noballs
                if legal_ball:
                    bw["balls"] += 1
                    if ph == "pp":
                        bw["pp_balls"] += 1
                    elif ph == "death":
                        bw["death_balls"] += 1
                    if charged == 0:
                        bw["dots"] += 1
                bw["runs"] += charged
                if ph == "pp":
                    bw["pp_runs"] += charged
                elif ph == "death":
                    bw["death_runs"] += charged

                for w in d.get("wickets", []) or []:
                    kind = w.get("kind", "")
                    player_out = w.get("player_out")
                    if player_out:
                        pb = players[player_out]["bat"]
                        pb["outs"] += 1
                        if ph == "death":
                            pb["death_outs"] += 1
                    if kind in BOWLER_WICKETS:
                        bw["wkts"] += 1
                        if ph == "pp":
                            bw["pp_wkts"] += 1
                        elif ph == "death":
                            bw["death_wkts"] += 1
                    for f in w.get("fielders", []) or []:
                        fname = f.get("name")
                        if not fname:
                            continue
                        ff = players[fname]["field"]
                        if kind == "run out":
                            ff["runouts"] += 1
                        elif kind == "stumped":
                            ff["stumpings"] += 1
                        elif kind in ("caught", "caught and bowled"):
                            ff["catches"] += 1

        for name, pos in order.items():
            players[name]["bat"]["pos_sum"] += pos
            players[name]["bat"]["innings"] += 1

    return season, appeared


def main():
    if not os.path.exists(RAW_ZIP):
        print(f"ERROR: {RAW_ZIP} not found.", file=sys.stderr)
        sys.exit(1)
    os.makedirs(OUT_DIR, exist_ok=True)

    agg = defaultdict(lambda: defaultdict(lambda: {
        "bat": new_bat(), "bowl": new_bowl(), "field": new_field(), "matches": 0}))

    n_matches = 0
    for match_id, data in iter_matches():
        match_players = defaultdict(lambda: {
            "bat": new_bat(), "bowl": new_bowl(), "field": new_field()})
        season, appeared = process_match(data, match_players)
        for pname, tab in match_players.items():
            dst = agg[pname][season]
            for cat in ("bat", "bowl", "field"):
                for k, v in tab[cat].items():
                    dst[cat][k] += v
            if pname in appeared:
                dst["matches"] += 1
        n_matches += 1

    out = {pname: {"seasons": dict(seasons)} for pname, seasons in agg.items()}
    with open(OUT_FILE, "w") as f:
        json.dump(out, f)

    print(f"Parsed {n_matches} matches, {len(out)} players -> {OUT_FILE}")
    tot = sorted(((sum(s["bat"]["runs"] for s in d["seasons"].values()), p)
                  for p, d in out.items()), reverse=True)
    print("Top 5 run-scorers (sanity):", ", ".join(f"{p}({r})" for r, p in tot[:5]))


if __name__ == "__main__":
    main()
