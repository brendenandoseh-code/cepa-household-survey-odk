# CEPA Household Survey — ODK/XLSForm instrument and cleaning pipeline

A digitised version of a community health survey I designed and ran on paper as a Peace Corps
Volunteer in Lesotho, rebuilt as an ODK XLSForm with the submission-cleaning pipeline that
should have gone with it.

**What is here**

| File | What it is |
|---|---|
| `build_xlsform.py` | Source of truth for the form. Generates the XLSForm workbook. |
| `cepa_household_survey.xlsx` | The XLSForm itself — `survey`, `choices`, `settings` sheets. |
| `cepa_household_survey.xml` | The compiled ODK form, produced by pyxform. |
| `clean_submissions.py` | Reads an ODK Central CSV export, validates it, and produces analysis-ready output. |
| `test_clean_submissions.py` | Tests asserting numerical behaviour of the cleaner. |
| `data/sample_submissions.csv` | **Synthetic** submissions used to demonstrate the pipeline. |

## Why I built it

In 2024 I ran a 16-household structured community health survey in Ha Monyake, Mohale's Hoek
District, as the community-entry assessment for my Peace Corps assignment. It was done on
paper and tallied by hand into a table. The findings held up — 7 of 16 households had a member
living with HIV, 4 of 16 were single-parent households, 7 of 16 included someone aged 65 or
over, and the infrastructure gaps residents named (electricity, water, roads) became the
evidence base for a funded community intervention.

What it did not have was a data pipeline. Paper forms mean no constraint enforcement at the
point of collection, no audit trail, and a transcription step where errors enter silently.
This repository is that survey rebuilt the way I would build it now.

## The form

`build_xlsform.py` is the source of truth rather than the spreadsheet, because an `.xlsx` is a
zip archive and reviewing a diff of one is guesswork. The script writes the workbook; pyxform
compiles it.

The instrument follows the original paper survey. Every question and every answer option comes
from the questions I actually asked and the responses residents actually gave — the income
sources, strengths, challenges and growth opportunities in the `choices` sheet are the
free-text answers from the 2024 fieldwork, normalised into coded lists. Nothing is invented.
"Fato-Fato" appears under opportunities because that is what residents called irrigation work.

Design decisions worth pointing at:

- **Consent gate.** A `select_one` consent question controls the `relevant` expression on every
  substantive group. Declining ends the interview but still submits a record, so refusals stay
  visible as fieldwork effort rather than disappearing.
- **Cross-field constraints.** `single_parents`, `people_over_65` and `people_with_hiv` are each
  constrained to `<= ${household_size}`. On paper nothing stopped a tally that exceeded the
  household. In the compiled XML this resolves to
  `constraint=". >= 0 and . <= /data/composition/household_size"`.
- **The HIV question is optional by design.** It sits behind a note read aloud telling the
  respondent they may skip it, and it is the only substantive question without `required`.
  Asking a household in a village of this size to disclose HIV status is not a neutral act, and
  a required field would have coerced an answer or produced a false zero.
- **Other-specify branches.** Each `select_multiple` has an `other` option with a follow-up text
  field gated on `selected(${field}, 'other')`.

## The cleaning pipeline

ODK Central exports one row per submission, and two things need handling before analysis:

1. `select_multiple` answers arrive space-delimited in one column (`"farming livestock other"`),
   which is unusable in a groupby. They expand to one 0/1 indicator per choice. The tests check
   that `piece_jobs` — which appears in both the income and strengths lists — does not bleed
   across columns.
2. **A blank HIV answer means "declined", not zero.** Coercing it to 0 would silently understate
   prevalence. It is kept as a nullable integer and excluded from that indicator's denominator,
   and the summary reports how many households were excluded and why. This is the same handling
   I gave CMS-suppressed values in my hospital-readmissions project, for the same reason: a
   placeholder that gets averaged is worse than a gap that gets declared.

The form already enforces the range and cross-field rules on device. `clean_submissions.py`
re-checks them anyway, because forms get revised mid-collection and paper backfill entered later
never passes through the form at all. The sample data includes two deliberate violations to show
the check firing.

## Running it

```bash
pip install pyxform openpyxl pandas
python build_xlsform.py
python -m pyxform.xls2xform --skip_validate cepa_household_survey.xlsx cepa_household_survey.xml
python clean_submissions.py data/sample_submissions.csv --outdir out
python test_clean_submissions.py
```

Output on the sample data:

```
submissions read      : 12
non-consenting dropped: 1
analysable households : 11
validation problems   : 2
  ! row 10: people_with_hiv exceeds household_size
  ! row 11: challenges records 'none' alongside a specific challenge
```

All 12 test assertions pass.

## Honest limits

- **The form is compiled but not deployed.** pyxform's conversion succeeds, which means the
  XLSForm parses, every `${...}` reference resolves, and the constraint and relevant expressions
  are valid XPath. The stricter ODK Validate pass needs a Java runtime I did not have available,
  and I have not yet pushed the form to an ODK Central server or collected a real submission
  through it. Compiled and deployed are different claims and I am making the first one.
- **No real survey data is published here, and none will be.** The 2024 responses are
  household-level records including HIV status in a named village of roughly sixteen surveyed
  households. Aggregate figures are safe to publish and appear above; the row-level table is not,
  because with a denominator that small it is potentially re-identifying. Everything in
  `data/` is synthetic, generated to exercise the code paths, and labelled as such in every row.
- **This is a reconstruction, not the original instrument.** The paper survey was a tally table
  with free-text columns. Coding those free-text answers into choice lists is an interpretation I
  made afterwards, and a real redeployment would want the original respondents' wording tested
  against the coded options before going to field.
- **Single-language.** The original interviews were conducted in Sesotho. A production version
  would carry `label::Sesotho (st)` columns alongside the English, and the translation would need
  a native speaker rather than me.

## Provenance

Survey instrument, fieldwork and original analysis: my own, Ha Monyake, Mohale's Hoek District,
Lesotho, 2024, as a Peace Corps Volunteer attached to Mofumahali oa Rosari Health Center.
Digitisation, cleaning pipeline and tests: 2026.
