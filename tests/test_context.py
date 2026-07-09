from sqlalchemy import select

from app.core.security import create_access_token
from app.models.dataset import Dataset, DatasetVersion
from app.models.llm_model import LLMModel
from app.models.project import Project
from app.models.user import User


async def test_run_context_requires_auth(test_client):
    response = await test_client.get("/me/run-context")
    assert response.status_code == 401


async def test_run_context_returns_project_dataset_version_and_models(
    test_client, session_factory, seeded_demo_user
):
    # seeded_demo_user already creates one Project ("Demo Project") for this
    # user — add the dataset/versions/model onto that existing project
    # rather than creating a second one, so "first()" in the endpoint is
    # unambiguous.
    async with session_factory() as session:
        project = (
            await session.execute(select(Project).where(Project.owner_id == seeded_demo_user.id))
        ).scalars().one()

        dataset = Dataset(project_id=project.id, name="D")
        session.add(dataset)
        await session.flush()
        v1 = DatasetVersion(dataset_id=dataset.id, version_number=1, sample_seed=1, sample_size=1)
        v2 = DatasetVersion(dataset_id=dataset.id, version_number=2, sample_seed=2, sample_size=1)
        session.add_all([v1, v2])
        model = LLMModel(provider="openai", name="gpt-4o-mini", display_name="GPT-4o mini")
        session.add(model)
        await session.flush()
        await session.commit()
        project_id, latest_version_id = project.id, v2.id

    token = create_access_token(subject=str(seeded_demo_user.id))
    response = await test_client.get("/me/run-context", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    body = response.json()
    assert body["project_id"] == project_id
    assert body["dataset_version_id"] == latest_version_id  # picks the latest, not the first
    assert len(body["models"]) == 1
    assert body["models"][0]["display_name"] == "GPT-4o mini"


async def test_run_context_404_when_project_has_no_dataset_version(test_client, session_factory):
    """A brand new user with a project but no dataset/version yet (not
    reachable through normal seeding, but a real state a fresh signup could
    be in before Phase 8's dataset-management UI exists)."""
    async with session_factory() as session:
        user = User(email="freshuser@example.com", hashed_password="x")
        session.add(user)
        await session.flush()
        project = Project(owner_id=user.id, name="Empty Project")
        session.add(project)
        await session.flush()
        await session.commit()
        user_id = user.id

    token = create_access_token(subject=str(user_id))
    response = await test_client.get("/me/run-context", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 404
