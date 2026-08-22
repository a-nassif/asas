"""LocalStorage durability: atomic overwrite (readers never see a torn
object), fetch/stat consistency under concurrent replacement, and the
put-vs-prune directory race. The bucket backends get these properties from
the service; the local backend has to construct them."""

from pathlib import Path

import pytest

from asas_storage import LocalStorage


def test_fetch_stat_matches_stream_across_overwrite(tmp_path):
    """The size fetch() reports must describe the bytes its iterator yields,
    even when the object is replaced between the call and consumption —
    a serving layer emits Content-Length from it."""
    store = LocalStorage(tmp_path)
    store.put("k/f.bin", b"a" * 1000)
    stat, chunks = store.fetch("k/f.bin")
    store.put("k/f.bin", b"b" * 5)  # replaced before the stream is consumed
    body = b"".join(chunks)
    assert len(body) == stat.size == 1000
    assert body == b"a" * 1000  # the complete pre-overwrite object, not a mix


def test_fetch_range_consistent_across_overwrite(tmp_path):
    store = LocalStorage(tmp_path)
    payload = bytes(range(256)) * 4
    store.put("k/f.bin", payload)
    stat, chunks = store.fetch_range("k/f.bin", 100, 199)
    store.put("k/f.bin", b"tiny")
    assert b"".join(chunks) == payload[100:200]
    assert stat.size == len(payload)


def test_overwrite_leaves_no_partial_state_on_disk(tmp_path):
    """put() must land whole-or-not-at-all: after an overwrite the key holds
    exactly the new bytes and no temp artifacts remain."""
    store = LocalStorage(tmp_path)
    store.put("k/f.bin", b"x" * 4096)
    store.put("k/f.bin", b"y" * 128)
    assert store.get("k/f.bin") == b"y" * 128
    assert [p.name for p in (tmp_path / "k").iterdir()] == ["f.bin"]


def test_put_survives_concurrent_prune_of_parent(tmp_path, monkeypatch):
    """delete()'s _prune_empty_dirs can remove the parent directory between
    put()'s mkdir and its write landing — put must retry, not lose the
    upload to FileNotFoundError."""
    store = LocalStorage(tmp_path)
    original = Path.write_bytes
    pruned = []

    def write_bytes_with_prune(self, data):
        if not pruned:  # first attempt: simulate the prune winning the race
            pruned.append(True)
            for p in (self.parent, self.parent.parent):
                if p != tmp_path:
                    p.rmdir()
            # the directory is gone — the real write now fails as in the race
        return original(self, data)

    monkeypatch.setattr(Path, "write_bytes", write_bytes_with_prune)
    store.put("orgs/1/a.bin", b"payload")
    assert store.get("orgs/1/a.bin") == b"payload"


def test_delete_prefix_then_put_same_tree(tmp_path):
    """The sequential shape of the race: prune the tree, then re-put under
    the same directories."""
    store = LocalStorage(tmp_path)
    store.put("orgs/1/photos/5/a.jpg", b"1")
    store.delete("orgs/1/photos/5/a.jpg")
    assert not (tmp_path / "orgs").exists()  # pruned to the root
    store.put("orgs/1/photos/5/a.jpg", b"2")
    assert store.get("orgs/1/photos/5/a.jpg") == b"2"
