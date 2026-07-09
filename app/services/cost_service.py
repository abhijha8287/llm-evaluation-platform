import litellm


def compute_cost_usd(
    provider_model: str, prompt_tokens: int | None, completion_tokens: int | None
) -> float | None:
    """eng-review D6: cost is sourced from LiteLLM's maintained pricing map
    (litellm.model_cost / litellm.cost_per_token), not a hand-maintained
    Costs table. Returns None — never 0.0 — when the model is missing from
    the map or token counts are unavailable; a missing price must not
    silently read as free. Verified against the installed litellm 1.83.7:
    an unresolvable model raises litellm.BadRequestError, not a quiet
    fallback, so this function converts that into an explicit None."""
    if prompt_tokens is None or completion_tokens is None:
        return None
    try:
        prompt_cost, completion_cost = litellm.cost_per_token(
            model=provider_model, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens
        )
    except Exception:
        return None
    return prompt_cost + completion_cost
