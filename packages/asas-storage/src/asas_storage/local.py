"""On-disk backend — the zero-config default: files live under ``root/<key>``,
so a host adopting the seam over an existing uploads directory wakes up
unchanged."""

from __future__ import annotations

import mimetypes
import shutil
from pathlib import Path
from typing import Iterator, Optional, Tuple

from .base import FileStat, valid_key

_CHUNK = 64 * 1024


class LocalStorage:
    def __init__(self, root: Path):
        self._root = root.resolve()

    def _full(self, key: str) -> Optional[Path]:
        """Resolve ``key`` under the root; ``None`` when invalid. ``valid_key``
        keeps key semantics identical across backends (``orgs//x`` or
        ``orgs/../x`` must not become a working alias on one backend only);
        the resolve+containment check stays as defense in depth."""
        if not valid_key(key):
            return None
        full = (self._root / key).resolve()
        if full == self._root or not str(full).startswith(str(self._root) + "/"):
            return None
        return full

    def put(self, key: str, data: bytes, content_type: Optional[str] = None) -> None:
        full = self._full(key)
        if full is None:
            raise ValueError(f"Invalid storage key: {key!r}")
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_bytes(data)

    def get(self, key: str) -> bytes:
        full = self._full(key)
        if full is None or not full.is_file():
            raise FileNotFoundError(key)
        return full.read_bytes()

    def stream(self, key: str) -> Iterator[bytes]:
        # Validate eagerly (contract parity with S3Storage), yield lazily.
        full = self._full(key)
        if full is None or not full.is_file():
            raise FileNotFoundError(key)
        return self._chunks(full)

    def fetch(self, key: str) -> Tuple[FileStat, Iterator[bytes]]:
        full = self._full(key)
        if full is None or not full.is_file():
            raise FileNotFoundError(key)
        stat = FileStat(
            size=full.stat().st_size, content_type=mimetypes.guess_type(key)[0]
        )
        return stat, self._chunks(full)

    @staticmethod
    def _chunks(full: Path) -> Iterator[bytes]:
        with full.open("rb") as fh:
            while chunk := fh.read(_CHUNK):
                yield chunk

    def exists(self, key: str) -> bool:
        full = self._full(key)
        return full is not None and full.is_file()

    def stat(self, key: str) -> Optional[FileStat]:
        full = self._full(key)
        if full is None or not full.is_file():
            return None
        return FileStat(
            size=full.stat().st_size, content_type=mimetypes.guess_type(key)[0]
        )

    def delete(self, key: str) -> None:
        full = self._full(key)
        if full is None:
            return
        full.unlink(missing_ok=True)
        self._prune_empty_dirs(full.parent)

    def delete_prefix(self, prefix: str) -> int:
        full = self._full(prefix)
        if full is None or not full.is_dir():
            return 0
        count = sum(1 for p in full.rglob("*") if p.is_file())
        shutil.rmtree(full, ignore_errors=True)
        self._prune_empty_dirs(full.parent)
        return count

    def list(self, prefix: str) -> Iterator[str]:
        full = self._full(prefix)
        if full is None or not full.is_dir():
            return
        for path in sorted(full.rglob("*")):
            if path.is_file():
                yield path.relative_to(self._root).as_posix()

    def _prune_empty_dirs(self, directory: Path) -> None:
        """Best-effort: drop now-empty parent dirs so the local tree doesn't
        accumulate husks. Never removes the root."""
        while directory != self._root and directory.is_dir():
            try:
                directory.rmdir()  # only succeeds when empty
            except OSError:
                return
            directory = directory.parent
