"""S3-compatible backend — any endpoint speaking the S3 API: AWS S3, Supabase
Storage, MinIO, R2. Needs the ``[s3]`` extra (boto3), imported lazily so the
local tier never requires the dependency.

Construction validates config and fails loud: a missing bucket/key must stop
host startup — silently degrading to an ephemeral local disk would lose
uploads on the next redeploy.
"""

from __future__ import annotations

from typing import Iterator, Optional, Tuple

from .base import FileStat, RangeNotSatisfiable, clean_content_type, valid_key

_CHUNK = 64 * 1024
_BATCH = 1000  # delete_objects hard limit


class S3Storage:
    def __init__(
        self,
        *,
        bucket: str,
        access_key: str,
        secret_key: str,
        endpoint_url: str = "",
        region: str = "",
    ):
        missing = [
            name
            for name, value in (
                ("STORAGE_S3_BUCKET", bucket),
                ("STORAGE_S3_ACCESS_KEY", access_key),
                ("STORAGE_S3_SECRET_KEY", secret_key),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(
                "STORAGE_BACKEND=s3 requires " + ", ".join(missing)
            )
        import boto3  # deferred so the local tier never needs the dependency at import time
        from botocore.exceptions import BotoCoreError, ClientError

        self._bucket = bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url or None,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region or None,
        )
        # Probe now: client construction alone never contacts the endpoint, so
        # bad credentials / a missing bucket would otherwise surface on the
        # first upload instead of failing the boot.
        try:
            self._client.head_bucket(Bucket=bucket)
        except (BotoCoreError, ClientError) as exc:
            raise RuntimeError(
                f"Cannot access S3 bucket {bucket!r}"
                f" at {endpoint_url or 'AWS'}: {exc}"
            ) from exc

    def _missing(self, exc) -> bool:
        code = exc.response.get("Error", {}).get("Code", "")
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        return code in ("NoSuchKey", "404", "NotFound") or status == 404

    def put(self, key: str, data: bytes, content_type: Optional[str] = None) -> None:
        if not valid_key(key):
            raise ValueError(f"Invalid storage key: {key!r}")
        # Same hygiene as the Azure backend: an unheaderable caller-supplied
        # value (CR/LF from a client-controlled multipart header) must be
        # dropped, not raise out of urllib3's header validation as a 500.
        content_type = clean_content_type(content_type)
        extra = {"ContentType": content_type} if content_type else {}
        self._client.put_object(Bucket=self._bucket, Key=key, Body=data, **extra)

    def get(self, key: str) -> bytes:
        from botocore.exceptions import ClientError

        if not valid_key(key):
            raise FileNotFoundError(key)
        try:
            obj = self._client.get_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            if self._missing(exc):
                raise FileNotFoundError(key) from exc
            raise
        return obj["Body"].read()

    def stream(self, key: str) -> Iterator[bytes]:
        from botocore.exceptions import ClientError

        if not valid_key(key):
            raise FileNotFoundError(key)
        try:
            obj = self._client.get_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            if self._missing(exc):
                raise FileNotFoundError(key) from exc
            raise
        return obj["Body"].iter_chunks(_CHUNK)

    def fetch(self, key: str) -> Tuple[FileStat, Iterator[bytes]]:
        from botocore.exceptions import ClientError

        if not valid_key(key):
            raise FileNotFoundError(key)
        try:
            obj = self._client.get_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            if self._missing(exc):
                raise FileNotFoundError(key) from exc
            raise
        stat = FileStat(size=obj["ContentLength"], content_type=obj.get("ContentType"))
        return stat, obj["Body"].iter_chunks(_CHUNK)

    def fetch_range(
        self, key: str, start: int, end: int
    ) -> Tuple[FileStat, Iterator[bytes]]:
        from botocore.exceptions import ClientError

        if not valid_key(key):
            raise FileNotFoundError(key)
        if start < 0 or end < start:
            raise RangeNotSatisfiable(f"bytes={start}-{end}")
        try:
            obj = self._client.get_object(
                Bucket=self._bucket, Key=key, Range=f"bytes={start}-{end}"
            )
        except ClientError as exc:
            if self._missing(exc):
                raise FileNotFoundError(key) from exc
            if exc.response.get("Error", {}).get("Code") == "InvalidRange":
                # start past EOF — S3's 416.
                raise RangeNotSatisfiable(f"bytes={start}-{end}") from exc
            raise
        # Ranged GetObject's ContentLength is the RANGE length; the total rides
        # ContentRange ("bytes 0-99/1234"). RFC 9110 lets a server ignore
        # ``Range`` and answer 200 with no ContentRange (AWS does this for
        # zero-byte objects) — ContentLength is the total then.
        content_range = obj.get("ContentRange")
        total = (
            int(content_range.rpartition("/")[2])
            if content_range
            else obj["ContentLength"]
        )
        # ``start == total`` is unsatisfiable per RFC 9110 §14.1.1, and the
        # InvalidRange mapping above is not enough to enforce it: AWS 416s
        # there, but S3-compatible endpoints (the same emulator class that
        # motivated the Azure check, TEAMY-700) can answer an empty 206.
        # Decide the boundary ourselves — Local and Azure already do.
        if start >= total:
            raise RangeNotSatisfiable(f"bytes={start}-{end} of {total}")
        stat = FileStat(size=total, content_type=obj.get("ContentType"))
        return stat, obj["Body"].iter_chunks(_CHUNK)

    def exists(self, key: str) -> bool:
        return self.stat(key) is not None

    def stat(self, key: str) -> Optional[FileStat]:
        from botocore.exceptions import ClientError

        if not valid_key(key):
            return None
        try:
            head = self._client.head_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            if self._missing(exc):
                return None
            raise
        return FileStat(
            size=head["ContentLength"], content_type=head.get("ContentType")
        )

    def delete(self, key: str) -> None:
        if not valid_key(key):
            return
        self._client.delete_object(Bucket=self._bucket, Key=key)

    def delete_prefix(self, prefix: str) -> int:
        keys = list(self.list(prefix))
        for start in range(0, len(keys), _BATCH):
            batch = keys[start : start + _BATCH]
            self._client.delete_objects(
                Bucket=self._bucket,
                Delete={"Objects": [{"Key": k} for k in batch], "Quiet": True},
            )
        return len(keys)

    def list(self, prefix: str) -> Iterator[str]:
        if not valid_key(prefix):
            return
        # Directory semantics, matching LocalStorage: "orgs/1/photos/1" must not
        # match "orgs/1/photos/12".
        prefix = prefix.rstrip("/") + "/"
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
            for item in page.get("Contents", []):
                yield item["Key"]
