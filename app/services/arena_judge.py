import random
from dataclasses import dataclass
from typing import Literal

import litellm

Verdict = Literal["A", "B", "TIE"]

_COMPARISON_PROMPT = """You are comparing two AI assistant responses to the same question. \
Judge only by quality, accuracy, and helpfulness — not length or style. \
Respond with exactly one word: "A" if Response A is better, "B" if Response B is better, \
or "TIE" if they are equally good. Do not explain your reasoning.

Question: {question}

Response A: {response_a}

Response B: {response_b}

Verdict:"""


@dataclass
class ArenaJudgeResult:
    verdict: Verdict
    # True when the judge saw response_1 as "A" (i.e. no swap happened).
    # Exposed so callers can map the verdict back to the correct model id
    # without needing to know the judge's internal randomization.
    response_1_was_a: bool


class ArenaJudge:
    """office-hours design doc Phase 6: a fixed neutral LLM judge (the same
    model as the metric judge, app.core.config.judge_model) casts blind
    pairwise votes — "blind" means the judge is never told which model
    produced which response, and this class additionally randomizes A/B
    slot assignment per call so position bias (LLM judges are documented to
    favor whichever response they see first) doesn't systematically favor
    one caller-supplied ordering."""

    def __init__(self, judge_model: str):
        self.judge_model = judge_model

    async def judge(self, question: str, response_1: str, response_2: str) -> ArenaJudgeResult:
        response_1_was_a = random.random() < 0.5
        response_a, response_b = (
            (response_1, response_2) if response_1_was_a else (response_2, response_1)
        )

        prompt = _COMPARISON_PROMPT.format(question=question, response_a=response_a, response_b=response_b)
        completion = await litellm.acompletion(
            model=self.judge_model,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = (completion.choices[0].message.content or "").strip().upper()

        verdict: Verdict
        if raw.startswith("A"):
            verdict = "A"
        elif raw.startswith("B"):
            verdict = "B"
        else:
            verdict = "TIE"

        return ArenaJudgeResult(verdict=verdict, response_1_was_a=response_1_was_a)
