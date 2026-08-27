"""The ticket domain — plain SQLModel, owned by the host, not by any Asas
package. asas-ratelimit and asas-validation only guard the host's own
writes below; neither package knows this schema exists."""

from datetime import date
from typing import Optional

from sqlmodel import Field, SQLModel


class Ticket(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    description: str = ""
    status: str = "open"  # open | in_progress | resolved | closed
    priority: str = "normal"  # low | normal | high | urgent
    requester_email: str
    created_at: date = Field(default_factory=date.today)
    due_at: Optional[date] = None


class TicketCreate(SQLModel):
    title: str
    description: str = ""
    priority: str = "normal"
    requester_email: str
    due_at: Optional[date] = None


class TicketUpdate(SQLModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    due_at: Optional[date] = None
