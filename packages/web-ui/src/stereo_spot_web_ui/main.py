"""FastAPI app: server-rendered pages for dashboard, jobs, create, detail, play."""

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from stereo_spot_shared import configure_logging

from .config import bootstrap_env
from .constants import STATIC_DIR, TEMPLATES_DIR
from .deps import get_operator_links_provider
from .routers.jobs import router as jobs_router
from .routers.launch import router as launch_router

# Load .env from STEREOSPOT_ENV_FILE if set (e.g. by nx run web-ui:serve). Unset in ECS.
bootstrap_env()

# Root logger level (events stream logs at DEBUG); uvicorn --log-level only affects uvicorn.
configure_logging()

app = FastAPI(title="Stereo-Spot Web UI", version="0.1.0")


def _cost_explorer_context(request: Request) -> dict:
    """Inject cost_explorer_url into all templates (from OperatorLinksProvider when available)."""
    provider = get_operator_links_provider(request)
    url = provider.get_cost_dashboard_url() if provider else None
    return {"cost_explorer_url": url}


templates = Jinja2Templates(
    directory=str(TEMPLATES_DIR),
    context_processors=[_cost_explorer_context],
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.state.templates = templates

# Launch first so /playlist.m3u and /playlist/... are matched before any catch-all in jobs.
app.include_router(launch_router)
app.include_router(jobs_router)
