import time
from dataclasses import dataclass

from deepeval.metrics import AnswerRelevancyMetric, BiasMetric, FaithfulnessMetric, ToxicityMetric
from deepeval.models.llms.openai_model import GPTModel
from deepeval.test_case import LLMTestCase

from app.models.evaluation_result import EvaluationStatus, MetricName
from app.models.question import Question, QuestionType
from app.monitoring.metrics import JUDGE_EVAL_CALLS_TOTAL, JUDGE_EVAL_DURATION_SECONDS

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
    passed: bool | None = None
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
    environment.

    TODOS.md item 4 fix: GPTModel construction is lazy (deferred to the
    first score_response call), not eager in __init__. Verified during
    Phase 3 that DeepEval's GPTModel construction requires an API key
    eagerly (raises immediately, before any network call, if the key is
    empty/invalid) — Phase 9's live verification then found that eager
    construction in __init__ meant a bad judge key crashed the whole caller
    (eval_tasks.py's run_pair_task) before LLMRunner.run() ever executed,
    bypassing D3's provider-call isolation entirely: no response was ever
    generated, let alone recorded as FAILED. Deferring construction into
    the per-metric try/except below means a construction failure now
    degrades to EvaluationStatus.FAILED for every applicable metric — the
    same shape as any other judge-call failure — instead of aborting the
    task. Construction is attempted at most once per EvaluationService
    instance (success or failure both cached) so a persistently bad key
    doesn't retry GPTModel construction once per metric.
    """

    def __init__(self, judge_model: str, judge_api_key: str):
        self.judge_model_name = judge_model
        self._judge_api_key = judge_api_key
        self._judge: GPTModel | None = None
        self._judge_construction_error: Exception | None = None

    def _get_judge(self) -> GPTModel:
        if self._judge is None and self._judge_construction_error is None:
            try:
                self._judge = GPTModel(model=self.judge_model_name, api_key=self._judge_api_key)
            except Exception as exc:  # noqa: BLE001 - see class docstring;
                # must degrade to a per-metric FAILED result, never propagate.
                self._judge_construction_error = exc
        if self._judge_construction_error is not None:
            raise self._judge_construction_error
        assert self._judge is not None
        return self._judge

    async def score_response(self, question: Question, actual_output: str) -> list[MetricScore]:
        test_case = LLMTestCase(
            input=question.text,
            actual_output=actual_output,
            retrieval_context=[question.retrieval_context] if question.retrieval_context else None,
        )

        results: list[MetricScore] = []
        for metric_name in applicable_metrics(question.type):
            started = time.monotonic()
            try:
                judge = self._get_judge()
                metric = _METRIC_CLASSES[metric_name](model=judge)
                await metric.a_measure(test_case, _show_indicator=False)
            except Exception as exc:  # noqa: BLE001 - DeepEval doesn't
                # document a specific exception hierarchy for judge-call
                # failures (network errors, malformed judge output, judge
                # construction failures, etc.); any failure here must
                # degrade to EvaluationStatus.FAILED, never propagate and
                # abort the other metrics for this response.
                self._record_metrics(metric_name, EvaluationStatus.FAILED, started)
                results.append(
                    MetricScore(
                        metric_name=metric_name,
                        status=EvaluationStatus.FAILED,
                        error_message=str(exc),
                    )
                )
                continue
            self._record_metrics(metric_name, EvaluationStatus.SUCCESS, started)
            results.append(
                MetricScore(
                    metric_name=metric_name,
                    status=EvaluationStatus.SUCCESS,
                    score=metric.score,
                    # Captured directly from DeepEval, not reimplemented —
                    # verified (Phase 8) that pass/fail direction differs by
                    # metric: Faithfulness/AnswerRelevancy pass when score >=
                    # threshold (higher is better), Toxicity/Bias pass when
                    # score <= threshold (lower is better). Recomputing this
                    # ourselves would risk getting a direction wrong.
                    passed=metric.success,
                    reason=metric.reason,
                )
            )
        return results

    @staticmethod
    def _record_metrics(metric_name: MetricName, status: EvaluationStatus, started: float) -> None:
        elapsed_seconds = time.monotonic() - started
        JUDGE_EVAL_CALLS_TOTAL.labels(metric_name=metric_name.value, status=status.value).inc()
        JUDGE_EVAL_DURATION_SECONDS.labels(metric_name=metric_name.value, status=status.value).observe(
            elapsed_seconds
        )
