"""Task T4 verify: rate limit fires after the configured number of requests,
and only after successful auth + project/dataset-version/model validation.

Phase 5: POST /runs no longer executes synchronously — it validates, commits
the Run row, and dispatches a Celery chord (app.api.routes.runs.dispatch_run).
These tests patch dispatch_run to verify the HTTP-layer contract (what gets
validated, what gets returned, what dispatch is asked to do) without needing
a live Celery worker. dispatch_run's own task-count/argument behavior is
covered separately in tests/test_eval_tasks.py."""

from unittest.mock import MagicMock


import app.api.routes.runs as runs_module
from app.core.config import get_settings
from app.core.security import create_access_token
from app.models.dataset import Dataset, DatasetVersion, DatasetVersionQuestion
from app.models.llm_model import LLMModel
from app.models.project import Project
from app.models.question import Question, QuestionType
from app.models.response import Response, ResponseStatus
from app.models.run import Run, RunStatus
from app.models.user import User


async def _seed_project_dataset_and_model(session_factory, owner_id: int) -> tuple[int, int, int]:
    async with session_factory() as session:
        project = Project(owner_id=owner_id, name="Test Project")
        session.add(project)
        await session.flush()

        dataset = Dataset(project_id=project.id, name="Test Dataset")
        session.add(dataset)
        await session.flush()

        question = Question(dataset_id=dataset.id, type=QuestionType.OPEN_DOMAIN, text="Q1")
        session.add(question)
        await session.flush()

        dataset_version = DatasetVersion(dataset_id=dataset.id, version_number=1, sample_seed=1, sample_size=1)
        session.add(dataset_version)
        await session.flush()

        session.add(DatasetVersionQuestion(dataset_version_id=dataset_version.id, question_id=question.id))

        model = LLMModel(provider="openai", name="gpt-4o-mini", display_name="GPT-4o mini")
        session.add(model)
        await session.flush()

        await session.commit()
        return project.id, dataset_version.id, model.id


def _patch_dispatch_run(monkeypatch) -> MagicMock:
    mock = MagicMock()
    monkeypatch.setattr(runs_module, "dispatch_run", mock)
    return mock


async def test_create_run_requires_auth(test_client):
    response = await test_client.post(
        "/runs", json={"project_id": 1, "dataset_version_id": 1, "model_ids": [1]}
    )
    assert response.status_code == 401


async def test_create_run_rejects_empty_model_ids(test_client, seeded_demo_user):
    token = create_access_token(subject=str(seeded_demo_user.id))
    response = await test_client.post(
        "/runs",
        json={"project_id": 1, "dataset_version_id": 1, "model_ids": []},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 400


async def test_create_run_rejects_unowned_project(test_client, session_factory, seeded_demo_user):
    async with session_factory() as session:
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
        model = LLMModel(provider="openai", name="gpt-4o-mini", display_name="GPT-4o mini")
        session.add(model)
        await session.flush()
        await session.commit()
        other_project_id, other_version_id, model_id = other_project.id, other_version.id, model.id

    token = create_access_token(subject=str(seeded_demo_user.id))
    response = await test_client.post(
        "/runs",
        json={"project_id": other_project_id, "dataset_version_id": other_version_id, "model_ids": [model_id]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 404


async def test_create_run_rejects_unknown_model_id(test_client, session_factory, seeded_demo_user):
    project_id, dataset_version_id, _model_id = await _seed_project_dataset_and_model(
        session_factory, seeded_demo_user.id
    )
    token = create_access_token(subject=str(seeded_demo_user.id))
    response = await test_client.post(
        "/runs",
        json={"project_id": project_id, "dataset_version_id": dataset_version_id, "model_ids": [999999]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 404


async def test_create_run_rejects_dataset_version_with_no_questions(
    test_client, session_factory, seeded_demo_user
):
    async with session_factory() as session:
        project = Project(owner_id=seeded_demo_user.id, name="Empty Dataset Project")
        session.add(project)
        await session.flush()
        dataset = Dataset(project_id=project.id, name="D")
        session.add(dataset)
        await session.flush()
        # No questions sampled into this version.
        dataset_version = DatasetVersion(dataset_id=dataset.id, version_number=1, sample_seed=1, sample_size=0)
        session.add(dataset_version)
        model = LLMModel(provider="openai", name="gpt-4o-mini", display_name="GPT-4o mini")
        session.add(model)
        await session.flush()
        await session.commit()
        project_id, dataset_version_id, model_id = project.id, dataset_version.id, model.id

    token = create_access_token(subject=str(seeded_demo_user.id))
    response = await test_client.post(
        "/runs",
        json={"project_id": project_id, "dataset_version_id": dataset_version_id, "model_ids": [model_id]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 400


async def test_create_run_dispatches_with_all_question_and_model_ids(
    test_client, session_factory, seeded_demo_user, monkeypatch
):
    dispatch_mock = _patch_dispatch_run(monkeypatch)
    project_id, dataset_version_id, model_id = await _seed_project_dataset_and_model(
        session_factory, seeded_demo_user.id
    )
    token = create_access_token(subject=str(seeded_demo_user.id))

    response = await test_client.post(
        "/runs",
        json={"project_id": project_id, "dataset_version_id": dataset_version_id, "model_ids": [model_id]},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "running"
    assert body["completed_at"] is None

    dispatch_mock.assert_called_once()
    call_run_id, call_question_ids, call_model_ids = dispatch_mock.call_args.args
    assert call_run_id == body["id"]
    assert call_model_ids == [model_id]
    assert len(call_question_ids) == 1

    async with session_factory() as session:
        run = await session.get(Run, body["id"])
        assert run.status == RunStatus.RUNNING


async def test_create_run_is_rate_limited(test_client, session_factory, seeded_demo_user, monkeypatch):
    _patch_dispatch_run(monkeypatch)
    monkeypatch.setenv("MAX_RUNS_PER_DAY", "2")
    get_settings.cache_clear()

    project_id, dataset_version_id, model_id = await _seed_project_dataset_and_model(
        session_factory, seeded_demo_user.id
    )
    token = create_access_token(subject=str(seeded_demo_user.id))
    headers = {"Authorization": f"Bearer {token}"}
    body = {"project_id": project_id, "dataset_version_id": dataset_version_id, "model_ids": [model_id]}

    first = await test_client.post("/runs", json=body, headers=headers)
    assert first.status_code == 201
    second = await test_client.post("/runs", json=body, headers=headers)
    assert second.status_code == 201
    third = await test_client.post("/runs", json=body, headers=headers)
    assert third.status_code == 429

    get_settings.cache_clear()


async def test_get_run_returns_current_status(test_client, session_factory, seeded_demo_user):
    async with session_factory() as session:
        project = Project(owner_id=seeded_demo_user.id, name="P")
        session.add(project)
        await session.flush()
        dataset = Dataset(project_id=project.id, name="D")
        session.add(dataset)
        await session.flush()
        dataset_version = DatasetVersion(dataset_id=dataset.id, version_number=1, sample_seed=1, sample_size=1)
        session.add(dataset_version)
        await session.flush()
        run = Run(project_id=project.id, dataset_version_id=dataset_version.id, status=RunStatus.RUNNING)
        session.add(run)
        await session.flush()
        await session.commit()
        run_id = run.id

    response = await test_client.get(f"/runs/{run_id}")
    assert response.status_code == 200
    assert response.json()["status"] == "running"


async def test_get_run_requires_no_auth(test_client, session_factory, seeded_demo_user):
    """eng-review D2: read-only endpoints are public."""
    async with session_factory() as session:
        project = Project(owner_id=seeded_demo_user.id, name="P")
        session.add(project)
        await session.flush()
        dataset = Dataset(project_id=project.id, name="D")
        session.add(dataset)
        await session.flush()
        dataset_version = DatasetVersion(dataset_id=dataset.id, version_number=1, sample_seed=1, sample_size=1)
        session.add(dataset_version)
        await session.flush()
        run = Run(project_id=project.id, dataset_version_id=dataset_version.id)
        session.add(run)
        await session.flush()
        await session.commit()
        run_id = run.id

    response = await test_client.get(f"/runs/{run_id}")
    assert response.status_code == 200


async def test_get_run_404_for_unknown_id(test_client):
    response = await test_client.get("/runs/999999")
    assert response.status_code == 404


async def test_list_runs_requires_no_auth_and_reports_response_count(
    test_client, session_factory, seeded_demo_user
):
    """Phase 8: backs the Experiment History dashboard page."""
    project_id, dataset_version_id, model_id = await _seed_project_dataset_and_model(
        session_factory, seeded_demo_user.id
    )
    async with session_factory() as session:
        run = Run(
            project_id=project_id, dataset_version_id=dataset_version_id, status=RunStatus.COMPLETED
        )
        session.add(run)
        await session.flush()
        session.add(Response(run_id=run.id, question_id=1, model_id=model_id, status=ResponseStatus.SUCCESS))
        session.add(Response(run_id=run.id, question_id=1, model_id=model_id, status=ResponseStatus.SUCCESS))
        await session.commit()
        run_id = run.id

    response = await test_client.get("/runs", params={"project_id": project_id})
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == run_id
    assert body[0]["response_count"] == 2


async def test_list_runs_excludes_regression_run(test_client, session_factory, seeded_demo_user):
    """Regression-run-owned runs show up under Regression Results instead —
    same exclusion rationale as the leaderboard (see leaderboard.py)."""
    project_id, dataset_version_id, model_id = await _seed_project_dataset_and_model(
        session_factory, seeded_demo_user.id
    )
    async with session_factory() as session:
        from app.models.prompt import PromptTemplate, PromptVersion
        from app.models.regression import RegressionRun, RegressionStatus

        plain_run = Run(project_id=project_id, dataset_version_id=dataset_version_id, status=RunStatus.COMPLETED)
        session.add(plain_run)
        await session.flush()

        template = PromptTemplate(project_id=project_id, name="T")
        session.add(template)
        await session.flush()
        version = PromptVersion(prompt_template_id=template.id, version_number=1, content="{question}")
        session.add(version)
        await session.flush()

        regression_underlying_run = Run(
            project_id=project_id, dataset_version_id=dataset_version_id, status=RunStatus.COMPLETED
        )
        session.add(regression_underlying_run)
        await session.flush()
        session.add(
            RegressionRun(
                prompt_version_id=version.id,
                dataset_version_id=dataset_version_id,
                model_id=model_id,
                run_id=regression_underlying_run.id,
                status=RegressionStatus.COMPLETED,
            )
        )
        await session.commit()
        plain_run_id = plain_run.id

    response = await test_client.get("/runs", params={"project_id": project_id})
    assert response.status_code == 200
    body = response.json()
    assert [r["id"] for r in body] == [plain_run_id]
