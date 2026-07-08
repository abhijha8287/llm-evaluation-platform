from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import auth, runs
from app.core.database import get_session_factory


@asynccontextmanager
async def lifespan(app: FastAPI):
    # eng-review D10: seed the single demo user/project on startup so the
    # public deploy never needs an open registration flow to be usable.
    from app.core.seed_data import seed_demo_user

    async with get_session_factory()() as session:
        await seed_demo_user(session, password="demo-password-change-me")
    yield


app = FastAPI(title="LLM Evaluation Platform", lifespan=lifespan)

app.include_router(auth.router)
app.include_router(runs.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
