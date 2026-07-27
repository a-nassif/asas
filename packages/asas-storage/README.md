# asas-storage

A pluggable file/object storage seam: every stored byte goes through one process-wide
backend behind a traversal-safe `Storage` protocol. Two built-in backends — `LocalStorage`
(zero-config on-disk) and `S3Storage` (any S3-compatible endpoint: AWS S3, Supabase
Storage, MinIO, R2; needs the `[s3]` extra) — with identical key semantics, so swapping
backends never touches data.

Keys are `/`-separated relative paths (the strings the host stores in its DB). Absolute
paths and `..`/empty segments are rejected identically on disk and bucket: traversal
safety lives in the library, not in callers.

Table-less **and** router-less variant of the Asas host contract: no session dependency,
no `seed`, no `migrate`, no `build_routers` — serving bytes over HTTP is host auth
territory. The host installs a backend factory at startup:

```python
import asas_storage
from asas_storage import LocalStorage, S3Storage

def _build() -> asas_storage.Storage:
    # read *your* settings; the library reads no configuration itself
    if settings.storage_backend == "s3":
        return S3Storage(bucket=..., access_key=..., secret_key=..., endpoint_url=...)
    return LocalStorage(settings.uploads_dir)

asas_storage.configure(_build)          # lazy: built on first storage() call
```

Call sites then use `storage()`:

```python
from asas_storage import storage, safe_filename

storage().put(f"orgs/{org}/documents/{uuid}-{safe_filename(name)}", data, content_type)
stat, chunks = storage().fetch(key)     # stat + stream in one backend call
storage().delete_prefix(f"orgs/{org}/photos/{member_id}")
```

Tests point the singleton at a tmp dir: `set_storage(LocalStorage(tmp_path))`
(`set_storage(None)` resets to lazy re-selection via the factory).

See the repo README for the full contract. Extracted from Teamy (storage seam TEAMY-248,
extraction epic TEAMY-466 / design record 0017).
