"""The composed /mcp ASGI app end-to-end over plain JSON-RPC POSTs (stateless
streamable HTTP, JSON responses — no handshake or session id): tool listing
with honest annotations, calls with the str/dict result duality, prompts, and
the optional bearer-auth stack. Harness mirrors Teamy's test_mcp.py."""

import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from asas_mcp import MCPPromptArg, MCPPromptDef, MCPToolDef, build_mcp_app

_ACCEPT = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}

_TOOLS = [
    MCPToolDef(
        name="echo",
        description="Echo text back.",
        input_schema={"type": "object", "properties": {"text": {"type": "string"}}},
    ),
    MCPToolDef(
        name="write_thing",
        description="A write tool.",
        input_schema={"type": "object", "properties": {}},
        read_only=False,
        idempotent=False,
    ),
    MCPToolDef(
        name="void_thing",
        description="A write tool with no return value.",
        input_schema={"type": "object", "properties": {}},
        read_only=False,
    ),
    MCPToolDef(
        name="list_thing",
        description="Returns a list.",
        input_schema={"type": "object", "properties": {}},
    ),
]


def _run_tool(token, name, arguments):
    if name == "echo":
        return f"echo:{arguments.get('text', '')} token={token}"
    if name == "write_thing":
        return {"ok": True, "wrote": 1}
    if name == "void_thing":
        return None
    if name == "list_thing":
        return ["a", 1]
    raise ValueError(f"unknown tool {name}")


_PROMPTS = [
    MCPPromptDef(
        name="greet",
        description="Greeting recipe",
        arguments=[MCPPromptArg(name="who", description="Whom to greet")],
        render=lambda args: f"Say hello to {args.get('who', 'the world')}",
    )
]


def _client(token_verifier=None, resource_metadata_url=None):
    asgi_app, lifespan = build_mcp_app(
        name="asas-test",
        instructions="Test server.",
        list_tools=lambda: _TOOLS,
        run_tool=_run_tool,
        prompts=_PROMPTS,
        token_verifier=token_verifier,
        resource_metadata_url=resource_metadata_url,
    )
    routes = [Route("/mcp", endpoint=asgi_app, methods=["POST", "GET", "DELETE"])]

    class _App(Starlette):
        pass

    import contextlib

    @contextlib.asynccontextmanager
    async def app_lifespan(app):
        async with lifespan():
            yield

    return TestClient(_App(routes=routes, lifespan=app_lifespan))


def _rpc(client, method, params=None, token=None, id=1):
    headers = dict(_ACCEPT)
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    body = {"jsonrpc": "2.0", "id": id, "method": method}
    if params is not None:
        body["params"] = params
    return client.post("/mcp", json=body, headers=headers)


def test_list_tools_with_honest_annotations():
    with _client() as client:
        result = _rpc(client, "tools/list").json()["result"]
        tools = {t["name"]: t for t in result["tools"]}
        assert tools["echo"]["annotations"]["readOnlyHint"] is True
        assert tools["write_thing"]["annotations"]["readOnlyHint"] is False
        assert tools["write_thing"]["annotations"]["idempotentHint"] is False
        assert tools["echo"]["inputSchema"]["properties"]["text"]["type"] == "string"


def test_call_tool_str_and_dict_results():
    with _client() as client:
        result = _rpc(
            client, "tools/call", {"name": "echo", "arguments": {"text": "hi"}}
        ).json()["result"]
        assert result["content"][0]["text"] == "echo:hi token=None"
        result = _rpc(
            client, "tools/call", {"name": "write_thing", "arguments": {}}, id=2
        ).json()["result"]
        # Dict results carry structuredContent AND the JSON as text (TEAMY-360).
        assert result["structuredContent"] == {"ok": True, "wrote": 1}
        assert '"wrote"' in result["content"][0]["text"]


def test_prompts_list_and_render():
    with _client() as client:
        prompts = _rpc(client, "prompts/list").json()["result"]["prompts"]
        assert prompts[0]["name"] == "greet"
        got = _rpc(
            client, "prompts/get", {"name": "greet", "arguments": {"who": "Asas"}}, id=3
        ).json()["result"]
        assert got["messages"][0]["content"]["text"] == "Say hello to Asas"


def test_bearer_stack_gates_and_passes_token():
    from mcp.server.auth.provider import AccessToken, TokenVerifier

    class StubVerifier(TokenVerifier):
        async def verify_token(self, token: str):
            if token == "good":
                return AccessToken(token=token, client_id="c", scopes=[])
            return None

    with _client(
        token_verifier=StubVerifier(),
        resource_metadata_url="https://api.example/.well-known/oauth-protected-resource",
    ) as client:
        resp = _rpc(client, "tools/list")
        assert resp.status_code == 401
        assert "resource_metadata" in resp.headers.get("www-authenticate", "")
        assert _rpc(client, "tools/list", token="bad").status_code == 401
        assert _rpc(client, "tools/list", token="good").status_code == 200
        # The runner receives the request's raw bearer credential.
        result = _rpc(
            client, "tools/call", {"name": "echo", "arguments": {"text": "x"}},
            token="good", id=4,
        ).json()["result"]
        assert result["content"][0]["text"].endswith("token=good")


def test_tool_error_is_reported_not_raised():
    with _client() as client:
        result = _rpc(
            client, "tools/call", {"name": "nope", "arguments": {}}
        ).json()["result"]
        assert result.get("isError") is True


def test_unknown_prompt_is_invalid_params_not_code_zero():
    """The spec wants -32602 (Invalid params) for an unknown prompt name; a
    bare ValueError surfaced as JSON-RPC error code 0 — not a valid code."""
    with _client() as client:
        resp = _rpc(client, "prompts/get", {"name": "nope"}).json()
        assert resp["error"]["code"] == -32602
        assert "nope" in resp["error"]["message"]


def test_missing_required_prompt_argument_is_invalid_params():
    """prompts/list advertises `who` as required; accepting a call without it
    silently rendered a different prompt."""
    with _client() as client:
        resp = _rpc(client, "prompts/get", {"name": "greet"}).json()
        assert resp["error"]["code"] == -32602
        assert "who" in resp["error"]["message"]
        # with the argument present it renders as before
        ok = _rpc(
            client, "prompts/get", {"name": "greet", "arguments": {"who": "asas"}}, id=2
        ).json()["result"]
        assert ok["messages"][0]["content"]["text"] == "Say hello to asas"


def test_non_str_tool_results_are_normalized_not_pydantic_dumps():
    """ToolRunner is typed Any: a void write tool returning None (or a list)
    must yield honest text content, not an isError pydantic validation dump."""
    with _client() as client:
        result = _rpc(
            client, "tools/call", {"name": "void_thing", "arguments": {}}
        ).json()["result"]
        assert not result.get("isError", False)
        assert result["content"] == [] or result["content"][0]["text"] == ""
        result = _rpc(
            client, "tools/call", {"name": "list_thing", "arguments": {}}, id=2
        ).json()["result"]
        assert not result.get("isError", False)
        assert result["content"][0]["text"] == '["a", 1]'
