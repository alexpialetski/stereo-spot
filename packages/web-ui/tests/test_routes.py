"""Unit tests for web-ui: utils, static files."""

from fastapi.testclient import TestClient

from stereo_spot_web_ui.utils import normalize_title_for_storage, safe_download_filename


def test_normalize_title_for_storage() -> None:
    """Title normalization: basename, strip extension, safe chars."""
    assert normalize_title_for_storage("attack-on-titan.mp4") == "attack-on-titan"
    assert normalize_title_for_storage("/path/to/video.mp4") == "video"
    assert normalize_title_for_storage("my video (1).mp4") == "my_video__1"


def test_safe_download_filename() -> None:
    """Download filename: title -> base3d.mp4; no title -> final.mp4."""
    assert safe_download_filename("attack-on-titan") == "attack-on-titan3d.mp4"
    assert safe_download_filename(None) == "final.mp4"
    assert safe_download_filename("") == "final.mp4"


def test_static_favicon_served(client: TestClient) -> None:
    """Static files are served from /static."""
    response = client.get("/static/favicon.png", follow_redirects=False)
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
