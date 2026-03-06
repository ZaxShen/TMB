# Pool-Based 1:1 Matching Algorithm

## Core Concepts
- **Matching is 1:1 and symmetric**: If A matches B, then B matches A. Each user appears at most once.
- **Pools are hard constraints**: Users are grouped by `(school, has_face)`. Cross-pool matching is NEVER allowed.
- **Unmatched users**: Get `matchedUserId = None`. This happens when a pool has an odd count or when preference constraints leave someone out.

## v1: Random Matching Within Pools

```python
import random

def match_pool_v1(user_ids: list[str]) -> dict[str, str | None]:
    """Randomly pair users. Odd-one-out is unmatched."""
    shuffled = user_ids.copy()
    random.shuffle(shuffled)
    
    matches = {}
    for i in range(0, len(shuffled) - 1, 2):
        a, b = shuffled[i], shuffled[i + 1]
        matches[a] = b
        matches[b] = a
    
    # Odd-one-out
    if len(shuffled) % 2 == 1:
        matches[shuffled[-1]] = None
    
    return matches
```

## v2: Gender Preference Matching (3 Rounds)

### Data Preparation
Each user needs: `userId`, `gender_clean`, `expectedGender` (None = no preference).

### Round 1: Mutual Bidirectional Preference
Both users have preferences, and each satisfies the other's.
```python
def round1_mutual_preference(users: list[dict]) -> tuple[dict, list[dict]]:
    """Match users with mutual bidirectional gender preferences."""
    # users with a preference
    pref_users = [u for u in users if u["expectedGender"] is not None]
    no_pref_users = [u for u in users if u["expectedGender"] is None]
    
    matches = {}
    matched_ids = set()
    
    # Build index: gender -> list of users wanting that gender
    # Try to pair: A wants B's gender AND B wants A's gender
    random.shuffle(pref_users)
    
    for i, a in enumerate(pref_users):
        if a["userId"] in matched_ids:
            continue
        for j in range(i + 1, len(pref_users)):
            b = pref_users[j]
            if b["userId"] in matched_ids:
                continue
            if (a["expectedGender"] == b["gender_clean"] and
                b["expectedGender"] == a["gender_clean"]):
                matches[a["userId"]] = b["userId"]
                matches[b["userId"]] = a["userId"]
                matched_ids.add(a["userId"])
                matched_ids.add(b["userId"])
                break
    
    remaining = [u for u in users if u["userId"] not in matched_ids]
    return matches, remaining
```

### Round 2: Preference User + No-Preference User
The preference-having user's `expectedGender` must match the no-preference user's `gender_clean`.
```python
def round2_pref_with_nopref(remaining: list[dict]) -> tuple[dict, list[dict]]:
    """Match preference users with no-preference users (one-directional check)."""
    pref_users = [u for u in remaining if u["expectedGender"] is not None]
    no_pref_users = [u for u in remaining if u["expectedGender"] is None]
    
    matches = {}
    matched_ids = set()
    
    random.shuffle(pref_users)
    random.shuffle(no_pref_users)
    
    for a in pref_users:
        if a["userId"] in matched_ids:
            continue
        for b in no_pref_users:
            if b["userId"] in matched_ids:
                continue
            if a["expectedGender"] == b["gender_clean"]:
                matches[a["userId"]] = b["userId"]
                matches[b["userId"]] = a["userId"]
                matched_ids.add(a["userId"])
                matched_ids.add(b["userId"])
                break
    
    leftover = [u for u in remaining if u["userId"] not in matched_ids]
    return matches, leftover
```

### Round 3: No-Preference Users Together
No gender constraint — just pair them randomly.
```python
def round3_nopref_together(remaining: list[dict]) -> tuple[dict, list[dict]]:
    """Pair remaining no-preference users randomly."""
    no_pref = [u for u in remaining if u["expectedGender"] is None]
    has_pref = [u for u in remaining if u["expectedGender"] is not None]
    
    matches = {}
    random.shuffle(no_pref)
    
    for i in range(0, len(no_pref) - 1, 2):
        a, b = no_pref[i], no_pref[i + 1]
        matches[a["userId"]] = b["userId"]
        matches[b["userId"]] = a["userId"]
    
    # Odd-one-out from no_pref + all remaining pref users → unmatched
    unmatched = has_pref.copy()
    if len(no_pref) % 2 == 1:
        unmatched.append(no_pref[-1])
    
    return matches, unmatched
```

### Combining All Rounds
```python
def match_pool_v2(users: list[dict]) -> dict[str, str | None]:
    all_matches = {}
    
    r1_matches, remaining = round1_mutual_preference(users)
    all_matches.update(r1_matches)
    
    r2_matches, remaining = round2_pref_with_nopref(remaining)
    all_matches.update(r2_matches)
    
    r3_matches, unmatched = round3_nopref_together(remaining)
    all_matches.update(r3_matches)
    
    for u in unmatched:
        all_matches[u["userId"]] = None
    
    return all_matches
```

## Validation Checks (Both Versions)
1. **Completeness**: Every userId from input appears exactly once in output.
2. **Symmetry**: If A→B then B→A.
3. **No self-match**: No user matched with themselves.
4. **Pool constraint**: Matched users share the same `school` AND `has_face`.
5. **No duplicates**: No userId appears as matchedUserId more than once.
6. **v2 only — Preference check**: If both users have preferences, they must be mutually satisfied.

## Gotchas
- **Shuffle before matching** to ensure randomness — don't rely on CSV row order.
- **Set a random seed** (`random.seed(42)`) for reproducibility during development/testing.
- **gender_clean values**: Likely `"female"`, `"male"` — verify actual values in the data before hardcoding.
- **The O(n²) inner loops** are fine for pool sizes in the hundreds/low thousands. Don't prematurely optimize.
