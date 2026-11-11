from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import AuditLog


def audit(s: Session, actor: str, action: str, entity_type: str | None = None, entity_id: str | None = None,
          detail: dict | None = None) -> None:
    s.add(AuditLog(actor=actor, action=action, entity_type=entity_type, entity_id=entity_id, detail=detail))
