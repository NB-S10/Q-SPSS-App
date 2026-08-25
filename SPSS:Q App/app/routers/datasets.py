"""Dataset endpoints. Ingest itself lands in phase 2 -- this is the shell the
upload screen talks to."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlmodel import Session, select

from app.config import MAX_UPLOAD_MB
from app.core.ingest import IngestError, list_sheets, read_upload, summarise
from app.core.variables import build_variables
from app.core.weights import (
    classify_efficiency,
    inspect_weights,
    resolve_weights,
    weighting_efficiency,
)
from app.db import get_session
from app.models import Dataset, Project, Variable
from app.storage import delete_frame, new_parquet_path, read_frame, write_frame

router = APIRouter(prefix="/api/datasets", tags=["datasets"])


@router.post("/upload", status_code=201)
async def upload_dataset(
    project_id: int = Form(...),
    name: str = Form(""),
    sheet: str = Form(""),
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
) -> dict:
    """Read the file, derive the variable tree, and store both. The variable
    tree is saved rather than recomputed so the user's later corrections on the
    Variables screen survive."""
    if not session.get(Project, project_id):
        raise HTTPException(404, "Project not found")

    content = await file.read()
    if len(content) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"That file is over the {MAX_UPLOAD_MB}MB limit")

    try:
        df = read_upload(file.filename or "upload.csv", content, sheet=sheet or 0)
    except IngestError as exc:
        raise HTTPException(422, str(exc)) from exc

    info = summarise(df)
    path = new_parquet_path(name or file.filename or "dataset")
    write_frame(df.astype(str).where(df.notna(), None), path)

    dataset = Dataset(
        project_id=project_id,
        name=(name or file.filename or "Dataset").strip(),
        source_filename=file.filename or "",
        parquet_path=str(path),
        n_rows=info["n_rows"],
        n_columns=info["n_columns"],
        header_style=info["header_style"],
        weight_column=info["weight_column"],
    )
    session.add(dataset)
    session.commit()
    session.refresh(dataset)

    for spec in build_variables(df):
        row = spec.to_row()
        session.add(
            Variable(
                dataset_id=dataset.id,
                var_key=row["var_key"],
                code=row["code"],
                label=row["label"],
                kind=row["kind"],
                order_index=row["order_index"],
                columns=row["columns"],
                base_columns=row["base_columns"],
                value_labels=row["value_labels"],
                category_order=row["category_order"],
                order_rule=row["order_rule"],
                missing_codes=[],
                nets=[],
                derived_from={"notes": row["notes"], "parent_key": row["parent_key"]}
                if (row["notes"] or row["parent_key"])
                else None,
            )
        )
    session.commit()

    return {"id": dataset.id, "name": dataset.name, **info}


@router.post("/sheets")
async def inspect_sheets(file: UploadFile = File(...)) -> dict:
    """Sheet names, so an Excel upload can target the right one."""
    content = await file.read()
    return {"sheets": list_sheets(file.filename or "", content)}


@router.get("/{dataset_id}")
def get_dataset(dataset_id: int, session: Session = Depends(get_session)) -> dict:
    ds = session.get(Dataset, dataset_id)
    if not ds:
        raise HTTPException(404, "Dataset not found")
    _backfill_weight_column(ds, session)
    variables = session.exec(
        select(Variable).where(Variable.dataset_id == dataset_id).order_by(Variable.order_index)
    ).all()
    return {
        "id": ds.id,
        "name": ds.name,
        "source_filename": ds.source_filename,
        "n_rows": ds.n_rows,
        "n_columns": ds.n_columns,
        "header_style": ds.header_style,
        "weight_column": ds.weight_column,
        "variables": [
            {
                "id": v.id,
                "var_key": v.var_key,
                "code": v.code,
                "label": v.label,
                "kind": v.kind,
                "columns": v.columns,
                "n_columns": len(v.columns),
                "base_columns": v.base_columns or [],
                "value_labels": v.value_labels,
                "category_order": v.category_order or list(v.value_labels),
                "order_rule": v.order_rule,
                "missing_codes": v.missing_codes,
                "notes": (v.derived_from or {}).get("notes", []),
                "parent_key": (v.derived_from or {}).get("parent_key"),
            }
            for v in variables
        ],
    }


@router.get("/{dataset_id}/rows")
def get_rows(
    dataset_id: int,
    offset: int = 0,
    limit: int = 50,
    session: Session = Depends(get_session),
) -> dict:
    """A window onto the raw data for the Data screen's grid."""
    ds = session.get(Dataset, dataset_id)
    if not ds:
        raise HTTPException(404, "Dataset not found")
    limit = max(1, min(limit, 500))
    df = read_frame(ds.parquet_path)
    window = df.iloc[offset : offset + limit]
    return {
        "columns": list(df.columns),
        "rows": window.astype(object).where(window.notna(), None).values.tolist(),
        "offset": offset,
        "total": int(len(df)),
    }


def _backfill_weight_column(ds: Dataset, session: Session) -> None:
    """Fill in the weight column for datasets stored before it was recorded.
    Without this the UI reports "no weight in file" while the table is in fact
    weighted, because the engine falls back to reading the file."""
    if ds.weight_column:
        return
    found = inspect_weights(read_frame(ds.parquet_path)).column
    if found:
        ds.weight_column = found
        session.add(ds)
        session.commit()
        session.refresh(ds)


@router.get("/{dataset_id}/weights")
def get_weights(dataset_id: int, session: Session = Depends(get_session)) -> dict:
    """The dataset's weighting position: which column is used, whether it is
    usable, and how much precision it costs."""
    ds = session.get(Dataset, dataset_id)
    if not ds:
        raise HTTPException(404, "Dataset not found")

    df = read_frame(ds.parquet_path)
    info = inspect_weights(df)
    payload: dict = {
        "dataset_id": ds.id,
        "dataset_name": ds.name,
        "n_rows": ds.n_rows,
        "weight_column": info.column or "",
        "candidates": info.candidates,
        "has_weight": info.has_weight,
        "effectively_unweighted": info.effectively_unweighted,
        "n_invalid": info.n_invalid,
        "warnings": info.warnings,
        "diagnostics": None,
        "band": None,
    }
    if info.has_weight:
        eff = weighting_efficiency(resolve_weights(df, "column", info.column))
        payload["diagnostics"] = eff
        payload["band"] = classify_efficiency(eff.get("efficiency_percent", 0.0))
    return payload


@router.delete("/{dataset_id}", status_code=204)
def delete_dataset(dataset_id: int, session: Session = Depends(get_session)) -> None:
    ds = session.get(Dataset, dataset_id)
    if not ds:
        raise HTTPException(404, "Dataset not found")
    for v in session.exec(select(Variable).where(Variable.dataset_id == dataset_id)).all():
        session.delete(v)
    delete_frame(ds.parquet_path)
    session.delete(ds)
    session.commit()
