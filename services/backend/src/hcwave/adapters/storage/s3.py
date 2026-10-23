"""Amazon S3 (or any S3-compatible store such as MinIO) adapter.

Included to show the portability path: switching ``storage.provider`` to
``s3`` moves report storage to AWS with no code changes elsewhere.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from hcwave.adapters.base import AdapterContext, AdapterSettings
from hcwave.adapters.storage.base import ObjectStorage


class S3Settings(AdapterSettings):
    """Settings for S3. Containers map to buckets (optionally prefixed)."""

    region: str = "ap-south-1"
    endpoint_url: str = ""
    bucket_prefix: str = ""
    kms_key_id: str = ""
    # False streams files through the API (e.g. an in-cluster MinIO whose
    # host name browsers cannot reach).
    presign_urls: bool = True


class S3Storage(ObjectStorage):
    """Object storage backed by S3 (boto3 run in a worker thread)."""

    settings_model = S3Settings
    name = "s3"

    def __init__(self, raw_settings: Mapping[str, Any], ctx: AdapterContext) -> None:
        super().__init__(raw_settings, ctx)
        import boto3

        self._s3 = boto3.client(
            "s3", region_name=self.config.region, endpoint_url=self.config.endpoint_url or None
        )

    def _bucket(self, container: str) -> str:
        return f"{self.config.bucket_prefix}{container}"

    async def put(self, container: str, path: str, data: bytes, content_type: str) -> None:
        """Uploads an object with server-side encryption."""
        extra: dict[str, Any] = {}
        if self.config.kms_key_id:
            extra = {"ServerSideEncryption": "aws:kms", "SSEKMSKeyId": self.config.kms_key_id}
        elif not self.config.endpoint_url:  # S3-compatible stores may lack SSE support
            extra = {"ServerSideEncryption": "AES256"}
        await asyncio.to_thread(
            self._s3.put_object,
            Bucket=self._bucket(container),
            Key=path,
            Body=data,
            ContentType=content_type,
            **extra,
        )

    async def get(self, container: str, path: str) -> bytes:
        """Downloads an object."""
        try:
            response = await asyncio.to_thread(
                self._s3.get_object, Bucket=self._bucket(container), Key=path
            )
        except self._s3.exceptions.NoSuchKey as exc:
            raise FileNotFoundError(f"{container}/{path}") from exc
        return await asyncio.to_thread(response["Body"].read)

    async def list(self, container: str, prefix: str = "") -> list[str]:
        """Lists keys (first 1000)."""
        response = await asyncio.to_thread(
            self._s3.list_objects_v2, Bucket=self._bucket(container), Prefix=prefix
        )
        return [item["Key"] for item in response.get("Contents", [])]

    async def delete(self, container: str, path: str) -> None:
        """Deletes an object."""
        await asyncio.to_thread(self._s3.delete_object, Bucket=self._bucket(container), Key=path)

    async def temporary_url(
        self, container: str, path: str, ttl_minutes: int, download_name: str
    ) -> str | None:
        """Returns a presigned GET URL (or None to stream through the API)."""
        if not self.config.presign_urls:
            return None
        return await asyncio.to_thread(
            self._s3.generate_presigned_url,
            "get_object",
            Params={
                "Bucket": self._bucket(container),
                "Key": path,
                "ResponseContentDisposition": f'inline; filename="{download_name}"',
            },
            ExpiresIn=ttl_minutes * 60,
        )
