# Parsing JSON Strings from CSV Columns

## The Problem
The `basicInfo` column contains JSON strings like:
```
{"name": "Alice", "birthday": "2000-01-01", "expectedGender": "male"}
```
These must be parsed to extract fields like `expectedGender`.

## Safe Parsing Pattern
```python
import json
import pandas as pd

def parse_basic_info(raw_value):
    """Parse basicInfo JSON string, returning dict or empty dict on failure."""
    if pd.isna(raw_value):
        return {}
    if not isinstance(raw_value, str):
        return {}
    try:
        parsed = json.loads(raw_value)
        if isinstance(parsed, dict):
            return parsed
        return {}
    except (json.JSONDecodeError, TypeError):
        return {}

# Apply to column
df["basicInfo_parsed"] = df["basicInfo"].apply(parse_basic_info)
```

## Extracting expectedGender
```python
def extract_expected_gender(parsed_info):
    """Extract expectedGender, returning None for missing/non-string values."""
    val = parsed_info.get("expectedGender", None)
    if isinstance(val, str) and val.strip():
        return val.strip().lower()
    # Non-string values (int, bool, list, etc.) → treat as no preference
    return None

df["expectedGender"] = df["basicInfo_parsed"].apply(extract_expected_gender)
```

## Gotchas
- **Non-string values**: `expectedGender` might be `null`, `true`, `123`, or a nested object — always check `isinstance(val, str)`.
- **Empty strings**: `""` or `" "` should be treated as no preference (same as missing).
- **Encoding issues**: Some JSON strings may have escaped unicode — `json.loads()` handles this automatically.
- **Nested JSON**: `basicInfo` might be double-encoded (a JSON string inside a JSON string). Check if the first parse returns a string, and parse again if so:
  ```python
  parsed = json.loads(raw_value)
  if isinstance(parsed, str):
      parsed = json.loads(parsed)  # double-encoded
  ```

## Notebook Exploration Pattern
When creating the `.ipynb` to demonstrate parsing:
```python
# Show distribution of expectedGender values
print(df["expectedGender"].value_counts(dropna=False))

# Show examples of non-string values that were handled
non_str_mask = df["basicInfo_parsed"].apply(
    lambda d: "expectedGender" in d and not isinstance(d.get("expectedGender"), str)
)
print(f"Non-string expectedGender values: {non_str_mask.sum()}")
print(df.loc[non_str_mask, "basicInfo"].head(10))
```

## Performance
- `json.loads()` on 68K rows takes < 1 second — no optimization needed.
- Avoid `ast.literal_eval()` — it doesn't handle JSON `null`, `true`, `false` correctly.
