"""End-to-end proof that the wired packages actually guard the ticket
routes — not just that the app boots."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import asas_ratelimit
import asas_validation
import main


@pytest.fixture(autouse=True)
def _fresh_app(monkeypatch):
    """Isolated in-memory DB + clean package state per test — ratelimit and
    validation are both process-wide globals. StaticPool matters here: a
    plain sqlite:// engine hands each new connection its own independent
    :memory: database, so create_all() and the request handler would each
    see a different empty DB without pinning them to one shared connection."""
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(main, "engine", engine)
    monkeypatch.setattr(main, "get_session", lambda: Session(engine))

    asas_ratelimit.reset()
    asas_ratelimit.configure(enabled=True)
    asas_ratelimit.declare(asas_ratelimit.Rule(name="ticket.create", limit=2, window_seconds=3600))

    main.app.dependency_overrides[main.get_session] = lambda: Session(engine)
    yield
    main.app.dependency_overrides.clear()
    asas_ratelimit.reset()


@pytest.fixture
def client():
    return TestClient(main.app)


def test_create_ticket_happy_path(client):
    r = client.post("/tickets", json={
        "title": "Printer on fire",
        "requester_email": "a@example.com",
        "due_at": "2026-09-01",
    })
    assert r.status_code == 201
    assert r.json()["status"] == "open"


def test_create_ticket_rejects_due_date_before_created(client):
    r = client.post("/tickets", json={
        "title": "Time travel needed",
        "requester_email": "a@example.com",
        "due_at": "2020-01-01",
    })
    assert r.status_code == 422
    assert "due" in r.json()["detail"][0]["msg"].lower()


def test_create_ticket_rate_limited_after_declared_burst(client):
    for _ in range(2):
        r = client.post("/tickets", json={"title": "x", "requester_email": "spammer@example.com"})
        assert r.status_code == 201

    r = client.post("/tickets", json={"title": "x", "requester_email": "spammer@example.com"})
    assert r.status_code == 429
    assert "Retry-After" in r.headers


def test_rate_limit_is_per_requester_not_global(client):
    for _ in range(2):
        client.post("/tickets", json={"title": "x", "requester_email": "a@example.com"})
    r = client.post("/tickets", json={"title": "x", "requester_email": "b@example.com"})
    assert r.status_code == 201  # different requester, fresh bucket


def test_update_ticket_validated_against_existing_created_at(client):
    created = client.post("/tickets", json={
        "title": "Leaky faucet", "requester_email": "a@example.com",
    }).json()

    r = client.patch(f"/tickets/{created['id']}", json={"due_at": "2020-01-01"})
    assert r.status_code == 422


def test_get_missing_ticket_404s(client):
    assert client.get("/tickets/999").status_code == 404
