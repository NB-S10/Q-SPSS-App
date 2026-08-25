# Survey analysis

Crosstabs, RIM weighting and significance testing for survey data. Replaces the
work currently split between the Streamlit weighting wizard and the browser-only
regression/crosstab tools.

## Running it

```
make install     # uv venv on Python 3.12, then install
make dev         # http://localhost:8420
make test
```

## Layout

| Path | Holds |
|---|---|
| `app/core/` | The analysis engines: header parsing, crosstabs, raking, significance, modelling |
| `app/routers/` | HTTP endpoints, one module per screen |
| `app/models.py` | SQLModel schema. A `Variable` owns one or more dataframe columns |
| `web/` | Jinja templates, vanilla ES modules, Public First CSS and fonts |
| `data/` | Runtime only, gitignored. SQLite database and Parquet datasets |

Respondent-level data lives in Parquet under `data/datasets/`. SQLite holds only
the metadata describing it, so the database stays small and portable.

## Configuration

All via environment variable, so deployment needs no code change:

| Variable | Default |
|---|---|
| `SPSSQ_DATA_DIR` | `./data` |
| `SPSSQ_DB_PATH` | `./data/app.db` |
| `SPSSQ_MAX_UPLOAD_MB` | `200` |

## Conventions inherited from existing tools

- `weight_demog` is the weight column name.
- Alchemer colon-delimited headers: `CODE: QUESTION` for single response,
  `CODE: OPTION: QUESTION` for multi-punch and matrix items. Question codes match
  `^(\d+[a-z]?):`.
- Weighting targets are `Group` / `Specific` / `Proportion`, and a proportion of
  `0` means "free category, take whatever the sample has".
