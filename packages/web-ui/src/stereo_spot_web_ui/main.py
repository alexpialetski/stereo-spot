"""FastAPI app: server-rendered pages for dashboard, jobs, create, detail, play."""

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from stereo_spot_shared import configure_logging

from .config import bootstrap_env
from .constants import STATIC_DIR, TEMPLATES_DIR
from .deps import get_operator_links_provider
from .job_events_consumer import run_job_events_consumer
from .routers.jobs import router as jobs_router
from .routers.launch import router as launch_router

# Load .env from STEREOSPOT_ENV_FILE if set (e.g. by nx run web-ui:serve). Unset in ECS.
bootstrap_env()

# Root logger level (events stream logs at DEBUG); uvicorn --log-level only affects uvicorn.
configure_logging()


def _load_vapid_from_secrets_manager_if_configured() -> None:
    """Load VAPID keys from Secrets Manager when VAPID_SECRET_ARN is set."""
    secret_arn = os.environ.get("VAPID_SECRET_ARN")
    if not secret_arn:
        return
    try:
        import boto3

        client = boto3.client("secretsmanager")
        resp = client.get_secret_value(SecretId=secret_arn)
        data = json.loads(resp["SecretString"])
        os.environ["VAPID_PUBLIC_KEY"] = data.get("vapid_public_key", "")
        os.environ["VAPID_PRIVATE_KEY"] = data.get("vapid_private_key", "")
        logging.getLogger(__name__).info("VAPID keys loaded from Secrets Manager")
    except Exception as e:
        logging.getLogger(__name__).warning(
            "VAPID: failed to load from Secrets Manager: %s", e
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start job-events consumer when JOB_EVENTS_QUEUE_URL is set; stop on shutdown."""
    _load_vapid_from_secrets_manager_if_configured()
    registry: dict = {}
    app.state.job_events_registry = registry
    receiver = None
    push_store = None
    job_store = None
    segment_store = None
    normalizer = None
    try:
        from stereo_spot_adapters.env_config import (
            job_events_normalizer_from_env,
            job_events_queue_receiver_from_env_or_none,
            job_store_from_env,
            push_subscriptions_store_from_env_or_none,
            segment_completion_store_from_env,
        )

        receiver = job_events_queue_receiver_from_env_or_none()
        push_store = push_subscriptions_store_from_env_or_none()
        if receiver:
            job_store = job_store_from_env()
            segment_store = segment_completion_store_from_env()
            normalizer = job_events_normalizer_from_env()
    except Exception:
        pass
    app.state.job_events_receiver = receiver
    app.state.push_subscriptions_store = push_store
    app.state.job_store = job_store
    app.state.segment_completion_store = segment_store
    app.state.vapid_public_key = os.environ.get("VAPID_PUBLIC_KEY", "")
    vapid_private = os.environ.get("VAPID_PRIVATE_KEY")
    base_url = os.environ.get("WEB_UI_URL", "http://localhost:8000")
    task = None
    if receiver and job_store is not None and segment_store is not None and normalizer is not None:
        task = asyncio.create_task(
            run_job_events_consumer(
                receiver,
                registry,
                job_store,
                segment_store,
                normalizer,
                push_subscriptions_store=push_store,
                vapid_private_key=vapid_private,
                base_url=base_url,
            )
        )
    yield
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Stereo-Spot Web UI", version="0.1.0", lifespan=lifespan)


def _cost_explorer_context(request: Request) -> dict:
    """Inject cost_explorer_url into all templates (from OperatorLinksProvider when available)."""
    provider = get_operator_links_provider(request)
    url = provider.get_cost_dashboard_url() if provider else None
    return {"cost_explorer_url": url}


templates = Jinja2Templates(
    directory=str(TEMPLATES_DIR),
    context_processors=[_cost_explorer_context],
)


@app.get("/static/sw.js", response_class=FileResponse)
def _serve_service_worker():
    """Serve the service worker with Service-Worker-Allowed: / so it can use scope '/'."""
    path = STATIC_DIR / "sw.js"
    return FileResponse(
        path,
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/"},
    )


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.state.templates = templates

# Launch first so /playlist.m3u and /playlist/... are matched before any catch-all in jobs.
app.include_router(launch_router)
app.include_router(jobs_router)
