"""Task T5 verify: open-domain vs RAG-style branch tests; judge-failure
exclusion test.

deepeval metric.a_measure() is patched per-class — these tests exercise our
branch logic (eng-review Premise 3, D8, D9), not real judge-model calls."""

from unittest.mock import patch

from deepeval.metrics import AnswerRelevancyMetric, BiasMetric, FaithfulnessMetric, ToxicityMetric

from app.evaluation.scoring_service import EvaluationService, applicable_metrics
from app.models.evaluation_result import EvaluationStatus, MetricName
from app.models.question import Question, QuestionType


def _question(question_type: QuestionType, retrieval_context: str | None = None) -> Question:
    return Question(
        id=1,
        dataset_id=1,
        type=question_type,
        text="What did the document say?",
        retrieval_context=retrieval_context,
    )


async def _fake_measure_ok(self, test_case, **kwargs):
    self.score = 0.9
    self.success = True
    self.reason = "looks fine"
    return 0.9


async def _fake_measure_below_threshold(self, test_case, **kwargs):
    self.score = 0.1
    self.success = False
    self.reason = "below threshold"
    return 0.1


async def _fake_measure_fails(self, test_case, **kwargs):
    raise RuntimeError("judge model timed out")


def test_applicable_metrics_open_domain_excludes_faithfulness():
    metrics = applicable_metrics(QuestionType.OPEN_DOMAIN)
    assert MetricName.FAITHFULNESS not in metrics
    assert set(metrics) == {MetricName.TOXICITY, MetricName.BIAS, MetricName.ANSWER_RELEVANCY}


def test_applicable_metrics_rag_includes_all_four():
    metrics = applicable_metrics(QuestionType.RAG)
    assert set(metrics) == {
        MetricName.FAITHFULNESS,
        MetricName.TOXICITY,
        MetricName.BIAS,
        MetricName.ANSWER_RELEVANCY,
    }


async def test_score_response_open_domain_never_attempts_faithfulness():
    question = _question(QuestionType.OPEN_DOMAIN)

    with patch.object(ToxicityMetric, "a_measure", _fake_measure_ok), patch.object(
        BiasMetric, "a_measure", _fake_measure_ok
    ), patch.object(AnswerRelevancyMetric, "a_measure", _fake_measure_ok), patch.object(
        FaithfulnessMetric, "a_measure", _fake_measure_fails
    ):
        service = EvaluationService(judge_model="gpt-4o-mini", judge_api_key="fake-key")
        results = await service.score_response(question, actual_output="An answer")

    metric_names = {r.metric_name for r in results}
    assert len(results) == 3
    assert MetricName.FAITHFULNESS not in metric_names
    assert all(r.status == EvaluationStatus.SUCCESS for r in results)
    assert all(r.score == 0.9 for r in results)
    assert all(r.passed is True for r in results)


async def test_score_response_captures_passed_false_below_threshold():
    """Phase 8: passed is captured directly from DeepEval's metric.success,
    not derived from score alone — this confirms the wiring surfaces False
    correctly, not just the "everything passes" happy path."""
    question = _question(QuestionType.OPEN_DOMAIN)

    with patch.object(ToxicityMetric, "a_measure", _fake_measure_below_threshold), patch.object(
        BiasMetric, "a_measure", _fake_measure_ok
    ), patch.object(AnswerRelevancyMetric, "a_measure", _fake_measure_ok):
        service = EvaluationService(judge_model="gpt-4o-mini", judge_api_key="fake-key")
        results = await service.score_response(question, actual_output="An answer")

    by_name = {r.metric_name: r for r in results}
    assert by_name[MetricName.TOXICITY].passed is False
    assert by_name[MetricName.TOXICITY].score == 0.1
    assert by_name[MetricName.BIAS].passed is True


async def test_score_response_rag_includes_faithfulness():
    question = _question(QuestionType.RAG, retrieval_context="Refunds accepted within 30 days.")

    with patch.object(ToxicityMetric, "a_measure", _fake_measure_ok), patch.object(
        BiasMetric, "a_measure", _fake_measure_ok
    ), patch.object(AnswerRelevancyMetric, "a_measure", _fake_measure_ok), patch.object(
        FaithfulnessMetric, "a_measure", _fake_measure_ok
    ):
        service = EvaluationService(judge_model="gpt-4o-mini", judge_api_key="fake-key")
        results = await service.score_response(question, actual_output="30 days")

    metric_names = {r.metric_name for r in results}
    assert len(results) == 4
    assert MetricName.FAITHFULNESS in metric_names


async def test_judge_failure_on_one_metric_does_not_abort_the_others():
    """eng-review D9: a failed judge call for one metric is isolated —
    recorded as EvaluationStatus.FAILED, never propagated, never blocking
    the other metrics for the same response."""
    question = _question(QuestionType.RAG, retrieval_context="Refunds accepted within 30 days.")

    with patch.object(ToxicityMetric, "a_measure", _fake_measure_fails), patch.object(
        BiasMetric, "a_measure", _fake_measure_ok
    ), patch.object(AnswerRelevancyMetric, "a_measure", _fake_measure_ok), patch.object(
        FaithfulnessMetric, "a_measure", _fake_measure_ok
    ):
        service = EvaluationService(judge_model="gpt-4o-mini", judge_api_key="fake-key")
        results = await service.score_response(question, actual_output="30 days")

    assert len(results) == 4
    by_name = {r.metric_name: r for r in results}
    assert by_name[MetricName.TOXICITY].status == EvaluationStatus.FAILED
    assert by_name[MetricName.TOXICITY].score is None
    assert "judge model timed out" in by_name[MetricName.TOXICITY].error_message
    assert by_name[MetricName.BIAS].status == EvaluationStatus.SUCCESS
    assert by_name[MetricName.FAITHFULNESS].status == EvaluationStatus.SUCCESS
    assert by_name[MetricName.ANSWER_RELEVANCY].status == EvaluationStatus.SUCCESS


def test_construction_with_empty_api_key_does_not_raise():
    """TODOS.md item 4 regression guard: constructing EvaluationService must
    never raise, regardless of judge_api_key validity — judge-model
    construction is deferred to the first score_response call so a bad key
    degrades to per-metric FAILED results instead of crashing the caller
    (eval_tasks.py's run_pair_task) before LLMRunner.run() ever executes."""
    service = EvaluationService(judge_model="gpt-4o-mini", judge_api_key="")
    assert service.judge_model_name == "gpt-4o-mini"


async def test_empty_api_key_degrades_every_applicable_metric_to_failed_not_a_crash():
    """The actual bug found in Phase 9's live verification: an empty judge
    key used to raise DeepEvalError out of EvaluationService.__init__,
    which — because eval_tasks.py constructed EvaluationService before ever
    calling LLMRunner.run() — crashed the whole Celery task and its chord
    before any provider call happened. Now the same bad key is caught here,
    per metric, exactly like any other judge-call failure."""
    question = _question(QuestionType.RAG, retrieval_context="Refunds accepted within 30 days.")
    service = EvaluationService(judge_model="gpt-4o-mini", judge_api_key="")

    results = await service.score_response(question, actual_output="30 days")

    assert len(results) == 4
    assert all(r.status == EvaluationStatus.FAILED for r in results)
    assert all(r.score is None for r in results)
    assert all(r.error_message for r in results)


async def test_judge_construction_failure_is_cached_not_retried_per_metric():
    """Construction is attempted at most once per EvaluationService instance
    — a persistently bad key must not retry GPTModel construction once per
    applicable metric (4x for a RAG question)."""
    question = _question(QuestionType.RAG, retrieval_context="Refunds accepted within 30 days.")
    service = EvaluationService(judge_model="gpt-4o-mini", judge_api_key="")

    with patch(
        "app.evaluation.scoring_service.GPTModel", side_effect=RuntimeError("construction attempted")
    ) as mock_gptmodel:
        results = await service.score_response(question, actual_output="30 days")

    assert len(results) == 4
    mock_gptmodel.assert_called_once()
