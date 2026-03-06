# Project Paths — YikYak Matching

## Project Root
`/Users/Zax/Git/GitHub/TEST_Baymax`

## Directory Layout
```
/Users/Zax/Git/GitHub/TEST_Baymax/
├── data/yik-yak/yik-yak-profiles-cleaned_v4.csv   # Input data (67,953 rows)
├── scripts/                                         # All Python scripts & notebooks
│   ├── matching_v1.py
│   ├── matching_v2.py
│   ├── validate_v1.py
│   ├── validate_v2.py
│   └── parsing_exploration.ipynb
├── output/                                          # All generated CSV outputs
│   ├── matchings_zax_v1.csv
│   └── matchings_zax_v2.csv
└── Baymax/                                          # Framework (DO NOT MODIFY)
```

## Path Conventions
- Scripts live in `scripts/` and are run from that directory: `cd scripts && python matching_v1.py`
- From inside `scripts/`, use relative paths:
  - Input CSV: `../data/yik-yak/yik-yak-profiles-cleaned_v4.csv`
  - Output dir: `../output/`
- The `output/` directory must be created before running scripts.

## Important
- All `mkdir` and `cd` commands use the project root: `/Users/Zax/Git/GitHub/TEST_Baymax`
- The Baymax directory is the framework — never modify files inside it.
