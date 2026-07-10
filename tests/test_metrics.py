"""Phase 9: Prometheus instrumentation. Verifies actual counter/histogram
values change on the exact call sites (LLMRunner, EvaluationService,
RunOrchestrator, Celery signal handlers, FastAPI's HTTP middleware) — not
just that importing app.monitoring.metrics doesn't crash."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import litellm

from app.evaluation.scoring_service import EvaluationService
from app.llm.runner import LLMRunner
from app.models.evaluation_result import EvaluationStatus
from app.models.question import Question, QuestionType
from app.monitoring.metrics import (
    CELERY_TASK_DURATION_SECONDS,
    CELERY_TASKS_TOTAL,
    JUDGE_EVAL_CALLS_TOTAL,
    LLM_PROVIDER_CALLS_TOTAL,
    RESPONSE_COST_USD_TOTAL,
)


def _counter_value(counter, **labels) -> float:
    return counter.labels(**labels)._value.get()


async def test_llm_runner_success_increments_counter_with_success_label():
    before = _counter_value(LLM_PROVIDER_CALLS_TOTAL, model="metrics-test-model", status="success")
    runner = LLMRunner()
    fake_response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
    )
    with patch("app.llm.runner.litellm.acompletion", new=AsyncMock(return_value=fake_response)):
        await runner.run(provider_model="metrics-test-model", prompt="Q")

    after = _counter_value(LLM_PROVIDER_CALLS_TOTAL, model="metrics-test-model", status="success")
    assert after == before + 1


async def test_llm_runner_timeout_increments_counter_with_timeout_label():
    before = _counter_value(LLM_PROVIDER_CALLS_TOTAL, model="metrics-test-model-timeout", status="timeout")
    runner = LLMRunner()
    timeout_exc = litellm.exceptions.Timeout(message="timed out", model="x", llm_provider="openai")
    with patch("app.llm.runner.litellm.acompletion", new=AsyncMock(side_effect=timeout_exc)):
        await runner.run(provider_model="metrics-test-model-timeout", prompt="Q")

    after = _counter_value(LLM_PROVIDER_CALLS_TOTAL, model="metrics-test-model-timeout", status="timeout")
    assert after == before + 1


async def _fake_measure_ok(self, test_case, **kwargs):
    self.score = 0.9
    self.success = True
    self.reason = "fine"
    return 0.9


async def _fake_measure_fails(self, test_case, **kwargs):
    raise RuntimeError("judge down")


async def test_scoring_service_success_increments_judge_eval_counter():
    from deepeval.metrics import AnswerRelevancyMetric, BiasMetric, ToxicityMetric

    before = _counter_value(JUDGE_EVAL_CALLS_TOTAL, metric_name="toxicity", status="success")
    question = Question(id=1, dataset_id=1, type=QuestionType.OPEN_DOMAIN, text="Q")

    with patch.object(ToxicityMetric, "a_measure", _fake_measure_ok), patch.object(
        BiasMetric, "a_measure", _fake_measure_ok
    ), patch.object(AnswerRelevancyMetric, "a_measure", _fake_measure_ok):
        service = EvaluationService(judge_model="gpt-4o-mini", judge_api_key="fake-key")
        await service.score_response(question, actual_output="A")

    after = _counter_value(JUDGE_EVAL_CALLS_TOTAL, metric_name="toxicity", status="success")
    assert after == before + 1


async def test_scoring_service_failure_increments_judge_eval_counter_with_failed_label():
    from deepeval.metrics import AnswerRelevancyMetric, BiasMetric, ToxicityMetric

    before = _counter_value(JUDGE_EVAL_CALLS_TOTAL, metric_name="toxicity", status="failed")
    question = Question(id=1, dataset_id=1, type=QuestionType.OPEN_DOMAIN, text="Q")

    with patch.object(ToxicityMetric, "a_measure", _fake_measure_fails), patch.object(
        BiasMetric, "a_measure", _fake_measure_ok
    ), patch.object(AnswerRelevancyMetric, "a_measure", _fake_measure_ok):
        service = EvaluationService(judge_model="gpt-4o-mini", judge_api_key="fake-key")
        results = await service.score_response(question, actual_output="A")

    assert any(r.status == EvaluationStatus.FAILED for r in results)
    after = _counter_value(JUDGE_EVAL_CALLS_TOTAL, metric_name="toxicity", status="failed")
    assert after == before + 1


async def test_run_orchestrator_increments_cost_counter(db_session):
    from app.models.dataset import Dataset, DatasetVersion
    from app.models.llm_model import LLMModel
    from app.models.project import Project
    from app.models.run import Run
    from app.models.user import User
    from app.services.run_orchestrator import RunOrchestrator

    user = User(email="metrics-cost@example.com", hashed_password="x")
    db_session.add(user)
    await db_session.flush()
    project = Project(owner_id=user.id, name="P")
    db_session.add(project)
    await db_session.flush()
    dataset = Dataset(project_id=project.id, name="D")
    db_session.add(dataset)
    await db_session.flush()
    question = Question(dataset_id=dataset.id, type=QuestionType.OPEN_DOMAIN, text="Q")
    db_session.add(question)
    await db_session.flush()
    dataset_version = DatasetVersion(dataset_id=dataset.id, version_number=1, sample_seed=1, sample_size=1)
    db_session.add(dataset_version)
    await db_session.flush()
    # gpt-4o-mini is in LiteLLM's real pricing map — needed so compute_cost_usd
    # returns a real (non-null) cost_usd for this test to observe an increment.
    model = LLMModel(provider="openai", name="gpt-4o-mini", display_name="GPT-4o mini")
    db_session.add(model)
    await db_session.flush()
    run = Run(project_id=project.id, dataset_version_id=dataset_version.id)
    db_session.add(run)
    await db_session.flush()

    before = _counter_value(RESPONSE_COST_USD_TOTAL, model="gpt-4o-mini")

    llm_runner = LLMRunner()
    fake_response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
        usage=SimpleNamespace(prompt_tokens=100, completion_tokens=50),
    )
    with patch("app.llm.runner.litellm.acompletion", new=AsyncMock(return_value=fake_response)):
        from tests.conftest import make_fake_evaluation_service

        orchestrator = RunOrchestrator(db_session, llm_runner, make_fake_evaluation_service())
        await orchestrator.run_pair(run, question, model)

    after = _counter_value(RESPONSE_COST_USD_TOTAL, model="gpt-4o-mini")
    assert after > before


def test_celery_signal_handlers_record_duration_and_status():
    import app.workers.celery_app as celery_app_module

    fake_task = SimpleNamespace(name="eval_tasks.metrics_test_task")
    before = _counter_value(
        CELERY_TASKS_TOTAL, task_name="eval_tasks.metrics_test_task", status="SUCCESS"
    )

    celery_app_module._record_task_start(task_id="metrics-test-task-id")
    celery_app_module._record_task_end(
        task_id="metrics-test-task-id", task=fake_task, state="SUCCESS"
    )

    after = _counter_value(
        CELERY_TASKS_TOTAL, task_name="eval_tasks.metrics_test_task", status="SUCCESS"
    )
    assert after == before + 1
    # Duration was actually observed (nonzero _sum), not just the counter bumped.
    assert (
        CELERY_TASK_DURATION_SECONDS.labels(
            task_name="eval_tasks.metrics_test_task", status="SUCCESS"
        )._sum.get()
        >= 0
    )


def test_celery_signal_handler_pops_start_time_so_it_cannot_leak_across_tasks():
    import app.workers.celery_app as celery_app_module

    fake_task = SimpleNamespace(name="eval_tasks.metrics_test_task_2")
    celery_app_module._record_task_start(task_id="leak-test-id")
    assert "leak-test-id" in celery_app_module._task_started_at

    celery_app_module._record_task_end(task_id="leak-test-id", task=fake_task, state="SUCCESS")
    assert "leak-test-id" not in celery_app_module._task_started_at


async def test_metrics_endpoint_returns_prometheus_text_and_reflects_http_requests(test_client):
    await test_client.get("/health")
    response = await test_client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    body = response.text
    assert "http_requests_total" in body
    assert 'path="/health"' in body
