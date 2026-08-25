"""Deciding what weight a table is computed on.

Most files arrive already weighted, carrying a `weight_demog` column from the
supplier or from the weighting wizard. In that case there is nothing to compute:
the column is used as-is. Raking is only needed when no weight is present.

Three modes:

    "column"      use a weight column already in the data (the normal case)
    "unweighted"  every respondent counts 1
    "scheme"      use a weight computed in this app (not built yet)

Every mode returns a plain float array the length of the dataframe, so the
crosstab engine has exactly one code path and never branches on whether the data
is weighted.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from app.config import DEFAULT_WEIGHT_COLUMN

# Anything named like a weight. `weight_demog` is the house convention and wins.
WEIGHT_NAME_HINTS = ("weight", "wt", "wgt")


@dataclass
class WeightInfo:
    """What we know about a dataset's weighting before any table is built."""

    column: str | None
    candidates: list[str] = field(default_factory=list)
    n_valid: int = 0
    n_invalid: int = 0
    effectively_unweighted: bool = False
    warnings: list[str] = field(default_factory=list)

    @property
    def has_weight(self) -> bool:
        return bool(self.column)


def find_weight_candidates(columns: list[str]) -> list[str]:
    """Weight-looking columns, house convention first."""
    hits = [
        c for c in columns
        if any(h in str(c).lower() for h in WEIGHT_NAME_HINTS)
    ]
    hits.sort(key=lambda c: (str(c) != DEFAULT_WEIGHT_COLUMN, str(c).lower()))
    return hits


def inspect_weights(df: pd.DataFrame) -> WeightInfo:
    """Find and sanity-check the dataset's weight column."""
    candidates = find_weight_candidates(list(df.columns))
    if not candidates:
        return WeightInfo(column=None, candidates=[])

    column = candidates[0]
    values = pd.to_numeric(df[column], errors="coerce")
    valid = values.notna() & (values > 0)

    info = WeightInfo(
        column=column,
        candidates=candidates,
        n_valid=int(valid.sum()),
        n_invalid=int((~valid).sum()),
    )

    if info.n_valid == 0:
        info.warnings.append(
            f'"{column}" has no usable values, so it can\'t be used as a weight.'
        )
        info.column = None
        return info

    if info.n_invalid:
        info.warnings.append(
            f"{info.n_invalid} of {len(df)} rows have a missing, zero or negative "
            f'"{column}" and would be excluded from weighted tables.'
        )

    # A weight column of all 1s means the file was exported unweighted. Worth
    # saying so rather than presenting it as a weighted dataset.
    if np.allclose(values[valid].to_numpy(dtype=float), 1.0):
        info.effectively_unweighted = True
        info.warnings.append(
            f'Every value in "{column}" is 1, so this data is effectively unweighted.'
        )

    if len(candidates) > 1:
        info.warnings.append(
            f"More than one weight-looking column: {', '.join(candidates)}. "
            f'Using "{column}".'
        )
    return info


def resolve_weights(
    df: pd.DataFrame, mode: str = "column", column: str | None = None
) -> np.ndarray:
    """The weight vector for a table. Invalid weights become 0 rather than
    dropping rows, so the array always aligns with the dataframe's index."""
    n = len(df)
    if mode == "unweighted":
        return np.ones(n, dtype=float)

    if mode == "column":
        name = column or DEFAULT_WEIGHT_COLUMN
        if name not in df.columns:
            raise KeyError(f'No column called "{name}" in this dataset')
        # copy(): a Parquet-backed column yields a read-only array.
        values = pd.to_numeric(df[name], errors="coerce").to_numpy(dtype=float).copy()
        values[~np.isfinite(values)] = 0.0
        values[values < 0] = 0.0
        return values

    raise ValueError(f'Unknown weight mode "{mode}"')


def kish_effective_base(weights: np.ndarray) -> float:
    """Kish's effective sample size, (sum w)^2 / sum(w^2).

    This is the n that significance tests must use on weighted data. Using the
    weighted base instead makes every test anti-conservative -- the mistake the
    existing R tables app makes.
    """
    w = np.asarray(weights, dtype=float)
    w = w[np.isfinite(w) & (w > 0)]
    if w.size == 0:
        return 0.0
    total = w.sum()
    return float(total * total / np.square(w).sum())


def weighting_efficiency(weights: np.ndarray) -> dict[str, float]:
    """Kish diagnostics. Lifted from the weighting wizard
    (weighting_wizard_shareable/app.py:312), which had these right.

    Adds percentile reporting, because a single efficiency figure hides the one
    respondent carrying a weight of 40.
    """
    w = np.asarray(weights, dtype=float)
    w = w[np.isfinite(w) & (w > 0)]
    n = float(w.size)
    if n == 0:
        return {}
    sum_w = float(w.sum())
    sum_w_sq = float(np.square(w).sum())
    effective_n = sum_w * sum_w / sum_w_sq
    mean_w = sum_w / n
    sd_w = float(np.std(w, ddof=1)) if n > 1 else 0.0
    return {
        "n": n,
        "sum_weights": sum_w,
        "design_effect": n * sum_w_sq / (sum_w * sum_w),
        "effective_base": effective_n,
        "efficiency_percent": effective_n / n * 100.0,
        "min_weight": float(w.min()),
        "max_weight": float(w.max()),
        "mean_weight": mean_w,
        "sd_weight": sd_w,
        "cv_percent": (sd_w / mean_w * 100.0) if mean_w else 0.0,
        "p1": float(np.percentile(w, 1)),
        "p99": float(np.percentile(w, 99)),
    }


# House banding, merged from the wizard's two duplicate implementations
# (classify_efficiency_level and get_efficiency_level_details).
EFFICIENCY_BANDS = ((90, "Excellent"), (80, "Good"), (70, "Acceptable"), (60, "Poor"))


def classify_efficiency(efficiency_percent: float) -> str:
    for threshold, label in EFFICIENCY_BANDS:
        if efficiency_percent >= threshold:
            return label
    return "Very poor"
