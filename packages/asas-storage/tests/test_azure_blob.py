"""AzureBlobStorage construction rules (TEAMY-71).

These assertions deliberately run *without* the Azure SDK installed: the
config checks happen before the deferred import, so a misconfigured host
fails with a message naming the missing setting rather than an ImportError.
The behavioural contract itself is covered by the shared parity fixture in
test_contract.py.
"""

import pytest

from asas_storage import AzureBlobStorage


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
