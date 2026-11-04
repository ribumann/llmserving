from __future__ import annotations

from common.blob_export import upload_export


class _FakeContainerClient:
    def __init__(self) -> None:
        self.uploaded: dict[str, bytes] = {}
        self.content_settings: dict[str, object] = {}

    def upload_blob(self, blob_name, content, *, overwrite, content_settings) -> None:
        assert overwrite is True
        self.uploaded[blob_name] = content
        self.content_settings[blob_name] = content_settings


class _FakeBlobServiceClient:
    def __init__(self) -> None:
        self.container_client = _FakeContainerClient()
        self.requested_containers: list[str] = []

    def get_container_client(self, container_name: str) -> _FakeContainerClient:
        self.requested_containers.append(container_name)
        return self.container_client


def test_upload_export_writes_content_and_returns_blob_path() -> None:
    client = _FakeBlobServiceClient()
    path = upload_export(
        "acct1",
        "exports",
        "run-1.json",
        b'{"a": 1}',
        content_type="application/json",
        client=client,
    )

    assert path == "exports/run-1.json"
    assert client.requested_containers == ["exports"]
    assert client.container_client.uploaded["run-1.json"] == b'{"a": 1}'
