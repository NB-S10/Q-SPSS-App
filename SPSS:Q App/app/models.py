"""Persistence model.

The key idea, and the thing that makes this behave like Q rather than pandas,
is that a raw spreadsheet column is not a variable. A Variable owns one or more
columns, carries its own labels, missing codes and nets, and is the unit every
other screen refers to.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _json_field(default_factory):
    return Field(default_factory=default_factory, sa_column=Column(JSON))


class Project(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    notes: str = ""
    created_at: datetime = Field(default_factory=_now)


class Dataset(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    name: str
    source_filename: str
    parquet_path: str
    n_rows: int = 0
    n_columns: int = 0
    # "alchemer" when colon-delimited headers were detected, else "generic".
    header_style: str = "generic"
    # The weight column found in the file, empty when there isn't one. Most
    # supplier files arrive already weighted, in which case no raking is needed.
    weight_column: str = ""
    created_at: datetime = Field(default_factory=_now)


class Variable(SQLModel, table=True):
    """One analysable question. `columns` holds the underlying dataframe column
    names -- more than one for multi-punch and matrix groups."""

    id: int | None = Field(default=None, primary_key=True)
    dataset_id: int = Field(foreign_key="dataset.id", index=True)
    # Stable identifier such as "single:12" or "multi:12a", survives re-import.
    var_key: str = Field(index=True)
    code: str = ""
    label: str = ""
    # single | multi | matrix_group | matrix_item | numeric | text | meta
    kind: str = "single"
    order_index: int = 0
    columns: list[str] = _json_field(list)
    # For one option of a multi-punch: every column of its question, so the
    # option is based on everyone who answered rather than on itself.
    base_columns: list[str] = _json_field(list)
    value_labels: dict[str, str] = _json_field(dict)
    # The order categories appear in as table rows or banner columns. Alchemer
    # gives no answer order, so this is suggested on import and then dragged.
    category_order: list[str] = _json_field(list)
    # Which rule produced category_order: "scale" | "numeric" | "data" | "user".
    order_rule: str = "data"
    missing_codes: list[str] = _json_field(list)
    # [{"name": "Top 2 box", "values": [...], "kind": "net"}]
    nets: list[dict[str, Any]] = _json_field(list)
    # Set on variables produced by a recode, band, or a segmentation run.
    derived_from: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))


class TargetSet(SQLModel, table=True):
    """A reusable weighting specification: the population targets plus how raw
    data values map onto them. Saved per project so a scheme is defined once and
    reloaded, rather than rebuilt from dropdowns every session."""

    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    name: str
    # [{"group": "Age", "specific": "18-24", "proportion": 0.11}]
    targets: list[dict[str, Any]] = _json_field(list)
    # {"Age": "<dataframe column name>"}
    group_column_map: dict[str, str] = _json_field(dict)
    # {"Age": {"18-24": ["18", "19", ...]}}
    value_mappings: dict[str, dict[str, list[str]]] = _json_field(dict)
    # [{"name": "AgeXGender", "columns": ["age_band", "gender"]}]
    interlocks: list[dict[str, Any]] = _json_field(list)
    created_at: datetime = Field(default_factory=_now)


class WeightScheme(SQLModel, table=True):
    """A materialised run of a TargetSet against a Dataset."""

    id: int | None = Field(default=None, primary_key=True)
    dataset_id: int = Field(foreign_key="dataset.id", index=True)
    target_set_id: int | None = Field(default=None, foreign_key="targetset.id")
    name: str
    weight_column: str = "weight_demog"
    # {"tolerance": 1e-6, "max_iterations": 200, "legacy_mode": false,
    #  "min_weight": null, "max_weight": null}
    settings: dict[str, Any] = _json_field(dict)
    # Kish efficiency, effective base, weight spread, achieved vs target, warnings.
    diagnostics: dict[str, Any] = _json_field(dict)
    converged: bool = False
    created_at: datetime = Field(default_factory=_now)


class Banner(SQLModel, table=True):
    """An ordered set of crosstab column groups."""

    id: int | None = Field(default=None, primary_key=True)
    dataset_id: int = Field(foreign_key="dataset.id", index=True)
    name: str
    # [{"var_key": "single:7", "label": "Age", "categories": [...]}]
    groups: list[dict[str, Any]] = _json_field(list)
    created_at: datetime = Field(default_factory=_now)


class SavedTable(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    name: str
    # A full TableSpec: rows, banner, weight, filter, statistics, base rule, sig.
    spec: dict[str, Any] = _json_field(dict)
    created_at: datetime = Field(default_factory=_now)
