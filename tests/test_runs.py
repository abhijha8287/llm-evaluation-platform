"""Task T4 verify: rate limit fires after the configured number of requests,
and only after successful auth + project/dataset-version validation."""

from app.core.config import get_settings
from app.core.security import create_access_token
from app.models.dataset import Dataset, DatasetVersion
from app.models.project import Project


async def _seed_project_and_dataset_version(session_factory, owner_id: int) -> tuple[int, int]:
    async with session_factory() as session:
        project = Project(owner_id=owner_id, name="Test Project")
        session.add(project)
        await session.flush()

        dataset = Dataset(project_id=project.id, name="Test Dataset")
        session.add(dataset)
        await session.flush()

        dataset_version = DatasetVersion(dataset_id=dataset.id, version_number=1, sample_seed=1, sample_size=5)
        session.add(dataset_version)
        await session.flush()

        await session.commit()
        return project.id, dataset_version.id


async def test_create_run_requires_auth(test_client):
    response = await test_client.post("/runs", json={"project_id": 1, "dataset_version_id": 1})
    assert response.status_code == 401


async def test_create_run_rejects_unowned_project(test_client, session_factory, seeded_demo_user):
    # A second user's project — demo user must not be able to trigger runs on it.
    async with session_factory() as session:
        from app.models.user import User

        other_user = User(email="other@example.com", hashed_password="x")
        session.add(other_user)
        await session.flush()
        other_project = Project(owner_id=other_user.id, name="Not Yours")
        session.add(other_project)
        await session.flush()
        other_dataset = Dataset(project_id=other_project.id, name="D")
        session.add(other_dataset)
        await session.flush()
        other_version = DatasetVersion(dataset_id=other_dataset.id, version_number=1, sample_seed=1, sample_size=1)
        session.add(other_version)
        await session.flush()
        await session.commit()
        other_project_id, other_version_id = other_project.id, other_version.id

    token = create_access_token(subject=str(seeded_demo_user.id))
    response = await test_client.post(
        "/runs",
        json={"project_id": other_project_id, "dataset_version_id": other_version_id},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 404


async def test_create_run_succeeds_and_is_rate_limited(test_client, session_factory, seeded_demo_user, monkeypatch):
    monkeypatch.setenv("MAX_RUNS_PER_DAY", "2")
    get_settings.cache_clear()

    project_id, dataset_version_id = await _seed_project_and_dataset_version(session_factory, seeded_demo_user.id)
    token = create_access_token(subject=str(seeded_demo_user.id))
    headers = {"Authorization": f"Bearer {token}"}
    body = {"project_id": project_id, "dataset_version_id": dataset_version_id}

    first = await test_client.post("/runs", json=body, headers=headers)
    assert first.status_code == 201
    assert first.json()["status"] == "pending"

    second = await test_client.post("/runs", json=body, headers=headers)
    assert second.status_code == 201

    third = await test_client.post("/runs", json=body, headers=headers)
    assert third.status_code == 429

    get_settings.cache_clear()
