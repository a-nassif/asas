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

from typing import Iterator, Optional, Tuple

from .base import FileStat, valid_key

_CHUNK = 64 * 1024
_BATCH = 256  # delete_blobs hard limit per batch request


class AzureBlobStorage:
    def __init__(
        self,
        *,
        container: str,
        account_url: str = "",
        connection_string: str = "",
    ):
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
            service = BlobServiceClient.from_connection_string(connection_string)
        else:
            from azure.identity import DefaultAzureCredential

            service = BlobServiceClient(
                account_url=account_url, credential=DefaultAzureCredential()
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
            raise FileNotFoundError(key) from exc

    def get(self, key: str) -> bytes:
        return self._download(key).readall()

    def stream(self, key: str) -> Iterator[bytes]:
        return self._download(key).chunks()

    def fetch(self, key: str) -> Tuple[FileStat, Iterator[bytes]]:
        downloader = self._download(key)
        props = downloader.properties
        stat = FileStat(
            size=downloader.size,
            content_type=(props.content_settings or {}).get("content_type"),
        )
        return stat, downloader.chunks()

    def exists(self, key: str) -> bool:
        return self.stat(key) is not None

    def stat(self, key: str) -> Optional[FileStat]:
        from azure.core.exceptions import ResourceNotFoundError

        if not valid_key(key):
            return None
        try:
            props = self._container.get_blob_client(key).get_blob_properties()
        except ResourceNotFoundError:
            return None
        return FileStat(
            size=props.size,
            content_type=(props.content_settings or {}).get("content_type"),
        )

    def delete(self, key: str) -> None:
        from azure.core.exceptions import ResourceNotFoundError

        if not valid_key(key):
            return
        try:
            self._container.delete_blob(key)
        except ResourceNotFoundError:
            return  # missing keys are a no-op, matching the other backends

    def delete_prefix(self, prefix: str) -> int:
        keys = list(self.list(prefix))
        for start in range(0, len(keys), _BATCH):
            self._container.delete_blobs(*keys[start : start + _BATCH])
        return len(keys)

    def list(self, prefix: str) -> Iterator[str]:
        if not valid_key(prefix):
            return
        # Directory semantics, matching LocalStorage/S3Storage: "orgs/1/photos/1"
        # must not match "orgs/1/photos/12".
        prefix = prefix.rstrip("/") + "/"
        for blob in self._container.list_blobs(name_starts_with=prefix):
            yield blob.name
