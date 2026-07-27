"""Singleton lifecycle: the configure(factory) host hook, lazy build,
set_storage override, and the fail-loud unconfigured state."""

import pytest

import asas_storage
from asas_storage import LocalStorage, set_storage, storage


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Each test starts (and leaves the process) unconfigured."""
    asas_storage.configure(None)
    yield
    asas_storage.configure(None)


def test_unconfigured_storage_fails_loud():
    with pytest.raises(RuntimeError, match="not configured"):
        storage()


def test_configure_builds_lazily_and_once(tmp_path):
    calls = []

    def factory():
        calls.append(1)
        return LocalStorage(tmp_path)

    asas_storage.configure(factory)
    assert calls == []  # lazy: nothing built yet
    first = storage()
    assert storage() is first  # cached — factory ran once
    assert calls == [1]


def test_set_storage_overrides_and_none_reselects(tmp_path):
    asas_storage.configure(lambda: LocalStorage(tmp_path / "factory"))
    override = LocalStorage(tmp_path / "override")
    set_storage(override)
    assert storage() is override
    set_storage(None)  # back to lazy re-selection via the factory
    rebuilt = storage()
    assert rebuilt is not override
    assert isinstance(rebuilt, LocalStorage)


def test_reconfigure_drops_cached_instance(tmp_path):
    asas_storage.configure(lambda: LocalStorage(tmp_path / "a"))
    first = storage()
    asas_storage.configure(lambda: LocalStorage(tmp_path / "b"))
    assert storage() is not first


def test_factory_error_propagates(tmp_path):
    """A factory that rejects its config (e.g. s3 selected but unconfigured)
    must fail loud, not fall back."""

    def factory():
        raise RuntimeError("STORAGE_BACKEND=s3 requires STORAGE_S3_BUCKET")

    asas_storage.configure(factory)
    with pytest.raises(RuntimeError, match="STORAGE_S3_BUCKET"):
        storage()
