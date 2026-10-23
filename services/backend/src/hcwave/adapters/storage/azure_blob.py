"""Azure Blob Storage adapter.

The storage account has public access and shared keys disabled, so signed
links are *user delegation* SAS tokens minted with the workload identity
(``Storage Blob Data Contributor`` + ``Storage Blob Delegator``). Encryption at
rest is on by default; customer-managed keys can be enabled in Bicep.
"""

from __future__ import annotations

import contextlib
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from hcwave.adapters.base import AdapterContext, AdapterSettings
from hcwave.adapters.storage.base import ObjectStorage


class AzureBlobSettings(AdapterSettings):
    """Settings for Azure Blob Storage.

    Attributes:
        account_url: ``https://<account>.blob.core.windows.net``.
        connection_string: Optional (Azurite/local only); empty = Entra ID.
        signed_url_host: Optional host override when blobs are served through
            Front Door; leave empty to use the account URL.
    """

    account_url: str = ""
    connection_string: str = ""
    signed_url_host: str = ""


class AzureBlobStorage(ObjectStorage):
    """Object storage backed by Azure Blob Storage."""

    settings_model = AzureBlobSettings
    name = "azure_blob"

    def __init__(self, raw_settings: Mapping[str, Any], ctx: AdapterContext) -> None:
        super().__init__(raw_settings, ctx)
        self._client: Any = None

    def _service(self) -> Any:
        if self._client is None:
            from azure.storage.blob.aio import BlobServiceClient

            if self.config.connection_string:
                self._client = BlobServiceClient.from_connection_string(
                    self.config.connection_string
                )
            else:
                self._client = BlobServiceClient(
                    self.config.account_url, credential=self.ctx.credentials.aio
                )
        return self._client

    async def put(self, container: str, path: str, data: bytes, content_type: str) -> None:
        """Uploads a blob."""
        from azure.storage.blob import ContentSettings

        blob = self._service().get_blob_client(container, path)
        await blob.upload_blob(
            data, overwrite=True, content_settings=ContentSettings(content_type=content_type)
        )

    async def get(self, container: str, path: str) -> bytes:
        """Downloads a blob."""
        from azure.core.exceptions import ResourceNotFoundError

        try:
            stream = await self._service().get_blob_client(container, path).download_blob()
            return await stream.readall()
        except ResourceNotFoundError as exc:
            raise FileNotFoundError(f"{container}/{path}") from exc

    async def list(self, container: str, prefix: str = "") -> list[str]:
        """Lists blob names."""
        client = self._service().get_container_client(container)
        return [blob.name async for blob in client.list_blobs(name_starts_with=prefix or None)]

    async def delete(self, container: str, path: str) -> None:
        """Deletes a blob if present."""
        from azure.core.exceptions import ResourceNotFoundError

        with contextlib.suppress(ResourceNotFoundError):
            await self._service().get_blob_client(container, path).delete_blob()

    async def temporary_url(
        self, container: str, path: str, ttl_minutes: int, download_name: str
    ) -> str | None:
        """Mints a read-only user delegation SAS valid for ``ttl_minutes``."""
        from azure.storage.blob import BlobSasPermissions, generate_blob_sas

        service = self._service()
        start = datetime.now(UTC) - timedelta(minutes=2)  # clock-skew allowance
        expiry = datetime.now(UTC) + timedelta(minutes=ttl_minutes)
        if self.config.connection_string:
            sas = generate_blob_sas(
                account_name=service.account_name,
                container_name=container,
                blob_name=path,
                account_key=service.credential.account_key,
                permission=BlobSasPermissions(read=True),
                start=start,
                expiry=expiry,
                content_disposition=f'inline; filename="{download_name}"',
            )
        else:
            delegation_key = await service.get_user_delegation_key(start, expiry)
            sas = generate_blob_sas(
                account_name=service.account_name,
                container_name=container,
                blob_name=path,
                user_delegation_key=delegation_key,
                permission=BlobSasPermissions(read=True),
                start=start,
                expiry=expiry,
                protocol="https",
                content_disposition=f'inline; filename="{download_name}"',
            )
        base = (self.config.signed_url_host or service.url).rstrip("/")
        return f"{base}/{container}/{path}?{sas}"

    async def aclose(self) -> None:
        """Closes the client."""
        if self._client is not None:
            await self._client.close()
