"""Backend contract parity (local disk vs S3 via moto), traversal safety,
prefix directory-semantics, and key hygiene. Ported from Teamy's
tests/test_storage.py (TEAMY-248) with the extraction (TEAMY-472)."""

import pytest

from asas_storage import LocalStorage, S3Storage, safe_filename


@pytest.fixture(params=["local", "s3"])
def store(request, tmp_path):
    """The same contract assertions run against both backends."""
    if request.param == "local":
        yield LocalStorage(tmp_path)
        return
    moto = pytest.importorskip("moto")
    import boto3

    with moto.mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="asas-test")
        yield S3Storage(
            bucket="asas-test", access_key="test", secret_key="test", region="us-east-1"
        )


def test_put_get_roundtrip_and_overwrite(store):
    store.put("orgs/1/documents/2/a.txt", b"first", content_type="text/plain")
    assert store.get("orgs/1/documents/2/a.txt") == b"first"
    store.put("orgs/1/documents/2/a.txt", b"second")
    assert store.get("orgs/1/documents/2/a.txt") == b"second"


def test_get_missing_raises(store):
    with pytest.raises(FileNotFoundError):
        store.get("orgs/1/nope.bin")


def test_stream_yields_all_bytes(store):
    blob = b"x" * (200 * 1024) + b"tail"  # spans multiple chunks
    store.put("orgs/1/attachments/big.bin", blob)
    assert b"".join(store.stream("orgs/1/attachments/big.bin")) == blob
    with pytest.raises(FileNotFoundError):
        store.stream("orgs/1/attachments/missing.bin")


def test_exists_and_stat(store):
    assert not store.exists("orgs/1/photos/3/small.jpg")
    assert store.stat("orgs/1/photos/3/small.jpg") is None
    store.put("orgs/1/photos/3/small.jpg", b"jpegbytes", content_type="image/jpeg")
    assert store.exists("orgs/1/photos/3/small.jpg")
    stat = store.stat("orgs/1/photos/3/small.jpg")
    assert stat.size == len(b"jpegbytes")
    assert stat.content_type == "image/jpeg"


def test_delete_is_idempotent(store):
    store.put("orgs/1/documents/2/gone.txt", b"bye")
    store.delete("orgs/1/documents/2/gone.txt")
    assert not store.exists("orgs/1/documents/2/gone.txt")
    store.delete("orgs/1/documents/2/gone.txt")  # second delete is a no-op


def test_delete_prefix_uses_directory_semantics(store):
    """orgs/1/photos/1 must never swallow orgs/1/photos/12 (the classic
    string-prefix bug)."""
    for member in (1, 12):
        for name in ("small.jpg", "large.jpg"):
            store.put(f"orgs/1/photos/{member}/{name}", b"x")
    assert store.delete_prefix("orgs/1/photos/1") == 2
    assert not store.exists("orgs/1/photos/1/small.jpg")
    assert store.exists("orgs/1/photos/12/small.jpg")
    assert store.delete_prefix("orgs/1/photos/1") == 0  # idempotent


def test_list_returns_keys_under_prefix(store):
    store.put("orgs/1/documents/2/a.txt", b"a")
    store.put("orgs/1/documents/2/b.txt", b"b")
    store.put("orgs/2/documents/9/c.txt", b"c")
    assert sorted(store.list("orgs/1")) == [
        "orgs/1/documents/2/a.txt",
        "orgs/1/documents/2/b.txt",
    ]
    assert list(store.list("orgs/9")) == []


def test_traversal_keys_are_rejected(store):
    with pytest.raises(ValueError):
        store.put("../escape.txt", b"x")
    with pytest.raises(FileNotFoundError):
        store.get("orgs/../../etc/passwd")
    assert not store.exists("../escape.txt")
    assert store.stat("/absolute.txt") is None
    store.delete("../escape.txt")  # no-op, no error


def test_fetch_returns_stat_and_bytes_in_one_call(store):
    """fetch() is the serving hot path: stat + stream from a single backend
    call — one GetObject on S3 instead of Head+Get."""
    store.put("orgs/1/photos/9/small.jpg", b"jpegdata", content_type="image/jpeg")
    stat, chunks = store.fetch("orgs/1/photos/9/small.jpg")
    assert stat.size == len(b"jpegdata")
    assert stat.content_type == "image/jpeg"
    assert b"".join(chunks) == b"jpegdata"
    with pytest.raises(FileNotFoundError):
        store.fetch("orgs/1/photos/9/missing.jpg")
    with pytest.raises(FileNotFoundError):
        store.fetch("../escape.jpg")


def test_safe_filename_flattens_exotic_characters():
    """Supabase's S3 layer 400s on keys with e.g. U+202F (macOS screenshot
    names) — safe_filename flattens anything outside the safe charset."""
    assert (
        safe_filename("Screenshot 2025-08-11 at 4.26.18\u202fPM.png")
        == "Screenshot 2025-08-11 at 4.26.18_PM.png"
    )
    assert safe_filename("Deep Research (v2).docx") == "Deep Research (v2).docx"
    assert safe_filename("données_2025.csv") == "donn_es_2025.csv"
    assert safe_filename("\u202f") == "_"  # a lone exotic char still yields a key
    assert safe_filename("") == "file"  # empty basename -> placeholder
