from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_session
from app.core.security import decode_access_token
from app.models.user import User
from app.repositories.run_repository import RunRepository
from app.repositories.user_repository import UserRepository

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


async def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    session: AsyncSession = Depends(get_session),
) -> User:
    """eng-review D10: login-only, single seeded demo user. No public
    registration endpoint exists — see app/api/routes/auth.py."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if token is None:
        raise credentials_exception
    user_id = decode_access_token(token)
    if user_id is None:
        raise credentials_exception
    user = await UserRepository(session).get(int(user_id))
    if user is None:
        raise credentials_exception
    return user


async def enforce_run_rate_limit(project_id: int, session: AsyncSession) -> None:
    """eng-review D2: rate limit is enforced in the endpoint itself,
    independent of auth state — defense in depth in case auth is ever
    misconfigured or bypassed. Not a substitute for get_current_user, a
    second, unconditional gate alongside it.

    Plain helper (not a FastAPI Depends chain) so it can be called explicitly
    after project/dataset-version validation in the route body, rather than
    resolving before the request body is available."""
    settings = get_settings()
    count = await RunRepository(session).count_last_24h(project_id)
    if count >= settings.max_runs_per_day:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Rate limit reached: {settings.max_runs_per_day} new runs/day "
                "per project. Try again later."
            ),
        )
