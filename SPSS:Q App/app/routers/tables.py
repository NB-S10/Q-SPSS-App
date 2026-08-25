"""Building a table from a spec."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.core.crosstab import TableSpecError, compute_table
from app.core.weights import inspect_weights, resolve_weights
from app.db import get_session
from app.models import Dataset, Variable
from app.storage import read_frame

router = APIRouter(prefix="/api/tables", tags=["tables"])


class BannerGroup(BaseModel):
    var_key: str
    categories: list[str] = Field(default_factory=list)


class FilterClause(BaseModel):
    var_key: str
    categories: list[str] = Field(default_factory=list)


class TableSpec(BaseModel):
    dataset_id: int
    rows: list[str]
    banner: list[BannerGroup] = Field(default_factory=list)
    filters: list[FilterClause] = Field(default_factory=list)
    # var_key -> the categories to show as rows. Absent means show them all.
    # Hiding rows never changes the base; see compute_block.
    row_categories: dict[str, list[str]] = Field(default_factory=dict)
    # var_key -> categories removed from this table entirely, rebasing the
    # question without them. This is the Excel pivot behaviour and the default.
    row_exclusions: dict[str, list[str]] = Field(default_factory=dict)
    weight_mode: str = "column"          # "column" | "unweighted"
    weight_column: str | None = None
    base_rule: str = "valid"             # "valid" | "total"


@router.post("/compute")
def compute(spec: TableSpec, session: Session = Depends(get_session)) -> dict[str, Any]:
    dataset = session.get(Dataset, spec.dataset_id)
    if not dataset:
        raise HTTPException(404, "Dataset not found")

    variables = {
        v.var_key: v
        for v in session.exec(
            select(Variable).where(Variable.dataset_id == spec.dataset_id)
        ).all()
    }

    def pick(keys: list[str], what: str) -> list[Variable]:
        missing = [k for k in keys if k not in variables]
        if missing:
            raise HTTPException(422, f"{what} not in this dataset: {', '.join(missing[:3])}")
        return [variables[k] for k in keys]

    row_variables = pick(spec.rows, "Row variables")
    banner_variables = pick([g.var_key for g in spec.banner], "Banner variables")
    filter_variables = pick([f.var_key for f in spec.filters], "Filter variables")

    df = read_frame(dataset.parquet_path)

    mode = spec.weight_mode
    column = spec.weight_column or dataset.weight_column or None
    if mode == "column" and not column:
        # The stored weight column can be empty for a dataset uploaded before
        # weight detection existed, so fall back to reading the file itself
        # rather than trusting the record.
        column = inspect_weights(df).column

    notices: list[str] = []
    if mode == "column" and not column:
        # Never quietly return unweighted numbers when weighted ones were asked
        # for -- say so, loudly enough for the UI to show it on the table.
        mode = "unweighted"
        notices.append(
            "This dataset has no weight column, so the table is unweighted."
        )

    try:
        weights = resolve_weights(df, mode, column)
    except KeyError as exc:
        raise HTTPException(422, str(exc)) from exc

    try:
        table = compute_table(
            df,
            row_variables=row_variables,
            banner_groups=[g.model_dump() for g in spec.banner],
            banner_variables=banner_variables,
            weights=weights,
            filter_clauses=[f.model_dump() for f in spec.filters],
            filter_variables=filter_variables,
            base_rule=spec.base_rule,
            row_categories=spec.row_categories,
            row_exclusions=spec.row_exclusions,
        )
    except TableSpecError as exc:
        raise HTTPException(422, str(exc)) from exc

    table["weight"] = {
        "mode": mode,
        "column": column if mode == "column" else None,
        "requested_mode": spec.weight_mode,
    }
    table["notices"] = notices
    table["dataset"] = {"id": dataset.id, "name": dataset.name}
    return table
