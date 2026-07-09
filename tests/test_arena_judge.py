"""ArenaJudge: verdict parsing, and position-bias randomization doesn't
break which original response the verdict maps back to."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services.arena_judge import ArenaJudge


def _fake_completion(content: str) -> SimpleNamespace:
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


async def test_judge_parses_a_verdict():
    judge = ArenaJudge(judge_model="gpt-4o-mini")
    with patch("app.services.arena_judge.random.random", return_value=0.0), patch(
        "app.services.arena_judge.litellm.acompletion", new=AsyncMock(return_value=_fake_completion("A"))
    ):
        result = await judge.judge("Q", "response one", "response two")
    assert result.verdict == "A"
    assert result.response_1_was_a is True


async def test_judge_parses_b_verdict():
    judge = ArenaJudge(judge_model="gpt-4o-mini")
    with patch("app.services.arena_judge.random.random", return_value=0.0), patch(
        "app.services.arena_judge.litellm.acompletion", new=AsyncMock(return_value=_fake_completion("B"))
    ):
        result = await judge.judge("Q", "response one", "response two")
    assert result.verdict == "B"


async def test_judge_parses_tie_verdict():
    judge = ArenaJudge(judge_model="gpt-4o-mini")
    with patch("app.services.arena_judge.litellm.acompletion", new=AsyncMock(return_value=_fake_completion("TIE"))):
        result = await judge.judge("Q", "response one", "response two")
    assert result.verdict == "TIE"


async def test_judge_treats_unparseable_output_as_tie():
    judge = ArenaJudge(judge_model="gpt-4o-mini")
    with patch(
        "app.services.arena_judge.litellm.acompletion",
        new=AsyncMock(return_value=_fake_completion("I cannot decide between these.")),
    ):
        result = await judge.judge("Q", "response one", "response two")
    assert result.verdict == "TIE"


async def test_judge_position_swap_prompt_still_places_response_1_correctly():
    """When random.random() >= 0.5, response_1 is placed in slot B — the
    prompt sent to the judge must reflect that swap, and response_1_was_a
    must correctly report False so callers can un-swap the verdict."""
    judge = ArenaJudge(judge_model="gpt-4o-mini")
    mock_completion = AsyncMock(return_value=_fake_completion("A"))
    with patch("app.services.arena_judge.random.random", return_value=0.9), patch(
        "app.services.arena_judge.litellm.acompletion", new=mock_completion
    ):
        result = await judge.judge("Q", "RESPONSE_ONE_TEXT", "RESPONSE_TWO_TEXT")

    assert result.response_1_was_a is False
    sent_prompt = mock_completion.call_args.kwargs["messages"][0]["content"]
    # response_2 ("RESPONSE_TWO_TEXT") should appear as "Response A" in the
    # prompt since response_1 was swapped to slot B.
    a_index = sent_prompt.index("Response A:")
    b_index = sent_prompt.index("Response B:")
    assert "RESPONSE_TWO_TEXT" in sent_prompt[a_index:b_index]
    assert "RESPONSE_ONE_TEXT" in sent_prompt[b_index:]
