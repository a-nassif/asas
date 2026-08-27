"""helpdesk — the Asas example project.

Started by `asas new helpdesk --with ratelimit,validation`; the generated
boot sequence below has been filled in with a real ticket domain (this file
is plain, editable Python — nothing here depends on asas-cli after
generation). More packages get wired in as the example grows: see
README.md for the plan.
"""

from datetime import date
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException
from sqlmodel import Session, SQLModel, create_engine, select

import asas_ratelimit
import asas_validation

from models import Ticket, TicketCreate, TicketUpdate
from settings import AppSettings

settings = AppSettings()
engine = create_engine(settings.database_url)


def get_session():
    with Session(engine) as session:
        yield session


app = FastAPI(title="helpdesk")

# ── ratelimit ───────────────────────────────────────────────────────────
# Anti-spam on the public ticket-creation form, keyed by the requester's own
# email so one abusive requester can't drown out everyone else's quota.
asas_ratelimit.configure(enabled=settings.rate_limit_enabled)
asas_ratelimit.declare(
    asas_ratelimit.Rule(name="ticket.create", limit=5, window_seconds=3600)
)
for _name, (_count, _window) in asas_ratelimit.parse_overrides(
    settings.rate_limit_overrides
).items():
    asas_ratelimit.declare(
        asas_ratelimit.Rule(name=_name, limit=_count, window_seconds=_window)
    )


# ── validation ──────────────────────────────────────────────────────────
asas_validation.register_fields("ticket", {"title", "created_at", "due_at"})
asas_validation.declare_rules([
    asas_validation.Rule(
        entity="ticket", kind="order",
        fields=("created_at", "due_at"),
        message="Due date can't be before the ticket was created.",
        code="ticket.due_after_created",
    ),
    asas_validation.Rule(
        entity="ticket", kind="not_future",
        fields=("created_at",),
        message="Created date can't be in the future.",
        code="ticket.created_not_future",
    ),
])
asas_validation.assert_rules_known()  # fails loud at boot on a typo'd field/kind
app.include_router(asas_validation.build_router())  # already prefixed "/validation"


@app.on_event("startup")
def _boot() -> None:
    # The ticket table is host-owned — no Asas package here owns schema
    # (ratelimit and validation are both table-less). A real project would
    # use Alembic; SQLModel.metadata.create_all is enough for the example.
    SQLModel.metadata.create_all(engine)


# ── routes ────────────────────────────────────────────────────────────────

@app.post("/tickets", response_model=Ticket, status_code=201)
def create_ticket(payload: TicketCreate, session: Session = Depends(get_session)):
    asas_ratelimit.check("ticket.create", payload.requester_email)

    # created_at is server-assigned (Ticket.created_at's default_factory), never
    # part of the incoming payload — asas_validation only sees values actually
    # present in `changes`/`record`, so the cross-field due-date rule below
    # would silently never fire on create without setting it explicitly here.
    changes = payload.model_dump()
    changes["created_at"] = date.today()
    asas_validation.raise_if_invalid("ticket", None, changes)

    ticket = Ticket(**changes)
    session.add(ticket)
    session.commit()
    session.refresh(ticket)
    return ticket


@app.get("/tickets", response_model=list[Ticket])
def list_tickets(status: Optional[str] = None, session: Session = Depends(get_session)):
    query = select(Ticket)
    if status:
        query = query.where(Ticket.status == status)
    return session.exec(query).all()


@app.get("/tickets/{ticket_id}", response_model=Ticket)
def get_ticket(ticket_id: int, session: Session = Depends(get_session)):
    ticket = session.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return ticket


@app.patch("/tickets/{ticket_id}", response_model=Ticket)
def update_ticket(
    ticket_id: int, payload: TicketUpdate, session: Session = Depends(get_session)
):
    ticket = session.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")

    changes = payload.model_dump(exclude_unset=True)
    asas_validation.raise_if_invalid("ticket", ticket, changes)

    for field, value in changes.items():
        setattr(ticket, field, value)
    session.add(ticket)
    session.commit()
    session.refresh(ticket)
    return ticket
