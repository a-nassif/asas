"""Read models for the /me/notifications API. Kept in sync with the TS types in
``frontend/src/lib/api.ts`` (house rule)."""

from datetime import datetime
from typing import Optional

from sqlmodel import SQLModel

from .models import Category, Reason, Urgency


class NotificationRead(SQLModel):
    id: int
    kind: str
    category: Category
    urgency: Urgency
    reason: Reason
    entity_type: Optional[str] = None
    entity_id: Optional[int] = None
    title: str
    body: Optional[str] = None
    link: Optional[str] = None
    read_at: Optional[datetime] = None
    created_at: datetime


class NotificationList(SQLModel):
    items: list[NotificationRead]
    total: int
    unread_count: int


class ReadAllResult(SQLModel):
    updated: int
