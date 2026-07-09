"""Phase 8: read-only browsing endpoints (Projects/Datasets/Questions dashboard
pages). Public, no-auth per eng-review D2 — same as leaderboard.py, GET
/runs/{id}."""

from sqlalchemy import select

from app.models.dataset import Dataset, DatasetVersion
from app.models.project import Project
from app.models.question import Question, QuestionType


async def test_list_projects_returns_seeded_demo_project(test_client, seeded_demo_user):
    response = await test_client.get("/projects")
    assert response.status_code == 200
    body = response.json()
    assert any(p["owner_id"] == seeded_demo_user.id for p in body)


async def test_list_project_datasets_nests_versions(test_client, session_factory, seeded_demo_user):
    async with session_factory() as session:
        project = (
            await session.execute(select(Project).where(Project.owner_id == seeded_demo_user.id))
        ).scalars().one()
        dataset = Dataset(project_id=project.id, name="D")
        session.add(dataset)
        await session.flush()
        session.add(DatasetVersion(dataset_id=dataset.id, version_number=1, sample_seed=1, sample_size=3))
        await session.commit()
        project_id, dataset_id = project.id, dataset.id

    response = await test_client.get(f"/projects/{project_id}/datasets")
    assert response.status_code == 200
    body = response.json()
    matching = [d for d in body if d["id"] == dataset_id]
    assert len(matching) == 1
    assert len(matching[0]["versions"]) == 1
    assert matching[0]["versions"][0]["sample_size"] == 3


async def test_list_project_datasets_404_for_unknown_project(test_client):
    response = await test_client.get("/projects/999999/datasets")
    assert response.status_code == 404


async def test_list_dataset_questions_reports_has_retrieval_context(test_client, session_factory, seeded_demo_user):
    async with session_factory() as session:
        project = (
            await session.execute(select(Project).where(Project.owner_id == seeded_demo_user.id))
        ).scalars().one()
        dataset = Dataset(project_id=project.id, name="D")
        session.add(dataset)
        await session.flush()
        session.add(Question(dataset_id=dataset.id, type=QuestionType.OPEN_DOMAIN, text="Open one"))
        session.add(
            Question(
                dataset_id=dataset.id, type=QuestionType.RAG, text="RAG one", retrieval_context="ctx"
            )
        )
        await session.commit()
        dataset_id = dataset.id

    response = await test_client.get(f"/datasets/{dataset_id}/questions")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    by_text = {q["text"]: q for q in body}
    assert by_text["Open one"]["has_retrieval_context"] is False
    assert by_text["RAG one"]["has_retrieval_context"] is True


async def test_list_dataset_questions_404_for_unknown_dataset(test_client):
    response = await test_client.get("/datasets/999999/questions")
    assert response.status_code == 404


async def test_list_dataset_questions_empty_dataset_returns_empty_list(test_client, session_factory, seeded_demo_user):
    async with session_factory() as session:
        project = (
            await session.execute(select(Project).where(Project.owner_id == seeded_demo_user.id))
        ).scalars().one()
        dataset = Dataset(project_id=project.id, name="Empty")
        session.add(dataset)
        await session.commit()
        dataset_id = dataset.id

    response = await test_client.get(f"/datasets/{dataset_id}/questions")
    assert response.status_code == 200
    assert response.json() == []
