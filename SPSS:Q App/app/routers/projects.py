from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.db import get_session
from app.models import Dataset, Project

router = APIRouter(prefix="/api/projects", tags=["projects"])


class ProjectCreate(BaseModel):
    name: str
    notes: str = ""


@router.get("")
def list_projects(session: Session = Depends(get_session)) -> list[dict]:
    projects = session.exec(select(Project).order_by(Project.created_at.desc())).all()
    out = []
    for p in projects:
        n = len(session.exec(select(Dataset).where(Dataset.project_id == p.id)).all())
        out.append(
            {
                "id": p.id,
                "name": p.name,
                "notes": p.notes,
                "dataset_count": n,
                "created_at": p.created_at.isoformat(),
            }
        )
    return out


@router.post("", status_code=201)
def create_project(payload: ProjectCreate, session: Session = Depends(get_session)) -> dict:
    name = payload.name.strip()
    if not name:
        raise HTTPException(422, "Enter a project name")
    project = Project(name=name, notes=payload.notes.strip())
    session.add(project)
    session.commit()
    session.refresh(project)
    return {"id": project.id, "name": project.name}


@router.get("/{project_id}")
def get_project(project_id: int, session: Session = Depends(get_session)) -> dict:
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    datasets = session.exec(select(Dataset).where(Dataset.project_id == project_id)).all()
    return {
        "id": project.id,
        "name": project.name,
        "notes": project.notes,
        "datasets": [
            {
                "id": d.id,
                "name": d.name,
                "n_rows": d.n_rows,
                "n_columns": d.n_columns,
                "header_style": d.header_style,
            }
            for d in datasets
        ],
    }
