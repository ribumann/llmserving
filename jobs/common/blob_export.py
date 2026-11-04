"""Shared helper for uploading an export artifact to the `exports` blob
container in `artifacts_storage` (infra/control/main.tf's
`azapi_resource.artifacts_storage`/`azapi_resource.exports_container`), used
by the `export_worker` job.

The storage account has `allowSharedKeyAccess = false` and no public network
access - only Entra ID (managed-identity) auth over the private endpoint
works, matching every other job's auth pattern (no shared secrets anywhere in
this design, FR-078/FR-081).
"""

from __future__ import annotations

from typing import Any


def _default_credential() -> Any:
    from azure.identity import DefaultAzureCredential

    return DefaultAzureCredential()


def _default_blob_service_client(account_name: str, credential: Any | None) -> Any:
    from azure.storage.blob import BlobServiceClient

    account_url = f"https://{account_name}.blob.core.windows.net"
    return BlobServiceClient(account_url, credential=credential or _default_credential())


def _content_settings(content_type: str) -> Any:
    from azure.storage.blob import ContentSettings

    return ContentSettings(content_type=content_type)


def upload_export(
    account_name: str,
    container_name: str,
    blob_name: str,
    content: bytes,
    *,
    content_type: str = "application/octet-stream",
    credential: Any | None = None,
    client: Any | None = None,
) -> str:
    """Uploads `content` to `{container_name}/{blob_name}` and returns the blob's
    path (not a URL - the account has no public access, so any download path
    goes through a caller-generated user-delegation SAS, not this job)."""
    blob_service_client = client or _default_blob_service_client(account_name, credential)
    container_client = blob_service_client.get_container_client(container_name)
    # Only build the real SDK's ContentSettings type when actually talking to the
    # real BlobServiceClient (which already requires azure-storage-blob to be
    # installed) - a fake `client` injected by tests never needs the real type.
    settings: Any = (
        _content_settings(content_type) if client is None else {"content_type": content_type}
    )
    container_client.upload_blob(
        blob_name,
        content,
        overwrite=True,
        content_settings=settings,
    )
    return f"{container_name}/{blob_name}"
