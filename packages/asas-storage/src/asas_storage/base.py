"""Storage backend contract.

Keys are ``/``-separated relative paths (``orgs/{org}/photos/3/small.jpg``) —
exactly the strings the host stores in its DB. A key that is absolute or
escapes the root (``..``) is treated as nonexistent by reads and rejected by
writes: traversal safety lives here, not in callers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, Optional, Protocol, Tuple, runtime_checkable


@dataclass(frozen=True)
class FileStat:
    size: int
    content_type: Optional[str] = None


_SAFE_NAME_CHARS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 ._()-"
)


def safe_filename(name: str) -> str:
    """Flatten a client filename into the ASCII-safe charset for storage keys.

    Object stores reject keys real-world filenames produce — Supabase's S3
    layer 400s on macOS screenshot names, which carry a U+202F narrow
    no-break space before "AM/PM" (found the hard way during the TEAMY-248
    cutover). Only the *key* is flattened; the display name stored on the row
    keeps the original. Uploaders prefix keys with a uuid, so flattening
    can't collide."""
    cleaned = "".join(c if c in _SAFE_NAME_CHARS else "_" for c in name)
    return cleaned.strip() or "file"


def valid_key(key: str) -> bool:
    """A safe relative key: no absolute paths, no empty/`.`/`..` segments.
    Backends share this so traversal behaves identically on disk and bucket."""
    if not key or key.startswith("/") or "\\" in key:
        return False
    return all(seg not in ("", ".", "..") for seg in key.split("/"))


@runtime_checkable
class Storage(Protocol):
    def put(self, key: str, data: bytes, content_type: Optional[str] = None) -> None:
        """Store ``data`` under ``key``, overwriting. Raises ValueError on a bad key."""
        ...

    def get(self, key: str) -> bytes:
        """Return the stored bytes. Raises FileNotFoundError when absent."""
        ...

    def stream(self, key: str) -> Iterator[bytes]:
        """Yield the stored bytes in chunks. Raises FileNotFoundError when absent."""
        ...

    def fetch(self, key: str) -> Tuple[FileStat, Iterator[bytes]]:
        """Stat + stream in one backend call (the serving hot path — on S3 a
        single GetObject instead of Head+Get). Raises FileNotFoundError when
        absent."""
        ...

    def exists(self, key: str) -> bool: ...

    def stat(self, key: str) -> Optional[FileStat]:
        """Size + best-effort content type, or ``None`` when absent."""
        ...

    def delete(self, key: str) -> None:
        """Remove the object; missing (or invalid) keys are a no-op."""
        ...

    def delete_prefix(self, prefix: str) -> int:
        """Remove every object under ``prefix`` (a directory-like subtree).
        Returns the number of objects removed."""
        ...

    def list(self, prefix: str) -> Iterator[str]:
        """Yield the keys under ``prefix`` (used by migration/export tooling)."""
        ...
