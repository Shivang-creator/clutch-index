"""
Sanity checks for the pressure formula in pipeline/pressure.py.

These aren't just smoke tests — each one encodes a specific claim a cricket
fan would make about a situation ("that's basically no pressure",
"that chase is nearly dead") and checks the model agrees with it.
"""
import pytest

from pressure import (
    current_run_rate,
    is_death_over,
    lateness_component,
    pressure_score,
    required_run_rate,
    rrr_gap_component,
    wicket_component,
)


def test_required_run_rate_way_above_current_scores_high_pressure():
    # 100 needed off 24 balls (4 overs left) = 25/over required against a
    # current rate of ~6.25/over, 7 wickets down, deep in the death overs of
    # a 20-over chase. A commentator would call this "basically gone" — the
    # model should agree.
    score = pressure_score(
        runs_needed=100, runs_scored=100, balls_remaining=24,
        legal_balls_bowled=96, total_balls=120,
        wickets_down=7, over_idx=18, chase_overs=20,
    )
    assert score > 0.85


def test_low_target_wickets_in_hand_scores_low_pressure():
    # Chasing a modest target, cruising near the required rate, only 1
    # wicket down, plenty of the innings left. This is a stroll, not a chase.
    score = pressure_score(
        runs_needed=20, runs_scored=100, balls_remaining=60,
        legal_balls_bowled=60, total_balls=120,
        wickets_down=1, over_idx=10, chase_overs=20,
    )
    assert score < 0.15


def test_score_is_always_bounded_0_to_1():
    extreme_cases = [
        dict(runs_needed=250, runs_scored=0, balls_remaining=6, legal_balls_bowled=114,
             total_balls=120, wickets_down=9, over_idx=19, chase_overs=20),
        dict(runs_needed=0, runs_scored=0, balls_remaining=120, legal_balls_bowled=0,
             total_balls=120, wickets_down=0, over_idx=0, chase_overs=20),
        dict(runs_needed=-5, runs_scored=200, balls_remaining=1, legal_balls_bowled=119,
             total_balls=120, wickets_down=0, over_idx=19, chase_overs=20),
        dict(runs_needed=10, runs_scored=10, balls_remaining=0, legal_balls_bowled=120,
             total_balls=120, wickets_down=9, over_idx=19, chase_overs=20),
    ]
    for case in extreme_cases:
        score = pressure_score(**case)
        assert 0.0 <= score <= 1.0, case


def test_more_wickets_down_never_decreases_pressure():
    # Hold the equation and the clock fixed; only wickets down changes.
    # Losing more wickets should never make a batter's situation feel safer.
    base = dict(runs_needed=60, runs_scored=100, balls_remaining=48,
                legal_balls_bowled=72, total_balls=120, over_idx=12, chase_overs=20)
    scores = [pressure_score(wickets_down=w, **base) for w in range(0, 9)]
    for earlier, later in zip(scores, scores[1:]):
        assert later >= earlier - 1e-9


def test_death_over_multiplier_increases_score_for_the_same_situation():
    situation = dict(runs_needed=40, runs_scored=140, balls_remaining=24,
                      legal_balls_bowled=96, total_balls=120, wickets_down=4)
    mid_innings = pressure_score(over_idx=10, chase_overs=20, **situation)
    death_overs = pressure_score(over_idx=17, chase_overs=20, **situation)
    assert death_overs > mid_innings


def test_is_death_over_boundary():
    # Last 5 overs of a 20-over chase = overs 15..19 (0-indexed).
    assert not is_death_over(14, 20)
    assert is_death_over(15, 20)
    assert is_death_over(19, 20)


def test_is_death_over_generalises_to_shortened_chases():
    # A DLS-reduced 14-over chase should still treat its own last 5 overs as death.
    assert is_death_over(9, 14)
    assert not is_death_over(8, 14)


def test_required_run_rate_zero_balls_remaining_does_not_crash():
    # Guards the (should-be-unreachable) edge where the innings has run out
    # of balls but we're still asked for a required rate.
    rate = required_run_rate(runs_needed=10, balls_remaining=0)
    assert rate > 0


def test_current_run_rate_zero_balls_bowled_is_zero_not_a_crash():
    assert current_run_rate(runs_scored=0, legal_balls_bowled=0) == 0.0


@pytest.mark.parametrize("gap,expected", [(-20, 0.0), (0, 0.0), (100, 1.0)])
def test_rrr_gap_component_clamps_to_0_1(gap, expected):
    # crr chosen so that rrr - crr == gap exactly
    crr = 10.0
    rrr = crr + gap
    assert rrr_gap_component(rrr, crr) == expected


def test_wicket_component_all_out_edge_case_returns_max():
    # wickets_in_hand <= 0 shouldn't divide by zero — treat as maximum pressure.
    assert wicket_component(wickets_down=10, wickets_in_hand=0) == 1.0


def test_lateness_component_increases_through_the_innings():
    early = lateness_component(legal_balls_bowled=6, total_balls=120)
    late = lateness_component(legal_balls_bowled=114, total_balls=120)
    assert late > early
