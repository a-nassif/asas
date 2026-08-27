# helpdesk — the Asas example project

A small support-ticket API, built up incrementally as a real, working
demonstration of each Asas package — not a toy. Started with `asas new
helpdesk --with ratelimit,validation`; everything past the initial
scaffold is hand-written, same as any real project would do.

## Run it

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
uvicorn main:app --reload
```

```bash
pytest -q   # 6 tests: happy path, validation rejection, rate-limit trip,
            # per-requester isolation, update validation, 404
```

## What's wired so far

| Package | What it does here |
| --- | --- |
| `asas-ratelimit` | `POST /tickets` is limited to 5/hour **per requester email** — anti-spam on the public ticket form, not global |
| `asas-validation` | Two rules on `ticket`: due date can't precede the creation date (cross-field), created date can't be in the future |

### A real gotcha this example hit

`Ticket.created_at` is server-assigned (`default_factory=date.today`), never
part of the incoming request body. `asas_validation.evaluate()` only reads
values actually present in `changes`/the existing `record` — it silently
**skips** a rule if any field it needs is missing, by design (so a rule
never blocks on data that isn't there). The due-date-after-created rule
would therefore never fire on ticket creation unless `created_at` is added
to `changes` explicitly before validating — see the comment in
`create_ticket()` in `main.py`. Worth knowing before assuming a validation
rule is "on" just because it's declared.

## Endpoints

- `POST /tickets` — create (rate-limited, validated)
- `GET /tickets` — list, optional `?status=`
- `GET /tickets/{id}` — fetch one
- `PATCH /tickets/{id}` — update (validated against the existing record)
- `GET /validation/rules` — the declared rule catalog (from `asas-validation`)

## Plan — packages still to wire

Same risk-tiered order used to build this so far:

1. ~~`ratelimit`~~ — done
2. ~~`validation`~~ — done
3. `storage` — file attachments on tickets
4. `lookups` — status/priority as real bilingual reference data instead of bare strings
5. `notifications` — notify the assignee on comment/status change
6. `jobs` — SLA-breach reminders, digest emails
7. `search` — search across tickets + comments
8. `access` — internal-only tickets, agent/admin/viewer roles
9. `workflow` — approval routing for a ticket type (e.g. refund requests)
10. `mcp` — expose "create ticket" / "search tickets" to an AI client

## Adding a package

```bash
asas add <package>   # pins it into pyproject.toml at its own latest tag
```

Then wire it into `main.py` by hand, following the same pattern already
there for `ratelimit`/`validation` — each package's own README documents
its exact contract.
