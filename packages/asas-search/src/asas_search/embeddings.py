"""Embedding provider seam (Phase 3, WXL-162; design in Teamy DR 0006 §3D/§5).

Embeddings live in exactly one place — this package (the contract Teamy DR 0010 §4
records: chat and any future consumer reach vectors only through the ``asas_search``
seam, never a second store). Like the rest of the package this module is
self-contained: configuration values are passed in by app wiring, never read here.

One adapter covers every OpenAI-compatible /embeddings API — OpenAI itself, Azure,
and local servers (TEI, Ollama) — selected by ``base_url``. Adding a genuinely
different protocol = a new class implementing :class:`EmbeddingProvider` + a factory
entry, mirroring ``services/linkedin``.
"""

from typing import List, Protocol

import httpx


class EmbeddingProvider(Protocol):
    """``model`` is stored per vector so a provider/model switch re-embeds instead of
    ever mixing vector spaces (queries filter on it)."""

    model: str

    def embed(self, texts: List[str]) -> List[List[float]]: ...


class OpenAICompatibleEmbeddings:
    def __init__(self, api_key: str, model: str, base_url: str) -> None:
        if not api_key:
            raise RuntimeError("embedding provider not configured (missing API key)")
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")

    # Providers cap inputs per request (OpenAI: 2048); chunk well below it.
    _BATCH = 100

    def embed(self, texts: List[str]) -> List[List[float]]:
        out: List[List[float]] = []
        for i in range(0, len(texts), self._BATCH):
            chunk = texts[i : i + self._BATCH]
            resp = httpx.post(
                f"{self.base_url}/embeddings",
                json={"model": self.model, "input": chunk},
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=60.0,
            )
            resp.raise_for_status()
            data = sorted(resp.json()["data"], key=lambda d: d["index"])
            out.extend(d["embedding"] for d in data)
        return out


def create_provider(
    provider: str, api_key: str, model: str, base_url: str
) -> EmbeddingProvider:
    """Factory, mirroring ``services/linkedin``: new vendor = new class + one entry."""
    if provider == "openai":
        return OpenAICompatibleEmbeddings(api_key, model, base_url)
    raise RuntimeError(f"unknown EMBEDDING_PROVIDER: {provider!r}")
