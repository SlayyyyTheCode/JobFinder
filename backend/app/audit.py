from sqlmodel import Session

from .models import AuditEvent, Notification


def audit(s: Session, actor: str, action: str, entity: str = "", entity_id: int | None = None,
          commit: bool = True, **meta) -> None:
    s.add(AuditEvent(actor=actor, action=action, entity=entity, entity_id=entity_id, meta=meta))
    if commit:
        s.commit()


def notify(s: Session, type: str, title: str, body: str = "", link: str = "",
           important: bool = False, commit: bool = True) -> None:
    s.add(Notification(type=type, title=title, body=body, link=link, important=important))
    if commit:
        s.commit()
