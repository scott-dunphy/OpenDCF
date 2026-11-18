"""Frozen valuations cannot change (docs/valuation-lifecycle-plan.md).

A flush hook rejects any change to a valuation that is in review or approved, other than its
labels and review state, and any delete of one, whichever route or service attempts it.
"""
from __future__ import annotations

from sqlalchemy import event, exists, inspect, select
from sqlalchemy.orm import Session

from src.models.valuation import Valuation, ValuationSnapshot

# May change on a frozen valuation: labels and the review trail itself
EDITABLE_WHEN_FROZEN = {
    "name", "description", "comment", "review_status", "snapshot_id", "updated_at",
    "ai_permission_mode",  # a copilot setting, not a model input
}


class ValuationFrozenError(Exception):
    """Raised when something tries to change or delete a frozen valuation."""


def _committed_review_status(obj: Valuation) -> str:
    history = inspect(obj).attrs.review_status.history
    if history.deleted:
        return history.deleted[0]
    return obj.review_status or "draft"


def _guard_inputs(session: Session) -> None:
    """A frozen valuation's own rows are its inputs: no adds, edits or deletes."""
    from src.services.input_tracking import _tracked, valuation_id_of

    touched = [o for o in (*session.new, *session.dirty, *session.deleted)
               if _tracked(o) and o.__tablename__ != "properties"]
    if not touched:
        return
    conn = session.connection()
    ids = {vid for vid in (valuation_id_of(conn, o) for o in touched) if vid}
    if not ids:
        return
    frozen = conn.execute(
        select(Valuation.name).where(Valuation.id.in_(ids), Valuation.review_status != "draft")
    ).scalars().first()
    if frozen is not None:
        raise ValuationFrozenError(
            f"Valuation '{frozen}' is frozen for review; reopen or duplicate it to change its inputs."
        )


@event.listens_for(Session, "before_flush")
def _guard(session: Session, flush_context, instances) -> None:
    _guard_inputs(session)
    for obj in session.deleted:
        if not isinstance(obj, Valuation):
            continue
        if _committed_review_status(obj) != "draft":
            raise ValuationFrozenError(
                f"Valuation '{obj.name}' is {_committed_review_status(obj).replace('_', ' ')} and cannot be "
                "deleted."
            )
        # A reopened valuation keeps its frozen versions; deleting it would erase that record
        has_history = session.connection().execute(
            select(exists().where(ValuationSnapshot.valuation_id == obj.id))
        ).scalar()
        if has_history:
            raise ValuationFrozenError(
                f"Valuation '{obj.name}' has review history and cannot be deleted."
            )
    for obj in session.dirty:
        if not isinstance(obj, Valuation) or _committed_review_status(obj) == "draft":
            continue
        state = inspect(obj)
        changed = sorted(
            a.key for a in state.attrs if a.key not in EDITABLE_WHEN_FROZEN and a.history.has_changes()
        )
        if changed:
            raise ValuationFrozenError(
                f"Valuation '{obj.name}' is frozen for review; reopen or duplicate it to change "
                f"{', '.join(changed)}."
            )
