# Blueprint — Issue #2

**Objective**: YikYak User Matching (v1 + v2)
**Date**: 2026-03-06

---

```json
[
  {
    "branch_id": "1",
    "description": "Create the `scripts/` and `output/` directories at the project root (`/Users/Zax/Git/GitHub/TEST_Baymax/`). Run: `mkdir -p scripts output` from the project root.",
    "tools_required": ["shell"],
    "skills_required": ["project-paths-yikyak"],
    "success_criteria": "Both `scripts/` and `output/` directories exist at the project root."
  },
  {
    "branch_id": "2",
    "description": "Create `scripts/matching_v1.py` — a Python script that reads `data/yik-yak/yik-yak-profiles-cleaned_v4.csv`, groups users into pools by `(school, has_face)`, randomly pairs users 1:1 within each pool, and writes `output/matchings_zax_v1.csv` with columns `userId` and `matchedUserId`. Details: (1) Read CSV with `pandas`, dtype `userId`=str, `school`=str, `has_face`=str. (2) Group by `(school, has_face)` — `has_face` is a string 'yes'/'no', NOT boolean. (3) Within each pool, shuffle user IDs and pair sequentially (index 0↔1, 2↔3, etc.). If odd count, last user gets `matchedUserId=None`. (4) Collect all matches into a DataFrame with columns `userId`, `matchedUserId`. Every userId from input must appear exactly once. (5) Write to `output/matchings_zax_v1.csv` with `index=False`. Use relative paths from project root (script is run from project root via `python scripts/matching_v1.py`). Print summary: total users, matched pairs, unmatched count, pool counts.",
    "tools_required": ["file_write", "shell"],
    "skills_required": ["pool-matching-algorithm", "csv-pandas-matching", "project-paths-yikyak"],
    "success_criteria": "Running `python scripts/matching_v1.py` from project root produces `output/matchings_zax_v1.csv` with exactly 67,953 rows (one per user), two columns (`userId`, `matchedUserId`), and prints a summary to stdout."
  },
  {
    "branch_id": "3",
    "description": "Create `scripts/validate_v1.py` — a validation script that reads `output/matchings_zax_v1.csv` and `data/yik-yak/yik-yak-profiles-cleaned_v4.csv` and checks ALL of the following rules, printing PASS/FAIL for each: (1) Every userId from the input CSV appears exactly once in the output. (2) No userId appears as both matched and unmatched. (3) Symmetry: if A→B then B→A. (4) No self-matches. (5) Pool constraint: every matched pair shares the same `school`. (6) Face constraint: every matched pair shares the same `has_face` value. (7) Every `matchedUserId` (when not null) exists in the input `userId` column. (8) No user is matched to more than one other user. Print a final summary: 'ALL CHECKS PASSED' or list failures. Exit code 0 on success, 1 on failure.",
    "tools_required": ["file_write", "shell"],
    "skills_required": ["csv-pandas-matching", "project-paths-yikyak"],
    "success_criteria": "Running `python scripts/validate_v1.py` from project root prints 'ALL CHECKS PASSED' and exits with code 0 when run against the output of `matching_v1.py`."
  },
  {
    "branch_id": "4",
    "description": "Run `scripts/matching_v1.py` to generate `output/matchings_zax_v1.csv`, then run `scripts/validate_v1.py` to confirm all rules pass. Execute from project root: `python scripts/matching_v1.py && python scripts/validate_v1.py`. If validation fails, debug and fix `matching_v1.py` until validation passes.",
    "tools_required": ["shell"],
    "skills_required": ["project-paths-yikyak"],
    "success_criteria": "Both scripts run successfully. `validate_v1.py` prints 'ALL CHECKS PASSED' and exits with code 0. `output/matchings_zax_v1.csv` exists with 67,953 rows."
  },
  {
    "branch_id": "5",
    "description": "Create `scripts/matching_v2.py` — a Python script that builds on v1 logic but adds gender preference matching. Steps: (1) Read CSV with pandas (same dtypes as v1, plus `basicInfo`=str, `gender_clean`=str). (2) Parse `basicInfo` JSON column to extract `expectedGender`: use `json.loads()` safely, handle NaN/non-string/empty values → treat as None (no preference). Normalize to lowercase and strip whitespace. (3) Group by `(school, has_face)` pools (same hard constraint as v1). (4) Within each pool, run 3-round cascade: Round 1 — match users where BOTH have preferences and each satisfies the other's (A.expectedGender == B.gender_clean AND B.expectedGender == A.gender_clean); Round 2 — match remaining preference-having users with no-preference users where the preference user's expectedGender matches the no-preference user's gender_clean; Round 3 — match remaining no-preference users randomly with each other. (5) Unmatched users get `matchedUserId=None`. (6) Write `output/matchings_zax_v2.csv` with columns `userId`, `matchedUserId`. Print summary: total users, matched per round, unmatched count.",
    "tools_required": ["file_write", "shell"],
    "skills_required": ["pool-matching-algorithm", "csv-pandas-matching", "json-from-csv-column", "project-paths-yikyak"],
    "success_criteria": "Running `python scripts/matching_v2.py` from project root produces `output/matchings_zax_v2.csv` with exactly 67,953 rows, two columns, and prints round-by-round matching statistics."
  },
  {
    "branch_id": "6",
    "description": "Create `scripts/validate_v2.py` — a validation script that reads `output/matchings_zax_v2.csv` and `data/yik-yak/yik-yak-profiles-cleaned_v4.csv` and checks ALL v1 rules (completeness, symmetry, no self-match, same school, same has_face) PLUS v2-specific rules: (1) For every matched pair where BOTH users have a non-null `expectedGender`, verify bidirectional gender satisfaction (A.expectedGender == B.gender_clean AND B.expectedGender == A.gender_clean). (2) For every matched pair where exactly ONE user has a preference, verify that the preference user's expectedGender matches the other user's gender_clean. (3) Report statistics: how many pairs are mutual-preference, one-preference, no-preference. Parse `expectedGender` from `basicInfo` the same way as `matching_v2.py`. Print PASS/FAIL per check and final summary. Exit code 0 on success, 1 on failure.",
    "tools_required": ["file_write", "shell"],
    "skills_required": ["csv-pandas-matching", "json-from-csv-column", "project-paths-yikyak"],
    "success_criteria": "Running `python scripts/validate_v2.py` from project root prints 'ALL CHECKS PASSED' and exits with code 0 when run against the output of `matching_v2.py`."
  },
  {
    "branch_id": "7",
    "description": "Run `scripts/matching_v2.py` to generate `output/matchings_zax_v2.csv`, then run `scripts/validate_v2.py` to confirm all rules pass. Execute from project root: `python scripts/matching_v2.py && python scripts/validate_v2.py`. If validation fails, debug and fix `matching_v2.py` until validation passes.",
    "tools_required": ["shell"],
    "skills_required": ["project-paths-yikyak"],
    "success_criteria": "Both scripts run successfully. `validate_v2.py` prints 'ALL CHECKS PASSED' and exits with code 0. `output/matchings_zax_v2.csv` exists with 67,953 rows."
  },
  {
    "branch_id": "8",
    "description": "Create `scripts/parsing_exploration.ipynb` — a Jupyter notebook (created programmatically using `nbformat` or raw JSON) that demonstrates parsing `basicInfo.expectedGender`. The notebook must contain these sections as separate cells: (1) Markdown: title and description. (2) Code: Load CSV and show sample `basicInfo` values (first 5 rows). (3) Code: Parse `basicInfo` JSON with `json.loads()`, show the parsing function with error handling. (4) Code: Extract `expectedGender`, show value distribution with `value_counts(dropna=False)`. (5) Code: Show examples of non-string `expectedGender` values (null, numeric, boolean, etc.) and how they are handled (treated as no preference). (6) Markdown: Summary of findings — how many users have preferences, how many don't, what non-string types were encountered. Install `nbformat` first if needed: `uv add nbformat`. The notebook should be valid JSON and openable in Jupyter.",
    "tools_required": ["file_write", "shell"],
    "skills_required": ["jupyter-notebook-creation", "json-from-csv-column", "project-paths-yikyak"],
    "success_criteria": "File `scripts/parsing_exploration.ipynb` exists, is valid JSON, and can be validated with `python -c \"import json; json.load(open('scripts/parsing_exploration.ipynb'))\"`. Contains at least 6 cells (mix of markdown and code) covering all required sections."
  }
]
```
