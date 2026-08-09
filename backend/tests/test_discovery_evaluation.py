"""The scorecard that decides whether a ranking change helped.

Deterministic and offline on purpose: it is the half that can run in the suite,
so a change that quietly starts throwing away real happenings fails here rather
than being noticed weeks later by someone reading a thin digest.
"""

import os

os.environ["DEBUG"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")

from backend.cli.evaluate_discovery_ranking import FLOORS, main
from backend.discovery.evaluation import load_cases, score_attribution, score_filtering
from backend.discovery.listing_filter import looks_like_a_directory


def test_the_labelled_cases_are_readable_and_two_sided():
    cases = load_cases()

    assert len(cases) >= 20
    # A set with only listings, or only happenings, cannot detect a filter that
    # rejects everything or nothing.
    assert any(case.is_listing for case in cases)
    assert any(not case.is_listing for case in cases)


def test_no_real_happening_is_thrown_away():
    score = score_filtering(load_cases(), looks_like_a_directory)

    # The asymmetry is deliberate. An admitted listing wastes a slot in a
    # digest; a rejected happening removes something the user wanted and leaves
    # no trace it ever existed, which is why this floor is 1.0 and the other
    # is not.
    assert score.happening_retention == 1.0, score.wrongly_rejected
    assert score.listing_recall >= FLOORS["listing_recall"], score.still_admitted


def test_attribution_counts_a_wrong_reason_apart_from_no_reason():
    cases = load_cases()
    named = {case.title: "Horses" for case in cases}

    score = score_attribution(cases, named)

    # Naming the wrong interest is a stated reason that is false; naming none
    # is only a missed opportunity. The scorecard keeps them separate so a
    # change cannot trade one for the other unnoticed.
    assert score.judged == sum(1 for case in cases if not case.is_listing)
    assert score.wrong
    assert score.accuracy < 1.0


def test_the_harness_runs_clean_and_reports_a_scorecard(capsys):
    assert main([]) == 0
    assert "listing_recall" in capsys.readouterr().out


def test_an_impossible_floor_fails_the_run(capsys):
    assert main(["--min-listing-recall", "1.0"]) == 1
    assert "FAILED" in capsys.readouterr().out
