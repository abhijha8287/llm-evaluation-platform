from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.project import Project
from app.models.user import User
from app.repositories.project_repository import ProjectRepository
from app.repositories.user_repository import UserRepository

DEMO_USER_EMAIL = "demo@llm-eval-platform.dev"


async def seed_demo_user(session: AsyncSession, password: str) -> User:
    """eng-review D10: the public deploy has exactly one seeded user/project —
    no open self-registration. Idempotent: safe to call on every startup."""
    user_repo = UserRepository(session)
    existing = await user_repo.get_by_email(DEMO_USER_EMAIL)
    if existing is not None:
        return existing

    user = await user_repo.add(User(email=DEMO_USER_EMAIL, hashed_password=hash_password(password)))
    await ProjectRepository(session).add(Project(owner_id=user.id, name="Demo Project"))
    await session.commit()
    return user
