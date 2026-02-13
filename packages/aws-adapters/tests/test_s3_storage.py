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

    def test_exists(self, s3_buckets):
        input_bucket, _ = s3_buckets
        storage = S3ObjectStorage(region_name="us-east-1")
        assert storage.exists(input_bucket, "missing/key") is False
        storage.upload(input_bucket, "some/key", b"data")
        assert storage.exists(input_bucket, "some/key") is True

    def test_upload_file(self, s3_buckets, tmp_path):
        _, output_bucket = s3_buckets
        storage = S3ObjectStorage(region_name="us-east-1")
        f = tmp_path / "video.mp4"
        f.write_bytes(b"small file content")
        storage.upload_file(output_bucket, "jobs/j1/final.mp4", str(f))
        data = storage.download(output_bucket, "jobs/j1/final.mp4")
        assert data == b"small file content"
