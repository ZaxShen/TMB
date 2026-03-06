# V2 Validation — Gender Preference Checks

## Overview
`validate_v2.py` must run ALL v1 checks (completeness, symmetry, no self-match, same school, same has_face, valid IDs, no multi-match) **plus** gender preference validation on each matched pair.

## Setup: Reparse expectedGender Identically to matching_v2.py
The validator must parse `basicInfo.expectedGender` using the **exact same logic** as `matching_v2.py`. Copy the `parse_basic_info()` and `extract_expected_gender()` functions verbatim — do NOT reimplement.

```python
import json
import pandas as pd

def parse_basic_info(raw_value) -> dict:
    if pd.isna(raw_value):
        return {}
    if not isinstance(raw_value, str):
        return {}
    try:
        parsed = json.loads(raw_value)
        if isinstance(parsed, str):
            parsed = json.loads(parsed)  # double-encoded
        if isinstance(parsed, dict):
            return parsed
        return {}
    except (json.JSONDecodeError, TypeError):
        return {}

def extract_expected_gender(parsed_info: dict):
    val = parsed_info.get("expectedGender", None)
    if isinstance(val, str) and val.strip():
        return val.strip().lower()
    return None
```

## Loading and Preparing Data
```python
profiles = pd.read_csv(INPUT_CSV, dtype={"userId": str, "school": str, "has_face": str, "basicInfo": str, "gender_clean": str})
matchings = pd.read_csv(MATCHINGS_CSV, dtype=str)

# CRITICAL: Convert "None" string to pd.NA
matchings["matchedUserId"] = matchings["matchedUserId"].replace("None", pd.NA)
matchings.loc[matchings["matchedUserId"] == "", "matchedUserId"] = pd.NA

# Parse expectedGender for all profiles
profiles["basicInfo_parsed"] = profiles["basicInfo"].apply(parse_basic_info)
profiles["expectedGender"] = profiles["basicInfo_parsed"].apply(extract_expected_gender)
profiles["gender_clean"] = profiles["gender_clean"].fillna("").str.strip().str.lower()

# Build lookup
profile_lookup = profiles.set_index("userId")
```

## Pair Classification Logic
For each matched pair (A, B), classify into exactly one category:

```python
def check_gender_preference():
    """Validate gender preference satisfaction for all matched pairs."""
    matched = matchings[matchings["matchedUserId"].notna()]
    
    mutual_pref = one_pref = no_pref = 0
    violations = []
    
    seen = set()  # avoid checking A→B and B→A twice
    for _, row in matched.iterrows():
        uid, mid = row["userId"], row["matchedUserId"]
        pair_key = tuple(sorted([uid, mid]))
        if pair_key in seen:
            continue
        seen.add(pair_key)
        
        a_pref = profile_lookup.loc[uid, "expectedGender"]  # str or None
        b_pref = profile_lookup.loc[mid, "expectedGender"]
        a_gender = profile_lookup.loc[uid, "gender_clean"]
        b_gender = profile_lookup.loc[mid, "gender_clean"]
        
        a_has_pref = pd.notna(a_pref) and a_pref is not None
        b_has_pref = pd.notna(b_pref) and b_pref is not None
        
        if a_has_pref and b_has_pref:
            # MUTUAL PREFERENCE — both must be satisfied
            mutual_pref += 1
            if a_pref != b_gender:
                violations.append(f"{uid} wants '{a_pref}' but {mid} is '{b_gender}'")
            if b_pref != a_gender:
                violations.append(f"{mid} wants '{b_pref}' but {uid} is '{a_gender}'")
        
        elif a_has_pref or b_has_pref:
            # ONE PREFERENCE — the pref-having user's expectedGender must match partner's gender
            one_pref += 1
            pref_user = uid if a_has_pref else mid
            other_user = mid if a_has_pref else uid
            pref_val = a_pref if a_has_pref else b_pref
            other_gender = b_gender if a_has_pref else a_gender
            if pref_val != other_gender:
                violations.append(f"{pref_user} wants '{pref_val}' but {other_user} is '{other_gender}'")
        
        else:
            # NO PREFERENCE — no gender check needed
            no_pref += 1
    
    print(f"  Pair breakdown: mutual={mutual_pref}, one-pref={one_pref}, no-pref={no_pref}")
    
    if violations:
        return False, f"{len(violations)} gender violations. First 5: {violations[:5]}"
    return True, f"All pairs satisfy gender preferences (mutual={mutual_pref}, one={one_pref}, none={no_pref})"
```

## Key Gotchas
1. **`expectedGender` stored as None in the profile_lookup**: When you do `profile_lookup.loc[uid, "expectedGender"]`, Python `None` and `pd.NA`/`NaN` behave differently. The `extract_expected_gender()` function returns Python `None`, but after storing in a DataFrame column, it becomes `NaN`. Use `pd.notna()` to check.
2. **Deduplicate pairs**: Each match is symmetric (A→B and B→A). Use `tuple(sorted([uid, mid]))` to avoid double-counting.
3. **gender_clean normalization**: Must match exactly what `matching_v2.py` does — `fillna("").str.strip().str.lower()`.
4. **Empty gender_clean**: A user with `gender_clean = ""` can never satisfy a preference check (no `expectedGender` value equals `""`), so they should only appear in no-pref pairs.

## Runner Integration
Add the gender check to the existing v1 check list:
```python
checks = [
    ("Completeness", check_completeness()),
    ("Symmetry", check_symmetry()),
    ("No self-match", check_no_self_match()),
    ("Same school", check_same_school()),
    ("Same has_face", check_same_has_face()),
    ("Valid match IDs", check_valid_ids()),
    ("No multi-match", check_no_multi_match()),
    ("Gender preference", check_gender_preference()),  # NEW for v2
]
```
