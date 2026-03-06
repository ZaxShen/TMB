# Validation Script Pattern

## Architecture
Each validation script follows a consistent pattern: individual check functions + a runner.

```python
import sys
import pandas as pd

# --- Load data ---
INPUT_CSV = "../data/yik-yak/yik-yak-profiles-cleaned_v4.csv"
MATCHINGS_CSV = "../output/matchings_zax_v1.csv"

profiles = pd.read_csv(INPUT_CSV, dtype={"userId": str, "school": str, "has_face": str})
matchings = pd.read_csv(MATCHINGS_CSV, dtype=str)

# CRITICAL: pandas reads the string "None" as a literal string, NOT as NaN.
# You MUST convert it after loading:
matchings["matchedUserId"] = matchings["matchedUserId"].replace("None", pd.NA)

# --- Check functions ---
# Each returns (passed: bool, message: str)

def check_completeness(profiles, matchings):
    input_ids = set(profiles["userId"])
    output_ids = set(matchings["userId"])
    missing = input_ids - output_ids
    extra = output_ids - input_ids
    dupes = matchings["userId"].duplicated().sum()
    if missing or extra or dupes:
        return False, f"Missing: {len(missing)}, Extra: {len(extra)}, Dupes: {dupes}"
    return True, f"All {len(input_ids)} users present, no duplicates"

def check_symmetry(matchings):
    match_dict = dict(zip(matchings["userId"], matchings["matchedUserId"]))
    violations = 0
    for uid, mid in match_dict.items():
        if pd.notna(mid):
            if match_dict.get(mid) != uid:
                violations += 1
    if violations:
        return False, f"{violations} asymmetric matches"
    return True, "All matches are symmetric"

# ... more check functions ...

# --- Runner ---
def run_checks():
    checks = [
        ("Completeness", check_completeness(profiles, matchings)),
        ("Symmetry", check_symmetry(matchings)),
        # ... add all checks
    ]
    
    all_passed = True
    for name, (passed, msg) in checks:
        status = "PASS" if passed else "FAIL"
        print(f"[{status}] {name}: {msg}")
        if not passed:
            all_passed = False
    
    print()
    if all_passed:
        print("ALL CHECKS PASSED")
    else:
        print("SOME CHECKS FAILED")
    
    sys.exit(0 if all_passed else 1)

if __name__ == "__main__":
    run_checks()
```

## Key Rules
1. **Always replace 'None' string with pd.NA** after loading matchings CSV
2. **Use `pd.notna(val)`** to check for non-null matchedUserId, never `val is not None`
3. **Exit code 0** = all passed, **exit code 1** = any failure
4. **Print format**: `[PASS]` or `[FAIL]` prefix per check, then summary line
5. Each check function is standalone — can be tested independently
