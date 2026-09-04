"""Clean and summarise ODK submissions from the CEPA household survey.

ODK Central exports one row per submission. Two things about that export need handling
before the data is analysable:

1. `select_multiple` answers arrive as a single space-delimited string
   ("farming livestock other"), which is unusable in a groupby. They are expanded here
   into one 0/1 indicator column per choice.
2. The HIV question is deliberately optional, so a blank is "declined to answer", not
   zero. Coercing it to 0 would silently understate prevalence. It is kept as a nullable
   integer and excluded from denominators, which is the same handling the CMS suppressed
   values got in the hospital-readmissions project.

The form already enforces the range and cross-field constraints on device. They are
re-checked here anyway: forms get revised mid-collection, and paper backfill entered
later does not pass through the form at all.

Usage:
    python clean_submissions.py data/sample_submissions.csv --outdir out
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

# choice lists, mirrored from the choices sheet in build_xlsform.py
MULTISELECT = {
    "income_source": ["remittance_sa", "piece_jobs", "child_grant", "pension", "livestock",
                      "crop_sales", "alcohol_sales", "petty_trade", "domestic_work", "other"],
    "strengths": ["farming", "livestock", "piece_jobs", "shopkeeping", "hairdressing",
                  "petty_trade", "alcohol_production", "domestic_work", "other"],
    "challenges": ["adverse_weather", "land_use_conflict", "food_insecurity", "no_electricity",
                   "water_shortage", "poor_roads", "unemployment", "school_fees", "non_payment",
                   "seed_supply", "weak_collaboration", "none", "other"],
    "opportunities": ["electricity", "roads", "water_supply", "irrigation", "farming_inputs",
                      "livestock_support", "income_generation", "community_collaboration", "other"],
}

COUNT_COLS = ["single_parents", "people_over_65", "people_with_hiv"]


def load(path: str | Path) -> pd.DataFrame:
    """Read an ODK Central or KoboToolbox CSV export into a frame with flat column names.

    Two export shapes have to be reconciled. ODK Central prefixes grouped fields with their
    group path (`composition/household_size`), which is stripped here. KoboToolbox does that
    too, but additionally ships every `select_multiple` pre-expanded into one column per
    choice (`strengths/livestock`). Those pre-expanded columns are dropped rather than kept:
    `expand_multiselect` recomputes the same indicators from the space-delimited source
    column, that is the path the tests cover, and keeping both would leave the output with
    two competing versions of the same fact.

    Dropping them also removes a collision. `income_source/livestock` and
    `strengths/livestock` both reduce to `livestock` once the prefix is stripped, as do
    piece_jobs, petty_trade, domestic_work and other. Found the first time a real Kobo
    export was run through the pipeline; the fixtures could not surface it because they
    were written in ODK Central's shape only, which has no pre-expanded columns.

    Raises ValueError if any collision survives, rather than letting one column silently
    win over another.
    """
    df = pd.read_csv(path, dtype=str, keep_default_na=False, na_values=[""])

    pre_expanded = {f"{col}/{choice}"
                    for col, choices in MULTISELECT.items()
                    for choice in choices}
    dropped = [c for c in df.columns if c in pre_expanded]
    df = df.drop(columns=dropped)

    df.columns = [c.split("/")[-1] for c in df.columns]

    names = list(df.columns)
    collisions = sorted({c for c in names if names.count(c) > 1})
    if collisions:
        raise ValueError(
            "column names collide after stripping group prefixes: "
            + ", ".join(collisions)
            + ". Two exported fields share a leaf name, so one would silently overwrite "
              "the other. Widen the prefix handling instead of guessing which is wanted."
        )

    df.attrs["pre_expanded_dropped"] = len(dropped)
    return df


def coerce_numeric(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["household_size"] = pd.to_numeric(df["household_size"], errors="coerce").astype("Int64")
    for c in COUNT_COLS:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").astype("Int64")
    return df


def drop_non_consenting(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Non-consenting visits are real records of fieldwork effort but carry no data."""
    keep = df["consent"].str.lower() == "yes"
    return df[keep].copy(), int((~keep).sum())


def expand_multiselect(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for col, choices in MULTISELECT.items():
        if col not in df.columns:
            continue
        selected = df[col].fillna("").str.split()
        for choice in choices:
            df[f"{col}__{choice}"] = selected.apply(lambda s, c=choice: int(c in s))
    return df


def validate(df: pd.DataFrame) -> list[str]:
    """Return human-readable violations. Empty list means the data is internally consistent."""
    problems: list[str] = []

    def flag(mask, message):
        for idx in df.index[mask]:
            problems.append(f"row {idx}: {message}")

    size = df["household_size"]
    flag(size.isna(), "household_size is missing")
    flag(size.notna() & ((size < 1) | (size > 30)), "household_size outside 1-30")

    for c in COUNT_COLS:
        if c not in df.columns:
            continue
        v = df[c]
        flag(v.notna() & (v < 0), f"{c} is negative")
        # NA is legitimate for people_with_hiv (declined) so only compare where present
        flag(v.notna() & size.notna() & (v > size), f"{c} exceeds household_size")

    for col in MULTISELECT:
        if col in df.columns:
            flag(df[col].isna(), f"{col} has no selection")

    # 'none' is mutually exclusive with any substantive challenge
    if "challenges__none" in df.columns:
        others = [f"challenges__{c}" for c in MULTISELECT["challenges"] if c != "none"]
        both = (df["challenges__none"] == 1) & (df[others].sum(axis=1) > 0)
        flag(both, "challenges records 'none' alongside a specific challenge")

    return problems


def summarize(df: pd.DataFrame) -> pd.DataFrame:
    """Household-level indicators, matching the definitions used in the original report."""
    n = len(df)
    hiv = df["people_with_hiv"]
    hiv_answered = int(hiv.notna().sum())

    rows = [
        ("Households surveyed", n, n,
         "Consenting households only."),
        ("Households with at least one single parent",
         int((df["single_parents"].fillna(0) > 0).sum()), n, ""),
        ("Households with at least one member aged 65+",
         int((df["people_over_65"].fillna(0) > 0).sum()), n, ""),
        ("Households with at least one member living with HIV",
         int((hiv.fillna(0) > 0).sum()), hiv_answered,
         f"Denominator excludes {n - hiv_answered} household(s) that declined this optional question."),
        ("Households naming farming as a strength",
         int(df.get("strengths__farming", pd.Series(0, index=df.index)).sum()), n, ""),
        ("Households naming livestock as a strength",
         int(df.get("strengths__livestock", pd.Series(0, index=df.index)).sum()), n, ""),
        ("Households reporting no electricity",
         int(df.get("challenges__no_electricity", pd.Series(0, index=df.index)).sum()), n, ""),
        ("Households reporting food insecurity",
         int(df.get("challenges__food_insecurity", pd.Series(0, index=df.index)).sum()), n, ""),
    ]

    out = pd.DataFrame(rows, columns=["indicator", "count", "denominator", "note"])
    out["percent"] = (out["count"] / out["denominator"] * 100).round(1)
    return out[["indicator", "count", "denominator", "percent", "note"]]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("csv", help="ODK Central CSV export")
    ap.add_argument("--outdir", default="out")
    ap.add_argument("--strict", action="store_true",
                    help="exit non-zero if any validation problem is found")
    args = ap.parse_args(argv)

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    raw = load(args.csv)
    df, declined = drop_non_consenting(raw)
    df = coerce_numeric(df)
    df = expand_multiselect(df)

    problems = validate(df)

    print(f"submissions read      : {len(raw)}")
    if raw.attrs.get("pre_expanded_dropped"):
        print(f"pre-expanded dropped  : {raw.attrs['pre_expanded_dropped']} "
              f"(Kobo select_multiple columns; recomputed from the source column below)")
    print(f"non-consenting dropped: {declined}")
    print(f"analysable households : {len(df)}")
    print(f"validation problems   : {len(problems)}")
    for p in problems:
        print(f"  ! {p}")

    tidy_path = outdir / "households_clean.csv"
    summary_path = outdir / "indicator_summary.csv"
    df.to_csv(tidy_path, index=False)
    summary = summarize(df)
    summary.to_csv(summary_path, index=False)

    print(f"\nwrote {tidy_path}")
    print(f"wrote {summary_path}\n")
    print(summary.to_string(index=False))

    return 1 if (problems and args.strict) else 0


if __name__ == "__main__":
    sys.exit(main())
