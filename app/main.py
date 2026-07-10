import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response as FastAPIResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.api.routes import arena, auth, catalog, context, dashboard, leaderboard, prompts, regression, runs
from app.core.database import get_session_factory
from app.monitoring.metrics import HTTP_REQUEST_DURATION_SECONDS, HTTP_REQUESTS_TOTAL


@asynccontextmanager
async def lifespan(app: FastAPI):
    # eng-review D10: seed the single demo user/project/models/dataset on
    # startup so the public deploy never needs an open registration flow or
    # a manual data-entry step to be usable.
    from app.core.seed_data import seed_all_demo_data

    async with get_session_factory()() as session:
        await seed_all_demo_data(session, demo_password="demo-password-change-me")
    yield


app = FastAPI(title="LLM Evaluation Platform", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    # Phase 4: any localhost port, not just 3000 — Next.js auto-increments
    # to the next free port (3001, 3002, ...) whenever something else on the
    # dev machine already holds 3000, which a hardcoded single origin would
    # silently break. Tightened to the exact deployed frontend origin in
    # Phase 10 (deploy) — see design doc Distribution Plan.
    allow_origin_regex=r"http://localhost:\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(runs.router)
app.include_router(leaderboard.router)
app.include_router(context.router)
app.include_router(arena.router)
app.include_router(prompts.router)
app.include_router(regression.router)
app.include_router(catalog.projects_router)
app.include_router(catalog.datasets_router)
app.include_router(dashboard.router)


@app.middleware("http")
async def prometheus_http_metrics(request: Request, call_next):
    """Phase 9: FastAPI process's half of the HTTP metrics (see
    app/monitoring/metrics.py's module docstring for the two-process split).
    Labeled by the matched route's templated path (e.g. "/runs/{run_id}"),
    not the raw request path — FastAPI's own APIRoute.matches() sets
    request.scope["route"] (verified against the installed fastapi/
    starlette's routing.py, not assumed), so the label set stays bounded
    regardless of how many distinct run/regression-run IDs are ever
    requested. Unmatched paths (404s) collapse to one "unmatched" label for
    the same reason — an arbitrary bad-path probe must never grow the label
    cardinality."""
    started = time.monotonic()
    response = await call_next(request)
    elapsed_seconds = time.monotonic() - started

    route = request.scope.get("route")
    path = route.path if route is not None else "unmatched"

    HTTP_REQUESTS_TOTAL.labels(method=request.method, path=path, status=response.status_code).inc()
    HTTP_REQUEST_DURATION_SECONDS.labels(method=request.method, path=path).observe(elapsed_seconds)
    return response


@app.get("/metrics")
async def metrics() -> FastAPIResponse:
    """Public, unauthenticated — standard Prometheus scrape convention, same
    trust boundary as every other read-only endpoint here (D2)."""
    return FastAPIResponse(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
