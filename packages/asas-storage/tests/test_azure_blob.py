"""AzureBlobStorage construction rules + Azure-specific behaviour (TEAMY-71).

The config-check assertions deliberately run *without* the Azure SDK
installed: they happen before the deferred import, so a misconfigured host
fails with a message naming the missing setting rather than an ImportError.
The construction-contract tests monkeypatch the SDK (no network); the
behavioural tests at the bottom run against Azurite and cover the failure
modes Azure has that S3/local don't — snapshots, batch-delete partial
failure, blob-vs-container 404 ambiguity. The generic contract itself is
covered by the shared parity fixture in test_contract.py.
"""

import os
import uuid

import pytest

from asas_storage import AzureBlobStorage
from asas_storage.azure_blob import _CHUNK, _clean_content_type

from test_contract import AZURITE_CONN


# --- config checks (no SDK, no network) -----------------------------------


def test_container_is_required():
    with pytest.raises(RuntimeError, match="STORAGE_AZURE_CONTAINER"):
        AzureBlobStorage(container="", account_url="https://acct.blob.core.windows.net")


def test_exactly_one_credential_source_required():
    """Neither is a misconfiguration; both is ambiguous — and silently
    preferring one would make an operator think managed identity is in use
    when a key is."""
    with pytest.raises(RuntimeError, match="exactly one"):
        AzureBlobStorage(container="uploads")
    with pytest.raises(RuntimeError, match="exactly one"):
        AzureBlobStorage(
            container="uploads",
            account_url="https://acct.blob.core.windows.net",
            connection_string="DefaultEndpointsProtocol=https;AccountName=acct;",
        )


def test_whitespace_only_values_read_as_unset():
    """A stray space/newline left by an env-var pane or secret-manager
    reference must not count as 'set' — that error told the operator they
    configured both sources when they configured one."""
    with pytest.raises(RuntimeError, match="exactly one"):
        AzureBlobStorage(container="uploads", account_url=" ")
    with pytest.raises(RuntimeError, match="STORAGE_AZURE_CONTAINER"):
        AzureBlobStorage(container="  ", account_url="https://acct.blob.core.windows.net")


# --- construction contract (SDK monkeypatched, no network) -----------------


def test_malformed_connection_string_raises_runtime_error():
    """from_connection_string raises a bare ValueError; the module promises
    construction fails with a RuntimeError naming the setting."""
    pytest.importorskip("azure.storage.blob")
    with pytest.raises(RuntimeError, match="STORAGE_AZURE_CONNECTION_STRING"):
        AzureBlobStorage(container="uploads", connection_string="total-garbage")


def test_account_url_path_uses_default_azure_credential(monkeypatch):
    """The preferred production shape — account_url + DefaultAzureCredential —
    must actually construct that way (nothing else in the suite ever executes
    this branch: Azurite only speaks shared key)."""
    azure_identity = pytest.importorskip("azure.identity")
    import azure.storage.blob as blob_mod

    built = {}

    class FakeCredential:
        pass

    class FakeContainerClient:
        def get_container_properties(self):
            return {}

    class FakeServiceClient:
        def __init__(self, account_url=None, credential=None, **kwargs):
            built["account_url"] = account_url
            built["credential"] = credential
            built["kwargs"] = kwargs

        def get_container_client(self, name):
            built["container"] = name
            return FakeContainerClient()

    monkeypatch.setattr(azure_identity, "DefaultAzureCredential", FakeCredential)
    monkeypatch.setattr(blob_mod, "BlobServiceClient", FakeServiceClient)

    AzureBlobStorage(
        container="uploads",
        account_url="https://acct.blob.core.windows.net",
        # whitespace-only second source strips to unset — must not trip the
        # exactly-one gate:
        connection_string="\n",
    )
    assert built["account_url"] == "https://acct.blob.core.windows.net"
    assert isinstance(built["credential"], FakeCredential)
    assert built["container"] == "uploads"
    # streaming + fail-fast knobs reach the client (the SDK defaults buffer
    # 32 MiB per download and hang ~85s on an unreachable endpoint)
    assert built["kwargs"]["max_single_get_size"] == _CHUNK
    assert built["kwargs"]["max_chunk_get_size"] == _CHUNK
    assert built["kwargs"]["connection_timeout"] == 5


def test_clean_content_type():
    assert _clean_content_type(None) is None
    assert _clean_content_type("") is None
    assert _clean_content_type("text/plain") == "text/plain"
    assert _clean_content_type("text/plain ") == "text/plain"  # breaks signing
    assert _clean_content_type("text/plain\r\nx-injected: 1") is None  # header injection
    assert _clean_content_type("\r\n") is None


# --- Azure-specific behaviour (Azurite) ------------------------------------


@pytest.fixture
def azurite():
    """A BlobServiceClient against the local emulator, or skip/fail."""
    pytest.importorskip("azure.storage.blob")
    from azure.core.exceptions import AzureError
    from azure.storage.blob import BlobServiceClient

    service = BlobServiceClient.from_connection_string(AZURITE_CONN)
    try:
        service.get_service_properties()
    except (AzureError, OSError) as exc:
        if os.environ.get("ASAS_REQUIRE_AZURE"):
            pytest.fail(
                "ASAS_REQUIRE_AZURE is set but Azurite is unavailable at "
                f"127.0.0.1:10000 ({exc}) — the azure leg may not silently skip"
            )
        pytest.skip(f"Azurite unavailable at 127.0.0.1:10000 ({exc})")
    return service


@pytest.fixture
def azurite_store(azurite):
    name = f"asas-test-{uuid.uuid4().hex[:12]}"
    azurite.create_container(name)
    try:
        yield AzureBlobStorage(container=name, connection_string=AZURITE_CONN), (
            azurite.get_container_client(name)
        )
    finally:
        azurite.delete_container(name)


def test_delete_takes_snapshots_along(azurite_store):
    """Azure refuses to delete a blob with snapshots (409 SnapshotsPresent)
    unless delete_snapshots='include' — snapshot-based backup would otherwise
    turn every member delete into a 500."""
    store, raw = azurite_store
    store.put("orgs/1/photos/7/small.jpg", b"x")
    raw.get_blob_client("orgs/1/photos/7/small.jpg").create_snapshot()
    store.delete("orgs/1/photos/7/small.jpg")
    assert not store.exists("orgs/1/photos/7/small.jpg")


def test_delete_prefix_tolerates_vanished_blobs(azurite_store, monkeypatch):
    """A blob deleted between list() and the batch (concurrent cleanup, an
    at-least-once jobs retry) must not abort the batch — and the return value
    is blobs actually removed, not listed."""
    store, raw = azurite_store
    for name in ("a.jpg", "b.jpg", "c.jpg"):
        store.put(f"orgs/1/photos/7/{name}", b"x")
    real_keys = list(store.list("orgs/1/photos/7"))
    monkeypatch.setattr(
        store, "list", lambda prefix: iter(real_keys + ["orgs/1/photos/7/ghost.jpg"])
    )
    assert store.delete_prefix("orgs/1/photos/7") == 3
    for name in ("a.jpg", "b.jpg", "c.jpg"):
        assert not raw.get_blob_client(f"orgs/1/photos/7/{name}").exists()


def test_delete_prefix_takes_snapshots_along(azurite_store):
    store, raw = azurite_store
    store.put("orgs/1/photos/7/small.jpg", b"x")
    raw.get_blob_client("orgs/1/photos/7/small.jpg").create_snapshot()
    assert store.delete_prefix("orgs/1/photos/7") == 1
    assert not store.exists("orgs/1/photos/7/small.jpg")


def test_missing_container_is_not_a_missing_blob(azurite):
    """Azure raises ResourceNotFoundError for a missing *container* too; the
    narrow BlobNotFound check keeps a deleted container (or an account swap)
    loud instead of silently no-op'ing deletes while every file reads as
    absent — S3 propagates NoSuchBucket the same way."""
    from azure.core.exceptions import ResourceNotFoundError

    name = f"asas-test-{uuid.uuid4().hex[:12]}"
    azurite.create_container(name)
    store = AzureBlobStorage(container=name, connection_string=AZURITE_CONN)
    store.put("orgs/1/photos/7/small.jpg", b"x")
    azurite.delete_container(name)  # the rug-pull

    with pytest.raises(ResourceNotFoundError):
        store.delete("orgs/1/photos/7/small.jpg")
    with pytest.raises(ResourceNotFoundError):
        store.stat("orgs/1/photos/7/small.jpg")
    with pytest.raises(ResourceNotFoundError):
        store.get("orgs/1/photos/7/small.jpg")


def test_stream_yields_bounded_chunks(azurite_store):
    """Without the client-level get-size caps the SDK materialises the whole
    blob (up to 32 MiB) before chunks() yields a byte — every host object is
    under that, so streaming would degenerate into buffering."""
    store, _ = azurite_store
    blob = os.urandom(3 * _CHUNK + 512)
    store.put("orgs/1/documents/2/cv.pdf", blob)
    chunks = list(store.stream("orgs/1/documents/2/cv.pdf"))
    assert b"".join(chunks) == blob
    assert len(chunks) > 1
    assert all(len(c) <= _CHUNK for c in chunks)


def test_put_normalises_hostile_content_type(azurite_store):
    """content_type reaches an Azure request header verbatim and hosts source
    it from a client-controlled multipart header: CR/LF must not become header
    injection / an 82s retry stall, and a trailing space must not break
    shared-key signing."""
    store, _ = azurite_store
    store.put("orgs/1/a.txt", b"x", content_type="text/plain\r\nx-evil: 1")
    # dropped, so the service default applies (Azure stamps octet-stream)
    assert store.stat("orgs/1/a.txt").content_type in (None, "application/octet-stream")
    store.put("orgs/1/b.txt", b"x", content_type="text/plain ")
    assert store.stat("orgs/1/b.txt").content_type == "text/plain"
