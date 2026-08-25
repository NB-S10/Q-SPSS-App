"""SQLite engine plus the pragmatic PRAGMA-based migration pattern from the
Omni App (omni_intake/backend/db.py) -- no Alembic needed at this scale."""
from __future__ import annotations

from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine

from app.config import DB_PATH

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},
)


def init_db() -> None:
    import app.models  # noqa: F401  -- register tables before create_all

    SQLModel.metadata.create_all(engine)
    _migrate_schema()


def _column_exists(table_name: str, column_name: str) -> bool:
    with engine.connect() as conn:
        rows = conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
    return any(row[1] == column_name for row in rows)


def _migrate_schema() -> None:
    """Append (table, column, DDL) triples here as the schema grows.
    Each runs only if the column is absent, so this is safe to re-run."""
    migrations: list[tuple[str, str, str]] = [
        ("variable", "category_order", "ALTER TABLE variable ADD COLUMN category_order JSON"),
        ("variable", "order_rule", "ALTER TABLE variable ADD COLUMN order_rule TEXT DEFAULT 'data'"),
        ("dataset", "weight_column", "ALTER TABLE dataset ADD COLUMN weight_column TEXT DEFAULT ''"),
        ("variable", "base_columns", "ALTER TABLE variable ADD COLUMN base_columns JSON"),
    ]

    with engine.begin() as conn:
        for table_name, column_name, statement in migrations:
            if not _column_exists(table_name, column_name):
                conn.execute(text(statement))


def get_session():
    with Session(engine) as session:
        yield session
