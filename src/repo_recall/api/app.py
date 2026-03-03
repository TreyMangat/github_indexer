from __future__ import annotations

import logging
import os
import platform
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Generator, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from starlette.requests import Request

from .. import __version__
from ..catalog.db import get_github_index_run, list_github_index_runs
from ..catalog.jobs import CatalogJobRunner
from ..catalog.scheduler import CatalogSweepScheduler
from ..catalog.webhooks import verify_github_webhook_signature
from ..config import Settings, get_settings
from ..db import (
    connect,
    db_ping,
    get_index_run,
    get_index_stats,
    get_pgvector_version,
    get_repo_details,
    init_db,
    list_index_runs,
    list_repos,
)
from ..jobs import JobRunner
from ..logging import setup_logging
from ..retrieval.search import search_repos

setup_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title="Repo Recall API", version=__version__)
settings: Settings = get_settings()

# Jobs are optional (primarily used by the UI).
job_runner: Optional[JobRunner] = None
catalog_job_runner: Optional[CatalogJobRunner] = None
catalog_scheduler: Optional[CatalogSweepScheduler] = None


# --- Models ---


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    top_k_repos: int = Field(default=5, ge=1, le=20)
    top_k_chunks: int = Field(default=3, ge=1, le=10)


class IndexRequest(BaseModel):
    repo: str = Field(..., min_length=1, description="Local path or git URL")
    incremental: bool = Field(default=True, description="If true, uses git diff / file hashes")


class CatalogSuggestRequest(BaseModel):
    actor_id: str = Field(..., min_length=1)
    query: Optional[str] = Field(default="", description="Optional repo/branch query")
    org: Optional[str] = Field(default=None)
    top_k_repos: int = Field(default=5, ge=1, le=50)
    top_k_branches_per_repo: int = Field(default=5, ge=1, le=50)
    github_token: Optional[str] = Field(
        default=None,
        description="Optional short-lived OAuth token used to bootstrap sync if cache is empty",
    )


class CatalogSyncRequest(BaseModel):
    actor_id: str = Field(..., min_length=1)
    scope: str = Field(default="incremental", description="full | incremental | webhook")
    org: Optional[str] = Field(default=None)
    github_token: Optional[str] = Field(default=None, description="Short-lived OAuth token")
    source_token_owner: Optional[str] = Field(default=None)
    repo_full_name: Optional[str] = Field(default=None, description="Optional owner/repo for targeted sync")


class CatalogSetTokenRequest(BaseModel):
    actor_id: str = Field(..., min_length=1)
    github_token: str = Field(..., min_length=1)
    ttl_seconds: int = Field(default=3600, ge=60, le=86_400)


class CatalogSeedDemoRequest(BaseModel):
    actor_id: str = Field(..., min_length=1)
    org: str = Field(default="demo-org", min_length=1)


# --- Dependencies ---


def get_conn() -> Generator[Any, None, None]:
    conn = connect(settings)
    try:
        yield conn
    finally:
        try:
            conn.close()
        except Exception:
            pass


def require_auth(
    authorization: Optional[str] = Header(default=None),
    x_ff_token: Optional[str] = Header(default=None, alias="X-FF-Token"),
) -> None:
    if settings.auth_mode == "disabled":
        return

    token = settings.api_auth_token
    if not token:
        # Misconfiguration: auth enabled but no token configured.
        raise HTTPException(
            status_code=500, detail="AUTH_MODE=api_token but API_AUTH_TOKEN is not set"
        )

    provided: Optional[str] = None
    if x_ff_token:
        provided = x_ff_token.strip()
    elif authorization and authorization.lower().startswith("bearer "):
        provided = authorization.split(" ", 1)[1].strip()

    if not provided:
        raise HTTPException(status_code=401, detail="Missing API token")

    if provided != token:
        raise HTTPException(status_code=403, detail="Invalid API token")


def _catalog_runner_or_404() -> CatalogJobRunner:
    if not settings.enable_catalog:
        raise HTTPException(status_code=404, detail="Catalog disabled")
    global catalog_job_runner
    if catalog_job_runner is None:
        raise HTTPException(status_code=503, detail="Catalog runner unavailable")
    return catalog_job_runner


def _require_catalog_dev_endpoints() -> None:
    if not settings.enable_catalog_dev_endpoints:
        raise HTTPException(status_code=404, detail="Catalog dev endpoints disabled")


# --- Lifecycle ---


@app.on_event("startup")
def _startup() -> None:
    if settings.init_db_on_startup:
        with connect(settings) as conn:
            init_db(conn)
        logger.info("DB initialized")

    global job_runner
    if settings.enable_ui:
        job_runner = JobRunner(settings)
        logger.info("Job runner started (JOB_WORKERS=%d)", settings.job_workers)

    global catalog_job_runner, catalog_scheduler
    if settings.enable_catalog:
        catalog_job_runner = CatalogJobRunner(settings)
        catalog_scheduler = CatalogSweepScheduler(
            runner=catalog_job_runner,
            interval_seconds=settings.catalog_sync_interval_seconds,
        )
        catalog_scheduler.start()
        logger.info(
            "Catalog runner started (interval=%ss)",
            settings.catalog_sync_interval_seconds,
        )

    logger.info("API started")


@app.on_event("shutdown")
def _shutdown() -> None:
    global job_runner, catalog_job_runner, catalog_scheduler
    if job_runner is not None:
        job_runner.shutdown()
        job_runner = None
    if catalog_scheduler is not None:
        catalog_scheduler.stop()
        catalog_scheduler = None
    if catalog_job_runner is not None:
        catalog_job_runner.shutdown()
        catalog_job_runner = None


# --- UI ---


_ui_root = Path(__file__).resolve().parent.parent / "ui"
_templates_dir = _ui_root / "templates"
_static_dir = _ui_root / "static"

if _static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")

templates = Jinja2Templates(directory=str(_templates_dir))


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse(url="/ui")


@app.get("/ui", include_in_schema=False)
def ui(request: Request) -> Any:
    if not settings.enable_ui:
        raise HTTPException(status_code=404, detail="UI disabled")
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "title": "Repo Recall",
        },
    )


@app.get("/ui/catalog", include_in_schema=False)
def ui_catalog(request: Request) -> Any:
    if not settings.enable_ui:
        raise HTTPException(status_code=404, detail="UI disabled")
    return templates.TemplateResponse(
        "catalog.html",
        {
            "request": request,
            "title": "Repo Recall Catalog",
            "enable_catalog_dev_endpoints": settings.enable_catalog_dev_endpoints,
        },
    )


# --- Health ---


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready")
def ready(conn: Any = Depends(get_conn)) -> dict[str, Any]:
    try:
        db_ping(conn)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"DB not ready: {e}")

    v = get_pgvector_version(conn)
    if not v:
        raise HTTPException(status_code=503, detail="pgvector extension is not installed")

    return {"status": "ready", "db": "ok", "pgvector": v}


@app.get("/health/runtime")
def runtime() -> dict[str, Any]:
    return {
        "name": "repo-recall",
        "version": __version__,
        "app_env": settings.app_env,
        "mock_mode": settings.mock_mode,
        "auth_mode": settings.auth_mode,
        "ui_enabled": settings.enable_ui,
        "init_db_on_startup": settings.init_db_on_startup,
        "embedding": {
            "enabled": bool(settings.openai_api_key) and not settings.mock_mode,
            "model": settings.embedding_model,
            "dim": settings.embedding_dim,
        },
        "security": {
            "secret_redaction": settings.enable_secret_redaction,
        },
        "catalog": {
            "enabled": settings.enable_catalog,
            "sync_interval_seconds": settings.catalog_sync_interval_seconds,
            "github_api_base_url": settings.github_api_base_url,
            "token_broker_enabled": bool(settings.github_token_broker_url),
            "dev_endpoints_enabled": settings.enable_catalog_dev_endpoints,
        },
        "python": {
            "version": sys.version.split(" ")[0],
            "implementation": platform.python_implementation(),
        },
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
        },
        "build": {
            "git_sha": os.environ.get("GIT_SHA") or os.environ.get("GITHUB_SHA"),
        },
    }


# --- Retrieval ---


@app.post("/search", dependencies=[Depends(require_auth)])
def search(req: SearchRequest, conn: Any = Depends(get_conn)) -> dict[str, object]:
    return search_repos(
        conn,
        settings=settings,
        query=req.query,
        top_k_repos=req.top_k_repos,
        top_k_chunks=req.top_k_chunks,
    )


# PRFactory-style alias (keeps /api/* space for integrations)
@app.post("/api/indexer/search", dependencies=[Depends(require_auth)])
def search_alias(req: SearchRequest, conn: Any = Depends(get_conn)) -> dict[str, object]:
    return search(req=req, conn=conn)


# --- Indexer metadata APIs ---


@app.get("/api/indexer/stats", dependencies=[Depends(require_auth)])
def stats(conn: Any = Depends(get_conn)) -> dict[str, Any]:
    return {"stats": get_index_stats(conn)}


@app.get("/api/indexer/repos", dependencies=[Depends(require_auth)])
def repos(
    conn: Any = Depends(get_conn),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0, le=10_000),
) -> dict[str, Any]:
    return {"repos": list_repos(conn, limit=limit, offset=offset)}


@app.get("/api/indexer/repos/{repo_id}", dependencies=[Depends(require_auth)])
def repo_detail(repo_id: str, conn: Any = Depends(get_conn)) -> dict[str, Any]:
    try:
        rid = uuid.UUID(repo_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid repo_id")

    details = get_repo_details(conn, rid)
    if not details:
        raise HTTPException(status_code=404, detail="Repo not found")
    return details


# --- GitHub catalog APIs ---


@app.post("/api/indexer/catalog/suggest", dependencies=[Depends(require_auth)])
def catalog_suggest(req: CatalogSuggestRequest, conn: Any = Depends(get_conn)) -> dict[str, Any]:
    runner = _catalog_runner_or_404()
    if req.github_token:
        runner.token_store.set(actor_id=req.actor_id, token=req.github_token)

    response = runner.service.suggest(
        conn=conn,
        actor_id=req.actor_id,
        query=req.query,
        org=req.org,
        top_k_repos=req.top_k_repos,
        top_k_branches_per_repo=req.top_k_branches_per_repo,
    )

    if response.get("auth_required") and req.github_token:
        run_id = runner.submit_sync(
            actor_id=req.actor_id,
            scope="incremental",
            org=req.org,
            github_token=req.github_token,
            source_token_owner=req.actor_id,
        )
        dbg = response.get("debug")
        if not isinstance(dbg, dict):
            dbg = {}
        dbg["sync_queued"] = True
        dbg["sync_run_id"] = str(run_id)
        response["debug"] = dbg
        response["auth_required"] = False
        response["connect_url"] = None
    return response


@app.get("/api/indexer/catalog/repos", dependencies=[Depends(require_auth)])
def catalog_repos(
    actor_id: str = Query(..., min_length=1),
    org: Optional[str] = Query(default=None),
    updated_since: Optional[datetime] = Query(default=None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0, le=10_000),
    conn: Any = Depends(get_conn),
) -> dict[str, Any]:
    runner = _catalog_runner_or_404()
    repos = runner.service.list_repos(
        conn=conn,
        actor_id=actor_id,
        org=org,
        updated_since=updated_since,
        limit=limit,
        offset=offset,
    )
    return {"repos": repos}


@app.get("/api/indexer/catalog/repos/{repo_id}/branches", dependencies=[Depends(require_auth)])
def catalog_repo_branches(
    repo_id: str,
    actor_id: str = Query(..., min_length=1),
    include_generated: bool = Query(True),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0, le=10_000),
    conn: Any = Depends(get_conn),
) -> dict[str, Any]:
    runner = _catalog_runner_or_404()
    try:
        rid = uuid.UUID(repo_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid repo_id")
    branches = runner.service.list_branches(
        conn=conn,
        actor_id=actor_id,
        repo_id=rid,
        include_generated=include_generated,
        limit=limit,
        offset=offset,
    )
    return {"branches": branches}


@app.post("/api/indexer/catalog/sync", dependencies=[Depends(require_auth)])
def catalog_sync(req: CatalogSyncRequest) -> dict[str, Any]:
    runner = _catalog_runner_or_404()
    scope = req.scope.strip().lower()
    if scope not in {"full", "incremental", "webhook"}:
        raise HTTPException(status_code=400, detail="scope must be one of: full, incremental, webhook")

    token = req.github_token or runner.token_store.get(actor_id=req.actor_id)
    if not token:
        return {
            "status": "auth_required",
            "auth_required": True,
            "connect_url": runner.service.connect_url(actor_id=req.actor_id),
        }

    run_id = runner.submit_sync(
        actor_id=req.actor_id,
        scope=scope,
        org=req.org,
        github_token=token,
        source_token_owner=req.source_token_owner or req.actor_id,
        repo_full_name=req.repo_full_name,
    )
    return {"status": "queued", "run_id": str(run_id)}


@app.post("/api/indexer/catalog/dev/token", dependencies=[Depends(require_auth)])
def catalog_set_actor_token(req: CatalogSetTokenRequest) -> dict[str, Any]:
    _require_catalog_dev_endpoints()
    runner = _catalog_runner_or_404()
    runner.token_store.set(
        actor_id=req.actor_id,
        token=req.github_token,
        ttl_seconds=req.ttl_seconds,
    )
    return {
        "status": "stored",
        "actor_id": req.actor_id,
        "ttl_seconds": req.ttl_seconds,
    }


@app.post("/api/indexer/catalog/dev/seed", dependencies=[Depends(require_auth)])
def catalog_seed_demo(req: CatalogSeedDemoRequest, conn: Any = Depends(get_conn)) -> dict[str, Any]:
    _require_catalog_dev_endpoints()
    runner = _catalog_runner_or_404()
    seeded = runner.service.seed_demo_data(
        conn=conn,
        actor_id=req.actor_id,
        org=req.org,
    )
    return {"status": "seeded", "seed": seeded}


@app.get("/api/indexer/catalog/runs", dependencies=[Depends(require_auth)])
def catalog_runs(
    conn: Any = Depends(get_conn),
    actor_id: Optional[str] = Query(default=None),
    limit: int = Query(25, ge=1, le=200),
) -> dict[str, Any]:
    _ = _catalog_runner_or_404()
    return {"runs": list_github_index_runs(conn, actor_id=actor_id, limit=limit)}


@app.get("/api/indexer/catalog/runs/{run_id}", dependencies=[Depends(require_auth)])
def catalog_run_detail(run_id: str, conn: Any = Depends(get_conn)) -> dict[str, Any]:
    _ = _catalog_runner_or_404()
    try:
        rid = uuid.UUID(run_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid run_id")
    run = get_github_index_run(conn, run_id=rid)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return {"run": run}


@app.post("/api/indexer/webhooks/github")
async def github_webhook(
    request: Request,
    x_github_event: Optional[str] = Header(default=None, alias="X-GitHub-Event"),
    x_github_delivery: Optional[str] = Header(default=None, alias="X-GitHub-Delivery"),
    x_hub_signature_256: Optional[str] = Header(default=None, alias="X-Hub-Signature-256"),
    x_github_oauth_token: Optional[str] = Header(default=None, alias="X-GitHub-OAuth-Token"),
    x_actor_id: Optional[str] = Header(default=None, alias="X-Actor-Id"),
    conn: Any = Depends(get_conn),
) -> dict[str, Any]:
    runner = _catalog_runner_or_404()
    event_type = (x_github_event or "").strip()
    delivery_id = (x_github_delivery or "").strip()
    if not event_type or not delivery_id:
        raise HTTPException(status_code=400, detail="Missing GitHub webhook headers")

    body = await request.body()
    if not verify_github_webhook_signature(
        body=body,
        secret=settings.github_webhook_secret,
        signature_header=x_hub_signature_256,
    ):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    payload_raw = await request.json()
    if not isinstance(payload_raw, dict):
        raise HTTPException(status_code=400, detail="Invalid webhook payload")
    payload = payload_raw

    created, actor_id, repo_full_name = runner.service.register_webhook_delivery(
        conn=conn,
        delivery_id=delivery_id,
        event_type=event_type,
        payload=payload,
    )
    if not created:
        return {"status": "duplicate", "delivery_id": delivery_id}

    actor = (x_actor_id or actor_id or "").strip()
    repo_name = (repo_full_name or "").strip()
    if not actor or not repo_name:
        runner.service.mark_webhook_processed(
            conn=conn,
            delivery_id=delivery_id,
            status="failed",
            error="Missing actor_id or repository name in payload",
        )
        return {"status": "ignored", "delivery_id": delivery_id}

    token = x_github_oauth_token or runner.token_store.get(actor_id=actor)
    if not token:
        runner.service.mark_webhook_processed(
            conn=conn,
            delivery_id=delivery_id,
            status="failed",
            error="Missing OAuth token for webhook refresh",
        )
        return {
            "status": "auth_required",
            "delivery_id": delivery_id,
            "auth_required": True,
            "connect_url": runner.service.connect_url(actor_id=actor),
        }

    run_id = runner.submit_sync(
        actor_id=actor,
        scope="webhook",
        github_token=token,
        repo_full_name=repo_name,
        source_token_owner=actor,
    )
    runner.service.mark_webhook_processed(
        conn=conn,
        delivery_id=delivery_id,
        status="processed",
        error=None,
    )
    return {"status": "queued", "delivery_id": delivery_id, "run_id": str(run_id)}


# --- Index job APIs (used by UI) ---


@app.post("/api/indexer/index", dependencies=[Depends(require_auth)])
def index_repo(req: IndexRequest) -> dict[str, Any]:
    if not settings.enable_ui:
        raise HTTPException(status_code=404, detail="Index jobs disabled")

    global job_runner
    if job_runner is None:
        raise HTTPException(status_code=503, detail="Job runner not available")

    run_id = job_runner.submit_index(repo_ref=req.repo, incremental=req.incremental)
    return {"run_id": str(run_id), "status": "queued"}


@app.post("/api/indexer/update", dependencies=[Depends(require_auth)])
def update_repo(req: IndexRequest) -> dict[str, Any]:
    # Alias of index incremental=true
    req2 = IndexRequest(repo=req.repo, incremental=True)
    return index_repo(req2)


@app.get("/api/indexer/runs", dependencies=[Depends(require_auth)])
def runs(conn: Any = Depends(get_conn), limit: int = Query(25, ge=1, le=200)) -> dict[str, Any]:
    return {"runs": list_index_runs(conn, limit=limit)}


@app.get("/api/indexer/runs/{run_id}", dependencies=[Depends(require_auth)])
def run_detail(run_id: str, conn: Any = Depends(get_conn)) -> dict[str, Any]:
    try:
        rid = uuid.UUID(run_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid run_id")

    run = get_index_run(conn, rid)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return {"run": run}
