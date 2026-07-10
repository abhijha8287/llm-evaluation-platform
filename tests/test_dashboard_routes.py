"""Phase 8: GET /dashboard/trends backs the Latency Trend / Cost Analysis /
Pass Rate / Faithfulness Trend dashboard charts — one point per (run, model)
pair, ordered by run creation time."""


from app.models.dataset import Dataset, DatasetVersion
from app.models.evaluation_result import EvaluationResult, EvaluationStatus, MetricName
from app.models.llm_model import LLMModel
from app.models.project import Project
from app.models.regression import RegressionRun, RegressionStatus
from app.models.response import Response, ResponseStatus
from app.models.run import Run, RunStatus


async def _seed_completed_run_with_responses(session_factory, project_id: int, dataset_version_id: int) -> dict:
    async with session_factory() as session:
        model = LLMModel(provider="openai", name="gpt-4o-mini", display_name="GPT-4o mini")
        session.add(model)
        await session.flush()

        run = Run(project_id=project_id, dataset_version_id=dataset_version_id, status=RunStatus.COMPLETED)
        session.add(run)
        await session.flush()

        r1 = Response(
            run_id=run.id, question_id=1, model_id=model.id, status=ResponseStatus.SUCCESS,
            latency_ms=100, cost_usd=0.01,
        )
        r2 = Response(
            run_id=run.id, question_id=2, model_id=model.id, status=ResponseStatus.SUCCESS,
            latency_ms=200, cost_usd=0.02,
        )
        session.add(r1)
        session.add(r2)
        await session.flush()

        session.add(
            EvaluationResult(
                response_id=r1.id, metric_name=MetricName.TOXICITY, status=EvaluationStatus.SUCCESS,
                score=0.1, passed=True, judge_model="gpt-4o-mini",
            )
        )
        session.add(
            EvaluationResult(
                response_id=r2.id, metric_name=MetricName.TOXICITY, status=EvaluationStatus.SUCCESS,
                score=0.3, passed=False, judge_model="gpt-4o-mini",
            )
        )
        await session.commit()
        return {"run_id": run.id, "model_id": model.id}


async def _seed_project_and_dataset_version(session_factory, owner_id: int) -> dict:
    async with session_factory() as session:
        project = Project(owner_id=owner_id, name="Trend Project")
        session.add(project)
        await session.flush()
        dataset = Dataset(project_id=project.id, name="D")
        session.add(dataset)
        await session.flush()
        dataset_version = DatasetVersion(dataset_id=dataset.id, version_number=1, sample_seed=1, sample_size=2)
        session.add(dataset_version)
        await session.flush()
        await session.commit()
        return {"project_id": project.id, "dataset_version_id": dataset_version.id}


async def test_trends_aggregates_latency_cost_and_pass_rate_per_run_model(
    test_client, session_factory, seeded_demo_user
):
    ids = await _seed_project_and_dataset_version(session_factory, seeded_demo_user.id)
    seeded = await _seed_completed_run_with_responses(
        session_factory, ids["project_id"], ids["dataset_version_id"]
    )

    response = await test_client.get("/dashboard/trends", params={"project_id": ids["project_id"]})
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    point = body[0]
    assert point["run_id"] == seeded["run_id"]
    assert point["model_id"] == seeded["model_id"]
    assert point["avg_latency_ms"] == 150.0
    assert point["avg_cost_usd"] == 0.015
    assert point["pass_rate"] == 0.5
    assert point["metric_averages"]["toxicity"] == 0.2


async def test_trends_excludes_regression_run(test_client, session_factory, seeded_demo_user):
    ids = await _seed_project_and_dataset_version(session_factory, seeded_demo_user.id)

    async with session_factory() as session:
        from app.models.prompt import PromptTemplate, PromptVersion

        model = LLMModel(provider="openai", name="gpt-4o-mini", display_name="GPT-4o mini")
        session.add(model)
        await session.flush()

        run = Run(
            project_id=ids["project_id"], dataset_version_id=ids["dataset_version_id"],
            status=RunStatus.COMPLETED,
        )
        session.add(run)
        await session.flush()
        session.add(
            Response(
                run_id=run.id, question_id=1, model_id=model.id, status=ResponseStatus.SUCCESS,
                latency_ms=100, cost_usd=0.01,
            )
        )
        await session.flush()

        template = PromptTemplate(project_id=ids["project_id"], name="T")
        session.add(template)
        await session.flush()
        version = PromptVersion(prompt_template_id=template.id, version_number=1, content="{question}")
        session.add(version)
        await session.flush()
        session.add(
            RegressionRun(
                prompt_version_id=version.id,
                dataset_version_id=ids["dataset_version_id"],
                model_id=model.id,
                run_id=run.id,
                status=RegressionStatus.COMPLETED,
            )
        )
        await session.commit()

    response = await test_client.get("/dashboard/trends", params={"project_id": ids["project_id"]})
    assert response.status_code == 200
    assert response.json() == []


async def test_trends_empty_project_returns_empty_list(test_client, session_factory, seeded_demo_user):
    ids = await _seed_project_and_dataset_version(session_factory, seeded_demo_user.id)
    response = await test_client.get("/dashboard/trends", params={"project_id": ids["project_id"]})
    assert response.status_code == 200
    assert response.json() == []
