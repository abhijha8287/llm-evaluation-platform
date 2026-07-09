from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import arena, auth, context, leaderboard, runs
from app.core.database import get_session_factory


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


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
