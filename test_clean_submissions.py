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


# KoboToolbox exports the same survey in a different shape from ODK Central: every
# select_multiple arrives both as the space-delimited source column AND pre-expanded into
# one column per choice. The leaf names of those pre-expanded columns collide across
# questions - livestock, piece_jobs, petty_trade, domestic_work and other each appear under
# more than one question - which is what these three tests pin down. The collision was found
# by running a real Kobo export through the pipeline; the fixtures above are ODK Central's
# shape and could never have surfaced it.
KOBO_HEADER = (
    "consent,household_size,single_parents,people_over_65,people_with_hiv,"
    "income_source,income_source/piece_jobs,income_source/livestock,"
    "strengths,strengths/farming,strengths/livestock,strengths/piece_jobs,"
    "challenges,challenges/food_insecurity,"
    "opportunities,opportunities/electricity,"
    "_id,_uuid,meta/rootUuid\n"
)

# strengths says "farming" only, but the pre-expanded strengths/livestock column claims 1.
# They disagree deliberately, so the tests can prove which one the pipeline believes.
KOBO_ROW = (
    "yes,4,1,1,,"
    "piece_jobs,1,0,"
    "farming,1,1,0,"
    "food_insecurity,1,"
    "electricity,1,"
    "17,abc-123,abc-123\n"
)


def test_kobo_pre_expanded_columns_are_dropped():
    """A Kobo export must load without two columns sharing a name.

    Seven pre-expanded columns are present. All seven are dropped, and nothing that
    survives is duplicated.
    """
    df = cs.load(io.StringIO(KOBO_HEADER + KOBO_ROW))
    names = list(df.columns)
    dupes = sorted({c for c in names if names.count(c) > 1})
    f = check("no duplicate columns survive a Kobo export", dupes, [])
    f += check("pre-expanded columns dropped", df.attrs["pre_expanded_dropped"], 7)
    f += check("source column kept", "strengths" in names, True)
    return f


def test_source_column_wins_over_pre_expanded():
    """The space-delimited answer is authoritative, not the platform's expansion.

    The fixture's strengths/livestock column says 1 while the strengths answer itself
    lists only farming. The indicator must follow the answer, so livestock is 0.
    """
    df = cs.load(io.StringIO(KOBO_HEADER + KOBO_ROW))
    df, _ = cs.drop_non_consenting(df)
    df = cs.coerce_numeric(df)
    df = cs.expand_multiselect(df)
    s = cs.summarize(df)

    livestock = s[s["indicator"].str.contains("livestock as a strength")].iloc[0]
    farming = s[s["indicator"].str.contains("farming as a strength")].iloc[0]
    f = check("contradictory pre-expanded value ignored", int(livestock["count"]), 0)
    f += check("source column drives the indicator", int(farming["count"]), 1)
    return f


def test_genuine_column_collision_raises():
    """Two real groups sharing a leaf name must fail loudly, not silently overwrite.

    This is not the Kobo case - these are ordinary grouped fields - so dropping is wrong
    and guessing is worse. The loader should refuse.
    """
    header = "consent,household_size,visit/notes,followup/notes\n"
    row = "yes,4,first,second\n"
    try:
        cs.load(io.StringIO(header + row))
    except ValueError as e:
        return check("collision names the offending column", "notes" in str(e), True)
    print("FAIL genuine collision was not raised")
    return 1


def main():
    tests = [
        test_declined_hiv_is_not_zero,
        test_non_consenting_dropped_but_counted,
        test_multiselect_expands_to_indicators,
        test_cross_field_constraint_is_caught,
        test_mutually_exclusive_none_is_caught,
        test_clean_data_produces_no_problems,
        test_at_least_one_semantics,
        test_kobo_pre_expanded_columns_are_dropped,
        test_source_column_wins_over_pre_expanded,
        test_genuine_column_collision_raises,
    ]
    failures = 0
    for t in tests:
        print(f"\n-- {t.__name__}")
        failures += t() or 0
    print(f"\n{'FAILED' if failures else 'PASSED'}: {failures} assertion failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
