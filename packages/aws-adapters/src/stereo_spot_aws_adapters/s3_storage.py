"""S3 implementation of ObjectStorage."""

import os

import boto3
from botocore.exceptions import ClientError

# Minimum S3 multipart part size (except last) is 5 MB
MULTIPART_CHUNK_SIZE = 8 * 1024 * 1024  # 8 MB
MULTIPART_THRESHOLD = 100 * 1024 * 1024  # 100 MB: use multipart above this


class S3ObjectStorage:
    """ObjectStorage implementation using S3."""

    def __init__(
        self,
        *,
        region_name: str | None = None,
        endpoint_url: str | None = None,
    ) -> None:
        self._client = boto3.client(
            "s3",
            region_name=region_name,
            endpoint_url=endpoint_url,
        )

    def presign_upload(
        self,
        bucket: str,
        key: str,
        *,
        expires_in: int = 3600,
    ) -> str:
        """Return a presigned PUT URL for the given bucket and key."""
        return self._client.generate_presigned_url(
            "put_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=expires_in,
        )

    def presign_download(
        self,
        bucket: str,
        key: str,
        *,
        expires_in: int = 3600,
    ) -> str:
        """Return a presigned GET URL for the given bucket and key."""
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=expires_in,
        )

    def upload(self, bucket: str, key: str, body: bytes) -> None:
        """Upload bytes to the given bucket and key."""
        self._client.put_object(Bucket=bucket, Key=key, Body=body)

    def upload_file(self, bucket: str, key: str, path: str) -> None:
        """Upload a file from local path; uses multipart for files over 100 MB."""
        file_size = os.path.getsize(path)
        if file_size >= MULTIPART_THRESHOLD:
            self._upload_multipart(bucket, key, path, file_size)
        else:
            with open(path, "rb") as f:
                self._client.put_object(Bucket=bucket, Key=key, Body=f.read())

    def _upload_multipart(self, bucket: str, key: str, path: str, file_size: int) -> None:
        """Upload using S3 multipart API for large files."""
        resp = self._client.create_multipart_upload(Bucket=bucket, Key=key)
        upload_id = resp["UploadId"]
        parts: list[dict] = []
        try:
            with open(path, "rb") as f:
                part_number = 1
                while True:
                    chunk = f.read(MULTIPART_CHUNK_SIZE)
                    if not chunk:
                        break
                    part_resp = self._client.upload_part(
                        Bucket=bucket,
                        Key=key,
                        UploadId=upload_id,
                        PartNumber=part_number,
                        Body=chunk,
                    )
                    parts.append({"ETag": part_resp["ETag"], "PartNumber": part_number})
                    part_number += 1
            self._client.complete_multipart_upload(
                Bucket=bucket,
                Key=key,
                UploadId=upload_id,
                MultipartUpload={"Parts": parts},
            )
        except Exception:
            self._client.abort_multipart_upload(
                Bucket=bucket, Key=key, UploadId=upload_id
            )
            raise

    def exists(self, bucket: str, key: str) -> bool:
        """Return True if the object exists, False otherwise."""
        try:
            self._client.head_object(Bucket=bucket, Key=key)
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] in ("404", "NoSuchKey"):
                return False
            raise

    def download(self, bucket: str, key: str) -> bytes:
        """Download object from bucket/key and return its body as bytes."""
        resp = self._client.get_object(Bucket=bucket, Key=key)
        return resp["Body"].read()
