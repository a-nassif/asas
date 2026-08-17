"""Azure Blob Storage backend — the Azure tier of the storage seam.

Azure Blob speaks no S3 API, so ``S3Storage`` cannot reach it and an S3
translation gateway (MinIO, S3Proxy) would add a component to patch *and*
reintroduce a static key pair. This backend talks the native Blob API
instead, which lets the preferred deployment carry **no storage credential
at all**: ``account_url`` + a managed identity resolved by
``DefaultAzureCredential``.

Two ways to construct, matching the two things deployments actually have:

- ``account_url`` (``https://<account>.blob.core.windows.net``) — authenticates
  with ``DefaultAzureCredential``: managed identity in Azure, developer
  credentials (az login / env vars) elsewhere. **Prefer this.**
- ``connection_string`` — an account key, for the storage emulator and for
  deployments whose identity plane can't issue tokens to the workload.

Needs the ``[azure]`` extra (``azure-storage-blob`` + ``azure-identity``),
imported lazily so the local and S3 tiers never require it.

Construction validates config and probes the container, mirroring
``S3Storage``: a missing container or unusable credential must stop host
startup rather than surface on the first upload.
"""

from __future__ import annotations

from typing import Iterator, List, Optional, Tuple

from .base import FileStat, RangeNotSatisfiable, valid_key

# On Azure each downloaded chunk is a separate ranged GET (unlike S3, where
# chunks slice one streaming response), so this is deliberately larger than
# S3's 64 KiB: small enough that a stream holds ~1 MiB rather than the SDK
# default of the whole blob (max_single_get_size defaults to 32 MiB — above
# every object the hosts store, so without this cap "streaming" degenerates
# into buffering the entire object before the first byte leaves).
_CHUNK = 1024 * 1024
_BATCH = 256  # delete_blobs hard limit per batch request

# Shared client construction knobs. The storage SDK's defaults are tuned for
# batch tooling, not a web process: ExponentialRetry starts at a 15s backoff
# with a 20s connect timeout, which turns an unreachable endpoint into an
# ~85s hang — long enough for a container platform's startup probe to kill
# the instance before the boot-time RuntimeError ever prints.
_CLIENT_KWARGS = dict(
    max_single_get_size=_CHUNK,
    max_chunk_get_size=_CHUNK,
    connection_timeout=5,
    read_timeout=60,
    retry_total=2,
    initial_backoff=1,
    increment_base=2,
)


def _clean_content_type(value: Optional[str]) -> Optional[str]:
    """Best-effort normalisation of a caller-supplied content type.

    The value travels verbatim into an Azure request header, where hosts may
    source it from a client-controlled multipart part header: a CR/LF makes
    azure-core fail the request after its full retry schedule, and a trailing
    space breaks shared-key signing (403). Content type is best-effort by
    contract, so anything unheaderable is dropped rather than raised.
    """
    if not value:
        return None
    value = value.strip()
    if not value or any(not (" " <= ch <= "~") for ch in value):
        return None
    return value


def _to_stat(props) -> FileStat:
    # BlobProperties.content_settings is constructed unconditionally by the
    # SDK on both the HEAD and GET paths — no need to guard for None.
    return FileStat(size=props.size, content_type=props.content_settings.content_type)


class AzureBlobStorage:
    def __init__(
        self,
        *,
        container: str,
        account_url: str = "",
        connection_string: str = "",
    ):
        # Strip before validating: a stray newline or space left by an env-var
        # pane or a secret-manager reference must not read as "set" (or worse,
        # survive into the account URL).
        container = container.strip()
        account_url = account_url.strip()
        connection_string = connection_string.strip()
        if not container:
            raise RuntimeError("STORAGE_BACKEND=azure_blob requires STORAGE_AZURE_CONTAINER")
        if bool(account_url) == bool(connection_string):
            raise RuntimeError(
                "STORAGE_BACKEND=azure_blob requires exactly one of "
                "STORAGE_AZURE_ACCOUNT_URL (managed identity, preferred) or "
                "STORAGE_AZURE_CONNECTION_STRING (account key)"
            )
        # Deferred so the local/S3 tiers never need the dependency at import time.
        from azure.core.exceptions import AzureError
        from azure.storage.blob import BlobServiceClient

        if connection_string:
            try:
                service = BlobServiceClient.from_connection_string(
                    connection_string, **_CLIENT_KWARGS
                )
            except ValueError as exc:
                # The SDK raises a bare ValueError on a mis-pasted string;
                # keep the "construction fails with RuntimeError naming the
                # setting" contract the account_url path already honours.
                raise RuntimeError(
                    f"STORAGE_AZURE_CONNECTION_STRING is malformed: {exc}"
                ) from exc
        else:
            from azure.identity import DefaultAzureCredential

            service = BlobServiceClient(
                account_url=account_url,
                credential=DefaultAzureCredential(),
                **_CLIENT_KWARGS,
            )
        self._container = service.get_container_client(container)
        # Probe now: client construction never contacts Azure, so a wrong
        # container or an identity without a data-plane role assignment would
        # otherwise fail on the first upload instead of failing the boot.
        try:
            self._container.get_container_properties()
        except AzureError as exc:
            raise RuntimeError(
                f"Cannot access Azure blob container {container!r}"
                f" at {account_url or 'the configured account'}: {exc}"
            ) from exc

    def put(self, key: str, data: bytes, content_type: Optional[str] = None) -> None:
        from azure.storage.blob import ContentSettings

        if not valid_key(key):
            raise ValueError(f"Invalid storage key: {key!r}")
        content_type = _clean_content_type(content_type)
        settings = ContentSettings(content_type=content_type) if content_type else None
        self._container.upload_blob(
            name=key, data=data, overwrite=True, content_settings=settings
        )

    def _download(self, key: str):
        """Single GetBlob returning the SDK downloader (properties + stream)."""
        from azure.core.exceptions import ResourceNotFoundError

        if not valid_key(key):
            raise FileNotFoundError(key)
        try:
            return self._container.download_blob(key)
        except ResourceNotFoundError as exc:
            # Azure raises the same type for a missing *container*; only a
            # missing blob maps to FileNotFoundError — anything else (deleted
            # container, rotated account) must propagate, matching S3's
            # NoSuchBucket behaviour.
            if exc.error_code == "BlobNotFound":
                raise FileNotFoundError(key) from exc
            raise

    def get(self, key: str) -> bytes:
        return self._download(key).readall()

    def fetch_range(
        self, key: str, start: int, end: int
    ) -> Tuple[FileStat, Iterator[bytes]]:
        from azure.core.exceptions import HttpResponseError, ResourceNotFoundError

        if not valid_key(key):
            raise FileNotFoundError(key)
        if start < 0 or end < start:
            raise RangeNotSatisfiable(f"bytes={start}-{end}")
        try:
            downloader = self._container.download_blob(
                key, offset=start, length=end - start + 1
            )
        except ResourceNotFoundError as exc:
            if exc.error_code == "BlobNotFound":
                raise FileNotFoundError(key) from exc
            raise
        except HttpResponseError as exc:
            if exc.status_code == 416:  # start past EOF
                raise RangeNotSatisfiable(f"bytes={start}-{end}") from exc
            raise
        # A ranged download's ``properties.size`` is the RANGE length; the
        # blob's total size rides ``content_range`` ("bytes 0-99/1234").
        props = downloader.properties
        content_range = getattr(props, "content_range", None)
        total = (
            int(content_range.rpartition("/")[2]) if content_range else props.size
        )
        # ``start == total`` is unsatisfiable per RFC 9110 §14.1.1, and the 416
        # above is not enough to enforce it: Azure returns 416 there, but Azurite
        # answers an empty 206 and only 416s from ``start > total``. Deciding it
        # here costs nothing — the total came back on this same response — and
        # makes the backend authoritative about its own contract instead of
        # trusting a service (or an emulator standing in for one) to be right.
        # LocalStorage has always done exactly this; only Azure delegated it.
        if start >= total:
            raise RangeNotSatisfiable(f"bytes={start}-{end} of {total}")
        stat = FileStat(
            size=total,
            content_type=_to_stat(props).content_type,
        )
        return stat, downloader.chunks()

    def stream(self, key: str) -> Iterator[bytes]:
        return self._download(key).chunks()

    def fetch(self, key: str) -> Tuple[FileStat, Iterator[bytes]]:
        downloader = self._download(key)
        return _to_stat(downloader.properties), downloader.chunks()

    def exists(self, key: str) -> bool:
        return self.stat(key) is not None

    def stat(self, key: str) -> Optional[FileStat]:
        from azure.core.exceptions import ResourceNotFoundError

        if not valid_key(key):
            return None
        try:
            props = self._container.get_blob_client(key).get_blob_properties()
        except ResourceNotFoundError as exc:
            if exc.error_code == "BlobNotFound":
                return None
            raise
        return _to_stat(props)

    def delete(self, key: str) -> None:
        from azure.core.exceptions import ResourceNotFoundError

        if not valid_key(key):
            return
        try:
            # "include": Azure refuses to delete a blob that has snapshots
            # (409 SnapshotsPresent) unless told to take them along — and
            # snapshot-based backup is exactly what a government deployment
            # runs. S3 and local have no equivalent failure mode.
            self._container.delete_blob(key, delete_snapshots="include")
        except ResourceNotFoundError as exc:
            if exc.error_code == "BlobNotFound":
                return  # missing keys are a no-op, matching the other backends
            raise  # a missing container is NOT a clean delete — see _download

    def delete_prefix(self, prefix: str) -> int:
        removed = 0
        batch: List[str] = []
        for key in self.list(prefix):
            batch.append(key)
            if len(batch) == _BATCH:
                removed += self._delete_batch(batch)
                batch = []
        if batch:
            removed += self._delete_batch(batch)
        return removed

    def _delete_batch(self, keys: List[str]) -> int:
        """One Blob Batch request; returns how many blobs were actually removed.

        ``raise_on_any_failure=False`` keeps the "missing keys are a no-op"
        contract: a blob deleted between list() and the batch (a concurrent
        cleanup, an at-least-once job retry) 404s its sub-request without
        aborting the rest — the failure mode that would otherwise orphan
        every object after the first already-gone key.
        """
        responses = self._container.delete_blobs(
            *keys, delete_snapshots="include", raise_on_any_failure=False
        )
        return sum(1 for r in responses if r.status_code == 202)

    def list(self, prefix: str) -> Iterator[str]:
        if not valid_key(prefix):
            return
        # Directory semantics, matching LocalStorage/S3Storage: "orgs/1/photos/1"
        # must not match "orgs/1/photos/12".
        prefix = prefix.rstrip("/") + "/"
        # list_blob_names: names only, skipping BlobProperties deserialisation
        # (~3x faster on large prefixes; delete_prefix and migration sweeps
        # pay this on every call).
        yield from self._container.list_blob_names(name_starts_with=prefix)
