# Deploying this form

The form in this repository is **built and compiled** but **not deployed**. Deploying it takes
about twenty minutes and upgrades what you can honestly claim on a resume from "designed and
compiled an ODK form" to "designed, deployed, and collected through an ODK form."

You need to do this part yourself — it requires creating an account, which I can't do on your
behalf.

## Which platform

**Use KoboToolbox.** Verified 2026-08-07: free accounts are available at
<https://www.kobotoolbox.org/sign-up/>, with a choice of the Global server or an EU-hosted
server (Ireland). Pick **Global** — you have no data-residency requirement, and it is the one
most organisations use.

Kobo is the right choice over the alternatives for three reasons:

- It ingests XLSForm directly. The `.xlsx` in this repo uploads as-is, no conversion step.
- It is the standard tool in humanitarian and global-health MEL work — the same world MCD
  Global Health operates in. Naming Kobo in an interview lands better than naming a
  self-hosted instance nobody can verify.
- The free tier is enough. You are demonstrating capability, not running a real survey round.

ODK Central is the other option, but it means either paying for ODK Cloud or standing up a
server on a DigitalOcean droplet. That is a lot of yak-shaving for the same end result.

## Steps

1. **Create the account.** <https://www.kobotoolbox.org/sign-up/> → "Create an account" under
   *Global KoboToolbox Server*. Use your personal email. Confirm the verification email.

2. **Upload the form.** From the projects list, create a new project and choose the option to
   **upload an XLSForm**, then select:

   ```
   Portfolio_Projects\cepa-household-survey-odk\cepa_household_survey.xlsx
   ```

   If Kobo rejects it, the error will name a sheet and row. Fix it in `build_xlsform.py`, re-run
   `python build_xlsform.py`, and re-upload — do not hand-edit the `.xlsx`, or the repo and the
   deployed form will drift apart.

3. **Check the form preview.** Open the preview and confirm three things actually behave:
   - Answering **No** to the consent question hides every following group.
   - Entering a household size of 3 and then 5 people living with HIV shows the constraint
     message "Cannot exceed the household size you entered."
   - Selecting **Other** under income source reveals the follow-up text box.

   These are the three pieces of logic worth talking about in an interview, so see them work.

4. **Deploy it.** Deploy the project. That produces a web form link (Enketo) and makes the form
   available to the KoboCollect Android app.

5. **Submit two test responses** through the web form link — one consenting, one declining. Use
   obviously fake values.

6. **Export and run the pipeline on real export output.** Download the CSV export, then:

   ```bash
   python clean_submissions.py path\to\kobo_export.csv --outdir out
   ```

   Kobo's column headers may differ slightly from the sample file — it sometimes exports flat
   column names rather than the `group/field` paths ODK Central uses. `load()` already strips the
   group prefix, so it should work either way, but if a column is missing the script will raise a
   `KeyError` naming it. Fix the mapping rather than renaming the export by hand.

7. **Do not commit the export.** `.gitignore` already blocks `data/*_export.csv` and
   `data/submissions_*.csv`. Test data is harmless, but the habit matters and the next export
   might not be.

## After deploying

Update the **Honest limits** section of `README.md`. It currently says the form is compiled but
not deployed, and that stops being true the moment you finish step 5. Replace that bullet with
what is then accurate: which platform, and that you collected test submissions through it.

Keep the distinction the README already draws. Compiling, deploying, and collecting real
programme data are three different claims, and this repository should only ever assert the ones
it can show.
