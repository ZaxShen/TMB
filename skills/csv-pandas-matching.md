# CSV Handling with Pandas

## Installation
```bash
uv add pandas
```

## Reading CSV
```python
import pandas as pd

# Read the profiles CSV — specify dtypes to avoid silent coercion
df = pd.read_csv(
    "yik-yak-profiles-cleaned_v4.csv",
    dtype={"userId": str, "school": str, "has_face": str, "gender_clean": str, "basicInfo": str},
    keep_default_na=True,  # NaN for missing values
)
```

### Gotchas
- **`has_face` is a string** (`"yes"` / `"no"`), NOT a boolean. Never compare with `True`/`False`.
- **`userId` should be read as string** to avoid integer overflow or float conversion on large IDs.
- **`basicInfo` is a JSON string column** — must be parsed separately (see `json-from-csv-column` skill).
- **Missing values**: Use `pd.isna(val)` to check, not `val is None` or `val == ""`.

## Writing Output CSV
```python
# Output must have exactly these columns
output_df = pd.DataFrame({
    "userId": user_ids,           # all user IDs from input
    "matchedUserId": matched_ids, # matched partner or None
})

# Write with None becoming empty string in CSV
output_df.to_csv("matchings_zax_v1.csv", index=False)
```

### Output Rules
- Every userId from the input must appear exactly once in the output.
- `matchedUserId` is `None`/NaN for unmatched users.
- Naming convention: `matchings_zax_v1.csv`, `matchings_zax_v2.csv`

## Grouping by Pool
```python
# Pool users by (school, has_face) — these are hard constraints
for (school, has_face), group in df.groupby(["school", "has_face"]):
    pool_users = group["userId"].tolist()
    # ... perform matching within this pool
```

## Validation Pattern
```python
# Check symmetry: if A matched B, then B must have matched A
matches = pd.read_csv("matchings_zax_v1.csv", dtype=str)
match_dict = dict(zip(matches["userId"], matches["matchedUserId"]))

for uid, mid in match_dict.items():
    if pd.notna(mid):
        assert match_dict.get(mid) == uid, f"Asymmetric match: {uid} -> {mid}"
```

## Performance Tips
- For ~68K rows, pandas handles this trivially — no chunking needed.
- Use `.groupby()` rather than manual filtering loops.
- Avoid `iterrows()` for large operations; prefer vectorized ops or `groupby().apply()`.
