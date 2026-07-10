from unittest.mock import MagicMock

from sqlalchemy import select

import app.api.routes.regression as regression_module
from app.core.security import create_access_token
from app.models.dataset import Dataset, DatasetVersion, DatasetVersionQuestion
from app.models.llm_model import LLMModel
from app.models.project import Project
from app.models.prompt import PromptTemplate, PromptVersion
from app.models.question import Question, QuestionType
from app.models.regression import RegressionResult, RegressionRun, RegressionStatus
from app.models.run import Run, RunStatus


def _patch_dispatch(monkeypatch) -> MagicMock:
    mock = MagicMock()
    monkeypatch.setattr(regression_module, "dispatch_regression_run", mock)
    return mock


async def _seed_regression_inputs(session_factory, owner_id: int) -> dict:
    async with session_factory() as session:
        project = (await session.execute(select(Project).where(Project.owner_id == owner_id))).scalars().one()
        dataset = Dataset(project_id=project.id, name="D")
        session.add(dataset)
        await session.flush()
        question = Question(dataset_id=dataset.id, type=QuestionType.OPEN_DOMAIN, text="Q")
        session.add(question)
        await session.flush()
        dataset_version = DatasetVersion(dataset_id=dataset.id, version_number=1, sample_seed=1, sample_size=1)
        session.add(dataset_version)
        await session.flush()
        session.add(DatasetVersionQuestion(dataset_version_id=dataset_version.id, question_id=question.id))
        model = LLMModel(provider="openai", name="gpt-4o-mini", display_name="GPT-4o mini")
        session.add(model)
        await session.flush()
        template = PromptTemplate(project_id=project.id, name="T")
        session.add(template)
        await session.flush()
        version = PromptVersion(prompt_template_id=template.id, version_number=1, content="{question}")
        session.add(version)
        await session.flush()
        await session.commit()
        return {
            "project_id": project.id,
            "dataset_version_id": dataset_version.id,
            "model_id": model.id,
            "prompt_version_id": version.id,
        }


async def test_create_regression_run_requires_auth(test_client):
    response = await test_client.post(
        "/regression-runs",
        json={"prompt_version_id": 1, "dataset_version_id": 1, "model_id": 1},
    )
    assert response.status_code == 401


async def test_create_regression_run_dispatches_and_returns_running(
    test_client, session_factory, seeded_demo_user, monkeypatch
):
    dispatch_mock = _patch_dispatch(monkeypatch)
    inputs = await _seed_regression_inputs(session_factory, seeded_demo_user.id)
    token = create_access_token(subject=str(seeded_demo_user.id))

    response = await test_client.post(
        "/regression-runs",
        json={
            "prompt_version_id": inputs["prompt_version_id"],
            "dataset_version_id": inputs["dataset_version_id"],
            "model_id": inputs["model_id"],
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "running"
    assert body["completed_at"] is None

    dispatch_mock.assert_called_once()
    call_regression_run_id, call_question_ids = dispatch_mock.call_args.args
    assert call_regression_run_id == body["id"]
    assert len(call_question_ids) == 1

    async with session_factory() as session:
        run = await session.get(Run, body["run_id"])
        assert run.status == RunStatus.RUNNING


async def test_create_regression_run_rejects_baseline_from_different_template(
    test_client, session_factory, seeded_demo_user, monkeypatch
):
    _patch_dispatch(monkeypatch)
    inputs = await _seed_regression_inputs(session_factory, seeded_demo_user.id)

    async with session_factory() as session:
        other_template = PromptTemplate(project_id=inputs["project_id"], name="Other")
        session.add(other_template)
        await session.flush()
        other_version = PromptVersion(prompt_template_id=other_template.id, version_number=1, content="{question}")
        session.add(other_version)
        await session.flush()
        await session.commit()
        other_version_id = other_version.id

    token = create_access_token(subject=str(seeded_demo_user.id))
    response = await test_client.post(
        "/regression-runs",
        json={
            "prompt_version_id": inputs["prompt_version_id"],
            "dataset_version_id": inputs["dataset_version_id"],
            "model_id": inputs["model_id"],
            "baseline_prompt_version_id": other_version_id,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 400


async def test_get_regression_run_returns_status_and_results(test_client, session_factory, seeded_demo_user):
    inputs = await _seed_regression_inputs(session_factory, seeded_demo_user.id)

    async with session_factory() as session:
        run = Run(project_id=inputs["project_id"], dataset_version_id=inputs["dataset_version_id"], status=RunStatus.COMPLETED)
        session.add(run)
        await session.flush()
        regression_run = RegressionRun(
            prompt_version_id=inputs["prompt_version_id"],
            dataset_version_id=inputs["dataset_version_id"],
            model_id=inputs["model_id"],
            run_id=run.id,
            status=RegressionStatus.COMPLETED,
        )
        session.add(regression_run)
        await session.flush()
        session.add(
            RegressionResult(
                regression_run_id=regression_run.id, question_id=1, metric_name="toxicity", score=0.1,
                delta_from_baseline=None,
            )
        )
        await session.commit()
        regression_run_id = regression_run.id

    response = await test_client.get(f"/regression-runs/{regression_run_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert len(body["results"]) == 1
    assert body["results"][0]["score"] == 0.1


async def test_get_regression_run_404_for_unknown_id(test_client):
    response = await test_client.get("/regression-runs/999999")
    assert response.status_code == 404


async def test_list_regression_runs_requires_no_auth_and_filters_by_template(
    test_client, session_factory, seeded_demo_user
):
    """Phase 8: backs the Regression Results dashboard page. Filtered by
    prompt_template_id, not prompt_version_id, so a run against a sibling
    version of the same template is included but an unrelated template's
    runs are not."""
    inputs = await _seed_regression_inputs(session_factory, seeded_demo_user.id)

    async with session_factory() as session:
        run = Run(
            project_id=inputs["project_id"], dataset_version_id=inputs["dataset_version_id"],
            status=RunStatus.COMPLETED,
        )
        session.add(run)
        await session.flush()
        regression_run = RegressionRun(
            prompt_version_id=inputs["prompt_version_id"],
            dataset_version_id=inputs["dataset_version_id"],
            model_id=inputs["model_id"],
            run_id=run.id,
            status=RegressionStatus.COMPLETED,
        )
        session.add(regression_run)
        await session.flush()
        await session.commit()
        regression_run_id = regression_run.id

        prompt_version = await session.get(PromptVersion, inputs["prompt_version_id"])
        template_id = prompt_version.prompt_template_id

        other_template = PromptTemplate(project_id=inputs["project_id"], name="Unrelated")
        session.add(other_template)
        await session.flush()
        other_version = PromptVersion(prompt_template_id=other_template.id, version_number=1, content="{question}")
        session.add(other_version)
        await session.flush()
        other_run = Run(
            project_id=inputs["project_id"], dataset_version_id=inputs["dataset_version_id"],
            status=RunStatus.COMPLETED,
        )
        session.add(other_run)
        await session.flush()
        session.add(
            RegressionRun(
                prompt_version_id=other_version.id,
                dataset_version_id=inputs["dataset_version_id"],
                model_id=inputs["model_id"],
                run_id=other_run.id,
                status=RegressionStatus.COMPLETED,
            )
        )
        await session.commit()

    response = await test_client.get("/regression-runs", params={"prompt_template_id": template_id})
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == regression_run_id
