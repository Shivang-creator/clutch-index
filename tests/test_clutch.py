"""
Tests for pipeline/clutch.py: the tertile split, the shrinkage, and the
delta computation itself. The most important one is
test_synthetic_batter_who_improves_under_pressure_shows_positive_delta —
it builds a fake batter with a known, deliberate skill difference between
low- and high-pressure balls and checks the pipeline recovers it.
"""
from clutch import (
    aggregate,
    avg,
    bucket_of,
    compute_tertile_cutoffs,
    shrink,
    sr,
)


def make_ball(batter, pressure, bat_runs=0, faced=True, out=False, match_id="m1"):
    return {
        "match_id": match_id,
        "batter": batter,
        "bat_runs": bat_runs,
        "faced": faced,
        "pressure": pressure,
        "dismissed_players": [batter] if out else [],
    }


# ---- sr() / avg() ----

def test_sr_basic():
    assert sr(50, 25) == 200.0


def test_sr_zero_balls_is_none():
    assert sr(0, 0) is None


def test_avg_basic():
    assert avg(90, 3) == 30.0


def test_avg_zero_outs_is_none_not_infinity():
    assert avg(150, 0) is None


# ---- compute_tertile_cutoffs / bucket_of ----

def test_compute_tertile_cutoffs_empty_list_does_not_crash():
    low, high = compute_tertile_cutoffs([])
    assert low == 0.0 and high == 1.0


def test_compute_tertile_cutoffs_splits_into_roughly_equal_thirds():
    scores = [i / 99 for i in range(100)]  # 0.00 .. 1.00
    low_max, high_min = compute_tertile_cutoffs(scores)
    below = sum(1 for s in scores if s <= low_max)
    above = sum(1 for s in scores if s >= high_min)
    assert 30 <= below <= 36
    assert 30 <= above <= 36


def test_bucket_of_boundaries():
    low_max, high_min = 0.2, 0.7
    assert bucket_of(0.2, low_max, high_min) == "lo"
    assert bucket_of(0.7, low_max, high_min) == "hi"
    assert bucket_of(0.5, low_max, high_min) == "mid"
    assert bucket_of(0.0, low_max, high_min) == "lo"
    assert bucket_of(1.0, low_max, high_min) == "hi"


# ---- shrink() ----

def test_shrink_full_confidence_returns_value_unchanged():
    assert shrink(10.0, volume=100, target=60) == 10.0


def test_shrink_pulls_low_volume_delta_much_closer_to_zero():
    low_volume = shrink(10.0, volume=6, target=60)   # conf = 0.10
    high_volume = shrink(10.0, volume=600, target=60)  # conf = 1.00 (capped)
    assert high_volume == 10.0
    assert abs(low_volume) < abs(high_volume)
    assert low_volume == 1.0  # 0.10 * 10.0 + 0.90 * 0.0


def test_shrink_none_passes_through():
    assert shrink(None, volume=100, target=60) is None


# ---- aggregate() + delta computation (the actual "clutch" claim) ----

def test_synthetic_batter_who_improves_under_pressure_shows_positive_delta():
    balls = []
    # 30 low-pressure balls: 40 runs off 30 (SR ~133), 3 dismissals -> avg ~13.3
    for i in range(30):
        balls.append(make_ball("Clutch Carl", pressure=0.05, bat_runs=(2 if i % 3 else 0),
                                out=(i in (5, 15, 25))))
    # 30 high-pressure balls: 60 runs off 30 (SR 200), 2 dismissals -> avg 30
    for i in range(30):
        balls.append(make_ball("Clutch Carl", pressure=0.90, bat_runs=(2 if i % 3 == 0 else 2),
                                out=(i in (10, 20))))

    scores = [b["pressure"] for b in balls]
    low_max, high_min = compute_tertile_cutoffs(scores)
    runs_balls, outs, match_ids = aggregate(balls, low_max, high_min)

    rb = runs_balls["Clutch Carl"]
    o = outs["Clutch Carl"]
    conv_sr = sr(rb["all"][0], rb["all"][1])
    hi_sr = sr(rb["hi"][0], rb["hi"][1])
    conv_avg = avg(rb["all"][0], o["all"])
    hi_avg = avg(rb["hi"][0], o["hi"])

    assert hi_sr > conv_sr, "a batter who scores faster under pressure should have hi_sr > conv_sr"
    delta_sr = hi_sr - conv_sr
    assert delta_sr > 0

    assert hi_avg > conv_avg, "fewer dismissals + more runs under pressure should lift the average too"


def test_aggregate_credits_non_striker_run_out_without_crediting_balls_faced():
    # A non-striker run out: the delivery's "batter" is someone else, but the
    # dismissed player should still get an out (and no ball faced) for it.
    balls = [
        make_ball("Striker", pressure=0.5, bat_runs=1, faced=True, out=False),
    ]
    balls[0]["dismissed_players"] = ["NonStriker"]  # run out at the non-striker's end

    runs_balls, outs, match_ids = aggregate(balls, low_max=0.3, high_min=0.7)

    assert "NonStriker" not in runs_balls  # never faced a ball
    assert outs["NonStriker"]["all"] == 1
    assert outs["Striker"]["all"] == 0
    assert runs_balls["Striker"]["all"] == [1, 1]


def test_aggregate_conventional_combines_all_three_buckets():
    balls = [
        make_ball("P", pressure=0.05, bat_runs=4),
        make_ball("P", pressure=0.50, bat_runs=1),
        make_ball("P", pressure=0.95, bat_runs=6),
    ]
    runs_balls, outs, match_ids = aggregate(balls, low_max=0.3, high_min=0.7)
    rb = runs_balls["P"]
    assert rb["all"] == [11, 3]
    assert rb["lo"] == [4, 1]
    assert rb["mid"] == [1, 1]
    assert rb["hi"] == [6, 1]
