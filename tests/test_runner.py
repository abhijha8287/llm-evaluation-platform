"""Task T2 verify: success/timeout/error/isolation coverage for LLMRunner.

litellm.acompletion is mocked — these tests exercise our error-handling
branches (eng-review D3), not LiteLLM or real provider behavior."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import litellm
import openai
import pytest

from app.llm.runner import LLMRunner
from app.models.response import ResponseStatus


def _fake_success_response(content: str = "Paris") -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=12, completion_tokens=3),
    )


def _fake_http_response(status_code: int) -> httpx.Response:
    return httpx.Response(status_code=status_code, request=httpx.Request("POST", "https://example.com"))


async def test_provider_success():
    runner = LLMRunner()
    with patch("app.llm.runner.litellm.acompletion", new=AsyncMock(return_value=_fake_success_response())):
        result = await runner.run(provider_model="gpt-4o", prompt="What is the capital of France?")

    assert result.status == ResponseStatus.SUCCESS
    assert result.output == "Paris"
    assert result.prompt_tokens == 12
    assert result.completion_tokens == 3
    assert result.latency_ms is not None


async def test_provider_timeout():
    runner = LLMRunner()
    timeout_exc = litellm.exceptions.Timeout(message="timed out", model="gpt-4o", llm_provider="openai")
    with patch("app.llm.runner.litellm.acompletion", new=AsyncMock(side_effect=timeout_exc)):
        result = await runner.run(provider_model="gpt-4o", prompt="Slow question")

    assert result.status == ResponseStatus.TIMEOUT
    assert result.output is None
    assert "timed out" in result.error_message


async def test_provider_rate_limit_error_is_isolated_not_raised():
    """Regression guard for the litellm.exceptions.APIError vs
    openai.OpenAIError bug caught during Phase 2 review: RateLimitError is
    NOT a subclass of litellm.exceptions.APIError, so a naive `except
    litellm.exceptions.APIError` would let this propagate uncaught."""
    runner = LLMRunner()
    rate_limit_exc = openai.RateLimitError(
        message="rate limited", response=_fake_http_response(429), body=None
    )
    with patch("app.llm.runner.litellm.acompletion", new=AsyncMock(side_effect=rate_limit_exc)):
        result = await runner.run(provider_model="gpt-4o", prompt="Popular question")

    assert result.status == ResponseStatus.FAILED
    assert "rate limited" in result.error_message


async def test_provider_error_is_isolated_not_raised():
    runner = LLMRunner()
    auth_exc = openai.AuthenticationError(
        message="invalid api key", response=_fake_http_response(401), body=None
    )
    with patch("app.llm.runner.litellm.acompletion", new=AsyncMock(side_effect=auth_exc)):
        result = await runner.run(provider_model="gpt-4o", prompt="Any question")

    assert result.status == ResponseStatus.FAILED
    assert result.output is None


async def test_unexpected_error_still_propagates():
    """Only known provider/timeout errors are converted to a RunResult.
    A genuinely unexpected exception (e.g. a bug in our own code) should
    still raise — silently swallowing everything would hide real bugs."""
    runner = LLMRunner()
    with patch("app.llm.runner.litellm.acompletion", new=AsyncMock(side_effect=ValueError("bug"))):
        with pytest.raises(ValueError):
            await runner.run(provider_model="gpt-4o", prompt="Any question")


async def test_batch_isolation_one_failure_does_not_affect_others():
    """eng-review D3: one failed provider call never blocks or corrupts the
    others in the same batch."""
    runner = LLMRunner()
    responses = [
        openai.RateLimitError(message="rate limited", response=_fake_http_response(429), body=None),
        _fake_success_response("Berlin"),
        _fake_success_response("Rome"),
    ]

    async def fake_acompletion(**kwargs):
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    with patch("app.llm.runner.litellm.acompletion", new=AsyncMock(side_effect=fake_acompletion)):
        results = [await runner.run(provider_model="gpt-4o", prompt="Q") for _ in range(3)]

    assert results[0].status == ResponseStatus.FAILED
    assert results[1].status == ResponseStatus.SUCCESS
    assert results[1].output == "Berlin"
    assert results[2].status == ResponseStatus.SUCCESS
    assert results[2].output == "Rome"
