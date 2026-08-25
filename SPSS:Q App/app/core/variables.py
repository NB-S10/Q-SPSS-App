"""Turn a flat wide export into a list of analysable variables.

This is the layer that makes the rest of the app possible: a spreadsheet column
is not a question. A multi-punch block is eight columns but one variable; a
matrix is one parent with N items; an "Other (please specify)" follow-up is a
text column that must not be mistaken for a response option.

Ported from Apps/Regression App/app.js:179-303 (buildQuestionEntries,
classifyGroup) and app.js:85-123 (VarClassifier.classify), with three fixes that
real Alchemer exports force:

1. Specify/describe columns are split out before a group is classified.
   Without this, "What is your ethnic group?" (one single-response column plus
   five free-text follow-ups) is misread as a matrix.
2. Empty columns are tolerated. Routed questions nobody reached export as fully
   blank columns, and a group of those has no distinct values to classify on.
3. A group can mix a 1-colon header (the question) with 2-colon headers (its
   specify follow-ups); the 1-colon column is the real variable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from app.config import DEFAULT_WEIGHT_COLUMN, MISSING_TOKENS
from app.core.headers import parse_header
from app.core.ordering import suggest_order

# Above this many distinct values, a column is free text rather than a category.
MAX_CATEGORY_LEVELS = 30

# Values meaning "this option was not selected", on top of blank. Alchemer
# writes the option label when picked and nothing when not, but exports from
# elsewhere code the same thing as 0 / No / False.
UNSELECTED = frozenset({"0", "no", "false", "not selected", "unselected", "off", "n"})


@dataclass
class VariableSpec:
    var_key: str
    label: str
    kind: str  # single | multi | multi_item | matrix_group | matrix_item | numeric | text | meta
    columns: list[str]
    code: str = ""
    # For one option of a multi-punch: the whole group's columns, so its base is
    # everyone who answered the question rather than everyone who picked this
    # option. Without it a single option would always read 100%.
    base_columns: list[str] = field(default_factory=list)
    order_index: int = 0
    parent_key: str | None = None
    value_labels: dict[str, str] = field(default_factory=dict)
    category_order: list[str] = field(default_factory=list)
    order_rule: str = "data"
    notes: list[str] = field(default_factory=list)

    def to_row(self) -> dict[str, Any]:
        return {
            "var_key": self.var_key,
            "code": self.code,
            "label": self.label,
            "kind": self.kind,
            "columns": list(self.columns),
            "base_columns": list(self.base_columns),
            "value_labels": dict(self.value_labels),
            "category_order": list(self.category_order),
            "order_rule": self.order_rule,
            "order_index": self.order_index,
            "notes": list(self.notes),
            "parent_key": self.parent_key,
        }


def is_missing_token(value: Any) -> bool:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return True
    return str(value).strip().lower() in MISSING_TOKENS


def clean_series(series: pd.Series) -> pd.Series:
    """Drop missing-like values so counts and level detection ignore them."""
    mask = series.map(is_missing_token)
    return series[~mask.astype(bool)]


def distinct_values(series: pd.Series) -> list[str]:
    """Distinct non-missing values in order of first appearance.

    Note this is NOT questionnaire order. Alchemer exports the response text
    only, so the order here is whatever the first few respondents happened to
    pick -- a scale can come back as "Very favourable, Don't know, Slightly
    favourable". Crosstab rows therefore need an explicit category order, set on
    the Variables screen (or read from an order file), before tables are
    presentable. Tracked as a known gap, not a bug in this function.
    """
    seen: dict[str, None] = {}
    for value in clean_series(series):
        seen.setdefault(str(value).strip(), None)
    return list(seen)


def _looks_numeric(values: list[str]) -> bool:
    if not values:
        return False
    ok = 0
    for v in values:
        try:
            float(v.replace(",", ""))
            ok += 1
        except ValueError:
            pass
    return ok / len(values) >= 0.9


def classify_column(series: pd.Series) -> tuple[str, list[str]]:
    """Type a single column from its contents. Returns (kind, distinct values).
    Port of VarClassifier.classify with the level cap raised -- real demographic
    questions such as region or ethnicity exceed the original 20."""
    values = distinct_values(series)
    if not values:
        return "empty", []
    if _looks_numeric(values) and len(values) > MAX_CATEGORY_LEVELS:
        return "numeric", values
    if len(values) > MAX_CATEGORY_LEVELS:
        return "text", values
    return "single", values


def build_variables(df: pd.DataFrame) -> list[VariableSpec]:
    """The variable tree for a whole dataframe, in column order."""
    headers = [(col, parse_header(str(col))) for col in df.columns]

    # Preserve first-appearance order of codes so the tree follows the
    # questionnaire rather than an alphabetical sort.
    groups: dict[str, list[tuple[str, Any]]] = {}
    metas: list[tuple[str, Any]] = []
    for col, meta in headers:
        if meta.is_meta:
            metas.append((col, meta))
        else:
            groups.setdefault(meta.code, []).append((col, meta))

    specs: list[VariableSpec] = []
    for col, meta in metas:
        kind = "weight" if col == DEFAULT_WEIGHT_COLUMN else "meta"
        specs.append(
            VariableSpec(
                var_key=f"meta:{col}",
                label=meta.question_text or col,
                kind=kind,
                columns=[col],
            )
        )

    for code, members in groups.items():
        specs.extend(_build_group(code, members, df))

    for index, spec in enumerate(specs):
        spec.order_index = index
        # Suggest a category order once, at import. The user's later dragging
        # overwrites this and sets order_rule to "user".
        if spec.value_labels and not spec.category_order:
            spec.category_order, spec.order_rule = suggest_order(list(spec.value_labels))
    return specs


def _build_group(code: str, members: list[tuple[str, Any]], df: pd.DataFrame) -> list[VariableSpec]:
    core = [(c, m) for c, m in members if not m.is_specify]
    specify = [(c, m) for c, m in members if m.is_specify]

    out: list[VariableSpec] = []
    question = next((m.question_text for _, m in members if m.question_text), code)

    if not core:
        # Everything in the group was a free-text follow-up.
        out.extend(_specify_specs(code, specify, question))
        return out

    if len(core) == 1:
        col, meta = core[0]
        kind, values = classify_column(df[col])
        label = meta.question_text or meta.option_text or col
        spec = VariableSpec(
            var_key=f"{'single' if kind == 'single' else kind}:{code}",
            label=label,
            kind=kind,
            columns=[col],
            code=code,
            value_labels={v: v for v in values} if kind == "single" else {},
        )
        if kind == "empty":
            spec.notes.append("No responses in this column")
        out.append(spec)
        out.extend(_specify_specs(code, specify, question))
        return out

    # Several response columns sharing one code: multi-punch or matrix.
    value_sets = [distinct_values(df[c]) for c, _ in core]
    level_counts = [len(v) for v in value_sets]
    answered = [n for n in level_counts if n > 0]

    if not answered:
        group = VariableSpec(
            var_key=f"multi:{code}",
            label=question,
            kind="multi",
            columns=[c for c, _ in core],
            code=code,
            notes=["No responses to any option -- routed question, or nobody reached it"],
        )
        out.append(group)
        out.extend(_specify_specs(code, specify, question))
        return out

    if max(answered) <= 1 or _looks_like_binary_multi(core, value_sets):
        # Each column carries at most its own option label: multi-punch.
        labels = {}
        for col, meta in core:
            option = meta.option_text or str(col)
            labels[option] = option
        group_columns = [c for c, _ in core]
        parent_key = f"multi:{code}"
        out.append(
            VariableSpec(
                var_key=parent_key,
                label=question,
                kind="multi",
                columns=group_columns,
                code=code,
                value_labels=labels,
            )
        )
        # Each option is also offered on its own, so a single option can be
        # tabulated or used as a column. Its percentage matches the combined
        # table's figure for that option, because it shares the group's base.
        for col, meta in core:
            option = meta.option_text or str(col)
            out.append(
                VariableSpec(
                    var_key=f"multi_item:{code}:{option}",
                    label=option,
                    kind="multi_item",
                    columns=[col],
                    base_columns=list(group_columns),
                    code=code,
                    parent_key=parent_key,
                    value_labels={"Selected": "Selected", "Not selected": "Not selected"},
                    category_order=["Selected", "Not selected"],
                    order_rule="scale",
                )
            )
    else:
        # Each column holds a full scale: a matrix. Parent plus one item each.
        parent_key = f"matrix:{code}"
        out.append(
            VariableSpec(
                var_key=parent_key,
                label=question,
                kind="matrix_group",
                columns=[c for c, _ in core],
                code=code,
            )
        )
        for col, meta in core:
            values = distinct_values(df[col])
            item = VariableSpec(
                var_key=f"matrix_item:{code}:{meta.option_text or col}",
                label=meta.option_text or str(col),
                kind="matrix_item",
                columns=[col],
                code=code,
                parent_key=parent_key,
                value_labels={v: v for v in values},
            )
            if not values:
                item.notes.append("No responses in this column")
            out.append(item)

    out.extend(_specify_specs(code, specify, question))
    return out


def _looks_like_binary_multi(core, value_sets: list[list[str]]) -> bool:
    """Recognise a multi-punch coded as selected/not-selected rather than as
    blank-or-label: "Apples"/"No", or 1/0. Such a column holds two distinct
    values, which would otherwise be misread as a two-point matrix scale.

    The test is on the value CONTENT, not how many distinct values there are:
    every value must be either the column's own option label or a
    selected/unselected token. A real two-point matrix ("Agree"/"Disagree")
    fails that test because neither value is a selection token, so it stays a
    matrix. The small cap only guards against pathological columns.
    """
    from app.core.ordering import normalise

    selected_tokens = {"1", "yes", "true", "selected", "y", "checked"}
    for (_col, meta), values in zip(core, value_sets):
        if len(values) > 4:
            return False
        option = normalise(meta.option_text or "")
        for value in values:
            v = normalise(value)
            if v in UNSELECTED or v in selected_tokens:
                continue
            if option and v == option:
                continue
            return False
    return True


def _specify_specs(code: str, specify, question: str) -> list[VariableSpec]:
    """Free-text follow-ups become their own text variables, kept beside the
    question they belong to but never treated as response options."""
    out = []
    for col, meta in specify:
        out.append(
            VariableSpec(
                var_key=f"text:{code}:{meta.option_text or col}",
                label=f"{meta.option_text or col}".strip(),
                kind="text",
                columns=[col],
                code=code,
                parent_key=None,
                notes=[f"Free text follow-up to: {question[:70]}"],
            )
        )
    return out
