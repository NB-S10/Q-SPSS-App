"""Point the app at a throwaway database and data directory BEFORE anything
imports app.config, which resolves both at import time. Without this, running
the suite writes test rows into the real project database."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="spssq-tests-"))
os.environ["SPSSQ_DATA_DIR"] = str(_tmp)
os.environ["SPSSQ_DB_PATH"] = str(_tmp / "test.db")
