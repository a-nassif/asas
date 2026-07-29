# asas-mcp

A remote **Model Context Protocol** server core for FastAPI/Starlette hosts:
`build_mcp_app(...)` returns a composed ASGI app + lifespan that the host
registers as an **exact route** (never a mount — MCP clients don't reliably
survive the trailing-slash redirect) and runs inside its own lifespan.

Design choices baked in (from Teamy's decision record 0014):

- **Low-level SDK server, not FastMCP** — the host's tools already carry
  hand-written JSON Schemas that must be exposed *verbatim*; the low-level
  `list_tools`/`call_tool` handlers give that control.
- **Stateless streamable HTTP, plain JSON responses** — no `Mcp-Session-Id`,
  every POST self-contained: scale-out safe behind a PaaS edge.
- **Honest annotations** (`MCPToolDef.read_only/destructive/idempotent`) —
  clients build their human-approval UX on them; a write tool mislabeled
  read-only would skip the user's approval prompt.
- **Auth is optional by construction** — pass an SDK `TokenVerifier` to get the
  hand-composed bearer stack (verification → auth contextvar → 401 gate whose
  challenge advertises the RFC 9728 protected-resource metadata); pass `None`
  for open access, mirroring the host's enforce flag.
- **Sync tool runners run in a worker thread**; the request's bearer token is
  read off the auth contextvar in async context and handed to the runner.
- A `dict` tool result becomes `structuredContent` *and* its JSON as text (the
  ChatGPT search/fetch compatibility shape); a `str` becomes plain text.

```python
from asas_mcp import MCPToolDef, build_mcp_app

asgi_app, lifespan = build_mcp_app(
    name="myapp",
    instructions="…",
    list_tools=lambda: [MCPToolDef(name="search", description="…", input_schema=SCHEMA)],
    run_tool=lambda token, name, args: dispatch(token, name, args),   # sync, threaded
    token_verifier=my_verifier,                # or None = open access
    resource_metadata_url="https://api…/.well-known/oauth-protected-resource",
)
app.router.routes.append(Route("/mcp", endpoint=asgi_app, methods=["POST", "GET", "DELETE"]))
# …and run `lifespan()` inside the app lifespan.
```

Protocol-only variant of the Asas host contract: no tables, no seeds, no
router factory — the host owns auth, tool registries, and allowlists. See the
repo README for the full contract. Extracted from Teamy (MCP epic TEAMY-357;
extraction epic TEAMY-466 / design record 0017).
