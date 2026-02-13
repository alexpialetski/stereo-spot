"""S3 implementation of ObjectStorage."""

import boto3


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

    def download(self, bucket: str, key: str) -> bytes:
        """Download object from bucket/key and return its body as bytes."""
        resp = self._client.get_object(Bucket=bucket, Key=key)
        return resp["Body"].read()
