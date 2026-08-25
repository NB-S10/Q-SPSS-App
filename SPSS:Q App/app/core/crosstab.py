"""The crosstab engine.

One function computes one canonical table, which the UI renders and both
exporters consume. Nothing recomputes per output format.

The part that goes wrong in every home-made tables tool is the base. Rules here:

* A respondent is in the base for a question if they answered it. For a single
  response that means a non-missing value; for a multi-punch it means at least
  one option selected. It is never the number of selections -- a 3-punch answer
  is one respondent, so multi-punch columns legitimately sum past 100%.
* Categories marked as missing codes ("Don't know", "Prefer not to say") are
  excluded from the base when the base rule is "valid", which changes every
  percentage in the table. So the base is reported on every table, both
  unweighted and weighted, and it is recomputed per banner column -- a
  respondent can be in the base for one column and not another.
* Weighting is not a separate code path. Unweighted means a vector of 1s, so
  there is one set of arithmetic and no chance of the two drifting apart.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

import numpy as np
import pandas as pd

from app.core.headers import parse_header
from app.core.ordering import normalise
from app.core.variables import UNSELECTED, is_missing_token


class TableSpecError(ValueError):
    """The table asks for something that can't be resolved. Always raised rather
    than skipped: a silently dropped filter returns unfiltered numbers that look
    filtered, which is how wrong figures get published."""


class VariableLike(Protocol):
    """What the engine needs from a variable. Satisfied by the DB model and by
    the import-time VariableSpec, so tests don't need a database."""

    var_key: str
    label: str
    kind: str
    columns: list[str]
    base_columns: list[str]
    value_labels: dict[str, str]
    category_order: list[str]
    missing_codes: list[str]


@dataclass
class VariableView:
    """A variable resolved against a dataframe: one boolean mask per category,
    plus the mask of respondents who answered at all."""

    var_key: str
    label: str
    kind: str
    categories: list[str]
    masks: dict[str, np.ndarray]
    base_mask: np.ndarray
    excluded: list[str] = field(default_factory=list)

    @property
    def is_multi(self) -> bool:
        return self.kind == "multi"


def _selected(series: pd.Series) -> np.ndarray:
    """Multi-punch selection: a value that is present and doesn't say "no"."""
    def one(v: Any) -> bool:
        if is_missing_token(v):
            return False
        return normalise(v) not in UNSELECTED

    return series.map(one).to_numpy(dtype=bool)


def build_view(
    variable: VariableLike,
    df: pd.DataFrame,
    base_rule: str = "valid",
    extra_excluded: list[str] | None = None,
) -> VariableView:
    """Resolve a variable into category masks against this dataframe.

    `extra_excluded` are categories dropped for this table only, on top of the
    variable's own missing codes. This is how an Excel PivotTable behaves when
    you untick an item in a field filter: the records go, and everything
    rebases. (Excel's opposite behaviour -- keeping filtered items in the totals
    -- is a non-default OLAP-only setting, and Excel flags such totals with an
    asterisk.)
    """
    n = len(df)
    excluded = list(variable.missing_codes or []) if base_rule == "valid" else []
    if extra_excluded:
        excluded = list(dict.fromkeys([*excluded, *extra_excluded]))
    ordered = list(variable.category_order or variable.value_labels or [])

    masks: dict[str, np.ndarray] = {}

    if variable.kind == "multi_item":
        # One option of a multi-punch, on its own. Selected against the whole
        # question's base -- everyone who answered it -- so this reads the same
        # as the option's row in the combined table. Basing it on the option's
        # own column would make it 100% by construction.
        selected = _selected(df[variable.columns[0]])
        group = getattr(variable, "base_columns", None) or variable.columns
        answered = np.logical_or.reduce([_selected(df[c]) for c in group])
        masks = {"Selected": selected, "Not selected": answered & ~selected}
        categories = [c for c in (ordered or ["Selected", "Not selected"]) if c in masks]
        return VariableView(
            var_key=variable.var_key,
            label=variable.label,
            kind=variable.kind,
            categories=categories,
            masks=masks,
            base_mask=answered,
            excluded=[],
        )

    if variable.kind == "multi":
        # One column per option. The category name comes from the column header,
        # not from the data: an option nobody selected has no value to read, and
        # a column of blanks would otherwise get no label at all.
        label_for = {col: (parse_header(col).option_text or str(col))
                     for col in variable.columns}
        for col in variable.columns:
            masks[label_for[col]] = _selected(df[col])
        if not ordered:
            ordered = [label_for[c] for c in variable.columns]
    else:
        column = variable.columns[0]
        values = df[column].map(lambda x: None if is_missing_token(x) else str(x).strip())
        as_array = values.to_numpy(dtype=object)
        for category in ordered:
            masks[category] = as_array == category

    categories = [c for c in ordered if c in masks]
    # Anything present in the data but missing from the declared order still has
    # to appear, or the table silently drops respondents.
    categories += [c for c in masks if c not in categories]

    if variable.kind == "multi":
        counted = [masks[c] for c in categories if c not in excluded]
        base = np.logical_or.reduce(counted) if counted else np.zeros(n, dtype=bool)
    else:
        counted = [masks[c] for c in categories if c not in excluded]
        base = np.logical_or.reduce(counted) if counted else np.zeros(n, dtype=bool)

    return VariableView(
        var_key=variable.var_key,
        label=variable.label,
        kind=variable.kind,
        categories=categories,
        masks=masks,
        base_mask=base,
        excluded=[c for c in excluded if c in masks],
    )


# ---------------------------------------------------------------- banner


@dataclass
class BannerColumn:
    key: str
    group: str      # the banner variable's label; "" for the Total column
    label: str
    mask: np.ndarray
    letter: str = ""


def column_letters(count: int) -> list[str]:
    """Significance-marker letters: a..z then aa, ab, ... A banner wider than 26
    columns is unusual but recycling letters would make the markers ambiguous."""
    letters = []
    for i in range(count):
        label, n = "", i
        while True:
            label = chr(ord("a") + n % 26) + label
            n = n // 26 - 1
            if n < 0:
                break
        letters.append(label)
    return letters


def build_banner(
    groups: list[dict[str, Any]],
    views: dict[str, VariableView],
    n_rows: int,
    include_total: bool = True,
) -> list[BannerColumn]:
    """Turn banner group definitions into flat columns.

    A banner group is a variable plus the categories to show as columns. Groups
    sit side by side, so the same respondent appears once in each group's
    columns -- and more than once within a group if the banner variable is
    multi-punch.
    """
    columns: list[BannerColumn] = []
    if include_total:
        columns.append(
            BannerColumn(key="total", group="", label="Total",
                         mask=np.ones(n_rows, dtype=bool))
        )

    for group in groups:
        view = views.get(group["var_key"])
        if view is None:
            raise TableSpecError(
                f"Banner variable \"{group['var_key']}\" isn't in this dataset"
            )
        wanted = group.get("categories") or view.categories
        for category in wanted:
            mask = view.masks.get(category)
            if mask is None:
                raise TableSpecError(
                    f'"{category}" is not a category of {view.label!r}'
                )
            columns.append(
                BannerColumn(
                    key=f"{view.var_key}::{category}",
                    group=view.label,
                    label=category,
                    mask=mask,
                )
            )

    # Letters are assigned only to the comparison columns, not to Total.
    comparison = [c for c in columns if c.key != "total"]
    for column, letter in zip(comparison, column_letters(len(comparison))):
        column.letter = letter
    return columns


def build_filter_mask(
    clauses: list[dict[str, Any]], views: dict[str, VariableView], n_rows: int
) -> tuple[np.ndarray, list[str]]:
    """Combine filter clauses with AND, each clause being a variable and the
    categories to keep. Ported from the browser app's IfFilter."""
    mask = np.ones(n_rows, dtype=bool)
    described: list[str] = []
    for clause in clauses or []:
        key = clause.get("var_key")
        view = views.get(key)
        if view is None:
            raise TableSpecError(f'Filter variable "{key}" isn\'t in this dataset')
        categories = clause.get("categories") or []
        if not categories:
            raise TableSpecError(
                f"The filter on {view.label!r} lists no categories, so it would "
                f"keep everybody. Remove it or choose categories."
            )
        unknown = [c for c in categories if c not in view.masks]
        if unknown:
            raise TableSpecError(
                f"Not a category of {view.label!r}: {', '.join(unknown[:3])}"
            )
        mask &= np.logical_or.reduce([view.masks[c] for c in categories])
        described.append(f"{view.label}: {', '.join(categories)}")
    return mask, described


# ---------------------------------------------------------------- the table


def _sum(weights: np.ndarray, mask: np.ndarray) -> float:
    return float(weights[mask].sum())


def compute_block(
    view: VariableView,
    columns: list[BannerColumn],
    weights: np.ndarray,
    scope: np.ndarray,
    show_categories: list[str] | None = None,
    dropped: list[str] | None = None,
) -> dict[str, Any]:
    """One row variable against the whole banner.

    `scope` is the filter mask. Bases are computed per column here rather than
    once for the table, because whether a respondent is in the base depends on
    the row variable as well as the column.

    Two different ways of taking a category out, which must not be conflated:

    `dropped`     the category is gone and the base rebases without it, so the
                  remaining percentages still sum to 100%. This is what an Excel
                  pivot does when you untick an item, and it is the default.
    `show_categories`
                  the category is merely not displayed. The base is untouched,
                  so the rows you keep sum to less than 100%. Useful when a table
                  has to stay comparable with others on the same base.
    """
    ones = np.ones_like(weights)

    base_masks = [view.base_mask & scope & column.mask for column in columns]
    bases_weighted = [_sum(weights, m) for m in base_masks]
    bases_unweighted = [_sum(ones, m) for m in base_masks]

    dropped = dropped or []
    if show_categories is not None:
        unknown = [c for c in show_categories if c not in view.masks]
        if unknown:
            raise TableSpecError(
                f"Not a category of {view.label!r}: {', '.join(unknown[:3])}"
            )
        visible = [c for c in view.categories
                   if c in set(show_categories) and c not in dropped]
        if not visible:
            raise TableSpecError(
                f"Every category of {view.label!r} is hidden, so there is nothing "
                f"to show. Tick at least one."
            )
    else:
        # Dropped categories are gone from the table, not greyed out: the base
        # already excludes them, so showing an empty row would only confuse.
        visible = [c for c in view.categories if c not in dropped]

    rows: list[dict[str, Any]] = []
    for category in visible:
        cat_mask = view.masks[category]
        cells: list[dict[str, Any]] = []
        for index, column in enumerate(columns):
            selected = cat_mask & base_masks[index]
            weighted = _sum(weights, selected)
            base = bases_weighted[index]
            cells.append({
                "count": weighted,
                "count_unweighted": _sum(ones, selected),
                "col_pct": (weighted / base) if base else None,
                "base": base,
                "base_unweighted": bases_unweighted[index],
            })

        # Row percentages distribute one row category across a banner group. The
        # Total column is excluded: it would always be 100% and its inclusion
        # would halve every other figure.
        for group_name in {c.group for c in columns if c.group}:
            indices = [i for i, c in enumerate(columns) if c.group == group_name]
            group_total = sum(cells[i]["count"] for i in indices)
            for i in indices:
                cells[i]["row_pct"] = (
                    cells[i]["count"] / group_total if group_total else None
                )

        total_pct = cells[0]["col_pct"] if columns and columns[0].key == "total" else None
        for cell in cells:
            cell.setdefault("row_pct", None)
            # Index: this column against the table total, 100 = no difference.
            cell["index"] = (
                round(cell["col_pct"] / total_pct * 100)
                if (total_pct and cell["col_pct"] is not None)
                else None
            )

        rows.append({
            "label": category,
            "excluded": category in view.excluded,
            "cells": cells,
        })

    return {
        "var_key": view.var_key,
        "label": view.label,
        "kind": view.kind,
        "is_multi": view.is_multi,
        "excluded_categories": [c for c in view.excluded if c not in dropped],
        "dropped_categories": [c for c in dropped if c in view.masks],
        "hidden_categories": [
            c for c in view.categories if c not in visible and c not in dropped
        ],
        "all_categories": list(view.categories),
        "bases_weighted": bases_weighted,
        "bases_unweighted": bases_unweighted,
        "rows": rows,
    }


def compute_table(
    df: pd.DataFrame,
    row_variables: list[VariableLike],
    banner_groups: list[dict[str, Any]],
    banner_variables: list[VariableLike],
    weights: np.ndarray,
    filter_clauses: list[dict[str, Any]] | None = None,
    filter_variables: list[VariableLike] | None = None,
    base_rule: str = "valid",
    row_categories: dict[str, list[str]] | None = None,
    row_exclusions: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """The whole table: one block per row variable, sharing one banner.

    Filter variables must be passed in as well as named in the clauses -- the
    engine resolves masks against the dataframe and cannot invent a variable it
    hasn't been given.
    """
    n = len(df)
    if weights.shape[0] != n:
        raise ValueError("The weight vector doesn't match the number of rows")
    if not row_variables:
        raise TableSpecError("A table needs at least one row variable")

    # Banner and filter views never carry a row variable's exclusions: excluding
    # "Don't know" from one question must not silently redefine the same variable
    # where it is being used as a column.
    views: dict[str, VariableView] = {}
    for variable in [*banner_variables, *(filter_variables or [])]:
        if variable.var_key not in views:
            views[variable.var_key] = build_view(variable, df, base_rule)

    columns = build_banner(banner_groups, views, n)
    scope, filter_description = build_filter_mask(filter_clauses or [], views, n)

    blocks = []
    for variable in row_variables:
        dropped = (row_exclusions or {}).get(variable.var_key) or []
        unknown = [c for c in dropped if c not in (variable.value_labels or {})]
        if unknown:
            raise TableSpecError(
                f"Not a category of {variable.label!r}: {', '.join(unknown[:3])}"
            )
        view = build_view(variable, df, base_rule, extra_excluded=dropped)
        if not [c for c in view.categories if c not in dropped]:
            raise TableSpecError(
                f"Every category of {variable.label!r} has been removed, so there "
                f"is nothing to show."
            )
        blocks.append(
            compute_block(
                view, columns, weights, scope,
                show_categories=(row_categories or {}).get(variable.var_key),
                dropped=dropped,
            )
        )

    return {
        "columns": [
            {"key": c.key, "group": c.group, "label": c.label, "letter": c.letter}
            for c in columns
        ],
        "blocks": blocks,
        "base_rule": base_rule,
        "filter": filter_description,
        "n_filtered": int(scope.sum()),
        "n_total": n,
    }
