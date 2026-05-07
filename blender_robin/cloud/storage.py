"""
Generic object storage client.
Supports S3-compatible backends: AWS S3, Alibaba OSS, Baidu BOS, MinIO, etc.

All providers speak the S3 API via boto3 / aiobotocore — just point the
endpoint_url to your provider and supply credentials.

Usage examples
--------------
# Local MinIO
store = ObjectStore.from_env()   # reads ROBIN_STORAGE_* env vars

# Explicit config
store = ObjectStore(
    bucket="my-renders",
    endpoint="http://minio.internal:9000",
    access_key="minioadmin",
    secret_key="minioadmin",
    region="us-east-1",
)

# Sync upload / download
store.upload_file("local/file.png", "renders/output.png")
store.download_file("renders/output.png", "local/file.png")

# Async upload / download
await store.upload_file_async("local/file.png", "renders/output.png")
await store.download_file_async("renders/output.png", "local/file.png")
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import List, Optional


class StorageError(Exception):
    pass


class ObjectStore:
    """S3-compatible object store wrapper (sync + async)."""

    # Provider endpoint shortcuts
    ENDPOINTS = {
        "aws": None,                             # use boto3 default
        "bos": "http://s3.bj.bcebos.com",        # Baidu BOS (Beijing)
        "bos-gz": "http://s3.gz.bcebos.com",     # Baidu BOS (Guangzhou)
        "oss": "https://oss-cn-hangzhou.aliyuncs.com",  # Alibaba OSS
        "minio": "http://localhost:9000",
    }

    def __init__(
        self,
        bucket: str,
        access_key: str,
        secret_key: str,
        region: str = "us-east-1",
        endpoint: Optional[str] = None,
        provider: Optional[str] = None,
    ):
        self.bucket = bucket
        self._access_key = access_key
        self._secret_key = secret_key
        self._region = region
        # Resolve endpoint from provider alias or direct value
        if endpoint is None and provider:
            endpoint = self.ENDPOINTS.get(provider)
        self._endpoint = endpoint

    @classmethod
    def from_env(cls) -> "ObjectStore":
        """Build from environment variables.

        Required:
            ROBIN_STORAGE_BUCKET
            ROBIN_STORAGE_ACCESS_KEY
            ROBIN_STORAGE_SECRET_KEY
        Optional:
            ROBIN_STORAGE_ENDPOINT   (e.g. http://s3.bj.bcebos.com)
            ROBIN_STORAGE_PROVIDER   (aws|bos|oss|minio)
            ROBIN_STORAGE_REGION     (default: us-east-1)
        """
        bucket = os.environ["ROBIN_STORAGE_BUCKET"]
        access_key = os.environ["ROBIN_STORAGE_ACCESS_KEY"]
        secret_key = os.environ["ROBIN_STORAGE_SECRET_KEY"]
        endpoint = os.environ.get("ROBIN_STORAGE_ENDPOINT")
        provider = os.environ.get("ROBIN_STORAGE_PROVIDER")
        region = os.environ.get("ROBIN_STORAGE_REGION", "us-east-1")
        return cls(bucket, access_key, secret_key, region, endpoint, provider)

    def _boto_kwargs(self) -> dict:
        kw: dict = dict(
            region_name=self._region,
            aws_access_key_id=self._access_key,
            aws_secret_access_key=self._secret_key,
        )
        if self._endpoint:
            kw["endpoint_url"] = self._endpoint
        return kw

    # ── Sync ──────────────────────────────────────────────────────────────

    def upload_file(self, local_path: str | Path, remote_key: str) -> None:
        """Upload a local file to the object store."""
        try:
            import boto3
        except ImportError:
            raise StorageError("boto3 is required: pip install boto3")

        s3 = boto3.client("s3", **self._boto_kwargs())
        s3.upload_file(str(local_path), self.bucket, remote_key)

    def download_file(self, remote_key: str, local_path: str | Path) -> None:
        """Download a remote object to a local file."""
        try:
            import boto3
        except ImportError:
            raise StorageError("boto3 is required: pip install boto3")

        Path(local_path).parent.mkdir(parents=True, exist_ok=True)
        s3 = boto3.client("s3", **self._boto_kwargs())
        s3.download_file(self.bucket, remote_key, str(local_path))

    def list_keys(self, prefix: str = "") -> List[str]:
        """List all object keys under a prefix."""
        try:
            import boto3
        except ImportError:
            raise StorageError("boto3 is required: pip install boto3")

        s3 = boto3.client("s3", **self._boto_kwargs())
        paginator = s3.get_paginator("list_objects_v2")
        keys = []
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                keys.append(obj["Key"])
        return keys

    def key_exists(self, remote_key: str) -> bool:
        try:
            import boto3
            from botocore.exceptions import ClientError
        except ImportError:
            raise StorageError("boto3 is required: pip install boto3")

        s3 = boto3.client("s3", **self._boto_kwargs())
        try:
            s3.head_object(Bucket=self.bucket, Key=remote_key)
            return True
        except ClientError:
            return False

    def upload_directory(self, local_dir: str | Path, remote_prefix: str) -> List[str]:
        """Upload all files in a local directory, return list of uploaded keys."""
        local_dir = Path(local_dir)
        uploaded = []
        for f in local_dir.rglob("*"):
            if not f.is_file():
                continue
            relative = f.relative_to(local_dir)
            key = f"{remote_prefix.rstrip('/')}/{relative.as_posix()}"
            self.upload_file(f, key)
            uploaded.append(key)
        return uploaded

    # ── Async ─────────────────────────────────────────────────────────────

    async def upload_file_async(
        self, local_path: str | Path, remote_key: str,
        semaphore: asyncio.Semaphore = None,
    ) -> tuple[bool, str]:
        """Async upload. Returns (success, error_message)."""
        try:
            import aiobotocore.session as aio_s3
        except ImportError:
            raise StorageError("aiobotocore is required: pip install aiobotocore")

        sem = semaphore or asyncio.Semaphore(1)
        async with sem:
            session = aio_s3.get_session()
            try:
                async with session.create_client("s3", **self._boto_kwargs()) as client:
                    import aiofiles
                    async with aiofiles.open(local_path, "rb") as f:
                        data = await f.read()
                    await client.put_object(Bucket=self.bucket, Key=remote_key, Body=data)
                    return True, ""
            except Exception as e:
                return False, f"upload {remote_key} failed: {e}"

    async def download_file_async(
        self, remote_key: str, local_path: str | Path,
        semaphore: asyncio.Semaphore = None,
    ) -> tuple[bool, str]:
        """Async download. Returns (success, error_message)."""
        try:
            import aiobotocore.session as aio_s3
        except ImportError:
            raise StorageError("aiobotocore is required: pip install aiobotocore")

        sem = semaphore or asyncio.Semaphore(1)
        Path(local_path).parent.mkdir(parents=True, exist_ok=True)
        async with sem:
            session = aio_s3.get_session()
            try:
                async with session.create_client("s3", **self._boto_kwargs()) as client:
                    resp = await client.get_object(Bucket=self.bucket, Key=remote_key)
                    import aiofiles
                    async with aiofiles.open(local_path, "wb") as f:
                        await f.write(await resp["Body"].read())
                    return True, ""
            except Exception as e:
                return False, f"download {remote_key} failed: {e}"

    async def upload_directory_async(
        self,
        local_dir: str | Path,
        remote_prefix: str,
        concurrency: int = 5,
    ) -> list[tuple[bool, str]]:
        """Upload all files in a directory concurrently."""
        local_dir = Path(local_dir)
        files = [f for f in local_dir.rglob("*") if f.is_file()]
        sem = asyncio.Semaphore(concurrency)
        tasks = []
        for f in files:
            relative = f.relative_to(local_dir)
            key = f"{remote_prefix.rstrip('/')}/{relative.as_posix()}"
            tasks.append(self.upload_file_async(f, key, sem))
        return await asyncio.gather(*tasks)
