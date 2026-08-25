"""Dataset files on disk. Respondent-level data lives in Parquet, never in
SQLite -- SQLite holds only the project metadata that describes it."""
from __future__ import annotations

import uuid
from pathlib import Path

import pandas as pd

from app.config import DATASET_DIR


def new_parquet_path(dataset_name: str) -> Path:
    """A collision-proof path. The human name lives in the database, so the
    filename only needs to be unique and roughly recognisable."""
    stem = "".join(c if c.isalnum() else "_" for c in dataset_name)[:40].strip("_")
    return DATASET_DIR / f"{stem or 'dataset'}_{uuid.uuid4().hex[:8]}.parquet"


def write_frame(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)


def read_frame(path: str | Path, columns: list[str] | None = None) -> pd.DataFrame:
    return pd.read_parquet(path, columns=columns)


def delete_frame(path: str | Path) -> None:
    Path(path).unlink(missing_ok=True)
