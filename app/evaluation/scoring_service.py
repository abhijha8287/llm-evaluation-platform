from dataclasses import dataclass

from deepeval.metrics import AnswerRelevancyMetric, BiasMetric, FaithfulnessMetric, ToxicityMetric
from deepeval.models.llms.openai_model import GPTModel
from deepeval.test_case import LLMTestCase

from app.models.evaluation_result import EvaluationStatus, MetricName
from app.models.question import Question, QuestionType

_METRIC_CLASSES = {
    MetricName.FAITHFULNESS: FaithfulnessMetric,
    MetricName.TOXICITY: ToxicityMetric,
    MetricName.BIAS: BiasMetric,
    MetricName.ANSWER_RELEVANCY: AnswerRelevancyMetric,
}

# eng-review Premise 3 / D9: Faithfulness requires retrieval_context and is
# RAG-only. Verified against the installed deepeval's actual
# FaithfulnessMetric._required_params — not assumed.
_RAG_ONLY_METRICS = frozenset({MetricName.FAITHFULNESS})


@dataclass
class MetricScore:
    """Pure result object, same pattern as app.llm.runner.RunResult — the
    service never touches the DB directly. The caller persists this into an
    EvaluationResult row."""

    metric_name: MetricName
    status: EvaluationStatus
    score: float | None = None
    reason: str | None = None
    error_message: str | None = None


def applicable_metrics(question_type: QuestionType) -> list[MetricName]:
    """eng-review Premise 3: not every metric applies to every question.
    RAG questions get the full suite; open-domain questions never attempt
    RAG-only metrics (they'd fail validation without retrieval_context)."""
    if question_type == QuestionType.RAG:
        return list(_METRIC_CLASSES.keys())
    return [name for name in _METRIC_CLASSES if name not in _RAG_ONLY_METRICS]


class EvaluationService:
    """eng-review D8: the ONE place that runs DeepEval metrics against a
    response. Used by both the live eval pipeline (Phase 3) and the
    regression re-scoring engine (Phase 7) — a fix or metric change here
    applies to both callers, they can never silently drift apart.

    eng-review D9: a judge-model failure for one metric never aborts the
    others — each metric call is isolated and recorded with its own status.

    Constraints/D6: judge model is explicit (GPTModel with an explicit
    api_key), never relying on OPENAI_API_KEY being present in the process
    environment — verified during Phase 3 that DeepEval's metric
    construction requires an API key eagerly (even before any network call),
    so an implicit env-var dependency would be a real footgun here.
    """

    def __init__(self, judge_model: str, judge_api_key: str):
        self._judge = GPTModel(model=judge_model, api_key=judge_api_key)
        self.judge_model_name = judge_model

    async def score_response(self, question: Question, actual_output: str) -> list[MetricScore]:
        test_case = LLMTestCase(
            input=question.text,
            actual_output=actual_output,
            retrieval_context=[question.retrieval_context] if question.retrieval_context else None,
        )

        results: list[MetricScore] = []
        for metric_name in applicable_metrics(question.type):
            metric = _METRIC_CLASSES[metric_name](model=self._judge)
            try:
                await metric.a_measure(test_case, _show_indicator=False)
            except Exception as exc:  # noqa: BLE001 - DeepEval doesn't
                # document a specific exception hierarchy for judge-call
                # failures (network errors, malformed judge output, etc.);
                # any failure here must degrade to EvaluationStatus.FAILED,
                # never propagate and abort the other metrics for this
                # response.
                results.append(
                    MetricScore(
                        metric_name=metric_name,
                        status=EvaluationStatus.FAILED,
                        error_message=str(exc),
                    )
                )
                continue
            results.append(
                MetricScore(
                    metric_name=metric_name,
                    status=EvaluationStatus.SUCCESS,
                    score=metric.score,
                    reason=metric.reason,
                )
            )
        return results
