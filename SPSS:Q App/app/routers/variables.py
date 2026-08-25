"""Editing the inferred variable metadata."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from app.core.ordering import suggest_order
from app.db import get_session
from app.models import Variable

router = APIRouter(prefix="/api/variables", tags=["variables"])


class OrderUpdate(BaseModel):
    category_order: list[str]


class LabelUpdate(BaseModel):
    label: str | None = None
    missing_codes: list[str] | None = None


@router.patch("/{variable_id}/order")
def set_order(
    variable_id: int, payload: OrderUpdate, session: Session = Depends(get_session)
) -> dict:
    """Save a user-chosen category order.

    The submitted order must contain exactly the variable's own categories --
    nothing added, nothing dropped. Silently accepting a partial list would drop
    categories from every table built afterwards.
    """
    variable = session.get(Variable, variable_id)
    if not variable:
        raise HTTPException(404, "Variable not found")

    known = set(variable.value_labels)
    submitted = list(payload.category_order)
    if len(submitted) != len(set(submitted)):
        raise HTTPException(422, "That order repeats a category")
    if set(submitted) != known:
        missing = sorted(known - set(submitted))
        unknown = sorted(set(submitted) - known)
        detail = "The order doesn't match this variable's categories."
        if missing:
            detail += f" Missing: {', '.join(m[:40] for m in missing[:3])}."
        if unknown:
            detail += f" Not a category: {', '.join(u[:40] for u in unknown[:3])}."
        raise HTTPException(422, detail)

    variable.category_order = submitted
    variable.order_rule = "user"
    session.add(variable)
    session.commit()
    return {"category_order": variable.category_order, "order_rule": variable.order_rule}


@router.post("/{variable_id}/order/suggest")
def resuggest_order(variable_id: int, session: Session = Depends(get_session)) -> dict:
    """Throw away a hand-made order and re-run the suggestion."""
    variable = session.get(Variable, variable_id)
    if not variable:
        raise HTTPException(404, "Variable not found")
    order, rule = suggest_order(list(variable.value_labels))
    variable.category_order = order
    variable.order_rule = rule
    session.add(variable)
    session.commit()
    return {"category_order": order, "order_rule": rule}


@router.patch("/{variable_id}")
def update_variable(
    variable_id: int, payload: LabelUpdate, session: Session = Depends(get_session)
) -> dict:
    variable = session.get(Variable, variable_id)
    if not variable:
        raise HTTPException(404, "Variable not found")
    if payload.label is not None:
        label = payload.label.strip()
        if not label:
            raise HTTPException(422, "A variable needs a label")
        variable.label = label
    if payload.missing_codes is not None:
        unknown = set(payload.missing_codes) - set(variable.value_labels)
        if unknown:
            raise HTTPException(
                422, f"Not a category of this variable: {', '.join(sorted(unknown)[:3])}"
            )
        variable.missing_codes = payload.missing_codes
    session.add(variable)
    session.commit()
    return {
        "id": variable.id,
        "label": variable.label,
        "missing_codes": variable.missing_codes,
    }
