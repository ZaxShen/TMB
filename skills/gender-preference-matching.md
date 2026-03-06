# Gender Preference Matching (v2)

## Data Model
Each user has:
- `gender_clean`: their own gender (string like "female", "male", or NaN/empty)
- `expectedGender`: extracted from `basicInfo` JSON — the gender they want to match with (or None = no preference)

## Normalization Rules
- `gender_clean`: `fillna("")`, `.strip().lower()` — empty string means unknown gender
- `expectedGender`: extracted via `parse_basic_info()` + `extract_expected_gender()` — returns lowercase string or None

## 3-Round Cascade (within each pool)

### Round 1: Mutual Bidirectional Preference
- Both users have `expectedGender` (not None)
- A.expectedGender == B.gender_clean AND B.expectedGender == A.gender_clean
- **Bucket optimization**: group pref users by `(expectedGender, gender_clean)` tuple. Pair complementary buckets: bucket `(wants_X, is_Y)` pairs with bucket `(wants_Y, is_X)`.

### Round 2: Preference + No-Preference
- One user has `expectedGender`, the other doesn't
- The pref user's `expectedGender` must match the no-pref user's `gender_clean`
- Group no-pref users by `gender_clean`, then for each remaining pref user, pull from the matching bucket

### Round 3: Remaining No-Preference
- Neither user has `expectedGender`
- Random pairing (same as v1 logic)
- Odd-one-out gets None

## Validation Rules for v2
For each matched pair, classify:
- **Mutual-pref**: both have expectedGender → check bidirectional match
- **One-pref**: exactly one has expectedGender → check that pref user's expectedGender matches partner's gender_clean
- **No-pref**: neither has expectedGender → no gender check needed

## Edge Cases
- Users with `gender_clean` = empty/NaN can only match in Round 3 (no-pref with no-pref) since no pref user's expectedGender can match empty
- Users with `expectedGender` pointing to a gender not present in their pool → will fall through all rounds, end up unmatched
- Pools with all same gender and all wanting different gender → all unmatched after Round 1
