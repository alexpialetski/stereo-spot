"""
Basic integration test: env and web-ui API work against moto-backed resources.

Does not require ffmpeg. Ensures the integration fixture and create-job flow are wired.
"""

from fastapi.testclient import TestClient
from stereo_spot_adapters.env_config import job_store_from_env
from stereo_spot_shared import JobStatus
from stereo_spot_web_ui.main import app


def test_create_job_via_api_against_moto(integration_env: dict[str, str]) -> None:
    """Create job via POST /jobs; assert job exists in DynamoDB (moto) with status created."""
    client = TestClient(app)
    response = client.post("/jobs", data={"mode": "anaglyph"}, follow_redirects=False)
    assert response.status_code == 303
    location = response.headers["location"]
    assert "/jobs/" in location
    job_id = location.split("/jobs/")[1].rstrip("/")
    assert job_id

    job_store = job_store_from_env()
    job = job_store.get(job_id)
    assert job is not None
    assert job.job_id == job_id
    assert job.status == JobStatus.CREATED
