"""Reading an uploaded file into a dataset the rest of the app can use."""
from __future__ import annotations

import csv
import io
from pathlib import Path

import pandas as pd

from app.core.headers import detect_header_style
from app.core.variables import build_variables
from app.core.weights import inspect_weights

SUPPORTED_SUFFIXES = {".csv", ".xlsx", ".xls"}


class IngestError(ValueError):
    """Something about the uploaded file stops it being read."""


def read_upload(filename: str, content: bytes, sheet: str | int = 0) -> pd.DataFrame:
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise IngestError(
            f"Can't read {suffix or 'that file'}. Upload a .csv, .xlsx or .xls file."
        )

    # Check for duplicate headers on the raw header row. pandas silently
    # renames the second "Age" to "Age.1", which hides the problem rather than
    # reporting it, so the check has to happen before pandas sees the file.
    _reject_duplicate_headers(_raw_header(suffix, content, sheet))

    try:
        if suffix == ".csv":
            # Survey exports are frequently UTF-8 with a BOM from Excel.
            df = pd.read_csv(io.BytesIO(content), encoding="utf-8-sig", dtype=object)
        else:
            df = pd.read_excel(io.BytesIO(content), sheet_name=sheet, dtype=object)
    except Exception as exc:  # noqa: BLE001 -- surface the parser's own words
        raise IngestError(f"Couldn't read the file: {exc}") from exc

    if df.empty:
        raise IngestError("That file has no rows.")
    return _clean_frame(df)


def list_sheets(filename: str, content: bytes) -> list[str]:
    """Excel workbooks often carry the data on a sheet other than the first;
    the old wizard silently took sheet 0 and gave no way to choose."""
    if Path(filename).suffix.lower() not in {".xlsx", ".xls"}:
        return []
    return list(pd.ExcelFile(io.BytesIO(content)).sheet_names)


def _raw_header(suffix: str, content: bytes, sheet: str | int) -> list[str]:
    try:
        if suffix == ".csv":
            text = content.decode("utf-8-sig", errors="replace")
            row = next(csv.reader(io.StringIO(text)), [])
        else:
            head = pd.read_excel(
                io.BytesIO(content), sheet_name=sheet, header=None, nrows=1, dtype=object
            )
            row = ["" if pd.isna(v) else v for v in head.iloc[0].tolist()]
    except Exception:  # noqa: BLE001 -- the real read below reports properly
        return []
    return [str(c).strip() for c in row]


def _reject_duplicate_headers(names: list[str]) -> None:
    dupes = _duplicate_names([n for n in names if n])
    if dupes:
        raise IngestError(
            "Two or more columns share the same header, so they can't be told "
            f"apart: {', '.join(d[:60] for d in dupes[:3])}"
        )


def _clean_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Strip whitespace from headers and values. Value matching throughout the
    app is on the string form, so trailing spaces would otherwise split a
    category in two -- one of the silent failures in the existing wizard."""
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]

    for col in df.columns:
        if df[col].dtype == object:
            df[col] = df[col].map(lambda v: v.strip() if isinstance(v, str) else v)
    return df


def _duplicate_names(names: list[str]) -> list[str]:
    seen: set[str] = set()
    dupes: list[str] = []
    for n in names:
        if n in seen and n not in dupes:
            dupes.append(n)
        seen.add(n)
    return dupes


def summarise(df: pd.DataFrame) -> dict:
    """What the Data screen reports back after an upload."""
    specs = build_variables(df)
    weights = inspect_weights(df)
    by_kind: dict[str, int] = {}
    for s in specs:
        by_kind[s.kind] = by_kind.get(s.kind, 0) + 1

    # Questions are what a user counts. Multi-punch options and matrix items are
    # also offered individually, so the raw variable count exceeds the column
    # count and is a confusing thing to report on its own.
    question_kinds = {"single", "multi", "matrix_group", "numeric"}
    n_questions = sum(1 for s in specs if s.kind in question_kinds)
    return {
        "n_questions": n_questions,
        "weight_column": weights.column or "",
        "weight_warnings": weights.warnings,
        "effectively_unweighted": weights.effectively_unweighted,
        "n_rows": int(len(df)),
        "n_columns": int(len(df.columns)),
        "header_style": detect_header_style(list(df.columns)),
        "n_variables": len(specs),
        "by_kind": by_kind,
        "flagged": [
            {"var_key": s.var_key, "label": s.label, "notes": s.notes}
            for s in specs
            if s.notes and s.kind != "text"
        ],
    }
