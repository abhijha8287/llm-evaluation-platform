import time
from dataclasses import dataclass

import litellm
import openai

from app.models.response import ResponseStatus


@dataclass
class RunResult:
    """Pure result object — LLMRunner never touches the DB directly. The
    caller (a repository/service, or Phase 5's Celery task) is responsible
    for persisting this into a Response row. Keeps the runner unit-testable
    without a database and reusable outside a web-request context."""

    status: ResponseStatus
    output: str | None = None
    error_message: str | None = None
    latency_ms: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class LLMRunner:
    """Thin async wrapper around LiteLLM. eng-review D3: every call is
    isolated — a timeout or error here becomes a RunResult with the
    corresponding status, never an unhandled exception that could take down
    a batch of otherwise-successful provider calls."""

    def __init__(self, timeout_seconds: float = 30.0):
        self.timeout_seconds = timeout_seconds

    async def run(self, provider_model: str, prompt: str) -> RunResult:
        """provider_model is a LiteLLM-format model string, e.g. "gpt-4o",
        "claude-3-5-sonnet-20241022", "groq/llama-3.3-70b-versatile"."""
        started = time.monotonic()
        try:
            response = await litellm.acompletion(
                model=provider_model,
                messages=[{"role": "user", "content": prompt}],
                timeout=self.timeout_seconds,
            )
        except litellm.exceptions.Timeout as exc:
            return RunResult(
                status=ResponseStatus.TIMEOUT,
                error_message=str(exc),
                latency_ms=self._elapsed_ms(started),
            )
        except openai.OpenAIError as exc:
            # litellm.exceptions.RateLimitError, AuthenticationError,
            # APIConnectionError, ServiceUnavailableError, etc. are NOT
            # subclasses of litellm.exceptions.APIError despite the name —
            # verified against the installed litellm 1.83.7 exception MRO.
            # openai.OpenAIError (the real openai-python base, re-exported
            # by litellm's exception classes) is the actual shared base
            # covering all of them. Every one is isolated to this single
            # Response, never propagated to abort the rest of the batch.
            return RunResult(
                status=ResponseStatus.FAILED,
                error_message=str(exc),
                latency_ms=self._elapsed_ms(started),
            )

        latency_ms = self._elapsed_ms(started)
        choice = response.choices[0]
        usage = response.usage
        return RunResult(
            status=ResponseStatus.SUCCESS,
            output=choice.message.content,
            latency_ms=latency_ms,
            prompt_tokens=usage.prompt_tokens if usage else None,
            completion_tokens=usage.completion_tokens if usage else None,
        )

    @staticmethod
    def _elapsed_ms(started: float) -> int:
        return int((time.monotonic() - started) * 1000)
