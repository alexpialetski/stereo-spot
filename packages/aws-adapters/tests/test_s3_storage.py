"""Tests for S3 ObjectStorage."""

from stereo_spot_aws_adapters import S3ObjectStorage


class TestS3ObjectStorage:
    """Tests for S3 presign, upload, download."""

    def test_upload_and_download(self, s3_buckets):
        input_bucket, _ = s3_buckets
        storage = S3ObjectStorage(region_name="us-east-1")
        storage.upload(input_bucket, "input/job-1/source.mp4", b"video content here")
        data = storage.download(input_bucket, "input/job-1/source.mp4")
        assert data == b"video content here"

    def test_presign_upload_url(self, s3_buckets):
        input_bucket, _ = s3_buckets
        storage = S3ObjectStorage(region_name="us-east-1")
        url = storage.presign_upload(input_bucket, "input/j1/source.mp4", expires_in=60)
        assert "input/j1/source.mp4" in url or "X-Amz-" in url

    def test_presign_download_url(self, s3_buckets):
        _, output_bucket = s3_buckets
        storage = S3ObjectStorage(region_name="us-east-1")
        storage.upload(output_bucket, "jobs/j1/final.mp4", b"final")
        url = storage.presign_download(output_bucket, "jobs/j1/final.mp4", expires_in=60)
        assert "jobs/j1/final.mp4" in url or "X-Amz-" in url
