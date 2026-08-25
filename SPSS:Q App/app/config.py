"""Runtime configuration. Everything overridable by env var so the container
needs no code changes when this moves to a shared server."""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = BASE_DIR / "web"

# DATA_DIR is the only writable location. Mount it as a volume in Docker.
DATA_DIR = Path(os.environ.get("SPSSQ_DATA_DIR", BASE_DIR / "data"))
DATASET_DIR = DATA_DIR / "datasets"
DB_PATH = Path(os.environ.get("SPSSQ_DB_PATH", DATA_DIR / "app.db"))

# House convention, hardcoded in both existing JS apps.
DEFAULT_WEIGHT_COLUMN = "weight_demog"

# Union of the two disagreeing token sets in the existing apps
# (crosstab used ['', 'NA', 'N/A', 'NULL']; regression used a lowercase superset).
# Compared case-insensitively after stripping.
MISSING_TOKENS = frozenset(
    {"", "na", "n/a", "n.a", "null", "none", "missing", "nan", "-", "."}
)

MAX_UPLOAD_MB = int(os.environ.get("SPSSQ_MAX_UPLOAD_MB", "200"))

for _d in (DATA_DIR, DATASET_DIR):
    _d.mkdir(parents=True, exist_ok=True)
