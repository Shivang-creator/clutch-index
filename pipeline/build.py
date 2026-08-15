"""
build.py — one-shot pipeline entry point.

Steps:
  1. parse ball-by-ball IPL data      -> out/player_stats.json   (ingest_cricsheet.py)
  2. score every run-chase ball 0..1  -> (in-memory, pressure.py, used by clutch.py)
  3. compute per-batter clutch deltas -> out/clutch.json          (clutch.py)

Fully offline: reads pipeline/raw/ipl_json.zip (already committed to this
repo), makes zero network calls and zero API calls of any kind.

Usage:  python3 pipeline/build.py
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RAW_ZIP = os.path.join(HERE, "raw", "ipl_json.zip")


def run(script):
    print(f"\n=== {script} ===")
    r = subprocess.run([sys.executable, os.path.join(HERE, script)])
    if r.returncode != 0:
        sys.exit(r.returncode)


def main():
    if not os.path.exists(RAW_ZIP):
        print(f"ERROR: {RAW_ZIP} not found. This repo should ship it committed "
              f"at pipeline/raw/ipl_json.zip so the whole pipeline runs offline.",
              file=sys.stderr)
        sys.exit(1)

    run("ingest_cricsheet.py")
    run("clutch.py")
    print("\nDone. Open index.html in a browser (it reads out/clutch.json).")


if __name__ == "__main__":
    main()
