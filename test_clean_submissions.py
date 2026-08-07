"""Tests for the CEPA submission cleaner.

These assert numerical behaviour on fixtures with known answers, not merely that the
code runs. Each test targets a specific way the pipeline could be silently wrong.

Run:  python test_clean_submissions.py
"""

import io
import sys

import pandas as pd

import clean_submissions as cs

HEADER = (
    "consent,composition/household_size,composition/single_parents,"
    "composition/people_over_65,health/people_with_hiv,livelihoods/income_source,"
    "livelihoods/strengths,livelihoods/challenges,livelihoods/opportunities\n"
)


def frame(rows: str) -> pd.DataFrame:
    df = cs.load(io.StringIO(HEADER + rows))
    df, _ = cs.drop_non_consenting(df)
    df = cs.coerce_numeric(df)
    return cs.expand_multiselect(df)


def check(name, actual, expected):
    if actual != expected:
        print(f"FAIL {name}: expected {expected!r}, got {actual!r}")
        return 1
    print(f"ok   {name}")
    return 0


def test_declined_hiv_is_not_zero():
    """A blank optional answer must not be counted as 'no one has HIV'.

    Two households, one reporting 1 case and one declining. Prevalence is 1/1 = 100%
    among those who answered, not 1/2 = 50%.
    """
    df = frame(
        "yes,4,0,0,1,piece_jobs,farming,food_insecurity,electricity\n"
        "yes,4,0,0,,piece_jobs,farming,food_insecurity,electricity\n"
    )
    s = cs.summarize(df)
    row = s[s["indicator"].str.contains("living with HIV")].iloc[0]
    f = check("declined HIV excluded from denominator", int(row["denominator"]), 1)
    f += check("declined HIV not counted as a zero", float(row["percent"]), 100.0)
    return f


def test_non_consenting_dropped_but_counted():
    raw = cs.load(io.StringIO(
        HEADER
        + "yes,4,0,0,0,piece_jobs,farming,food_insecurity,electricity\n"
        + "no,,,,,,,,\n"
    ))
    kept, declined = cs.drop_non_consenting(raw)
    f = check("non-consenting row dropped", len(kept), 1)
    f += check("non-consenting row still counted", declined, 1)
    return f


def test_multiselect_expands_to_indicators():
    """Space-delimited selections must become one column per choice, not a substring match."""
    df = frame("yes,4,0,0,0,piece_jobs,farming livestock,food_insecurity,electricity\n")
    f = check("selected choice -> 1", int(df["strengths__farming"].iloc[0]), 1)
    f += check("second selected choice -> 1", int(df["strengths__livestock"].iloc[0]), 1)
    f += check("unselected choice -> 0", int(df["strengths__shopkeeping"].iloc[0]), 0)
    # 'piece_jobs' appears in both income_source and strengths lists; must not bleed across
    f += check("no cross-column bleed", int(df["strengths__piece_jobs"].iloc[0]), 0)
    return f


def test_cross_field_constraint_is_caught():
    df = frame("yes,3,0,0,5,piece_jobs,farming,food_insecurity,electricity\n")
    problems = cs.validate(df)
    f = check("count exceeding household size flagged", len(problems), 1)
    f += check("violation names the field", "people_with_hiv" in problems[0], True)
    return f


def test_mutually_exclusive_none_is_caught():
    df = frame("yes,3,0,0,0,piece_jobs,farming,none food_insecurity,electricity\n")
    problems = [p for p in cs.validate(df) if "none" in p]
    return check("'none' plus a specific challenge flagged", len(problems), 1)


def test_clean_data_produces_no_problems():
    """Guard against a validator that flags everything and looks vigilant while being useless."""
    df = frame(
        "yes,4,1,0,0,piece_jobs,farming,food_insecurity,electricity\n"
        "yes,6,0,2,1,pension,livestock,water_shortage,water_supply\n"
    )
    return check("clean data yields no violations", cs.validate(df), [])


def test_at_least_one_semantics():
    """Indicators are household-level 'at least one', not sums of people."""
    df = frame(
        "yes,9,3,0,0,piece_jobs,farming,food_insecurity,electricity\n"
        "yes,4,0,0,0,piece_jobs,farming,food_insecurity,electricity\n"
    )
    s = cs.summarize(df)
    row = s[s["indicator"].str.contains("single parent")].iloc[0]
    return check("3 single parents in 1 household counts as 1 household", int(row["count"]), 1)


def main():
    tests = [
        test_declined_hiv_is_not_zero,
        test_non_consenting_dropped_but_counted,
        test_multiselect_expands_to_indicators,
        test_cross_field_constraint_is_caught,
        test_mutually_exclusive_none_is_caught,
        test_clean_data_produces_no_problems,
        test_at_least_one_semantics,
    ]
    failures = 0
    for t in tests:
        print(f"\n-- {t.__name__}")
        failures += t() or 0
    print(f"\n{'FAILED' if failures else 'PASSED'}: {failures} assertion failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
