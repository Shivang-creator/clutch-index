"""
common.py
---------
Shared helpers for reading the Cricsheet ball-by-ball archive. Used by both
ingest_cricsheet.py (career/season aggregates) and pressure.py (ball-level
run-chase pressure scoring), so the zip-reading and season-labelling logic
only lives in one place.

Adapted from the ball-by-ball ingestion pipeline of an earlier personal
project ("IPL Auction Game"); see README.md "Credit" section.
"""
import json
import os
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
RAW_ZIP = os.path.join(HERE, "raw", "ipl_json.zip")
# out/ lives at the repo root (a sibling of index.html), NOT inside pipeline/,
# so index.html's relative fetch("out/clutch.json") resolves correctly.
OUT_DIR = os.path.join(REPO_ROOT, "out")

# Cricsheet records a batter leaving injured as a 'wicket' of kind "retired hurt"
# (or "retired not out"). Neither is a dismissal: the batter is not out, the
# team has not lost a wicket, and the batter may come back to bat.
NOT_OUT_KINDS = {"retired hurt", "retired not out"}


def season_of(info):
    """Cricsheet 'season' is sometimes "2020/21" (straddles a new year) —
    normalise to a single 4-digit year string, falling back to the match date."""
    s = info.get("season")
    if s is not None:
        s = str(s)
        if "/" in s:
            head, tail = s.split("/")
            return head if len(tail) != 2 else str(int(head))
        return s
    dates = info.get("dates") or []
    return dates[0][:4] if dates else "unknown"


def iter_matches(zip_path=RAW_ZIP):
    """Yield (match_id, parsed_json) for every valid match file in the archive."""
    if not os.path.exists(zip_path):
        raise FileNotFoundError(
            f"{zip_path} not found. This should be committed at "
            "pipeline/raw/ipl_json.zip — see README.md."
        )
    with zipfile.ZipFile(zip_path) as z:
        for name in z.namelist():
            if not name.endswith(".json"):
                continue
            try:
                data = json.loads(z.read(name))
            except Exception:
                continue
            if "innings" not in data:
                continue
            match_id = os.path.splitext(os.path.basename(name))[0]
            yield match_id, data


def phase_of(over_idx, total_overs=20):
    """T20 phase bucketing (0-indexed overs). Death overs = last 5 of the
    innings, which generalises to rain-shortened matches via total_overs."""
    if over_idx <= 5:
        return "pp"
    if over_idx >= total_overs - 5:
        return "death"
    return "mid"


def clamp(x, lo, hi):
    return max(lo, min(hi, x))
