# Creating Jupyter Notebooks

## Installation
```bash
uv add jupyter nbformat pandas
```

## Option 1: Create Notebook Programmatically (Preferred for Automation)
Use `nbformat` to create a `.ipynb` file without launching Jupyter:

```python
import nbformat

nb = nbformat.v4.new_notebook()

# Add a markdown cell
nb.cells.append(nbformat.v4.new_markdown_cell(
    "# Parsing `basicInfo.expectedGender`\n\n"
    "This notebook demonstrates how we extract and handle the `expectedGender` field."
))

# Add a code cell
nb.cells.append(nbformat.v4.new_code_cell(
    "import pandas as pd\nimport json\n\n"
    "df = pd.read_csv('yik-yak-profiles-cleaned_v4.csv', dtype=str)\n"
    "print(f'Total rows: {len(df)}')"
))

# Add more cells as needed...

# Write the notebook
with open("parsing_exploration.ipynb", "w") as f:
    nbformat.write(nb, f)
```

## Option 2: Write the JSON Directly
A `.ipynb` file is just JSON. Minimal structure:
```python
import json

notebook = {
    "nbformat": 4,
    "nbformat_minor": 5,
    "metadata": {
        "kernelspec": {
            "display_name": "Python 3",
            "language": "python",
            "name": "python3"
        },
        "language_info": {"name": "python", "version": "3.11.0"}
    },
    "cells": [
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": ["# Title\n", "Description"]
        },
        {
            "cell_type": "code",
            "metadata": {},
            "source": ["import pandas as pd\n", "df = pd.read_csv('data.csv')"],
            "outputs": [],
            "execution_count": None
        }
    ]
}

with open("parsing_exploration.ipynb", "w") as f:
    json.dump(notebook, f, indent=1)
```

## What the Notebook Should Contain
For this project, the `parsing_exploration.ipynb` should demonstrate:

1. **Loading the data** and showing the `basicInfo` column samples
2. **Parsing JSON** from the column with error handling
3. **Extracting `expectedGender`** and showing value distribution
4. **Handling non-string values** — show examples of `null`, numeric, boolean values and how they're treated
5. **Summary statistics** — how many users have preferences vs. no preference

## Gotchas
- **Cell source must be a list of strings** (each line) when writing JSON directly, or a single string when using `nbformat`.
- **Outputs should be empty** — the notebook is meant to be run by the reviewer.
- **Don't forget `execution_count: null`** for code cells in raw JSON format.
- **File extension must be `.ipynb`** — Jupyter won't recognize other extensions.

## Running the Notebook (for QA)
```bash
# Execute all cells and save output in-place
jupyter nbconvert --to notebook --execute parsing_exploration.ipynb --output parsing_exploration.ipynb

# Or just validate it opens without errors
jupyter nbconvert --to html parsing_exploration.ipynb
```
